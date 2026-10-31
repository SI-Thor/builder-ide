"""Experiment: why do the checks miss the seeded defects?

The corrected thresholds removed every false positive from the clean frames
(0 of 34 now), but they also cost the checks their catches: the fireflies
check caught 47 %, the texture swap 3 %, the floating object 0 %. This script
measures the *mechanism* of each miss so the fix is a measurement rather than
a guess.

Run:

    .venv/bin/python core/critic/exp_misses.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import box_mean, components, local_std, luma  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402


def profile_steps(image: np.ndarray) -> tuple[float, float]:
    a = image.astype(np.float64) / 255.0
    rows = a.mean(axis=1)
    cols = a.mean(axis=0)
    row_steps = np.linalg.norm(np.diff(rows, axis=0), axis=1)
    col_steps = np.linalg.norm(np.diff(cols, axis=0), axis=1)
    return float(row_steps.max()), float(col_steps.max())


def clearance_below(g: np.ndarray, comp, height: int) -> float:
    """How far below a blob the ground is, in frame heights.

    For each column under the blob, the first textured row *below* the
    blob's bottom. The **nearest** of those is the ground the blob sits on
    (or nearly sits on); the further it is, the more the blob is suspended.
    """
    textured = local_std(g, 9) > 0.05
    nearest = height
    for x in range(comp.x0, comp.x1 + 1):
        rows = np.flatnonzero(textured[comp.y1 + 1 :, x])
        if rows.size:
            nearest = min(nearest, comp.y1 + 1 + int(rows[0]))
    return max(0.0, (nearest - comp.y1) / float(height))


def blob_candidates(g: np.ndarray) -> list:
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


def firefly_counts(image: np.ndarray, delta: float = 0.35) -> tuple[int, int]:
    g = luma(image)
    interior = g[1:-1, 1:-1]
    nmax = np.maximum(np.maximum(g[:-2, 1:-1], g[2:, 1:-1]), np.maximum(g[1:-1, :-2], g[1:-1, 2:]))
    nmin = np.minimum(np.minimum(g[:-2, 1:-1], g[2:, 1:-1]), np.minimum(g[1:-1, :-2], g[1:-1, 2:]))
    return int(((interior - nmax) > delta).sum()), int(((nmin - interior) > delta).sum())


def main() -> int:
    bases = harvest()

    print("=== 1. texture swap: the joint (row, column) step ===")
    print("   clean frames — is any one of them high in BOTH directions?")
    clean_pairs = []
    for base in bases:
        image = load_rgb(base.image_path)
        r, c = profile_steps(image)
        clean_pairs.append((r, c, base.id))
    clean_pairs.sort(key=lambda t: -min(t[0] / 0.08, t[1] / 0.22))
    for r, c, name in clean_pairs[:6]:
        print(f"     {name:14s} row={r:.3f} col={c:.3f}")
    planted_pairs = []
    for base in bases:
        image = load_rgb(base.image_path)
        donor = load_rgb(bases[(bases.index(base) + 1) % len(bases)].image_path)
        broken, _ = defects.apply(
            image,
            defects.plan("texture_swap", base_id=base.id, seed=902, donor_id="d"),
            donor_image=donor,
        )
        r, c = profile_steps(broken)
        planted_pairs.append((r, c, base.id))
    planted_pairs.sort(key=lambda t: -min(t[0] / 0.08, t[1] / 0.22))
    print("   planted frames — the swap's own step:")
    for r, c, name in planted_pairs[:6]:
        print(f"     {name:14s} row={r:.3f} col={c:.3f}")

    print("\n=== 2. floating object: the clearance below the blob ===")
    clean_clear = []
    planted_clear = []
    for base in bases:
        image = load_rgb(base.image_path)
        g = luma(image)
        for comp in blob_candidates(g):
            clean_clear.append(clearance_below(g, comp, g.shape[0]))
        broken, _ = defects.apply(
            image, defects.plan("floating_object", base_id=base.id, seed=902)
        )
        gb = luma(broken)
        for comp in blob_candidates(gb):
            planted_clear.append(clearance_below(gb, comp, gb.shape[0]))
    for name, values in (("clean", clean_clear), ("planted", planted_clear)):
        values = sorted(values)
        if values:
            print(
                f"   {name:8s} n={len(values):4d} min={values[0]:.3f} "
                f"p50={values[len(values)//2]:.3f} p90={values[int(len(values)*0.9)]:.3f} "
                f"max={values[-1]:.3f}"
            )
    print("   separation (clearance >= X):")
    for threshold in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        fp = sum(1 for v in clean_clear if v >= threshold)
        tp = sum(1 for v in planted_clear if v >= threshold)
        print(
            f"     >= {threshold:4.2f}: clean {fp:3d}/{len(clean_clear):3d} "
            f"({fp/max(1,len(clean_clear)):5.1%}), planted {tp:3d}/{len(planted_clear):3d}"
        )

    print("\n=== 3. fireflies: how many of the planted 320 are visible? ===")
    for base in bases[:6]:
        image = load_rgb(base.image_path)
        broken, _ = defects.apply(
            image, defects.plan("noise_fireflies", base_id=base.id, seed=902)
        )
        hi, lo = firefly_counts(broken)
        chi, clo = firefly_counts(image)
        print(
            f"   {base.id:14s} clean={chi + clo:4d} planted={hi + lo:4d} "
            f"(bright {hi}, dark {lo})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
