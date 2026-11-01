"""Measure the re-recorded cell: the recorder fixed, the same 240 steps.

**What this is.** The calibration note's §8 fixed the prompt at replay
time; §9 (the recorder fixed at the source) re-records the trace the fixed
recorder would have written — `recorder.py`'s pair (truth + drawn decoy,
once each) in the canonical order — and measures the same cell on that
trace. This script reads the two re-recordings
(`rerecorded-d1-2B.json`, `rerecorded-d1-3B.json`) and the October traces,
and computes, per model:

1. **accuracy** — overall and by the October presentation groups (the 158
   steps the old recorder presented the truth on, the 82 it presented a
   decoy on — 43 of them naming one condition twice); on the fixed
   prompts the groups describe the task's noise process, not the prompt,
   which no longer knows which group a step is in;
2. **the positional tally** — the answer is the first-named condition, the
   second-named one, or a third (all 240 steps: no fixed prompt names a
   condition twice);
3. **the AUC of the confidence against being right**, with its bootstrap
   interval (the repository's: 2,000 draws, seed 20261031);
4. **the τ gate** — the escalation sweep on the note's grid, by group and
   overall, plus the τ inside the 10/20/30 % budgets;
5. **the routing table** — the two models side by side (§8.3's shape) on
   the re-recorded traces;
6. **what the re-record changed against §8's replay** — the steps whose
   fixed prompt differs from the recorded one, and the steps where §8's
   canonical arm asked a different pair than the recorder's (the
   recording's decoy field held the truth's other neighbour wherever the
   drawn decoy came from below).

**No model call.** This reads the re-recordings and the October traces and
writes ``results/recorder-fix-measurement.json``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]

#: the prompt-fix analysis holds the statistics the note's numbers are in
#: (the sweep, the bootstrap, the budgets, the Wilson interval); one copy.
PROMPT_FIX_SCRIPTS = HERE.parent / "judge-prompt-fix-scripts"
sys.path.insert(0, str(PROMPT_FIX_SCRIPTS))
sys.path.insert(0, str(REPO))

import measure_fixed as mf  # noqa: E402

from core.judge.calibration import area_under_curve  # noqa: E402
from recorder import (  # noqa: E402
    MARKER,
    build_trials,
    condition_name,
    named_sentences,
    old_build_trials,
    prompt_faults,
)

MODELS: tuple[str, ...] = ("d1-2B", "d1-3B")

#: where the October traces live on the Thor.
TRACES = Path("/home/caseydigennaro/lm-wt/liquid-study/results")


def read_rerecorded(path: Path) -> list[dict[str, Any]]:
    """One row per step out of a re-recording."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for row in data["steps"]:
        truth_key = mf.KEYS[int(row["truth"])]
        probs = row["answer"]["probs"]
        argmax = mf.argmax_of(probs)
        sentences = named_sentences(row["state"], MARKER)
        first = mf.letter_of(condition_name(sentences[0], MARKER))
        second = mf.letter_of(condition_name(sentences[1], MARKER))
        rows.append(
            {
                "t": row["t"],
                "trial": row["trial"],
                "truth": truth_key,
                "shown": mf.KEYS[int(row["shown"])],
                "decoy": mf.KEYS[int(row["decoy"])],
                "state": row["state"],
                "identical_prompt": row["identical_prompt"],
                "named_first": first,
                "argmax": argmax,
                "confidence": probs[argmax],
                "right": argmax == truth_key,
                "positional": argmax == first,
                "content": argmax == second,
                "third": argmax not in (first, second),
                "ms": row["answer"]["ms"],
            }
        )
    return rows


