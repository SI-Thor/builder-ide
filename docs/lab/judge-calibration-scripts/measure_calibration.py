"""Measure the calibration of the judge's confidence on the data we have.

The seed bank #2 (B15) says the experiment costs no new model runs: the
endpoint already returned the full probability vector for every answer, so
the same week of logs can be re-scored. This script does exactly that and
nothing more — it replays **recorded vectors** through
:mod:`core.judge.calibration` and writes the numbers.

Four sets of recorded vectors, all of them real:

* the **liquid study's d1 traces** (``exp_c_trace_d1-2B.json`` and
  ``exp_c_trace_d1-3B.json``) — 240 five-way judgments each, with the
  probability vector, the model's answer and the truth;
* the **tiles rig** (``judge-tiles-coldstart.json``) — 600 plays of the
  acceptance rig's simulated game with the judge's distribution over the
  six tiles, and the outcome replayed from the rig's own sha256 draw;
* the **clef cascade's teacher** (``c3-calibration-runs.json``) — 200 cases
  of raw probability vectors over the scene, defect and tile questions, with
  the ground truth rebuilt from the cascade's own case builder;
* the **clef cascade's student** (the same file) — the lopsided booleans,
  labelled by the teacher.

Nothing here calls a model. Nothing here needs a GPU, a network or a
cloud key. The machine state is recorded beside the numbers because a
number without the box it was measured on is a number without a meaning.

    .venv/bin/python docs/lab/judge-calibration-scripts/measure_calibration.py
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.judge.calibration import (  # noqa: E402
    CANONICAL_CONFIDENCE,
    CONFIDENCE_DEFINITIONS,
    CalibrationSample,
    TemperatureScale,
    area_under_curve,
    bootstrap_auc,
    bootstrap_brier_improvement,
    cell_of,
    confidence_of,
    escalation_sweep,
    expected_calibration_error,
    mean_confidence,
    raw_floor_for,
    recalibrate,
    reliability_curve,
    brier_score,
    accuracy,
)
from core.judge.calibration import IsotonicScale  # noqa: E402

RIG = REPO / "docs/lab/judge-scripts/measure_tiles_coldstart.py"
COLDSTART = REPO / "docs/lab/judge-scripts/results/judge-tiles-coldstart.json"
HYSTERESIS = REPO / "docs/lab/hysteresis-scripts/results/hysteresis-d1-sweep.json"
LIQUID = Path("/home/proart/lm-wt/liquid-study/results")
CLEF = Path("/home/proart/lm-wt/clef-cascade/results")
CLEF_SCRIPTS = REPO / "docs/lab/clef-cascade-scripts"

TAUS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


# --- the machine ----------------------------------------------------------------


def machine_state() -> dict[str, Any]:
    """The box the numbers were measured on, beside the numbers."""
    state: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": _git("rev-parse", "--short", "HEAD"),
        "gpu": "not used — the vectors are replayed from disk",
    }
    try:
        import numpy  # noqa: PLC0415

        state["numpy"] = numpy.__version__
    except Exception:  # pragma: no cover - numpy is not required
        state["numpy"] = None
    return state


def _git(*args: str) -> str:
    import subprocess  # noqa: PLC0415

    try:
        return subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:  # pragma: no cover - git may be absent
        return "unknown"


# --- the datasets ---------------------------------------------------------------


def liquid_traces(model: str) -> list[CalibrationSample]:
    """The liquid study's recorded d1 traces.

    Each entry is one five-way judgment: the probability vector the
    endpoint returned, the model's answer (``shown``) and the ground truth
    (``truth``). The options are the sea states in order, so the truth's
    option is ``"ABCDE"[truth]`` — the liquid study's own rule ("the ground
    truth is always the TRUE condition").

    The model's answer is the **argmax of the vector**, and the outcome is
    whether that argmax names the true sea state. The trace's ``shown``
    field is the state the prompt named first, which is not the model's
    answer: the study's own numbers (d1-2B accuracy 0.525, d1-3B 0.3292)
    are the argmax rule, and they are what this reproduces.
    """
    path = LIQUID / f"exp_c_trace_{model}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = sorted(data["trace"][0]["probs"])
    samples: list[CalibrationSample] = []
    for entry in data["trace"]:
        distribution = {key: float(entry["probs"][key]) for key in keys}
        truth_key = keys[int(entry["truth"])]
        answer = max(sorted(distribution), key=lambda key: distribution[key])
        samples.append(
            CalibrationSample(
                backend="d1",
                model=model,
                task="liquid-trace",
                kind="choice",
                qid="option",
                distribution=distribution,
                outcome=answer == truth_key,
                answer=answer,
                truth=truth_key,
                at=str(entry.get("t", "")),
            )
        )
    return samples


def _rig_module():
    """The tiles rig, imported from its own script — the constants, verbatim."""
    spec = importlib.util.spec_from_file_location("coldstart_rig", str(RIG))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def tiles_rig_samples() -> tuple[list[CalibrationSample], dict[str, Any]]:
    """The tiles rig's judge-only arm, with its outcomes replayed.

    The arm wrote its distributions but not its play rows, so the outcome
    is recomputed from the rig's own seeded draw: ``sha256(tile|bucket|index)``
    against the match/miss chance of the tile's style against the context's
    wanted style. The replay is exact — the rig's draw is a hash, not a
    random number.

    A judgment is scored by the play that answers it: the play of the tile
    the judge named. A surfaced judgment (below τ) fell back to a seeded
    uniform pick, so that play is not the judgment's answer and does not
    score it.
    """
    rig = _rig_module()
    from core.tiles.library import TileLibrary  # noqa: PLC0415
    from core.vocab.registry import VocabularyRegistry  # noqa: PLC0415
    from core.vocab.words import default_entries  # noqa: PLC0415

    library = TileLibrary(registry=VocabularyRegistry(default_entries()))
    tiles = rig.author_tiles(library)
    style_of = {tile.id: tile.steps[0].params["style"] for tile in tiles}

    data = json.loads(COLDSTART.read_text(encoding="utf-8"))
    trace = data["judge_only_trace"]
    contexts = rig.contexts(len(trace))
    rng = random.Random(99)  # the rig's own seed for the surfaced fallback

    samples: list[CalibrationSample] = []
    n_surfaced = 0
    n_unanswered = 0
    for index, entry in enumerate(trace):
        context = contexts[index]
        bucket = entry["bucket"]
        distribution = {key: float(value) for key, value in entry["distribution"].items()}
        answer = max(sorted(distribution), key=lambda key: distribution[key])
        if entry["gate"] == "act":
            tile_id = answer
        else:
            n_surfaced += 1
            tile_id = rng.choice([tile.id for tile in tiles])
        chance = (
            rig.P_MATCH
            if style_of[tile_id] == context["wanted_style"]
            else rig.P_MISS
        )
        won = rig.game_draw(tile_id, bucket, index) < chance
        if tile_id != answer:
            # the play of another tile says nothing about this judgment
            n_unanswered += 1
            continue
        others = {key: value for key, value in distribution.items() if key != answer}
        total = sum(others.values())
        truth = answer if won else (
            max(sorted(others), key=lambda key: others[key]) if total > 0 else None
        )
        samples.append(
            CalibrationSample(
                backend="d1",
                model=data["model"],
                task="tiles.shortlist",
                kind="choice",
                qid="tile",
                distribution=distribution,
                outcome=won,
                answer=answer,
                truth=truth,
                at=str(index),
            )
        )
    meta = {
        "n_plays": len(trace),
        "n_surfaced": n_surfaced,
        "n_scored": len(samples),
        "n_play_of_another_tile": n_unanswered,
        "box_at_start": data.get("box_at_start"),
        "win_rates": data.get("win_rates"),
    }
    return samples, meta


def _clef_cases():
    """The clef cascade's cases, rebuilt from its own builder (no network)."""
    sys.path.insert(0, str(CLEF_SCRIPTS))
    import cascade  # noqa: PLC0415

    return {case.id: case for case in cascade.build_all(80, 60, 60)}


