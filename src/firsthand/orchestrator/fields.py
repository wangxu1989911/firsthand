"""Which fields a draft needs before it is worth investigating (design doc §2).

The clarification loop (§2) exists to fill these in — capped at
``MAX_CLARIFICATION_ROUNDS`` rounds, after which the draft proceeds with what it
has and is flagged if still thin.
"""

from __future__ import annotations

from firsthand.contracts import Category

#: Per-category minimum. Kept small on purpose: every entry here is a question
#: the agent may spend one of its three rounds on.
REQUIRED_FIELDS: dict[Category, list[str]] = {
    "bug": ["steps_to_reproduce", "expected_behavior", "actual_behavior"],
    "feature": ["problem", "proposed_solution", "affected_users"],
    "question": ["context"],
}


def required_fields_for(category: Category) -> list[str]:
    """The required-field list for a category, copied so callers can't mutate it."""
    return list(REQUIRED_FIELDS[category])
