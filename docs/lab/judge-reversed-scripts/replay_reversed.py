"""Replay the recorded sea-state trace with the two named conditions swapped.

**What this is.** The October trace (`exp_c_trace_d1-2B.json`,
`exp_c_trace_d1-3B.json`) asked each of 240 sea-state steps in **one** order:
the prompt named the shown condition first and the other one second. The
calibration note then computed the both-order protocol's catch rate under one
stated assumption — that a reversed prompt makes the model answer the *other*
named condition — because the recording does not hold the reversed replies.
This script holds them: it asks every recorded step again, in both orders, on
the same server, in the same session, and writes the argmax and the full
probability vector of each reply.

**The swap.** A step's state text is two sentences, one per named condition:
``The sea is <shown>: .... The sea is <other>: ....``. The reversed prompt is
those two sentences the other way round. Nothing else changes: the question,
its five criteria and their letters A–E, the ground truth (always the true
condition, never the shown one) and the order of the calls are untouched. On
the 43 steps where the prompt named the *same* condition twice the two texts
are byte-identical, so the reversal is a no-op there — and those steps double
as the run's determinism control.

**The order inside the pair alternates.** Half the steps ask the original
prompt first and half ask the reversed one first, so "which condition the
prompt named first" and "which call came first in the pair" are not the same
variable.

**Fidelity.** Every live original-order reply is compared with the recorded
one, vector against vector. The live server is the instrument; the recorded
trace is the reference; the difference between them is written out per step.

**What this makes of the box.** Every number in the output is recorded beside
the box state it was taken under — the load, the free memory, the GPU's
utilisation, the CPU's busy cores and the GPU's clock and rail — because the
box is shared and absolute times drift under other seats' load.

**Usage** (on the Thor, with a d1 model served):

    python3 replay_reversed.py --model d1-2B --port 8094 --out results/replay-d1-2B.json
    python3 replay_reversed.py --model d1-3B --port 8320 --out results/replay-d1-3B.json

Reads the October trace, asks 240 x 2 questions, measures the latency of one
call, of two calls in sequence and of two calls at the same time, and writes
one JSON. No analysis: the analysis is `measure_reversed.py`, which reads
this file and the trace and makes no model call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Sequence

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

#: where the October traces live on the Thor.
TRACES = Path("/home/caseydigennaro/lm-wt/liquid-study/results")

#: the question, copied verbatim from the recorder (liquid-study's
#: scripts/exp_c_hysteresis.py) so the replay asks exactly what was asked.
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

#: every state sentence starts with this, which is what makes the swap a
#: sentence swap rather than a guess.
MARKER = "The sea is "

#: the option letters, in the order the criteria are written.
KEYS = "ABCDE"


# --- the steps -------------------------------------------------------------


def load_steps(trace_path: Path) -> list[dict[str, Any]]:
    """The 240 recorded steps, in the order they were recorded.

    The trace file holds the trials (with the state text and the ground truth)
    and the recorded replies (with the probabilities), in the same order: the
    recorder walked the trials in order and appended one trace row per step.
    The two are zipped here and checked against each other, so a mismatch is
    an error rather than a silently shifted row.
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


def split_state(state: str) -> tuple[str, str]:
    """The state's two sentences: the first-named condition and the second."""
    first = state.index(MARKER)
    second = state.index(MARKER, first + 1)
    return state[:second].strip(), state[second:].strip()


def swapped_state(state: str) -> str:
    """The same state with the two named conditions the other way round."""
    first, second = split_state(state)
    return f"{second} {first}"


def is_degenerate(step: dict[str, Any]) -> bool:
    """True when the prompt named the same condition twice: the swap is a no-op."""
    return int(step["shown"]) == int(step["decoy"])


# --- the model -------------------------------------------------------------


