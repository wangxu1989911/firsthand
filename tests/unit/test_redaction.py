"""Redaction is the §1 boundary: raw_text never reaches a model, only this output."""

from __future__ import annotations

import pytest

from firsthand.orchestrator.redaction import (
    CARD_PLACEHOLDER,
    EMAIL_PLACEHOLDER,
    IP_PLACEHOLDER,
    PHONE_PLACEHOLDER,
    TOKEN_PLACEHOLDER,
    redact,
)


@pytest.mark.parametrize(
    ("raw", "expected_placeholder", "leaked"),
    [
        ("mail me at jane.doe@example.co.uk please", EMAIL_PLACEHOLDER, "jane.doe@example.co.uk"),
        ("server at 10.1.42.9 is down", IP_PLACEHOLDER, "10.1.42.9"),
        ("card 4111 1111 1111 1111 was charged", CARD_PLACEHOLDER, "4111 1111 1111 1111"),
        ("call +1 415 555 2671 after noon", PHONE_PLACEHOLDER, "555 2671"),
        ("token sk-ABCDEF0123456789ghij leaked", TOKEN_PLACEHOLDER, "sk-ABCDEF0123456789ghij"),
    ],
)
def test_each_identifier_class_is_replaced(
    raw: str, expected_placeholder: str, leaked: str
) -> None:
    out = redact(raw)
    assert expected_placeholder in out
    assert leaked not in out


def test_plain_prose_and_short_numbers_are_left_alone() -> None:
    text = "The dashboard on version 12 fails for about 30 users in region 3."
    assert redact(text) == text


def test_an_email_containing_digits_is_redacted_whole() -> None:
    assert redact("ping user42@corp.example.com") == f"ping {EMAIL_PLACEHOLDER}"


def test_redaction_is_idempotent() -> None:
    once = redact("reach me: a@b.com / 10.0.0.1")
    assert redact(once) == once
