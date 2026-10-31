"""Experiment: the last two signals, measured on the real frames.

Two checks still need their discriminator measured rather than guessed:

* **patch_seam** fires on 13 of 38 clean frames — the seam detector finds
  rectangles in ordinary landscapes. What separates a *pasted* block from a
  landscape's own rectangles is how different the block's interior is from
  the ring around it, so the question is what that difference is on clean
  frames and on planted ones.
* **floating_blob** catches only 8 % of the planted floats, because the
  horizon estimate (the topmost textured row) is unreliable when the sky
  itself has texture — snow, cloud. The question is whether "how far does
  background extend below the blob before it hits something textured"
  separates the two populations.

Run:

    .venv/bin/python core/critic/exp_last_signals.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    box_mean,
    components,
    local_std,
    luma,
    _check_patch_seam,
)
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402


def seam_delta(image: np.ndarray) -> float:
    return _check_patch_seam(image, DEFAULT_THRESHOLDS).measured.get("seam_delta", 0.0)


def blobs(image: np.ndarray) -> list:
    g = luma(image)
    h, w = g.shape
    total = h * w
    background = box_mean(g, 31)
    difference = np.abs(g - background)
    mask = difference > 0.05
    _, found = components(mask)
    out = []
    for comp in found:
        if not (0.005 * total <= comp.size <= 0.08 * total):
            continue
        if comp.x0 <= 0 or comp.y0 <= 0 or comp.x1 >= w - 1 or comp.y1 >= h - 1:
            continue
        if comp.width / float(max(1, comp.height)) < 0.25:
            continue
        out.append(comp)
    return out


def open_run_below(g: np.ndarray, comp, height: int) -> float:
    """How far **open** background extends below the blob, in frame heights.

    The blob's own columns, the rows under it: how many rows of pure
    background (no local detail) before the first textured row. A prop
    hanging in the air has a long open run under it; a bump on the ground
    has none.
    """
    texture = local_std(g, 9)
    smooth = texture <= 0.05
    width = g.shape[1]
    best = 0
    for x in range(comp.x0, comp.x1 + 1):
        run = 0
        for y in range(comp.y1 + 1, height):
            if not smooth[y, x]:
                break
            run += 1
        best = max(best, run)
    return best / float(height)


def main() -> int:
    bases = harvest()
    print(f"bases: {len(bases)}\n")

    print("=== patch_seam: the best rectangle's interior difference ===")
    clean = []
    planted = []
    for base in bases:
        image = load_rgb(base.image_path)
        clean.append(seam_delta(image))
        donor = load_rgb(bases[(bases.index(base) + 1) % len(bases)].image_path)
        broken, _ = defects.apply(
            image,
            defects.plan("texture_swap", base_id=base.id, seed=902, donor_id="d"),
            donor_image=donor,
        )
        planted.append(seam_delta(broken))
    for name, values in (("clean", clean), ("planted", planted)):
        values = sorted(values)
        print(
            f"  {name:8s} n={len(values):3d} min={values[0]:.3f} "
            f"p50={values[len(values)//2]:.3f} p90={values[int(len(values)*0.9)]:.3f} "
            f"max={values[-1]:.3f}"
        )
    print("  separation (seam delta >= X):")
    for threshold in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        fp = sum(1 for v in clean if v >= threshold)
        tp = sum(1 for v in planted if v >= threshold)
        print(
            f"    >= {threshold:4.2f}: clean {fp:3d}/{len(clean):3d} "
            f"({fp/max(1,len(clean)):5.1%}), planted {tp:3d}/{len(planted):3d}"
        )

    print("\n=== floating: the open run below the blob ===")
    clean_open = []
    planted_open = []
    for base in bases:
        image = load_rgb(base.image_path)
        g = luma(image)
        for comp in blobs(image):
            clean_open.append(open_run_below(g, comp, g.shape[0]))
        broken, _ = defects.apply(
            image, defects.plan("floating_object", base_id=base.id, seed=902)
        )
        gb = luma(broken)
        for comp in blobs(gb):
            planted_open.append(open_run_below(gb, comp, gb.shape[0]))
    for name, values in (("clean", clean_open), ("planted", planted_open)):
        values = sorted(values)
        print(
            f"  {name:8s} n={len(values):4d} min={values[0]:.3f} "
            f"p50={values[len(values)//2]:.3f} p90={values[int(len(values)*0.9)]:.3f} "
            f"max={values[-1]:.3f}"
        )
    print("  separation (open run >= X):")
    for threshold in (0.03, 0.05, 0.08, 0.12, 0.16, 0.20):
        fp = sum(1 for v in clean_open if v >= threshold)
        tp = sum(1 for v in planted_open if v >= threshold)
        print(
            f"    >= {threshold:4.2f}: clean {fp:3d}/{len(clean_open):3d} "
            f"({fp/max(1,len(clean_open)):5.1%}), planted {tp:3d}/{len(planted_open):3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