def post_decision(
    url: str, state: str, questions: dict[str, Any], timeout: float = 120.0
) -> tuple[int, dict[str, Any], float]:
    """One decision round. Returns (status, body, seconds).

    The request is the recorder's: one state, and the questions keyed by their
    id — ``{"state": ..., "questions": {"sea": <the choice>}}``. The endpoint
    reads each key of ``questions`` as a question id, so the choice's own
    fields must sit under one.
    """
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
    """The reply's argmax, its vector and its confidences."""
    answers = body["answers"][question]
    probs = {key: float(value) for key, value in answers["probabilities"].items()}
    argmax = max(sorted(probs), key=lambda key: probs[key])
    return {
        "argmax": argmax,
        "probs": probs,
        "confidence": probs[argmax],
        "reported_confidence": answers.get("confidence"),
        "usage": body.get("usage"),
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
    """The box state every number in this run is recorded beside.

    Best-effort: a probe that fails leaves its key out rather than killing the
    run, because the state is context for the numbers, not the measurement.
    """
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


# --- the replay -------------------------------------------------------------


def _replay_step(
    url: str, index: int, step: dict[str, Any], *, timeout: float = 120.0
) -> dict[str, Any]:
    """One step, asked in both orders.

    The pair's order alternates with the step's index, so "which condition
    the prompt named first" and "which call came first in the pair" are not
    the same variable.
    """
    original_state = step["state"]
    reversed_state = swapped_state(original_state)
    order = ("original", "reversed") if index % 2 == 0 else ("reversed", "original")
    calls: dict[str, dict[str, Any]] = {}
    for which in order:
        state = original_state if which == "original" else reversed_state
        calls[which] = ask(url, state, timeout)
    return {
        "t": step["t"],
        "trial": step["trial"],
        "truth": step["truth"],
        "shown": step["shown"],
        "decoy": step["decoy"],
        "state_original": original_state,
        "state_reversed": reversed_state,
        "identical_prompt": original_state == reversed_state,
        "first_call": order[0],
        "original": calls["original"],
        "reversed": calls["reversed"],
        "recorded": step.get("recorded"),
    }


def replay(
    url: str,
    steps: Sequence[dict[str, Any]],
    *,
    timeout: float = 120.0,
    progress_every: int = 20,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Ask every step in both orders and record what came back."""
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        rows.append(_replay_step(url, index, step, timeout=timeout))
        if on_progress and progress_every and (index + 1) % progress_every == 0:
            on_progress(index + 1, len(steps))
    return rows


def fidelity(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How close the live original-order replies are to the recorded ones."""
    diffs: list[float] = []
    same_argmax = 0
    compared = 0
    for row in rows:
        recorded = row.get("recorded")
        if not recorded:
            continue
        compared += 1
        live = row["original"]["probs"]
        for key, value in recorded["probs"].items():
            diffs.append(abs(float(value) - live.get(key, 0.0)))
        if max(sorted(live), key=lambda key: live[key]) == max(
            sorted(recorded["probs"]), key=lambda key: recorded["probs"][key]
        ):
            same_argmax += 1
    return {
        "compared": compared,
        "max_abs_diff": round(max(diffs), 12) if diffs else None,
        "mean_abs_diff": round(statistics.fmean(diffs), 12) if diffs else None,
        "argmax_identical": same_argmax,
        "argmax_identical_share": round(same_argmax / compared, 6) if compared else None,
    }


# --- the latency ------------------------------------------------------------


def _percentiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "p50": None, "p95": None, "min": None, "max": None, "mean": None}
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
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
        "mean": round(statistics.fmean(ordered), 3),
    }


