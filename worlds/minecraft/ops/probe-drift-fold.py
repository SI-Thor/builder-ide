#!/usr/bin/env python3
"""Fold the live ledger the way the drift detector does, and say what it sees.

The detector's own view, printed: for each agent, the recent buckets
(plays, wins, losses, the worst gap, the idle) and whether the idle was
**excused** by a yield — the fold sets ``idle_seconds`` to None when a
``drift.yield`` falls inside the window, because an agent standing aside
is not an agent stalled.

    runtime/venv/bin/python ops/probe-drift-fold.py [buckets]

Needs nothing but the ledger and the drift brief's core on the path
(AW_DRIFT_HOME, default ~/lm-wt/drift-pause).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("AW_DRIFT_HOME", str(Path.home() / "lm-wt" / "drift-pause")))
sys.path.insert(0, str(HOME))

from core.drift.ledger import build_series, read_yields  # noqa: E402

LEDGER = Path(
    os.environ.get(
        "AW_LEDGER",
        str(Path.home() / "lm-wt" / "agent-world" / "runtime" / "world-ledger.sqlite3"),
    )
)


def main() -> None:
    how_many = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    yields = read_yields(LEDGER)
    series = build_series(str(LEDGER))
    print(f"ledger: {LEDGER}")
    print(f"yield points in the ledger: {len(yields)}")
    by_agent: dict[str, int] = {}
    for point in yields:
        name = str(point.get("agent"))
        by_agent[name] = by_agent.get(name, 0) + 1
    print(f"yields per agent: {by_agent}")
    print(f"buckets: {len(series.buckets)} (agents: {series.agents})")
    print()
    for agent in series.agents:
        print(f"--- {agent} ---")
        for bucket in series.buckets[-how_many:]:
            entry = bucket.agents.get(agent)
            if entry is None:
                print(f"  {int(bucket.start)}  (no bucket for this agent)")
                continue
            idle = entry.idle_seconds
            idle_text = "excused (a yield inside the window)" if idle is None else f"{idle:.0f}s"
            print(
                f"  {int(bucket.start)}  plays {entry.plays:3d}  wins {entry.wins:3d}  "
                f"losses {entry.losses:3d}  gap_max "
                f"{('%.0f' % entry.gap_max) if entry.gap_max is not None else '-':>7}  "
                f"idle {idle_text}"
            )
        print()


if __name__ == "__main__":
    main()
