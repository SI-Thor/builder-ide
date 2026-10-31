"""Measure the reference set: every defect class, seeded and scored.

The point of this script is to find out, on **real renders**, which checks
catch which seeded defects and which fire on the clean controls. It is the
measurement behind the thresholds in :mod:`core.critic.checks` and the
numbers behind ``core/critic/CALIBRATION.md``.

Run:

    .venv/bin/python core/critic/measure_set.py [--sweep-root DIR]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import run_image_checks  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402
from core.critic.models import DEFECT_TARGETS, IMAGE_DEFECTS  # noqa: E402


def main(argv: list[str]) -> int:
    root = argv[0] if argv and not argv[0].startswith("-") else None
    bases = harvest(root)
    print(f"bases: {len(bases)}\n")

    fired: dict[str, Counter] = {d: Counter() for d in IMAGE_DEFECTS}
    clean_fired: dict[str, Counter] = {}
    detail: dict[str, list[str]] = {d: [] for d in IMAGE_DEFECTS}

    for base in bases:
        image = load_rgb(base.image_path)

        clean = {o.check: o for o in run_image_checks(image)}
        for check, outcome in clean.items():
            if outcome.fired:
                clean_fired.setdefault(check, Counter())[base.id] += 1

        for defect in IMAGE_DEFECTS:
            donor = None
            if defect == "texture_swap":
                donor = load_rgb(bases[(bases.index(base) + 1) % len(bases)].image_path)
            plan_ = defects.plan(defect, base_id=base.id, seed=902, donor_id="donor")
            broken, recipe = defects.apply(
                image, plan_, donor_image=donor
            )
            outcomes = {o.check: o for o in run_image_checks(broken)}
            target = DEFECT_TARGETS[defect]
            if outcomes[target].fired:
                fired[defect]["hit"] += 1
                detail[defect].append(f"{base.id}:hit")
            else:
                fired[defect]["miss"] += 1
                detail[defect].append(f"{base.id}:MISS({recipe})")

    print("=== clean controls: what fires on an un-defected real render ===")
    for check in sorted(clean_fired):
        n = sum(clean_fired[check].values())
        print(f"  {check:16s} fired on {n:3d}/{len(bases)} clean frames")
        if n:
            print(f"      {dict(clean_fired[check])}")

    print("\n=== seeded defects: does the target check catch it? ===")
    for defect in IMAGE_DEFECTS:
        c = fired[defect]
        total = c["hit"] + c["miss"]
        rate = c["hit"] / total if total else 0.0
        print(
            f"  {defect:18s} target={DEFECT_TARGETS[defect]:14s} "
            f"caught {c['hit']:3d}/{total:3d} ({rate:5.1%})"
        )
        misses = [d for d in detail[defect] if "MISS" in d]
        if misses:
            for m in misses[:4]:
                print(f"      {m[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
