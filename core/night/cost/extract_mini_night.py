"""Extract the mini-night's recorded lane splits into the cost model's data.

The mini-night (``docs/lab/mini-night.md``) is the only *whole night* the box
has run end to end: 18 jobs on the real models, with the GPU lane and the CPU
lane measured separately. Those 18 numbers are the best recorded sample of
what a night's work costs, so they go into the cost model — but they must
stay reproducible, or they are just numbers somebody typed.

This script reads the mini-night's **ledger** (the same audit log the night
runner writes) and emits the per-job lane splits in the recorded-data shape:
seconds, one sample per job, with the artefact's name.

    ~/lm-wt/integrate-core/.venv/bin/python -m core.night.cost.extract_mini_night \\
        --ledger ~/lm-wt/propmaker-batch/artifacts/mini-night/ledger.db \\
        > core/night/cost/data/mini_night.json

The CPU lane is ``wall - gpu``: the mini-night ran one prompt at a time
(``no_overlap`` in its report), so the two lanes never ran together and the
difference is the CPU lane plus the few seconds of file writing. The
mini-night's own lane totals differ from this by ~1 % (12.5 s of 929 s); the
model charges that to the CPU lane, which is the conservative reading.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _rows(ledger: Path) -> list[dict[str, Any]]:
    """The ``job.done`` events, in order: one per attempt the night ran."""
    db = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        cursor = db.execute(
            "select payload from audit where type = 'job.done' order by seq"
        )
        return [json.loads(payload) for (payload,) in cursor]
    finally:
        db.close()


def _sample(row: dict[str, Any]) -> dict[str, Any]:
    cost = row.get("cost") or {}
    gpu_minutes = float(cost.get("gpu_minutes", 0.0))
    wall_minutes = float(cost.get("wall_minutes", 0.0))
    artifact = str(row.get("artifact") or "")
    return {
        "name": artifact.rsplit("/", 1)[-1],
        "kind": "prop" if artifact.endswith(".glb") else "image",
        "gpu_seconds": round(gpu_minutes * 60.0, 6),
        "cpu_seconds": round((wall_minutes - gpu_minutes) * 60.0, 6),
        "wall_seconds": round(wall_minutes * 60.0, 6),
    }


def extract(ledger: Path) -> dict[str, Any]:
    """A night's lane splits, in the recorded-data shape.

    One sample per job the night ran, with the GPU lane and the CPU lane
    measured separately. The model's refresh path writes this file.
    """
    samples = [_sample(row) for row in _rows(Path(ledger))]
    return {
        "source": "mini_night",
        "origin": str(ledger),
        "doc": "docs/lab/mini-night.md",
        "rule": "one prompt at a time; the CPU lane is wall - gpu",
        "jobs": len(samples),
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(
            "/home/caseydigennaro/lm-wt/propmaker-batch/artifacts/mini-night/ledger.db"
        ),
        help="the mini-night's ledger",
    )
    args = parser.parse_args()

    print(json.dumps(extract(args.ledger), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - an extraction script
    raise SystemExit(main())