def clef_teacher_samples() -> list[CalibrationSample]:
    """The teacher's raw probability vectors, scored against the truth.

    The teacher's answers are the reference the cascade calibrated against,
    and the ground truth comes from the cascade's own case builder — the
    same builder that made the cases the teacher saw.
    """
    cases = _clef_cases()
    data = json.loads((CLEF / "c3-calibration-runs.json").read_text(encoding="utf-8"))
    teacher = data["teacher"][0]["cases"]
    samples: list[CalibrationSample] = []
    for entry in teacher:
        case = cases[entry["id"]]
        for qid, decided in (entry.get("decided") or {}).items():
            truth = case.truth.get(qid)
            if truth is None:
                continue
            if decided["type"] == "noul":
                p_true = float(decided["p"])
                distribution = {"true": p_true, "false": round(1.0 - p_true, 10)}
                truth_key = "true" if truth else "false"
            else:
                distribution = {key: float(value) for key, value in decided["p"].items()}
                truth_key = str(truth)
            if truth_key not in distribution:
                continue
            answer = max(sorted(distribution), key=lambda key: distribution[key])
            samples.append(
                CalibrationSample(
                    backend="clef",
                    model="clef-27B",
                    task=f"{case.task}.{qid}",
                    kind="choice" if decided["type"] != "noul" else "noul",
                    qid=qid,
                    distribution=distribution,
                    outcome=answer == truth_key,
                    answer=answer,
                    truth=truth_key,
                    at=entry["id"],
                )
            )
    return samples


