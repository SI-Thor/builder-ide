#!/usr/bin/env python3
"""The night's decisions, counted from the ledger — the one count every
document must agree with.

The letter of 2026-11-02 (night-v5) said "1 of 5 decisions answered
locally (4 went to the cloud)" while the run's own measurements said 251
decisions, 245 on the local d1-3B. Both numbers were honestly derived and
they disagreed, because they counted different things:

* the letter read ``morning.json``'s ``decisions`` block, which the runner
  folds from the JudgeSeat's **in-memory list** — one entry per *decision*
  the seat itself finished, and nothing else. The routed decoy cell's 240
  verdicts (asked through the probe's own Judge, not the seat) and the
  two refused attempts never reached it, and attempts that escalated
  (a local try, then the cloud) collapsed into one entry blaming the
  cloud.
* the ledger's ``judge.verdict`` rows are one row per **attempt** —
  refused attempts included — which is what ``measure.py`` counts.

The ledger is the receipt, so the ledger is the count. This module is the
one place the split is computed, and the letter writer, the facts
transcriber and the tests all ask it, so the letter's numbers equal the
ledger's by construction.

An *attempt* row is attributed by its ``author``: ``judge@d1:d1-3B`` is
local, ``judge@jev:...`` / anything with ``jev`` or ``clef`` in it went to
the cloud, and a row with no author is a refusal (the backend never
answered, so nobody can be blamed). "Local" in the old facts transcriber
counted the cloud rows as local (``author != '?'``) — that is fixed here
too.

Run on the Thor:

    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/decision_counts.py \
        --ledger artifacts/night-v6/ledger.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

#: Authors that mean "went to the cloud" — the escalation ladder's rungs.
CLOUD_MARKS = ("jev", "clef")


def verdict_rows(ledger: Path) -> list[dict[str, Any]]:
    """Every ``judge.verdict`` payload in the ledger, in ledger order."""
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        return [
            json.loads(payload)
            for (payload,) in connection.execute(
                "select payload from audit where type = ? order by seq",
                ("judge.verdict",))
        ]
    finally:
        connection.close()


def count_decisions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The one split: attempts by author, and the gates they landed on.

    This is ``measure.py``'s counting (by_rung / by_gate), factored out so
    the letter and the facts file cannot drift from the measurements.
    """
    rungs: dict[str, int] = {}
    gates: dict[str, int] = {}
    for verdict in rows:
        author = str(verdict.get("author") or "?")
        rungs[author] = rungs.get(author, 0) + 1
        for judgment in verdict.get("judgments", []):
            gate = str(judgment.get("gate"))
            gates[gate] = gates.get(gate, 0) + 1
    cloud = sum(count for author, count in rungs.items()
                if any(mark in author for mark in CLOUD_MARKS))
    local = sum(count for author, count in rungs.items()
                if author != "?" and not any(mark in author for mark in CLOUD_MARKS))
    return {
        "count": len(rows),
        "local": local,
        "escalated": cloud,
        "unattributed": rungs.get("?", 0),
        "surfaced": gates.get("surfaced", 0),
        "act": gates.get("act", 0),
        "escalate": gates.get("escalate", 0),
        "rungs": rungs,
    }


def count_ledger(ledger: Path) -> dict[str, Any]:
    """The split for one ledger file on disk."""
    return count_decisions(verdict_rows(ledger))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(count_ledger(args.ledger), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
