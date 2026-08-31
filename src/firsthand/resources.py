"""Process-wide resources: the pool, the Redis client, and the stores on top."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from firsthand.config import Settings
from firsthand.storage.postgres_vector import PostgresVectorStore
from firsthand.storage.redis_state import RedisStateStore

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from psycopg_pool import AsyncConnectionPool
    from redis.asyncio import Redis


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
        redis = Redis.from_url(settings.redis_url)
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
        """Readiness probe: both dependencies answer, or the caller gets the reason."""
        checks: dict[str, Any] = {}
        try:
            async with self._pool.connection() as conn:
                await conn.execute("SELECT 1")
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = f"error: {exc}"
        try:
            await self._redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
        return checks
