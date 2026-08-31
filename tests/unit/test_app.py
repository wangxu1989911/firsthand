"""The Phase 0 skeleton: it comes up, and it tells the truth about readiness."""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from asgi_lifespan import LifespanManager
from tests.fakes import FakePool, FakeRedis

from firsthand import __version__
from firsthand.app import create_app
from firsthand.config import Settings
from firsthand.resources import AppResources


def _resources(pool: FakePool, redis: FakeRedis) -> AppResources:
    return AppResources(
        cast(Any, pool), cast(Any, redis), embedding_dimensions=3, state_ttl_seconds=30
    )


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_startup_opens_the_stack_and_shutdown_releases_it() -> None:
    pool, redis = FakePool(), FakeRedis()
    app = create_app(Settings(), resources=_resources(pool, redis))

    async with LifespanManager(app):
        assert pool.opened
    assert pool.closed
    assert redis.closed


async def test_healthz_is_liveness_only() -> None:
    app = create_app(Settings(), resources=_resources(FakePool(), FakeRedis()))
    async with LifespanManager(app), await _client(app) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_readyz_is_green_when_both_dependencies_answer() -> None:
    app = create_app(Settings(), resources=_resources(FakePool(), FakeRedis()))
    async with LifespanManager(app), await _client(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


async def test_readyz_is_503_when_a_dependency_is_down() -> None:
    app = create_app(Settings(), resources=_resources(FakePool(), FakeRedis(fail_ping=True)))
    async with LifespanManager(app), await _client(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"].startswith("error:")


async def test_without_injected_resources_the_app_builds_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[AppResources] = []
    pool, redis = FakePool(), FakeRedis()

    def fake_from_settings(settings: Settings) -> AppResources:
        resources = _resources(pool, redis)
        built.append(resources)
        return resources

    monkeypatch.setattr(AppResources, "from_settings", staticmethod(fake_from_settings))
    monkeypatch.setenv("FIRSTHAND_EMBEDDING_DIMENSIONS", "3")

    app = create_app()
    async with LifespanManager(app):
        assert built
    assert pool.closed
