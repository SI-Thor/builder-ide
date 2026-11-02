#!/usr/bin/env python3
"""Drive the Crafter adapter's whole port surface with no model.

The smoke run died five times in observe() on a numpy truth value
before any model was asked; this probe walks the port (open, observe,
run_code, evaluate, goal_truth, progress, close) so the next smoke run
starts from an adapter that has been round the loop once.

Usage: .venv/bin/python docs/lab/voyager-port-scripts/probe_crafter_adapter.py
Takes ~10 s and no tokens.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.voyager.adapters.crafter import CrafterAdapter


def main() -> int:
    adapter = CrafterAdapter(log=print)
    adapter.open()
    facts = adapter.observe()
    print("observe ok:", sorted(facts)[:6], "...")
    result = adapter.run_code(
        "print(mc.move('left', 2))\nprint(mc.achievements())", timeout_s=30.0
    )
    print("run_code ok:", result.ok, "log:", result.log[:2])
    check = adapter.evaluate("return True", timeout_s=10.0)
    print("evaluate ok:", check.passed)
    truth = adapter.goal_truth("collect_wood")
    print("goal_truth ok:", truth)
    snap = adapter.progress()
    print("progress ok:", snap.unique_items)
    adapter.close()
    print("the port round-trips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
