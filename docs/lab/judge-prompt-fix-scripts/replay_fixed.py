"""The fresh recording: the same 240 steps, the prompt's order fixed.

**What this is.** §7 of the calibration note replayed the recorded sea-state
steps with the two named conditions swapped, and settled the mechanism: the
d1-2B answers the condition the prompt names **first** (85.8 % of its
two-condition steps), so the state's order — the recorder's presentation
choice — is the model's answer. This script records what the same 240 steps
score when the order stops carrying that information, on the same served
models, in one session, beside the box state.

**The three arms.** Every step is asked three times, once per arm:

* ``recorded`` — the recorded state text, verbatim. This is the control: its
  live replies are compared with the October recording vector against vector
  (the instrument check §7 ran), and its numbers are the "before".
* ``canonical`` — the state rebuilt to name **the true condition and the
  decoy** (the recorder's own stated intent: *the state text mentions the
  true condition plus a decoy*), in ``core.judge.ordering``'s canonical
  order — sorted by the condition's own name, a key unrelated to which is
  true.
* ``balanced`` — the same pair, in the seeded balanced order (sha256 over
  the step's ``(trial, t)`` key): half the steps name either condition
  first, deterministic per step, unrelated to the truth.

The rebuilt arms change the named pair on the noise steps, and that is
deliberate: on those steps the recorded prompt names the decoy and a
neighbour of the truth, so **the truth is not in the prompt at all** and no
answer can be right (§7.1's bound — 82 of the 2B's 114 errors unwinnable).
An order fix alone cannot raise an accuracy that is pinned at zero by
arithmetic; naming the truth and the decoy — which the recorder's docstring
always claimed to do — is what makes the decoy-first steps answerable.

**The arms rotate.** The three calls of a step go in an order that rotates
with the step index, so "which arm went first" and "which arm is which" are
not the same variable.

**The determinism control.** After the main pass the first ``--repeat-steps``
steps are asked again in each arm; every repeat must return the vector it
returned the first time, which is the run's own check that the difference
between arms is the prompt and not the run. The ``recorded`` arm keeps §7's
control too: the 43 steps whose prompt names one condition twice must
reproduce the October vectors byte for byte.

**Usage** (on the Thor, with a d1 model served):

    python3 replay_fixed.py --model d1-2B --port 8094 --out results/fresh-d1-2B.json
    python3 replay_fixed.py --model d1-3B --port 8320 --out results/fresh-d1-3B.json

Reads the October trace, asks 240 x 3 calls plus the repeats, and writes one
JSON. No analysis: the analysis is ``measure_fixed.py``, which reads these
files and the trace and makes no model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

import sys

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from core.judge.ordering import (  # noqa: E402
    canonical_order,
    condition_name,
    named_sentences,
    balanced_order,
)

#: where the October traces live on the Thor.
TRACES = Path("/home/caseydigennaro/lm-wt/liquid-study/results")

#: the conditions and their sentences, copied verbatim from the recorder
#: (liquid-study's scripts/exp_c_hysteresis.py) so the rebuilt states are
#: built from the recorder's own material and nothing invented here.
SEA_STATES: list[tuple[str, str]] = [
    ("flat calm", "the water is flat as glass between the breakwaters, no chop at all"),
    ("slight chop", "a light ripple runs across the water, short and regular, nothing breaking"),
    ("rough swell", "a long heavy swell comes up from the southwest and the whole boat lifts on it"),
    ("confused chop", "the sea is confused with rain on it, chop from two directions at once"),
    ("breaking water", "white water is breaking over the shoal and spray is coming aboard"),
]

#: the sentence each condition names, indexed by condition number.
TRUE_TEXT: list[str] = [f"The sea is {name}: {desc}." for name, desc in SEA_STATES]

#: the question, the recorder's own.
QUESTIONS: dict[str, Any] = {
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

#: every state sentence starts with this.
MARKER = "The sea is "

#: the arms, in their home order; the per-step rotation moves them.
ARMS: tuple[str, ...] = ("recorded", "canonical", "balanced")


# --- the steps -------------------------------------------------------------


def load_steps(trace_path: Path) -> list[dict[str, Any]]:
    """The 240 recorded steps, in the order they were recorded.

    The same shape ``judge-reversed-scripts/replay_reversed.py`` reads: the
    trials hold the fields, the trace holds the recorded replies, the two
    are zipped and checked against each other.
    """
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = []
    for trial_index, trial in enumerate(data["trials"]):
        for row in trial:
            steps.append(
                {
                    "t": int(row["t"]),
                    "trial": trial_index,
                    "truth": int(row["truth"]),
                    "shown": int(row["shown"]),
                    "decoy": int(row["decoy"]),
                    "state": row["state"],
                }
            )
    recorded = data["trace"]
    if len(recorded) != len(steps):
        raise ValueError(
            f"the trace holds {len(recorded)} replies for {len(steps)} steps"
        )
    for step, row in zip(steps, recorded):
        if int(row["t"]) != step["t"]:
            raise ValueError("the trace and the trials are not in the same order")
        if int(row["truth"]) != step["truth"] or int(row["shown"]) != step["shown"]:
            raise ValueError("the trace and the trials disagree about a step")
        step["recorded"] = {
            "probs": {key: float(value) for key, value in row["probs"].items()},
            "confidence": row.get("confidence"),
            "wall_ms": row.get("wall_ms"),
        }
    return steps


def check_catalog(steps: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Every sentence the recorded states name is one of the recorder's.

    The rebuilt arms are built from TRUE_TEXT; this is the check that the
    recording was built from the same table, so the rebuild differs from
    the recording by the named pair and the order — and by nothing else.
    """
    catalog = {sentence.strip() for sentence in TRUE_TEXT}
    seen: dict[str, str] = {}
    for step in steps:
        for sentence in named_sentences(step["state"], MARKER):
            sentence = sentence.strip()
            if sentence not in catalog:
                raise ValueError(f"a recorded state names a sentence outside the catalog: {sentence!r}")
            name = condition_name(sentence, MARKER)
            if seen.setdefault(name, sentence) != sentence:
                raise ValueError(f"the recording holds two texts for {name!r}")
    missing = [
        condition_name(sentence, MARKER)
        for sentence in TRUE_TEXT
        if condition_name(sentence, MARKER) not in seen
    ]
    return {
        "sentences_seen": len(seen),
        "conditions_missing_from_the_recording": sorted(missing),
    }


