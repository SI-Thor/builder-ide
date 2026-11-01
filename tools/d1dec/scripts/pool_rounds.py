#!/usr/bin/env python3
"""Pool every interleaved round that has been measured, and summarise it.

The box is shared, and what else is using the GPU moves the absolute
numbers by a factor of two within a run: in one run of this server the
six rounds came out at 52, 28, 30, 38, 33 and 36 decisions/s. A single
round is a sample of a noisy process, so the headline is the **median**
over every round measured, and every round's number is kept.

The rounds are paired: round *i* of the baseline and round *i* of this
server were measured back to back, so the pairing keeps the comparison
fair even when the box's load moved between the two.

    python scripts/pool_rounds.py            # -> results/rounds/pooled.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUNDS_DIR = ROOT / "results" / "rounds"

ap = argparse.ArgumentParser()
ap.add_argument("--archive", default="", help="archive the current run under this tag")
args = ap.parse_args()


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def main() -> None:
    # -- archive the run that has just finished, so that every round
    #    ever measured is on disk and can be pooled
    if args.archive:
        tag = args.archive
        ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
        for name, src in (("ours", "bench_ours.json"), ("llamacpp", "bench_llamacpp.json")):
            src_path = ROOT / "results" / src
            if src_path.exists():
                (ROUNDS_DIR / f"{tag}_{name}.json").write_text(src_path.read_text())
        print(f"archived this run as {tag}")

    runs: list[tuple[str, dict, dict]] = []
    for ours_path in sorted(ROUNDS_DIR.glob("run*_ours.json")):
        tag = ours_path.stem.replace("_ours", "")
        base_path = ROUNDS_DIR / f"{tag}_llamacpp.json"
        ours = load(ours_path)
        base = load(base_path)
        if ours and base:
            runs.append((tag, ours, base))
    if not runs:
        raise SystemExit("no rounds to pool")

    pairs = []
    for tag, o, b in runs:
        o_rates = o["n64"].get("decisions_per_s_n64_rounds") or []
        b_rates = b["n64"].get("decisions_per_s_n64_rounds") or []
        o_p95 = o["n1"].get("pack_ms_p95_rounds") or []
        b_p95 = b["n1"].get("pack_ms_p95_rounds") or []
        o_tick = o["n64"].get("tick_ms_p95_rounds") or []
        b_tick = b["n64"].get("tick_ms_p95_rounds") or []
        n = min(len(o_rates), len(b_rates))
        for i in range(n):
            pairs.append({
                "run": tag,
                "round": i + 1,
                "ours_decisions_per_s": o_rates[i],
                "llamacpp_decisions_per_s": b_rates[i],
                "ours_p95_ms_n1": o_p95[i] if i < len(o_p95) else None,
                "llamacpp_p95_ms_n1": b_p95[i] if i < len(b_p95) else None,
                "ours_p95_ms_n64_tick": o_tick[i] if i < len(o_tick) else None,
                "llamacpp_p95_ms_n64_tick": b_tick[i] if i < len(b_tick) else None,
                "speedup": o_rates[i] / b_rates[i] if b_rates[i] else None,
                "loadavg": (o.get("loadavg_per_round") or [None] * (n + 1))[i]
                if o.get("loadavg_per_round") else None,
            })

    ours_rates = [p["ours_decisions_per_s"] for p in pairs]
    base_rates = [p["llamacpp_decisions_per_s"] for p in pairs]
    ours_n1 = [p["ours_p95_ms_n1"] for p in pairs if p["ours_p95_ms_n1"] is not None]
    base_n1 = [p["llamacpp_p95_ms_n1"] for p in pairs if p["llamacpp_p95_ms_n1"] is not None]
    ours_tick = [p["ours_p95_ms_n64_tick"] for p in pairs if p["ours_p95_ms_n64_tick"] is not None]
    base_tick = [p["llamacpp_p95_ms_n64_tick"] for p in pairs if p["llamacpp_p95_ms_n64_tick"] is not None]

    out = {
        "runs": [tag for tag, _, _ in runs],
        "n_rounds": len(pairs),
        "statistic": "the median over every interleaved round measured",
        "ours": {
            "decisions_per_s_n64": statistics.median(ours_rates),
            "decisions_per_s_n64_mean": statistics.mean(ours_rates),
            "decisions_per_s_n64_min": min(ours_rates),
            "decisions_per_s_n64_max": max(ours_rates),
            "p95_ms_n1": statistics.median(ours_n1),
            "p95_ms_n1_mean": statistics.mean(ours_n1),
            "p95_ms_n64_tick": statistics.median(ours_tick),
        },
        "llamacpp": {
            "decisions_per_s_n64": statistics.median(base_rates),
            "decisions_per_s_n64_mean": statistics.mean(base_rates),
            "decisions_per_s_n64_min": min(base_rates),
            "decisions_per_s_n64_max": max(base_rates),
            "p95_ms_n1": statistics.median(base_n1),
            "p95_ms_n1_mean": statistics.mean(base_n1),
            "p95_ms_n64_tick": statistics.median(base_tick),
        },
        "speedup_x": statistics.median(ours_rates) / statistics.median(base_rates),
        "rounds": pairs,
    }
    ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    (ROUNDS_DIR / "pooled.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rounds"}, indent=2))


if __name__ == "__main__":
    main()
