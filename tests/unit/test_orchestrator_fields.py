"""The required-field map drives the clarification loop."""

from __future__ import annotations

import pytest

from firsthand.orchestrator.fields import REQUIRED_FIELDS, required_fields_for


@pytest.mark.parametrize("category", ["bug", "feature", "question"])
def test_every_category_has_a_required_list(category: str) -> None:
    fields = required_fields_for(category)  # type: ignore[arg-type]
    assert fields == REQUIRED_FIELDS[category]  # type: ignore[index]
    assert fields, "a category with no required fields would never clarify"


def test_the_returned_list_is_a_copy() -> None:
    fields = required_fields_for("bug")
    fields.append("mutated")
    assert "mutated" not in REQUIRED_FIELDS["bug"]
