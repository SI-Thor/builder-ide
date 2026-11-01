"""The cascade harness: one parameterized student, three levers, three tasks.

This is the machinery C3 and C4 share.

  teacher   Clef-27B on Workers AI labels a task set.
  student   Clef-flash on Workers AI answers the same task set under a
            *harness*: a small, explicit set of levers.

The harness levers (each one a knob with a default):

  wording        how the question is phrased.  "plain" is last-mile's
                 wording, "rule" restates the decision rule and demands one
                 option, "terse" cuts it down.
  gate_facts     whether code-computed gate facts go into the state.  This
                 is the D47 lever: code computes the gates, the model judges
                 over them.
  threshold      the probability at which a boolean is called true.
  calibration    per-boolean Platt map, p' = sigmoid(a*logit(p) + b), fitted
                 on the teacher's labels.  This is the calibration map for
                 the biased booleans.
  choice_prior   per-option additive log-prior for choice questions.
  hint           free text the cloud improver may add to the state.

Everything is pure Python 3 stdlib, deterministic given a seed, and every
fit happens on a calibration split that never overlaps the eval split.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gates
import tasks

# ==========================================================================
# harness
# ==========================================================================

WORDINGS = ("plain", "rule", "terse")


@dataclass
class Harness:
    wording: str = "plain"
    gate_facts: bool = False
    threshold: float = 0.5
    calibration: dict[str, list[float]] = field(default_factory=dict)
    choice_prior: dict[str, dict[str, float]] = field(default_factory=dict)
    hint: str = ""
    name: str = "h0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "wording": self.wording,
            "gate_facts": self.gate_facts, "threshold": self.threshold,
            "calibration": {k: [round(x, 5) for x in v]
                            for k, v in self.calibration.items()},
            "choice_prior": {k: {o: round(w, 5) for o, w in v.items()}
                             for k, v in self.choice_prior.items()},
            "hint": self.hint,
        }

    def copy(self, **kw) -> "Harness":
        return replace(self, **kw)

    def fingerprint(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# --- wording -------------------------------------------------------------

def _plain_q(instr: str, criteria: dict | None) -> dict[str, Any]:
    q = {"type": "noul", "instructions": instr}
    return q


def reword(q: dict[str, Any], wording: str, task: str) -> dict[str, Any]:
    """Apply a wording variant to one question."""
    out = dict(q)
    if out.get("type") == "choice":
        crit = out.get("criteria") or {}
        opts = list(crit.keys())
        if wording == "rule":
            body = ("Pick exactly one option. " + out["instructions"] +
                    " Apply the rule to the facts given and choose the single "
                    "option that follows from them.")
            out["criteria"] = {o: crit.get(o) for o in opts}
            out["instructions"] = body
        elif wording == "terse":
            out["instructions"] = out["instructions"].split(":")[0].strip()
        elif wording == "plain":
            pass
        else:
            raise ValueError(f"unknown wording {wording}")
    else:
        if wording == "rule":
            out["instructions"] = ("Answer true only if the facts given "
                                   "establish this. " + out["instructions"])
        elif wording == "terse":
            out["instructions"] = out["instructions"].split("(")[0].strip()
        elif wording == "plain":
            pass
        else:
            raise ValueError(f"unknown wording {wording}")
    return out


# ==========================================================================
# cases
# ==========================================================================

@dataclass
class Case:
    id: str
    task: str          # scene | defect | tile
    state: str
    questions: dict[str, Any]
    truth: dict[str, Any]
    question_ids: list[str]
    meta: dict[str, Any] = field(default_factory=dict)


def _scene_state(seed: int, with_facts: bool) -> str:
    g, a, b, es = tasks._world(seed)
    base = tasks.scene_state(g, a, b, es)
    if not with_facts:
        return base
    truth = tasks.scene_truth(g, a, b, es)
    lines = [base,
             "Code-computed gate facts (computed from the map, not guessed):"]
    lines.append(f"- agent_xy={list(a)}  beacon_xy={list(b)}")
    if es:
        for i, e in enumerate(es):
            lines.append(f"- enemy_{i+1}: xy={list(e)} "
                         f"chebyshev={tasks._cheb(a, e)} "
                         f"line_of_sight={tasks._los(g, a, e)}")
    else:
        lines.append("- enemies: none")
    lines.append(f"- bfs_steps_to_beacon={truth['path_len']}")
    return "\n".join(lines)


def build_scene_cases(n: int, seed_base: int = 1000) -> list[Case]:
    out = []
    for i in range(n):
        seed = seed_base + i
        g, a, b, es = tasks._world(seed)
        truth = tasks.scene_truth(g, a, b, es)
        qs = {k: v for k, v in tasks.SCENE_QUESTIONS.items()}
        out.append(Case(
            id=f"scene-{seed}", task="scene",
            state=_scene_state(seed, False),
            questions=qs,
            truth={k: truth[k] for k in ("enemy_visible", "action",
                                         "beacon_bearing", "beacon_reachable")},
            question_ids=list(qs.keys()),
            meta={"seed": seed},
        ))
    return out


def build_defect_cases(n: int) -> list[Case]:
    raw = tasks.build_defect_cases()
    out = []
    for c in raw[:n]:
        out.append(Case(
            id=c["id"], task="defect", state=c["state"],
            questions=tasks.DEFECT_QUESTIONS,
            truth={"defect_class": c["truth"]},
            question_ids=["defect_class"],
            meta={"source": c["source"], "layer": c["layer"]},
        ))
    return out


def build_tile_cases(n: int) -> list[Case]:
    raw = tasks.build_tile_cases(n)
    out = []
    for c in raw:
        out.append(Case(
            id=c.id, task="tile", state=c.text,
            questions=tasks.tile_questions(c.options),
            truth={"tile": c.truth},
            question_ids=["tile"],
            meta={"options": c.options},
        ))
    return out


def build_all(n_scene: int = 80, n_defect: int = 60, n_tile: int = 60) -> list[Case]:
    return (build_scene_cases(n_scene)
            + build_defect_cases(n_defect)
            + build_tile_cases(n_tile))


def split_cases(cases: list[Case], frac_calib: float = 0.5,
                seed: int = 20261031) -> tuple[list[Case], list[Case]]:
    """Deterministic calibration/eval split, stratified by task."""
    by_task: dict[str, list[Case]] = {}
    for c in cases:
        by_task.setdefault(c.task, []).append(c)
    calib, ev = [], []
    for task in sorted(by_task):
        lst = by_task[task]
        idx = list(range(len(lst)))
        random.Random(seed + hash(task) % 1000).shuffle(idx)
        cut = int(len(lst) * frac_calib)
        sel = set(idx[:cut])
        for i, c in enumerate(lst):
            (calib if i in sel else ev).append(c)
    return calib, ev


# ==========================================================================
# running a harness
# ==========================================================================

def apply_harness(harness: Harness, case: Case) -> tuple[str, dict[str, Any]]:
    """Return the (state, questions) a harness sends for one case."""
    state = case.state
    if harness.gate_facts and case.task == "scene":
        state = _scene_state(case.meta["seed"], True)
    if harness.hint:
        state = state + "\n" + harness.hint
    qs = {qid: reword(q, harness.wording, case.task)
          for qid, q in case.questions.items()}
    return state, qs


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x < -30:
        return 1e-13
    if x > 30:
        return 1 - 1e-13
    return 1.0 / (1.0 + math.exp(-x))


def decide(harness: Harness, case: Case, answers: dict[str, Any]) -> dict[str, Any]:
    """Turn raw model answers into decisions, under the harness's levers."""
    out: dict[str, Any] = {}
    for qid in case.question_ids:
        a = answers.get(qid) or {}
        if a.get("type") == "noul" or "p" in a and not isinstance(a.get("p"), dict):
            p = float(a.get("p", 0.0))
            cal = harness.calibration.get(qid)
            if cal:
                p = _sigmoid(cal[0] * _logit(p) + cal[1])
            out[qid] = {"type": "noul", "p": p,
                        "answer": p >= harness.threshold}
        else:
            probs = dict(a.get("p") or {})
            prior = harness.choice_prior.get(qid) or {}
            if prior and probs:
                adj = {o: math.log(max(v, 1e-9)) + prior.get(o, 0.0)
                       for o, v in probs.items()}
                m = max(adj.values())
                ex = {o: math.exp(v - m) for o, v in adj.items()}
                s = sum(ex.values())
                probs = {o: v / s for o, v in ex.items()}
            out[qid] = {"type": "choice", "p": probs,
                        "answer": max(probs.items(), key=lambda kv: kv[1])[0]
                        if probs else None}
    return out


