"""Shared offline doubles for the Phase 1 unit suite.

Nothing here touches a network. The LLM is always :class:`RecordedLLM` from the
package, keyed through the same prompt-hashing the real fixtures use; the vector
and state stores are tiny in-memory implementations of the §3 protocols.
"""

from __future__ import annotations

import math
from typing import Any

from firsthand.contracts import IssueDraft
from firsthand.llm import RecordedLLM, embedding_key, structured_key
from firsthand.orchestrator.classify import SYSTEM_PROMPT as _CLASSIFY_SYSTEM
from firsthand.orchestrator.scoring import SYSTEM_PROMPT as _SCORE_SYSTEM
from firsthand.orchestrator.scoring import scoring_user_prompt
from firsthand.storage.base import Match


# --- LLM fixture builders ---------------------------------------------------
def classification_entry(redacted_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A recorded Classification completion for exactly ``redacted_text``."""
    key = structured_key("Classification", _CLASSIFY_SYSTEM, redacted_text)
    return {key: payload}


def score_entry(user_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A recorded ScoreJudgement completion for a pre-built user prompt."""
    key = structured_key("ScoreJudgement", _SCORE_SYSTEM, user_prompt)
    return {key: payload}


def embedding_entry(text: str, vector: list[float]) -> dict[str, list[float]]:
    """A recorded embedding for ``text``."""
    return {embedding_key(text): list(vector)}


def scoring_prompt(redacted_text: str, evidence: list[Any], duplicate_of: Any) -> str:
    """Re-export so tests build the exact scoring key without importing internals."""
    return scoring_user_prompt(redacted_text, evidence, duplicate_of)


def recorded_llm(
    *,
    completions: dict[str, Any] | None = None,
    embeddings: dict[str, list[float]] | None = None,
) -> RecordedLLM:
    return RecordedLLM(completions=completions or {}, embeddings=embeddings or {})


# --- storage doubles -------------------------------------------------------
class InMemoryVectorStore:
    """Cosine nearest-neighbour over an in-process dict. Implements ``VectorStore``."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[list[float], dict[str, Any]]] = {}

    async def upsert(self, id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        self.rows[id] = (list(embedding), dict(metadata))

    async def search(self, embedding: list[float], k: int) -> list[Match]:
        scored = [
            Match(id=row_id, score=_cosine(embedding, vector), metadata=meta)
            for row_id, (vector, meta) in self.rows.items()
        ]
        scored.sort(key=lambda match: match.score, reverse=True)
        return scored[:k]


class InMemoryStateStore:
    """Round-trips drafts through JSON, like Redis does, so bugs there surface."""

    def __init__(self) -> None:
        self.blobs: dict[str, str] = {}
        self.set_calls: list[tuple[str, int | None]] = []

    async def get(self, session_id: str) -> IssueDraft | None:
        raw = self.blobs.get(session_id)
        return IssueDraft.model_validate_json(raw) if raw is not None else None

    async def set(self, session_id: str, draft: IssueDraft, ttl_seconds: int | None = None) -> None:
        self.set_calls.append((session_id, ttl_seconds))
        self.blobs[session_id] = draft.model_dump_json()


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    return dot / (ln * rn) if ln and rn else 0.0