def clef_student_booleans() -> list[CalibrationSample]:
    """Clef-flash's lopsided booleans, labelled by the teacher.

    The student ran the baseline harness (no gate facts, no threshold, no
    Platt map) on each split's evaluation half. The teacher labelled every
    case once, so the teacher's answer is the outcome — the same protocol
    the cascade's own calibration used.

    Only the two boolean questions are taken: a noul's probability is a
    single number, and a boolean is where a lopsided answer hurts most
    (a gate reads the probability and decides).
    """
    cases = _clef_cases()
    data = json.loads((CLEF / "c3-calibration-runs.json").read_text(encoding="utf-8"))
    teacher = {
        entry["id"]: entry.get("decided") or {}
        for entry in data["teacher"][0]["cases"]
    }
    order = {case_id: index for index, case_id in enumerate(cases)}
    seen: set[str] = set()
    collected: list[tuple[str, str, float, str]] = []
    for run in data["runs"]:
        if run["tag"] != "R0 baseline":
            continue
        for entry in run["run"]["cases"]:
            case_id = entry["id"]
            if case_id in seen:
                continue
            seen.add(case_id)
            for qid, value in (entry.get("raw_p") or {}).items():
                if not isinstance(value, (int, float)):
                    continue
                label = (teacher.get(case_id) or {}).get(qid)
                if not label or label.get("type") != "noul":
                    continue
                # the cascade's noul answer is a JSON boolean, not the
                # string "true" — normalise it to the option key
                answer = label["answer"]
                truth_key = "true" if answer is True or str(answer).lower() == "true" else "false"
                collected.append((case_id, qid, float(value), truth_key))
    collected.sort(key=lambda row: order.get(row[0], 0))
    samples: list[CalibrationSample] = []
    for case_id, qid, p_true, truth_key in collected:
        distribution = {"true": p_true, "false": round(1.0 - p_true, 10)}
        answer = "true" if p_true >= 0.5 else "false"
        samples.append(
            CalibrationSample(
                backend="clef",
                model="clef-flash",
                task=f"scene.{qid}",
                kind="noul",
                qid=qid,
                distribution=distribution,
                outcome=answer == truth_key,
                answer=answer,
                truth=truth_key,
                at=case_id,
            )
        )
    return samples


