"""Implementations of the :class:`~firsthand.web.intake.Orchestrator` seam.

:class:`LoopOrchestrator` is the real one — a thin adapter over Phase 1's
``firsthand.orchestrator`` loop (classify → clarify → investigate → score →
route), chosen at startup whenever an LLM key is configured.

:class:`StubOrchestrator` is the deterministic fallback: the same shape of
clarification loop with fixed rules instead of an LLM. It backs the tests and
also keeps the public chat working on a stack that has no LLM key yet.
"""

from __future__ import annotations

from typing import Any

from firsthand.connectors.jira import JiraConnector, JiraTransportError
from firsthand.contracts import (
    Category,
    Conversation,
    IssueDraft,
    Routing,
    Score,
    Urgency,
)
from firsthand.orchestrator import Orchestrator as _Loop
from firsthand.orchestrator import OrchestratorDeps
from firsthand.web.intake import OrchestratorTurn
from firsthand.web.redaction import redact


class _UnconfiguredJiraTransport:
    """A :class:`~firsthand.connectors.jira.JiraTransport` for when no Jira
    connector has been set up in the admin area yet.

    Every call fails cleanly rather than reaching the network: the loop logs the
    failed ``search_jira`` and steps past it, and a failed ``create_ticket``
    routes the draft to a human. Configuring Jira swaps in the real transport at
    the next restart.
    """

    _MESSAGE = "no Jira connector is configured (Admin → Configuration)"

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        raise JiraTransportError(self._MESSAGE)

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise JiraTransportError(self._MESSAGE)


def unconfigured_jira() -> JiraConnector:
    """A :class:`JiraConnector` that fails every call until Jira is configured."""
    return JiraConnector(_UnconfiguredJiraTransport(), browse_base_url="")


class LoopOrchestrator:
    """Phase 1's real orchestrator behind the web intake seam.

    The loop loads and saves the draft itself through the shared
    :class:`~firsthand.storage.StateStore`, so this adapter only translates the
    call shape and the reply type. ``draft`` is accepted for protocol
    conformance but the loop re-reads it from the store.
    """

    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps

    async def advance(
        self,
        *,
        message: str,
        draft: IssueDraft | None,
        conversation: Conversation,
    ) -> OrchestratorTurn:
        reply = await _Loop(self._deps).handle(
            surface=conversation.surface,
            session_id=conversation.session_id,
            text=message,
        )
        return OrchestratorTurn(draft=reply.draft, reply=reply.message, done=reply.done)

    async def aclose(self) -> None:
        """Release the LLM client's HTTP connection pool at shutdown."""
        closer = getattr(self._deps.llm, "aclose", None)
        if closer is not None:
            await closer()


_REQUIRED_FIELDS: dict[Category, tuple[str, ...]] = {
    "bug": ("steps_to_reproduce", "affected_version"),
    "feature": ("problem", "desired_outcome"),
    "question": ("question_detail",),
}

_QUESTION_FOR: dict[str, str] = {
    "steps_to_reproduce": "What steps reproduce the problem, from a clean start?",
    "affected_version": "Which version or environment are you seeing this on?",
    "problem": "What problem would this feature solve, and for whom?",
    "desired_outcome": "What would the ideal outcome look like for you?",
    "question_detail": "Can you say a bit more about what you'd like to know?",
}

_BUG_WORDS = ("bug", "broken", "error", "crash", "fails", "failing", "regression")
_QUESTION_WORDS = ("how do i", "how can i", "what is", "why does", "?")
_URGENT_WORDS = ("urgent", "asap", "outage", "critical", "blocking", "production is down")


def _classify(text: str) -> Category:
    lowered = text.lower()
    if any(word in lowered for word in _BUG_WORDS):
        return "bug"
    if any(word in lowered for word in _QUESTION_WORDS):
        return "question"
    return "feature"


def _is_urgent(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _URGENT_WORDS)


def _urgency(text: str) -> Urgency:
    return "high" if _is_urgent(text) else "low"


class StubOrchestrator:
    """Implements the :class:`~firsthand.web.intake.Orchestrator` protocol."""

    async def advance(
        self,
        *,
        message: str,
        draft: IssueDraft | None,
        conversation: Conversation,
    ) -> OrchestratorTurn:
        if draft is None:
            draft = self._start(message, conversation)
        else:
            self._absorb_answer(draft, message)

        missing = draft.recompute_missing_fields()
        if not missing:
            return self._finish(draft)
        if not draft.may_ask_again:
            return self._give_up(draft)

        draft.round += 1
        draft.status = "gathering_info"
        return OrchestratorTurn(draft=draft, reply=_QUESTION_FOR[missing[0]], done=False)

    @staticmethod
    def _start(message: str, conversation: Conversation) -> IssueDraft:
        category = _classify(message)
        return IssueDraft(
            conversation=conversation,
            raw_text=message,
            redacted_text=redact(message),
            category=category,
            required_fields=list(_REQUIRED_FIELDS[category]),
            status="gathering_info",
        )

    @staticmethod
    def _absorb_answer(draft: IssueDraft, message: str) -> None:
        draft.raw_text = f"{draft.raw_text}\n{message}"
        draft.redacted_text = redact(draft.raw_text)
        pending = draft.recompute_missing_fields()
        if pending:
            draft.extracted_fields = {**draft.extracted_fields, pending[0]: message}

    @staticmethod
    def _finish(draft: IssueDraft) -> OrchestratorTurn:
        draft.score = Score(
            impact=5.0, effort=5.0, urgency=_urgency(draft.raw_text), confidence=0.5
        )
        if _is_urgent(draft.raw_text):
            draft.routing = Routing(
                decision="escalate",
                reason="Reporter signalled urgency; a person should review before filing.",
            )
            draft.status = "escalated"
            reply = "Thanks — this looks urgent, so I've flagged it for a person to review now."
        else:
            draft.routing = Routing(decision="auto_file", reason="All required fields gathered.")
            draft.status = "scored"
            reply = "Thanks, I have everything I need. I'll file this now."
        return OrchestratorTurn(draft=draft, reply=reply, done=True)

    @staticmethod
    def _give_up(draft: IssueDraft) -> OrchestratorTurn:
        draft.routing = Routing(
            decision="escalate",
            reason="Clarification limit reached with required fields still missing.",
        )
        draft.status = "escalated"
        return OrchestratorTurn(
            draft=draft,
            reply=(
                "I wasn't able to gather everything, so I've passed this to a person "
                "to follow up with you."
            ),
            done=True,
        )
