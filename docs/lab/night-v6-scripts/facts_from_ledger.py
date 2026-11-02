#!/usr/bin/env python3
"""Write the night's facts file from the night's own ledger, then the letter.

The letter is written from the rows the night's ledger holds. This script
transcribes them into the facts file `write_letter.py --facts` reads, so
every number in the letter is a number the ledger carries, and the
transcription is a command anyone can re-run.

The decision numbers are the ledger's split (`decision_counts.py`, beside
this script): one `judge.verdict` row per attempt, local/cloud/refused
attributed by the row's author. The night-v5 transcriber counted every
attributed row as local — the cloud's four included — and its "surfaced"
count read a gate key the row does not have (the gate lives on each
judgment inside the row); both are fixed by asking the shared counter.

    cd ~/lm-wt/night-v6 && PYTHONPATH=. \
        ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/facts_from_ledger.py \
        --night artifacts/night-v6 \
        --facts docs/lab/night-v6-scripts/letter-facts.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_counts import count_ledger  # noqa: E402


def rows(ledger: Path, kind: str) -> list[dict]:
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
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

    counted = count_ledger(ledger)
    facts["decisions"].update({
        key: counted[key]
        for key in ("count", "local", "escalated", "unattributed",
                    "surfaced", "act", "escalate", "rungs")
    })

    leases = rows(ledger, "night.heavy_lease")
    waits = [lease.get("waited_s", 0.0) for lease in leases]
    facts["memory"]["lease_wait_s"] = round(sum(waits), 2)
    facts["memory"]["leases"] = len(leases)

    args.facts.write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps({"facts": str(args.facts), "delegates": len(delegates),
                      "verdicts": counted["count"], "leases": len(leases),
                      "rungs": counted["rungs"],
                      "local": counted["local"],
                      "escalated": counted["escalated"],
                      "unattributed": counted["unattributed"],
                      "lease_wait_s": facts["memory"]["lease_wait_s"]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
