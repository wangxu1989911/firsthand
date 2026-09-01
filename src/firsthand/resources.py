"""Process-wide resources: the pool, the Redis client, and the stores on top."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from firsthand.config import Settings
from firsthand.storage.postgres_vector import PostgresVectorStore
from firsthand.storage.redis_state import RedisStateStore

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from psycopg_pool import AsyncConnectionPool
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: A readiness probe answers fast or not at all. Waiting the pool's default
#: 30s means a busy-but-healthy database reads as down, every instance
#: de-registers at once, and the load spike that caused it gets worse.
READINESS_TIMEOUT_SECONDS = 2.0


class AppResources:
    """Owns the connections and hands out the two §3 store interfaces."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        redis: Redis,
        *,
        embedding_dimensions: int,
        state_ttl_seconds: int,
    ) -> None:
        self._pool = pool
        self._redis = redis
        self.vector_store = PostgresVectorStore(pool, dimensions=embedding_dimensions)
        self.state_store = RedisStateStore(redis, default_ttl_seconds=state_ttl_seconds)

    @classmethod
    def from_settings(cls, settings: Settings) -> AppResources:
        """Build the real clients. Constructing them opens no connection yet."""
        from psycopg_pool import AsyncConnectionPool
        from redis.asyncio import Redis

        pool = AsyncConnectionPool(
            settings.database_url,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
            open=False,
        )
        # Timeouts are not optional here: with none, a failover or a reaped idle
        # connection leaves ping() blocking forever on a half-open socket, so
        # /readyz never answers at all rather than answering 503.
        redis = Redis.from_url(
            settings.redis_url,
            socket_timeout=settings.redis_timeout_seconds,
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_keepalive=True,
            health_check_interval=30,
        )
        return cls(
            pool,
            redis,
            embedding_dimensions=settings.embedding_dimensions,
            state_ttl_seconds=settings.state_ttl_seconds,
        )

    async def open(self) -> None:
        """Connect, then make sure the pgvector schema exists."""
        await self._pool.open(wait=True)
        await self.vector_store.ensure_schema()

    async def close(self) -> None:
        """Release both connections; a failure to close one still closes the other."""
        try:
            await self._pool.close()
        finally:
            await self._redis.aclose()

    async def check(self) -> dict[str, Any]:
        """Readiness probe: does each dependency answer?

        Reports only ok/error per dependency. The driver's own message names
        internal hosts, ports, and usernames, and /readyz is unauthenticated
        (§8.7) — so the detail goes to the log, where an operator can see it,
        and never into the response body.
        """
        checks: dict[str, Any] = {}
        try:
            async with self._pool.connection(timeout=READINESS_TIMEOUT_SECONDS) as conn:
                await conn.execute("SELECT 1")
            checks["postgres"] = "ok"
        except Exception:
            logger.exception("readiness check failed for postgres")
            checks["postgres"] = "error"
        try:
            await self._redis.ping()
            checks["redis"] = "ok"
        except Exception:
            logger.exception("readiness check failed for redis")
            checks["redis"] = "error"
        return checks