def latency_probe(
    url: str,
    steps: Sequence[dict[str, Any]],
    *,
    n: int = 120,
    warmup: int = 3,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """What the two calls of the both-order protocol cost.

    Three shapes are measured on the same pairs:

    * **one call** — the protocol's first reply alone;
    * **sequential** — the two calls one after the other, the pair's wall
      time measured from before the first to after the second;
    * **concurrent** — the two calls fired at the same time, the pair's wall
      time measured the same way. This is the closest the endpoint gets to
      "one batched call": ``/v1/systemone`` takes **one state per request**
      (the questions share the request's single state), so two prompts cannot
      be one HTTP request. Whether the server then merges the two into one
      batch is the server's business, and the difference between the
      sequential and the concurrent number is the measurement of it.

    The GPU is warmed before the timing: it idles at 315 MHz and a cold
    reading is 2.6x slow.
    """
    chosen = list(steps)[:n] if n else list(steps)
    for step in chosen[:warmup]:
        ask(url, step["state"], timeout)
    ask(url, swapped_state(chosen[0]["state"]), timeout)

    single: list[float] = []
    sequential: list[float] = []
    concurrent: list[float] = []
    single_call_ms: list[float] = []
    concurrent_call_ms: list[float] = []

    for step in chosen:
        original_state = step["state"]
        reversed_state = swapped_state(original_state)

        started = time.perf_counter()
        answer = ask(url, original_state, timeout)
        single_call_ms.append(answer["ms"])
        single.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        ask(url, original_state, timeout)
        ask(url, reversed_state, timeout)
        sequential.append((time.perf_counter() - started) * 1000.0)

        barrier = threading.Barrier(2)
        timings: list[float] = []

        def one(state: str) -> None:
            barrier.wait()
            begin = time.perf_counter()
            ask(url, state, timeout)
            timings.append((time.perf_counter() - begin) * 1000.0)

        started = time.perf_counter()
        threads = [
            threading.Thread(target=one, args=(original_state,)),
            threading.Thread(target=one, args=(reversed_state,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        concurrent.append((time.perf_counter() - started) * 1000.0)
        concurrent_call_ms.extend(timings)

    single_stats = _percentiles(single_call_ms)
    sequential_stats = _percentiles(sequential)
    concurrent_stats = _percentiles(concurrent)
    saving = None
    if sequential_stats["p50"] and concurrent_stats["p50"]:
        saving = round(100.0 * (1.0 - concurrent_stats["p50"] / sequential_stats["p50"]), 2)
    return {
        "pairs": len(chosen),
        "one_call": single_stats,
        "sequential_pair": sequential_stats,
        "concurrent_pair": concurrent_stats,
        "concurrent_saving_pct_at_p50": saving,
        "one_call_inside_the_concurrent_pair": _percentiles(concurrent_call_ms),
    }


# --- the run ----------------------------------------------------------------


def server_props(url: str) -> dict[str, Any]:
    """What the server says about itself: the model, the context, the slots."""
    try:
        with urllib.request.urlopen(url + "/props", timeout=10) as response:
            props = json.loads(response.read().decode("utf-8"))
    except Exception as error:  # pragma: no cover - a probe, not a measurement
        return {"error": str(error)}
    model = props.get("model_path") or props.get("default_generation_settings", {})
    context = props.get("default_generation_settings", {})
    return {
        "model_path": props.get("model_path"),
        "n_ctx": context.get("n_ctx"),
        "n_parallel": context.get("n_parallel"),
        "build": props.get("build_info"),
        "total_slots": props.get("total_slots"),
        "model": model if isinstance(model, str) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="the model being replayed")
    parser.add_argument("--port", type=int, required=True, help="the port it answers on")
    parser.add_argument(
        "--trace",
        type=Path,
        default=None,
        help="the October trace to replay (default: the model's own in TRACES)",
    )
    parser.add_argument("--out", type=Path, default=None, help="where to write the JSON")
    parser.add_argument(
        "--latency-steps",
        type=int,
        default=120,
        help="how many steps the latency probe measures (0 disables it)",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    trace_path = args.trace or (TRACES / f"exp_c_trace_{args.model}.json")
    out_path = args.out or (RESULTS / f"replay-{args.model}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    steps = load_steps(trace_path)
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    box_before = box_state()

    def assemble(
        rows: list[dict[str, Any]],
        latency: dict[str, Any],
        box_at_end: dict[str, Any],
        complete: bool,
    ) -> dict[str, Any]:
        return {
            "experiment": "judge-reversed-replay",
            "model": args.model,
            "url": url,
            "started": started,
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "complete": complete,
            "source_trace": {
                "path": str(trace_path),
                "sha256": _sha256(trace_path),
            },
            "server": server_props(url),
            "design": {
                "steps": len(steps),
                "calls": 2 * len(steps),
                "pair_order": "alternates: even steps ask the original first",
                "swap": "the two named conditions, sentences swapped, nothing else",
                "latency_steps": args.latency_steps,
            },
            "box": {
                "at_start": box_before,
                "after_replay": box_after_replay,
                "at_end": box_at_end,
            },
            "fidelity": fidelity(rows),
            "latency": latency,
            "steps": rows,
        }

    written: list[dict[str, Any]] = []

    def progress(done: int, total: int) -> None:
        # a checkpoint every 40 steps: the box is shared, and a lease can be
        # preempted, so the replies that have been collected are written down
        # as they arrive
        print(f"  {done}/{total} steps", flush=True)
        if done % 40 == 0:
            out_path.write_text(
                json.dumps(
                    assemble(written, {}, box_state(), False), indent=2
                ),
                encoding="utf-8",
            )

    box_after_replay = box_state()

    def run() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            rows.append(_replay_step(url, index, step, timeout=args.timeout))
            written.clear()
            written.extend(rows)
            if (index + 1) % 20 == 0:
                progress(index + 1, len(steps))
        return rows

    rows = run()
    box_after_replay = box_state()

    latency: dict[str, Any] = {}
    if args.latency_steps:
        latency = latency_probe(
            url, steps, n=args.latency_steps, timeout=args.timeout
        )
    box_at_end = box_state()

    result = assemble(rows, latency, box_at_end, True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"fidelity: {result['fidelity']}")
    if latency:
        print(f"latency: {latency}")
    return 0


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
