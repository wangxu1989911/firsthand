"""Turn ``raw_text`` into ``redacted_text`` before any model ever sees it (§1, §7).

Two layers, applied in order:

1. :func:`pattern_redact` — deterministic, dependency-free regex matching for
   the identifiers that show up in feature requests: emails, phone numbers,
   IPs, long digit runs that look like card or account numbers, and
   bearer-token-shaped strings. Always runs; never fails; needs nothing
   installed.
2. The NER pass — Microsoft Presidio (design doc §1, §8.1) over a small spaCy
   model, masking person names and place names the pattern pass cannot catch.
   It only fires on whatever text is left after step 1, so it never re-examines
   (and cannot un-mask) anything the pattern pass already replaced. If Presidio
   or its model is not installed, or the analysis itself fails, this layer is
   skipped and the pattern-redacted text is used as-is — a missing NER pass
   narrows what gets caught, it never widens what leaks.

Deliberately conservative throughout: this is not a general DLP engine.
Organization names, product names, dates, and URLs are left alone on purpose —
they are usually the substance of the report, not personal data, and a false
redaction destroys the reporter's meaning as surely as a missed one exposes it.
``raw_text`` is kept alongside ``redacted_text`` precisely so a human reviewing
an escalation still has the original (§3).

Changes here get more review, not less (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

EMAIL_PLACEHOLDER = "<EMAIL>"
PHONE_PLACEHOLDER = "<PHONE>"
IP_PLACEHOLDER = "<IP>"
CARD_PLACEHOLDER = "<NUMBER>"
TOKEN_PLACEHOLDER = "<TOKEN>"
PERSON_PLACEHOLDER = "<PERSON>"
LOCATION_PLACEHOLDER = "<LOCATION>"

_EMAIL = re.compile(r"\b[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# 12-19 digits, optionally split into groups by spaces or hyphens: card / account.
_LONG_NUMBER = re.compile(r"\b\d(?:[ \-]?\d){11,18}\b")
# A phone number: optional +, then 7-15 digits with spaces, hyphens or dots and
# optional parenthesised area code. Requires at least one separator so bare
# short integers ("version 12345") are left alone.
_PHONE = re.compile(r"(?<![\w.])\+?\d{1,3}?[ .\-]?\(?\d{2,4}\)?(?:[ .\-]\d{2,4}){2,4}(?![\w.])")
# bearer / api-key shaped: 20+ chars of base64/hex/underscore/hyphen, often with
# a recognisable prefix.
_TOKEN = re.compile(r"\b(?:sk|pk|ghp|xox[baprs]|Bearer)[-_ ][A-Za-z0-9_\-]{16,}\b")


def pattern_redact(text: str) -> str:
    """Replace recognised personal or secret identifiers with typed placeholders.

    Order matters: emails and tokens are matched before the numeric patterns so
    a phone number inside an email local-part is not clipped out from under the
    email rule.
    """
    text = _TOKEN.sub(TOKEN_PLACEHOLDER, text)
    text = _EMAIL.sub(EMAIL_PLACEHOLDER, text)
    text = _IPV4.sub(IP_PLACEHOLDER, text)
    text = _LONG_NUMBER.sub(CARD_PLACEHOLDER, text)
    text = _PHONE.sub(PHONE_PLACEHOLDER, text)
    return text


# --- the NER layer (Presidio, design doc §1 / §8.1) -------------------------

#: Only entities the pattern pass structurally cannot catch. Deliberately not
#: "everything Presidio knows": organization names, dates, and URLs are usually
#: the substance of a bug report, not personal data (see the module docstring).
_NER_ENTITIES: dict[str, str] = {
    "PERSON": PERSON_PLACEHOLDER,
    "LOCATION": LOCATION_PLACEHOLDER,
}

_SPACY_MODEL = "en_core_web_sm"


@lru_cache(maxsize=1)
def _analyzer() -> Any | None:
    """Build the Presidio analyzer once, or ``None`` if it can't be built.

    Cached (including the ``None`` result) so an unavailable engine — not
    installed, or its spaCy model was never downloaded — logs one warning per
    process and is never retried on every message.
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError:
        logger.warning(
            "presidio-analyzer is not installed; PII redaction is pattern-only "
            "(names and places will not be masked). Install the 'pii' extra to enable it."
        )
        return None
    try:
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": _SPACY_MODEL}],
            }
        ).create_engine()
        return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    except Exception:
        logger.warning(
            "Presidio's spaCy model (%s) is unavailable; PII redaction is pattern-only. "
            "Run `python -m spacy download %s` to enable name/place masking.",
            _SPACY_MODEL,
            _SPACY_MODEL,
            exc_info=True,
        )
        return None


def _ner_redact(text: str) -> str:
    """Blocking: runs spaCy inference. Call through :func:`redact`, not directly."""
    analyzer = _analyzer()
    if analyzer is None:
        return text

    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

    results = analyzer.analyze(text=text, language="en", entities=list(_NER_ENTITIES))
    if not results:
        return text
    operators = {
        entity: OperatorConfig("replace", {"new_value": placeholder})
        for entity, placeholder in _NER_ENTITIES.items()
    }
    anonymized = AnonymizerEngine().anonymize(
        text=text, analyzer_results=results, operators=operators
    )
    return str(anonymized.text)


async def redact(text: str) -> str:
    """The full redaction pipeline: pattern pass, then the NER pass if it's available.

    The NER pass runs spaCy inference, which is synchronous and CPU-bound;
    it is pushed to a worker thread so one request's redaction never blocks
    the event loop the rest of the process is running on. A failure anywhere
    in that pass is caught and logged — it degrades to the pattern-redacted
    text rather than raising, because a redaction failure must never become a
    reason to send ``raw_text`` onward instead.
    """
    text = pattern_redact(text)
    if not text.strip():
        return text
    try:
        return await asyncio.to_thread(_ner_redact, text)
    except Exception:
        logger.exception("PII NER pass failed; using the pattern-redacted text")
        return text
