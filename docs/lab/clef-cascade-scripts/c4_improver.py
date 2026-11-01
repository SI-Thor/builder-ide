"""C4 -- the cloud improver.

Casey's brief: "every N rounds, a cloud LLM (your own seat) proposes harness
edits; keep an edit only if the paired score improves. Log every edit with
its win or loss."

So this is the tiles idea applied to the harness itself.  The loop:

  1. score the current harness on the eval split (the paired score: the
     same cases, the same teacher labels, every time)
  2. keep the edit if the score improved, revert it if not
  3. hand the cloud LLM the failures -- the cases where the student
     disagreed with the teacher, with both answers -- and ask for a new
     harness edit as JSON
  4. repeat

The LLM's editable surface is semantic: wording, gate facts, the boolean
threshold, a free-text hint, and two switches that ask the code to re-fit
the calibration map and the choice prior on the calibration split.  The
cloud LLM never writes fitted numbers itself; it says *what* to fit.

Every proposal is logged with its win or loss, whether it was kept, and
why.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascade
from cascade import Harness, build_all, split_cases
from decision_client import ClefAI, DecisionClient, MODELS

RESULTS = Path(__file__).resolve().parent.parent / "results"
RESULTS.mkdir(exist_ok=True)

SYSTEM = (
    "You are tuning a decision-model harness for a small model (Clef-flash, "
    "9B) so that it agrees with a larger teacher model (Clef, 27B) on typed "
    "yes/no and multiple-choice questions. The harness levers are:\n"
    "  wording: 'plain' | 'rule' | 'terse' -- how each question is phrased.\n"
    "  gate_facts: true | false -- whether code-computed gate facts are "
    "placed in the state next to the question.\n"
    "  threshold: a number in (0,1) -- the probability at which a yes/no "
    "answer is called true. Or the string 'fit' to let the code re-fit it on "
    "the calibration split.\n"
    "  hint: a short string (max 300 chars) appended to the state, or "
    "empty. Use it for a rule the model keeps missing.\n"
    "  fit_platt: true | false -- re-fit the per-question calibration map "
    "(p' = sigmoid(a*logit(p)+b)) on the calibration split.\n"
    "  fit_choice_prior: true | false -- re-fit per-option priors for "
    "multiple-choice questions on the calibration split.\n"
    "Answer with ONE JSON object and nothing else, no prose, no markdown "
    "fence. Keys: wording, gate_facts, threshold, hint, fit_platt, "
    "fit_choice_prior, reason (a short sentence naming the failure you "
    "target). Change at most one lever from the current harness so the "
    "effect of each edit is attributable."
)

FEEDBACK = """\
Current harness:
{harness}

Current score on the held-out split:
  agreement with teacher = {agreement:.4f}
  accuracy vs ground truth = {accuracy:.4f}
  agreement by task = {by_task}

Agreement by question:
{by_question}

Here are cases where the student disagreed with the teacher. For each: the
state the student saw, the teacher's answer, the student's answer.

{failures}

Propose the single most promising harness edit. Return only the JSON object.
"""


def build_failure_text(cases_by_id, student_run, teacher_map, limit: int = 6) -> str:
    out = []
    for c in student_run["cases"]:
        tl = teacher_map.get(c["id"])
        if tl is None or c.get("status") != 200:
            continue
        case = cases_by_id.get(c["id"])
        if case is None:
            continue
        wrong = []
        for qid in case.question_ids:
            a = (c.get("decided") or {}).get(qid)
            b = (tl or {}).get(qid)
            if a is None or b is None:
                continue
            if a.get("type") == "noul":
                if a["answer"] != b["answer"]:
                    wrong.append(f"{qid}: teacher said {b['answer']}, "
                                 f"student said {a['answer']} (p={a['p']:.3f})")
            else:
                if a.get("answer") != b.get("answer"):
                    wrong.append(f"{qid}: teacher said {b.get('answer')}, "
                                 f"student said {a.get('answer')} "
                                 f"(probs={ {k: round(v,3) for k,v in (a.get('p') or {}).items()} })")
        if wrong:
            out.append(f"--- {c['id']} ({case.task}) ---\n"
                       f"state: {case.state[:420]}\n"
                       + "\n".join(wrong))
        if len(out) >= limit:
            break
    return "\n\n".join(out) if out else "(no failures on the held-out split)"


def parse_proposal(text: str) -> dict | None:
    """Pull one JSON object out of a reply, however the model wrapped it."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        for p in parts[1:]:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                d = json.loads(p)
                if isinstance(d, dict):
                    return d
            except Exception:
                continue
    # a whole-object parse
    try:
        d = json.loads(t)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    # balanced-brace scan, longest first
    for start in range(len(t)):
        if t[start] != "{":
            continue
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    frag = t[start:i + 1]
                    try:
                        d = json.loads(frag)
                        if isinstance(d, dict) and d:
                            return d
                    except Exception:
                        try:
                            d = json.loads(frag.replace(",}", "}").replace(",]", "]"))
                            if isinstance(d, dict) and d:
                                return d
                        except Exception:
                            pass
                    break
    return None


