#!/usr/bin/env python3
"""The night's numbers, beside the box state, and the diff against another
night.

The brief asks for five measurements beside the box state:

* wall time, GPU-minutes against the rail, and lease waits;
* decisions by rung;
* props kept and rejected, and why;
* diffs against run D on each.

This reads a night's `morning.json` and its `ledger.db` and prints all of
it. Given two nights it prints the diff.

Run on the Thor:

    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v5-scripts/measure.py \
        --night artifacts/night-v5 --against ~/lm-wt/night-v4/artifacts/night-v4
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def rows(ledger: Path, kind: str) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        return [
            json.loads(payload)
            for (payload,) in connection.execute(
                "select payload from audit where type = ?", (kind,))
        ]
    finally:
        connection.close()


def measure(night: Path) -> dict[str, Any]:
    morning_path = night / "morning.json"
    morning = json.loads(morning_path.read_text()) if morning_path.exists() else {}
    ledger = night / "ledger.db"
    jobs = rows(ledger, "job.done")
    leases = rows(ledger, "night.heavy_lease")
    phases = rows(ledger, "night.heavy_phase")
    verdicts = rows(ledger, "judge.verdict")
    box = rows(ledger, "night.box_state")
    prop_jobs = [job for job in jobs
                 if str(job.get("variant_id", "")).startswith("prop:")
                 or str(job.get("task_id", "")) in ("crate", "lantern", "anvil")]

    gpu_minutes = sum(float(job.get("cost", {}).get("gpu_minutes") or 0.0)
                       for job in jobs)
    wall_minutes = sum(float(job.get("cost", {}).get("wall_minutes") or 0.0)
                       for job in jobs)
    by_rung: dict[str, int] = {}
    by_gate: dict[str, int] = {}
    rung_latency: dict[str, list[float]] = {}
    for verdict in verdicts:
        author = str(verdict.get("author", "?"))
        by_rung[author] = by_rung.get(author, 0) + 1
        latency = float(verdict.get("latency_seconds") or 0.0)
        rung_latency.setdefault(author, []).append(latency)
        for judgment in verdict.get("judgments", []):
            gate = str(judgment.get("gate"))
            by_gate[gate] = by_gate.get(gate, 0) + 1

    # The winners are the morning's: a prop is kept when one of its
    # variants won its task's round. Every other prop variant is one the
    # critic rejected, and its reason is on the job row.
    winners = morning.get("props", {}).get("winners", []) or []
    winner_ids = {str(winner.get("variant")) for winner in winners}
    kept = [job for job in prop_jobs if str(job.get("variant_id")) in winner_ids]
    rejected = [job for job in prop_jobs
                if str(job.get("variant_id")) not in winner_ids]

    return {
        "night": str(night),
        "night_id": morning.get("night_id"),
        "status": morning.get("status"),
        "wall_minutes": morning.get("wall_minutes"),
        "gpu_minutes": round(gpu_minutes, 4),
        "job_wall_minutes": round(wall_minutes, 3),
        "jobs": len(jobs),
        "leases": leases,
        "lease_waits_s": [row.get("waited_s") for row in leases],
        "lease_wait_total_s": round(sum(float(row.get("waited_s") or 0.0)
                                        for row in leases), 1),
        "lease_kinds": sorted({str(row.get("kind")) for row in leases}),
        "phases": phases,
        "decisions_by_rung": by_rung,
        "decisions_by_gate": by_gate,
        "decision_latency_by_rung": {
            author: round(sum(values) / len(values), 4)
            for author, values in rung_latency.items() if values
        },
        "decision_count": len(verdicts),
        "props_kept": len(kept),
        "props_rejected": len(rejected),
        "props": [
            {"task": job.get("task_id"), "variant": job.get("variant_id"),
             "kept": str(job.get("variant_id")) in winner_ids,
             "score": job.get("score"),
             "reason": job.get("critic_reason") or job.get("reason"),
             "gpu_minutes": job.get("cost", {}).get("gpu_minutes")}
            for job in prop_jobs
        ],
        "box": box,
        "judge": morning.get("judge", {}),
        "critic": morning.get("critic", {}),
        "morning_decisions": {
            key: morning.get("decisions", {}).get(key)
            for key in ("count", "local", "escalated", "surfaced",
                        "latency_p50_s", "latency_p95_s", "standing_flickers")
        },
        "props_summary": {key: morning.get("props", {}).get(key)
                          for key in ("kept",)},
    }


def diff(here: dict[str, Any], there: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    def row(label: str, key: str, fmt: str = "{}") -> None:
        mine, theirs = here.get(key), there.get(key)
        if mine == theirs:
            lines.append(f"  {label:22} {fmt.format(theirs)}  (the same)")
        else:
            lines.append(f"  {label:22} {fmt.format(mine)}  vs run D "
                         f"{fmt.format(theirs)}")

    lines.append(f"the diff: {here.get('night')} against {there.get('night')}")
    row("wall minutes", "wall_minutes")
    row("GPU-minutes", "gpu_minutes")
    row("lease wait (s)", "lease_wait_total_s")
    row("lease kinds", "lease_kinds", "{}")
    row("decisions (rows)", "decision_count")
    row("decisions by rung", "decisions_by_rung", "{}")
    row("decisions by gate", "decisions_by_gate", "{}")
    row("props kept", "props_kept")
    row("props rejected", "props_rejected")
    row("status", "status", "{}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--night", type=Path, required=True)
    parser.add_argument("--against", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None,
                        help="write the measurement as JSON here")
    args = parser.parse_args()

    here = measure(args.night.resolve())
    print(f"=== {here['night']} — the measurements, beside the box state ===")
    print(json.dumps(here, indent=2, default=str))
    if args.against is not None:
        there = measure(args.against.resolve())
        print()
        print("\n".join(diff(here, there)))
    if args.json is not None:
        args.json.write_text(json.dumps(here, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
