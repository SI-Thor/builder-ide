"""Measure the prompt fix: what the neutral order does to the cell.

**What this is.** The calibration note's §7 settled the mechanism (the d1-2B
answers the first-named condition; the state's order was the leak) and left
the fix upstream, in the prompt. ``replay_fixed.py`` recorded the same 240
steps under three arms — ``recorded`` (the recording's own text, the
control), ``canonical`` and ``balanced`` (the true condition and the decoy,
named in ``core.judge.ordering``'s two neutral orders). This script reads
those recordings and computes, per model and per arm:

1. **accuracy** — overall, and by the recorded grouping (the 158 steps whose
   prompt named the truth first, the 82 whose prompt named a decoy first,
   the 43 of those named twice);
2. **the positional share** — how often the answer is the first-named
   condition, the second-named one, or a third (the §7.1 tally, per arm);
3. **the AUC of the confidence against being right**, with its bootstrap
   interval — the number that was 0.2815 (2B) and 0.2944 (3B) before;
4. **the τ gate's catch and tax**, overall and by group, at the note's τ
   grid and inside the 10/20/30 % escalation budgets;
5. **the brief's pass rows** — the AUC above the coin-flip line, the
   decoy-first accuracy risen, the truth-first accuracy not fallen;
6. **the routing table** — the two models side by side on the fixed arms
   (accuracy, latency, and what each is wrong that the other is right),
   for the recommendation if the 2B stays positional.

**The judgment.** One judgment per step per arm: the arm's own answer,
scored against the step's ground truth (always the true condition). The
"before" numbers are computed from the recording embedded in each step, so
before and after share the instrument, the session and the box.

**No model call.** This reads the fresh recordings and writes
``results/prompt-fix-measurement.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]

sys.path.insert(0, str(REPO))

from core.judge.calibration import area_under_curve  # noqa: E402
from core.judge.ordering import condition_name, named_sentences  # noqa: E402

#: every state sentence starts with this — the recorder's marker.
MARKER = "The sea is "

#: the option letters, in the order the criteria are written.
KEYS = "ABCDE"

#: the condition names in criteria order — the letter a name answers under.
NAMES = (
    "flat calm",
    "slight chop",
    "rough swell",
    "confused chop",
    "breaking water",
)

#: the τ grid, the note's.
TAUS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)

#: the escalation budgets the brief asks for.
BUDGETS: tuple[float, ...] = (0.10, 0.20, 0.30)

#: the bootstrap, the repository's: 2000 draws, seed 20261031.
RESAMPLES = 2000
SEED = 20261031

#: the arms, in the order they are reported.
ARMS: tuple[str, ...] = ("recorded", "canonical", "balanced")

#: the groups, by the recorded prompt's order.
GROUPS: tuple[str, ...] = ("truth_first", "decoy_first_noop", "decoy_first_two_cond")


# --- the small helpers --------------------------------------------------------


def argmax_of(probs: Mapping[str, float]) -> str:
    """The argmax, ties by name — the repository's rule."""
    return max(sorted(probs), key=lambda key: probs[key])


def letter_of(name: str) -> str:
    """The criteria letter a condition name answers under."""
    return KEYS[NAMES.index(name)]


def sweep(
    pairs: Sequence[tuple[float, bool]], taus: Sequence[float] = TAUS
) -> list[dict[str, Any]]:
    """The escalation sweep on explicit (confidence, outcome) pairs.

    The gate escalates when the confidence is **below** τ: the same rule and
    meaning as ``core.judge.calibration.escalation_sweep``, written on
    explicit pairs so the by-group rows come from the same walk.
    """
    wrong = [pair for pair in pairs if not pair[1]]
    right = [pair for pair in pairs if pair[1]]
    rows: list[dict[str, Any]] = []
    for tau in taus:
        escalated = [pair for pair in pairs if pair[0] < tau]
        caught = [pair for pair in escalated if not pair[1]]
        taxed = [pair for pair in escalated if pair[1]]
        rows.append(
            {
                "tau": tau,
                "escalated": len(escalated),
                "act_rate": round(len(escalated) / len(pairs), 4) if pairs else None,
                "catch": round(len(caught) / len(wrong), 4) if wrong else 0.0,
                "tax": round(len(taxed) / len(right), 4) if right else 0.0,
                "caught_all": bool(wrong) and len(caught) == len(wrong),
            }
        )
    return rows


