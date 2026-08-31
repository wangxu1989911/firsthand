"""The default StateStore: Redis, one key per session (design doc §3, §8.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from firsthand.contracts.draft import IssueDraft

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from redis.asyncio import Redis

DEFAULT_PREFIX = "firsthand:draft"
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class RedisStateStore:
    """Per-conversation drafts, held outside the process so any instance can serve.

    The TTL is the point of the design, not an afterthought: an abandoned
    "gathering info" draft expires on its own instead of accumulating forever.
    """

    def __init__(
        self,
        client: Redis,
        *,
        prefix: str = DEFAULT_PREFIX,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive")
        self._client = client
        self._prefix = prefix
        self._default_ttl = default_ttl_seconds

    def key(self, session_id: str) -> str:
        """The Redis key one session's draft lives under."""
        if not session_id:
            raise ValueError("session_id must not be empty")
        return f"{self._prefix}:{session_id}"

    async def get(self, session_id: str) -> IssueDraft | None:
        """Return the stored draft, or ``None`` if it never existed or expired."""
        raw = await self._client.get(self.key(session_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return IssueDraft.model_validate_json(raw)

    async def set(
        self,
        session_id: str,
        draft: IssueDraft,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store the draft, refreshing its expiry on every write."""
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        await self._client.set(self.key(session_id), draft.model_dump_json(), ex=ttl)
