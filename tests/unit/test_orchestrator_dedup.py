"""Dedup measures similarity and applies the §2 threshold — it decides nothing else."""

from __future__ import annotations

import pytest
from tests.support import InMemoryVectorStore, embedding_entry

from firsthand.contracts import DUPLICATE_SIMILARITY_THRESHOLD
from firsthand.llm import RecordedLLM
from firsthand.orchestrator.dedup import embed_one, index_request, nearest, pick_duplicate
from firsthand.storage.base import Match


async def test_embed_one_unwraps_a_single_vector() -> None:
    llm = RecordedLLM(embeddings=embedding_entry("hi", [1.0, 0.0]))
    assert await embed_one(llm, "hi") == [1.0, 0.0]


async def test_embed_one_rejects_a_wrong_count() -> None:
    class _Bad:
        async def structured(self, **_kw: object) -> object:  # pragma: no cover - unused
            raise AssertionError

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return []

    with pytest.raises(ValueError, match="returned 0 vectors"):
        await embed_one(_Bad(), "hi")  # type: ignore[arg-type]


async def test_nearest_excludes_the_callers_own_prior_row() -> None:
    store = InMemoryVectorStore()
    await store.upsert("s-self", [1.0, 0.0], {})
    await store.upsert("s-other", [1.0, 0.0], {"ticket_id": "PAY-2"})
    llm = RecordedLLM(embeddings=embedding_entry("q", [1.0, 0.0]))

    matches = await nearest(llm, store, "q", exclude_id="s-self", k=5)
    assert [m.id for m in matches] == ["s-other"]


async def test_nearest_without_exclusion_returns_k() -> None:
    store = InMemoryVectorStore()
    for i in range(4):
        await store.upsert(f"s-{i}", [1.0, 0.0], {})
    llm = RecordedLLM(embeddings=embedding_entry("q", [1.0, 0.0]))
    assert len(await nearest(llm, store, "q", k=2)) == 2


def test_pick_duplicate_needs_a_match_over_the_threshold() -> None:
    assert pick_duplicate([]) is None
    below = Match(id="x", score=DUPLICATE_SIMILARITY_THRESHOLD - 0.01, metadata={})
    assert pick_duplicate([below]) is None


def test_pick_duplicate_prefers_the_metadata_ticket_id_and_clamps_similarity() -> None:
    hit = Match(id="s-42", score=1.0, metadata={"ticket_id": "PAY-7"})
    dup = pick_duplicate([hit])
    assert dup is not None
    assert dup.ticket_id == "PAY-7"
    assert dup.similarity == 1.0

    no_ticket = Match(id="s-99", score=DUPLICATE_SIMILARITY_THRESHOLD, metadata={})
    dup2 = pick_duplicate([no_ticket])
    assert dup2 is not None
    assert dup2.ticket_id == "s-99"


async def test_index_request_upserts_the_embedding_and_metadata() -> None:
    store = InMemoryVectorStore()
    llm = RecordedLLM(embeddings=embedding_entry("body", [0.0, 1.0]))
    await index_request(llm, store, request_id="s-1", text="body", metadata={"status": "filed"})
    assert store.rows["s-1"] == ([0.0, 1.0], {"status": "filed"})
