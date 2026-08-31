"""PostgresVectorStore against a fake driver: SQL shape, guards, score mapping."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from tests.fakes import FakePool

from firsthand.storage import PostgresVectorStore
from firsthand.storage.postgres_vector import to_vector_literal


def _store(pool: FakePool, *, dimensions: int = 3) -> PostgresVectorStore:
    return PostgresVectorStore(cast(Any, pool), dimensions=dimensions)


def test_vector_literal_is_pgvectors_text_form() -> None:
    assert to_vector_literal([1, 2.5, -0.75]) == "[1.0,2.5,-0.75]"


def test_dimensions_must_be_positive() -> None:
    with pytest.raises(ValueError, match="dimensions must be positive"):
        _store(FakePool(), dimensions=0)


def test_a_table_name_is_never_free_text() -> None:
    with pytest.raises(ValueError, match="not a valid SQL identifier"):
        PostgresVectorStore(cast(Any, FakePool()), dimensions=3, table="issues; DROP TABLE users")


def test_ensure_schema_creates_extension_table_and_index() -> None:
    pool = FakePool()
    store = _store(pool)
    assert store.dimensions == 3

    import asyncio

    asyncio.run(store.ensure_schema())

    statements = pool.statements
    assert "CREATE EXTENSION IF NOT EXISTS vector" in statements[0]
    assert "CREATE TABLE IF NOT EXISTS issue_embeddings" in statements[1]
    assert "vector(3)" in statements[1]
    assert "USING hnsw (embedding vector_cosine_ops)" in statements[2]


async def test_upsert_replaces_on_conflict() -> None:
    pool = FakePool()
    await _store(pool).upsert("PAY-412", [0.1, 0.2, 0.3], {"title": "checkout slow"})

    sql, params = pool.conn.executed[0]
    assert "ON CONFLICT (id) DO UPDATE SET" in sql
    assert params[0] == "PAY-412"
    assert params[1] == "[0.1,0.2,0.3]"
    assert json.loads(params[2]) == {"title": "checkout slow"}


async def test_search_returns_similarity_ordered_matches() -> None:
    pool = FakePool(rows=[("PAY-412", {"title": "checkout"}, 0.94), ("PAY-77", "{}", 0.31)])
    matches = await _store(pool).search([0.1, 0.2, 0.3], k=2)

    assert [(m.id, m.score) for m in matches] == [("PAY-412", 0.94), ("PAY-77", 0.31)]
    assert matches[0].metadata == {"title": "checkout"}
    assert matches[1].metadata == {}

    sql, params = pool.conn.executed[0]
    assert "1 - (embedding <=> %s::vector) AS score" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert params[2] == 2


async def test_null_metadata_reads_back_as_an_empty_dict() -> None:
    pool = FakePool(rows=[("PAY-1", None, 0.5)])
    assert (await _store(pool).search([0.0, 0.0, 1.0], k=1))[0].metadata == {}


@pytest.mark.parametrize("embedding", [[0.1, 0.2], [0.1, 0.2, 0.3, 0.4]])
async def test_a_wrong_width_embedding_is_refused(embedding: list[float]) -> None:
    store = _store(FakePool())
    with pytest.raises(ValueError, match="index expects 3"):
        await store.upsert("PAY-1", embedding, {})
    with pytest.raises(ValueError, match="index expects 3"):
        await store.search(embedding, k=1)


async def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        await _store(FakePool()).search([0.1, 0.2, 0.3], k=0)
