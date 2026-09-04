"""`python -m firsthand.eval` is the CI gate — it must exit nonzero on regression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firsthand.eval.__main__ import main, run


def _baseline(tmp_path: Path, **overrides: object) -> Path:
    payload = {
        "threshold": 0.5,
        "precision": 0.875,
        "recall": 1.0,
        "f1": 0.9333,
        "tolerance": 0.02,
    }
    payload.update(overrides)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_run_passes_against_the_committed_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    assert "within tolerance" in capsys.readouterr().out


def test_run_fails_when_precision_regresses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline(tmp_path, recall=1.0, precision=1.0, tolerance=0.0)
    # The committed dataset has one false positive at t=0.5, so demanding
    # precision=1.0 is a regression.
    assert run(["--baseline", str(baseline)]) == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out
    assert "precision" in out


def test_run_fails_when_recall_regresses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A labelled duplicate pair with zero lexical overlap — the offline embedder
    # scores it a non-match, so recall drops below a recall=1.0 baseline.
    dataset = tmp_path / "issues.json"
    dataset.write_text(
        json.dumps(
            [
                {"id": "A1", "title": "alpha bravo charlie", "body": "delta echo foxtrot"},
                {
                    "id": "A2",
                    "title": "quebec romeo sierra",
                    "body": "tango uniform victor",
                    "duplicate_of": "A1",
                },
            ]
        ),
        encoding="utf-8",
    )
    baseline = _baseline(tmp_path, precision=0.0, recall=1.0, tolerance=0.0)
    assert run(["--dataset", str(dataset), "--baseline", str(baseline)]) == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out
    assert "recall" in out


def test_update_baseline_rewrites_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline(tmp_path, precision=0.1)
    assert run(["--baseline", str(baseline), "--update-baseline"]) == 0
    rewritten = json.loads(baseline.read_text())
    assert rewritten["precision"] == 0.875
    assert rewritten["tolerance"] == 0.02
    assert "baseline updated" in capsys.readouterr().out


def test_custom_dataset_flag_is_honoured(tmp_path: Path) -> None:
    dataset = tmp_path / "issues.json"
    dataset.write_text(
        json.dumps(
            [
                {"id": "A1", "title": "dark mode", "body": "add a dark mode toggle"},
                {
                    "id": "A2",
                    "title": "dark mode",
                    "body": "add a dark mode toggle",
                    "duplicate_of": "A1",
                },
            ]
        ),
        encoding="utf-8",
    )
    assert run(["--dataset", str(dataset), "--baseline", str(_baseline(tmp_path))]) == 0


def test_main_raises_systemexit_with_the_run_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["firsthand.eval"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
