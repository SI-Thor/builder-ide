#!/usr/bin/env python3
"""Capture the box's state beside the VLM stage's numbers.

CLAUDE.md: "Measure, with the box's state beside every number." The VLM stage
is the one heavy step of the bake-off, so this is where the box's state
matters most: how much memory the stage actually took, and what the whole
box's power rails did while it ran.

**The joules are whole-box and are not attributable to the critic.** This is
a shared Thor: the seed sweep is generating, another seat's FP8 benchmark is
on the GPU, and the rails measure the *box*, not this process. So the rails
are reported as context — what the box was doing — and the numbers that can
be attributed to a candidate are the ones in the result files: the wall time
and the process's own CPU time per verdict.

    python docs/lab/critic-select-scripts/stage_box.py --out results/stage-box.json

Runs until it is asked to stop (SIGTERM/SIGINT) or the duration is up.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from boxstate import PowerSampler, box_state, memory  # noqa: E402

#: The rails the box reports that say what it was doing.
RAILS = ("VDD_GPU", "VDD_CPU_SOC_MSS", "VIN_SYS_5V0", "VIN")


def _peak_memory(should_stop=lambda: False) -> tuple[int, int, float, dict, dict]:
    """(peak used MiB, min available MiB, elapsed s, joules, mean watts)."""
    peak_used = 0
    min_avail = 1 << 30
    sampler = PowerSampler(interval_ms=200)
    with sampler:
        start = time.perf_counter()
        while not should_stop():
            stats = memory()
            total = int(stats.get("MemTotal", 0))
            available = int(stats.get("MemAvailable", 0))
            peak_used = max(peak_used, total - available)
            min_avail = min(min_avail, available)
            time.sleep(2.0)
            if time.perf_counter() - start > 3600:
                break
        elapsed = sampler.elapsed_s
        joules = {
            rail: round(sampler.integrated_joules(rail), 1) for rail in RAILS
        }
        averages = {}
        for rail in RAILS:
            series = sampler._rail_series(rail, "avg")
            averages[rail] = round(
                sum(p for _, p in series) / max(len(series), 1) / 1000.0, 2
            )
    # The sampler stops when the context manager exits, so the window is
    # measured here — the samples' own timestamps are the truth.
    window = max((s["t"] for s in sampler.samples), default=0.0)
    return peak_used, min_avail, window, joules, averages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    stop = False

    def _stop(*_args):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    before = box_state()
    peak_used, min_avail, elapsed, joules, averages = _peak_memory(
        lambda: stop
    )
    after = box_state()

    payload = {
        "note": (
            "Whole-box numbers on a shared Thor. The joules are the box's "
            "rails during the stage, not the critic's: the seed sweep and "
            "other seats were running beside it, so they are context, not "
            "an attribution."
        ),
        "before": before,
        "after": after,
        "peak_used_mib": peak_used,
        "min_available_mib": min_avail,
        "window_s": round(elapsed, 1),
        "whole_box_joules": joules,
        "whole_box_mean_rail_watts": averages,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
