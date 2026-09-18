"""Redaction is the §1 boundary: raw_text never reaches a model, only this output.

Two layers: ``pattern_redact`` (always on, deterministic) and the NER pass
Presidio adds on top of it, exercised here with the analyzer faked out since
presidio-analyzer/spacy are an optional extra the fast unit job does not
install — the real thing is exercised by ``tests/integration/test_pii_ner.py``,
gated behind the ``presidio`` marker.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

import firsthand.redaction as redaction_module
from firsthand.redaction import (
    CARD_PLACEHOLDER,
    EMAIL_PLACEHOLDER,
    IP_PLACEHOLDER,
    LOCATION_PLACEHOLDER,
    PERSON_PLACEHOLDER,
    PHONE_PLACEHOLDER,
    TOKEN_PLACEHOLDER,
    pattern_redact,
    redact,
)

# --- pattern_redact ----------------------------------------------------------


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
    out = pattern_redact(raw)
    assert expected_placeholder in out
    assert leaked not in out


def test_plain_prose_and_short_numbers_are_left_alone() -> None:
    text = "The dashboard on version 12 fails for about 30 users in region 3."
    assert pattern_redact(text) == text


def test_an_email_containing_digits_is_redacted_whole() -> None:
    assert pattern_redact("ping user42@corp.example.com") == f"ping {EMAIL_PLACEHOLDER}"


def test_pattern_redact_is_idempotent() -> None:
    once = pattern_redact("reach me: a@b.com / 10.0.0.1")
    assert pattern_redact(once) == once


# --- redact() — the full pipeline, NER layer faked out ----------------------


async def test_redact_applies_the_pattern_pass_regardless_of_ner_availability() -> None:
    # presidio-analyzer is not installed in this job, so the NER layer is a
    # no-op here — this is the real, unmocked fallback path (§7): a missing
    # NER pass narrows what gets caught, it never leaks pattern-caught PII.
    assert await redact("mail me at jane@example.com") == "mail me at <EMAIL>"


async def test_redact_skips_the_ner_call_for_blank_text() -> None:
    assert await redact("") == ""
    assert await redact("   ") == "   "


async def test_redact_is_idempotent() -> None:
    once = await redact("reach me: a@b.com / 10.0.0.1")
    assert await redact(once) == once


async def test_redact_masks_entities_the_analyzer_finds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wires a fake presidio-analyzer/-anonymizer pair to pin the substitution logic."""
    person_hit = SimpleNamespace(entity_type="PERSON")

    class FakeAnalyzer:
        def analyze(self, *, text: str, language: str, entities: list[str]) -> list[object]:
            assert text == "hello John, we met in Paris"
            assert language == "en"
            assert set(entities) == {"PERSON", "LOCATION"}
            return [person_hit]

    expected = f"hello {PERSON_PLACEHOLDER}, we met in {LOCATION_PLACEHOLDER}"

    class FakeAnonymizerEngine:
        def anonymize(
            self, *, text: str, analyzer_results: list[object], operators: dict[str, object]
        ) -> object:
            assert text == "hello John, we met in Paris"
            assert analyzer_results == [person_hit]
            assert set(operators) == {"PERSON", "LOCATION"}
            return SimpleNamespace(text=expected)

    def fake_operator_config(operator: str, params: dict[str, object]) -> tuple[str, object]:
        return (operator, params)

    fake_anonymizer_pkg = types.ModuleType("presidio_anonymizer")
    fake_anonymizer_pkg.AnonymizerEngine = FakeAnonymizerEngine  # type: ignore[attr-defined]
    fake_entities_mod = types.ModuleType("presidio_anonymizer.entities")
    fake_entities_mod.OperatorConfig = fake_operator_config  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_anonymizer", fake_anonymizer_pkg)
    monkeypatch.setitem(sys.modules, "presidio_anonymizer.entities", fake_entities_mod)
    monkeypatch.setattr(redaction_module, "_analyzer", lambda: FakeAnalyzer())

    result = await redact("hello John, we met in Paris")
    assert result == expected


async def test_redact_returns_the_text_unchanged_when_the_analyzer_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyAnalyzer:
        def analyze(self, *, text: str, language: str, entities: list[str]) -> list[object]:
            return []

    monkeypatch.setattr(redaction_module, "_analyzer", lambda: EmptyAnalyzer())
    assert await redact("nothing personal here") == "nothing personal here"


async def test_redact_falls_back_to_the_pattern_pass_when_ner_analysis_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class ExplodingAnalyzer:
        def analyze(self, *, text: str, language: str, entities: list[str]) -> list[object]:
            raise RuntimeError("spaCy blew up")

    monkeypatch.setattr(redaction_module, "_analyzer", lambda: ExplodingAnalyzer())
    with caplog.at_level("ERROR"):
        result = await redact("mail me at jane@example.com")
    assert result == "mail me at <EMAIL>"  # the pattern pass still applied
    assert "PII NER pass failed" in caplog.text


def test_analyzer_returns_none_when_presidio_is_not_installed() -> None:
    # The real state of this job: presidio-analyzer is an optional extra, not
    # a dev dependency, so the cached analyzer is genuinely unavailable here.
    assert redaction_module._analyzer() is None


def test_analyzer_builds_the_real_engine_when_presidio_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fakes the presidio-analyzer package to pin _analyzer()'s success path."""
    built_engine = SimpleNamespace(marker="nlp-engine")

    class FakeAnalyzerEngine:
        def __init__(self, *, nlp_engine: object, supported_languages: list[str]) -> None:
            assert nlp_engine is built_engine
            assert supported_languages == ["en"]

    class FakeNlpEngineProvider:
        def __init__(self, *, nlp_configuration: dict) -> None:
            assert nlp_configuration["nlp_engine_name"] == "spacy"

        def create_engine(self) -> object:
            return built_engine

    fake_analyzer_pkg = types.ModuleType("presidio_analyzer")
    fake_analyzer_pkg.AnalyzerEngine = FakeAnalyzerEngine  # type: ignore[attr-defined]
    fake_nlp_engine_mod = types.ModuleType("presidio_analyzer.nlp_engine")
    fake_nlp_engine_mod.NlpEngineProvider = FakeNlpEngineProvider  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_analyzer", fake_analyzer_pkg)
    monkeypatch.setitem(sys.modules, "presidio_analyzer.nlp_engine", fake_nlp_engine_mod)

    redaction_module._analyzer.cache_clear()
    try:
        assert isinstance(redaction_module._analyzer(), FakeAnalyzerEngine)
    finally:
        redaction_module._analyzer.cache_clear()


def test_analyzer_returns_none_when_the_spacy_model_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presidio installed, but its model was never downloaded — engine build fails."""

    class FakeNlpEngineProvider:
        def __init__(self, *, nlp_configuration: dict) -> None:
            pass

        def create_engine(self) -> object:
            raise OSError("model 'en_core_web_sm' not found")

    fake_analyzer_pkg = types.ModuleType("presidio_analyzer")
    fake_analyzer_pkg.AnalyzerEngine = object  # type: ignore[attr-defined]  # never reached
    fake_nlp_engine_mod = types.ModuleType("presidio_analyzer.nlp_engine")
    fake_nlp_engine_mod.NlpEngineProvider = FakeNlpEngineProvider  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_analyzer", fake_analyzer_pkg)
    monkeypatch.setitem(sys.modules, "presidio_analyzer.nlp_engine", fake_nlp_engine_mod)

    redaction_module._analyzer.cache_clear()
    try:
        assert redaction_module._analyzer() is None
    finally:
        redaction_module._analyzer.cache_clear()
