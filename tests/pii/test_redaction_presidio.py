"""The real Presidio/spaCy NER pass, not the faked one in tests/unit/test_redaction.py."""

from __future__ import annotations

from firsthand.redaction import LOCATION_PLACEHOLDER, PERSON_PLACEHOLDER, redact


async def test_a_persons_name_is_masked(real_analyzer: object) -> None:
    result = await redact("Hi, this is John Smith reporting a bug with checkout.")
    assert "John Smith" not in result
    assert PERSON_PLACEHOLDER in result


async def test_a_place_name_is_masked(real_analyzer: object) -> None:
    result = await redact("I filed this from our Berlin office this morning.")
    assert "Berlin" not in result
    assert LOCATION_PLACEHOLDER in result


async def test_ordinary_technical_prose_is_left_alone(real_analyzer: object) -> None:
    text = "The checkout service times out after 30 seconds under load."
    assert await redact(text) == text


async def test_pattern_and_ner_layers_both_apply(real_analyzer: object) -> None:
    result = await redact("John Smith can be reached at john@example.com about this.")
    assert "John Smith" not in result
    assert "john@example.com" not in result
    assert PERSON_PLACEHOLDER in result
    assert "<EMAIL>" in result