def run_harness(harness: Harness, cases: Sequence[Case], client,
                model: str, tag: str = "",
                concurrency: int = 8) -> dict[str, Any]:
    """Ask every case once under one harness. Returns raw + decided answers.

    Concurrency 8 by default: C1 measured zero errors and zero throttle at
    that level for both models, and it keeps a 200-case sweep to seconds.
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(c: Case) -> dict[str, Any]:
        state, qs = apply_harness(harness, c)
        status, answers, ms, raw = client.ask(state, qs, model)
        if status != 200:
            return {"id": c.id, "task": c.task, "status": status,
                    "ms": ms, "error": str(raw)[:200]}
        dec = decide(harness, c, answers)
        return {
            "id": c.id, "task": c.task, "status": 200, "ms": ms,
            "decided": dec,
            "raw_p": {qid: (round(float(answers[qid].get("p", 0.0)), 5)
                             if (answers.get(qid) or {}).get("type") == "noul"
                             else (answers[qid].get("p") or {}))
                      for qid in c.question_ids if qid in answers},
        }

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        per_case = list(ex.map(one, cases))
    return {"harness": harness.to_dict(), "tag": tag, "cases": per_case}


# ==========================================================================
# scoring against the teacher
# ==========================================================================

def _teacher_labels(teacher_run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for c in teacher_run["cases"]:
        if c.get("status") == 200 and c.get("decided"):
            out[c["id"]] = c["decided"]
    return out


def score_against_teacher(student_run: dict[str, Any],
                           teacher: dict[str, dict[str, Any]],
                           cases_by_id: dict[str, Case]) -> dict[str, Any]:
    """Agreement per question and per task, plus accuracy against ground truth."""
    per_q: dict[str, list[int]] = {}
    per_task: dict[str, list[int]] = {}
    truth_hits: dict[str, list[int]] = {}
    n = 0
    for c in student_run["cases"]:
        t = teacher.get(c["id"])
        if t is None or c.get("status") != 200:
            continue
        case = cases_by_id[c["id"]]
        n += 1
        per_task.setdefault(case.task, []).append(1)
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = t.get(qid)
            if a is None or b is None:
                continue
            if a.get("type") == "noul":
                agree = (a["answer"] == b["answer"])
            else:
                agree = (a.get("answer") == b.get("answer"))
            per_q.setdefault(qid, []).append(1 if agree else 0)
            want = case.truth.get(qid)
            if want is not None:
                if a.get("type") == "noul":
                    ok = (a["answer"] == want)
                else:
                    ok = (a.get("answer") == want)
                truth_hits.setdefault(qid, []).append(1 if ok else 0)
    out = {
        "n_cases": n,
        "agreement_overall": (sum(sum(v) for v in per_q.values())
                              / max(1, sum(len(v) for v in per_q.values()))),
        "agreement_by_question": {k: sum(v) / len(v) for k, v in sorted(per_q.items())},
        "agreement_by_task": {},
        "accuracy_by_question": {k: sum(v) / len(v)
                                 for k, v in sorted(truth_hits.items())},
        # The metric that matters for "the teacher calibrates the student":
        # restricted to the questions the teacher gets RIGHT, how often does
        # the student match it?  Agreement on the teacher's mistakes is
        # agreement on noise.
        "agreement_on_teacher_correct": None,
        "student_accuracy_on_teacher_correct": None,
        "n_teacher_correct": 0,
        "teacher_accuracy": None,
    }
    task_tot: dict[str, list[int]] = {}
    for c in student_run["cases"]:
        t = teacher.get(c["id"])
        if t is None or c.get("status") != 200:
            continue
        case = cases_by_id[c["id"]]
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = t.get(qid)
            if a is None or b is None:
                continue
            if a.get("type") == "noul":
                task_tot.setdefault(case.task, []).append(
                    1 if a["answer"] == b["answer"] else 0)
            else:
                task_tot.setdefault(case.task, []).append(
                    1 if a.get("answer") == b.get("answer") else 0)
    out["agreement_by_task"] = {k: sum(v) / len(v)
                                for k, v in sorted(task_tot.items())}

    # teacher-correct subset
    tc_agree: list[int] = []
    tc_student: list[int] = []
    tc_total = 0
    tc_teacher_right = 0
    for c in student_run["cases"]:
        t = teacher.get(c["id"])
        if t is None or c.get("status") != 200:
            continue
        case = cases_by_id[c["id"]]
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = t.get(qid)
            if a is None or b is None:
                continue
            want = case.truth.get(qid)
            tc_total += 1
            teacher_ok = None
            if want is not None:
                teacher_ok = (b["answer"] == want) if b.get("type") == "noul" \
                    else (b.get("answer") == want)
            if teacher_ok is True:
                tc_teacher_right += 1
                same = (a["answer"] == b["answer"]) if a.get("type") == "noul" \
                    else (a.get("answer") == b.get("answer"))
                tc_agree.append(1 if same else 0)
                student_ok = (a["answer"] == want) if a.get("type") == "noul" \
                    else (a.get("answer") == want)
                tc_student.append(1 if student_ok else 0)
    if tc_agree:
        out["agreement_on_teacher_correct"] = sum(tc_agree) / len(tc_agree)
        out["student_accuracy_on_teacher_correct"] = sum(tc_student) / len(tc_student)
        out["n_teacher_correct"] = len(tc_agree)
    if tc_total:
        out["teacher_accuracy"] = tc_teacher_right / tc_total
    return out


# ==========================================================================
# fitting the levers on the calibration split
# ==========================================================================

def fit_threshold(cases: Sequence[Case], student_run: dict[str, Any],
                  teacher: dict[str, dict[str, Any]],
                  default: float = 0.5) -> float:
    """One global threshold for booleans, best agreement on the calibration split."""
    best, best_t = -1.0, default
    grid = [i / 100.0 for i in range(5, 96, 5)]
    for t in grid:
        hits = 0
        total = 0
        for c in student_run["cases"]:
            tl = teacher.get(c["id"])
            if tl is None or c.get("status") != 200:
                continue
            case = next((x for x in cases if x.id == c["id"]), None)
            if case is None:
                continue
            for qid in case.question_ids:
                a = (c.get("decided") or {}).get(qid)
                b = tl.get(qid)
                if a is None or b is None or a.get("type") != "noul":
                    continue
                total += 1
                hits += 1 if (a["p"] >= t) == b["answer"] else 0
        if total and hits / total > best:
            best, best_t = hits / total, t
    return best_t


def fit_per_question_threshold(cases: Sequence[Case], student_run: dict[str, Any],
                               teacher: dict[str, dict[str, Any]],
                               default: float = 0.5) -> dict[str, float]:
    out = {}
    by_id = {c.id: c for c in cases}
    qids = set()
    for c in student_run["cases"]:
        case = by_id.get(c["id"])
        if case is not None:
            qids.update(case.question_ids)
    qs = sorted(qids)
    for qid in qs:
        best, best_t = -1.0, default
        for t in [i / 100.0 for i in range(5, 96, 5)]:
            hits = total = 0
            for c in student_run["cases"]:
                tl = teacher.get(c["id"])
                if tl is None or c.get("status") != 200:
                    continue
                a = (c.get("decided") or {}).get(qid)
                b = (tl or {}).get(qid)
                if a is None or b is None or a.get("type") != "noul":
                    continue
                total += 1
                hits += 1 if (a["p"] >= t) == b["answer"] else 0
            if total and hits / total > best:
                best, best_t = hits / total, t
        out[qid] = best_t
    return out


def fit_platt(cases: Sequence[Case], student_run: dict[str, Any],
              teacher: dict[str, dict[str, Any]],
              rounds: int = 400, lr: float = 0.08) -> dict[str, list[float]]:
    """Per-boolean Platt scaling p' = sigmoid(a*logit(p)+b) on teacher labels."""
    by_id = {c.id: c for c in cases}
    data: dict[str, list[tuple[float, int]]] = {}
    for c in student_run["cases"]:
        tl = teacher.get(c["id"])
        if tl is None or c.get("status") != 200:
            continue
        case = by_id.get(c["id"])
        if case is None:
            continue
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = (tl or {}).get(qid)
            if a is None or b is None or a.get("type") != "noul":
                continue
            data.setdefault(qid, []).append(
                (_logit(float(a["p"])), 1 if b["answer"] else 0))
    out: dict[str, list[float]] = {}
    for qid, pts in data.items():
        if len(pts) < 8:
            continue
        a, b = 1.0, 0.0
        for _ in range(rounds):
            ga = gb = 0.0
            for z, y in pts:
                p = _sigmoid(a * z + b)
                d = p - y
                ga += d * z
                gb += d
            ga /= len(pts); gb /= len(pts)
            a -= lr * ga
            b -= lr * gb
            a = max(0.05, min(20.0, a))
            b = max(-8.0, min(8.0, b))
        out[qid] = [a, b]
    return out


