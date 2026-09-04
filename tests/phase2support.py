"""Shared helpers for the Phase 2 web-chat and admin tests."""

from __future__ import annotations

from typing import Any, cast

import httpx
from tests.fakes import FakePool, FakeRedis

from firsthand.app import create_app
from firsthand.auth import AdminUserStore, hash_password
from firsthand.config import Settings
from firsthand.contracts import AdminUser
from firsthand.resources import AppResources

SECRET = "test-secret-key-for-phase2"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "secret_key": SECRET,
        "state_ttl_seconds": 3600,
        "admin_session_ttl_seconds": 1800,
    }
    base.update(overrides)
    return Settings(**base)


def make_resources(redis: FakeRedis) -> AppResources:
    return AppResources(
        cast(Any, FakePool()), cast(Any, redis), embedding_dimensions=3, state_ttl_seconds=3600
    )


def make_app(
    redis: FakeRedis | None = None, *, settings: Settings | None = None
) -> tuple[Any, FakeRedis]:
    redis = redis or FakeRedis()
    app = create_app(settings or make_settings(), resources=make_resources(redis))
    return app, redis


def client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def seed_admin(
    redis: FakeRedis,
    *,
    username: str = "admin",
    password: str = "correct-horse-battery-staple",
    must_change_password: bool = False,
) -> None:
    """Put an admin straight into Redis so bootstrap is a no-op for the test."""
    await AdminUserStore(cast(Any, redis)).put(
        AdminUser(
            username=username,
            password_hash=hash_password(password),
            must_change_password=must_change_password,
        )
    )


async def login(
    http: httpx.AsyncClient, username: str = "admin", password: str = "correct-horse-battery-staple"
) -> httpx.Response:
    return await http.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
