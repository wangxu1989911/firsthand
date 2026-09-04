"""Chunk pages into passages and rank them against a query.

The ranker is a small, self-contained BM25 rather than an embedding model: it is
fully deterministic, needs no network and no LLM dependency, and a design-doc
search is short-query keyword-shaped work that lexical scoring handles well. The
scoring is standard Okapi BM25 with a non-negative IDF so a passage never earns
a negative score for containing a very common term.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from firsthand.connectors.docs.models import DocPage, Passage

#: Target upper bound on a passage, in characters. Long enough to keep a decision
#: and its rationale together, short enough that a hit points at one idea.
DEFAULT_MAX_CHARS = 500

_TOKEN = re.compile(r"[a-z0-9]+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

_BM25_K1 = 1.5
_BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric runs — the same rule for documents and queries."""
    return _TOKEN.findall(text.lower())


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Break an over-long paragraph on sentence boundaries, packing greedily.

    Only called when ``paragraph`` is already longer than ``max_chars`` and has
    real content, so at least one sentence survives the strip and ``current`` is
    non-empty by the final append.
    """
    chunks: list[str] = []
    current = ""
    for raw in _SENTENCE_BREAK.split(paragraph):
        sentence = raw.strip()
        if not sentence:
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    chunks.append(current)
    return chunks


def chunk_page(page: DocPage, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[Passage]:
    """Split one page into ordered, non-empty passages.

    Paragraphs are the unit; a paragraph longer than ``max_chars`` is split
    further on sentence boundaries so a single wall-of-text section still
    produces citable passages.
    """
    passages: list[Passage] = []
    for block in _PARAGRAPH_BREAK.split(page.text):
        collapsed = " ".join(block.split())
        if not collapsed:
            continue
        pieces = (
            [collapsed]
            if len(collapsed) <= max_chars
            else _split_long_paragraph(collapsed, max_chars)
        )
        for piece in pieces:
            passages.append(Passage(page=page, text=piece, ordinal=len(passages)))
    return passages


@dataclass(frozen=True)
class _Scored:
    passage: Passage
    score: float


class Bm25Index:
    """An immutable BM25 index over a fixed set of passages."""

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = passages
        self._tokens = [tokenize(p.text) for p in passages]
        self._lengths = [len(toks) for toks in self._tokens]
        self._counts = [Counter(toks) for toks in self._tokens]
        total = sum(self._lengths)
        # ``or 1.0`` keeps the length-normalisation term finite when every
        # passage tokenised to nothing (e.g. punctuation-only sections).
        self._avgdl = (total / len(passages)) if passages else 1.0
        self._avgdl = self._avgdl or 1.0
        self._idf = self._compute_idf()

    def _compute_idf(self) -> dict[str, float]:
        n = len(self._passages)
        doc_freq: Counter[str] = Counter()
        for counts in self._counts:
            doc_freq.update(counts.keys())
        return {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in doc_freq.items()
        }

    def _score(self, query_terms: list[str], index: int) -> float:
        counts = self._counts[index]
        dl = self._lengths[index]
        norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / self._avgdl)
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            score += self._idf.get(term, 0.0) * (tf * (_BM25_K1 + 1)) / (tf + norm)
        return score

    def rank(self, query: str, *, limit: int) -> list[Passage]:
        """Return up to ``limit`` passages that share a term with the query.

        A passage that shares no term scores zero and is dropped — that is the
        explicit no-match signal the connector turns into ``evidence=[]``.
        """
        if limit <= 0 or not self._passages:
            return []
        query_terms = list(dict.fromkeys(tokenize(query)))
        if not query_terms:
            return []
        scored = [
            _Scored(passage=self._passages[i], score=self._score(query_terms, i))
            for i in range(len(self._passages))
        ]
        hits = [s for s in scored if s.score > 0.0]
        hits.sort(key=lambda s: (-s.score, s.passage.page.url, s.passage.ordinal))
        return [s.passage for s in hits[:limit]]
