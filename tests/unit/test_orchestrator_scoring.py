"""Scoring is LLM-as-judge over gathered evidence; it returns a plain Score (§5)."""

from __future__ import annotations

from tests.support import score_entry

from firsthand.contracts import DuplicateOf, Evidence, Score
from firsthand.llm import RecordedLLM
from firsthand.orchestrator.scoring import ScoreJudgement, score_draft, scoring_user_prompt


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            source="jira", ref="PAY-1", snippet="checkout p95 regressed", retrieved_by="search_jira"
        )
    ]


async def test_score_draft_maps_the_judgement_onto_the_contract() -> None:
    prompt = scoring_user_prompt("checkout slow", _evidence(), None)
    llm = RecordedLLM(
        completions=score_entry(
            prompt,
            {
                "impact": 7,
                "effort": 3,
                "urgency": "med",
                "confidence": 0.8,
                "rationale": "PAY-1 shows the same regression",
            },
        )
    )
    score = await score_draft(
        llm, redacted_text="checkout slow", evidence=_evidence(), duplicate_of=None
    )
    assert score == Score(impact=7, effort=3, urgency="med", confidence=0.8)


async def test_the_prompt_names_the_duplicate_and_the_no_evidence_state() -> None:
    prompt = scoring_user_prompt(
        "checkout slow", [], DuplicateOf(ticket_id="PAY-9", similarity=0.95)
    )
    assert "NO EVIDENCE WAS RETRIEVED." in prompt
    assert "PAY-9" in prompt

    llm = RecordedLLM(
        completions=score_entry(
            prompt,
            {"impact": 1, "effort": 1, "urgency": "low", "confidence": 0.2, "rationale": "thin"},
        )
    )
    score = await score_draft(
        llm,
        redacted_text="checkout slow",
        evidence=[],
        duplicate_of=DuplicateOf(ticket_id="PAY-9", similarity=0.95),
    )
    assert score.confidence == 0.2


def test_judgement_drops_the_rationale_when_narrowing_to_score() -> None:
    judgement = ScoreJudgement(
        impact=5, effort=5, urgency="high", confidence=0.5, rationale="because"
    )
    assert judgement.to_score() == Score(impact=5, effort=5, urgency="high", confidence=0.5)
