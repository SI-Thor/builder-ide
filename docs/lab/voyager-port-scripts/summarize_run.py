#!/usr/bin/env python3
"""Summarise a measured run into the numbers the report quotes.

The report's numbers are read out of the run's own payload rather than
copied by hand, so they cannot drift from what was measured.

Usage:
  .venv/bin/python docs/lab/voyager-port-scripts/summarize_run.py \
      docs/lab/voyager-port-scripts/results/minecraft-run.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    payload = json.loads(path.read_text())
    steps = payload.get("steps") or []

    print("=== the run ===")
    print("world            :", payload.get("world"))
    print("started          :", payload.get("started_at"))
    print("finished         :", payload.get("finished_at"))
    print("wall seconds     :", payload.get("wall_seconds"))
    print("steps            :", len(steps))
    print("stopped by       :", payload.get("stopped_by"))
    print("failure          :", payload.get("failure") or "(none)")
    print("models           :", json.dumps(payload.get("models"), sort_keys=True))

    print()
    print("=== the items ===")
    items = payload.get("items") or {}
    print("unique items     :", payload.get("unique_items"))
    for name, count in items.items():
        print("  %-24s %s" % (name, count))

    print()
    print("=== the tech tree ===")
    reached = payload.get("milestones_reached") or []
    seconds = payload.get("milestone_seconds") or {}
    tokens = payload.get("milestone_tokens") or {}
    print("milestones       :", list(reached))
    for key in reached:
        print(
            "  %-16s at %8.1f s, %9d tokens"
            % (key, float(seconds.get(key, 0.0)), int(tokens.get(key, 0)))
        )
    if not reached:
        print("  (none)")

    print()
    print("=== the skills ===")
    print("admitted         :", payload.get("skills_admitted"))
    print("rejected         :", payload.get("skills_rejected"))
    print("superseded       :", payload.get("skills_superseded"))

    print()
    print("=== the episodes ===")
    # crafter's teacher-comparison number: achievements per episode,
    # read off the last step's own facts (the adapter exposes it;
    # a minecraft run has no such facts and says so)
    last_facts = {}
    for step in steps:
        if step.get("facts"):
            last_facts = step["facts"]
    if last_facts.get("episodes_finished") is None:
        print("episodes         : (not this world's facts)")
    else:
        print("episodes finished:", last_facts.get("episodes_finished"))
        print("achievements/epi :", last_facts.get("mean_achievements_per_episode"))
        print("episode now      :", last_facts.get("episode"))
        reached_names = last_facts.get("achievements_reached") or []
        print("achievements     :", ", ".join(reached_names) or "(none)")
        print("spatial fact     :", "yes" if last_facts.get("spatial") else "no")

    print()
    print("=== the tokens ===")
    print("by role          :", json.dumps(payload.get("tokens_by_role"), sort_keys=True))
    print("total            :", payload.get("total_tokens"))
    book = payload.get("cost_book") or {}
    print("cost book        :", json.dumps(book.get("by_role", book), sort_keys=True))
    print("cost total       :", book.get("total_tokens", ""))
    print("cost cents       :", payload.get("cost_cents"))
    print("budget           :", json.dumps(payload.get("budget"), sort_keys=True))

    print()
    print("=== the turns ===")
    print(
        "%-5s %-16s %-13s %-6s %-9s %-8s %s"
        % ("step", "goal", "verdict", "truth", "disposition", "tokens", "reason")
    )
    for step in steps:
        print(
            "%-5s %-16s %-13s %-6s %-9s %-8s %s"
            % (
                step.get("index"),
                step.get("goal"),
                step.get("verdict"),
                step.get("truth"),
                step.get("disposition"),
                sum(u.get("total_tokens", 0) for u in step.get("usage") or []),
                str(step.get("reason") or "")[:60],
            )
        )

    print()
    print("=== the box ===")
    print("free mb          :", (payload.get("box") or {}).get("free_mb"))
    print("load average     :", (payload.get("box") or {}).get("loadavg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
