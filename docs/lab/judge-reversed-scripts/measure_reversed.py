"""Measure the reversed replay: what the swap settles.

**What this is.** The calibration note computed the both-order protocol under
one stated assumption (that a reversed prompt makes the model answer the other
named condition), because the October recording holds only the original order.
`replay_reversed.py` holds both orders. This script reads those two files and
computes the five numbers the brief asks for:

1. **the positional share** — how often the reversed answer names the *other*
   condition (the model followed the position) against the *same* condition
   (the model followed the content), against a third option;
2. **the real disagreement set** — the steps whose two orders really disagree,
   and the catch and the tax of escalating on a disagreement;
3. **the average of the confidences against the average of the vectors** —
   the AUC and the escalation sweep of each, and whether either un-inverts the
   AUC the note published;
4. **sane budgets** — the catch rate at 10 %, 20 % and 30 % escalation, for
   the τ gate against the both-order protocol;
5. **the latency** — one call, two calls in sequence, two calls at the same
   time, with the box state beside each.

**The judgment.** Every protocol here gates *one* judgment: the original
order's answer. "Right" means that answer named the true condition; "wrong"
means it did not. The reversed answer is not a second judgment to be scored —
it is the second reading the gate uses. That keeps the catch and the tax
comparable with the note's, which scored the recording's one answer per step.

**The τ semantics** are the repository's: the gate escalates when the
confidence is **below** τ (``core.judge.calibration.escalation_sweep``), the
canonical confidence is the top probability (``top_probability``), and the
AUC counts a tie as a half. The sweeps here are written on explicit
(confidence, outcome) pairs so that the two averaged confidences — which are
not the top probability of any single vector — can be swept the same way; the
test suite pins them against the repository's own sweep.

**No model call.** This reads the replay's JSON and the October trace and
writes ``results/reversed-measurement.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]

sys.path.insert(0, str(REPO))

from core.judge.calibration import (  # noqa: E402
    CANONICAL_CONFIDENCE,
    CalibrationSample,
    area_under_curve,
    escalation_sweep,
)

#: the October traces, on the Thor.
TRACES = Path("/home/caseydigennaro/lm-wt/liquid-study/results")

#: the option letters, in the order the criteria are written.
KEYS = "ABCDE"

#: the τ grid, the note's.
TAUS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)

#: the escalation budgets the brief asks for.
BUDGETS: tuple[float, ...] = (0.10, 0.20, 0.30)

#: the bootstrap, the repository's: 2000 draws, seed 20261031, the 2.5th and
#: 97.5th percentiles.
RESAMPLES = 2000
SEED = 20261031


# --- the small helpers --------------------------------------------------------


def argmax_of(probs: Mapping[str, float]) -> str:
    """The argmax, ties by name — the repository's rule."""
    return max(sorted(probs), key=lambda key: probs[key])


def mean_vector(
    left: Mapping[str, float], right: Mapping[str, float]
) -> dict[str, float]:
    """The elementwise average of two distributions."""
    return {key: (float(left[key]) + float(right[key])) / 2.0 for key in left}


