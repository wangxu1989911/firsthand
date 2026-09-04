"""Match is what the orchestrator reads similarity off — pin its guarantees."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from firsthand.storage import Match


def test_cosine_similarity_may_be_negative() -> None:
    """Opposed embeddings are a real result, not an error — just never a duplicate."""
    assert Match(id="PAY-1", score=-0.42).score == -0.42


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_score_is_refused(bad: float) -> None:
    """NaN sorts arbitrarily, which makes bad ranking undetectable."""
    with pytest.raises(ValidationError):
        Match(id="PAY-1", score=bad)


def test_metadata_defaults_to_empty_and_is_not_shared() -> None:
    first, second = Match(id="a", score=0.1), Match(id="b", score=0.2)
    first.metadata["title"] = "only mine"
    assert second.metadata == {}
