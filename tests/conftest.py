"""Shared fixtures. Unit tests never touch a network; integration tests do."""

from __future__ import annotations

import pytest

from firsthand.contracts import Conversation, Evidence, IssueDraft


@pytest.fixture
def draft() -> IssueDraft:
    """A minimal draft, one round in, with one piece of Jira evidence."""
    return IssueDraft(
        conversation=Conversation(surface="web", session_id="s-1"),
        raw_text="checkout is slow for jane@example.com",
        redacted_text="checkout is slow for <EMAIL>",
        category="bug",
        required_fields=["steps_to_reproduce", "affected_version"],
        extracted_fields={"steps_to_reproduce": "open checkout, wait"},
        evidence=[
            Evidence(
                source="jira",
                ref="PAY-412",
                snippet="Checkout p95 regressed after the 4.2 rollout",
                retrieved_by="search_jira",
            )
        ],
    )
