"""Signed, Redis-backed admin login sessions (design doc §8.3, §8.7).

Session state never lives in process memory: the cookie carries only an opaque
id plus an HMAC signature, and the session record itself is a Redis key with a
TTL, so a follow-up request served by a different instance still resolves.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

__all__ = ["AdminSession", "AdminSessionStore", "CookieSigner"]

_SESSION_PREFIX = "firsthand:admin:session"


class CookieSigner:
    """Signs and verifies a short string with HMAC-SHA256.

    The signature only proves the id was minted by this deployment; the id
    itself is a random lookup key, so tampering yields a value that resolves to
    no session rather than to someone else's.
    """

    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("secret_key must not be empty")
        self._key = secret_key.encode("utf-8")

    def _mac(self, value: str) -> str:
        return hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def sign(self, value: str) -> str:
        """Return ``value`` with its signature appended."""
        return f"{value}.{self._mac(value)}"

    def unsign(self, signed: str | None) -> str | None:
        """Return the original value, or ``None`` if the signature does not check out."""
        if not signed or signed.count(".") != 1:
            return None
        value, signature = signed.split(".", 1)
        if not hmac.compare_digest(signature, self._mac(value)):
            return None
        return value


@dataclass(frozen=True)
class AdminSession:
    """A resolved login session."""

    username: str
    created_at: datetime


class AdminSessionStore:
    """Creates, resolves, and destroys admin sessions in Redis."""

    def __init__(
        self,
        redis: Redis,
        signer: CookieSigner,
        *,
        ttl_seconds: int,
        prefix: str = _SESSION_PREFIX,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis
        self._signer = signer
        self._ttl = ttl_seconds
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}:{session_id}"

    async def create(self, username: str) -> str:
        """Mint a session for ``username`` and return the signed cookie value."""
        session_id = secrets.token_urlsafe(32)
        record = {"username": username, "created_at": datetime.now(UTC).isoformat()}
        await self._redis.set(self._key(session_id), json.dumps(record), ex=self._ttl)
        return self._signer.sign(session_id)

    async def resolve(self, cookie_value: str | None) -> AdminSession | None:
        """Return the live session for a cookie value, or ``None``."""
        session_id = self._signer.unsign(cookie_value)
        if session_id is None:
            return None
        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        record = json.loads(raw)
        return AdminSession(
            username=record["username"],
            created_at=datetime.fromisoformat(record["created_at"]),
        )

    async def destroy(self, cookie_value: str | None) -> None:
        """Delete the session a cookie points at; a no-op if it points nowhere."""
        session_id = self._signer.unsign(cookie_value)
        if session_id is None:
            return
        await self._redis.delete(self._key(session_id))
