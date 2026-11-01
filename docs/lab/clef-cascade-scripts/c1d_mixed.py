"""C1d -- is the per-minute request budget per model or shared across the account?

C1c measures the ceiling for one model at a time.  A cascade runs the small
model and the big model at the same time, so the question that matters for
the design is: if clef-flash and clef-27B each have their own allowance, both
can run at full rate; if they share one, running both halves each.

This script drives BOTH models concurrently for one window, after a quiet
interval, and reports the accepted rate per model and in total.

If the allowance were shared, the total accepted rate would match the single
model ceiling.  If it is per model, the total would be about twice it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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


def drive(model: str, concurrency: int, seconds: float, seed_base: int,
          stop_at: float, backend, pace: float | None = None) -> dict:
    """Hammer one model until stop_at (absolute perf_counter).

    pace = requests per second to submit.  Unpaced, the client floods and
    most requests are rejected; paced, the accepted rate is the thing under
    test and the wasted-request count stays small.
    """
    calls: list[dict] = []
    lock = threading.Lock()
    counter = {"i": 0}
    t0 = time.perf_counter()

    def one():
        with lock:
            i = counter["i"]
            counter["i"] += 1
        seed = seed_base + (i % 64)
        qq = canonical_questions(gates.one_gate_pack(seed)[0])
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

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = []
        n = 0
        while time.perf_counter() < stop_at:
            if pace:
                # submit on a fixed schedule
                due = t0 + n / pace
                lag = due - time.perf_counter()
                if lag > 0:
                    time.sleep(lag)
                n += 1
            futs.append(ex.submit(one))
            if not pace:
                time.sleep(0.002)
        for f in futs:
            f.result()
    return {"model": model, "calls": calls}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c1d-mixed-budget.json")
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--quiet", type=float, default=75.0)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--pace", type=float, default=40.0,
                    help="requests per second submitted per model")
    args = ap.parse_args()

    print(f"  waiting {args.quiet:.0f}s for a fresh per-minute budget ...",
          flush=True)
    time.sleep(args.quiet)

    backend = ClefAI(url=args.url)
    stop_at = time.perf_counter() + args.seconds
    results = {}

    def run(mk: str, seed_base: int):
        results[mk] = drive(MODELS[mk], args.concurrency, args.seconds,
                            seed_base, stop_at, backend, pace=args.pace)

    # both models hammer at the same time, on separate threads
    t = threading.Thread(target=run, args=("flash", 1000))
    u = threading.Thread(target=run, args=("clef27", 2000))
    t.start()
    u.start()
    t.join()
    u.join()

    out = {
        "experiment": "C1d is the per-minute request budget per model or shared?",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "window_s": args.seconds,
        "concurrency_per_model": args.concurrency,
        "pace_per_model_rps": args.pace,
        "models": {},
    }
    total_ok = 0
    total_attempts = 0
    for mk, r in results.items():
        calls = sorted(r["calls"], key=lambda c: c["t"])
        win = [c for c in calls if c["t"] <= args.seconds]
        ok = [c for c in win if c["status"] == 200]
        bad = [c for c in win if c["status"] != 200]
        ok_all = [c for c in calls if c["status"] == 200]
        toks = sum(c["in_tokens"] for c in ok_all)
        lat = sorted(c["ms"] for c in ok_all)
        neurons = neurons_for(MODELS[mk], toks)
        total_ok += len(ok)
        total_attempts += len(win)
        out["models"][mk] = {
            "model": MODELS[mk],
            "attempts_in_window": len(win),
            "ok_in_window": len(ok),
            "error_rate": round(len(bad) / max(1, len(win)), 4),
            "errors": dict(Counter(c["err"] for c in bad)),
            "ok_requests_per_min": round(len(ok) / args.seconds * 60.0, 1),
            "latency_ms": {"p50": round(statistics.median(lat), 1) if lat else None,
                           "p95": round(sorted(lat)[int(len(lat) * .95) - 1], 1)
                           if len(lat) > 1 else None},
            "neurons": round(neurons, 2),
        }
        print(f"  {mk:8s} attempts={len(win):6d} ok={len(ok):5d} "
              f"err={out['models'][mk]['error_rate']:.3f} "
              f"{out['models'][mk]['errors']} "
              f"ok/min={out['models'][mk]['ok_requests_per_min']}", flush=True)

    out["total_ok_in_window"] = total_ok
    out["total_attempts_in_window"] = total_attempts
    out["total_ok_requests_per_min"] = round(total_ok / args.seconds * 60.0, 1)
    out["neurons_total"] = round(sum(v["neurons"] for v in out["models"].values()), 2)
    out["usd_total"] = round(out["neurons_total"] / 1000 * 0.011, 6)
    print(f"  TOTAL ok/min={out['total_ok_requests_per_min']} "
          f"(single-model ceiling was ~1700/min)")
    print(f"\nneurons={out['neurons_total']} usd={out['usd_total']} "
          f"-> results/{args.out}")
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