def sweep(
    pairs: Sequence[tuple[float, bool]], taus: Sequence[float] = TAUS
) -> list[dict[str, Any]]:
    """The escalation sweep on explicit (confidence, outcome) pairs.

    The gate escalates when the confidence is **below** τ: the same rule, and
    the same meaning, as ``core.judge.calibration.escalation_sweep`` (which
    reads the confidence off a sample's distribution, and so cannot be used
    for a confidence that is not a distribution's top probability).
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
    """The AUC's bootstrap interval, the repository's method on explicit pairs.

    The judgment is the unit: each draw takes the same number of judgments
    with replacement, the AUC is recomputed, and the interval is the 2.5th
    and 97.5th percentile of the draws.
    """
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
        """A percentile, interpolated between the order statistics.

        The repository's own rule (``core.judge.calibration._percentiles``),
        so the two intervals are computed the same way.
        """
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
    """The τ whose escalation share is the largest that stays under the budget.

    The gate escalates when the confidence is below τ, so the escalation share
    grows with τ. The τ returned is the largest on a 0.005 grid whose
    escalation share does not exceed the budget; the row that would exceed it
    is returned beside it, because a gap in the confidence distribution can
    put the two far apart.
    """
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


def capped_protocol(
    outcomes: Sequence[bool],
    disagree: Sequence[bool],
    scores: Sequence[float],
    budget: float,
) -> dict[str, Any]:
    """The both-order protocol inside an escalation budget.

    The published protocol escalates **every** disagreement, which is 86.7 %
    of the steps. A budget needs a ranking, and no ranking is part of the
    published protocol; the scores passed in are the candidate rankings (the
    first order's confidence, the mean confidence, the mean vector's
    confidence), and the steps are escalated from the most suspicious score
    up, until the budget is spent.
    """
    disagreements = [index for index, flag in enumerate(disagree) if flag]
    if not disagreements:
        return {}
    order = sorted(disagreements, key=lambda index: scores[index])
    budget_steps = int(round(budget * len(outcomes)))
    chosen = set(order[:budget_steps])
    wrong = sum(1 for outcome in outcomes if not outcome)
    right = sum(1 for outcome in outcomes if outcome)
    caught = sum(1 for index in chosen if not outcomes[index])
    taxed = sum(1 for index in chosen if outcomes[index])
    return {
        "escalated": len(chosen),
        "share": round(len(chosen) / len(outcomes), 4),
        "caught": caught,
        "taxed": taxed,
        "catch": round(caught / wrong, 4) if wrong else 0.0,
        "tax": round(taxed / right, 4) if right else 0.0,
        "disagreements_available": len(disagreements),
    }


# --- the replay ---------------------------------------------------------------


def load_steps(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["trace"]


def analyse(replay: Mapping[str, Any], recorded: Mapping[str, Any] | None) -> dict[str, Any]:
    """Everything the brief asks for, for one model."""
    rows = list(replay["steps"])
    n = len(rows)

    per_step: list[dict[str, Any]] = []
    for row in rows:
        truth_key = KEYS[int(row["truth"])]
        shown_key = KEYS[int(row["shown"])]
        other_key = KEYS[int(row["decoy"])]
        original = row["original"]
        reversed_ = row["reversed"]
        orig_argmax = original["argmax"]
        rev_argmax = reversed_["argmax"]
        degenerate = shown_key == other_key
        if degenerate:
            kind = "identical_prompt"
        elif rev_argmax == other_key:
            kind = "positional"
        elif rev_argmax == shown_key:
            kind = "content"
        else:
            kind = "third"
        per_step.append(
            {
                "t": row["t"],
                "trial": row["trial"],
                "truth": truth_key,
                "shown": shown_key,
                "other": other_key,
                "group": "truth_first" if shown_key == truth_key else "decoy_first",
                "degenerate": degenerate,
                "orig_argmax": orig_argmax,
                "rev_argmax": rev_argmax,
                "orig_conf": original["confidence"],
                "rev_conf": reversed_["confidence"],
                "orig_right": orig_argmax == truth_key,
                "rev_right": rev_argmax == truth_key,
                "kind": kind,
                "disagree": orig_argmax != rev_argmax,
                "identical_vector": original["probs"] == reversed_["probs"],
            }
        )

    # -- 1. the positional share -----------------------------------------
    def tally(subset: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        counts = {"positional": 0, "content": 0, "third": 0, "identical_prompt": 0}
        for step in subset:
            counts[step["kind"]] += 1
        total = len(subset)
        return {
            "n": total,
            **counts,
            "positional_share": round(counts["positional"] / total, 4) if total else None,
            "content_share": round(counts["content"] / total, 4) if total else None,
            "third_share": round(counts["third"] / total, 4) if total else None,
        }

    non_degenerate = [step for step in per_step if not step["degenerate"]]
    degenerate = [step for step in per_step if step["degenerate"]]
    positional_share = {
        "all_steps": tally(per_step),
        "distinct_conditions": tally(non_degenerate),
        "by_group": {
            group: tally([step for step in per_step if step["group"] == group])
            for group in ("truth_first", "decoy_first")
        },
        "determinism_control": {
            "steps": len(degenerate),
            "identical_prompt": len(degenerate),
            "identical_vector": sum(1 for step in degenerate if step["identical_vector"]),
            "identical_argmax": sum(
                1 for step in degenerate if step["orig_argmax"] == step["rev_argmax"]
            ),
        },
    }

    # -- the two orders, each on its own --------------------------------
    def order_summary(
        argmax_key: str, confidence_key: str
    ) -> dict[str, Any]:
        right = [step for step in per_step if step[f"{argmax_key}_right"]]
        confidences = [step[confidence_key] for step in per_step]
        first_named = [step for step in per_step if step[f"{argmax_key}_argmax"] == step["shown"]]
        pairs = [(step[confidence_key], step[f"{argmax_key}_right"]) for step in per_step]
        by_group = {}
        for group in ("truth_first", "decoy_first"):
            rows_in_group = [step for step in per_step if step["group"] == group]
            hits = sum(1 for step in rows_in_group if step[f"{argmax_key}_right"])
            by_group[group] = {
                "n": len(rows_in_group),
                "accuracy": round(hits / len(rows_in_group), 4) if rows_in_group else None,
                "mean_confidence": round(
                    statistics.fmean(step[confidence_key] for step in rows_in_group), 4
                )
                if rows_in_group
                else None,
            }
        return {
            "accuracy": round(len(right) / len(per_step), 4) if per_step else None,
            "mean_confidence": round(statistics.fmean(confidences), 4) if confidences else None,
            "position_answers": len(first_named),
            "position_answer_share": round(len(first_named) / len(per_step), 4) if per_step else None,
            "by_group": by_group,
            "auc": bootstrap_auc(pairs),
        }

    orders = {
        "original": order_summary("orig", "orig_conf"),
        "reversed": order_summary("rev", "rev_conf"),
    }

    # -- 2. the real disagreement set ------------------------------------
    disagreements = [step for step in per_step if step["disagree"]]
    wrong = [step for step in per_step if not step["orig_right"]]
    right_steps = [step for step in per_step if step["orig_right"]]
    caught = [step for step in disagreements if not step["orig_right"]]
    taxed = [step for step in disagreements if step["orig_right"]]
    position_answer_steps = [step for step in per_step if step["orig_argmax"] == step["shown"]]
    assumption = {
        "the_swap_assumption_says": (
            "the two orders disagree exactly when the answer was one of the two "
            "named conditions"
        ),
        "position_answers": len(position_answer_steps),
        "predicted_escalations": len(position_answer_steps),
        "measured_escalations": len(disagreements),
        "degenerate_steps_that_cannot_disagree": len(degenerate),
        "note": (
            "the degenerate steps name the same condition twice, so the reversed "
            "prompt is byte-identical and the two orders cannot disagree there"
        ),
    }
    disagreement = {
        "n": n,
        "escalations": len(disagreements),
        "escalation_share": round(len(disagreements) / n, 4) if n else None,
        "wrong": len(wrong),
        "right": len(right_steps),
        "caught": len(caught),
        "taxed": len(taxed),
        "catch": round(len(caught) / len(wrong), 4) if wrong else 0.0,
        "tax": round(len(taxed) / len(right_steps), 4) if right_steps else 0.0,
        "by_group": {
            group: {
                "n": sum(1 for step in per_step if step["group"] == group),
                "escalations": sum(
                    1 for step in disagreements if step["group"] == group
                ),
                "caught": sum(1 for step in caught if step["group"] == group),
            }
            for group in ("truth_first", "decoy_first")
        },
        "degenerate_agreement": {
            "steps": len(degenerate),
            "disagreements": sum(1 for step in degenerate if step["disagree"]),
        },
        "assumption_check": assumption,
    }

    # -- 3. the two averages ---------------------------------------------
    mean_conf_pairs: list[tuple[float, bool]] = []
    mean_vec_pairs: list[tuple[float, bool]] = []
    mean_confidence_samples: list[CalibrationSample | None] = []
    mean_vector_samples: list[CalibrationSample] = []
    for row, step in zip(rows, per_step):
        original = row["original"]
        reversed_ = row["reversed"]
        averaged_vector = mean_vector(original["probs"], reversed_["probs"])
        averaged_confidence = (original["confidence"] + reversed_["confidence"]) / 2.0
        outcome = step["orig_right"]
        mean_conf_pairs.append((averaged_confidence, outcome))
        mean_vec_pairs.append((max(averaged_vector.values()), outcome))
        carrier = _pair_distribution(averaged_confidence)
        if carrier is None:
            mean_confidence_samples.append(None)
        else:
            mean_confidence_samples.append(
                CalibrationSample(
                    backend="thor-admit",
                    model=replay["model"],
                    task="sea-state-both-order",
                    kind="mean_confidence",
                    qid=f"mean-conf-{row['t']}",
                    distribution=carrier,
                    outcome=outcome,
                    answer=step["orig_argmax"],
                    truth=step["truth"],
                )
            )
        mean_vector_samples.append(
            CalibrationSample(
                backend="thor-admit",
                model=replay["model"],
                task="sea-state-both-order",
                kind="mean_vector",
                qid=f"mean-vec-{row['t']}",
                distribution=averaged_vector,
                outcome=outcome,
                answer=step["orig_argmax"],
                truth=step["truth"],
            )
        )

    canonical_pairs = [(step["orig_conf"], step["orig_right"]) for step in per_step]
    averaging = {
        "canonical_original_only": {
            "auc": bootstrap_auc(canonical_pairs),
            "sweep": sweep(canonical_pairs),
        },
        "mean_confidence": {
            "auc": bootstrap_auc(mean_conf_pairs),
            "sweep": sweep(mean_conf_pairs),
            "mean_value": round(
                statistics.fmean(pair[0] for pair in mean_conf_pairs), 4
            )
            if mean_conf_pairs
            else None,
            "repository_sweep_agrees": _sweep_agrees(mean_confidence_samples, mean_conf_pairs),
        },
        "mean_vector": {
            "auc": bootstrap_auc(mean_vec_pairs),
            "sweep": sweep(mean_vec_pairs),
            "mean_value": round(
                statistics.fmean(pair[0] for pair in mean_vec_pairs), 4
            )
            if mean_vec_pairs
            else None,
            "repository_sweep_agrees": _sweep_agrees(mean_vector_samples, mean_vec_pairs),
        },
    }

    # -- 4. sane budgets ---------------------------------------------------
    budgets: dict[str, Any] = {"budgets": [budget for budget in BUDGETS]}
    budgets["tau_gate"] = {
        f"{budget:.2f}": tau_for_budget(canonical_pairs, budget) for budget in BUDGETS
    }
    budgets["mean_confidence_gate"] = {
        f"{budget:.2f}": tau_for_budget(mean_conf_pairs, budget) for budget in BUDGETS
    }
    budgets["mean_vector_gate"] = {
        f"{budget:.2f}": tau_for_budget(mean_vec_pairs, budget) for budget in BUDGETS
    }
    disagree_flags = [step["disagree"] for step in per_step]
    outcome_flags = [step["orig_right"] for step in per_step]
    budgets["both_order"] = {
        "unbudgeted": {
            "escalated": len(disagreements),
            "share": round(len(disagreements) / n, 4) if n else None,
            "catch": round(len(caught) / len(wrong), 4) if wrong else 0.0,
            "tax": round(len(taxed) / len(right_steps), 4) if right_steps else 0.0,
        },
        "capped": {
            ranking: {
                f"{budget:.2f}": capped_protocol(
                    outcome_flags,
                    disagree_flags,
                    scores,
                    budget,
                )
                for budget in BUDGETS
            }
            for ranking, scores in (
                ("original_confidence_ascending", [step["orig_conf"] for step in per_step]),
                ("mean_confidence_ascending", [pair[0] for pair in mean_conf_pairs]),
                ("mean_vector_confidence_ascending", [pair[0] for pair in mean_vec_pairs]),
            )
        },
    }

    # -- 5. the latency, with the box ------------------------------------
    latency = dict(replay.get("latency") or {})
    latency["box"] = replay.get("box")

    # -- the joint: did the answer follow the truth or the position? ------
    truth_joint: dict[str, Any] = {}
    for group in ("all", "truth_first", "decoy_first"):
        subset = [
            step
            for step in per_step
            if group == "all" or step["group"] == group
        ]
        both_truth = sum(
            1 for step in subset if step["orig_right"] and step["rev_right"]
        )
        orig_truth_rev_other = sum(
            1 for step in subset if step["orig_right"] and not step["rev_right"]
        )
        orig_other_rev_truth = sum(
            1 for step in subset if not step["orig_right"] and step["rev_right"]
        )
        both_other = sum(
            1 for step in subset if not step["orig_right"] and not step["rev_right"]
        )
        truth_joint[group] = {
            "n": len(subset),
            "both_named_the_truth": both_truth,
            "original_truth_reversed_other": orig_truth_rev_other,
            "original_other_reversed_truth": orig_other_rev_truth,
            "both_named_an_other": both_other,
            "switched": orig_truth_rev_other + orig_other_rev_truth,
            "switched_share": round(
                (orig_truth_rev_other + orig_other_rev_truth) / len(subset), 4
            )
            if subset
            else None,
        }

    result: dict[str, Any] = {
        "model": replay["model"],
        "n": n,
        "url": replay.get("url"),
        "server": replay.get("server"),
        "box": replay.get("box"),
        "fidelity": replay.get("fidelity"),
        "positional_share": positional_share,
        "orders": orders,
        "truth_joint": truth_joint,
        "disagreement": disagreement,
        "averaging": averaging,
        "budgets": budgets,
        "latency": latency,
    }

    if recorded is not None:
        result["recorded_baseline"] = _recorded_baseline(recorded)
    return result


def _pair_distribution(confidence: float) -> dict[str, float] | None:
    """A distribution whose top probability is the given confidence.

    Used only to carry a mean-confidence through the repository's own sweep
    and bootstrap, which read the confidence off a distribution. The shape is
    a point mass on one option with the remainder on a second, so the top
    probability is exactly the confidence given.

    ``None`` below a half: a distribution that sums to one cannot have a top
    probability under a half (two options of at most that much cannot reach
    one), so a confidence under a half has no such carrier and the
    repository's sweep cannot read it. The pairs-based sweep can, which is
    why the sweeps here are written on pairs.
    """
    confidence = max(0.0, min(1.0, float(confidence)))
    if confidence < 0.5:
        return None
    return {"X": confidence, "Y": 1.0 - confidence} if confidence < 1.0 else {"X": 1.0}


def _sweep_agrees(
    samples: Sequence[CalibrationSample | None], pairs: Sequence[tuple[float, bool]]
) -> bool | None:
    """Whether the repository's sweep and this script's sweep agree.

    The repository reads the confidence off the distribution; this script
    reads it off the pair. On the mean vector they must agree exactly; on the
    mean confidence the distribution carries the confidence as its top
    probability, so they must agree there too.

    ``None`` when a confidence has no distribution to be read from (a mean
    confidence under a half), because then the repository's sweep cannot be
    asked the question at all.
    """
    from core.judge.calibration import escalation_sweep as repository_sweep

    if any(sample is None for sample in samples):
        return None
    repository = repository_sweep([sample for sample in samples if sample], TAUS)
    mine = sweep(pairs)
    if len(repository) != len(mine):
        return False
    for repo_row, my_row in zip(repository, mine):
        if repo_row.escalated != my_row["escalated"]:
            return False
        # this sweep rounds to four places, the repository keeps full precision
        if abs(repo_row.catch - my_row["catch"]) > 1e-4:
            return False
        if abs(repo_row.tax - my_row["tax"]) > 1e-4:
            return False
    return True


def _recorded_baseline(recorded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The October recording's own numbers, recomputed the same way."""
    steps = []
    for entry in recorded:
        probs = {key: float(value) for key, value in entry["probs"].items()}
        truth_key = KEYS[int(entry["truth"])]
        shown_key = KEYS[int(entry["shown"])]
        argmax = argmax_of(probs)
        steps.append(
            {
                "truth": truth_key,
                "shown": shown_key,
                "argmax": argmax,
                "confidence": probs[argmax],
                "right": argmax == truth_key,
                "group": "truth_first" if shown_key == truth_key else "decoy_first",
            }
        )
    pairs = [(step["confidence"], step["right"]) for step in steps]
    wrong = [step for step in steps if not step["right"]]
    right_steps = [step for step in steps if step["right"]]
    return {
        "n": len(steps),
        "accuracy": round(len(right_steps) / len(steps), 4) if steps else None,
        "position_answers": sum(1 for step in steps if step["argmax"] == step["shown"]),
        "auc": bootstrap_auc(pairs),
        "sweep": sweep(pairs),
        "wrong": len(wrong),
        "right": len(right_steps),
    }


