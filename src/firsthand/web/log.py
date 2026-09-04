"""The per-session chat transcript, held in Redis (design doc §8.3).

The transcript is presentation state — what to re-render when the page reloads —
not part of the :class:`~firsthand.contracts.IssueDraft`. It expires on the same
clock as the draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

__all__ = ["ConversationLog", "LogEntry"]

Role = Literal["user", "assistant"]
_LOG_PREFIX = "firsthand:web:log"


@dataclass(frozen=True)
class LogEntry:
    """One line of the transcript."""

    role: Role
    text: str


class ConversationLog:
    """Append-only transcript for one session, newest last."""

    def __init__(
        self,
        redis: Redis,
        *,
        prefix: str = _LOG_PREFIX,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis
        self._prefix = prefix
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}:{session_id}"

    async def append(self, session_id: str, role: Role, text: str) -> None:
        """Add one line and refresh the transcript's expiry."""
        key = self._key(session_id)
        await self._redis.rpush(key, json.dumps({"role": role, "text": text}))
        await self._redis.expire(key, self._ttl)

    async def entries(self, session_id: str) -> list[LogEntry]:
        """Return the whole transcript in order."""
        raw = await self._redis.lrange(self._key(session_id), 0, -1)
        entries: list[LogEntry] = []
        for item in raw:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            record = json.loads(item)
            entries.append(LogEntry(role=record["role"], text=record["text"]))
        return entries
