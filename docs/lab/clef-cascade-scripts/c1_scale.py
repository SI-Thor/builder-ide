"""C1 -- scale: Clef-flash and Clef-27B on Workers AI at real concurrency.

The question Casey asked: "the Thor can run it, but so can the Cloudflare
Workers themselves, so tests can be done on the ProArt with the cloud
version, and scale."

Matrix: 2 models x 4 concurrency levels x 2 question packs (1 question vs
the full 64-question pack), all through a local `wrangler dev --remote`
proxy -- nothing is deployed.

Every call is metered.  Workers AI returns `usage.input_tokens`; the
published per-model neuron rate turns that into neurons and dollars, so the
run's cost is known while it is running, not after.

Latency is recorded twice: client-side (what a caller sees, including the
dev-proxy hop) and inside the Worker (around env.AI.run), so the hop can be
separated from the inference.
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
from decision_client import (MODELS, canonical_questions, neurons_for, pct)

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)


def pack_for(seed: int, pack: str):
    if pack == "q1":
        return gates.one_gate_pack(seed)
    return gates.build_gates(seed)


def classify_error(status: int, raw) -> str:
    """Name the failure mode: rate limit, out-of-capacity, auth, other.

    Workers AI reports these inside a 500 from the AI binding:
      3021  "rate limiting: inference request per min rate reached"
      3040  "Capacity temporarily exceeded, please try again"
    """
    if status == 200:
        return "ok"
    if status == 429:
        return "throttle_429"
    text = json.dumps(raw) if not isinstance(raw, str) else raw
    if "3021" in text or "rate limit" in text.lower():
        return "rate_limited_3021"
    if "3040" in text or "capacity" in text.lower():
        return "out_of_capacity_3040"
    if status == 3040:
        return "out_of_capacity_3040"
    if "429" in text or "too many" in text.lower():
        return "throttle"
    if "401" in text or "403" in text or "auth" in text.lower():
        return "auth"
    if "quota" in text.lower() or "limit" in text.lower():
        return "quota"
    return f"http_{status}"


def run_cell(model: str, pack: str, concurrency: int, n_calls: int,
             seeds: list[int], backend, timeout: float = 180.0,
             budget: dict | None = None) -> dict:
    """One matrix cell: n_calls requests at the given concurrency.

    `budget` is a shared {"neurons": float, "max": float} meter.  A call is
    refused once the projected total would pass `max`, so the run can never
    walk past its cost ceiling mid-cell.
    """
    results: list[dict] = []
    lock = threading.Lock()
    idx = threading.Lock()
    counter = {"i": 0}

    def one() -> None:
        with idx:
            i = counter["i"]
            counter["i"] += 1
        seed = seeds[i % len(seeds)]
        questions, truth = pack_for(seed, pack)
        qs = canonical_questions(questions)
        if budget is not None:
            with lock:
                if budget["neurons"] >= budget["max"]:
                    return
        status, raw, ms = backend.ask(_state_for(seed), qs, model)
        rec = {"i": i, "seed": seed, "status": status, "ms": ms,
               "err": classify_error(status, raw)}
        if status == 200:
            usage = raw.get("usage") or {}
            rec["in_tokens"] = int(usage.get("input_tokens", 0) or 0)
            rec["out_tokens"] = int(usage.get("output_tokens", 0) or 0)
            rec["worker_ms"] = raw.get("__worker_ms__")
            answers = raw.get("answers", {})
            rec["answers"] = _flatten_answers(answers, truth)
            rec["correct"] = _score(answers, truth)
        else:
            rec["raw_err"] = (json.dumps(raw)[:300] if not isinstance(raw, str) else raw[:300])
        with lock:
            results.append(rec)

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(lambda _: one(), range(n_calls)))
    wall = time.perf_counter() - t_start

    ok = [r for r in results if r["status"] == 200]
    lat = sorted(r["ms"] for r in ok)
    errs = Counter(r["err"] for r in results if r["status"] != 200)
    toks = sum(r.get("in_tokens", 0) for r in ok)
    neurons = neurons_for(model, toks)
    per_gates: list[float] = []
    for r in ok:
        c = r.get("correct") or []
        if c:
            per_gates.append(sum(c) / len(c))
    gate_acc = statistics.mean(per_gates) if per_gates else None

    return {
        "model": model, "pack": pack, "concurrency": concurrency,
        "n_calls": n_calls, "n_ok": len(ok),
        "wall_s": round(wall, 3),
        "throughput_rps": round(len(ok) / wall, 3) if wall > 0 else 0.0,
        "latency_ms": {
            "p50": round(pct(lat, .50), 1) if lat else None,
            "p95": round(pct(lat, .95), 1) if lat else None,
            "p99": round(pct(lat, .99), 1) if lat else None,
            "mean": round(statistics.mean(lat), 1) if lat else None,
            "min": round(min(lat), 1) if lat else None,
            "max": round(max(lat), 1) if lat else None,
        },
        "errors": dict(errs),
        "error_rate": round(1 - len(ok) / max(1, len(results)), 4),
        "input_tokens_total": toks,
        "input_tokens_per_call": round(toks / len(ok), 1) if ok else None,
        "neurons_total": round(neurons, 3),
        "neurons_per_call": round(neurons / len(ok), 4) if ok else None,
        "usd_at_published_rate": round(neurons / 1000 * 0.011, 6),
        "gate_accuracy": round(gate_acc, 4) if gate_acc is not None else None,
        "per_call": results,
    }


# --- state injection -----------------------------------------------------
_STATE_CACHE: dict[int, str] = {}


def _state_for(seed: int) -> str:
    if seed not in _STATE_CACHE:
        from tasks import scene_state, _world
        g, a, b, es = _world(seed)
        _STATE_CACHE[seed] = scene_state(g, a, b, es)
    return _STATE_CACHE[seed]


def _flatten_answers(answers: dict, truth: dict) -> dict:
    out = {}
    for qid, a in (answers or {}).items():
        if a.get("type") == "noul":
            out[qid] = round(float(a.get("noul", 0.0)), 4)
        else:
            out[qid] = a.get("choice")
    return out


def _score(answers: dict, truth: dict) -> list[bool]:
    out = []
    for qid, want in truth.items():
        a = answers.get(qid) or {}
        if isinstance(want, bool):
            out.append((float(a.get("noul", 0.0)) >= 0.5) == want)
        else:
            out.append(a.get("choice") == want)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c1-scale.json")
    ap.add_argument("--calls-q1", type=int, default=128)
    ap.add_argument("--calls-q64", default="flash=64,clef27=16",
                    help="per-model call count for the 64-question pack; "
                         "the 27B pack costs ~140 neurons a call")
    ap.add_argument("--concurrency", default="1,8,32,128")
    ap.add_argument("--models", default="flash,clef27")
    ap.add_argument("--packs", default="q1,q64")
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    ap.add_argument("--max-neurons", type=float, default=20000.0,
                    help="hard ceiling on neurons for the whole run")
    args = ap.parse_args()

    from decision_client import ClefAI
    backend = ClefAI(url=args.url)

    model_keys = [m.strip() for m in args.models.split(",") if m.strip()]
    packs = [p.strip() for p in args.packs.split(",") if p.strip()]
    concs = [int(c) for c in args.concurrency.split(",") if c.strip()]
    q64_counts: dict[str, int] = {}
    for part in args.calls_q64.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            q64_counts[k.strip()] = int(v)
    default_q64 = int(next(iter(q64_counts.values()), 16))

    matrix = []
    t0 = time.perf_counter()
    budget = {"neurons": 0.0, "max": args.max_neurons}
    order = []
    for pack in packs:
        for mk in model_keys:
            for c in concs:
                order.append((mk, pack, c))
    for mk, pack, c in order:
        model = MODELS[mk]
        n = args.calls_q1 if pack == "q1" else q64_counts.get(mk, default_q64)
        seeds = list(range(1000, 1000 + max(n, 64)))
        if budget["neurons"] >= budget["max"]:
            print(f"SKIP {mk} {pack} c={c}: neuron budget reached "
                  f"({budget['neurons']:.0f}/{budget['max']:.0f})")
            continue
        cell = run_cell(model, pack, c, n, seeds, backend, budget=budget)
        budget["neurons"] = sum(x["neurons_total"] for x in matrix)
        matrix.append(cell)
        lat = cell["latency_ms"]
        print(f"{mk:7s} {pack:4s} c={c:<4d} n={n:<4d} "
              f"ok={cell['n_ok']}/{n} p50={lat['p50']} p95={lat['p95']} "
              f"p99={lat['p99']} rps={cell['throughput_rps']} "
              f"err={cell['error_rate']} "
              f"tok/call={cell['input_tokens_per_call']} "
              f"neur/call={cell['neurons_per_call']} "
              f"acc={cell['gate_accuracy']} "
              f"[neurons {budget['neurons']:.0f}/{budget['max']:.0f}]", flush=True)

    neurons = sum(c["neurons_total"] for c in matrix)
    out = {
        "experiment": "C1 scale",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": f"wrangler dev --remote proxy at {args.url}",
        "wall_s": round(time.perf_counter() - t0, 1),
        "neurons_total": round(neurons, 3),
        "usd_total": round(neurons / 1000 * 0.011, 6),
        "free_tier_neurons_per_day": 10000,
        "free_tier_note": "Workers Free: 10,000 neurons/day free; over that the "
                          "API errors. Workers Paid: $0.011 per 1,000 neurons.",
        "matrix": matrix,
    }
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    print(f"\nneurons={neurons:.1f} usd={out['usd_total']} wall={out['wall_s']}s "
          f"-> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