# --- the run ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay",
        type=Path,
        nargs="*",
        default=None,
        help="the replay JSON(s) (default: every results/replay-*.json)",
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=TRACES,
        help="where the October traces live",
    )
    parser.add_argument("--out", type=Path, default=RESULTS / "reversed-measurement.json")
    args = parser.parse_args()

    replays = args.replay
    if not replays:
        replays = sorted(RESULTS.glob("replay-*.json"))
    if not replays:
        print("no replay JSON to measure")
        return 1

    models: dict[str, Any] = {}
    for path in replays:
        replay = json.loads(path.read_text(encoding="utf-8"))
        model = replay["model"]
        trace_path = args.trace_dir / f"exp_c_trace_{model}.json"
        recorded = None
        if trace_path.exists():
            recorded = load_steps(trace_path)
        models[model] = analyse(replay, recorded)

    result = {
        "experiment": "judge-reversed-replay",
        "measured": sorted(models),
        "taus": list(TAUS),
        "budgets": list(BUDGETS),
        "canonical_confidence": CANONICAL_CONFIDENCE,
        "models": models,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    for model, numbers in models.items():
        _print_summary(model, numbers)
    return 0


def _print_summary(model: str, numbers: Mapping[str, Any]) -> None:
    share = numbers["positional_share"]
    disagree = numbers["disagreement"]
    averaging = numbers["averaging"]
    print(f"\n=== {model} ===")
    print(
        "positional share (distinct conditions): "
        f"{share['distinct_conditions']['positional']} positional, "
        f"{share['distinct_conditions']['content']} content, "
        f"{share['distinct_conditions']['third']} third"
    )
    print(
        f"disagreements: {disagree['escalations']} of {disagree['n']} "
        f"({disagree['escalation_share']}) — catch {disagree['catch']}, tax {disagree['tax']}"
    )
    for name in ("canonical_original_only", "mean_confidence", "mean_vector"):
        auc = averaging[name]["auc"]
        print(f"{name}: AUC {auc['auc']} [{auc['low']}, {auc['high']}]" if auc else f"{name}: —")


if __name__ == "__main__":
    raise SystemExit(main())
