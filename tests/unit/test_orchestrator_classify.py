"""Classification turns redacted text into a category + fields, nothing more (§2)."""

from __future__ import annotations

import pytest
from tests.support import classification_entry

from firsthand.llm import RecordedLLM
from firsthand.orchestrator.classify import Classification, classify, next_question


async def test_classify_sends_only_the_redacted_text_and_returns_structured() -> None:
    llm = RecordedLLM(
        completions=classification_entry(
            "checkout is slow for <EMAIL>",
            {
                "category": "bug",
                "extracted_fields": {"actual_behavior": "p95 latency doubled", "problem": "   "},
                "summary": "Checkout latency regressed",
            },
        )
    )
    result = await classify(llm, "checkout is slow for <EMAIL>")
    assert isinstance(result, Classification)
    assert result.category == "bug"
    # the blank value is dropped by clean_fields, the real one kept
    assert result.clean_fields() == {"actual_behavior": "p95 latency doubled"}
    assert llm.structured_calls[0][0] == "Classification"


async def test_unknown_keys_from_the_model_are_ignored_not_errors() -> None:
    llm = RecordedLLM(
        completions=classification_entry(
            "please add SSO",
            {"category": "feature", "extracted_fields": {}, "summary": "", "hallucinated": 1},
        )
    )
    result = await classify(llm, "please add SSO")
    assert result.category == "feature"
    assert result.extracted_fields == {}


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        (["context"], "Could you tell me the context?"),
        (
            ["steps_to_reproduce", "expected_behavior"],
            "Could you tell me the steps to reproduce and expected behavior?",
        ),
        (
            ["a", "b", "c"],
            "Could you tell me the a, b and c?",
        ),
    ],
)
def test_next_question_reads_naturally(missing: list[str], expected: str) -> None:
    assert next_question(missing) == expected
