"""Turn ``raw_text`` into ``redacted_text`` before any model ever sees it (§1, §7).

This is deliberately conservative and pattern-based: it strips the identifiers
that show up in feature requests — emails, phone numbers, IPs, long digit runs
that look like card or account numbers, and bearer-token-shaped strings. It is
not a general DLP engine; anything it is unsure about it leaves alone, because a
false redaction destroys the reporter's meaning and a human still reviews every
escalation against ``raw_text``.

Changes here get more review, not less (CLAUDE.md §5).
"""

from __future__ import annotations

import re

EMAIL_PLACEHOLDER = "<EMAIL>"
PHONE_PLACEHOLDER = "<PHONE>"
IP_PLACEHOLDER = "<IP>"
CARD_PLACEHOLDER = "<NUMBER>"
TOKEN_PLACEHOLDER = "<TOKEN>"

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


def redact(text: str) -> str:
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
