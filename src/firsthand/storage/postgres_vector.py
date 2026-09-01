"""The default VectorStore: Postgres + pgvector (design doc §3, §6, §8.6)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from firsthand.storage.base import Match

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "issue_embeddings"

#: pgvector refuses an HNSW index above this width. A wider index is still a
#: usable table — it just falls back to an exact scan, which beats refusing to
#: start over a configuration value the README advertises as free to set.
MAX_HNSW_DIMENSIONS = 2000


def _advisory_lock_key(table: str) -> int:
    """A stable per-table key, so two tables never serialize against each other."""
    digest = hashlib.blake2b(table.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


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
        A table that already exists at a *different* width is the case
        ``IF NOT EXISTS`` cannot handle, so it is checked explicitly.
        """
        async with self._pool.connection() as conn:
            # IF NOT EXISTS is not race-safe: several instances starting at once
            # (a cold-start burst, or a crash-loop restarting) collide on the
            # catalog's unique indexes and all but one die. The lock is held to
            # the end of this transaction, so the losers wait and then no-op.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(%s)", (_advisory_lock_key(self._table),)
            )
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id TEXT PRIMARY KEY,"
                f" embedding vector({self._dimensions}) NOT NULL,"
                " metadata JSONB NOT NULL DEFAULT '{}'::jsonb,"
                " updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await self._check_existing_width(conn)
            if self._dimensions <= MAX_HNSW_DIMENSIONS:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._table}_embedding_cosine_idx"
                    f" ON {self._table} USING hnsw (embedding vector_cosine_ops)"
                )
            else:
                logger.warning(
                    "embedding width %d exceeds the %d-dimension HNSW limit; "
                    "%s will use exact search instead of an index",
                    self._dimensions,
                    MAX_HNSW_DIMENSIONS,
                    self._table,
                )

    async def _check_existing_width(self, conn: Any) -> None:
        """Fail loudly at startup if the table was built for a different width.

        Otherwise the mismatch surfaces on the first write, deep inside Postgres,
        long after the deploy that caused it looked successful.
        """
        cursor = await conn.execute(
            "SELECT atttypmod FROM pg_attribute"
            " WHERE attrelid = %s::regclass AND attname = 'embedding'",
            (self._table,),
        )
        rows = await cursor.fetchall()
        if not rows:  # a driver that reports nothing tells us nothing to act on
            return
        existing = int(rows[0][0])
        if existing > 0 and existing != self._dimensions:
            raise RuntimeError(
                f"{self._table} was created with vector({existing}) but this process is"
                f" configured for {self._dimensions} dimensions —"
                " re-embed into a new table rather than writing mixed widths"
            )

    def _validate(self, embedding: list[float]) -> str:
        if len(embedding) != self._dimensions:
            raise ValueError(
                f"embedding has {len(embedding)} dimensions, index expects {self._dimensions}"
            )
        # A NaN or inf would serialize to a literal pgvector rejects, and a
        # NaN distance makes the ORDER BY ranking arbitrary rather than wrong
        # in any detectable way.
        if not all(math.isfinite(value) for value in embedding):
            raise ValueError("embedding contains a non-finite value")
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