def apply_proposal(h: Harness, prop: dict, fit_platt_fn, fit_prior_fn,
                   fit_threshold_fn, calib, calib_run, teacher) -> tuple[Harness, list[str]]:
    """Turn a proposal into a new harness. Returns (harness, notes)."""
    nh = h.copy()
    notes = []
    if prop.get("wording") in cascade.WORDINGS and prop["wording"] != h.wording:
        nh.wording = prop["wording"]
        notes.append(f"wording {h.wording} -> {nh.wording}")
    if isinstance(prop.get("gate_facts"), bool) and prop["gate_facts"] != h.gate_facts:
        nh.gate_facts = prop["gate_facts"]
        notes.append(f"gate_facts {h.gate_facts} -> {nh.gate_facts}")
    thr = prop.get("threshold")
    if thr == "fit":
        new_thr = fit_threshold_fn(calib, calib_run, teacher)
        if abs(new_thr - h.threshold) > 1e-9:
            nh.threshold = new_thr
            notes.append(f"threshold refit on calib -> {new_thr}")
    if thr is not None and thr != "fit":
        try:
            v = float(thr)
            if 0.0 < v < 1.0 and abs(v - h.threshold) > 1e-9:
                nh.threshold = v
                notes.append(f"threshold {h.threshold} -> {v}")
        except (TypeError, ValueError):
            pass
    hint = prop.get("hint")
    if isinstance(hint, str) and hint.strip() != h.hint:
        nh.hint = hint.strip()[:300]
        notes.append("hint set")
    if prop.get("fit_platt") and not h.calibration:
        nh.calibration = fit_platt_fn(calib, calib_run, teacher)
        notes.append(f"platt map fitted ({len(nh.calibration)} questions)")
    if prop.get("fit_choice_prior") and not h.choice_prior:
        nh.choice_prior = fit_prior_fn(calib, calib_run, teacher)
        notes.append(f"choice prior fitted ({len(nh.choice_prior)} questions)")
    return nh, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="c4-improver.json")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--scenes", type=int, default=80)
    ap.add_argument("--defects", type=int, default=60)
    ap.add_argument("--tiles", type=int, default=60)
    ap.add_argument("--url", default="http://127.0.0.1:8797")
    ap.add_argument("--provider", default="minimax")
    ap.add_argument("--model", default="MiniMax-M3.1-Flash")
    args = ap.parse_args()

    from cloud_thor import CloudLLM
    llm = CloudLLM(provider=args.provider, model=args.model)

    backend = ClefAI(url=args.url)
    student = DecisionClient(backend, MODELS["flash"])
    teacher = DecisionClient(backend, MODELS["clef27"])

    cases = build_all(args.scenes, args.defects, args.tiles)
    calib, ev = split_cases(cases, 0.5)
    by_id = {c.id: c for c in cases}

    # teacher labels, fixed for the whole run
    teacher_run = cascade.run_harness(Harness(name="teacher"), cases, teacher,
                                      MODELS["clef27"], tag="teacher")
    teacher_map = cascade._teacher_labels(teacher_run)

    def score(h: Harness, split, tag):
        run = cascade.run_harness(h, split, student, MODELS["flash"], tag=tag)
        sc = cascade.score_against_teacher(run, teacher_map, by_id)
        ac = c_accuracy(run, by_id)
        return run, sc, ac

    def c_accuracy(run, by_id):
        hits: list[int] = []
        for c in run["cases"]:
            case = by_id.get(c["id"])
            if case is None or c.get("status") != 200:
                continue
            for qid in case.question_ids:
                a = (c.get("decided") or {}).get(qid)
                want = case.truth.get(qid)
                if a is None or want is None:
                    continue
                hits.append(1 if a.get("answer") == want else 0)
        return sum(hits) / max(1, len(hits))

    current = Harness(name="R0 baseline")
    run, sc, acc = score(current, ev, "round0")
    best_score = sc["agreement_overall"]
    best_harness = current
    best_run, best_sc, best_acc = run, sc, acc
    print(f"round 0 (baseline): agreement={best_score:.4f} accuracy={acc:.4f}")

    edits = []
    curve = [{"round": 0, "harness": current.to_dict(),
              "agreement": sc["agreement_overall"], "accuracy": acc,
              "agreement_by_task": sc["agreement_by_task"]}]

    for r in range(1, args.rounds + 1):
        prompt = FEEDBACK.format(
            harness=json.dumps(current.to_dict(), indent=1),
            agreement=sc["agreement_overall"],
            accuracy=acc,
            by_task=json.dumps({k: round(v, 3) for k, v in
                                sc["agreement_by_task"].items()}),
            by_question=json.dumps({k: round(v, 3) for k, v in
                                    sc["agreement_by_question"].items()}),
            failures=build_failure_text(by_id, run, teacher_map),
        )
        resp = llm.call(SYSTEM + "\n\n" + prompt, max_tokens=4000,
                        temperature=0.2)
        text = resp.get("text", "") or ""
        prop = parse_proposal(text)
        if prop is None:
            # one strict retry: the reply was prose, not an object
            resp2 = llm.call(
                SYSTEM + "\n\n" + prompt +
                "\n\nYour previous reply could not be parsed as one JSON "
                "object. Reply with the JSON object and nothing else.",
                max_tokens=4000, temperature=0.0)
            text2 = resp2.get("text", "") or ""
            prop = parse_proposal(text2)
            resp["text"] = (text[:600] + " || RETRY || " + text2[:600])
            resp["ms"] = resp.get("ms", 0) + resp2.get("ms", 0)
        entry = {"round": r, "llm_ms": round(resp.get("ms", 0)),
                 "llm_credential": resp.get("credential_source"),
                 "raw_reply": (resp.get("text", "") or "")[:1200],
                 "proposal": prop, "kept": False, "reason": "",
                 "notes": []}
        if prop is None:
            entry["reason"] = "could not parse a proposal from the cloud LLM"
            edits.append(entry)
            print(f"round {r}: NO PROPOSAL ({entry['reason']})")
            continue

        calib_run = cascade.run_harness(current, calib, student,
                                        MODELS["flash"], tag=f"calib-r{r}")
        proposal, notes = apply_proposal(
            current, prop, cascade.fit_platt, cascade.fit_choice_prior,
            cascade.fit_threshold, calib, calib_run, teacher_map)
        entry["notes"] = notes
        proposal.name = f"r{r}-proposal"
        if not notes:
            entry["reason"] = "the proposal changed nothing"
            edits.append(entry)
            print(f"round {r}: proposal was a no-op")
            continue

        new_run, new_sc, new_acc = score(proposal, ev, f"round{r}")
        entry["new_harness"] = proposal.to_dict()
        entry["new_agreement"] = new_sc["agreement_overall"]
        entry["new_accuracy"] = new_acc
        entry["delta_agreement"] = new_sc["agreement_overall"] - sc["agreement_overall"]
        if new_sc["agreement_overall"] > best_score + 1e-9:
            entry["kept"] = True
            entry["reason"] = (f"paired score improved "
                               f"{sc['agreement_overall']:.4f} -> "
                               f"{new_sc['agreement_overall']:.4f}")
            current, run, sc, acc = proposal, new_run, new_sc, new_acc
            best_score = new_sc["agreement_overall"]
            best_harness = proposal
            best_run, best_sc, best_acc = new_run, new_sc, new_acc
        else:
            entry["reason"] = (f"paired score did not improve "
                               f"({sc['agreement_overall']:.4f} -> "
                               f"{new_sc['agreement_overall']:.4f}); reverted")
        edits.append(entry)
        curve.append({"round": r, "harness": current.to_dict(),
                      "agreement": sc["agreement_overall"], "accuracy": acc,
                      "agreement_by_task": sc["agreement_by_task"],
                      "kept": entry["kept"],
                      "new_agreement": entry["new_agreement"]})
        print(f"round {r}: agreement {sc['agreement_overall']:.4f} -> "
              f"{entry['new_agreement']:.4f} kept={entry['kept']} "
              f"({'; '.join(notes)})")

    out = {
        "experiment": "C4 cloud improver",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cloud_llm": f"{args.provider}/{args.model}",
        "student_model": MODELS["flash"], "teacher_model": MODELS["clef27"],
        "n_cases": len(cases), "n_calib": len(calib), "n_eval": len(ev),
        "rounds": args.rounds,
        "curve": curve,
        "edits": edits,
        "best_harness": best_harness.to_dict(),
        "best_agreement": best_score,
        "best_accuracy": best_acc,
        "neurons_total": round(backend.total_neurons, 2),
        "usd_total": round(backend.total_neurons / 1000 * 0.011, 6),
    }
    (RESULTS / args.out).write_text(json.dumps(out, indent=1))

    print("\nedits:")
    for e in edits:
        print(f"  round {e['round']}: kept={e['kept']} "
              f"agreement={e.get('new_agreement')} :: {e['reason']}")
    print(f"\nbest agreement {best_score:.4f} accuracy {best_acc:.4f}")
    print(f"neurons={backend.total_neurons:.1f} -> results/{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
