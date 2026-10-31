"""Experiment: what separates a *floating* object from a hilltop bump?

The first measurement of the reference set found the ``floating_blob`` check
firing on 8 of 34 clean real renders — a false-positive rate of 23.5 %, well
over the 10 % band. The reason is that a bump on a smooth hillside looks, to
a local statistic, exactly like a prop hanging in the air: a compact blob in
smooth surroundings with smooth stuff under it.

This script measures the candidate signals on the clean frames (where the
answer is "not floating") and on the planted ones (where the answer is
"floating"), and reports how well each separates them.

Run:

    .venv/bin/python core/critic/exp_floating.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import box_mean, components, load_rgb, local_std, luma  # noqa: E402


def candidates(image: np.ndarray) -> list[dict]:
    """Every compact blob in smooth surroundings, with its signals."""
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
        band = 9
        x0 = max(0, comp.x0 - band)
        y0 = max(0, comp.y0 - band)
        x1 = min(w - 1, comp.x1 + band)
        y1 = min(h - 1, comp.y1 + band)
        outside = np.ones((y1 - y0 + 1, x1 - x0 + 1), dtype=bool)
        ox0 = comp.x0 - x0
        oy0 = comp.y0 - y0
        outside[oy0 : oy0 + comp.height, ox0 : ox0 + comp.width] = False
        region = local_std(g[y0 : y1 + 1, x0 : x1 + 1], 9)
        surround = float(np.median(region[outside])) if outside.any() else 1.0

        gap_rows = max(1, int(0.02 * h))
        below = difference[comp.y1 + 1 : comp.y1 + 1 + gap_rows, comp.x0 : comp.x1 + 1]
        gap = float((below < 0.05).mean()) if below.size else 0.0

        # The silhouette: the topmost strongly-textured row in each column.
        # A prop hanging in the air sits *above* the ground everywhere under it.
        textured = local_std(g, 9) > 0.05
        col_ground = []
        for x in range(comp.x0, comp.x1 + 1):
            rows = np.flatnonzero(textured[:, x])
            col_ground.append(int(rows[0]) if rows.size else h)
        ground = max(col_ground) if col_ground else h
        clearance = (ground - comp.y1) / float(h)

        out.append(
            {
                "area": comp.size,
                "surround": surround,
                "gap": gap,
                "clearance": clearance,
                "bottom": comp.y1,
                "x0": comp.x0,
            }
        )
    return out


def main() -> int:
    bases = harvest()
    clean_rows: list[dict] = []
    planted_rows: list[dict] = []
    for base in bases:
        image = load_rgb(base.image_path)
        for row in candidates(image):
            clean_rows.append(row)
        plan_ = defects.plan("floating_object", base_id=base.id, seed=902)
        broken, _ = defects.apply(image, plan_)
        for row in candidates(broken):
            planted_rows.append(row)

    def report(name: str, rows: list[dict], key: str) -> None:
        values = sorted(r[key] for r in rows)
        if not values:
            print(f"  {name:12s} {key:12s} (none)")
            return
        print(
            f"  {name:12s} {key:12s} n={len(values):4d} "
            f"min={values[0]:8.4f} p50={values[len(values)//2]:8.4f} "
            f"p90={values[int(len(values)*0.9)]:8.4f} max={values[-1]:8.4f}"
        )

    print("clean frames (the candidate is NOT floating):")
    for key in ("area", "surround", "gap", "clearance"):
        report("clean", clean_rows, key)
    print("\nplanted frames (the candidate IS floating):")
    for key in ("area", "surround", "gap", "clearance"):
        report("planted", planted_rows, key)

    # How well does "clearance" separate? A floating prop has ground well
    # below it; a hilltop bump has ground right under it.
    print("\nseparation by clearance (ground below the blob, in frame heights):")
    for threshold in (0.02, 0.05, 0.10, 0.20, 0.30):
        fp = sum(1 for r in clean_rows if r["clearance"] >= threshold)
        tp = sum(1 for r in planted_rows if r["clearance"] >= threshold)
        print(
            f"  clearance >= {threshold:4.2f}: {fp:3d}/{len(clean_rows):3d} clean "
            f"candidates pass ({fp/max(1,len(clean_rows)):5.1%}), "
            f"{tp:3d}/{len(planted_rows):3d} planted pass"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
