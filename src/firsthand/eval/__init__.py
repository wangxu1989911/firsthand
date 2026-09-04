"""Offline dedup eval harness (design doc §8.4).

Runs entirely against the vendored, duplicate-labelled issue set with a
deterministic lexical embedder — no network, reproducible on every machine.
``python -m firsthand.eval`` gates CI against ``baseline.json``.
"""

from firsthand.eval.dataset import IssueRecord, gold_pairs, load_dataset
from firsthand.eval.embedding import EVAL_DIMENSIONS, cosine, embed_text
from firsthand.eval.harness import EVAL_THRESHOLD, EvalResult, evaluate

__all__ = [
    "EVAL_DIMENSIONS",
    "EVAL_THRESHOLD",
    "EvalResult",
    "IssueRecord",
    "cosine",
    "embed_text",
    "evaluate",
    "gold_pairs",
    "load_dataset",
]
