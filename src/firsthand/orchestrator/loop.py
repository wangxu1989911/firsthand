"""The agent loop: classify -> clarify -> investigate -> score -> route -> act.

One inbound message drives one pass. All state lives on the ``IssueDraft`` and
round-trips through the ``StateStore`` — a follow-up reply may land on a
different instance than the one that asked the question (§8.3). Both caps are
respected: at most ``MAX_CLARIFICATION_ROUNDS`` clarifying questions across the
conversation (§2), and at most ``MAX_TOOL_CALLS`` tool calls per pass (§7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from firsthand.contracts import (
    Conversation,
    IssueDraft,
    Surface,
    Ticket,
)
from firsthand.llm.base import LLMClient
from firsthand.orchestrator.classify import classify, next_question
from firsthand.orchestrator.dedup import index_request, nearest, pick_duplicate
from firsthand.orchestrator.fields import required_fields_for
from firsthand.orchestrator.redaction import redact
from firsthand.orchestrator.routing import decide_routing
from firsthand.orchestrator.scoring import score_draft
from firsthand.orchestrator.tools import ToolRegistry
from firsthand.storage.base import StateStore, VectorStore

logger = logging.getLogger(__name__)

#: Statuses from which a new inbound message does nothing but report state.
_TERMINAL = frozenset({"filed", "closed"})

#: Jira free-text search is not helped by a wall of text.
_MAX_QUERY_CHARS = 300


@dataclass(frozen=True)
class OrchestratorReply:
    """What the caller (a web or Slack adapter, Phase 2) shows the reporter."""

    draft: IssueDraft
    message: str
    done: bool


@dataclass
class OrchestratorDeps:
    """Everything the loop needs, all injectable so tests stay offline."""

    llm: LLMClient
    vector_store: VectorStore
    state_store: StateStore
    tools: ToolRegistry
    project_key: str = "FH"
    state_ttl_seconds: int | None = field(default=None)


class Orchestrator:
    """Stateless across calls — every fact it needs comes from the ``StateStore``."""

    def __init__(self, deps: OrchestratorDeps) -> None:
        self._d = deps

    async def _save(self, draft: IssueDraft) -> None:
        await self._d.state_store.set(
            draft.conversation.session_id, draft, self._d.state_ttl_seconds
        )

    async def handle(self, *, surface: Surface, session_id: str, text: str) -> OrchestratorReply:
        """Advance one conversation by one message."""
        draft = await self._d.state_store.get(session_id)
        if draft is None:
            draft = IssueDraft(
                conversation=Conversation(surface=surface, session_id=session_id),
                raw_text=text,
            )
        else:
            draft.raw_text = f"{draft.raw_text}\n{text}"
            draft.round += 1

        if draft.status in _TERMINAL:
            return OrchestratorReply(
                draft=draft, message=f"This request is already {draft.status}.", done=True
            )

        # raw_text is never sent anywhere; only this redacted copy is (§1, §5).
        draft.redacted_text = redact(draft.raw_text)

        classification = await classify(self._d.llm, draft.redacted_text)
        if draft.category is None:
            draft.category = classification.category
            draft.required_fields = required_fields_for(classification.category)
        merged = dict(draft.extracted_fields)
        merged.update(classification.clean_fields())
        draft.extracted_fields = merged
        if classification.summary.strip():
            draft.summary = classification.summary.strip()
        draft.recompute_missing_fields()

        # --- clarify (capped) -------------------------------------------------
        if draft.missing_fields and draft.may_ask_again:
            draft.status = "gathering_info"
            await self._save(draft)
            return OrchestratorReply(
                draft=draft, message=next_question(draft.missing_fields), done=False
            )

        # --- investigate (capped) ------------------------------------------------
        draft.status = "investigating"
        self._d.tools.reset()
        query = (draft.summary or draft.redacted_text)[:_MAX_QUERY_CHARS]
        search = await self._d.tools.search_jira(query)
        if search.failed:
            logger.warning("search_jira failed for %s: %s", session_id, search.result)
        draft.evidence.extend(search.evidence())

        matches = await nearest(
            self._d.llm, self._d.vector_store, draft.redacted_text, exclude_id=session_id
        )
        draft.duplicate_of = pick_duplicate(matches)

        # --- score ----------------------------------------------------------------
        draft.score = await score_draft(
            self._d.llm,
            redacted_text=draft.redacted_text,
            evidence=draft.evidence,
            duplicate_of=draft.duplicate_of,
        )
        draft.status = "scored"

        # --- route + act --------------------------------------------------------
        draft.routing = decide_routing(draft)
        if draft.routing.decision == "auto_file":
            message = await self._file(draft)
        else:  # "escalate" — "ask_again" was handled by the clarify gate above
            draft.status = "escalated"
            message = f"Sent to a human: {draft.routing.reason}"

        await self._index(draft)
        await self._save(draft)
        # By here the draft is either "filed" or "escalated" — the turn is done
        # either way; the only non-done exit is the clarify gate's early return.
        return OrchestratorReply(draft=draft, message=message, done=True)

    async def _file(self, draft: IssueDraft) -> str:
        """Create the ticket, and link it to the canonical one if it is a duplicate."""
        first_line = next(iter(draft.redacted_text.splitlines()), "(no description)")
        summary = draft.summary or first_line
        created = await self._d.tools.create_ticket(
            project_key=self._d.project_key,
            summary=summary[:200],
            description=draft.redacted_text,
        )
        if created.failed or not created.evidence():
            draft.status = "escalated"
            return f"Could not file the ticket automatically: {created.result}"

        key = created.evidence()[0].ref
        draft.evidence.extend(created.evidence())
        draft.ticket = Ticket(id=key, url=self._d.tools.issue_url(key), status="To Do")
        draft.status = "filed"

        if draft.duplicate_of is None:
            return f"Filed {key}."

        linked = await self._d.tools.link_duplicate(
            duplicate_key=key, canonical_key=draft.duplicate_of.ticket_id
        )
        if linked.failed:
            return f"Filed {key}, but linking it to {draft.duplicate_of.ticket_id} failed."
        draft.evidence.extend(linked.evidence())
        return f"Filed {key} and linked it to {draft.duplicate_of.ticket_id} as a duplicate."

    async def _index(self, draft: IssueDraft) -> None:
        """Add this request to the vector store so later ones dedup against it."""
        await index_request(
            self._d.llm,
            self._d.vector_store,
            request_id=draft.conversation.session_id,
            text=draft.redacted_text,
            metadata={
                "session_id": draft.conversation.session_id,
                "surface": draft.conversation.surface,
                "status": draft.status,
                "ticket_id": draft.ticket.id if draft.ticket is not None else "",
            },
        )
