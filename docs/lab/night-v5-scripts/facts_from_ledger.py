#!/usr/bin/env python3
"""Write the night's facts file from the night's own ledger, then the letter.

The letter is written from the rows the night's ledger holds. This script
transcribes them into the facts file `write_letter.py --facts` reads, so
every number in the letter is a number the ledger carries, and the
transcription is a command anyone can re-run.

    cd ~/lm-wt/night-v5 && PYTHONPATH=. \
        ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v5-scripts/facts_from_ledger.py \
        --night artifacts/night-v5 \
        --facts docs/lab/night-v5-scripts/letter-facts.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def rows(ledger: Path, kind: str) -> list[dict]:
    connection = sqlite3.connect(ledger)
    try:
        return [json.loads(payload) for (payload,) in connection.execute(
            "select payload from audit where type = ? order by seq", (kind,))]
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--night", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    args = parser.parse_args()

    ledger = args.night / "ledger.db"
    facts = json.loads(args.facts.read_text())

    delegates = rows(ledger, "night.prop_delegate")
    facts["critic"]["signals"] = [
        {"stage": signal.get("stage", "image"),
         "task_id": signal.get("task_id"),
         "variant_id": signal.get("variant_id"),
         "error": signal.get("error")}
        for signal in delegates
    ]

    verdicts = rows(ledger, "judge.verdict")
    rungs: dict[str, int] = {}
    for verdict in verdicts:
        author = verdict.get("author") or "?"
        rungs[author] = rungs.get(author, 0) + 1
    facts["decisions"]["count"] = len(verdicts)
    facts["decisions"]["local"] = sum(
        count for author, count in rungs.items() if author != "?")
    facts["decisions"]["escalated"] = sum(
        count for author, count in rungs.items() if "jev" in author)
    facts["decisions"]["surfaced"] = sum(
        1 for verdict in verdicts
        if (verdict.get("payload", verdict).get("gate") == "surfaced")
        if isinstance(verdict.get("payload", verdict), dict))
    facts["decisions"]["rungs"] = rungs

    leases = rows(ledger, "night.heavy_lease")
    waits = [lease.get("waited_s", 0.0) for lease in leases]
    facts["memory"]["lease_wait_s"] = round(sum(waits), 2)
    facts["memory"]["leases"] = len(leases)

    args.facts.write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps({"facts": str(args.facts), "delegates": len(delegates),
                      "verdicts": len(verdicts), "leases": len(leases),
                      "rungs": rungs, "lease_wait_s": facts["memory"]["lease_wait_s"]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
