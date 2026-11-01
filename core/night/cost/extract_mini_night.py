"""Extract a night's recorded lane splits into the cost model's data.

A night (``docs/lab/mini-night.md``, ``docs/lab/mini-night-2.md``) is a
*whole night* the box has run end to end: the real models, one prompt at a
time, with the GPU lane and the CPU lane measured separately. Those numbers
are the best recorded sample of what a night's work costs, so they go into
the cost model — but they must stay reproducible, or they are just numbers
somebody typed.

This script reads a night's **ledger** (the same audit log the night runner
writes) and emits the per-job lane splits in the recorded-data shape:
seconds, one sample per job, with the artefact's name.

    ~/lm-wt/propmaker-batch/.venv/bin/python -m core.night.cost.extract_mini_night \\
        --ledger ~/lm-wt/propmaker-batch/artifacts/mini-night/ledger.db \\
        --night mini_night --doc docs/lab/mini-night.md \\
        > core/night/cost/data/mini_night.json

    ~/lm-wt/propmaker-batch/.venv/bin/python -m core.night.cost.extract_mini_night \\
        --ledger ~/lm-wt/mini-night2/artifacts/mini-night-2/ledger.db \\
        --night mini_night_2 --doc docs/lab/mini-night-2.md \\
        > core/night/cost/data/mini_night_2.json

The CPU lane is ``wall - gpu``: the night ran one prompt at a time
(``no_overlap`` in its report), so the two lanes never ran together and the
difference is the CPU lane plus the few seconds of file writing. The
mini-night's own lane totals differ from this by ~1 % (12.5 s of 929 s); the
model charges that to the CPU lane, which is the conservative reading.

**The repair is in here too.** A night's repair stage runs *after* the
prompt returns, so the ledger's job cost does not carry it — the mesh the
night keeps is a repaired mesh, and the repair is part of what a prop costs.
The repair's own timings live in the night's ``repairs.json``, next to the
ledger, and they come out as samples of their own kind (``repair``) so the
model can charge them where they belong: the CPU lane.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

#: The kinds a night's samples come out as.
KIND_PROP = "prop"
KIND_IMAGE = "image"
KIND_REPAIR = "repair"


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
        "kind": KIND_PROP if artifact.endswith(".glb") else KIND_IMAGE,
        "gpu_seconds": round(gpu_minutes * 60.0, 6),
        "cpu_seconds": round((wall_minutes - gpu_minutes) * 60.0, 6),
        "wall_seconds": round(wall_minutes * 60.0, 6),
    }


def _repair_samples(repairs: Path) -> list[dict[str, Any]]:
    """The repair stage's own timings, as samples of the ``repair`` kind.

    The repair is CPU work that happens after the prompt returns, so it is
    not in the ledger's job cost.  It is in the night's ``repairs.json``,
    which records what the repair did and how long it took.
    """
    if not repairs.exists():
        return []
    payload = json.loads(repairs.read_text())
    samples: list[dict[str, Any]] = []
    for entry in payload:
        repair = entry.get("repair") or {}
        seconds = repair.get("seconds")
        if seconds is None:
            continue
        name = str(entry.get("glb") or "").rsplit("/", 1)[-1]
        samples.append(
            {
                "name": name,
                "kind": KIND_REPAIR,
                "gpu_seconds": 0.0,
                "cpu_seconds": round(float(seconds), 6),
                "wall_seconds": round(float(seconds), 6),
            }
        )
    return samples


def extract(
    ledger: Path,
    *,
    night: str = "mini_night",
    doc: str = "docs/lab/mini-night.md",
) -> dict[str, Any]:
    """A night's lane splits, in the recorded-data shape.

    One sample per job the night ran, with the GPU lane and the CPU lane
    measured separately, plus the repair stage's own timings.  The model's
    refresh path writes this file.
    """
    ledger = Path(ledger)
    samples = [_sample(row) for row in _rows(ledger)]
    repairs = _repair_samples(ledger.parent / "repairs.json")
    return {
        "source": night,
        "origin": str(ledger),
        "doc": doc,
        "rule": "one prompt at a time; the CPU lane is wall - gpu",
        "jobs": len(samples),
        "repairs": len(repairs),
        "samples": samples + repairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(
            "/home/caseydigennaro/lm-wt/propmaker-batch/artifacts/mini-night/ledger.db"
        ),
        help="the night's ledger",
    )
    parser.add_argument(
        "--night",
        default="mini_night",
        help="the night's name: the source key the cost model reads it under",
    )
    parser.add_argument(
        "--doc",
        default="docs/lab/mini-night.md",
        help="the lab note the night is written up in",
    )
    args = parser.parse_args()

    print(json.dumps(extract(args.ledger, night=args.night, doc=args.doc), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - an extraction script
    raise SystemExit(main())
