"""Embed a request, look for its nearest neighbours, decide if it is a duplicate.

The rule is the design doc's (§2): at or above ``DUPLICATE_SIMILARITY_THRESHOLD``
cosine similarity a neighbour is treated as the same request. Below it, the
neighbours are still useful context but the request stands on its own. This
module only measures similarity — whether a duplicate should be linked or
escalated is the orchestrator's call.
"""

from __future__ import annotations

from firsthand.contracts import DUPLICATE_SIMILARITY_THRESHOLD, DuplicateOf
from firsthand.llm.base import LLMClient
from firsthand.storage.base import Match, VectorStore

#: How many neighbours to pull back for the duplicate check and for context.
DEFAULT_NEIGHBOURS = 5


async def embed_one(llm: LLMClient, text: str) -> list[float]:
    """Embed a single string, raising if the client hands back the wrong count."""
    vectors = await llm.embed([text])
    if len(vectors) != 1:
        raise ValueError(f"embed returned {len(vectors)} vectors for one input")
    return vectors[0]


async def nearest(
    llm: LLMClient,
    store: VectorStore,
    text: str,
    *,
    exclude_id: str | None = None,
    k: int = DEFAULT_NEIGHBOURS,
) -> list[Match]:
    """The ``k`` closest indexed requests, most similar first, minus ``exclude_id``.

    ``exclude_id`` keeps a re-run of the same conversation from matching the row
    it wrote on the previous turn.
    """
    embedding = await embed_one(llm, text)
    matches = await store.search(embedding, k + 1 if exclude_id else k)
    if exclude_id is not None:
        matches = [match for match in matches if match.id != exclude_id]
    return matches[:k]


def pick_duplicate(matches: list[Match]) -> DuplicateOf | None:
    """Promote the top match to a duplicate iff it clears the threshold (§2)."""
    if not matches:
        return None
    best = matches[0]
    if best.score < DUPLICATE_SIMILARITY_THRESHOLD:
        return None
    ticket_id = str(best.metadata.get("ticket_id") or best.id)
    # ``score`` is cosine similarity in [-1, 1]; DuplicateOf.similarity is a
    # [0, 1] probability, so a rare negative-but-thresholded value is clamped.
    similarity = min(max(best.score, 0.0), 1.0)
    return DuplicateOf(ticket_id=ticket_id, similarity=similarity)


async def index_request(
    llm: LLMClient,
    store: VectorStore,
    *,
    request_id: str,
    text: str,
    metadata: dict[str, str],
) -> None:
    """Embed a request and upsert it so later requests can dedup against it."""
    embedding = await embed_one(llm, text)
    await store.upsert(request_id, embedding, dict(metadata))
