"""The routed cell, end to end: the fixed states through the shipped judge seam.

**What this is.** §8.3 of the calibration note routes this cell to the
d1-3B. This script applies the routing and measures the cell end to end —
not through a lab reimplementation of the gate, but through the
repository's own seam: `core.judge.judge.Judge` over `D1Backend` on the
routed model, the `ConfidencePolicy` with the shipped `CALIBRATED_TAUS`
(τ resolved per ask, its provenance stamped from the policy), every
attempt a `judge.verdict` row in a ledger.

**What the operator would see.** Per step: the fixed recorder's state, the
routed model's distribution over A–E, the canonical confidence, and the
gate's word. On a one-rung ladder a below-τ judgment reads `surfaced` —
the ladder's end is surfaced rows, and acting on one is the caller's
decision — so the run reports the surfaced share, the errors the gate
caught and the right answers it taxed at the policy's τ, and the same walk
on the note's τ grid (computed offline from the recorded judgments, the
sweep's rule).

**Usage** (on the Thor, with the routed model served):

    python3 route_end_to_end.py --model d1-3B --port 8320 \
        --out results/routed-end-to-end-d1-3B.json
    python3 route_end_to_end.py --model d1-2B --port 8094 \
        --out results/routed-end-to-end-d1-2B.json

240 asks a model, one per step of the fixed recording.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from core.judge.backends import D1Backend  # noqa: E402
from core.judge.gate import SEA_STATE_TASK  # noqa: E402
from core.judge.judge import Judge, fold_judgments  # noqa: E402
from core.judge.models import Question  # noqa: E402
from core.night.ledger import InMemoryLedger  # noqa: E402

from recorder import KEYS, QUESTIONS, build_trials  # noqa: E402

#: the τ grid the note reads the gate on (0.76 is the shipped 3B τ restated
#: into the top-probability space, the shipped table's value).
TAUS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.76, 0.8, 0.9)


def question_of() -> Question:
    """The recorder's one question, as the seam's typed `choice`."""
    return Question(
        qid="sea",
        kind="choice",
        instructions=QUESTIONS["instructions"],
        criteria=dict(QUESTIONS["criteria"]),
    )


def gate_at(pairs: list[tuple[float, bool]], tau: float) -> dict[str, Any]:
    """Catch and tax at one τ, the note's semantics (escalate below τ)."""
    wrong = [pair for pair in pairs if not pair[1]]
    right = [pair for pair in pairs if pair[1]]
    escalated = [pair for pair in pairs if pair[0] < tau]
    return {
        "tau": tau,
        "escalated": len(escalated),
        "act_share": round(len(escalated) / len(pairs), 4) if pairs else None,
        "catch": round(sum(1 for pair in escalated if not pair[1]) / len(wrong), 4)
        if wrong
        else 0.0,
        "tax": round(sum(1 for pair in escalated if pair[1]) / len(right), 4)
        if right
        else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    out_path = args.out or (RESULTS / f"routed-end-to-end-{args.model}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trials = build_trials()
    steps = [row for trial in trials for row in trial]
    question = question_of()

    ledger = InMemoryLedger()
    judge = Judge(
        backend=D1Backend(port=args.port, model=args.model, timeout=args.timeout),
        ledger=ledger,
    )
    tau_source = judge.policy.source_for("d1", args.model, SEA_STATE_TASK)
    print(
        f"routed run: {args.model} on {args.port}; "
        f"policy tau_source={tau_source!r} from the shipped table",
        flush=True,
    )

    rows: list[dict[str, Any]] = []

    def assemble(complete: bool) -> dict[str, Any]:
        pairs = [(row["confidence"], row["right"]) for row in rows]
        policy_taus = sorted({row["tau"] for row in rows if row["tau"] is not None})
        wrong = sum(1 for _, right in pairs if not right)
        walls = [row["wall_ms"] for row in rows] or [0.0]
        return {
            "experiment": "judge-recorder-fix",
            "what": "the routed cell, end to end through core.judge's Judge",
            "model": args.model,
            "port": args.port,
            "complete": complete,
            "steps": len(rows),
            "routed_by": "the calibration note's section 8.3 (this cell goes to the d1-3B)",
            "tau_source": tau_source,
            "policy_taus": policy_taus,
            "rows": rows,
            "accuracy": round(sum(1 for row in rows if row["right"]) / len(rows), 4)
            if rows
            else None,
            "gate_words": {
                word: sum(1 for row in rows if row["gate"] == word)
                for word in ("act", "escalate", "surfaced")
            },
            "wrong": wrong,
            "right": len(pairs) - wrong,
            "gates": {f"gate_at_{tau}": gate_at(pairs, tau) for tau in policy_taus},
            "tau_grid": [gate_at(pairs, tau) for tau in TAUS],
            "latency_ms": {
                "n": len(rows),
                "p50": round(statistics.median(walls), 3),
                "mean": round(statistics.fmean(walls), 3),
            },
            "ledger_rows": len(fold_judgments(ledger.events())),
        }

    for index, step in enumerate(steps):
        truth_key = KEYS[step["truth"]]
        started = time.perf_counter()
        answer = judge.judge(SEA_STATE_TASK, step["state"], (question,))
        wall_ms = round((time.perf_counter() - started) * 1000.0, 3)
        judgment = answer.judgment("sea")
        distribution = {key: float(value) for key, value in judgment.distribution.items()}
        argmax = max(sorted(distribution), key=lambda key: distribution[key])
        rows.append(
            {
                "t": step["t"],
                "trial": index // len(trials[0]),
                "truth": truth_key,
                "shown": KEYS[step["shown"]],
                "argmax": argmax,
                "right": argmax == truth_key,
                "confidence": judgment.confidence,
                "confidence_definition": judgment.confidence_definition,
                "tau": judgment.tau,
                "gate": judgment.gate,
                "surfaced": answer.surfaced,
                "attempts": answer.attempts,
                "backend_confidence": judgment.backend_confidence,
                "wall_ms": wall_ms,
            }
        )
        if (index + 1) % 20 == 0:
            print(f"  {index + 1}/{len(steps)} steps", flush=True)
        if (index + 1) % 60 == 0:
            out_path.write_text(json.dumps(assemble(False), indent=2), encoding="utf-8")

    result = assemble(True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"accuracy: {result['accuracy']}  gate words: {result['gate_words']}")
    print(f"gates at the policy's tau: {result['gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
