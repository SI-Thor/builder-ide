"""EXP C -- a first hysteresis gate on a decision task.

The idea under test: put a temporal gate BETWEEN perception and logic, so
that the decision only changes when the evidence has moved decisively. In
builder-ide terms this is the seam between "what the night perceives" and
"what the ship's computer decides", and it is the same shape as the tiles
chooser's stickiness (core/tiles/chooser.py) and the critic's re-arming.

The task is a five-way classification of sea state, with the ground truth
computed from the data (never from the model), and with a controlled amount
of perceptual noise: each step the state text mentions the true condition
plus a decoy, and with probability p the decoy is presented as the true one.
Near a boundary the model's probability vector wobbles, and a gate that
requires a margin before switching can suppress those wobbles.

What is measured:
  * flip rate      -- decisions changed per step, with and without the gate;
  * accuracy       -- per step, with and without the gate;
  * the lag cost   -- hysteresis delays a correct reversal, and that is the
                       price paid for the lower flip rate.

The raw probability trace is written out, so the whole analysis can be redone
offline without touching the GPU again.

Coordination with lab-cascade: their E2 is a cleanup loop that escalates a
low-confidence answer to a bigger model. That is a different mechanism --
escalation changes the MODEL, this gate changes only the THRESHOLD over the
same model's output. E2's subject is "is a small model enough"; this
subject is "should the decision hold still". No accuracy task, no precision
ladder, no cloud call.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d1lab import Server, box_state, decide, get_json, stats, warm_gpu, write_result

# ---------------------------------------------------------------- task ------

SEA_STATES = [
    ("flat calm", "the water is flat as glass between the breakwaters, no chop at all"),
    ("slight chop", "a light ripple runs across the water, short and regular, nothing breaking"),
    ("rough swell", "a long heavy swell comes up from the southwest and the whole boat lifts on it"),
    ("confused chop", "the sea is confused with rain on it, chop from two directions at once"),
    ("breaking water", "white water is breaking over the shoal and spray is coming aboard"),
]

OPTIONS = {
    "type": "choice",
    "instructions": "What is the sea state?",
    "criteria": {
        "A": "flat calm: the water is flat as glass, no chop, no swell",
        "B": "slight chop: a light ripple, short and regular, nothing breaking",
        "C": "rough swell: a long heavy swell, the boat lifts on it",
        "D": "confused chop: chop from two directions at once, often with rain",
        "E": "breaking water: white water over the shoal, spray coming aboard",
    },
}

#: the state text: the true condition, plus a decoy that may be presented
#: as the true one. The ground truth is always the TRUE condition.
TRUE_TEXT = [f"The sea is {name}: {desc}." for name, desc in SEA_STATES]


def make_trial(rng: random.Random, n_steps: int, noise: float) -> list[dict]:
    """A time series of sea states that changes slowly, with perceptual noise."""
    steps = []
    truth = rng.randrange(len(SEA_STATES))
    dwell = 0
    for t in range(n_steps):
        if dwell <= 0:
            truth = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
            dwell = rng.randint(3, 9)
        dwell -= 1
        decoy = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
        shown = truth
        if rng.random() < noise:
            shown = decoy
        # the text names the shown condition first, then names the other one
        other = decoy if shown != decoy else (truth + 1) % len(SEA_STATES)
        state = (TRUE_TEXT[shown] + " " + TRUE_TEXT[other])
        steps.append({
            "t": t,
            "truth": truth,
            "shown": shown,
            "decoy": other,
            "state": state,
        })
    return steps


# -------------------------------------------------------------- the gate ----

def sticky_choice(p: dict[str, float], current: str | None, margin: float) -> str:
    """Sticky argmax: only leave the current option when another beats it by `margin`.

    margin == 0 is plain argmax (no gate).
    """
    best = max(p, key=lambda k: float(p[k]))
    if current is None:
        return best
    if float(p[best]) > float(p[current]) + margin:
        return best
    return current


def apply_gate(trace: list[dict], margin: float) -> dict:
    """Run the gate over a recorded probability trace (offline, free)."""
    current = None
    chosen, flips = [], 0
    for row in trace:
        c = sticky_choice(row["probs"], current, margin)
        if current is not None and c != current:
            flips += 1
        current = c
        chosen.append(c)
    n = len(trace)
    correct = sum(1 for row, c in zip(trace, chosen)
                  if c == "ABCDE"[row["truth"]])
    # accuracy of the ungated decision, for the delta
    raw = [max(r["probs"], key=lambda k: float(r["probs"][k])) for r in trace]
    raw_correct = sum(1 for r, c in zip(trace, raw) if c == "ABCDE"[r["truth"]])
    return {
        "margin": margin,
        "flips": flips,
        "flip_rate": round(flips / n, 4) if n else None,
        "accuracy": round(correct / n, 4) if n else None,
        "ungated_accuracy": round(raw_correct / n, 4) if n else None,
        "accuracy_delta": round((correct - raw_correct) / n, 4) if n else None,
    }


def run_model(url: str, trials: list[list[dict]], model_name: str) -> list[dict]:
    trace = []
    for trial in trials:
        for row in trial:
            st, body, secs = decide(url, row["state"], {"sea": OPTIONS})
            if st != 200:
                raise RuntimeError(f"decide failed {st}: {body}")
            trace.append({
                "t": row["t"],
                "trial": trace and None,  # placeholder, filled below
                "truth": row["truth"],
                "shown": row["shown"],
                "probs": body["answers"]["sea"]["probabilities"],
                "confidence": body["answers"]["sea"].get("confidence"),
                "wall_ms": round(secs * 1000, 2),
            })
    # tag trials properly
    idx = 0
    for ti, trial in enumerate(trials):
        for _ in trial:
            trace[idx]["trial"] = ti
            idx += 1
    return trace


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "d1-2B"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8293
    n_trials = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    n_steps = int(sys.argv[4]) if len(sys.argv) > 4 else 40
    noise = float(sys.argv[5]) if len(sys.argv) > 5 else 0.35
    seed = 20261031

    out = {
        "experiment": "exp_c_hysteresis",
        "question": "does a hysteresis gate between perception and logic cut flip rate without costing accuracy?",
        "model": model, "precision": "Q8", "port": port,
        "task": "five-way sea-state classification; ground truth from the data; "
                "controlled perceptual noise (shown!=truth with p=noise)",
        "design": {"n_trials": n_trials, "n_steps_per_trial": n_steps,
                   "noise_prob": noise, "seed": seed},
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "box_at_start": box_state(),
    }

    rng = random.Random(seed)
    trials = [make_trial(rng, n_steps, noise) for _ in range(n_trials)]

    srv = Server(model=model, precision="Q8", port=port)
    srv.start()
    out["server_log"] = str(srv.log)
    try:
        warm_gpu(srv.url, {"sea": OPTIONS}, seconds=3.0)
        t0 = time.time()
        trace = run_model(srv.url, trials, model)
        out["model_seconds"] = round(time.time() - t0, 2)
    finally:
        srv.stop()

    out["latency_ms_per_decision"] = stats([r["wall_ms"] for r in trace])
    out["confidence_stats"] = stats([r["confidence"] for r in trace if r.get("confidence") is not None])
    out["accuracy_by_shown_equals_truth"] = {
        "when_shown_is_truth": round(sum(
            1 for r in trace if r["shown"] == r["truth"] and
            max(r["probs"], key=lambda k: float(r["probs"][k])) == "ABCDE"[r["truth"]]
        ) / max(1, sum(1 for r in trace if r["shown"] == r["truth"])), 4),
        "when_shown_is_noise": round(sum(
            1 for r in trace if r["shown"] != r["truth"] and
            max(r["probs"], key=lambda k: float(r["probs"][k])) == "ABCDE"[r["truth"]]
        ) / max(1, sum(1 for r in trace if r["shown"] != r["truth"])), 4),
        "n_shown_is_truth": sum(1 for r in trace if r["shown"] == r["truth"]),
        "n_shown_is_noise": sum(1 for r in trace if r["shown"] != r["truth"]),
    }

    out["gate_sweep"] = []
    for margin in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
        g = apply_gate(trace, margin)
        # per-trial flip rate as well: the gate should not just freeze one trial
        out["gate_sweep"].append(g)

    # the same gate applied per trial (a gate is per scene, not global)
    out["gate_sweep_per_trial"] = []
    for margin in (0.0, 0.10, 0.20, 0.30):
        per = []
        by_trial = {}
        for r in trace:
            by_trial.setdefault(r["trial"], []).append(r)
        for ti, rows in sorted(by_trial.items()):
            per.append(apply_gate(rows, margin))
        out["gate_sweep_per_trial"].append({
            "margin": margin,
            "mean_flip_rate": round(sum(p["flip_rate"] for p in per) / len(per), 4),
            "mean_accuracy": round(sum(p["accuracy"] for p in per) / len(per), 4),
            "mean_ungated_accuracy": round(sum(p["ungated_accuracy"] for p in per) / len(per), 4),
            "per_trial_flips": [p["flips"] for p in per],
        })

    # where the model is actually uncertain -- how much room does a gate have?
    margins = []
    for r in trace:
        p = {k: float(v) for k, v in r["probs"].items()}
        s = sorted(p.values(), reverse=True)
        margins.append(s[0] - s[1])
    out["decision_margin_stats"] = stats(margins)
    out["fraction_within_0.10_of_a_flip"] = round(
        sum(1 for m in margins if m < 0.10) / len(margins), 4)
    out["fraction_within_0.20_of_a_flip"] = round(
        sum(1 for m in margins if m < 0.20) / len(margins), 4)

    # save the raw trace so the analysis can be redone without the GPU
    trace_path = write_result(f"exp_c_trace_{model}.json", {"trace": trace, "trials": trials})
    out["trace_file"] = str(trace_path)

    out["box_at_end"] = box_state()
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    p = write_result(f"exp_c_hysteresis_{model}.json", out)
    print(json.dumps({
        "model": model,
        "latency_ms_per_decision": out["latency_ms_per_decision"],
        "accuracy_by_shown_equals_truth": out["accuracy_by_shown_equals_truth"],
        "decision_margin_stats": out["decision_margin_stats"],
        "gate_sweep": out["gate_sweep"],
        "gate_sweep_per_trial": out["gate_sweep_per_trial"],
    }, indent=2))
    print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
