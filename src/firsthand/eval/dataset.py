"""The vendored duplicate-labelled issue set the eval harness runs on (§8.4).

Tiny and checked in, so the suite is deterministic and needs no network. Each
record is one issue; ``duplicate_of`` names the earlier issue it duplicates, or
is null. Modelled on public GitHub-issue duplicate labels.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATASET = Path(__file__).parent / "data" / "issues.json"


@dataclass(frozen=True)
class IssueRecord:
    """One labelled issue."""

    id: str
    title: str
    body: str
    duplicate_of: str | None = None

    @property
    def text(self) -> str:
        """Title and body joined — what the dedup path would embed."""
        return f"{self.title}\n{self.body}"


def load_dataset(path: str | Path | None = None) -> list[IssueRecord]:
    """Load and validate the vendored set (or one pointed at by ``path``)."""
    resolved = Path(path) if path is not None else DEFAULT_DATASET
    rows = json.loads(resolved.read_text(encoding="utf-8"))
    records = [
        IssueRecord(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            duplicate_of=row.get("duplicate_of"),
        )
        for row in rows
    ]
    _check_referential_integrity(records)
    return records


def gold_pairs(records: Iterable[IssueRecord]) -> set[frozenset[str]]:
    """The set of unordered id-pairs the labels say are duplicates."""
    pairs: set[frozenset[str]] = set()
    for record in records:
        if record.duplicate_of is not None:
            pairs.add(frozenset({record.id, record.duplicate_of}))
    return pairs


def _check_referential_integrity(records: list[IssueRecord]) -> None:
    ids = {record.id for record in records}
    if len(ids) != len(records):
        raise ValueError("duplicate id in eval dataset")
    for record in records:
        if record.duplicate_of is not None and record.duplicate_of not in ids:
            raise ValueError(
                f"{record.id}.duplicate_of points at unknown id {record.duplicate_of!r}"
            )
        if record.duplicate_of == record.id:
            raise ValueError(f"{record.id} is marked a duplicate of itself")
