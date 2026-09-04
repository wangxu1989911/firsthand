"""The two storage interfaces the orchestrator is written against (§3)."""

from __future__ import annotations

import math
from typing import Any, Protocol

from pydantic import Field, field_validator

from firsthand.contracts.draft import Contract, IssueDraft


class Match(Contract):
    """One nearest-neighbour hit.

    ``score`` is cosine similarity, so it ranges over ``[-1, 1]`` — 1.0 is
    identical meaning, 0.0 unrelated, and negative values are opposed. Only the
    top of that range is duplicate-shaped; see ``DUPLICATE_SIMILARITY_THRESHOLD``.
    """

    id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float) -> float:
        """A NaN score sorts arbitrarily, which makes bad ranking undetectable."""
        if not math.isfinite(value):
            raise ValueError("score must be a finite number")
        return value


class VectorStore(Protocol):
    """Nearest-neighbour index over request embeddings."""

    async def upsert(
        self,
        id: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """Insert or replace one embedding and its metadata."""
        ...

    async def search(self, embedding: list[float], k: int) -> list[Match]:
        """Return the ``k`` nearest neighbours, most similar first."""
        ...


class StateStore(Protocol):
    """Per-session draft state, external to the process (§8.3)."""

    async def get(self, session_id: str) -> IssueDraft | None:
        """Return the stored draft, or ``None`` when there is none (or it expired)."""
        ...

    async def set(
        self,
        session_id: str,
        draft: IssueDraft,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store the draft, expiring it after ``ttl_seconds``."""
        ...
