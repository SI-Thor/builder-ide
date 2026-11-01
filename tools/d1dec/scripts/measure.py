#!/usr/bin/env python3
"""The whole measurement, in one place.

Waits for the two servers, checks the tokenizer against llama.cpp, checks
the answers against llama.cpp, then measures the two servers **interleaved**
— baseline, ours, baseline, ours — so that the shared box's drift hits
both of them the same way. Finally it merges the rounds and writes the
per-server numbers.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from d1dec.client import DecisionClient  # noqa: E402
from d1dec.workload import read_workload  # noqa: E402


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def wait_for(base: str, timeout: float = 3600.0) -> None:
    c = DecisionClient(base)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if c.health():
            return
        time.sleep(5)
    raise SystemExit(f"server {base} never came up")


def bench_server(
    base: str,
    packs: list[dict],
    label: str,
) -> dict:
    """One round of measurements on one server."""
    client = DecisionClient(base)
    by_tick: dict[int, list[dict]] = {}
    for p in packs:
        by_tick.setdefault(p.get("tick", 0), []).append(p)
    ticks = sorted(by_tick)

    # warm up
    client.ask_packs_concurrently(by_tick[ticks[0]])

    tick_latencies: list[float] = []
    pack_latencies: list[float] = []
    n_questions = 0
    n_errors = 0
    for t in ticks:
        p = by_tick[t]
        t0 = time.perf_counter()
        res = client.ask_packs_concurrently(p)
        dt = time.perf_counter() - t0
        tick_latencies.append(dt)
        pack_latencies.extend(r.latency_s for r in res)
        n_questions += sum(len(r.answers) for r in res)
        n_errors += sum(1 for r in res if r.error)

    # one character at a time
    single_latencies: list[float] = []
    n1_questions = 0
    for t in ticks:
        for p in by_tick[t][: max(1, len(by_tick[t]) // 4)]:
            body = {"state": p["state"], "questions": p["questions"]}
            _, dt, _ = client.ask_pack(body)
            single_latencies.append(dt)
            n1_questions += len(p["questions"])

    return {
        "label": label,
        "server": base,
        "ticks": len(tick_latencies),
        "n64": {
            "questions_per_tick": n_questions // max(1, len(tick_latencies)),
            "decisions_per_s_n64": n_questions / sum(tick_latencies),
            "tick_ms_mean": statistics.mean(tick_latencies) * 1000.0,
            "tick_ms_p95": pct(tick_latencies, 0.95) * 1000.0,
            "pack_ms_p95": pct(pack_latencies, 0.95) * 1000.0,
            "errors": n_errors,
        },
        "n1": {
            "samples": len(single_latencies),
            "questions": n1_questions,
            "pack_ms_mean": statistics.mean(single_latencies) * 1000.0,
            "pack_ms_p50": pct(single_latencies, 0.50) * 1000.0,
            "pack_ms_p95": pct(single_latencies, 0.95) * 1000.0,
            "decisions_per_s_n1": n1_questions / sum(single_latencies),
        },
        "loadavg": __import__("os").getloadavg(),
    }


def merge(rounds: list[dict]) -> dict:
    """Merge the rounds of one server.

    The box is shared and its load moves by a factor of two within a
    run, so the per-round numbers are kept and the median is the
    headline: the mean would let one round of interference decide the
    result.
    """
    ticks = [r["n64"]["tick_ms_p95"] for r in rounds]
    rates = [r["n64"]["decisions_per_s_n64"] for r in rounds]
    n1 = [r["n1"]["pack_ms_p95"] for r in rounds]
    out = {
        "rounds": len(rounds),
        "n64": {
            "decisions_per_s_n64": statistics.median(rates),
            "decisions_per_s_n64_mean": statistics.mean(rates),
            "decisions_per_s_n64_rounds": rates,
            "tick_ms_p95": statistics.median(ticks),
            "tick_ms_p95_mean": statistics.mean(ticks),
            "tick_ms_p95_rounds": ticks,
        },
        "n1": {
            "pack_ms_p95": statistics.median(n1),
            "pack_ms_p95_mean": statistics.mean(n1),
            "pack_ms_p95_rounds": n1,
        },
    }
    for k in ("ticks", "label", "server"):
        out[k] = rounds[0][k]
    out["loadavg_per_round"] = [r["loadavg"][0] for r in rounds]
    out["all_rounds"] = rounds
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="http://127.0.0.1:8137")
    ap.add_argument("--ours", default="http://127.0.0.1:8138")
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    outdir = ROOT / args.out_dir
    outdir.mkdir(parents=True, exist_ok=True)

    print("waiting for the servers ...", flush=True)
    wait_for(args.baseline)
    wait_for(args.ours)
    print("both servers are up", flush=True)

    # -- the tokenizer has to be llama.cpp's tokenizer --------------------
    print("checking the tokenizer against llama.cpp ...", flush=True)
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_tokenizer.py"), "--server", args.baseline],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    (outdir / "tokenizer_check.txt").write_text(rc.stdout + rc.stderr)
    print(rc.stdout.strip().splitlines()[-1] if rc.stdout.strip() else rc.stderr[-400:], flush=True)

    # -- the answers have to be llama.cpp's answers -----------------------
    print("checking the answers against llama.cpp ...", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "agreement.py"),
            "--baseline", args.baseline,
            "--ours", args.ours,
            "--workload", args.workload,
            "--out", str(outdir / "agreement.json"),
        ],
        cwd=ROOT,
    )

    # -- the numbers, interleaved ----------------------------------------
    packs = read_workload(ROOT / args.workload)
    base_rounds: list[dict] = []
    ours_rounds: list[dict] = []
    for r in range(args.rounds):
        print(f"round {r + 1}/{args.rounds}: baseline", flush=True)
        base_rounds.append(bench_server(args.baseline, packs, "llamacpp"))
        print(f"round {r + 1}/{args.rounds}: ours", flush=True)
        ours_rounds.append(bench_server(args.ours, packs, "ours"))

    merged_base = merge(base_rounds)
    merged_ours = merge(ours_rounds)
    (outdir / "bench_llamacpp.json").write_text(json.dumps(merged_base, indent=2) + "\n")
    (outdir / "bench_ours.json").write_text(json.dumps(merged_ours, indent=2) + "\n")

    # -- the memory the two servers took -----------------------------------
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "peak_mem.py"), "--out", str(outdir / "peak_mem.json")],
        cwd=ROOT,
    )

    print("\n=== summary ===")
    print(f"llama.cpp : {merged_base['n64']['decisions_per_s_n64']:.1f} decisions/s "
          f"(tick p95 {merged_base['n64']['tick_ms_p95']:.0f} ms, "
          f"n1 p95 {merged_base['n1']['pack_ms_p95']:.0f} ms)")
    print(f"ours      : {merged_ours['n64']['decisions_per_s_n64']:.1f} decisions/s "
          f"(tick p95 {merged_ours['n64']['tick_ms_p95']:.0f} ms, "
          f"n1 p95 {merged_ours['n1']['pack_ms_p95']:.0f} ms)")
    print(f"speedup   : {merged_ours['n64']['decisions_per_s_n64'] / merged_base['n64']['decisions_per_s_n64']:.2f}x")


if __name__ == "__main__":
    main()
