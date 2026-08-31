"""AppResources wires the drivers to the §3 stores and reports their health."""

from __future__ import annotations

import contextlib
from typing import Any, cast

from tests.fakes import FakePool, FakeRedis

from firsthand.config import Settings
from firsthand.resources import AppResources
from firsthand.storage import PostgresVectorStore, RedisStateStore


def _resources(pool: FakePool, redis: FakeRedis) -> AppResources:
    return AppResources(
        cast(Any, pool),
        cast(Any, redis),
        embedding_dimensions=3,
        state_ttl_seconds=30,
    )


def test_from_settings_builds_real_clients_without_connecting() -> None:
    resources = AppResources.from_settings(
        Settings(
            database_url="postgresql://u:p@localhost:5432/x", redis_url="redis://localhost:6379/0"
        )
    )
    assert isinstance(resources.vector_store, PostgresVectorStore)
    assert isinstance(resources.state_store, RedisStateStore)
    assert resources.vector_store.dimensions == 1536


async def test_open_connects_then_creates_the_schema() -> None:
    pool = FakePool()
    await _resources(pool, FakeRedis()).open()
    assert pool.opened
    assert any("CREATE TABLE IF NOT EXISTS" in sql for sql in pool.statements)


async def test_close_releases_both_clients() -> None:
    pool, redis = FakePool(), FakeRedis()
    await _resources(pool, redis).close()
    assert pool.closed
    assert redis.closed


async def test_redis_is_closed_even_if_the_pool_close_fails() -> None:
    pool, redis = FakePool(), FakeRedis()

    async def boom() -> None:
        raise RuntimeError("pool stuck")

    pool.close = boom  # type: ignore[method-assign]
    with contextlib.suppress(RuntimeError):
        await _resources(pool, redis).close()
    assert redis.closed


async def test_check_reports_both_dependencies_as_ok() -> None:
    assert await _resources(FakePool(), FakeRedis()).check() == {"postgres": "ok", "redis": "ok"}


async def test_check_names_the_failing_dependency() -> None:
    checks = await _resources(FakePool(fail_on_connect=True), FakeRedis(fail_ping=True)).check()
    assert checks["postgres"].startswith("error: connection refused")
    assert checks["redis"].startswith("error: redis down")