def fit_choice_prior(cases: Sequence[Case], student_run: dict[str, Any],
                      teacher: dict[str, dict[str, Any]],
                      rounds: int = 300, lr: float = 0.25) -> dict[str, dict[str, float]]:
    """Per-option additive log-prior for choice questions, fitted on the teacher."""
    by_id = {c.id: c for c in cases}
    data: dict[str, list[tuple[dict[str, float], str]]] = {}
    for c in student_run["cases"]:
        tl = teacher.get(c["id"])
        if tl is None or c.get("status") != 200:
            continue
        case = by_id.get(c["id"])
        if case is None:
            continue
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = (tl or {}).get(qid)
            if a is None or b is None or a.get("type") != "choice":
                continue
            probs = a.get("p") or {}
            if not probs:
                continue
            data.setdefault(qid, []).append((probs, b.get("answer")))
    out: dict[str, dict[str, float]] = {}
    for qid, pts in data.items():
        if len(pts) < 8:
            continue
        opts = sorted({o for p, _ in pts for o in p})
        w = {o: 0.0 for o in opts}
        for _ in range(rounds):
            grad = {o: 0.0 for o in opts}
            for probs, target in pts:
                adj = {o: math.log(max(probs.get(o, 1e-9), 1e-9)) + w.get(o, 0.0)
                       for o in opts}
                m = max(adj.values())
                ex = {o: math.exp(v - m) for o, v in adj.items()}
                s = sum(ex.values())
                for o in opts:
                    grad[o] += ex[o] / s
                grad[target] = grad.get(target, 0.0) - 1.0
            for o in opts:
                w[o] -= lr * grad[o] / len(pts)
        out[qid] = w
    return out
