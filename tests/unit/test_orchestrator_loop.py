"""The agent loop end to end, offline: classify -> clarify -> investigate -> score -> route.

Every LLM call is a recorded fixture; Jira is a scripted transport; the stores
are in-memory. Both caps (§2 clarification rounds, §7 tool calls) are asserted.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support import (
    InMemoryStateStore,
    InMemoryVectorStore,
    classification_entry,
    embedding_entry,
    recorded_llm,
    score_entry,
)

from firsthand.connectors.jira import JiraConnector, RecordedJiraTransport, search_response
from firsthand.connectors.jira.transport import JiraTransportError
from firsthand.contracts import Evidence, IssueDraft
from firsthand.orchestrator.loop import Orchestrator, OrchestratorDeps
from firsthand.orchestrator.scoring import scoring_user_prompt
from firsthand.orchestrator.tools import ToolRegistry

VEC = [1.0, 0.0, 0.0]

# A complete bug report — no clarification round needed.
COMPLETE = (
    "checkout fails on submit\n"
    "steps: open cart, click pay\n"
    "expected: order confirmed\n"
    "actual: 500 error"
)


def _classification(text: str, **fields: str) -> dict[str, Any]:
    return classification_entry(
        text,
        {
            "category": "bug",
            "extracted_fields": {
                "steps_to_reproduce": "open cart, click pay",
                "expected_behavior": "order confirmed",
                "actual_behavior": "500 error",
                **fields,
            },
            "summary": "Checkout submit returns a 500",
        },
    )


def _score(text: str, evidence: list[Evidence], dup: Any, **over: Any) -> dict[str, Any]:
    payload = {"impact": 6.0, "effort": 3.0, "urgency": "med", "confidence": 0.8, "rationale": "r"}
    payload.update(over)
    return score_entry(scoring_user_prompt(text, evidence, dup), payload)


def _jira(**scripts: list[dict[str, Any]]) -> RecordedJiraTransport:
    return RecordedJiraTransport(dict(scripts))


def _deps(
    llm: Any, transport: RecordedJiraTransport, store: InMemoryVectorStore
) -> OrchestratorDeps:
    return OrchestratorDeps(
        llm=llm,
        vector_store=store,
        state_store=InMemoryStateStore(),
        tools=ToolRegistry(jira=JiraConnector(transport, browse_base_url="https://jira.test")),
        project_key="FH",
    )


async def test_incomplete_report_triggers_one_clarifying_question() -> None:
    text = "the export button does nothing"
    llm = recorded_llm(
        completions=classification_entry(
            text,
            # no summary returned this turn — exercises the "skip summary" branch
            {
                "category": "bug",
                "extracted_fields": {"actual_behavior": "nothing happens"},
                "summary": "",
            },
        )
    )
    deps = _deps(llm, _jira(), InMemoryVectorStore())
    reply = await Orchestrator(deps).handle(surface="web", session_id="s1", text=text)

    assert reply.done is False
    assert reply.draft.status == "gathering_info"
    assert "steps to reproduce" in reply.message
    # persisted for the next turn, which may land on another instance (§8.3)
    assert isinstance(deps.state_store, InMemoryStateStore)
    assert "s1" in deps.state_store.blobs


async def test_complete_report_with_no_neighbours_is_auto_filed() -> None:
    store = InMemoryVectorStore()
    transport = _jira(
        **{
            "GET /rest/api/3/search": [search_response(("PAY-100", "checkout 500", "Open"))],
            "POST /rest/api/3/issue": [{"key": "FH-1"}],
        }
    )
    search_ev = [
        Evidence(
            source="jira", ref="PAY-100", snippet="checkout 500 [Open]", retrieved_by="search_jira"
        )
    ]
    llm = recorded_llm(
        completions={
            **_classification(COMPLETE),
            **_score(COMPLETE, search_ev, None),
        },
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = _deps(llm, transport, store)
    reply = await Orchestrator(deps).handle(surface="web", session_id="s2", text=COMPLETE)

    assert reply.done is True
    assert reply.draft.status == "filed"
    assert reply.draft.summary == "Checkout submit returns a 500"  # moved onto its own field
    assert reply.draft.routing is not None and reply.draft.routing.decision == "auto_file"
    assert reply.draft.ticket is not None
    assert reply.draft.ticket.id == "FH-1"
    assert reply.draft.ticket.url == "https://jira.test/browse/FH-1"
    assert reply.message == "Filed FH-1."
    # the new request was indexed for future dedup
    assert store.rows["s2"][1]["ticket_id"] == "FH-1"
    assert deps.tools.calls_made == 2  # one search, one create


async def test_a_complete_report_without_a_classifier_summary_still_files() -> None:
    """No summary this turn: the dedup query and ticket title fall back to the text."""
    store = InMemoryVectorStore()
    text = (
        "orders stay in pending forever\n"
        "steps: place an order\n"
        "expected: it moves to paid\n"
        "actual: it never leaves pending"
    )
    transport = _jira(
        **{
            "GET /rest/api/3/search": [{"issues": []}],
            "POST /rest/api/3/issue": [{"key": "FH-9"}],
        }
    )
    llm = recorded_llm(
        completions={
            **classification_entry(
                text,
                {
                    "category": "bug",
                    "extracted_fields": {
                        "steps_to_reproduce": "place an order",
                        "expected_behavior": "it moves to paid",
                        "actual_behavior": "it never leaves pending",
                    },
                    "summary": "",
                },
            ),
            **_score(text, [], None),
        },
        embeddings=embedding_entry(text, VEC),
    )
    deps = _deps(llm, transport, store)
    reply = await Orchestrator(deps).handle(surface="web", session_id="s9", text=text)

    assert reply.draft.status == "filed"
    assert reply.draft.summary == ""
    assert reply.draft.ticket is not None and reply.draft.ticket.id == "FH-9"


async def test_a_close_neighbour_is_filed_and_linked_as_a_duplicate() -> None:
    store = InMemoryVectorStore()
    await store.upsert("s-prior", VEC, {"ticket_id": "PAY-7"})
    transport = _jira(
        **{
            "GET /rest/api/3/search": [{"issues": []}],
            "POST /rest/api/3/issue": [{"key": "FH-2"}],
            "POST /rest/api/3/issueLink": [{}],
        }
    )
    llm = recorded_llm(
        completions={
            **_classification(COMPLETE),
            **_score(COMPLETE, [], _DupLike("PAY-7")),
        },
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = _deps(llm, transport, store)
    reply = await Orchestrator(deps).handle(surface="web", session_id="s3", text=COMPLETE)

    assert reply.draft.duplicate_of is not None
    assert reply.draft.duplicate_of.ticket_id == "PAY-7"
    assert reply.draft.status == "filed"
    assert "linked it to PAY-7" in reply.message
    assert deps.tools.calls_made == 3  # search + create + link


async def test_low_confidence_score_escalates_without_touching_jira_mutations() -> None:
    store = InMemoryVectorStore()
    transport = _jira(**{"GET /rest/api/3/search": [{"issues": []}]})
    llm = recorded_llm(
        completions={
            **_classification(COMPLETE),
            **_score(COMPLETE, [], None, confidence=0.2),
        },
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = _deps(llm, transport, store)
    reply = await Orchestrator(deps).handle(surface="web", session_id="s4", text=COMPLETE)

    assert reply.draft.status == "escalated"
    assert "Sent to a human" in reply.message
    assert deps.tools.calls_made == 1  # search only


async def test_the_clarification_cap_forces_a_decision_after_three_rounds() -> None:
    store = InMemoryVectorStore()
    state = InMemoryStateStore()
    transport = _jira(
        **{
            "GET /rest/api/3/search": [{"issues": []}],
            "POST /rest/api/3/issue": [{"key": "FH-9"}],
        }
    )
    # The model never manages to extract expected_behavior, so a field stays missing.
    thin = "app is broken"
    convo_texts = [
        thin,
        f"{thin}\nstill broken",
        f"{thin}\nstill broken\nreally broken",
        f"{thin}\nstill broken\nreally broken\nplease help",
    ]
    completions: dict[str, Any] = {}
    for text in convo_texts:
        completions.update(
            classification_entry(
                text,
                {
                    "category": "bug",
                    "extracted_fields": {"steps_to_reproduce": "launch it"},
                    "summary": "App broken",
                },
            )
        )
    completions.update(_score(convo_texts[-1], [], None))
    llm = recorded_llm(completions=completions, embeddings=embedding_entry(convo_texts[-1], VEC))

    deps = OrchestratorDeps(
        llm=llm,
        vector_store=store,
        state_store=state,
        tools=ToolRegistry(jira=JiraConnector(transport, browse_base_url="https://jira.test")),
    )
    orch = Orchestrator(deps)

    r1 = await orch.handle(surface="web", session_id="s5", text=thin)
    r2 = await orch.handle(surface="web", session_id="s5", text="still broken")
    r3 = await orch.handle(surface="web", session_id="s5", text="really broken")
    assert [r1.draft.status, r2.draft.status, r3.draft.status] == ["gathering_info"] * 3
    assert r3.draft.round == 2

    r4 = await orch.handle(surface="web", session_id="s5", text="please help")
    assert r4.draft.round == 3
    assert r4.draft.may_ask_again is False
    assert r4.draft.status == "escalated"
    assert "still missing expected_behavior" in (
        r4.draft.routing.reason if r4.draft.routing else ""
    )


async def test_state_is_picked_up_by_a_fresh_orchestrator_instance() -> None:
    store = InMemoryVectorStore()
    state = InMemoryStateStore()
    transport = _jira(
        **{
            "GET /rest/api/3/search": [{"issues": []}, {"issues": []}],
            "POST /rest/api/3/issue": [{"key": "FH-3"}],
        }
    )
    first_text = "the export button does nothing"
    full_text = f"{first_text}\nsteps: click export; expected: a file; actual: nothing"
    llm = recorded_llm(
        completions={
            **classification_entry(
                first_text,
                {
                    "category": "bug",
                    "extracted_fields": {"actual_behavior": "nothing"},
                    "summary": "Export inert",
                },
            ),
            **classification_entry(
                full_text,
                {
                    "category": "bug",
                    "extracted_fields": {
                        "steps_to_reproduce": "click export",
                        "expected_behavior": "a file downloads",
                        "actual_behavior": "nothing",
                    },
                    "summary": "Export inert",
                },
            ),
            **_score(full_text, [], None),
        },
        embeddings=embedding_entry(full_text, VEC),
    )

    def _make() -> Orchestrator:
        return Orchestrator(
            OrchestratorDeps(
                llm=llm,
                vector_store=store,
                state_store=state,
                tools=ToolRegistry(
                    jira=JiraConnector(transport, browse_base_url="https://jira.test")
                ),
            )
        )

    r1 = await _make().handle(surface="web", session_id="s6", text=first_text)
    assert r1.draft.status == "gathering_info"

    r2 = await _make().handle(
        surface="web",
        session_id="s6",
        text="steps: click export; expected: a file; actual: nothing",
    )
    assert r2.draft.status == "filed"
    assert r2.draft.ticket is not None and r2.draft.ticket.id == "FH-3"


async def test_a_message_after_filing_is_a_no_op_report() -> None:
    store = InMemoryVectorStore()
    state = InMemoryStateStore()
    filed = IssueDraft.model_validate_json(_filed_draft_json())
    await state.set("s7", filed)
    deps = OrchestratorDeps(
        llm=recorded_llm(),
        vector_store=store,
        state_store=state,
        tools=ToolRegistry(jira=JiraConnector(_jira(), browse_base_url="https://j")),
    )
    reply = await Orchestrator(deps).handle(surface="web", session_id="s7", text="any update?")
    assert reply.done is True
    assert reply.message == "This request is already filed."


async def test_raw_pii_never_reaches_the_model_only_the_redacted_copy_does() -> None:
    store = InMemoryVectorStore()
    raw = "checkout 500 for jane@example.com\nsteps: pay\nexpected: ok\nactual: 500"
    redacted = "checkout 500 for <EMAIL>\nsteps: pay\nexpected: ok\nactual: 500"
    transport = _jira(
        **{"GET /rest/api/3/search": [{"issues": []}], "POST /rest/api/3/issue": [{"key": "FH-8"}]}
    )
    llm = recorded_llm(
        completions={
            **classification_entry(
                redacted,
                {
                    "category": "bug",
                    "extracted_fields": {
                        "steps_to_reproduce": "pay",
                        "expected_behavior": "ok",
                        "actual_behavior": "500",
                    },
                    "summary": "Checkout 500",
                },
            ),
            **_score(redacted, [], None),
        },
        embeddings=embedding_entry(redacted, VEC),
    )
    deps = _deps(llm, transport, store)
    reply = await Orchestrator(deps).handle(surface="web", session_id="s8", text=raw)

    assert reply.draft.raw_text == raw  # kept for the human reviewer
    assert "jane@example.com" not in reply.draft.redacted_text
    for _schema, system, user in llm.structured_calls:
        assert "jane@example.com" not in system
        assert "jane@example.com" not in user
    for batch in llm.embed_calls:
        assert all("jane@example.com" not in item for item in batch)


async def test_a_failed_jira_search_is_logged_and_the_loop_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _SearchDown:
        async def get(self, *a: object, **k: object) -> dict[str, Any]:
            raise JiraTransportError("down")

        async def post(self, *a: object, **k: object) -> dict[str, Any]:
            return {"key": "FH-11"}

    store = InMemoryVectorStore()
    llm = recorded_llm(
        completions={**_classification(COMPLETE), **_score(COMPLETE, [], None)},
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = OrchestratorDeps(
        llm=llm,
        vector_store=store,
        state_store=InMemoryStateStore(),
        tools=ToolRegistry(jira=JiraConnector(_SearchDown(), browse_base_url="https://j")),
    )
    with caplog.at_level("WARNING"):
        reply = await Orchestrator(deps).handle(surface="web", session_id="s9", text=COMPLETE)
    assert reply.draft.status == "filed"
    assert all(e.retrieved_by != "search_jira" for e in reply.draft.evidence)
    assert "search_jira failed" in caplog.text


async def test_a_failed_create_ticket_escalates_with_a_message() -> None:
    class _Boom:
        async def get(self, *a: object, **k: object) -> dict[str, Any]:
            return {"issues": []}

        async def post(self, *a: object, **k: object) -> dict[str, Any]:
            raise JiraTransportError("nope")

    store = InMemoryVectorStore()
    llm = recorded_llm(
        completions={**_classification(COMPLETE), **_score(COMPLETE, [], None)},
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = OrchestratorDeps(
        llm=llm,
        vector_store=store,
        state_store=InMemoryStateStore(),
        tools=ToolRegistry(jira=JiraConnector(_Boom(), browse_base_url="https://j")),
    )
    reply = await Orchestrator(deps).handle(surface="web", session_id="s10", text=COMPLETE)
    assert reply.draft.status == "escalated"
    assert "Could not file the ticket" in reply.message


async def test_a_duplicate_that_files_but_fails_to_link_reports_the_partial_result() -> None:
    class _LinkDown:
        async def get(self, *a: object, **k: object) -> dict[str, Any]:
            return {"issues": []}

        async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            if path.endswith("issueLink"):
                raise JiraTransportError("link 400")
            return {"key": "FH-5"}

    store = InMemoryVectorStore()
    await store.upsert("s-prior", VEC, {"ticket_id": "PAY-7"})
    llm = recorded_llm(
        completions={**_classification(COMPLETE), **_score(COMPLETE, [], _DupLike("PAY-7"))},
        embeddings=embedding_entry(COMPLETE, VEC),
    )
    deps = OrchestratorDeps(
        llm=llm,
        vector_store=store,
        state_store=InMemoryStateStore(),
        tools=ToolRegistry(jira=JiraConnector(_LinkDown(), browse_base_url="https://j")),
    )
    reply = await Orchestrator(deps).handle(surface="web", session_id="s11", text=COMPLETE)
    assert reply.draft.status == "filed"
    assert reply.draft.ticket is not None and reply.draft.ticket.id == "FH-5"
    assert "linking it to PAY-7 failed" in reply.message


class _DupLike:
    """Minimal stand-in with the two attrs scoring_user_prompt reads."""

    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        self.similarity = 1.0


def _filed_draft_json() -> str:
    from firsthand.contracts import Conversation, Score, Ticket

    draft = IssueDraft(
        conversation=Conversation(surface="web", session_id="s7"),
        raw_text="done",
        redacted_text="done",
        category="bug",
        status="filed",
        score=Score(impact=1, effort=1, urgency="low", confidence=0.9),
        ticket=Ticket(id="FH-7", url="https://j/browse/FH-7", status="To Do"),
    )
    return draft.model_dump_json()
