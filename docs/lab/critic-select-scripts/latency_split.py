#!/usr/bin/env python3
"""The two latency splits the write-up quotes: per layer, and per question.

    python docs/lab/critic-select-scripts/latency_split.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def load(name: str):
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    for name in ("scripted", "vlm", "hybrid"):
        payload = load(name)
        if payload is None:
            print(f"### {name}: (not run)\n")
            continue
        members = payload.get("members", [])
        print(f"### {name}: per-verdict wall time, by layer")
        for layer in ("image", "mesh"):
            values = sorted(
                m["latency_ms"] for m in members if m.get("layer") == layer
            )
            if not values:
                continue
            print(
                f"    {layer:6s} n={len(values):3d}  median {statistics.median(values)/1000:8.3f}s"
                f"  min {min(values)/1000:8.3f}s  max {max(values)/1000:8.3f}s"
                f"  sum {sum(values)/1000:8.1f}s"
            )
        # The model's own time, per question.
        seconds = []
        for member in members:
            for check in member.get("checks", []):
                measured = check.get("measured") or {}
                for key in ("vlm_seconds", "jev_seconds"):
                    if key in measured:
                        seconds.append(measured[key])
        if seconds:
            print(
                f"    per question: n={len(seconds)}  "
                f"median {statistics.median(seconds):.1f}s  "
                f"min {min(seconds):.1f}s  mean {statistics.fmean(seconds):.1f}s  "
                f"max {max(seconds):.1f}s  total {sum(seconds):.0f}s"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
