#!/usr/bin/env python3
"""Print the bake-off: every candidate's table, side by side, with the numbers.

    python docs/lab/critic-select-scripts/report.py

Reads ``results/*.json`` — the files the candidate runs wrote — and prints
the comparison the brief asks for: each candidate's FP/FN table in the
published table's format, its per-verdict latency, and whether it holds the
band.

The band is the same one the published table uses: at most 5 % false
positives per class and no false negatives at all.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import RESULTS, ROOT  # noqa: E402

#: The order the candidates are printed in, and the label each one gets.
ORDER = [
    ("scripted", "scripted (the baseline, cold probe cache)"),
    ("scripted-warm", "scripted (the baseline, warm probe cache)"),
    ("dino-knn-base", "dino-probe, kNN head, leave-one-base-out"),
    ("dino-knn-member", "dino-probe, kNN head, leave-one-member-out"),
    ("dino-linear-base", "dino-probe, linear head, leave-one-base-out"),
    ("dino-linear-member", "dino-probe, linear head, leave-one-member-out"),
    ("vlm", "the local VLM (Muse Glimmer 30B)"),
    ("jev-verify-measurements", "Jev, verify arm, measurements only"),
    ("jev-classify-measurements", "Jev, classify arm, measurements only"),
    ("jev-verify-description+measurements", "Jev, verify arm, description + measurements"),
    ("jev-classify-description+measurements", "Jev, classify arm, description + measurements"),
    ("jev-verify-description", "Jev, verify arm, description only"),
    ("jev-classify-description", "Jev, classify arm, description only"),
    ("hybrid", "hybrid: scripted + the model on the out-of-band class"),
]

IMAGE_CLASSES = [
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
]


def load(name: str) -> dict | None:
    path = RESULTS / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def latency_summary(payload: dict) -> tuple[float, float]:
    """The median and the mean per-verdict latency, in milliseconds."""
    values = [m["latency_ms"] for m in payload.get("members", []) if m.get("latency_ms")]
    if not values:
        return 0.0, 0.0
    return statistics.median(values), statistics.fmean(values)


def cpu_summary(payload: dict) -> float:
    """The mean per-verdict CPU time, in milliseconds."""
    values = [m["cpu_ms"] for m in payload.get("members", []) if m.get("cpu_ms")]
    return statistics.fmean(values) if values else 0.0


def print_table(payload: dict) -> None:
    table = payload["table"]
    rows = {row["defect"]: row for row in table["rows"]}
    print("| class | members | TP | FP | FN | TN | FP rate |")
    print("|---|---|---|---|---|---|---|")
    for defect, row in rows.items():
        if not row["members"]:
            continue
        rate = row["fp_rate"]
        rate_text = "—" if rate is None else f"{rate:.1%}"
        print(
            f"| {defect} | {row['members']} | {row['tp']} | {row['fp']} | "
            f"{row['fn']} | {row['tn']} | {rate_text} |"
        )
    totals = table["totals"]
    print(
        f"| **all** | | **{totals['tp']}** | **{totals['fp']}** | "
        f"**{totals['fn']}** | **{totals['tn']}** | |"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-selection",
        action="store_true",
        help="write core/critic/selection.json — the selection the table publishes",
    )
    parser.add_argument(
        "--chosen",
        default=None,
        help="the candidate the selection names as chosen (default: the pick)",
    )
    args = parser.parse_args()

    print("# The bake-off\n")
    summary_rows = []
    for name, label in ORDER:
        payload = load(name)
        if payload is None:
            print(f"## {label}\n\n_(not run)_\n")
            continue
        table = payload["table"]
        totals = table["totals"]
        median, mean = latency_summary(payload)
        summary_rows.append(
            {
                "name": name,
                "label": label,
                "layers": ",".join(payload.get("layers", [])),
                "tp": totals["tp"],
                "fp": totals["fp"],
                "fn": totals["fn"],
                "tn": totals["tn"],
                "fp_rate": totals["fp_rate"],
                "in_band": table["in_band"],
                "median_ms": median,
                "mean_ms": mean,
                "cpu_ms": cpu_summary(payload),
                "members": len(payload.get("members", [])),
                "rows": [
                    {
                        "defect": row["defect"],
                        "check": row["check"],
                        "members": row["members"],
                        "tp": row["tp"],
                        "fp": row["fp"],
                        "fn": row["fn"],
                        "tn": row["tn"],
                        "fp_rate": row["fp_rate"],
                        "fn_rate": row["fn_rate"],
                    }
                    for row in table["rows"]
                    if row["members"]
                ],
            }
        )
        print(f"## {label}\n")
        print(f"`{name}` — layers: {', '.join(payload.get('layers', []))}, "
              f"{len(payload.get('members', []))} members scored, "
              f"per-verdict latency median {median:.0f} ms / mean {mean:.0f} ms, "
              f"CPU {cpu_summary(payload):.0f} ms per verdict, "
              f"**in band: {table['in_band']}**\n")
        print_table(payload)
        print()

    if summary_rows:
        print("## The comparison\n")
        print("| candidate | layers | TP | FP | FN | TN | FP rate | in band | median ms/verdict | CPU ms/verdict |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for row in summary_rows:
            rate = row["fp_rate"]
            rate_text = "—" if rate is None else f"{rate:.1%}"
            print(
                f"| {row['label']} | {row['layers']} | {row['tp']} | {row['fp']} | "
                f"{row['fn']} | {row['tn']} | {rate_text} | "
                f"{'yes' if row['in_band'] else 'no'} | {row['median_ms']:.0f} | "
                f"{row['cpu_ms']:.0f} |"
            )

    if args.write_selection:
        selection = {
            "measured_at": time.strftime("%Y-%m-%d"),
            "set": {
                "members": 30,
                "image_members": 21,
                "mesh_members": 9,
                "clean_controls": 6,
            },
            "chosen": args.chosen or _chosen(summary_rows),
            "report": "docs/lab/exp-critic-select.md",
            "candidates": [
                {
                    "name": row["name"],
                    "label": row["label"],
                    "layers": row["layers"],
                    "tp": row["tp"],
                    "fp": row["fp"],
                    "fn": row["fn"],
                    "tn": row["tn"],
                    "fp_rate": row["fp_rate"],
                    "in_band": row["in_band"],
                    "median_ms": round(row["median_ms"], 1),
                    "mean_ms": round(row["mean_ms"], 1),
                    "cpu_ms": round(row["cpu_ms"], 1),
                    "members": row["members"],
                    # The per-class rows, so the published table can carry
                    # the chosen critic's own table and not only its totals.
                    "rows": row["rows"],
                }
                for row in summary_rows
            ],
            "box": _box_state(),
        }
        out = ROOT / "core" / "critic" / "selection.json"
        out.write_text(json.dumps(selection, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {out} (chosen: {selection['chosen']})")
    return 0


def _box_state() -> dict:
    """The box the measurement was taken on — beside the numbers."""
    try:
        from boxstate import box_state

        return box_state()
    except Exception:  # noqa: BLE001 - the box's state is context, not the result
        return {}


def _chosen(summary_rows: list[dict]) -> str:
    """The candidate the selection names.

    The hybrid, when it holds the band: it is the checks everywhere they
    hold plus a model on the one class they miss. Otherwise the scripted
    checks — the default and the fallback — because nothing else held the
    band on the whole set.
    """
    by_name = {row["name"]: row for row in summary_rows}
    hybrid = by_name.get("hybrid")
    if hybrid is not None and hybrid["in_band"]:
        return "hybrid"
    for row in summary_rows:
        if row["in_band"]:
            return row["name"]
    return "scripted"


if __name__ == "__main__":
    raise SystemExit(main())