def read_october(model: str) -> list[dict[str, Any]]:
    """One row per step out of the October trace — the "before"."""
    data = json.loads((TRACES / f"exp_c_trace_{model}.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for trial_index, trial in enumerate(data["trials"]):
        for row in trial:
            reply = data["trace"][len(rows)]
            probs = {key: float(value) for key, value in reply["probs"].items()}
            argmax = mf.argmax_of(probs)
            truth = mf.KEYS[int(row["truth"])]
            rows.append(
                {
                    "t": row["t"],
                    "trial": trial_index,
                    "truth": truth,
                    "shown": mf.KEYS[int(row["shown"])],
                    "decoy": mf.KEYS[int(row["decoy"])],
                    "argmax": argmax,
                    "confidence": probs[argmax],
                    "right": argmax == truth,
                    "ms": reply.get("wall_ms"),
                }
            )
    return rows


def analyse_fixed(
    rows: Sequence[Mapping[str, Any]],
    october_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Everything the brief asks for, on one model's re-recorded trace.

    ``october_rows`` are the recording's own steps, index-aligned; the
    "doubled" subgroup is an October-prompt property (the recorded prompt
    named one condition twice), so it is read off the recording's fields,
    not the fixed trace's.
    """
    n = len(rows)
    correct = sum(1 for row in rows if row["right"])

    by_group: dict[str, Any] = {}
    for key, members in (
        ("truth_presented", [row for row in rows if row["shown"] == row["truth"]]),
        ("decoy_presented", [row for row in rows if row["shown"] != row["truth"]]),
    ):
        right = sum(1 for row in members if row["right"])
        by_group[key] = {
            "n": len(members),
            "correct": right,
            "accuracy": round(right / len(members), 4) if members else None,
            "wilson": mf.wilson(right, len(members)),
        }
    doubled = [
        row
        for row, oct_row in zip(rows, october_rows)
        if oct_row["shown"] == oct_row["decoy"]
    ]
    right_noop = sum(1 for row in doubled if row["right"])
    by_group["decoy_presented_doubled_october"] = {
        "n": len(doubled),
        "correct": right_noop,
        "accuracy": round(right_noop / len(doubled), 4) if doubled else None,
        "wilson": mf.wilson(right_noop, len(doubled)),
    }

    pairs = [(row["confidence"], row["right"]) for row in rows]
    auc = mf.bootstrap_auc(pairs)
    sweep_rows = mf.sweep(pairs)
    budgets = {f"{budget:.0%}": mf.tau_for_budget(pairs, budget) for budget in mf.BUDGETS}

    sweep_by_group: dict[str, list[dict[str, Any]]] = {}
    for key, members in (
        ("truth_presented", [row for row in rows if row["shown"] == row["truth"]]),
        ("decoy_presented", [row for row in rows if row["shown"] != row["truth"]]),
    ):
        group_pairs = [(row["confidence"], row["right"]) for row in members]
        group_wrong = sum(1 for _, right in group_pairs if not right)
        group_right = len(members) - group_wrong
        sweep_by_group[key] = [
            {
                "tau": row["tau"],
                "escalated": sum(1 for c, _ in group_pairs if c < row["tau"]),
                "catch": round(
                    sum(1 for c, r in group_pairs if c < row["tau"] and not r) / group_wrong, 4
                )
                if group_wrong
                else 0.0,
                "tax": round(
                    sum(1 for c, r in group_pairs if c < row["tau"] and r) / group_right, 4
                )
                if group_right
                else 0.0,
            }
            for row in sweep_rows
        ]

    tally = {
        "positional": sum(1 for row in rows if row["positional"]),
        "content": sum(1 for row in rows if row["content"]),
        "third": sum(1 for row in rows if row["third"]),
        "n": n,
    }
    latencies = sorted(row["ms"] for row in rows if row["ms"] is not None)

    def at(fraction: float) -> float:
        position = fraction * (len(latencies) - 1)
        low = int(position)
        high = min(low + 1, len(latencies) - 1)
        weight = position - low
        return latencies[low] * (1.0 - weight) + latencies[high] * weight

    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else None,
        "wilson": mf.wilson(correct, n),
        "by_group": by_group,
        "auc": auc,
        "sweep": sweep_rows,
        "sweep_by_group": sweep_by_group,
        "budgets": budgets,
        "positional_tally": tally,
        "latency_ms": {
            "n": len(latencies),
            "p50": round(at(0.50), 3),
            "p95": round(at(0.95), 3),
            "mean": round(statistics.fmean(latencies), 3),
        }
        if latencies
        else None,
    }


def analyse_october(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The before, from the recording's own vectors (the same walk as §8's)."""
    n = len(rows)
    correct = sum(1 for row in rows if row["right"])
    by_group: dict[str, Any] = {}
    for key, members in (
        ("truth_presented", [row for row in rows if row["shown"] == row["truth"]]),
        ("decoy_presented", [row for row in rows if row["shown"] != row["truth"]]),
    ):
        right = sum(1 for row in members if row["right"])
        by_group[key] = {
            "n": len(members),
            "correct": right,
            "accuracy": round(right / len(members), 4) if members else None,
        }
    pairs = [(row["confidence"], row["right"]) for row in rows]
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else None,
        "by_group": by_group,
        "auc": mf.bootstrap_auc(pairs),
    }


def routing_table(
    rows_by_model: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    """The two models side by side on the re-recorded traces (§8.3's shape)."""

    def gate_at(pairs: Sequence[tuple[float, bool]], tau: float) -> dict[str, Any]:
        wrong = sum(1 for _, right in pairs if not right)
        right = sum(1 for _, right in pairs if right)
        escalated = [(c, r) for c, r in pairs if c < tau]
        return {
            "escalated": len(escalated),
            "catch": round(sum(1 for _, r in escalated if not r) / wrong, 4) if wrong else 0.0,
            "tax": round(sum(1 for _, r in escalated if r) / right, 4) if right else 0.0,
        }

    by_model: dict[str, Any] = {}
    for name, rows in rows_by_model.items():
        pairs = [(row["confidence"], row["right"]) for row in rows]
        decoy = [row for row in rows if row["shown"] != row["truth"]]
        point = area_under_curve(pairs)
        latencies = sorted(row["ms"] for row in rows if row["ms"] is not None)
        by_model[name] = {
            "accuracy": round(sum(1 for row in rows if row["right"]) / len(rows), 4),
            "decoy_presented_accuracy": round(
                sum(1 for row in decoy if row["right"]) / len(decoy), 4
            )
            if decoy
            else None,
            "auc": round(point, 4) if point is not None else None,
            "gate_at_0_8": gate_at(pairs, 0.8),
            "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        }
    (name_a, rows_a), (name_b, rows_b) = list(rows_by_model.items())
    both = sum(1 for a, b in zip(rows_a, rows_b) if a["right"] and b["right"])
    a_only = sum(1 for a, b in zip(rows_a, rows_b) if a["right"] and not b["right"])
    b_only = sum(1 for a, b in zip(rows_a, rows_b) if b["right"] and not a["right"])
    by_model["steps_where_one_is_right"] = {
        "both": both,
        f"the {name_a} only": a_only,
        f"the {name_b} only": b_only,
        "neither": len(rows_a) - both - a_only - b_only,
    }
    return by_model


def pair_changes(october_steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the fixed recorder asks that the recording did not.

    The fixed builder is run on the October seed, so the comparison is
    step-for-step against the recording's own states: how many prompts
    differ, of those how many differ by the pair (both noise steps) and
    how many by the order alone (clean steps whose canonical order is the
    old order reversed), and — computed independently, from the
    recording's decoy field — how many steps §8's canonical arm asked a
    different pair than the recorder's. On a noise step the recording's
    decoy field holds the truth's other neighbour wherever the drawn decoy
    came from below, so §8's arm named (truth, truth+1) where the recorder
    names (truth, truth−1).
    """
    fixed_steps = [row for trial in build_trials() for row in trial]
    old_steps = [row for trial in old_build_trials() for row in trial]
    differ = 0
    order_only = 0
    pair_changed = 0
    arm_pair_differs = 0
    for fixed, old, recorded in zip(fixed_steps, old_steps, october_steps):
        if fixed["state"] != recorded["state"]:
            differ += 1
            if fixed["decoy"] != old["decoy"] or fixed["truth"] != old["truth"]:
                pair_changed += 1
            else:
                order_only += 1
        if int(recorded["decoy"]) != fixed["decoy"]:
            arm_pair_differs += 1
    return {
        "prompts_that_differ": differ,
        "of_those_order_only": order_only,
        "of_those_pair_changed": pair_changed,
        "the_8_arm_pair_differs_from_the_recorders": arm_pair_differs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument(
        "--out", type=Path, default=RESULTS / "recorder-fix-measurement.json"
    )
    args = parser.parse_args()

    fixed_rows: dict[str, list[dict[str, Any]]] = {}
    before: dict[str, Any] = {}
    analysis: dict[str, Any] = {}
    for model in args.models:
        path = RESULTS / f"rerecorded-{model}.json"
        rows = read_rerecorded(path)
        fixed_rows[model] = rows
        october_rows = read_october(model)
        october_steps = [
            row
            for trial in json.loads(
                (TRACES / f"exp_c_trace_{model}.json").read_text(encoding="utf-8")
            )["trials"]
            for row in trial
        ]
        before[model] = analyse_october(october_rows)
        analysis[model] = analyse_fixed(rows, october_rows)
        analysis[model]["faulty_prompts"] = sum(
            1
            for trial in build_trials()
            for step in trial
            if prompt_faults(step["state"], step["truth"])
        )
        analysis[model]["pair_changes_against_the_recording"] = pair_changes(october_steps)

    result = {
        "experiment": "judge-recorder-fix",
        "what": "the cell measured on the fixed recorder's own trace",
        "models": args.models,
        "before": before,
        "fixed": analysis,
        "routing": routing_table(fixed_rows) if len(fixed_rows) == 2 else None,
        "semantics": {
            "groups": "the October presentation (shown==truth / shown!=truth); the fixed prompt does not know the group",
            "confidence": "top probability — the canonical definition",
            "gate": "escalates when the confidence is below tau (core.judge.calibration's rule)",
            "auc": "bootstrap 2000 draws, seed 20261031, ties count a half",
        },
    }
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    for model in args.models:
        f = analysis[model]
        b = before[model]
        print(
            f"{model}: accuracy {b['accuracy']} -> {f['accuracy']}"
            f" | AUC {b['auc']['auc'] if b['auc'] else None}"
            f" -> {f['auc']['auc'] if f['auc'] else None}"
            f" [{f['auc']['low']}, {f['auc']['high']}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
