#!/usr/bin/env python3
"""How much do llama.cpp's own answers move between two runs?

The agreement with our server is 99.09%, and every disagreement is a
question where the two leading options are within 0.4% of each other.
That is only a fair thing to report if the *baseline* moves by about as
much on those questions — otherwise the disagreements could still be a
difference in the arithmetic.

So: ask the same server the same workload twice, and compare its
answers with itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from d1dec.client import DecisionClient  # noqa: E402


def top1(answer: dict) -> str:
    kind = answer.get("type")
    if kind == "choice":
        return str(answer.get("choice"))
    if kind == "score":
        return str(answer.get("score"))
    if kind == "noul":
        return "true" if float(answer.get("noul", 0.0)) >= 0.5 else "false"
    return "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8137")
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--out", default="results/baseline_self_stability.json")
    args = ap.parse_args()

    packs = [json.loads(line) for line in Path(args.workload).read_text().splitlines() if line]
    client = DecisionClient(args.server)

    runs = []
    for _ in range(2):
        answers = []
        for pack in packs:
            got, _, _ = client.ask_pack(
                {"state": pack["state"], "questions": pack["questions"]}
            )
            answers.append(got)
        runs.append(answers)

    n = 0
    flips = []
    for i, (a, b) in enumerate(zip(*runs)):
        for qid in a:
            if qid not in b:
                continue
            n += 1
            if top1(a[qid]) != top1(b[qid]):
                flips.append(
                    {
                        "pack": packs[i].get("id", str(i)),
                        "qid": qid,
                        "run1": top1(a[qid]),
                        "run2": top1(b[qid]),
                    }
                )

    out = {
        "server": args.server,
        "questions": n,
        "self_flips": len(flips),
        "self_stability": 1.0 - len(flips) / max(1, n),
        "flips": flips[:20],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
