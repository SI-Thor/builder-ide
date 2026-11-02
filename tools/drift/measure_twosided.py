"""Re-measure the one-sided gate against the old two-sided one, on the
committed dataset.

The lab note compares the shipped rate gate with the one that used
abs(delta). That comparison has to be measured on the *committed*
dataset, or the "before" number is from a different snapshot.

This script patches the gate's _feed to the old two-sided behaviour,
runs the same calibration, and prints both. It is a measurement, not a
change: nothing in core/ is modified.

    python3 tools/drift/measure_twosided.py
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.drift.gate as gate_module  # noqa: E402
from core.drift.gate import DriftGate  # noqa: E402

DATA = Path("docs/lab/drift-dataset")


def _two_sided_feed(self, value: float) -> float:
    """The gate as it was before the one-sided fix."""
    if self.mode == "level":
        return value
    previous = self._previous
    self._previous = value
    if previous is None:
        return 0.0
    if math.isinf(value) or math.isinf(previous):
        return math.inf
    return abs(value - previous)


def main() -> int:
    # The calibration runs IN THIS PROCESS, so that the patched gate is
    # the one it measures. A subprocess would measure the shipped code
    # both times and the comparison would be a no-op.
    import tools.drift.calibrate as calibrate  # noqa: E402

    out = {}
    original = DriftGate._feed
    for label, patch in (("two_sided", True), ("one_sided", False)):
        DriftGate._feed = _two_sided_feed if patch else original  # type: ignore[method-assign]
        target = Path(f"/tmp/drift-desk/calibration-{label}.json")
        with contextlib.redirect_stdout(io.StringIO()):
            calibrate.main(
                [
                    "--dataset", str(DATA / "dataset.json"),
                    "--labels", str(DATA / "labels.json"),
                    "--out", str(target),
                ]
            )
        report = json.loads(target.read_text())
        out[label] = {
            "success_rate_gate": {
                "leave_one_out": report["signals"]["success"]["rate"]["leave_one_out"],
                "shipped": report["signals"]["success"]["rate"]["shipped"],
            },
            "combined": {
                "holdout": report["combined"]["rate"]["holdout"],
                "alarms_per_hour": report["combined"]["rate"]["alarms_per_hour"],
            },
            "negative_control": report["negative_control"],
        }
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
