"""The default VectorStore: Postgres + pgvector (design doc §3, §6, §8.6)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from firsthand.storage.base import Match

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from psycopg_pool import AsyncConnectionPool

DEFAULT_TABLE = "issue_embeddings"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_identifier(name: str) -> str:
    """Table names are interpolated, so they are never allowed to be free text."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"not a valid SQL identifier: {name!r}")
    return name


def to_vector_literal(embedding: list[float]) -> str:
    """pgvector's text input form — avoids needing a registered type adapter."""
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


class PostgresVectorStore:
    """pgvector-backed nearest-neighbour index over request embeddings.

    Cosine distance is what the index is built on, so ``Match.score`` is
    ``1 - distance``: 1.0 is identical meaning, 0.0 is unrelated.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        dimensions: int,
        table: str = DEFAULT_TABLE,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._pool = pool
        self._dimensions = dimensions
        self._table = _check_identifier(table)

    @property
    def dimensions(self) -> int:
        """Embedding width this index was created for."""
        return self._dimensions

    async def ensure_schema(self) -> None:
        """Create the extension, table, and index if they are not there yet.

        Runs at startup rather than as a container init hook because the vector
        width comes from configuration (§8.3: config arrives via environment).
        """
        async with self._pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id TEXT PRIMARY KEY,"
                f" embedding vector({self._dimensions}) NOT NULL,"
                " metadata JSONB NOT NULL DEFAULT '{}'::jsonb,"
                " updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_embedding_cosine_idx"
                f" ON {self._table} USING hnsw (embedding vector_cosine_ops)"
            )

    def _validate(self, embedding: list[float]) -> str:
        if len(embedding) != self._dimensions:
            raise ValueError(
                f"embedding has {len(embedding)} dimensions, index expects {self._dimensions}"
            )
        return to_vector_literal(embedding)

    async def upsert(
        self,
        id: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """Insert or replace one embedding, keyed by ticket or draft id."""
        vector = self._validate(embedding)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO {self._table} (id, embedding, metadata, updated_at)"
                " VALUES (%s, %s::vector, %s::jsonb, now())"
                " ON CONFLICT (id) DO UPDATE SET"
                " embedding = EXCLUDED.embedding,"
                " metadata = EXCLUDED.metadata,"
                " updated_at = now()",
                (id, vector, json.dumps(metadata)),
            )

    async def search(self, embedding: list[float], k: int) -> list[Match]:
        """Return the ``k`` most similar entries, most similar first."""
        if k <= 0:
            raise ValueError("k must be positive")
        vector = self._validate(embedding)
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                f"SELECT id, metadata, 1 - (embedding <=> %s::vector) AS score"
                f" FROM {self._table}"
                " ORDER BY embedding <=> %s::vector"
                " LIMIT %s",
                (vector, vector, k),
            )
            rows = await cursor.fetchall()
        return [
            Match(id=row[0], score=float(row[2]), metadata=_as_metadata(row[1])) for row in rows
        ]


def _as_metadata(value: Any) -> dict[str, Any]:
    """psycopg hands back a dict for jsonb; a driver returning text still works."""
    if isinstance(value, str):
        decoded: dict[str, Any] = json.loads(value)
        return decoded
    return dict(value or {})
