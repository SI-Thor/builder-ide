"""C3 -- the teacher calibrates the student, until agreement plateaus.

Casey's idea: "Clef-27B (cloud) labels a task set; tune Clef-flash's harness
(question wording, gate facts computed by code, thresholds, a calibration
map for the biased booleans) until its agreement with the teacher plateaus.
Report the curve."

So: the teacher labels once, the student is re-harnessed one lever at a
time, and every round is measured on a held-out split the fitting never
touches.  The curve is the agreement between student and teacher as the
harness gets more levers.

Teacher labels are fixed for the whole run.  Every lever is fitted on the
calibration split only; the eval split is where the curve is read.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascade
from cascade import Harness, build_all, split_cases
from decision_client import ClefAI, DecisionClient, MODELS

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)


def accuracy_vs_truth(run: dict, cases_by_id: dict) -> dict:
    hits: dict[str, list[int]] = {}
    by_task: dict[str, list[int]] = {}
    for c in run["cases"]:
        case = cases_by_id.get(c["id"])
        if case is None or c.get("status") != 200:
            continue
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            want = case.truth.get(qid)
            if a is None or want is None:
                continue
            ok = (a["answer"] == want) if a.get("type") == "noul" else \
                 (a.get("answer") == want)
            hits.setdefault(qid, []).append(1 if ok else 0)
            by_task.setdefault(case.task, []).append(1 if ok else 0)
    return {
        "accuracy_overall": (sum(sum(v) for v in hits.values())
                              / max(1, sum(len(v) for v in hits.values()))),
        "accuracy_by_question": {k: sum(v) / len(v) for k, v in sorted(hits.items())},
        "accuracy_by_task": {k: sum(v) / len(v) for k, v in sorted(by_task.items())},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c3-calibration.json")
    ap.add_argument("--scenes", type=int, default=80)
    ap.add_argument("--defects", type=int, default=60)
    ap.add_argument("--tiles", type=int, default=60)
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    ap.add_argument("--max-neurons", type=float, default=12000.0)
    ap.add_argument("--splits", type=int, default=2,
                    help="run the whole ladder on this many independent "
                         "calibration/eval splits, so the curve is not split noise")
    args = ap.parse_args()

    backend = ClefAI(url=args.url)
    student = DecisionClient(backend, MODELS["flash"])
    teacher = DecisionClient(backend, MODELS["clef27"])
    cases = build_all(args.scenes, args.defects, args.tiles)
    by_id = {c.id: c for c in cases}
    print(f"cases={len(cases)}")

    t0 = time.perf_counter()
    log: list[dict] = []
    all_curves = []
    teacher_runs = []

    # ---- the teacher labels everything once --------------------------
    teacher_harness = Harness(name="teacher")
    teacher_run = cascade.run_harness(teacher_harness, cases, teacher,
                                      MODELS["clef27"], tag="teacher")
    teacher_map = cascade._teacher_labels(teacher_run)
    teacher_acc = accuracy_vs_truth(teacher_run, by_id)
    teacher_runs.append(teacher_run)
    print(f"teacher labelled {len(teacher_map)}/{len(cases)} cases; "
          f"teacher accuracy vs ground truth = {teacher_acc['accuracy_overall']:.4f} "
          f"by task {teacher_acc['accuracy_by_task']}")

    # ---- the ladder, on each split -----------------------------------
    for split_idx in range(args.splits):
        split_seed = 20261031 + split_idx * 7919
        calib, ev = split_cases(cases, 0.5, seed=split_seed)
        print(f"\n=== split {split_idx} (seed {split_seed}): "
              f"calib={len(calib)} eval={len(ev)} ===")
        rounds: list[dict] = []

        def evaluate(h: Harness, tag: str, split: list[cascade.Case]) -> dict:
            run = cascade.run_harness(h, split, student, MODELS["flash"], tag=tag)
            sc = cascade.score_against_teacher(run, teacher_map, by_id)
            ac = accuracy_vs_truth(run, by_id)
            row = {"tag": tag, "harness": h.to_dict(),
                   "split": "eval" if split is ev else "calib",
                   "agreement": sc["agreement_overall"],
                   "agreement_on_teacher_correct":
                       sc.get("agreement_on_teacher_correct"),
                   "student_accuracy_on_teacher_correct":
                       sc.get("student_accuracy_on_teacher_correct"),
                   "agreement_by_task": sc["agreement_by_task"],
                   "agreement_by_question": sc["agreement_by_question"],
                   "accuracy": ac["accuracy_overall"],
                   "accuracy_by_task": ac["accuracy_by_task"],
                   "accuracy_by_question": ac["accuracy_by_question"],
                   "n_cases": sc["n_cases"]}
            rounds.append(row)
            log.append({"split": split_idx, "tag": tag,
                        "harness": h.to_dict(), "run": run})
            print(f"  {tag:28s} agree={row['agreement']:.4f} "
                  f"agree|teacher-right="
                  f"{(row['agreement_on_teacher_correct'] or 0):.4f} "
                  f"acc={row['accuracy']:.4f} "
                  f"by_task={ {k: round(v,3) for k,v in row['agreement_by_task'].items()} }",
                  flush=True)
            return row

        print("ladder (eval split):")
        h = Harness(name="R0 baseline")
        evaluate(h, "R0 baseline", ev)

        h1 = h.copy(gate_facts=True, name="R1 +gate facts")
        evaluate(h1, "R1 +gate facts", ev)

        print("\nwording probe (calibration split):")
        best_wording, best_agree = "plain", -1.0
        for w in cascade.WORDINGS:
            probe = h1.copy(wording=w, name=f"probe {w}")
            row = evaluate(probe, f"probe wording={w}", calib)
            if row["agreement"] > best_agree:
                best_agree, best_wording = row["agreement"], w
        print(f"  best wording on calib: {best_wording} ({best_agree:.4f})")
        h2 = h1.copy(wording=best_wording, name=f"R2 +wording({best_wording})")
        evaluate(h2, f"R2 +wording({best_wording})", ev)

        calib_run = cascade.run_harness(h2, calib, student, MODELS["flash"],
                                        tag="R2 calib")
        thr = cascade.fit_threshold(calib, calib_run, teacher_map)
        h3 = h2.copy(threshold=thr, name=f"R3 +threshold({thr})")
        print(f"  threshold fitted on calib: {thr}")
        evaluate(h3, f"R3 +threshold({thr})", ev)

        prior = cascade.fit_choice_prior(calib, calib_run, teacher_map)
        h4 = h3.copy(choice_prior=prior, name="R4 +choice prior")
        evaluate(h4, "R4 +choice prior", ev)

        platt = cascade.fit_platt(calib, calib_run, teacher_map)
        h5 = h4.copy(calibration=platt, name="R5 +platt map")
        print(f"  platt map fitted for {len(platt)} boolean questions")
        evaluate(h5, "R5 +platt map", ev)

        calib_run5 = cascade.run_harness(h5, calib, student, MODELS["flash"],
                                         tag="R5 calib")
        thr2 = cascade.fit_threshold(calib, calib_run5, teacher_map)
        h6 = h5.copy(threshold=thr2, name=f"R6 +rethreshold({thr2})")
        print(f"  threshold re-fitted on calib after calibration: {thr2}")
        evaluate(h6, f"R6 +rethreshold({thr2})", ev)

        # R7/R8: does anything more come out of the same levers?
        h7 = h6.copy(calibration=platt, threshold=thr2,
                     name="R7 +refit everything")
        calib_run7 = cascade.run_harness(h7, calib, student, MODELS["flash"],
                                         tag="R7 calib")
        h7 = h7.copy(calibration=cascade.fit_platt(calib, calib_run7, teacher_map),
                     choice_prior=cascade.fit_choice_prior(calib, calib_run7,
                                                           teacher_map),
                     threshold=cascade.fit_threshold(calib, calib_run7,
                                                     teacher_map))
        evaluate(h7, "R7 refit everything", ev)

        h8 = h7.copy(gate_facts=not h7.gate_facts, name="R8 toggle gate facts")
        evaluate(h8, "R8 toggle gate facts off", ev)

        curve = [{"round": r["tag"], "harness": r["harness"],
                  "agreement": r["agreement"],
                  "agreement_on_teacher_correct":
                      r["agreement_on_teacher_correct"],
                  "accuracy": r["accuracy"],
                  "agreement_by_task": r["agreement_by_task"],
                  "accuracy_by_task": r["accuracy_by_task"]}
                 for r in rounds if r["split"] == "eval"]
        all_curves.append({"split": split_idx, "split_seed": split_seed,
                           "curve": curve, "rounds_all": rounds})

    neurons = backend.total_neurons
    out = {
        "experiment": "C3 teacher calibrates student",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "teacher_model": MODELS["clef27"], "student_model": MODELS["flash"],
        "n_cases": len(cases),
        "splits": all_curves,
        "teacher_accuracy_vs_truth": teacher_acc,
        "neurons_total": round(neurons, 2),
        "usd_total": round(neurons / 1000 * 0.011, 6),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))
    (RESULTS / (args.out.replace(".json", "") + "-runs.json")).write_text(
        json.dumps({"runs": log, "teacher": teacher_runs}, indent=1))

    print("\ncurves:")
    for sp in all_curves:
        print(f" split {sp['split']}:")
        for row in sp["curve"]:
            print(f"  {row['round']:28s} agreement={row['agreement']:.4f} "
                  f"agree|teacher-right="
                  f"{(row['agreement_on_teacher_correct'] or 0):.4f} "
                  f"accuracy={row['accuracy']:.4f}")
    print(f"\nneurons={neurons:.1f} usd={out['usd_total']} "
          f"wall={out['wall_s']}s -> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
