"""Phase 1 against the real stores: dedup on pgvector, orchestrator state on Redis.

Everything external to the two databases stays mocked — the LLM is a recorded
fixture, Jira is a scripted transport (§8.6).
"""

from __future__ import annotations

from tests.support import classification_entry, embedding_entry, recorded_llm, score_entry

from firsthand.connectors.jira import JiraConnector, RecordedJiraTransport, search_response
from firsthand.contracts import Evidence
from firsthand.orchestrator.dedup import index_request, nearest, pick_duplicate
from firsthand.orchestrator.loop import Orchestrator, OrchestratorDeps
from firsthand.orchestrator.scoring import scoring_user_prompt
from firsthand.orchestrator.tools import ToolRegistry
from firsthand.storage import PostgresVectorStore, RedisStateStore

_A = [1.0, 0.0, 0.0]
_NEAR = [0.999, 0.0447, 0.0]  # ~0.999 cosine with _A
_FAR = [0.0, 1.0, 0.0]

_TEXT = "checkout returns 500 on submit\nsteps: pay\nexpected: ok\nactual: 500"


async def test_index_then_nearest_finds_the_duplicate_on_real_pgvector(
    vector_store: PostgresVectorStore,
) -> None:
    llm = recorded_llm(
        embeddings={
            **embedding_entry("first request about checkout latency", _A),
            **embedding_entry("second request, basically the same latency issue", _NEAR),
            **embedding_entry("an unrelated request about dark mode", _FAR),
        }
    )
    await index_request(
        llm,
        vector_store,
        request_id="req-a",
        text="first request about checkout latency",
        metadata={"ticket_id": "PAY-1"},
    )
    await index_request(
        llm,
        vector_store,
        request_id="req-c",
        text="an unrelated request about dark mode",
        metadata={"ticket_id": "UX-9"},
    )

    matches = await nearest(
        llm, vector_store, "second request, basically the same latency issue", exclude_id="req-b"
    )
    assert matches[0].id == "req-a"
    dup = pick_duplicate(matches)
    assert dup is not None
    assert dup.ticket_id == "PAY-1"
    assert dup.similarity > 0.99


async def test_orchestrator_round_trips_state_through_real_redis(
    vector_store: PostgresVectorStore,
    state_store: RedisStateStore,
) -> None:
    transport = RecordedJiraTransport(
        {
            "GET /rest/api/3/search": [search_response(("PAY-2", "checkout 500", "Open"))],
            "POST /rest/api/3/issue": [{"key": "FH-1"}],
        }
    )
    search_ev = [
        Evidence(
            source="jira",
            ref="PAY-2",
            snippet="checkout 500 [Open]",
            retrieved_by="search_jira",
        )
    ]
    llm = recorded_llm(
        completions={
            **classification_entry(
                _TEXT,
                {
                    "category": "bug",
                    "extracted_fields": {
                        "steps_to_reproduce": "pay",
                        "expected_behavior": "ok",
                        "actual_behavior": "500",
                    },
                    "summary": "Checkout 500 on submit",
                },
            ),
            **score_entry(
                scoring_user_prompt(_TEXT, search_ev, None),
                {"impact": 6, "effort": 3, "urgency": "med", "confidence": 0.8, "rationale": "r"},
            ),
        },
        embeddings=embedding_entry(_TEXT, _A),
    )
    deps = OrchestratorDeps(
        llm=llm,
        vector_store=vector_store,
        state_store=state_store,
        tools=ToolRegistry(jira=JiraConnector(transport, browse_base_url="https://jira.test")),
        project_key="FH",
    )
    reply = await Orchestrator(deps).handle(surface="web", session_id="it-1", text=_TEXT)
    assert reply.draft.status == "filed"

    # a different Orchestrator instance reads the same draft back from Redis
    reloaded = await state_store.get("it-1")
    assert reloaded is not None
    assert reloaded.ticket is not None
    assert reloaded.ticket.id == "FH-1"
