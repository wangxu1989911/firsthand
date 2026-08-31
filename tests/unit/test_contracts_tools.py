"""Connectors return evidence, never conclusions (design doc §3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from firsthand.contracts import Evidence, ToolCall, ToolError, ToolSuccess


def _evidence() -> Evidence:
    return Evidence(
        source="jira", ref="PAY-412", snippet="p95 regressed", retrieved_by="search_jira"
    )


def test_a_successful_call_exposes_its_evidence() -> None:
    call = ToolCall(
        name="search_jira", args={"q": "checkout slow"}, result=ToolSuccess(evidence=[_evidence()])
    )
    assert not call.failed
    assert [item.ref for item in call.evidence()] == ["PAY-412"]


def test_no_evidence_found_is_an_explicit_state_not_a_gap() -> None:
    result = ToolSuccess()
    assert result.evidence == []
    assert not result.found_evidence
    assert ToolSuccess(evidence=[_evidence()]).found_evidence


def test_a_failed_call_surfaces_the_error_and_yields_no_evidence() -> None:
    call = ToolCall(name="search_git_history", result=ToolError(error="401 from git host"))
    assert call.failed
    assert call.evidence() == []


def test_a_pending_call_has_no_result_yet() -> None:
    call = ToolCall(name="search_design_docs")
    assert call.result is None
    assert not call.failed
    assert call.evidence() == []


def test_tool_calls_round_trip_through_json() -> None:
    call = ToolCall(name="link_duplicate", args={"ticket_id": "PAY-412"}, result=ToolSuccess())
    assert ToolCall.model_validate_json(call.model_dump_json()) == call


def test_unknown_tool_names_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolCall(name="rm_rf")  # type: ignore[arg-type]


def test_an_error_must_say_something() -> None:
    with pytest.raises(ValidationError):
        ToolError(error="")


def test_an_error_result_survives_json_without_being_read_as_a_success() -> None:
    call = ToolCall(name="search_jira", result=ToolError(error="401 from Jira"))
    restored = ToolCall.model_validate_json(call.model_dump_json())
    assert isinstance(restored.result, ToolError)
    assert restored.failed
    assert restored == call
