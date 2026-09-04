"""A deterministic, offline embedder for the eval harness (design doc §8.4).

The production dedup path embeds through the LLM provider. The eval suite must
run with no network and byte-identical results on every machine and CI run, so
it substitutes this: a signed hashing bag-of-words projection, L2-normalised.
It is lexical, not semantic — which is the point. The harness measures whether a
change to the *dedup logic* (thresholds, neighbour handling, text preparation)
regresses precision/recall against a fixed baseline; holding the embedder
constant and cheap is what makes that signal clean.
"""

from __future__ import annotations

import hashlib
import math
import re

#: Width of the eval embedding. Small: the dataset is tiny and vendored.
EVAL_DIMENSIONS = 256

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def embed_text(text: str, *, dimensions: int = EVAL_DIMENSIONS) -> list[float]:
    """Project ``text`` to a unit vector via signed feature hashing.

    An empty or all-stopword string has no features; it comes back as a single
    non-zero component so cosine similarity stays defined (the vector store
    makes the same guarantee).
    """
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [component / norm for component in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two equal-length vectors."""
    if len(left) != len(right):
        raise ValueError("vectors differ in length")
    return sum(a * b for a, b in zip(left, right, strict=True))
