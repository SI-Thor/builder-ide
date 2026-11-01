#!/usr/bin/env python3
"""The delegate bake-off's tables, side by side.

    python docs/lab/critic-delegate-scripts/report.py

Reads every ``results/*.json`` the bake-off wrote and prints one table: the
same counting rule for every candidate (:func:`core.critic.critic.calibration_table`),
so the rows are comparable by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

ORDER = [
    ("scripted", "scripted (the baseline)"),
    ("d1", "d1-2B (local, vision)"),
    ("clef", "clef-flash (cloud, vision)"),
    ("hybrid-d1", "hybrid + d1-2B"),
    ("hybrid-clef", "hybrid + clef-flash"),
]

CLASSES = [
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
    "wrong_scale",
    "hollow_mesh",
    "clipped_geometry",
]


def _load(name: str):
    path = RESULTS / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _latency(payload) -> tuple[float | None, float | None, float | None]:
    """Median, mean and max verdict latency in milliseconds.

    The median is the ordinary one (the mean of the two middle values on an
    even count), so the number in the table is the number a reader gets from
    any other median of the same list.
    """
    import statistics

    times = sorted(m["latency_ms"] for m in payload["members"])
    if not times:
        return None, None, None
    median = statistics.median(times)
    mean = statistics.mean(times)
    return median, mean, times[-1]


def main() -> int:
    payloads = [(name, label, _load(name)) for name, label in ORDER]
    payloads = [(n, l, p) for n, l, p in payloads if p is not None]
    if not payloads:
        print("no results yet")
        return 1

    for name, label, payload in payloads:
        print(f"\n### {label}")
        print("| class | members | TP | FP | FN | TN |")
        print("|---|---|---|---|---|---|")
        for row in payload["table"]["rows"]:
            if not row["members"] and not row["tn"]:
                continue
            print(
                f"| `{row['defect']}` | {row['members']} | {row['tp']} | {row['fp']} "
                f"| {row['fn']} | {row['tn']} |"
            )
        totals = payload["table"]["totals"]
        print(
            f"| **all** | | **{totals['tp']}** | **{totals['fp']}** | "
            f"**{totals['fn']}** | **{totals['tn']}** |"
        )
        print(f"in band: **{payload['table']['in_band']}**")

    print("\n## the comparison\n")
    print("| candidate | layers | TP | FP | FN | TN | FP rate | in band | median ms | mean ms | max ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, label, payload in payloads:
        totals = payload["table"]["totals"]
        median, mean, worst = _latency(payload)
        rate = totals["fp_rate"]
        print(
            f"| {label} | {','.join(payload['layers'])} | {totals['tp']} | {totals['fp']} "
            f"| {totals['fn']} | {totals['tn']} | "
            f"{'—' if rate is None else f'{rate * 100:.1f} %'} | "
            f"{'yes' if payload['table']['in_band'] else 'no'} | "
            f"{'—' if median is None else f'{median:.0f}'} | "
            f"{'—' if mean is None else f'{mean:.0f}'} | "
            f"{'—' if worst is None else f'{worst:.0f}'} |"
        )

    print("\n## the box\n")
    for name, label, payload in payloads:
        box = payload.get("box") or {}
        print(
            f"- {label}: MemAvailable {box.get('mem_available_gib')} GiB, "
            f"GPU {box.get('gpu')}, kernel {box.get('kernel')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
