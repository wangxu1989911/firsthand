"""The harness turns similarity + labels into precision/recall the CI stage gates on."""

from __future__ import annotations

import pytest

from firsthand.eval.dataset import IssueRecord
from firsthand.eval.harness import EVAL_THRESHOLD, EvalResult, evaluate


def _records() -> list[IssueRecord]:
    return [
        IssueRecord("A1", "dark mode theme", "add a dark mode theme toggle in settings"),
        IssueRecord(
            "A2", "dark mode theme option", "please add a dark mode theme toggle in settings", "A1"
        ),
        IssueRecord("B1", "csv export", "export the report table to a csv file"),
        IssueRecord("C1", "webhook retries", "retry failed webhook deliveries on error"),
    ]


def test_perfect_run_scores_1_0() -> None:
    result = evaluate(_records(), threshold=EVAL_THRESHOLD)
    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0


def test_a_high_threshold_misses_the_duplicate() -> None:
    result = evaluate(_records(), threshold=0.999)
    assert result.true_positives == 0
    assert result.false_negatives == 1
    assert result.recall == 0.0
    # no predictions at all -> precision defined as 1.0, f1 collapses to 0
    assert result.precision == 1.0
    assert result.f1 == 0.0


def test_a_low_threshold_overpredicts() -> None:
    result = evaluate(_records(), threshold=-1.0)
    assert result.false_positives > 0
    assert result.precision < 1.0
    assert result.recall == 1.0


def test_result_rounds_for_the_baseline_file() -> None:
    payload = EvalResult(0.5, 3, 1, 1).as_dict()
    assert payload == {"threshold": 0.5, "precision": 0.75, "recall": 0.75, "f1": 0.75}


def test_no_labels_and_no_predictions_is_vacuously_perfect() -> None:
    result = EvalResult(0.5, 0, 0, 0)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == pytest.approx(1.0)


def test_the_vendored_baseline_run_is_still_green() -> None:
    """Guards the numbers committed in baseline.json without shelling out."""
    import json
    from pathlib import Path

    from firsthand.eval.dataset import load_dataset

    baseline = json.loads(
        (Path(__file__).parents[2] / "src/firsthand/eval/baseline.json").read_text()
    )
    result = evaluate(load_dataset(), threshold=baseline["threshold"])
    assert result.precision >= baseline["precision"] - baseline["tolerance"]
    assert result.recall >= baseline["recall"] - baseline["tolerance"]
