"""C1c -- the real request-rate ceiling of Workers AI, measured cleanly.

C1 and C1b ran their matrix cells back to back.  Workers AI rejects with
``3021: rate limiting: inference request per min rate reached``, and that
budget is per account per minute -- so a cell that ran after four other
512-call cells inherited an almost-spent budget, and the c=128 numbers
mixed "the model cannot keep this up" with "I had already spent the
minute".

This script removes that confound:

  * it waits for a quiet minute before each measurement,
  * it then drives one model at one concurrency, continuously, for a fixed
    time, logging every call with its timestamp and outcome,
  * it reports the time to the first rejection, the sustained successful
    requests per minute, and the ceiling.

Two rejections look different and both are real:
  3021  per-minute request budget exhausted  (a rate limit)
  3040  "Capacity temporarily exceeded"       (a capacity limit: the
                                              request was too big for the
                                              pool, not too many of them)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gates
import tasks
from decision_client import ClefAI, MODELS, canonical_questions, neurons_for

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)


def classify(raw) -> str:
    text = raw if isinstance(raw, str) else json.dumps(raw)
    if "3021" in text or "rate limit" in text.lower():
        return "rate_limited_3021"
    if "3040" in text or "capacity" in text.lower():
        return "out_of_capacity_3040"
    return "other"


def state_for(seed: int) -> str:
    g, a, b, es = tasks._world(seed)
    return tasks.scene_state(g, a, b, es)


def measure(model: str, pack: str, concurrency: int, seconds: float,
            backend, quiet_s: float, seed_base: int = 1000,
            pace: float | None = None) -> dict:
    print(f"  waiting {quiet_s:.0f}s for a fresh per-minute budget ...",
          flush=True)
    time.sleep(quiet_s)

    calls: list[dict] = []
    lock = threading.Lock()
    counter = {"i": 0}
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()

    def one():
        with lock:
            i = counter["i"]
            counter["i"] += 1
        seed = seed_base + (i % 64)
        qq = canonical_questions(
            gates.one_gate_pack(seed)[0] if pack == "q1"
            else gates.build_gates(seed)[0])
        status, raw, ms = backend.ask(state_for(seed), qq, model)
        tok = 0
        if status == 200:
            tok = int((raw.get("usage") or {}).get("input_tokens", 0) or 0)
        rec = {"t": time.perf_counter() - t0, "status": status, "ms": ms,
               "err": "ok" if status == 200 else classify(raw),
               "in_tokens": tok}
        with lock:
            calls.append(rec)
        return rec

    # Submit continuously for the whole window, then let the backlog drain.
    # Every call records its own completion timestamp, so the rate is
    # measured over the window and not over the drain.
    submitted = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = []
        n = 0
        while time.perf_counter() - t0 < seconds:
            if pace:
                # submit on a fixed schedule: requests per second
                due = t0 + n / pace
                lag = due - time.perf_counter()
                if lag > 0:
                    time.sleep(lag)
                n += 1
            futs.append(ex.submit(one))
            submitted += 1
            if not pace:
                time.sleep(0.002)
        for f in futs:
            f.result()
    drain = time.perf_counter() - t0

    calls.sort(key=lambda r: r["t"])
    # "in window" = the call finished inside the measured window
    win = [c for c in calls if c["t"] <= seconds]
    ok_win = [c for c in win if c["status"] == 200]
    bad_win = [c for c in win if c["status"] != 200]
    ok_all = [c for c in calls if c["status"] == 200]
    bad_all = [c for c in calls if c["status"] != 200]
    first_bad = bad_win[0]["t"] if bad_win else None
    toks = sum(c["in_tokens"] for c in ok_all)
    neurons = neurons_for(model, toks)
    lat = sorted(c["ms"] for c in ok_all)

    rate_per_min = len(ok_win) / seconds * 60.0 if seconds > 0 else 0.0
    attempts_per_min = len(win) / seconds * 60.0 if seconds > 0 else 0.0

    # per-second timeline of the window: where the limiter starts rejecting
    timeline = []
    for s in range(int(seconds)):
        bucket = [c for c in win if s <= c["t"] < s + 1]
        timeline.append({
            "s": s,
            "ok": sum(1 for c in bucket if c["status"] == 200),
            "err": sum(1 for c in bucket if c["status"] != 200),
        })

    out = {
        "model": model, "pack": pack, "concurrency": concurrency,
        "window_s": seconds,
        "submitted": submitted,
        "completed_in_window": len(win),
        "ok_in_window": len(ok_win),
        "ok_total": len(ok_all),
        "err_in_window": len(bad_win),
        "err_total": len(bad_all),
        "drain_s": round(drain, 2),
        "error_rate": round(len(bad_win) / max(1, len(win)), 4),
        "errors": dict(Counter(c["err"] for c in bad_all)),
        "first_rejection_at_s": round(first_bad, 3) if first_bad is not None else None,
        "ok_requests_per_min": round(rate_per_min, 1),
        "attempted_requests_per_min": round(attempts_per_min, 1),
        "latency_ms": {"p50": round(statistics.median(lat), 1) if lat else None,
                       "p95": round(sorted(lat)[int(len(lat) * .95) - 1], 1)
                       if len(lat) > 1 else None,
                       "max": round(max(lat), 1) if lat else None},
        "neurons": round(neurons, 2),
        "usd": round(neurons / 1000 * 0.011, 6),
        "quiet_before_s": quiet_s,
        "pace_rps": pace,
        "timeline_per_s": timeline,
    }
    print(f"  {model.split('/')[-1]:11s} {pack:4s} c={concurrency:<4d} "
          f"submitted={submitted:6d} ok_win={len(ok_win):5d} "
          f"err={out['error_rate']:.3f} {out['errors']} "
          f"first_rej={out['first_rejection_at_s']}s "
          f"ok/min={out['ok_requests_per_min']} "
          f"attempt/min={out['attempted_requests_per_min']} "
          f"tok/call={round(toks/max(1,len(ok_all)),1)}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c1c-rate-ceiling.json")
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    ap.add_argument("--seconds", type=float, default=70.0)
    ap.add_argument("--quiet", type=float, default=75.0)
    ap.add_argument("--cells", default="flash:q1:32,flash:q1:128,clef27:q1:32")
    ap.add_argument("--pace", type=float, default=None,
                    help="requests per second submitted (default: as fast as "
                         "the client can, which measures the ceiling)")
    args = ap.parse_args()

    backend = ClefAI(url=args.url)
    rows = []
    for spec in args.cells.split(","):
        mk, pack, c = spec.split(":")
        model = MODELS[mk]
        print(f"\ncell {spec}")
        rows.append(measure(model, pack, int(c), args.seconds, backend,
                             args.quiet, pace=args.pace))

    out = {
        "experiment": "C1c Workers AI request-rate ceiling",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": ("each cell starts after a quiet interval so the per-minute "
                 "request budget is fresh; C1/C1b cells were back to back "
                 "and so shared one minute's budget"),
        "cells": rows,
        "neurons_total": round(sum(r["neurons"] for r in rows), 2),
        "usd_total": round(sum(r["usd"] for r in rows), 6),
    }
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    print(f"\nneurons={out['neurons_total']} usd={out['usd_total']} "
          f"-> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
