"""Admin auth: argon2id hashing, signed Redis sessions, the user store, bootstrap."""

from __future__ import annotations

from typing import Any, cast

import pytest
from tests.fakes import FakeRedis

from firsthand.auth import (
    AdminSessionStore,
    AdminUserStore,
    CookieSigner,
    bootstrap_admin,
    hash_password,
    verify_password,
)
from firsthand.contracts import AdminUser

# --------------------------------------------------------------------- passwords


def test_hash_is_argon2id_and_verifies() -> None:
    digest = hash_password("hunter2-hunter2")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, "hunter2-hunter2")


def test_hash_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        hash_password("")


def test_verify_is_false_for_wrong_password() -> None:
    assert not verify_password(hash_password("right-password"), "wrong-password")


def test_verify_is_false_for_empty_candidate() -> None:
    assert not verify_password(hash_password("right-password"), "")


def test_verify_is_false_for_a_malformed_stored_hash() -> None:
    assert not verify_password("not-an-argon2-hash", "whatever")


# ---------------------------------------------------------------------- signer


def test_signer_round_trips() -> None:
    signer = CookieSigner("k")
    assert signer.unsign(signer.sign("abc")) == "abc"


def test_signer_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        CookieSigner("")


@pytest.mark.parametrize("bad", [None, "no-dot", "too.many.dots", "abc.deadbeef"])
def test_signer_rejects_tampering(bad: str | None) -> None:
    assert CookieSigner("k").unsign(bad) is None


# ----------------------------------------------------------------- session store


def test_session_store_rejects_a_nonpositive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        AdminSessionStore(cast(Any, FakeRedis()), CookieSigner("k"), ttl_seconds=0)


async def test_a_session_is_created_signed_and_resolves() -> None:
    redis = FakeRedis()
    store = AdminSessionStore(cast(Any, redis), CookieSigner("k"), ttl_seconds=60)

    cookie = await store.create("admin")
    assert "." in cookie
    session = await store.resolve(cookie)
    assert session is not None
    assert session.username == "admin"
    assert next(iter(redis.store.values()))[1] == 60


async def test_resolve_is_none_for_a_bad_signature() -> None:
    store = AdminSessionStore(cast(Any, FakeRedis()), CookieSigner("k"), ttl_seconds=60)
    assert await store.resolve("forged.signature") is None


async def test_resolve_is_none_when_the_record_has_expired() -> None:
    redis = FakeRedis()
    store = AdminSessionStore(cast(Any, redis), CookieSigner("k"), ttl_seconds=60)
    cookie = await store.create("admin")
    redis.store.clear()
    assert await store.resolve(cookie) is None


async def test_resolve_decodes_a_bytes_reply() -> None:
    redis = FakeRedis(raw_as_bytes=True)
    store = AdminSessionStore(cast(Any, redis), CookieSigner("k"), ttl_seconds=60)
    cookie = await store.create("admin")
    session = await store.resolve(cookie)
    assert session is not None and session.username == "admin"


async def test_destroy_removes_the_record_and_ignores_a_bad_cookie() -> None:
    redis = FakeRedis()
    store = AdminSessionStore(cast(Any, redis), CookieSigner("k"), ttl_seconds=60)
    cookie = await store.create("admin")
    await store.destroy("garbage")  # no-op, unsigns to None
    assert await store.resolve(cookie) is not None
    await store.destroy(cookie)
    assert await store.resolve(cookie) is None


# ------------------------------------------------------------------- user store


async def test_user_store_round_trips_and_reports_absence() -> None:
    redis = FakeRedis()
    store = AdminUserStore(cast(Any, redis))
    assert await store.get("admin") is None
    assert not await store.any_exists()

    await store.put(AdminUser(username="admin", password_hash="h"))
    assert await store.any_exists()
    got = await store.get("admin")
    assert got is not None and got.username == "admin"


async def test_user_store_decodes_a_bytes_reply() -> None:
    redis = FakeRedis(raw_as_bytes=True)
    store = AdminUserStore(cast(Any, redis))
    await store.put(AdminUser(username="admin", password_hash="h"))
    got = await store.get("admin")
    assert got is not None and got.username == "admin"


# -------------------------------------------------------------------- bootstrap


async def test_bootstrap_creates_the_first_admin_once() -> None:
    redis = FakeRedis()
    store = AdminUserStore(cast(Any, redis))

    password = await bootstrap_admin(store)
    assert password is not None and len(password) == 20
    user = await store.get("admin")
    assert user is not None
    assert user.must_change_password
    assert verify_password(user.password_hash, password)

    assert await bootstrap_admin(store) is None


async def test_bootstrap_logs_the_password_once_at_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = AdminUserStore(cast(Any, FakeRedis()))
    with caplog.at_level("WARNING"):
        password = await bootstrap_admin(store)
    assert password is not None
    assert password in caplog.text
    assert any(record.levelname == "WARNING" for record in caplog.records)
