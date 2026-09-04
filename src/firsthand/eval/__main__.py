"""``python -m firsthand.eval`` — run the dedup eval and gate on the baseline (§8.4).

Exit 0 if precision and recall are within ``tolerance`` of the committed
baseline, 1 otherwise. ``--update-baseline`` rewrites ``baseline.json`` from the
current run — for a deliberate, reviewed change to the dedup logic or dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from firsthand.eval.dataset import load_dataset
from firsthand.eval.harness import EvalResult, evaluate

DEFAULT_BASELINE = Path(__file__).parent / "baseline.json"


def _format(result: EvalResult, baseline: dict[str, float]) -> str:
    return (
        f"threshold={result.threshold:.2f}\n"
        f"precision={result.precision:.4f} (baseline {baseline['precision']:.4f})\n"
        f"recall={result.recall:.4f} (baseline {baseline['recall']:.4f})\n"
        f"f1={result.f1:.4f} (baseline {baseline['f1']:.4f})\n"
        f"tp={result.true_positives} fp={result.false_positives} fn={result.false_negatives}"
    )


def _regressions(result: EvalResult, baseline: dict[str, float]) -> list[str]:
    tolerance = baseline.get("tolerance", 0.0)
    findings: list[str] = []
    if result.precision < baseline["precision"] - tolerance:
        findings.append(
            f"precision {result.precision:.4f} < baseline {baseline['precision']:.4f} - {tolerance}"
        )
    if result.recall < baseline["recall"] - tolerance:
        findings.append(
            f"recall {result.recall:.4f} < baseline {baseline['recall']:.4f} - {tolerance}"
        )
    return findings


def run(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m firsthand.eval")
    parser.add_argument("--dataset", type=Path, default=None, help="override the vendored dataset")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite the baseline from this run instead of gating on it",
    )
    args = parser.parse_args(argv)

    records = load_dataset(args.dataset)
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    result = evaluate(records, threshold=baseline["threshold"])

    if args.update_baseline:
        updated = {
            "_comment": baseline.get("_comment", ""),
            "tolerance": baseline.get("tolerance", 0.0),
            **result.as_dict(),
        }
        Path(args.baseline).write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated:\n{_format(result, updated)}")
        return 0

    print(_format(result, baseline))
    regressions = _regressions(result, baseline)
    if regressions:
        print("\nREGRESSION:")
        for finding in regressions:
            print(f"  - {finding}")
        return 1
    print("\nok: within tolerance of the baseline")
    return 0


def main() -> None:
    """Console entry: run and exit with the returned code."""
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    main()
