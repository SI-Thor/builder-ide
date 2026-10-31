"""Experiment: three candidate fixes, measured on the real frames.

Each of the three checks that lost its catch has a *mechanism*, and this
script measures the candidate replacements against the clean frames (where
the answer is "no defect") and the planted ones (where the answer is
"defect"):

1. **fireflies** — a planted firefly is only visible where it contrasts with
   its surroundings. Does planting it *opposite* to its local background
   make it visible everywhere, and does a larger delta keep the clean
   frames' sun glitter out?
2. **texture swap** — a pasted rectangle has four straight edges. Does
   looking for long straight *edges* (rather than the frame's row and column
   profiles) separate it?
3. **floating object** — a thing floating in the air is against the **sky**.
   Does the frame's horizon separate a blob in the sky from a bump on the
   ground?

Run:

    .venv/bin/python core/critic/exp_fixes.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import box_mean, components, local_std, luma  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import load_rgb  # noqa: E402


# -- 1. fireflies ------------------------------------------------------------


def outliers(image: np.ndarray, delta: float) -> int:
    g = luma(image)
    interior = g[1:-1, 1:-1]
    nmax = np.maximum(
        np.maximum(g[:-2, 1:-1], g[2:, 1:-1]), np.maximum(g[1:-1, :-2], g[1:-1, 2:])
    )
    nmin = np.minimum(
        np.minimum(g[:-2, 1:-1], g[2:, 1:-1]), np.minimum(g[1:-1, :-2], g[1:-1, 2:])
    )
    return int(((interior - nmax) > delta).sum()) + int(((nmin - interior) > delta).sum())


def plant_contrasting(image: np.ndarray, count: int = 320, spacing: int = 4):
    """Fireflies planted *opposite* to their local background.

    A firefly is by definition a pixel that stands out against what is
    around it. Planting 0 into a dark sky or 255 into a bright dune makes
    nothing at all — which is why the first plant left a third of its
    fireflies invisible.
    """
    g = luma(image)
    h, w = g.shape
    out = image.copy()
    background = box_mean(g, 9)
    placed: list[tuple[int, int]] = []
    attempts = 0
    while len(placed) < count and attempts < count * 40:
        attempts += 1
        y = int(np.random.default_rng(attempts * 7919 + 13).integers(1, h - 1))
        x = int(np.random.default_rng(attempts * 6271 + 7).integers(1, w - 1))
        if any(
            abs(y - py) < spacing and abs(x - px) < spacing for py, px in placed
        ):
            continue
        placed.append((y, x))
        local = float(background[y, x])
        # Bright firefly on a dark background, dark firefly on a bright one.
        value = 255 if local < 0.5 else 0
        out[y, x, :] = value
    return out, len(placed)


# -- 2. texture swap: straight edges -----------------------------------------


def edge_columns(image: np.ndarray, threshold: float = 0.12) -> np.ndarray:
    """For each column, how many rows carry a strong horizontal gradient.

    A pasted rectangle's left and right edges are columns where the frame
    steps sideways, and they step for the rectangle's whole height.
    """
    g = luma(image)
    grad = np.abs(np.diff(g, axis=1))  # (h, w-1)
    return (grad > threshold).sum(axis=0)


def edge_rows(image: np.ndarray, threshold: float = 0.12) -> np.ndarray:
    g = luma(image)
    grad = np.abs(np.diff(g, axis=0))  # (h-1, w)
    return (grad > threshold).sum(axis=1)


def rect_score(image: np.ndarray, threshold: float = 0.12) -> int:
    """The best rectangle: two long vertical edges spanned by two long
    horizontal edges."""
    cols = edge_columns(image, threshold)
    rows = edge_rows(image, threshold)
    h, w = image.shape[:2]
    # A vertical edge must run for a good fraction of the frame's height.
    col_hits = np.flatnonzero(cols >= max(8, int(0.06 * h)))
    row_hits = np.flatnonzero(rows >= max(8, int(0.06 * w)))
    if len(col_hits) < 2 or len(row_hits) < 2:
        return 0
    best = 0
    for i in range(len(col_hits)):
        for j in range(i + 1, len(col_hits)):
            c0, c1 = int(col_hits[i]), int(col_hits[j])
            if c1 - c0 < 8:
                continue
            span = rows[(rows >= 0)]
            inside = span[(span > 0)]
            # Two horizontal edges that lie between the two verticals.
            band = np.flatnonzero(
                (np.arange(len(rows)) > 0)
            )
            horizontal = [
                int(r)
                for r in row_hits
            ]
            candidates = []
            for a in range(len(horizontal)):
                for b in range(a + 1, len(horizontal)):
                    r0, r1 = horizontal[a], horizontal[b]
                    if r0 < 0 or r1 < 0:
                        continue
                    if r0 > c0 and r1 < c1:
                        pass
                    candidates.append(abs(r1 - r0))
            if not candidates:
                continue
            best = max(best, min(candidates) * (c1 - c0))
    return best


# -- 3. floating: the horizon ------------------------------------------------


def horizon(image: np.ndarray) -> int:
    """The frame's horizon: the median, over columns, of the topmost
    strongly-textured row."""
    g = luma(image)
    h, w = g.shape
    textured = local_std(g, 9) > 0.05
    tops = []
    for x in range(0, w, 4):
        rows = np.flatnonzero(textured[:, x])
        tops.append(int(rows[0]) if rows.size else h)
    return int(np.median(tops)) if tops else h


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


def main() -> int:
    bases = harvest()
    print(f"bases: {len(bases)}\n")

    print("=== 1. fireflies: delta threshold, and the contrasting plant ===")
    for delta in (0.35, 0.45, 0.55, 0.65):
        clean = []
        for base in bases:
            clean.append(outliers(load_rgb(base.image_path), delta))
        planted_old = []
        planted_new = []
        for base in bases:
            image = load_rgb(base.image_path)
            broken, _ = defects.apply(
                image, defects.plan("noise_fireflies", base_id=base.id, seed=902)
            )
            planted_old.append(outliers(broken, delta))
            new, _ = plant_contrasting(image)
            planted_new.append(outliers(new, delta))
        print(
            f"  delta={delta:.2f}  clean max={max(clean):4d} "
            f"| old plant min={min(planted_old):4d} "
            f"| new plant min={min(planted_new):4d} "
            f"(median {int(np.median(planted_new))})"
        )

    print("\n=== 2. texture swap: straight edges ===")
    clean_edges = []
    for base in bases:
        clean_edges.append(rect_score(load_rgb(base.image_path)))
    planted_edges = []
    for base in bases:
        image = load_rgb(base.image_path)
        donor = load_rgb(bases[(bases.index(base) + 1) % len(bases)].image_path)
        broken, _ = defects.apply(
            image,
            defects.plan("texture_swap", base_id=base.id, seed=902, donor_id="d"),
            donor_image=donor,
        )
        planted_edges.append(rect_score(broken))
    print(f"  clean: min={min(clean_edges)} p50={int(np.median(clean_edges))} max={max(clean_edges)}")
    print(f"  planted: min={min(planted_edges)} p50={int(np.median(planted_edges))} max={max(planted_edges)}")
    for threshold in (2000, 5000, 10000, 20000):
        fp = sum(1 for v in clean_edges if v >= threshold)
        tp = sum(1 for v in planted_edges if v >= threshold)
        print(f"  score >= {threshold:6d}: clean {fp:2d}/{len(clean_edges)} planted {tp:2d}/{len(planted_edges)}")

    print("\n=== 3. floating: the horizon ===")
    clean_above = []
    planted_above = []
    for base in bases:
        image = load_rgb(base.image_path)
        hz = horizon(image)
        for comp in blobs(image):
            clean_above.append((hz - comp.y1) / float(image.shape[0]))
        broken, _ = defects.apply(
            image, defects.plan("floating_object", base_id=base.id, seed=902)
        )
        hzb = horizon(broken)
        for comp in blobs(broken):
            planted_above.append((hzb - comp.y1) / float(broken.shape[0]))
    for name, values in (("clean", clean_above), ("planted", planted_above)):
        values = sorted(values)
        print(
            f"  {name:8s} n={len(values):4d} min={values[0]:.3f} "
            f"p50={values[len(values)//2]:.3f} p90={values[int(len(values)*0.9)]:.3f} "
            f"max={values[-1]:.3f}"
        )
    print("  separation (blob's bottom at least X above the horizon):")
    for threshold in (0.05, 0.10, 0.15, 0.20, 0.25):
        fp = sum(1 for v in clean_above if v >= threshold)
        tp = sum(1 for v in planted_above if v >= threshold)
        print(
            f"    >= {threshold:4.2f}: clean {fp:3d}/{len(clean_above):3d} "
            f"({fp/max(1,len(clean_above)):5.1%}), planted {tp:3d}/{len(planted_above):3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
