"""EXP A -- d1 latency per decision, decomposed.

Why this and not "the latency of d1":

The brief's claims check turns on a distinction the chats never made. The
chat claim is "d1-3B at 16 ms", and the box's own earlier number is "~90 ms
for a 3-question pack, ~11 ms per option". Those two are not measuring the
same thing, and the difference is the whole point:

  * a STANDALONE decision re-reads a fresh state every time, so it pays the
    full prefill of (state + question + options) plus the option scoring;
  * a question PACK shares one state prefix across several questions, so the
    first question pays the prefill and every additional question only pays
    the marginal cost of its own suffix.

If "16 ms" is the marginal cost of an extra question in a pack, it is a real
number and it is also the wrong number to size a robot loop on, because a
robot's loop gets a new state every tick and therefore never gets the
shared prefix.

So this measures BOTH, on one cell (d1-3B Q8), and reports the curve.

Coordination with lab-cascade: their E1 sweeps the full 3 sizes x 3
precisions x 3 tasks ladder and reports one latency number per cell. This
script runs ONE cell (d1-3B Q8) and measures a quantity E1 does not: the
standalone-vs-pack decomposition and the marginal cost of an additional
question. It does not re-measure the ladder, and it does not measure
accuracy at all.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d1lab import (Server, box_state, decide, get_json, get_text, stats,
                    summarise_state, warm_gpu, write_result)

MODEL = "d1-3B"
PRECISION = "Q8"
PORT = 8290

#: A tiles-shaped decision: a short scene, K scripted options, pick one.
#: Fixed shape so token counts stay comparable across requests.
SCENES = [
    "A lone rowboat is tied to a weathered post at the north dock. The tide is high and the "
    "channel is running fast past the mooring. A school of small silver fish is visible in "
    "the shallow water off the point, and the light is flat and grey.",
    "The skiff drifts alongside the ledge where the kelp beds end. The engine idles. Water is "
    "clear enough to see the bottom ten feet down, and several large shapes move slowly "
    "along the rock. The morning is calm and the swell is almost nothing.",
    "Rain is starting on the far shore and the sea has a confused chop. The boat is at the edge "
    "of the tide race where two currents meet. Visibility is poor past fifty metres and the "
    "buoys are hard to pick out.",
    "Deep water beyond the bank, clean swell rolling from the southwest, and a long line of "
    "birds working a seam a few hundred yards off the bow. The deck is wet and everything "
    "stays quiet.",
    "The harbour mouth at slack water. Nets drying on the rail, gulls on the mast, and the "
    "water flat as glass between the breakwaters.",
]

OPTIONS = {
    "type": "choice",
    "instructions": "Which action should the skipper take right now?",
    "criteria": {
        "A": "hold position and work the tide until it slackens",
        "B": "run out to the fish and work them while the light holds",
        "C": "run for the shelter of the point and wait out the weather",
        "D": "follow the birds out past the bank and set a long drift",
        "E": "make for the harbour and tie up for the night",
    },
}


def question_set(k: int) -> dict:
    """k distinct questions sharing one state prefix."""
    asks = [
        ("where", "Where is the best water to be working right now?"),
        ("tide", "How should the skipper read the tide from this state?"),
        ("weather", "What is the weather doing, and is it getting worse?"),
        ("gear", "Which piece of gear wants attention first?"),
        ("plan", "What is the one thing to do next, and why?"),
    ]
    out = {}
    for i, (qid, instr) in enumerate(asks[:k]):
        out[f"{qid}"] = {"type": "choice", "instructions": instr, "criteria": OPTIONS["criteria"]}
    return out


def prompt_metrics(url: str) -> dict:
    """llamacpp's /metrics is Prometheus text, not JSON -- proof that the pack
    shares a prefix rather than re-reading it."""
    st, body = get_text(url, "/metrics")
    if st != 200 or not isinstance(body, str):
        return {}
    vals = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("llamacpp:"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                vals[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return {
        "prompt_tokens_total": vals.get("llamacpp:prompt_tokens_total"),
        "prompt_tokens_cached_total": vals.get("llamacpp:prompt_tokens_cached_total"),
    }


def run_block(url: str, k: int, n: int, label: str) -> dict:
    """One block: n requests, each with k questions over one fresh state."""
    qs = question_set(k)
    warm = warm_gpu(url, {"warm": qs["where"]}, seconds=3.0)
    before = prompt_metrics(url)

    samples = []
    states = []
    for i in range(n):
        state = SCENES[i % len(SCENES)]
        st, body, secs = decide(url, state, qs)
        if st != 200:
            raise RuntimeError(f"decide failed: {st} {body}")
        # the box state is sampled every 5th request: it costs ~1 s, and the
        # block's state range is what matters, not every single sample
        if i % 5 == 0:
            states.append(box_state())
        samples.append({
            "wall_s": round(secs * 1000, 2),
            "input_tokens": body["usage"]["input_tokens"],
            "n_questions": k,
        })
    states.append(box_state())
    after = prompt_metrics(url)

    cached = ((after.get("prompt_tokens_cached_total") or 0)
              - (before.get("prompt_tokens_cached_total") or 0))
    processed = ((after.get("prompt_tokens_total") or 0)
                 - (before.get("prompt_tokens_total") or 0))
    walls = [s["wall_s"] for s in samples]

    return {
        "label": label,
        "n_questions_per_request": k,
        "n_requests": n,
        "latency_ms_per_request": stats(walls),
        "latency_ms_per_question_amortised": stats([w / k for w in walls]),
        "input_tokens_per_request": stats([s["input_tokens"] for s in samples]),
        "server_prompt_tokens_processed": processed,
        "server_prompt_tokens_cached": cached,
        "cached_fraction": round(cached / processed, 3) if processed else None,
        "warmup": warm,
        "box": summarise_state(states),
    }


def main() -> int:
    out = {
        "experiment": "exp_a_latency",
        "question": "what does a d1 decision actually cost, standalone vs in a shared-prefix pack?",
        "model": MODEL,
        "precision": PRECISION,
        "decision_type": "lfm2-d1 (LFM2 architecture, 32k ctx)",
        "server": "~/llama.cpp-upstream/build-up/bin/llama-server, /v1/systemone",
        "port": PORT,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "box_at_start": box_state(),
    }

    srv = Server(model=MODEL, precision=PRECISION, port=PORT)
    srv.start()
    out["server_log"] = str(srv.log)
    try:
        # sanity: the endpoint must answer a decision
        st, body, _ = decide(srv.url, SCENES[0], question_set(1))
        out["sanity"] = {"status": st, "answer": body.get("answers", {}).get("where")}
        if st != 200:
            raise RuntimeError(f"sanity failed: {body}")

        # Interleave the variants: on a shared box, sequential blocks let
        # drift masquerade as a difference (IDEAS.md rule 4). Each block is
        # already a randomised sample of the same scenes; we also re-measure
        # the k=1 block at the end, so any drift shows up as a difference
        # between the two k=1 blocks.
        blocks = []
        for k in (1, 2, 3, 5):
            blocks.append(run_block(srv.url, k, n=30, label=f"pack{k}"))
        blocks.append(run_block(srv.url, 1, n=30, label="pack1_repeat"))
        out["blocks"] = blocks

        # Derive the marginal cost of an extra question in a shared-prefix pack.
        by_label = {b["label"]: b for b in blocks}
        marginal = {}
        for k in (2, 3, 5):
            a = by_label[f"pack{k}"]["latency_ms_per_request"]["p50"]
            b = by_label["pack1"]["latency_ms_per_request"]["p50"]
            marginal[f"marginal_p50_ms_per_extra_question_pack{k}_vs_pack1"] = round((a - b) / (k - 1), 2)
        standalone = by_label["pack1"]["latency_ms_per_request"]["p50"]
        marginal["standalone_p50_ms_per_decision"] = standalone
        marginal["pack1_repeat_p50_ms"] = by_label["pack1_repeat"]["latency_ms_per_request"]["p50"]
        marginal["drift_check_p50_delta_ms"] = round(
            marginal["pack1_repeat_p50_ms"] - standalone, 2)
        pack3 = by_label["pack3"]["latency_ms_per_request"]["p50"]
        marginal["chat_claim_16ms_versus"] = {
            "standalone_per_decision_p50_ms": standalone,
            "pack3_total_p50_ms": pack3,
            "pack3_amortised_per_decision_p50_ms": by_label["pack3"]["latency_ms_per_question_amortised"]["p50"],
            "marginal_extra_question_p50_ms": marginal.get("marginal_p50_ms_per_extra_question_pack3_vs_pack1"),
        }
        out["derived"] = marginal
    finally:
        srv.stop()
        out["box_at_end"] = box_state()
        out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    p = write_result("exp_a_latency.json", out)
    print(json.dumps(out["derived"], indent=2))
    print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
