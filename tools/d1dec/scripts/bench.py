#!/usr/bin/env python3
"""Benchmark a decision server on the workload.

Two modes, both on the same packs:

* ``n64``  — a tick: 64 characters each send their 3-question pack at
  the same time. The rate is the number of *questions* answered per
  second, and the tick's wall time is the p95.
* ``n1``   — one character at a time: the p95 of a single pack's latency.

The client's own overhead is measured too, so it can be reported
alongside the numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.client import DecisionClient  # noqa: E402
from d1dec.workload import read_workload  # noqa: E402


def peak_rss_gb() -> float:
    """The peak resident set of this process, in GB."""
    me = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return max(me, kids) / (1024.0 * 1024.0)


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--mode", choices=["n64", "n1", "both"], default="both")
    ap.add_argument("--ticks", type=int, default=4)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    packs = read_workload(Path(args.workload))
    by_tick: dict[int, list[dict]] = {}
    for p in packs:
        by_tick.setdefault(p.get("tick", 0), []).append(p)
    ticks = sorted(by_tick)

    client = DecisionClient(args.server)
    if not client.health():
        print(f"server at {args.server} is not healthy", file=sys.stderr)
        sys.exit(2)

    out: dict = {
        "server": args.server,
        "label": args.label,
        "workload": args.workload,
        "n_packs": len(packs),
        "questions_per_pack": len(packs[0]["questions"]) if packs else 0,
    }

    if args.mode in ("n64", "both"):
        # a tick is the burst of every character of that tick
        tick_latencies: list[float] = []
        per_pack_latencies: list[float] = []
        n_questions = 0
        n_errors = 0
        error_kinds: dict[str, int] = {}
        # warmup
        for t in ticks[: args.warmup]:
            client.ask_packs_concurrently(by_tick[t])
        for t in ticks:
            p = by_tick[t]
            t0 = time.perf_counter()
            res = client.ask_packs_concurrently(p)
            dt = time.perf_counter() - t0
            tick_latencies.append(dt)
            per_pack_latencies.extend(r.latency_s for r in res)
            n_questions += sum(len(r.answers) for r in res)
            for r in res:
                if r.error:
                    n_errors += 1
                    kind = r.error.split(":")[0] + ": " + r.error.split(": ")[-1][:120]
                    error_kinds[kind] = error_kinds.get(kind, 0) + 1
        mean_tick = statistics.mean(tick_latencies)
        out["n64"] = {
            "ticks": len(tick_latencies),
            "questions_per_tick": n_questions // max(1, len(tick_latencies)),
            "decisions_per_s_n64": n_questions / sum(tick_latencies),
            "tick_ms_mean": mean_tick * 1000.0,
            "tick_ms_p95": pct(tick_latencies, 0.95) * 1000.0,
            "pack_ms_p95": pct(per_pack_latencies, 0.95) * 1000.0,
            "errors": n_errors,
            "error_kinds": error_kinds,
        }

    if args.mode in ("n1", "both"):
        latencies: list[float] = []
        n = 0
        for t in ticks:
            for p in by_tick[t][: max(1, len(by_tick[t]) // 8)]:
                body = {"state": p["state"], "questions": p["questions"]}
                _, dt, _ = client.ask_pack(body)
                latencies.append(dt)
                n += len(p["questions"])
        out["n1"] = {
            "samples": len(latencies),
            "questions": n,
            "pack_ms_mean": statistics.mean(latencies) * 1000.0,
            "pack_ms_p50": pct(latencies, 0.50) * 1000.0,
            "pack_ms_p95": pct(latencies, 0.95) * 1000.0,
            "decisions_per_s_n1": n / sum(latencies),
        }

    out["client_peak_rss_gb"] = peak_rss_gb()
    out["loadavg"] = os.getloadavg()
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
