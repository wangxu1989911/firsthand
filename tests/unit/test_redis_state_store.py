"""RedisStateStore against a fake driver: keys, TTLs, and round-tripping."""

from __future__ import annotations

from typing import Any, cast

import pytest
from tests.fakes import FakeRedis

from firsthand.contracts import IssueDraft
from firsthand.storage import RedisStateStore


def _store(redis: FakeRedis, **kwargs: Any) -> RedisStateStore:
    return RedisStateStore(cast(Any, redis), **kwargs)


def test_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="default_ttl_seconds must be positive"):
        _store(FakeRedis(), default_ttl_seconds=0)


def test_keys_are_namespaced_and_never_empty() -> None:
    store = _store(FakeRedis())
    assert store.key("s-1") == "firsthand:draft:s-1"
    with pytest.raises(ValueError, match="session_id must not be empty"):
        store.key("")


async def test_a_missing_session_reads_back_as_none() -> None:
    assert await _store(FakeRedis()).get("s-unknown") is None


async def test_a_draft_round_trips_and_expires_on_its_own(draft: IssueDraft) -> None:
    redis = FakeRedis()
    store = _store(redis, default_ttl_seconds=60)

    await store.set("s-1", draft)
    assert await store.get("s-1") == draft
    assert redis.store["firsthand:draft:s-1"][1] == 60


async def test_a_per_write_ttl_overrides_the_default(draft: IssueDraft) -> None:
    redis = FakeRedis()
    await _store(redis, default_ttl_seconds=60).set("s-1", draft, ttl_seconds=5)
    assert redis.store["firsthand:draft:s-1"][1] == 5


async def test_a_bytes_reply_decodes_the_same_way(draft: IssueDraft) -> None:
    redis = FakeRedis(raw_as_bytes=True)
    store = _store(redis)
    await store.set("s-1", draft)
    assert await store.get("s-1") == draft


async def test_a_non_expiring_write_is_refused(draft: IssueDraft) -> None:
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        await _store(FakeRedis()).set("s-1", draft, ttl_seconds=0)


async def test_an_unreadable_stored_draft_reads_back_as_none() -> None:
    """A draft written by a build with a different IssueDraft starts over, not 500s."""
    redis = FakeRedis()
    redis.store["firsthand:draft:s-1"] = ('{"conversation": {"surface": "web"}}', 60)
    assert await _store(redis).get("s-1") is None
