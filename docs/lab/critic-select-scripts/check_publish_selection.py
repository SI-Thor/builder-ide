#!/usr/bin/env python3
"""Dry-run the published table's selection section — before the real one exists.

The published file (`core/critic/CALIBRATION.md`) carries the selection: the
candidates, their counts, and the chosen critic's own per-class table. This
renders that section with a **synthetic** selection so the formatting is
checked without touching the real file.

    python docs/lab/critic-select-scripts/check_publish_selection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.critic.critic import CalibrationTable  # noqa: E402
from core.critic.publish import render_markdown  # noqa: E402

SYNTHETIC = {
    "chosen": "hybrid",
    "report": "docs/lab/exp-critic-select.md",
    "candidates": [
        {
            "name": "scripted",
            "layers": "image,mesh",
            "tp": 23,
            "fp": 0,
            "fn": 1,
            "tn": 39,
            "in_band": False,
            "median_ms": 1059.0,
            "rows": [
                {
                    "defect": "floating_object",
                    "check": "floating_blob",
                    "members": 2,
                    "tp": 1,
                    "fp": 0,
                    "fn": 1,
                    "tn": 6,
                    "fp_rate": 0.0,
                    "fn_rate": 0.5,
                }
            ],
        },
        {
            "name": "hybrid",
            "layers": "image,mesh",
            "tp": 24,
            "fp": 0,
            "fn": 0,
            "tn": 39,
            "in_band": True,
            "median_ms": 14000.0,
            "rows": [
                {
                    "defect": "floating_object",
                    "check": "floating_blob",
                    "members": 2,
                    "tp": 2,
                    "fp": 0,
                    "fn": 0,
                    "tn": 6,
                    "fp_rate": 0.0,
                    "fn_rate": 0.0,
                }
            ],
        },
    ],
}


def main() -> int:
    markdown = render_markdown(
        CalibrationTable(), selection=SYNTHETIC, critic="scripted"
    )
    start = markdown.find("## The selection")
    if start < 0:
        print("! the selection section was not rendered")
        return 1
    print(markdown[start : start + 1800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
