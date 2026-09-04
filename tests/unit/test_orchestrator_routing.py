"""Routing is the deterministic gate: score + dedup + completeness -> one decision."""

from __future__ import annotations

from firsthand.contracts import Conversation, DuplicateOf, IssueDraft, Score
from firsthand.orchestrator.routing import CONFIDENCE_FLOOR, decide_routing


def _draft(**kwargs: object) -> IssueDraft:
    base: dict[str, object] = {
        "conversation": Conversation(surface="web", session_id="s"),
        "raw_text": "x",
        "required_fields": ["a"],
    }
    base.update(kwargs)
    return IssueDraft(**base)  # type: ignore[arg-type]


def test_missing_fields_with_rounds_left_asks_again() -> None:
    draft = _draft(missing_fields=["a"], round=1)
    routing = decide_routing(draft)
    assert routing.decision == "ask_again"
    assert "round(s) left" in routing.reason


def test_a_duplicate_is_auto_filed_for_linking_even_when_urgent() -> None:
    draft = _draft(
        missing_fields=[],
        round=3,
        duplicate_of=DuplicateOf(ticket_id="PAY-1", similarity=0.97),
        score=Score(impact=5, effort=5, urgency="high", confidence=0.9),
    )
    routing = decide_routing(draft)
    assert routing.decision == "auto_file"
    assert "PAY-1" in routing.reason


def test_missing_after_the_cap_escalates() -> None:
    draft = _draft(missing_fields=["a"], round=3)
    assert decide_routing(draft).decision == "escalate"


def test_no_score_escalates() -> None:
    draft = _draft(missing_fields=[], round=3, score=None)
    assert decide_routing(draft).decision == "escalate"


def test_low_confidence_escalates() -> None:
    draft = _draft(
        missing_fields=[],
        round=1,
        score=Score(impact=5, effort=5, urgency="low", confidence=CONFIDENCE_FLOOR - 0.01),
    )
    routing = decide_routing(draft)
    assert routing.decision == "escalate"
    assert "confidence" in routing.reason


def test_high_urgency_escalates_even_when_confident() -> None:
    draft = _draft(
        missing_fields=[],
        round=1,
        score=Score(impact=8, effort=2, urgency="high", confidence=0.95),
    )
    assert decide_routing(draft).decision == "escalate"


def test_complete_confident_not_urgent_not_duplicate_auto_files() -> None:
    draft = _draft(
        missing_fields=[],
        round=1,
        score=Score(impact=6, effort=3, urgency="med", confidence=0.8),
    )
    routing = decide_routing(draft)
    assert routing.decision == "auto_file"
    assert routing.reason == "complete, no duplicate, confident, not urgent"
