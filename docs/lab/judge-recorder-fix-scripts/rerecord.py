"""The re-recording: the 240 steps as the fixed recorder builds them.

**What this is.** §8 of the calibration note fixed the prompt at replay
time (three arms over the recorded steps); this script records the trace
the **fixed recorder** would have written — `recorder.py`'s builder: the
truth and the drawn decoy, once each, in the canonical order, on the
October seed and stream. One prompt per step, one call a step, 240 calls a
model, plus the determinism control (the first ``--repeat-steps`` steps
asked again).

**The fidelity check the run carries on itself.** On the 158 steps the old
recorder presented the truth on, the fixed pair is the old pair; where the
canonical order also keeps the old order, the fixed prompt is
byte-identical to the recorded one, and the live reply must equal the
October recording's vector — the instrument check §7 and §8 ran. The
re-recording compares every byte-identical prompt's reply with the
recording and reports the diffs; the noise steps' prompts are new text, so
they are not comparable and are not compared.

**Usage** (on the Thor, with a d1 model served):

    python3 rerecord.py --model d1-2B --port 8094 --out results/rerecorded-d1-2B.json
    python3 rerecord.py --model d1-3B --port 8320 --out results/rerecorded-d1-3B.json

Writes one JSON: the metadata (server, box, fidelity, determinism), the
240 steps with their answers, and the trace in the October shape
(``{"trace": …, "trials": …}``) so the re-recorded trace drops into the
same readers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]

#: the prompt-fix scripts sit beside this one and hold the wire machinery
#: (``ask``, the box probe, the server probe). One copy, imported — not
#: re-typed here.
PROMPT_FIX_SCRIPTS = HERE.parent / "judge-prompt-fix-scripts"
sys.path.insert(0, str(PROMPT_FIX_SCRIPTS))
sys.path.insert(0, str(REPO))

import replay_fixed as pf  # noqa: E402

from recorder import (  # noqa: E402
    MARKER,
    N_STEPS,
    QUESTIONS,
    build_trials,
    condition_name,
    named_sentences,
    prompt_faults,
)

#: where the October traces live on the Thor.
TRACES = Path("/home/caseydigennaro/lm-wt/liquid-study/results")

if pf.QUESTIONS["criteria"] != QUESTIONS["criteria"]:
    raise SystemExit("the prompt-fix script's question is not the recorder's")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def fidelity(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The live replies on the byte-identical prompts, against the recording."""
    diffs: list[float] = []
    same_argmax = 0
    identical = 0
    compared = 0
    for row in rows:
        if not row["identical_prompt"]:
            continue
        compared += 1
        live = row["answer"]["probs"]
        recorded = row["october"]["probs"]
        for key, value in recorded.items():
            diffs.append(abs(float(value) - live.get(key, 0.0)))
        live_argmax = max(sorted(live), key=lambda key: live[key])
        recorded_argmax = max(sorted(recorded), key=lambda key: recorded[key])
        if live_argmax == recorded_argmax:
            same_argmax += 1
        if live == recorded:
            identical += 1
    return {
        "compared": compared,
        "max_abs_diff": round(max(diffs), 12) if diffs else None,
        "mean_abs_diff": round(statistics.fmean(diffs), 12) if diffs else None,
        "argmax_identical": same_argmax,
        "vector_identical": identical,
    }


def determinism(
    url: str, rows: Sequence[dict[str, Any]], n: int, *, timeout: float
) -> dict[str, Any]:
    """Ask the first n steps again; every reply must be the same vector."""
    checked = 0
    identical = 0
    for row in rows[:n]:
        again = pf.ask(url, row["state"], timeout=timeout)
        checked += 1
        if again["probs"] == row["answer"]["probs"]:
            identical += 1
    return {"steps": min(n, len(rows)), "calls": checked, "vector_identical": identical}


def latency_of(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(row["answer"]["ms"] for row in rows)
    if not values:
        return {"n": 0, "p50": None, "p95": None, "mean": None}

    def at(fraction: float) -> float:
        position = fraction * (len(values) - 1)
        low = int(position)
        high = min(low + 1, len(values) - 1)
        weight = position - low
        return values[low] * (1.0 - weight) + values[high] * weight

    return {
        "n": len(values),
        "p50": round(at(0.50), 3),
        "p95": round(at(0.95), 3),
        "mean": round(statistics.fmean(values), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--repeat-steps", type=int, default=12,
        help="how many leading steps the determinism control re-asks",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    out_path = args.out or (RESULTS / f"rerecorded-{args.model}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trials = build_trials()
    steps = [row for trial in trials for row in trial]
    october_path = TRACES / f"exp_c_trace_{args.model}.json"
    october = json.loads(october_path.read_text(encoding="utf-8"))
    october_rows = october["trace"]
    october_steps = [row for trial in october["trials"] for row in trial]

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    box_before = pf.box_state()

    rows: list[dict[str, Any]] = []
    det: dict[str, Any] = {}
    box_after: dict[str, Any] = {}
    box_end: dict[str, Any] = {}

    def assemble(complete: bool) -> dict[str, Any]:
        trace = [
            {
                "t": row["t"],
                "trial": row["trial"],
                "truth": row["truth"],
                "shown": row["shown"],
                "probs": row["answer"]["probs"],
                "confidence": row["answer"]["confidence"],
                "wall_ms": row["answer"]["ms"],
            }
            for row in rows
        ]
        return {
            "experiment": "judge-recorder-fix",
            "model": args.model,
            "url": url,
            "started": started,
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "complete": complete,
            "recorder": "docs/lab/judge-recorder-fix-scripts/recorder.py (the fixed builder)",
            "october_trace": {"path": str(october_path), "sha256": _sha256(october_path)},
            "server": pf.server_props(url),
            "design": {
                "steps": len(rows),
                "seed": 20261031,
                "n_trials": len(trials),
                "n_steps_per_trial": N_STEPS,
                "noise_prob": 0.35,
                "order_mode": "canonical",
            },
            "box": {"at_start": box_before, "after_replay": box_after, "at_end": box_end},
            "faulty_prompts": sum(1 for row in rows if row["faults"]),
            "fidelity": fidelity(rows) if len(rows) == len(steps) else None,
            "determinism": det,
            "latency": latency_of(rows) if complete else None,
            "steps": rows,
            "trace": trace,
            "trials": trials,
        }

    for index, step in enumerate(steps):
        oct_state = october_steps[index]["state"]
        answer = pf.ask(url, step["state"], timeout=args.timeout)
        sentences = named_sentences(step["state"], MARKER)
        rows.append(
            {
                "t": step["t"],
                "trial": index // N_STEPS,
                "truth": step["truth"],
                "shown": step["shown"],
                "decoy": step["decoy"],
                "state": step["state"],
                "named_first": condition_name(sentences[0], MARKER),
                "identical_prompt": step["state"] == oct_state,
                "answer": answer,
                "october": {
                    "state": oct_state,
                    "probs": october_rows[index]["probs"],
                    "confidence": october_rows[index].get("confidence"),
                },
                "faults": prompt_faults(step["state"], step["truth"]),
            }
        )
        if (index + 1) % 20 == 0:
            print(f"  {index + 1}/{len(steps)} steps", flush=True)
        if (index + 1) % 60 == 0:
            out_path.write_text(json.dumps(assemble(False), indent=2), encoding="utf-8")

    box_after = pf.box_state()
    det = determinism(url, rows, args.repeat_steps, timeout=args.timeout)
    box_end = pf.box_state()

    result = assemble(True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"fidelity: {result['fidelity']}")
    print(f"determinism: {det}")
    print(f"latency: {result['latency']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
