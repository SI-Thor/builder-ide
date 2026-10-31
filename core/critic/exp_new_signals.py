"""Experiment: the redesigned checks, measured on the real frames.

The redesign of ``patch_seam`` and ``floating_blob`` and of the plants that
feed them has to be measured, not argued: what the clean frames score, what
the planted defects score, and whether a threshold exists between them.

This script prints, for every image defect class, the distribution of the
target check's statistic on the clean frames and on the planted ones, and
the separation a threshold would give.

Run:

    .venv/bin/python core/critic/exp_new_signals.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    _check_black_frame,
    _check_dark_holes,
    _check_fireflies,
    _check_floating_blob,
    _check_flat_patch,
    _check_patch_seam,
)
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402

#: check name -> the statistic it reports in ``measured``.
STATISTIC = {
    "black_frame": "mean_luma",
    "fireflies": "fireflies",
    "flat_patch": "flat_frac",
    "dark_holes": "holes",
    "patch_seam": "seam_strength",
    "floating_blob": "gap",
}

#: check name -> (the defect class it targets, the direction of the test).
TARGET = {
    "black_frame": ("black_frame", "below"),
    "fireflies": ("noise_fireflies", "above"),
    "flat_patch": ("missing_object", "above"),
    "dark_holes": ("holes", "above"),
    "patch_seam": ("texture_swap", "above"),
    "floating_blob": ("floating_object", "above"),
}

CHECKS = {
    "black_frame": _check_black_frame,
    "fireflies": _check_fireflies,
    "flat_patch": _check_flat_patch,
    "dark_holes": _check_dark_holes,
    "patch_seam": _check_patch_seam,
    "floating_blob": _check_floating_blob,
}


def report(check: str, clean: list[float], planted: list[float]) -> None:
    defect, direction = TARGET[check]
    stat = STATISTIC[check]
    print(f"\n=== {check} (targets {defect}, statistic {stat}) ===")
    for name, values in (("clean", clean), ("planted", planted)):
        values = sorted(values)
        if not values:
            print(f"  {name:8s} (none)")
            continue
        print(
            f"  {name:8s} n={len(values):3d} min={values[0]:.4f} "
            f"p10={values[int(len(values)*0.1)]:.4f} "
            f"p50={values[len(values)//2]:.4f} "
            f"p90={values[int(len(values)*0.9)]:.4f} max={values[-1]:.4f}"
        )
    # The thresholds worth trying, between the two populations.
    candidates = sorted({round(v, 3) for v in clean + planted})
    best = None
    for threshold in candidates:
        if direction == "below":
            fp = sum(1 for v in clean if v < threshold)
            tp = sum(1 for v in planted if v < threshold)
        else:
            fp = sum(1 for v in clean if v >= threshold)
            tp = sum(1 for v in planted if v >= threshold)
        if fp == 0 and tp == len(planted) and planted:
            best = (threshold, fp, tp)
    if best:
        print(f"  a threshold that catches every plant and no clean frame: {best[0]}")
    else:
        # The best available: the most plants caught with the fewest FPs.
        rows = []
        for threshold in candidates:
            if direction == "below":
                fp = sum(1 for v in clean if v < threshold)
                tp = sum(1 for v in planted if v < threshold)
            else:
                fp = sum(1 for v in clean if v >= threshold)
                tp = sum(1 for v in planted if v >= threshold)
            rows.append((fp, -tp, threshold))
        rows.sort()
        print(f"  the best available: threshold {rows[0][2]} -> {rows[0][0]} FP, {-rows[0][1]} caught")
        # And the sweeps, for the record.
        for threshold in (0.02, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
            if direction == "below":
                fp = sum(1 for v in clean if v < threshold)
                tp = sum(1 for v in planted if v < threshold)
            else:
                fp = sum(1 for v in clean if v >= threshold)
                tp = sum(1 for v in planted if v >= threshold)
            print(
                f"    >= {threshold:5.3f}: clean {fp:3d}/{len(clean):3d}, "
                f"planted {tp:3d}/{len(planted):3d}"
            )


def main() -> int:
    bases = harvest()
    print(f"bases: {len(bases)}")
    images = [load_rgb(b.image_path) for b in bases]
    donors = [images[(i + 1) % len(images)] for i in range(len(images))]

    clean: dict[str, list[float]] = {name: [] for name in CHECKS}
    planted: dict[str, list[float]] = {name: [] for name in CHECKS}
    fired: dict[str, int] = {name: 0 for name in CHECKS}

    for index, (base, image) in enumerate(zip(bases, images)):
        for name, check in CHECKS.items():
            outcome = check(image, DEFAULT_THRESHOLDS)
            clean[name].append(float(outcome.measured.get(STATISTIC[name], 0.0)))
        for name, check in CHECKS.items():
            defect = TARGET[name][0]
            plan_ = defects.plan(defect, base_id=base.id, seed=902, donor_id="donor")
            broken, recipe = defects.apply(
                image, plan_, donor_image=donors[index] if defect == "texture_swap" else None
            )
            if defect == "floating_object" and not recipe.get("placed", True):
                planted[name].append(0.0)
                continue
            outcome = check(broken, DEFAULT_THRESHOLDS)
            planted[name].append(float(outcome.measured.get(STATISTIC[name], 0.0)))
            fired[name] += int(outcome.fired)

    for name in CHECKS:
        report(name, clean[name], planted[name])

    print("\n=== the checks as they stand, on the planted frames ===")
    for name, count in fired.items():
        print(f"  {name:14s} fired on {count}/{len(bases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
