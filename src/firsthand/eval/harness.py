"""Score the dedup logic against the vendored labels (design doc §8.4).

``evaluate`` embeds every issue with the offline embedder, predicts a duplicate
for every pair at or above the threshold, and compares that to the gold pairs.
The CI stage (``python -m firsthand.eval``) fails if precision or recall drops
below the committed baseline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from firsthand.eval.dataset import IssueRecord, gold_pairs
from firsthand.eval.embedding import cosine, embed_text

Embedder = Callable[[str], list[float]]

#: The eval embedder is lexical, so its similarity scale is compressed relative
#: to a semantic model — the production ``DUPLICATE_SIMILARITY_THRESHOLD`` (0.9)
#: would score every pair a non-match here. This is the offline-eval operating
#: point, chosen on a stable plateau of the dataset's score distribution.
EVAL_THRESHOLD = 0.5


@dataclass(frozen=True)
class EvalResult:
    """Confusion counts and the rates derived from them."""

    threshold: float
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 1.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 1.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "threshold": round(self.threshold, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def evaluate(
    records: Sequence[IssueRecord],
    *,
    threshold: float = EVAL_THRESHOLD,
    embedder: Embedder = embed_text,
) -> EvalResult:
    """Run the dedup rule over every pair and count hits against the labels."""
    vectors = {record.id: embedder(record.text) for record in records}
    ids = [record.id for record in records]
    gold = gold_pairs(records)

    predicted: set[frozenset[str]] = set()
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            if cosine(vectors[left], vectors[right]) >= threshold:
                predicted.add(frozenset({left, right}))

    true_positives = len(predicted & gold)
    return EvalResult(
        threshold=threshold,
        true_positives=true_positives,
        false_positives=len(predicted) - true_positives,
        false_negatives=len(gold) - true_positives,
    )
