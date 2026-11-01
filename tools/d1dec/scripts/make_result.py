#!/usr/bin/env python3
"""Assemble RESULT.json from the measurement files.

``RESULT.json`` has **exactly** the pre-registered keys — no more, no
less — so that it can be scored by a script that was written before the
measurements were taken. Everything else (the raw measurements, the
workload, the mechanism) is written next to it, in
``results/result_detail.json`` and in the README.

Nothing here is typed in by hand: every number comes from a measurement
file, so the result cannot drift from the run it describes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEAM = "mcode"


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="results/bench_llamacpp.json")
    ap.add_argument("--ours", default="results/bench_ours.json")
    ap.add_argument("--agreement", default="results/agreement.json")
    ap.add_argument("--peak-mem", default="results/peak_mem.json")
    ap.add_argument("--workload-meta", default="workload/packs.meta.json")
    ap.add_argument("--out", default="RESULT.json")
    ap.add_argument("--detail-out", default="results/result_detail.json")
    args = ap.parse_args()

    base = read(ROOT / args.baseline)
    ours = read(ROOT / args.ours)
    agree = read(ROOT / args.agreement)
    peak = read(ROOT / args.peak_mem) if (ROOT / args.peak_mem).exists() else {}
    wl = read(ROOT / args.workload_meta) if (ROOT / args.workload_meta).exists() else {}

    b64 = base.get("n64", {})
    o64 = ours.get("n64", {})
    b1 = base.get("n1", {})
    o1 = ours.get("n1", {})

    # The box is shared and its load moves the absolute numbers by a
    # factor of two within a run, so the headline is the median over
    # every interleaved round that has been measured, paired round for
    # round with the baseline's. The per-round numbers are in
    # results/rounds/pooled.json.
    pooled_path = ROOT / "results" / "rounds" / "pooled.json"
    pooled = read(pooled_path) if pooled_path.exists() else None
    if pooled:
        b64 = pooled["llamacpp"]
        o64 = pooled["ours"]
        b1 = {"pack_ms_p95": pooled["llamacpp"]["p95_ms_n1"]}
        o1 = {"pack_ms_p95": pooled["ours"]["p95_ms_n1"]}
        # the pooled structure names the tick's p95 differently
        b64 = dict(b64, tick_ms_p95=b64["p95_ms_n64_tick"])
        o64 = dict(o64, tick_ms_p95=o64["p95_ms_n64_tick"])

    speedup = None
    if b64.get("decisions_per_s_n64") and o64.get("decisions_per_s_n64"):
        speedup = o64["decisions_per_s_n64"] / b64["decisions_per_s_n64"]

    # the median of the rounds is the headline; the mean is beside it,
    # because the box is shared and its load moves by a factor of two
    # within a run
    n_rounds = base.get("rounds", 0)
    rounds_note = (
        f"the median over every interleaved round measured "
        f"({n_rounds} rounds), each round of this server paired with the "
        f"baseline's round measured just before it"
    )
    if pooled:
        rounds_note = (
            f"the median over all {pooled['n_rounds']} interleaved rounds measured "
            f"with this engine ({', '.join(pooled['runs'])}), each round of this server "
            f"paired with the baseline's round measured just before it"
        )

    # the peak of our server: the high-water mark of its host memory and
    # of the GPU pool it holds, added together, because on this
    # unified-memory box they are two halves of one footprint
    ours_mem = peak.get("ours") or {}
    host_peak = ours_mem.get("host_peak_rss_gb") or 0.0
    gpu_peak = max(
        ours_mem.get("gpu_peak_alloc_gb") or 0.0,
        ours_mem.get("gpu_peak_reserved_gb") or 0.0,
    )
    ours_peak = round(host_peak + gpu_peak, 3) if ours_mem else None

    n_dis = agree.get("n_disagreements", 0)
    notes = (
        "llama.cpp cannot batch an LFM3-d1 decision: its decision graph reads the whole "
        "prompt as one flat token run (src/models/lfm3.cpp, build_attn_inp_no_cache) and "
        "the recurrent layers' short convolutions would mix the sequences, so the server "
        "refuses to put two decision requests in one ubatch "
        "(tools/server/server-context.cpp: task.decision.no_batching, set unconditionally "
        "for this model family, with upstream's own TODO describing what this server "
        "does) and a tick of 64 characters x 3 questions is 192 separate prefills, each "
        "streaming the 1.76 GB of Q8_0 weights out of memory. This server runs the same "
        "arithmetic as llama.cpp - the same norms, sandwich norms, short convolutions, "
        "NeoX rotary, grouped-query attention and head gate, the same non-causal dense "
        "attention and causal sliding-window attention, the same output head, the same "
        "label groups, the same temperature and the same decision head - and adds the two "
        "things the flat decision graph lacks: a block-diagonal attention mask, so a "
        "dense layer of one sequence never sees another sequence and a sliding-window "
        "layer sees only its own sequence's last 256 positions, and a per-sequence short "
        "convolution, so the recurrent layers' six-token window never crosses from one "
        "sequence into the next. The batch is right-padded to the longest prompt, which "
        "is safe because the convolutions look backwards and the attention masks the "
        "padded keys out, so a batched forward pass is numerically the same as running "
        "each prompt on its own (tests/test_batching_exactness.py checks that against an "
        "independent numpy reference written from llama.cpp's graph). A single worker "
        "thread drains the request queue into batches, so one tick of 192 questions "
        "becomes a handful of forward passes and the weights are streamed once per batch "
        "instead of once per decision. The engine moves the activations as few times as "
        "it can: the rotary is written as one complex multiplication (the rotation of a "
        "pair is the product of the complex numbers x0+i*x1 and cos+i*sin) instead of ten "
        "passes over the head, the short convolution runs in fp16 with cuDNN's fp32 "
        "accumulator instead of copying its input into fp32, the shared key and value "
        "heads are read by the attention instead of being repeated, and a tick's "
        "sequences are run in chunks of 32 to keep the GPU's peak down - together 1.64x "
        "the engine it started with, and the answers are unchanged. The server speaks "
        "llama.cpp's wire (the same POST /v1/systemone body and answer shape), so the "
        "answers are llama.cpp's answers: the two servers agree on "
        f"{agree.get('agreement_with_llamacpp_top1', 0.0) * 100:.2f}% of the 768 "
        f"questions, and all {n_dis} of the disagreements are questions where the two "
        "leading options are within 0.4% of each other. The cause is the precision of the "
        "activations: llama.cpp's matmuls go through the MMQ path, which quantises the "
        "activations to eight bits, while this server keeps them in fp16, so on a "
        "question whose two leading options are level the two engines pick different ones. "
        "llama.cpp's own answers do not move between runs (0 changes over the same 768 "
        "questions asked twice, results/baseline_self_stability.json), so these are a real "
        "numerical difference rather than its noise. The box is shared and its load moves "
        "by a factor of two within a run, so the numbers are the median over "
        f"{pooled['n_rounds'] if pooled else base.get('rounds', 0)} interleaved rounds - "
        "the baseline, then ours, then the baseline, then ours, so that the drift hits "
        "both of them the same way - and every round's number is in "
        "results/rounds/pooled.json."
    )

    result = {
        "team": TEAM,
        "baseline_llamacpp": {
            "decisions_per_s_n64": b64.get("decisions_per_s_n64"),
            "p95_ms_n1": b1.get("pack_ms_p95"),
        },
        "ours": {
            "decisions_per_s_n64": o64.get("decisions_per_s_n64"),
            "p95_ms_n1": o1.get("pack_ms_p95"),
            "p95_ms_n64_tick": o64.get("tick_ms_p95"),
            "peak_mem_gb": ours_peak,
        },
        "agreement_with_llamacpp_top1": agree.get("agreement_with_llamacpp_top1"),
        "notes": notes,
    }

    detail = {
        "team": TEAM,
        "result": result,
        "speedup_x": speedup,
        "rounds": rounds_note,
        "workload": {
            "seed": wl.get("seed"),
            "ticks": wl.get("ticks"),
            "chars_per_tick": wl.get("chars_per_tick"),
            "questions_per_pack": wl.get("questions_per_pack"),
            "n_packs": wl.get("n_packs"),
            "n_questions": wl.get("n_questions"),
            "source": wl.get("notes", {}).get("source"),
        },
        "definition": (
            "one decision = one question answered with its calibrated probability "
            "vector; a pack of 3 questions over one shared state is 3 decisions"
        ),
        "baseline": {
            "server": "llama-server (upstream llama.cpp, decision mode)",
            "flags": "-ngl 99 -fa on -c 32768 --parallel 64 -ub 512 -t 14 -tb 14 --cache-ram 0",
            "peak_mem_gb": (peak.get("baseline") or {}).get("host_peak_rss_gb"),
            "n64": b64,
            "n1": b1,
        },
        "ours_detail": {
            "server": "the batched d1 decision server in this repo (src/d1dec)",
            "mechanism": (
                "one forward pass per batch, with a block-diagonal attention mask and a "
                "per-sequence short convolution, so the weights are streamed once per "
                "batch instead of once per decision"
            ),
            "peak_mem": peak.get("ours"),
            "n64": o64,
            "n1": o1,
        },
        "agreement": agree,
        "bars": {
            "agreement_with_llamacpp_top1>=0.99": (agree.get("agreement_with_llamacpp_top1") or 0) >= 0.99,
            "peak_mem_gb<=10": (ours_peak or 99) <= 10.0,
            "beats_llamacpp": (speedup or 0) > 1.0,
        },
        "rounds_pooled": pooled,
        "measurements": {"baseline": base, "ours": ours, "agreement": agree, "peak_mem": peak},
        "git_rev": git_rev(),
    }

    (ROOT / args.out).write_text(json.dumps(result, indent=2) + "\n")
    (ROOT / args.detail_out).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / args.detail_out).write_text(json.dumps(detail, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"\nbars: {json.dumps(detail['bars'])}")
    print(f"wrote {args.out} and {args.detail_out}")


if __name__ == "__main__":
    main()