def tau_gate_analysis(model: str) -> dict[str, Any]:
    """What the decoy-first finding means for the τ gate — measured.

    On this cell the confidence is a **position** detector: the model
    answers the condition the prompt named *first*, so the steps where
    the prompt named the decoy first are the steps where the model is
    confidently wrong. Three things are measured on the recorded trace:

    * the two groups — the prompt named the truth first, the decoy
      first — with their accuracy and their mean confidence;
    * what the τ gate does **in each group** at each τ: the share of
      the group's wrong judgments it escalates (its job) and the share
      of the group's right judgments it taxes (its cost);
    * the both-order protocol — ask the same question with the two named
      conditions in the other order and escalate when the two answers
      disagree — with its cost (two calls a decision) and its effect,
      computed from the model's recorded behaviour in the one order the
      recording holds.

    **The recording does not hold the reversed order.** The protocol's
    effect is therefore computed under one stated assumption: that the
    model treats the reversed prompt as the same question with the two
    named conditions swapped — its answer follows the option it chose,
    renamed — so the two orders disagree exactly when its answer was one
    of the two named conditions. The recording shows the model's answer
    is the **first**-named condition in 208 of its 240 steps (and in
    every one of the 82 decoy-first steps) and the second-named one in
    **none** of them, so on this trace the two orders disagree exactly
    on those 208 steps. A recording of the reversed replies would settle
    it; this measures the rest.
    """
    path = LIQUID / f"exp_c_trace_{model}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["trace"]

    groups: dict[str, list[dict[str, Any]]] = {"truth_first": [], "decoy_first": []}
    latencies: list[float] = []
    position_answers = 0
    for entry in entries:
        keys = sorted(entry["probs"])
        probs = {key: float(entry["probs"][key]) for key in keys}
        truth_key = keys[int(entry["truth"])]
        shown_key = keys[int(entry["shown"])]
        answer = max(sorted(probs), key=lambda key: probs[key])
        confidence = probs[answer]
        group = "truth_first" if shown_key == truth_key else "decoy_first"
        groups[group].append(
            {
                "confidence": confidence,
                "right": answer == truth_key,
                "position_answer": answer == shown_key,
                "reported": float(entry["confidence"]),
            }
        )
        latencies.append(float(entry.get("wall_ms", 0.0)))
        if answer == shown_key:
            position_answers += 1

    def side(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {}
        right = sum(1 for row in rows if row["right"])
        return {
            "n": len(rows),
            "accuracy": round(right / len(rows), 4),
            "mean_confidence": round(
                sum(row["confidence"] for row in rows) / len(rows), 4
            ),
            "mean_reported_confidence": round(
                sum(row["reported"] for row in rows) / len(rows), 4
            ),
            "position_answers": sum(1 for row in rows if row["position_answer"]),
        }

    # -- what the τ gate does, group by group -----------------------------
    sweep: list[dict[str, Any]] = []
    for tau in TAUS:
        entry: dict[str, Any] = {"tau": tau}
        for name, rows in groups.items():
            wrong = [row for row in rows if not row["right"]]
            right = [row for row in rows if row["right"]]
            escalated = [row for row in rows if row["confidence"] < tau]
            caught = [row for row in escalated if not row["right"]]
            taxed = [row for row in escalated if row["right"]]
            entry[name] = {
                "escalated": len(escalated),
                "act_rate": round(1.0 - len(escalated) / len(rows), 4) if rows else None,
                "catch": round(len(caught) / len(wrong), 4) if wrong else None,
                "tax": round(len(taxed) / len(right), 4) if right else None,
            }
        sweep.append(entry)

    # -- the both-order protocol ------------------------------------------
    # the reversed reply is not in the recording; under the stated
    # assumption — the model treats the reversed prompt as the same
    # question with the two named conditions swapped, so its answer
    # follows the option it chose, renamed — the two orders disagree
    # exactly when its answer was one of the two named conditions. On
    # this trace the answer is the first-named one in
    # `position_answers` steps and the second-named one in none, so the
    # disagreement set is the position answers.
    all_rows = groups["truth_first"] + groups["decoy_first"]
    disagreements = [row for row in all_rows if row["position_answer"]]
    wrong = [row for row in all_rows if not row["right"]]
    right = [row for row in all_rows if row["right"]]
    caught = [row for row in disagreements if not row["right"]]
    taxed = [row for row in disagreements if row["right"]]
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0

    return {
        "model": model,
        "n": len(all_rows),
        "groups": {name: side(rows) for name, rows in groups.items()},
        "position_answers": position_answers,
        "gate_by_group": sweep,
        "both_order_protocol": {
            "rule": "ask the same question with the two named conditions in the other "
            "order; escalate when the two answers disagree",
            "assumption": "the model treats the reversed prompt as the same "
            "question with the two named conditions swapped — its answer follows "
            "the option it chose, renamed — so the two orders disagree exactly "
            "when its answer was one of the two named conditions; on this trace "
            f"the first-named one in {position_answers} of its {len(all_rows)} "
            "steps and the second-named one in none",
            "reversed_replies_recorded": False,
            "escalated": len(disagreements),
            "escalation_rate": round(len(disagreements) / len(all_rows), 4),
            "catch": round(len(caught) / len(wrong), 4) if wrong else None,
            "tax": round(len(taxed) / len(right), 4) if right else None,
            "calls_per_judgment": 2,
            "latency_p50_ms_per_decision": round(p50, 4),
            "added_latency_p50_ms": round(p50, 4),
        },
    }


def liquid_trace_breakdown(model: str) -> dict[str, Any]:
    """Why the confidence is what it is: the prompt named the state first.

    The liquid study's task names two sea states, the *shown* one first.
    In 35 % of the steps the shown one is the decoy, and the ground truth
    is always the true condition. So the split below is the whole story of
    a confidence that is anti-correlated with being right: the model is
    confident about **which condition the prompt named**, and the prompt
    is wrong in exactly the rows the model is most sure about.
    """
    path = LIQUID / f"exp_c_trace_{model}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    clean: list[tuple[float, bool]] = []
    noisy: list[tuple[float, bool]] = []
    for entry in data["trace"]:
        keys = sorted(entry["probs"])
        top = max(float(entry["probs"][key]) for key in keys)
        answer = max(sorted(entry["probs"]), key=lambda key: entry["probs"][key])
        right = answer == keys[int(entry["truth"])]
        (clean if int(entry["shown"]) == int(entry["truth"]) else noisy).append((top, right))

    def side(rows: list[tuple[float, bool]]) -> dict[str, Any]:
        if not rows:
            return {}
        return {
            "n": len(rows),
            "accuracy": round(sum(1 for _, right in rows if right) / len(rows), 4),
            "mean_confidence": round(sum(top for top, _ in rows) / len(rows), 4),
        }

    return {
        "prompt_named_the_truth_first": side(clean),
        "prompt_named_the_decoy_first": side(noisy),
    }


def clef_student_lopsidedness(samples: Sequence[CalibrationSample]) -> dict[str, Any]:
    """How lopsided the student's booleans are, and where the gap is.

    The cascade found the student's booleans biased and needing a
    threshold at 0.05–0.20 rather than 0.50. This measures the shape
    behind that: the student's probability for a boolean is bimodal, with
    an empty band in the middle, so every threshold inside the gap gives
    the same decisions.
    """
    values = sorted(
        float(sample.distribution.get("true", 0.0))
        for sample in samples
        if sample.kind == "noul"
    )
    if not values:
        return {}
    histogram: dict[str, int] = {}
    for value in values:
        bucket = f"{int(value * 10) / 10:.1f}"
        histogram[bucket] = histogram.get(bucket, 0) + 1
    # the widest empty band in the probability space: the band where the
    # threshold can move without changing a single decision
    occupied = sorted(float(bucket) for bucket in histogram)
    bands: list[tuple[float, float]] = []
    cursor = 0.0
    for low in occupied:
        if low > cursor:
            bands.append((cursor, low))
        cursor = low + 0.1
    if cursor < 1.0:
        bands.append((cursor, 1.0))
    gap_start, gap_end = max(bands, key=lambda band: band[1] - band[0]) if bands else (0.0, 1.0)
    return {
        "n": len(values),
        "histogram": dict(sorted(histogram.items())),
        "widest_empty_band": [round(gap_start, 2), round(gap_end, 2)],
        "min": round(values[0], 4),
        "max": round(values[-1], 4),
        "mean": round(sum(values) / len(values), 4),
    }


def backend_confidence_of(
    samples: Sequence[CalibrationSample], backend_confidences: Sequence[float]
) -> dict[str, float | None]:
    """How the backend's own confidence compares with the canonical one.

    The seed's first claim is that the three d1 sizes report confidence by
    three different formulas, so a threshold on "confidence" is not the
    same quantity from one model to the next.
    """
    canonical = [sample.confidence(CANONICAL_CONFIDENCE) for sample in samples]
    matches = {
        definition: sum(
            1
            for sample, reported in zip(samples, backend_confidences)
            if abs(sample.confidence(definition) - reported) < 1e-6
        )
        for definition in CONFIDENCE_DEFINITIONS
    }
    return {
        "backend_mean": sum(backend_confidences) / len(backend_confidences),
        "canonical_mean": sum(canonical) / len(canonical),
        "matches_by_definition": matches,
        "n": len(samples),
    }


# --- the measurement ------------------------------------------------------------


def _split(samples: Sequence[CalibrationSample], fraction: float = 0.5):
    """The older half fits, the newer half reads."""
    cut = max(1, min(len(samples) - 1, int(len(samples) * fraction)))
    return list(samples[:cut]), list(samples[cut:])


def _mean_distribution(samples: Sequence[CalibrationSample]) -> dict[str, float]:
    """The cell's mean distribution — the shape the threshold is read on."""
    keys = list(samples[0].distribution)
    means = {
        key: sum(float(sample.distribution.get(key, 0.0)) for sample in samples) / len(samples)
        for key in keys
    }
    total = sum(means.values())
    return {key: value / total for key, value in means.items()} if total else means


def measure_cell(samples: Sequence[CalibrationSample], bins: int = 10) -> dict[str, Any]:
    """One cell: its numbers, its sweep, and its recalibration."""
    if not samples:
        return {}
    cell = cell_of(samples, bins=bins)
    fit, holdout = _split(samples)
    recal = recalibrate(fit, holdout)

    scale = recal.scale
    floors: dict[str, float] = {}
    if scale is not None:
        shape = _mean_distribution(samples)
        for tau in (0.5, 0.6, 0.7):
            floors[str(tau)] = round(raw_floor_for(scale, tau, shape), 4)

    sweeps = {
        definition: [row.as_dict() for row in escalation_sweep(samples, TAUS, definition=definition)]
        for definition in CONFIDENCE_DEFINITIONS
    }
    # the seed's question: is there a τ at which the gate fires the right
    # number of escalations? The best τ is the one that catches every
    # wrong judgment and taxes the fewest right ones.
    best: dict[str, Any] = {}
    for definition, rows in sweeps.items():
        catching = [row for row in rows if row["caught_all"]]
        chosen = (
            min(catching, key=lambda row: row["tax"]) if catching else None
        )
        best[definition] = chosen

    recalibrated = []
    if scale is not None:
        for sample in holdout:
            scaled = scale.apply(sample.distribution)
            recalibrated.append(
                CalibrationSample(
                    backend=sample.backend,
                    model=sample.model,
                    task=sample.task,
                    kind=sample.kind,
                    qid=sample.qid,
                    distribution=scaled,
                    outcome=sample.outcome,
                    answer=sample.answer,
                    truth=sample.truth,
                    at=sample.at,
                )
            )

    return {
        "cell": cell.as_dict(),
        "auc": _round(area_under_curve(
            [(sample.confidence(CANONICAL_CONFIDENCE), sample.outcome) for sample in samples]
        )),
        # the separability with its error bar: the judgment is the unit,
        # and the interval is the 2.5th and 97.5th percentile of the
        # bootstrap's draws
        "auc_interval": _interval(bootstrap_auc(samples, resamples=2000)),
        "sweeps": sweeps,
        "best_tau": best,
        "recalibration": recal.as_dict(),
        "held_out": {
            "n": len(holdout),
            "accuracy_before": _round(accuracy(holdout)),
            "accuracy_after": _round(accuracy(recalibrated) if recalibrated else None),
            "brier_before": _round(brier_score(holdout)),
            "brier_after": _round(brier_score(recalibrated) if recalibrated else None),
            # the improvement, paired: the same judgments scored with and
            # without the scale, so the interval is over the difference
            "brier_improvement": _interval(
                bootstrap_brier_improvement(holdout, scale, resamples=2000)
            ),
            "ece_before": _round(expected_calibration_error(holdout, bins=bins)),
            "ece_after": _round(
                expected_calibration_error(recalibrated, bins=bins) if recalibrated else None
            ),
            "mean_confidence_before": _round(mean_confidence(holdout)),
            "mean_confidence_after": _round(
                mean_confidence(recalibrated) if recalibrated else None
            ),
            # the split is time-ordered: the older half was fitted, the
            # newer half is scored here. The samples carry the timestamp
            # they were judged at, and the cut is on it.
            "split": "time-ordered: the older half of the cell's judgments was fitted, the newer half is scored",
        },
        "raw_floor_for_calibrated_tau": floors,
    }


def _interval(value) -> dict[str, Any] | None:
    """An interval as the JSON carries it."""
    return None if value is None else value.as_dict()


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _fmt(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


# --- the report -----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "results" / "calibration-measurement.json"),
    )
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args()

    tiles_samples, tiles_meta = tiles_rig_samples()
    teacher_samples = clef_teacher_samples()
    student_samples = clef_student_booleans()

    datasets: dict[str, list[CalibrationSample]] = {
        "d1-2B (the liquid study's traces)": liquid_traces("d1-2B"),
        "d1-3B (the liquid study's traces)": liquid_traces("d1-3B"),
        "the tiles rig (judge-only arm)": tiles_samples,
    }
    for sample in teacher_samples:
        datasets.setdefault(f"clef teacher · {sample.task}", []).append(sample)
    for sample in student_samples:
        datasets.setdefault(f"clef student · {sample.task}", []).append(sample)

    measured: dict[str, Any] = {}
    for name, samples in datasets.items():
        if not samples:
            continue
        measured[name] = {
            "n": len(samples),
            "cell": measure_cell(samples, bins=args.bins),
        }

    # -- the seed's first claim: three formulas for "confidence" -----------
    formulas: dict[str, Any] = {}
    for model in ("d1-2B", "d1-3B"):
        path = LIQUID / f"exp_c_trace_{model}.json"
        reported = [float(e["confidence"]) for e in json.loads(path.read_text())["trace"]]
        samples = liquid_traces(model)
        formulas[model] = backend_confidence_of(samples, reported)
        formulas[model]["prompt_breakdown"] = liquid_trace_breakdown(model)
        # what the same τ means on each model, under each definition
        formulas[model]["tau_means"] = {
            definition: {
                "at_tau_0.5": _top_probability_at(samples, definition, 0.5),
                "at_tau_0.7": _top_probability_at(samples, definition, 0.7),
            }
            for definition in CONFIDENCE_DEFINITIONS
        }

    # -- Clef's lopsided booleans -----------------------------------------
    lopsided = {
        task: clef_student_lopsidedness(
            [s for s in student_samples if f"scene.{s.qid}" == task]
        )
        for task in {f"scene.{s.qid}" for s in student_samples}
    }

    # -- the tiles rig's own numbers, beside ours -----------------------
    coldstart = json.loads(COLDSTART.read_text(encoding="utf-8"))
    hysteresis = json.loads(HYSTERESIS.read_text(encoding="utf-8"))

    result = {
        "experiment": "judge calibration — one definition of confidence, and the Brier tracked against it",
        "brief": "seed bank #2 (B15)",
        "machine": machine_state(),
        "definitions": list(CONFIDENCE_DEFINITIONS),
        "canonical_definition": CANONICAL_CONFIDENCE,
        "bins": args.bins,
        "taus": list(TAUS),
        "datasets": measured,
        "backend_confidence_formulas": formulas,
        "tau_gate": {
            model: tau_gate_analysis(model) for model in ("d1-2B", "d1-3B")
        },
        "clef_student_lopsidedness": lopsided,
        "tiles_rig": {
            **tiles_meta,
            "coldstart": {
                "model": coldstart.get("model"),
                "tau_default": coldstart.get("tau_default"),
                "n_plays": coldstart.get("n_plays"),
                "win_rates": coldstart.get("win_rates"),
                "judge_only_gates": coldstart.get("judge_only_gates"),
                "cost": coldstart.get("cost"),
                "box_at_start": coldstart.get("box_at_start"),
                "box_at_end": coldstart.get("box_at_end"),
                "server_peak_rss_mb": coldstart.get("server_peak_rss_mb"),
            },
            "hysteresis_sweep": {
                "models": list(hysteresis.get("models", {})),
                "window_ticks": hysteresis.get("window_ticks"),
                "bound_up_ticks": hysteresis.get("bound_up_ticks"),
                "bound_down_ticks": hysteresis.get("bound_down_ticks"),
                "chosen": {
                    model: block.get("chosen")
                    for model, block in hysteresis.get("models", {}).items()
                },
            },
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    _print_summary(result)
    print(f"\nwrote {out}")
    return 0


def _top_probability_at(
    samples: Sequence[CalibrationSample], definition: str, tau: float
) -> float | None:
    """The top probability that has to clear τ under one definition.

    This is the heart of the seed's claim: the same τ is a different
    probability on a different model, because the two models report
    confidence by different formulas. The shape is the cell's mean
    distribution; the top option's mass is swept and the others keep their
    relative shares of what is left.
    """
    shape = _mean_distribution(samples)
    keys = list(shape)
    top = max(keys, key=lambda key: shape[key])
    rest = [key for key in keys if key != top]
    rest_total = sum(shape[key] for key in rest)
    shares = {key: (shape[key] / rest_total if rest_total > 0 else 0.0) for key in rest}

    def confidence_at(raw: float) -> float:
        distribution = {top: raw}
        for key, share in shares.items():
            distribution[key] = (1.0 - raw) * share
        return confidence_of(distribution, definition)

    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2.0
        if confidence_at(middle) < tau:
            low = middle
        else:
            high = middle
        if high - low < 1e-9:
            break
    return high


def _print_summary(result: Mapping[str, Any]) -> None:
    print("=" * 78)
    print("the judge's calibration, measured on recorded vectors")
    print("=" * 78)
    machine = result["machine"]
    print(f"machine: {machine['platform']}")
    print(f"python:  {machine['python']}   numpy: {machine['numpy']}   git: {machine['git']}")
    print(f"definition: {result['canonical_definition']}")
    print()
    header = f"{'cell':44s} {'n':>5s} {'acc':>7s} {'Brier':>7s} {'ECE':>7s} {'conf':>7s}"
    print(header)
    print("-" * len(header))
    for name, block in result["datasets"].items():
        cell = block["cell"]["cell"]
        print(
            f"{name:44s} {cell['n']:5d} {_fmt(cell['accuracy']):>7s} "
            f"{_fmt(cell['brier']):>7s} {_fmt(cell['ece']):>7s} "
            f"{_fmt(cell['mean_confidence']):>7s}"
        )
    print()
    for name, block in result["datasets"].items():
        recal = block["cell"]["recalibration"]
        held = block["cell"]["held_out"]
        print(f"--- {name}")
        print(
            f"    recalibration: {recal['kind']} — {recal['reason']}"
        )
        print(
            f"    held-out Brier: {_fmt(held['brier_before'])} -> {_fmt(held['brier_after'])}"
            f"   ECE: {_fmt(held['ece_before'])} -> {_fmt(held['ece_after'])}"
        )
        floors = block["cell"].get("raw_floor_for_calibrated_tau") or {}
        if floors:
            print(
                "    the raw confidence that clears a calibrated τ of "
                + ", ".join(f"{tau}: {value}" for tau, value in floors.items())
            )
    print()
    print("the backend's own confidence vs the canonical one")
    for model, block in result["backend_confidence_formulas"].items():
        matches = block["matches_by_definition"]
        matched = [name for name, count in matches.items() if count == block["n"]]
        print(
            f"  {model}: the reported number is the {matched[0] if matched else '?'} "
            f"for {matches.get(matched[0], 0)}/{block['n']} judgments "
            f"(backend mean {block['backend_mean']:.4f}, canonical mean {block['canonical_mean']:.4f})"
        )


if __name__ == "__main__":
    raise SystemExit(main())
