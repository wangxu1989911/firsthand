"""Integration tests run against the real containers, or skip cleanly.

Bring the stack up with ./scripts/dev-up.sh and point the env at it with
`eval "$(./scripts/dev-env.sh)"`. CI wires the same two services directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from firsthand.config import get_settings
from firsthand.storage import PostgresVectorStore, RedisStateStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool() -> AsyncIterator[object]:
    psycopg_pool = pytest.importorskip("psycopg_pool")
    settings = get_settings()
    pool = psycopg_pool.AsyncConnectionPool(
        settings.database_url, min_size=1, max_size=2, open=False
    )
    try:
        await pool.open(wait=True, timeout=5)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"postgres not reachable: {exc}")
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def vector_store(pool: object) -> AsyncIterator[PostgresVectorStore]:
    store = PostgresVectorStore(pool, dimensions=3, table="issue_embeddings_it")  # type: ignore[arg-type]
    await store.ensure_schema()
    async with pool.connection() as conn:  # type: ignore[attr-defined]
        await conn.execute("TRUNCATE issue_embeddings_it")
    yield store


@pytest.fixture
async def state_store() -> AsyncIterator[RedisStateStore]:
    redis_asyncio = pytest.importorskip("redis.asyncio")
    settings = get_settings()
    client = redis_asyncio.Redis.from_url(settings.redis_url)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment-dependent
        await client.aclose()
        pytest.skip(f"redis not reachable: {exc}")
    try:
        yield RedisStateStore(client, prefix="firsthand:it", default_ttl_seconds=60)
    finally:
        await client.aclose()