def bootstrap_auc(
    pairs: Sequence[tuple[float, bool]],
    *,
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> dict[str, Any] | None:
    """The AUC's bootstrap interval, the repository's method."""
    if not pairs:
        return None
    point = area_under_curve(pairs)
    if point is None:
        return None
    rng = random.Random(seed)
    count = len(pairs)
    draws: list[float] = []
    for _ in range(resamples):
        draw = [pairs[rng.randrange(count)] for _ in range(count)]
        value = area_under_curve(draw)
        if value is not None:
            draws.append(value)
    if not draws:
        return None
    ordered = sorted(draws)

    def at(percent: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = percent / 100.0 * (len(ordered) - 1)
        below = math.floor(position)
        above = math.ceil(position)
        if below == above:
            return ordered[int(position)]
        weight = position - below
        return ordered[below] * (1.0 - weight) + ordered[above] * weight

    return {
        "auc": round(point, 4),
        "low": round(at(2.5), 4),
        "high": round(at(97.5), 4),
        "resamples": len(draws),
    }


def tau_for_budget(
    pairs: Sequence[tuple[float, bool]], budget: float, *, step: float = 0.005
) -> dict[str, Any]:
    """The τ whose escalation share is the largest that stays under the budget."""
    if not pairs:
        return {}
    grid = [round(index * step, 4) for index in range(1, int(1.0 / step) + 1)]
    under: tuple[float, int] | None = None
    over: tuple[float, int] | None = None
    for tau in grid:
        count = sum(1 for confidence, _ in pairs if confidence < tau)
        share = count / len(pairs)
        if share <= budget:
            under = (tau, count)
        elif over is None:
            over = (tau, count)
    if under is None:
        return {"tau": None, "note": "the lowest τ on the grid already exceeds the budget"}
    tau, count = under
    wrong = [pair for pair in pairs if not pair[1]]
    right = [pair for pair in pairs if pair[1]]
    escalated = [pair for pair in pairs if pair[0] < tau]
    caught = [pair for pair in escalated if not pair[1]]
    taxed = [pair for pair in escalated if pair[1]]
    row = {
        "tau": tau,
        "escalated": count,
        "share": round(count / len(pairs), 4),
        "catch": round(len(caught) / len(wrong), 4) if wrong else 0.0,
        "tax": round(len(taxed) / len(right), 4) if right else 0.0,
    }
    if over is not None:
        row["next_tau"] = over[0]
        row["next_tau_share"] = round(over[1] / len(pairs), 4)
    return row


def wilson(correct: int, n: int) -> dict[str, float] | None:
    """The Wilson score interval of a share — the accuracy's error bar."""
    if n == 0:
        return None
    share = correct / n
    z = 1.959963984540054
    denominator = 1.0 + z * z / n
    centre = (share + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(share * (1.0 - share) / n + z * z / (4.0 * n * n)) / denominator
    return {"low": round(centre - half, 4), "high": round(centre + half, 4)}


# --- the per-step table -------------------------------------------------------


def read_rows(path: Path) -> list[dict[str, Any]]:
    """One row per step, with the grouping and every arm's answer."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for row in data["steps"]:
        truth_key = KEYS[int(row["truth"])]
        shown_key = KEYS[int(row["shown"])]
        decoy_key = KEYS[int(row["decoy"])]
        if shown_key == truth_key:
            group = "truth_first"
        elif shown_key == decoy_key:
            group = "decoy_first_noop"
        else:
            group = "decoy_first_two_cond"
        arms: dict[str, Any] = {}
        for arm, answer in row["arms"].items():
            probs = answer["probs"]
            argmax = argmax_of(probs)
            sentences = named_sentences(answer["state"], MARKER)
            first = letter_of(condition_name(sentences[0], MARKER))
            second = (
                letter_of(condition_name(sentences[1], MARKER))
                if len(sentences) > 1
                else None
            )
            arms[arm] = {
                "argmax": argmax,
                "confidence": probs[argmax],
                "right": argmax == truth_key,
                "first_named": first,
                "second_named": second,
                "positional": argmax == first,
                "content": second is not None and argmax == second,
                "third": argmax != first and (second is None or argmax != second),
                "ms": answer["ms"],
            }
        recorded = row.get("recorded") or {}
        recorded_probs = recorded.get("probs") or {}
        recorded_argmax = argmax_of(recorded_probs) if recorded_probs else None
        arms["october"] = {
            "argmax": recorded_argmax,
            "confidence": (
                recorded_probs[recorded_argmax] if recorded_probs else None
            ),
            "right": bool(recorded_probs) and recorded_argmax == truth_key,
            "first_named": shown_key,
            "second_named": decoy_key if decoy_key != shown_key else None,
            "positional": recorded_argmax == shown_key if recorded_argmax else False,
            "content": (
                recorded_argmax == decoy_key
                if recorded_argmax and decoy_key != shown_key
                else False
            ),
            "third": (
                recorded_argmax not in (shown_key, decoy_key)
                if recorded_argmax
                else False
            ),
            "ms": recorded.get("wall_ms"),
        }
        rows.append(
            {
                "t": row["t"],
                "trial": row["trial"],
                "truth": truth_key,
                "shown": shown_key,
                "decoy": decoy_key,
                "group": group,
                "identical_prompt": row["identical_prompt"],
                "arms": arms,
            }
        )
    return rows


# --- the per-model, per-arm analysis ------------------------------------------


def analyse_arm(rows: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    """Everything the brief asks for, for one arm of one model."""
    subset = [row["arms"][arm] for row in rows]
    n = len(subset)
    correct = sum(1 for answer in subset if answer["right"])
    by_group: dict[str, Any] = {}
    for group in GROUPS:
        members = [
            row["arms"][arm] for row in rows if row["group"] == group
        ]
        right = sum(1 for answer in members if answer["right"])
        by_group[group] = {
            "n": len(members),
            "correct": right,
            "accuracy": round(right / len(members), 4) if members else None,
            "wilson": wilson(right, len(members)),
        }
    combined = [row["arms"][arm] for row in rows if row["group"] != "truth_first"]
    right_combined = sum(1 for answer in combined if answer["right"])
    by_group["decoy_first"] = {
        "n": len(combined),
        "correct": right_combined,
        "accuracy": round(right_combined / len(combined), 4) if combined else None,
        "wilson": wilson(right_combined, len(combined)),
    }

    pairs = [(answer["confidence"], answer["right"]) for answer in subset]
    auc = bootstrap_auc(pairs)

    sweep_rows = sweep(pairs)
    by_group_sweep: dict[str, list[dict[str, Any]]] = {}
    for group in ("truth_first", "decoy_first"):
        members = [
            (row["arms"][arm]["confidence"], row["arms"][arm]["right"])
            for row in rows
            if (row["group"] == "truth_first") == (group == "truth_first")
        ]
        group_wrong = sum(1 for _, right in members if not right)
        group_right = sum(1 for _, right in members if right)
        by_group_sweep[group] = [
            {
                "tau": row["tau"],
                "escalated": sum(
                    1 for confidence, _ in members if confidence < row["tau"]
                ),
                "catch": round(
                    sum(
                        1
                        for confidence, right in members
                        if confidence < row["tau"] and not right
                    )
                    / group_wrong,
                    4,
                )
                if group_wrong
                else 0.0,
                "tax": round(
                    sum(
                        1
                        for confidence, right in members
                        if confidence < row["tau"] and right
                    )
                    / group_right,
                    4,
                )
                if group_right
                else 0.0,
            }
            for row in sweep_rows
        ]

    budgets = {f"{budget:.0%}": tau_for_budget(pairs, budget) for budget in BUDGETS}

    # the positional tally counts the steps whose prompt names two different
    # conditions: the recorded arm's no-op steps (the prompt named one
    # condition twice) are the determinism control, not choices (§7.1)
    if arm in ("recorded", "october"):
        tally_rows = [row for row in rows if not row["identical_prompt"]]
    else:
        tally_rows = rows
    two_cond = [row["arms"][arm] for row in tally_rows]
    tally = {
        "positional": sum(1 for answer in two_cond if answer["positional"]),
        "content": sum(1 for answer in two_cond if answer["content"]),
        "third": sum(1 for answer in two_cond if answer["third"]),
        "n": len(two_cond),
    }

    latencies = [answer["ms"] for answer in subset if answer["ms"] is not None]
    latency = (
        {
            "n": len(latencies),
            "p50": round(sorted(latencies)[len(latencies) // 2], 3),
            "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
            "mean": round(statistics.fmean(latencies), 3),
        }
        if latencies
        else None
    )

    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else None,
        "wilson": wilson(correct, n),
        "by_group": by_group,
        "auc": auc,
        "sweep": sweep_rows,
        "sweep_by_group": by_group_sweep,
        "budgets": budgets,
        "positional_tally": tally,
        "latency_ms": latency,
    }


def pass_rows(
    recorded: Mapping[str, Any], fixed: Mapping[str, Any]
) -> dict[str, Any]:
    """The brief's pass rows, one fixed arm against the recorded control."""
    auc = fixed["auc"]["auc"] if fixed.get("auc") else None
    auc_interval = (fixed["auc"]["low"], fixed["auc"]["high"]) if fixed.get("auc") else None
    before_decoy = recorded["by_group"]["decoy_first"]["accuracy"]
    after_decoy = fixed["by_group"]["decoy_first"]["accuracy"]
    before_truth = recorded["by_group"]["truth_first"]["accuracy"]
    after_truth = fixed["by_group"]["truth_first"]["accuracy"]
    return {
        "auc_above_half": {
            "auc": auc,
            "interval": auc_interval,
            "pass": bool(auc is not None and auc > 0.5),
        },
        "decoy_first_accuracy_rises": {
            "before": before_decoy,
            "after": after_decoy,
            "delta": round(after_decoy - before_decoy, 4)
            if None not in (before_decoy, after_decoy)
            else None,
            "pass": bool(
                before_decoy is not None
                and after_decoy is not None
                and after_decoy > before_decoy
            ),
        },
        "truth_first_accuracy_does_not_fall": {
            "before": before_truth,
            "after": after_truth,
            "delta": round(after_truth - before_truth, 4)
            if None not in (before_truth, after_truth)
            else None,
            "pass": bool(
                before_truth is not None
                and after_truth is not None
                and after_truth >= before_truth
            ),
        },
    }


def _p50(values: Sequence[float]) -> float | None:
    """The median of the per-call latencies, the simple order-statistic way."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 3)
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 3)


def routing_table(
    rows_2b: Sequence[Mapping[str, Any]], rows_3b: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The two models side by side on the fixed arms — the routing input."""
    table: dict[str, Any] = {}
    for arm in ("canonical", "balanced"):

        def gate_at(pairs: Sequence[tuple[float, bool]], tau: float) -> dict[str, Any]:
            wrong = sum(1 for _, right in pairs if not right)
            right = sum(1 for _, right in pairs if right)
            escalated = [(c, r) for c, r in pairs if c < tau]
            return {
                "escalated": len(escalated),
                "catch": round(
                    sum(1 for _, r in escalated if not r) / wrong, 4
                )
                if wrong
                else 0.0,
                "tax": round(sum(1 for _, r in escalated if r) / right, 4)
                if right
                else 0.0,
            }

        by_model: dict[str, Any] = {}
        for name, rows in (("d1-2B", rows_2b), ("d1-3B", rows_3b)):
            subset = [row["arms"][arm] for row in rows]
            correct = sum(1 for answer in subset if answer["right"])
            decoy = [
                row["arms"][arm] for row in rows if row["group"] != "truth_first"
            ]
            decoy_right = sum(1 for answer in decoy if answer["right"])
            pairs = [(answer["confidence"], answer["right"]) for answer in subset]
            point = area_under_curve(pairs)
            by_model[name] = {
                "accuracy": round(correct / len(subset), 4),
                "decoy_first_accuracy": round(decoy_right / len(decoy), 4),
                "auc": round(point, 4) if point is not None else None,
                "gate_at_0_8": gate_at(pairs, 0.8),
                "latency_p50_ms": _p50([answer["ms"] for answer in subset]),
            }
        agree_right = sum(
            1
            for row_a, row_b in zip(rows_2b, rows_3b)
            if row_a["arms"][arm]["right"] and row_b["arms"][arm]["right"]
        )
        two_b_right_three_wrong = sum(
            1
            for row_a, row_b in zip(rows_2b, rows_3b)
            if row_a["arms"][arm]["right"] and not row_b["arms"][arm]["right"]
        )
        three_b_right_two_wrong = sum(
            1
            for row_a, row_b in zip(rows_2b, rows_3b)
            if row_b["arms"][arm]["right"] and not row_a["arms"][arm]["right"]
        )
        by_model["steps_where_one_is_right"] = {
            "both": agree_right,
            "the_2B_only": two_b_right_three_wrong,
            "the_3B_only": three_b_right_two_wrong,
            "neither": len(rows_2b)
            - agree_right
            - two_b_right_three_wrong
            - three_b_right_two_wrong,
        }
        table[arm] = by_model
    return table


# --- the run ------------------------------------------------------------------


def analyse_model(path: Path) -> dict[str, Any]:
    """Everything for one model: the three arms, the pass rows."""
    rows = read_rows(path)
    arms = {arm: analyse_arm(rows, arm) for arm in ARMS}
    passes = {
        arm: pass_rows(arms["recorded"], arms[arm])
        for arm in ("canonical", "balanced")
    }
    return {"arms": arms, "pass": passes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fresh",
        type=Path,
        nargs="+",
        default=None,
        help="the fresh recordings (default: both models' in RESULTS)",
    )
    parser.add_argument(
        "--out", type=Path, default=RESULTS / "prompt-fix-measurement.json"
    )
    args = parser.parse_args()

    fresh = args.fresh or sorted(RESULTS.glob("fresh-d1-*.json"))
    if not fresh:
        raise SystemExit("no fresh recordings found; run replay_fixed.py first")

    out: dict[str, Any] = {
        "experiment": "judge-prompt-fix",
        "measured": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "arms": list(ARMS),
        "models": {},
        "routing": None,
    }
    loaded: dict[str, list[dict[str, Any]]] = {}
    for path in fresh:
        data = json.loads(path.read_text(encoding="utf-8"))
        model = data["model"]
        loaded[model] = read_rows(path)
        result = analyse_model(path)
        result["box"] = data.get("box")
        result["server"] = data.get("server")
        result["design"] = data.get("design")
        result["fidelity"] = data.get("fidelity")
        result["determinism"] = data.get("determinism")
        result["latency_per_arm"] = data.get("latency_per_arm")
        out["models"][model] = result

    if "d1-2B" in loaded and "d1-3B" in loaded:
        out["routing"] = routing_table(loaded["d1-2B"], loaded["d1-3B"])

    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    for model, result in out["models"].items():
        for arm in ("canonical", "balanced"):
            row = result["pass"][arm]
            print(
                f"{model} {arm}: "
                f"auc={row['auc_above_half']['auc']} "
                f"decoy {row['decoy_first_accuracy_rises']['before']}"
                f"→{row['decoy_first_accuracy_rises']['after']} "
                f"truth {row['truth_first_accuracy_does_not_fall']['before']}"
                f"→{row['truth_first_accuracy_does_not_fall']['after']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
