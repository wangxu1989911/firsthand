"""The offline eval embedder must be deterministic and keep cosine defined."""

from __future__ import annotations

import pytest

from firsthand.eval.embedding import EVAL_DIMENSIONS, cosine, embed_text


def test_embedding_is_unit_length_and_deterministic() -> None:
    first = embed_text("login fails with SAML SSO")
    second = embed_text("login fails with SAML SSO")
    assert first == second
    assert len(first) == EVAL_DIMENSIONS
    assert cosine(first, first) == pytest.approx(1.0)


def test_similar_text_scores_higher_than_unrelated_text() -> None:
    anchor = embed_text("export the report table to a CSV file")
    near = embed_text("CSV export for the report table")
    far = embed_text("add a dark mode theme toggle")
    assert cosine(anchor, near) > cosine(anchor, far)


def test_empty_text_still_yields_a_defined_cosine() -> None:
    empty = embed_text("!!!")  # no word characters -> no features
    assert cosine(empty, empty) == pytest.approx(1.0)


def test_cosine_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="length"):
        cosine([1.0, 0.0], [1.0])
