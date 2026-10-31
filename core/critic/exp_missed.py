"""Experiment: the missed members, and why they were missed.

The published table says two classes have a false negative. This script
re-scores the set and prints what each missed member's check actually said
— the check's own words, not a guess.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_missed.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.critic import CriticRunner  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.models import DEFECT_TARGETS  # noqa: E402
from core.critic.set import read_manifest  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
ROOT = Path("/home/caseydigennaro/lm-wt/critic-calib/core/critic")


def main() -> int:
    bases = list(harvest())
    members = read_manifest(ROOT / "reference-set.json")
    runner = CriticRunner(bases=bases, blender_python=PYTHON)
    verdicts = runner.score_all(members)
    for verdict in verdicts:
        if verdict.defect is None:
            continue
        target = DEFECT_TARGETS[verdict.defect]
        outcome = verdict.outcome(target)
        if outcome is not None and outcome.fired:
            continue
        print(f"  MISSED {verdict.defect:18s} {verdict.member_id}")
        if outcome is None:
            print("      the check did not even run")
            continue
        print(f"      {target}: {outcome.detail}")
        print(f"      measured: {outcome.measured}")
        print(f"      recipe: {verdict.recipe if hasattr(verdict, 'recipe') else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
