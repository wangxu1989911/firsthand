"""The vendored dataset must stay internally consistent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firsthand.eval.dataset import gold_pairs, load_dataset


def test_vendored_dataset_loads_and_has_labelled_duplicates() -> None:
    records = load_dataset()
    assert len(records) >= 20
    pairs = gold_pairs(records)
    assert len(pairs) >= 5
    # every gold pair references two ids that are actually in the set
    ids = {record.id for record in records}
    for pair in pairs:
        assert pair <= ids


def test_text_joins_title_and_body() -> None:
    record = load_dataset()[0]
    assert record.text == f"{record.title}\n{record.body}"


def test_a_dangling_duplicate_reference_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "issues.json"
    bad.write_text(
        json.dumps([{"id": "X1", "title": "t", "body": "b", "duplicate_of": "NOPE"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown id"):
        load_dataset(bad)


def test_a_self_duplicate_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "issues.json"
    bad.write_text(
        json.dumps([{"id": "X1", "title": "t", "body": "b", "duplicate_of": "X1"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate of itself"):
        load_dataset(bad)


def test_a_repeated_id_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "issues.json"
    bad.write_text(
        json.dumps(
            [
                {"id": "X1", "title": "t", "body": "b"},
                {"id": "X1", "title": "t2", "body": "b2"},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(bad)
