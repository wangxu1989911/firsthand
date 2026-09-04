"""A deterministic stand-in for the real orchestrator (Phase 1 / §5).

It runs a real clarification loop against the §3 contracts — classify, gather the
required fields one question at a time, respect the round cap, then either
"file" or escalate — with fixed rules instead of an LLM. Phase 5 swaps in the
real :class:`~firsthand.web.intake.Orchestrator`; this class then only backs
tests.
"""

from __future__ import annotations

from firsthand.contracts import (
    Category,
    Conversation,
    IssueDraft,
    Routing,
    Score,
    Urgency,
)
from firsthand.web.intake import OrchestratorTurn
from firsthand.web.redaction import redact

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
