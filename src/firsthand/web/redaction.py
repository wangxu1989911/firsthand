"""Best-effort PII redaction (design doc §1, §7).

``raw_text`` is kept verbatim for human reviewers; only the redacted form is
ever handed onward to a model. This is a deliberately conservative pass over the
obvious identifiers — the orchestrator does the authoritative redaction, this
keeps the stored copy clean in the meantime.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")

__all__ = ["redact"]


def redact(text: str) -> str:
    """Return ``text`` with email addresses and phone-like runs masked."""
    text = _EMAIL.sub("<EMAIL>", text)
    text = _PHONE.sub("<PHONE>", text)
    return text