def arm_state(step: dict[str, Any], arm: str) -> str:
    """The state text one arm asks.

    ``recorded`` is the recording's own text. The two fixed arms name the
    true condition and the decoy — the recorder's stated pair — in the
    order ``core.judge.ordering`` chooses; on a step where the recording
    already names that pair they differ from it by the order alone.
    """
    if arm == "recorded":
        return step["state"]
    if arm not in ("canonical", "balanced"):
        raise ValueError(f"unknown arm: {arm!r}")
    pair = [TRUE_TEXT[int(step["truth"])], TRUE_TEXT[int(step["decoy"])]]
    if arm == "canonical":
        ordered = canonical_order(pair, MARKER)
    else:
        ordered = balanced_order(pair, f"{step['trial']}:{step['t']}")
    return " ".join(ordered)


def is_noop(step: dict[str, Any]) -> bool:
    """True when the recorded prompt named the same condition twice."""
    return int(step["shown"]) == int(step["decoy"])


def is_noise(step: dict[str, Any]) -> bool:
    """True when the recorded prompt named a decoy first: the noise step."""
    return int(step["shown"]) != int(step["truth"])


# --- the model -------------------------------------------------------------


def post_decision(
    url: str, state: str, questions: dict[str, Any], timeout: float = 120.0
) -> tuple[int, dict[str, Any], float]:
    """One decision round. Returns (status, body, seconds)."""
    payload = json.dumps(
        {"state": state, "questions": {"sea": questions}}, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(
        url + "/v1/systemone", data=payload, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body, time.perf_counter() - started
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return error.code, {"error": detail}, time.perf_counter() - started


def answer_of(body: dict[str, Any], question: str = "sea") -> dict[str, Any]:
    """The reply's argmax, its vector and its confidence."""
    answers = body["answers"][question]
    probs = {key: float(value) for key, value in answers["probabilities"].items()}
    argmax = max(sorted(probs), key=lambda key: probs[key])
    return {
        "argmax": argmax,
        "probs": probs,
        "confidence": probs[argmax],
        "reported_confidence": answers.get("confidence"),
    }


def ask(url: str, state: str, timeout: float = 120.0) -> dict[str, Any]:
    """One decision round, with the answer and the time it took."""
    status, body, seconds = post_decision(url, state, QUESTIONS, timeout)
    if status != 200:
        raise RuntimeError(f"the decision failed: {status} {body}")
    answer = answer_of(body)
    answer["ms"] = round(seconds * 1000.0, 3)
    return answer


# --- the box ----------------------------------------------------------------

_TG_RE = {
    "ram_used_mb": re.compile(r"RAM (\d+)/(\d+)MB"),
    "cpu": re.compile(r"CPU \[([^\]]*)\]"),
    "gpu_temp_c": re.compile(r"gpu@([\d.]+)C"),
    "vdd_gpu_w": re.compile(r"VDD_GPU (\d+)mW"),
}


def box_state() -> dict[str, Any]:
    """The box state every number in this run is recorded beside."""
    state: dict[str, Any] = {"ts": time.time()}
    try:
        state["load"] = [round(value, 2) for value in os.getloadavg()]
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    state["mem_available_mb"] = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass
    try:
        probe = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
        )
        first = probe.stdout.strip().splitlines()[0]
        state["gpu_util_pct"], state["gpu_mem_mb"] = [x.strip() for x in first.split(",")]
    except Exception:
        pass
    try:
        probe = subprocess.run(
            ["timeout", "1", "tegrastats", "--interval", "250"],
            capture_output=True, text=True, timeout=8,
        )
        lines = (probe.stdout or "").strip().splitlines()
        line = lines[-1] if lines else ""
        if line:
            match = _TG_RE["ram_used_mb"].search(line)
            if match:
                state["ram_used_mb"] = int(match.group(1))
                state["ram_total_mb"] = int(match.group(2))
            match = _TG_RE["gpu_temp_c"].search(line)
            if match:
                state["gpu_temp_c"] = float(match.group(1))
            match = _TG_RE["vdd_gpu_w"].search(line)
            if match:
                state["vdd_gpu_w"] = int(match.group(1)) / 1000.0
            match = _TG_RE["cpu"].search(line)
            if match:
                freqs = [int(x) for x in re.findall(r"@(\d+)", match.group(1))]
                state["cpu_freq_mhz"] = freqs
                state["cpu_busy_cores"] = sum(
                    1 for x in re.findall(r"(\d+)%", match.group(1)) if int(x) > 50
                )
    except Exception:
        pass
    return state


def server_props(url: str) -> dict[str, Any]:
    """What the server says about itself: the model, the context, the slots."""
    try:
        with urllib.request.urlopen(url + "/props", timeout=10) as response:
            props = json.loads(response.read().decode("utf-8"))
    except Exception as error:  # pragma: no cover - a probe, not a measurement
        return {"error": str(error)}
    context = props.get("default_generation_settings", {})
    return {
        "model_path": props.get("model_path"),
        "n_ctx": context.get("n_ctx"),
        "n_parallel": context.get("n_parallel"),
        "build": props.get("build_info"),
        "total_slots": props.get("total_slots"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


# --- the replay -------------------------------------------------------------


def fidelity(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How close the live recorded-arm replies are to the October recording."""
    diffs: list[float] = []
    same_argmax = 0
    compared = 0
    noop_same = 0
    noop_compared = 0
    for row in rows:
        recorded = row.get("recorded")
        live = row["arms"]["recorded"]
        compared += 1
        for key, value in recorded["probs"].items():
            diffs.append(abs(float(value) - live["probs"].get(key, 0.0)))
        live_argmax = max(sorted(live["probs"]), key=lambda key: live["probs"][key])
        recorded_argmax = max(
            sorted(recorded["probs"]), key=lambda key: recorded["probs"][key]
        )
        if live_argmax == recorded_argmax:
            same_argmax += 1
        if row["identical_prompt"]:
            noop_compared += 1
            if live["probs"] == recorded["probs"]:
                noop_same += 1
    return {
        "compared": compared,
        "max_abs_diff": round(max(diffs), 12) if diffs else None,
        "mean_abs_diff": round(statistics.fmean(diffs), 12) if diffs else None,
        "argmax_identical": same_argmax,
        "argmax_identical_share": round(same_argmax / compared, 6) if compared else None,
        "the_noop_steps": {
            "compared": noop_compared,
            "vector_identical": noop_same,
        },
    }


def repeats(
    url: str,
    steps: Sequence[dict[str, Any]],
    first_rows: Sequence[dict[str, Any]],
    n: int,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Ask the first n steps again, in every arm; compare vector for vector."""
    checked = 0
    identical = 0
    per_arm: dict[str, dict[str, int]] = {arm: {"compared": 0, "identical": 0} for arm in ARMS}
    for index in range(min(n, len(steps))):
        for arm in ARMS:
            state = first_rows[index]["arms"][arm]["state"]
            again = ask(url, state, timeout)
            first = first_rows[index]["arms"][arm]
            checked += 1
            per_arm[arm]["compared"] += 1
            if again["probs"] == first["probs"]:
                identical += 1
                per_arm[arm]["identical"] += 1
    return {
        "steps": min(n, len(steps)),
        "calls": checked,
        "vector_identical": identical,
        "per_arm": per_arm,
    }


def arm_latency(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Per call latency, p50 and p95, per arm — from the calls as they ran."""
    def percentiles(values: Sequence[float]) -> dict[str, float | None]:
        if not values:
            return {"n": 0, "p50": None, "p95": None, "mean": None}
        ordered = sorted(values)

        def at(fraction: float) -> float:
            if len(ordered) == 1:
                return ordered[0]
            position = fraction * (len(ordered) - 1)
            low = int(position)
            high = min(low + 1, len(ordered) - 1)
            weight = position - low
            return ordered[low] * (1.0 - weight) + ordered[high] * weight

        return {
            "n": len(ordered),
            "p50": round(at(0.50), 3),
            "p95": round(at(0.95), 3),
            "mean": round(statistics.fmean(ordered), 3),
        }

    return {
        arm: percentiles([row["arms"][arm]["ms"] for row in rows]) for arm in ARMS
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--repeat-steps", type=int, default=12,
        help="how many leading steps the determinism control re-asks",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    trace_path = args.trace or (TRACES / f"exp_c_trace_{args.model}.json")
    out_path = args.out or (RESULTS / f"fresh-{args.model}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    steps = load_steps(trace_path)
    catalog = check_catalog(steps)
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    box_before = box_state()

    written: list[dict[str, Any]] = []

    def assemble(complete: bool) -> dict[str, Any]:
        return {
            "experiment": "judge-prompt-fix",
            "model": args.model,
            "url": url,
            "started": started,
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "complete": complete,
            "source_trace": {"path": str(trace_path), "sha256": _sha256(trace_path)},
            "server": server_props(url),
            "design": {
                "steps": len(steps),
                "arms": list(ARMS),
                "calls": len(ARMS) * len(steps),
                "arm_rotation": "rotates with the step index",
                "fixed_pair": "the true condition and the decoy, in a neutral order",
                "catalog_check": catalog,
            },
            "box": {"at_start": box_before, "after_replay": box_after, "at_end": box_end},
            "fidelity": fidelity(written) if len(written) == len(steps) else None,
            "latency_per_arm": arm_latency(written) if complete else None,
            "determinism": determinism,
            "steps": written,
        }

    determinism: dict[str, Any] = {}
    box_after: dict[str, Any] = {}
    box_end: dict[str, Any] = {}

    def progress(done: int, total: int) -> None:
        print(f"  {done}/{total} steps", flush=True)
        if done % 40 == 0:
            out_path.write_text(json.dumps(assemble(False), indent=2), encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        rotation = index % len(ARMS)
        order = [ARMS[(rotation + offset) % len(ARMS)] for offset in range(len(ARMS))]
        arms: dict[str, dict[str, Any]] = {}
        for arm in order:
            state = arm_state(step, arm)
            answer = ask(url, state, timeout=args.timeout)
            answer["state"] = state
            answer["named_first"] = condition_name(
                named_sentences(state, MARKER)[0], MARKER
            )
            arms[arm] = answer
        rows.append(
            {
                "t": step["t"],
                "trial": step["trial"],
                "truth": step["truth"],
                "shown": step["shown"],
                "decoy": step["decoy"],
                "identical_prompt": int(step["shown"]) == int(step["decoy"]),
                "arm_order": order,
                "arms": arms,
                "recorded": step.get("recorded"),
            }
        )
        written.clear()
        written.extend(rows)
        if (index + 1) % 20 == 0:
            progress(index + 1, len(steps))

    box_after = box_state()
    determinism = repeats(url, steps, rows, args.repeat_steps, timeout=args.timeout)
    box_end = box_state()

    result = assemble(True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"fidelity: {result['fidelity']}")
    print(f"determinism: {determinism}")
    print(f"latency per arm: {result['latency_per_arm']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
