"""The measured batch: every prompt under prompts/, serially, then the
summary table from the summaries + the ledger.

Writes docs/lab/vibe-sandbox-scripts/results/batch.json and prints the
markdown the report quotes: per-stage latencies, pass rate, and the catch
matrix (which stage caught which seeded fault).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common import ARTIFACTS, LANE, RESULTS

SEEDED = {
    "clean-a": None,
    "clean-b": None,
    "float-a": "floating_object (crate.001 z=0.55)",
    "block-a": "blocked_door (crate.003 in the gap)",
    "pocket-a": "unreachable_area (interior walls seal 2x4 m corner)",
    "scale-a": "scale_bounds (crate.003 7.5x family median)",
    "selfx-a": "self_intersection (stackpile: two un-unioned boxes)",
}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-run rooms that already have a summary")
    args = ap.parse_args()

    prompts = sorted((LANE / "prompts").glob("*.json"))
    order = ["clean-a", "clean-b", "float-a", "block-a", "pocket-a", "scale-a", "selfx-a"]
    prompts.sort(key=lambda p: order.index(json.loads(p.read_text())["room_id"]))

    for p in prompts:
        room = json.loads(p.read_text())["room_id"]
        if not args.force and (ARTIFACTS / room / "summary.json").exists():
            print(f"=== {room} === already measured, skipping", flush=True)
            continue
        print(f"=== {room} ===", flush=True)
        subprocess.run(
            [sys.executable, str(LANE / "runner.py"), "--spec", str(p), "--commit-on-pass"],
            check=False,
        )

    rows = []
    for p in prompts:
        room = json.loads(p.read_text())["room_id"]
        summary_path = ARTIFACTS / room / "summary.json"
        if not summary_path.exists():
            rows.append({"room": room, "error": "no summary"})
            continue
        s = json.loads(summary_path.read_text())
        final_attempt = ARTIFACTS / room / f"a{s['attempts']}"
        prev_findings = s["findings_by_attempt"][0]
        rows.append(
            {
                "room": room,
                "seeded": SEEDED.get(room),
                "attempts": s["attempts"],
                "verdict": s["verdict"],
                "wall_ms": s["wall_ms"],
                "attempt_times": s["attempt_times"],
                "first_attempt_findings": [
                    f"{f.get('kind')}{':' + f['name'] if f.get('name') else ''} ({f['source']})"
                    for f in prev_findings
                ],
            }
        )

    batch = {"rooms": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "batch.json").write_text(json.dumps(batch, indent=1, sort_keys=True))
    print(json.dumps(batch, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
