#!/usr/bin/env python3
"""Print the numbers the write-up quotes, straight out of the result files.

Every figure in the lab document comes from here — the result files, not
memory. Prints each candidate's table, its latency spread, and the
per-question timing.

    python docs/lab/critic-select-scripts/numbers.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

ORDER = [
    "scripted",
    "dino-knn-base",
    "dino-knn-member",
    "dino-linear-base",
    "dino-linear-member",
    "vlm",
    "jev-verify-measurements",
    "jev-classify-measurements",
    "jev-verify-description",
    "jev-classify-description",
    "hybrid",
]


def load(name: str):
    path = RESULTS / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    for name in ORDER:
        payload = load(name)
        if payload is None:
            print(f"### {name}: (not run)")
            print()
            continue
        table = payload["table"]
        totals = table["totals"]
        members = payload.get("members", [])
        latencies = sorted(m["latency_ms"] for m in members if m.get("latency_ms"))
        cpus = [m["cpu_ms"] for m in members if m.get("cpu_ms")]
        print(f"### {name}")
        print(f"    layers      : {payload.get('layers')}")
        print(f"    members     : {len(members)}")
        print(f"    in_band     : {table['in_band']}")
        print(
            f"    totals      : tp={totals['tp']} fp={totals['fp']} "
            f"fn={totals['fn']} tn={totals['tn']}"
        )
        if latencies:
            print(
                f"    latency ms  : median {statistics.median(latencies):.0f}  "
                f"min {min(latencies):.0f}  mean {statistics.fmean(latencies):.0f}  "
                f"max {max(latencies):.0f}  sum {sum(latencies)/1000:.1f}s"
            )
        if cpus:
            print(
                f"    cpu ms      : median {statistics.median(cpus):.0f}  "
                f"mean {statistics.fmean(cpus):.0f}"
            )
        for row in table["rows"]:
            if not row["members"]:
                continue
            print(
                f"      {row['defect']:18s} {row['check']:12s} "
                f"tp={row['tp']} fp={row['fp']} fn={row['fn']} tn={row['tn']} "
                f"fp_rate={row['fp_rate']} fn_rate={row['fn_rate']}"
            )
        # The model-time detail, when the candidate measured it.
        seconds = []
        for member in members:
            for check in member.get("checks", []):
                measured = check.get("measured") or {}
                if "vlm_seconds" in measured:
                    seconds.append(measured["vlm_seconds"])
                if "jev_seconds" in measured:
                    seconds.append(measured["jev_seconds"])
        if seconds:
            print(
                f"    model s     : n={len(seconds)} "
                f"median {statistics.median(seconds):.1f} "
                f"min {min(seconds):.1f} max {max(seconds):.1f} "
                f"sum {sum(seconds):.0f}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
