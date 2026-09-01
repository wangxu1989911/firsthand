"""The same operations the unit tests fake, run against the real databases."""

from __future__ import annotations

import pytest

from firsthand.contracts import IssueDraft
from firsthand.storage import PostgresVectorStore, RedisStateStore


async def test_similar_meaning_ranks_above_unrelated(vector_store: PostgresVectorStore) -> None:
    await vector_store.upsert("PAY-412", [1.0, 0.0, 0.0], {"title": "checkout is slow"})
    await vector_store.upsert("PAY-77", [0.9, 0.1, 0.0], {"title": "payment page lags"})
    await vector_store.upsert("DOC-3", [0.0, 0.0, 1.0], {"title": "typo in the readme"})

    matches = await vector_store.search([1.0, 0.05, 0.0], k=3)

    assert [match.id for match in matches[:2]] == ["PAY-412", "PAY-77"]
    assert matches[0].score > matches[-1].score
    assert matches[0].metadata["title"] == "checkout is slow"


async def test_upsert_replaces_rather_than_duplicating(vector_store: PostgresVectorStore) -> None:
    await vector_store.upsert("PAY-412", [1.0, 0.0, 0.0], {"title": "first"})
    await vector_store.upsert("PAY-412", [0.0, 1.0, 0.0], {"title": "second"})

    matches = await vector_store.search([0.0, 1.0, 0.0], k=5)
    assert len(matches) == 1
    assert matches[0].metadata["title"] == "second"


async def test_a_draft_survives_a_round_trip_through_redis(
    state_store: RedisStateStore, draft: IssueDraft
) -> None:
    await state_store.set(draft.conversation.session_id, draft)
    assert await state_store.get(draft.conversation.session_id) == draft


async def test_an_abandoned_draft_expires_on_its_own(
    state_store: RedisStateStore, draft: IssueDraft
) -> None:
    import asyncio

    await state_store.set("s-abandoned", draft, ttl_seconds=1)
    await asyncio.sleep(1.2)
    assert await state_store.get("s-abandoned") is None


async def test_ensure_schema_is_idempotent(vector_store: PostgresVectorStore) -> None:
    """Startup runs it on every boot, so a second call must be a no-op."""
    await vector_store.ensure_schema()
    await vector_store.upsert("PAY-1", [1.0, 0.0, 0.0], {})
    assert len(await vector_store.search([1.0, 0.0, 0.0], k=1)) == 1


async def test_a_width_change_is_caught_at_startup(vector_store: PostgresVectorStore) -> None:
    """Verifies against real pgvector that we read the stored width correctly."""
    from firsthand.storage import PostgresVectorStore as Store

    rewidened = Store(vector_store._pool, dimensions=768, table="issue_embeddings_it")
    with pytest.raises(RuntimeError, match=r"vector\(3\)"):
        await rewidened.ensure_schema()
