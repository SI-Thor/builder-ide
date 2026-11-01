#!/usr/bin/env python3
"""Compare two decision servers on the same workload.

The score that matters is ``agreement_with_llamacpp_top1``: the fraction
of questions where the two servers pick the same answer. The
probability vectors are compared too, so a disagreement can be told
apart from a different calibration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.client import DecisionClient  # noqa: E402
from d1dec.workload import read_workload  # noqa: E402


def top1(answer: dict) -> str | None:
    """The answer of one question, as a comparable string.

    * a choice is the option that was picked;
    * a score is the level, as an integer (llama.cpp returns it as a
      double, so it is normalised here);
    * a noul has no "choice" key at all — it is the probability of the
      true option — so its answer is which side of one half it fell on.
    """
    if not answer:
        return None
    t = answer.get("type")
    if t == "choice":
        return f"choice:{answer.get('choice')}"
    if t == "score":
        return f"score:{int(round(float(answer.get('score', -1))))}"
    if t == "noul":
        p = float(answer.get("noul", 0.0))
        return f"noul:{'true' if p >= 0.5 else 'false'}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="http://127.0.0.1:8137")
    ap.add_argument("--ours", default="http://127.0.0.1:8138")
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--n", type=int, default=0, help="0 = all packs")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    packs = read_workload(Path(args.workload))
    if args.n:
        packs = packs[: args.n]

    base = DecisionClient(args.baseline)
    ours = DecisionClient(args.ours)
    for c in (base, ours):
        if not c.health():
            print(f"server {c.base_url} is not healthy", file=sys.stderr)
            sys.exit(2)

    n = 0
    agree = 0
    by_type: dict[str, list[int]] = {}
    max_diff = 0.0
    sum_diff = 0.0
    disagreements = []
    for pack in packs:
        body = {"state": pack["state"], "questions": pack["questions"]}
        a, _, _ = base.ask_pack(body)
        b, _, _ = ours.ask_pack(body)
        for qid in pack["questions"]:
            if qid not in a or qid not in b:
                continue
            n += 1
            ta, tb = top1(a[qid]), top1(b[qid])
            kind = (a[qid] or {}).get("type", "?")
            ok = ta == tb
            by_type.setdefault(kind, []).append(1 if ok else 0)
            if ok:
                agree += 1
            else:
                disagreements.append(
                    {
                        "pack": pack["char_id"],
                        "qid": qid,
                        "type": kind,
                        "baseline": a[qid],
                        "ours": b[qid],
                    }
                )
            pa = (a[qid] or {}).get("probabilities") or {}
            pb = (b[qid] or {}).get("probabilities") or {}
            for k in pa:
                if k in pb:
                    d = abs(pa[k] - pb[k])
                    max_diff = max(max_diff, d)
                    sum_diff += d

    out = {
        "questions": n,
        "agreement_with_llamacpp_top1": agree / n if n else 0.0,
        "by_type": {k: (sum(v) / len(v), len(v)) for k, v in by_type.items()},
        "max_prob_abs_diff": max_diff,
        "mean_prob_abs_diff": sum_diff / n if n else 0.0,
        "n_disagreements": len(disagreements),
        "disagreements": disagreements[:20],
    }
    text = json.dumps(out, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
