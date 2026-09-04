"""IssueDraft is the contract every later track builds on — pin its behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from firsthand.contracts import (
    MAX_CLARIFICATION_ROUNDS,
    Conversation,
    DuplicateOf,
    Evidence,
    IssueDraft,
    Routing,
    Score,
    Ticket,
)


def test_defaults_start_in_gathering_info(draft: IssueDraft) -> None:
    assert draft.status == "gathering_info"
    assert draft.round == 0
    assert draft.summary == ""
    assert draft.duplicate_of is None
    assert draft.score is None
    assert draft.routing is None
    assert draft.ticket is None


def test_raw_text_is_kept_alongside_the_redacted_copy(draft: IssueDraft) -> None:
    assert "jane@example.com" in draft.raw_text
    assert "jane@example.com" not in draft.redacted_text


def test_round_cap_governs_whether_another_question_is_allowed(draft: IssueDraft) -> None:
    assert draft.may_ask_again
    assert draft.rounds_remaining == MAX_CLARIFICATION_ROUNDS

    draft.round = MAX_CLARIFICATION_ROUNDS
    assert not draft.may_ask_again
    assert draft.rounds_remaining == 0

    draft.round = MAX_CLARIFICATION_ROUNDS + 1
    assert draft.rounds_remaining == 0


def test_missing_fields_is_required_minus_filled(draft: IssueDraft) -> None:
    assert draft.recompute_missing_fields() == ["affected_version"]
    assert draft.missing_fields == ["affected_version"]


def test_missing_fields_drops_anything_evidence_already_answers(draft: IssueDraft) -> None:
    assert draft.recompute_missing_fields(inferable={"affected_version"}) == []


def test_cite_filters_evidence_by_source(draft: IssueDraft) -> None:
    draft.evidence.append(
        Evidence(source="git", ref="a1b2c3d", snippet="perf fix", retrieved_by="search_git_history")
    )
    assert [item.ref for item in draft.cite("jira")] == ["PAY-412"]
    assert [item.ref for item in draft.cite("git")] == ["a1b2c3d"]
    assert draft.cite("docs") == []


def test_a_fully_populated_draft_round_trips_through_json(draft: IssueDraft) -> None:
    draft.summary = "checkout returns a 500 on submit"
    draft.duplicate_of = DuplicateOf(ticket_id="PAY-412", similarity=0.94)
    draft.score = Score(impact=7, effort=3, urgency="med", confidence=0.82)
    draft.routing = Routing(decision="auto_file", reason="backlog-shaped, confident")
    draft.ticket = Ticket(id="PAY-987", url="https://jira/PAY-987", status="To Do")
    draft.status = "filed"

    assert IssueDraft.model_validate_json(draft.model_dump_json()) == draft


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "epic"},
        {"status": "done"},
        {"round": -1},
        {"unexpected_field": "x"},
    ],
)
def test_invalid_drafts_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        IssueDraft(
            conversation=Conversation(surface="web", session_id="s-1"),
            raw_text="hi",
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("similarity", [-0.1, 1.1])
def test_similarity_stays_a_probability(similarity: float) -> None:
    with pytest.raises(ValidationError):
        DuplicateOf(ticket_id="PAY-1", similarity=similarity)


def test_score_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        Score(impact=11, effort=1, urgency="low", confidence=0.5)
    with pytest.raises(ValidationError):
        Score(impact=1, effort=1, urgency="low", confidence=1.4)


def test_session_id_and_evidence_refs_may_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        Conversation(surface="web", session_id="")
    with pytest.raises(ValidationError):
        Evidence(source="jira", ref="", snippet="x", retrieved_by="search_jira")


def test_a_blank_extracted_value_does_not_count_as_answered(draft: IssueDraft) -> None:
    """An extractor emitting "" for "not found" must not retire the question."""
    draft.extracted_fields["affected_version"] = "   "
    assert draft.recompute_missing_fields() == ["affected_version"]


def test_evidence_must_quote_an_actual_passage() -> None:
    """Grounding means a followable citation, not an empty one."""
    with pytest.raises(ValidationError):
        Evidence(source="jira", ref="PAY-1", snippet="", retrieved_by="search_jira")


def test_assignment_is_validated_not_just_construction(draft: IssueDraft) -> None:
    """A draft is mutated across turns; unvalidated assignment defeats the §2 cap.

    Without this the writer succeeds silently and the *next* container to read
    the draft back takes the ValidationError (§8.3).
    """
    with pytest.raises(ValidationError):
        draft.round = -1
    with pytest.raises(ValidationError):
        draft.status = "done"  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        draft.category = "epic"  # type: ignore[assignment]

    assert draft.may_ask_again
    assert draft.rounds_remaining <= MAX_CLARIFICATION_ROUNDS
