"""The urgency / confidence gate: what happens to a scored draft (design doc §2).

Deterministic on purpose. The model produces the score; this function turns the
score, the duplicate result, and how complete the draft is into one of three
decisions. Keeping it out of the model keeps the caps meaningful and the
behaviour testable.
"""

from __future__ import annotations

from firsthand.contracts import IssueDraft, Routing

#: Below this the evidence did not really support the score — a human looks (§5).
CONFIDENCE_FLOOR = 0.5


def decide_routing(draft: IssueDraft) -> Routing:
    """Map a draft's state to ``ask_again`` / ``escalate`` / ``auto_file``."""
    missing = draft.missing_fields

    if missing and draft.may_ask_again:
        return Routing(
            decision="ask_again",
            reason=f"still missing {', '.join(missing)}; {draft.rounds_remaining} round(s) left",
        )

    if draft.duplicate_of is not None:
        return Routing(
            decision="auto_file",
            reason=(
                f"duplicate of {draft.duplicate_of.ticket_id} at "
                f"similarity {draft.duplicate_of.similarity:.2f}; link rather than re-file"
            ),
        )

    if draft.score is None:
        return Routing(decision="escalate", reason="no score was produced")

    if missing:
        return Routing(
            decision="escalate",
            reason=f"still missing {', '.join(missing)} after {draft.round} clarification round(s)",
        )

    if draft.score.confidence < CONFIDENCE_FLOOR:
        return Routing(
            decision="escalate",
            reason=f"scoring confidence {draft.score.confidence:.2f} below {CONFIDENCE_FLOOR:.2f}",
        )

    if draft.score.urgency == "high":
        return Routing(
            decision="escalate",
            reason="high urgency — a human should see this before it is filed",
        )

    return Routing(
        decision="auto_file",
        reason="complete, no duplicate, confident, not urgent",
    )
