"""Experiment: which filter throws away the planted floating object?

The recalibration run showed the floating check catching 7 of 41 planted
floats. The check has six filters, and the measurement does not say which
one throws the planted object away — so this script names the filter for
every base.

For each base it plants the float the way the current plant does, finds the
blob the pasted object actually forms in the check's own foreground mask,
and reports every filter's verdict on it.

Run:

    .venv/bin/python core/critic/exp_float_diag.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    _open_gap,
    _surrounding_detail,
    components,
    local_std,
    luma,
)
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import box_mean, load_rgb, next_true_row  # noqa: E402


def main() -> int:
    t = DEFAULT_THRESHOLDS
    bases = harvest()
    print(f"bases: {len(bases)}\n")
    tally: dict[str, int] = {}
    for base in bases:
        image = load_rgb(base.image_path)
        broken, recipe = defects.apply(
            image, defects.plan("floating_object", base_id=base.id, seed=902)
        )
        if not recipe.get("placed", True):
            key = "not placed"
            tally[key] = tally.get(key, 0) + 1
            print(f"  {base.id:12s} NOT PLACED ({recipe.get('reason')})")
            continue
        dx0, dy0, dx1, dy1 = recipe["dest_bbox"]
        g = luma(broken)
        h, w = g.shape
        total = h * w
        detail = local_std(g, 9)
        background = box_mean(g, t.float_window)
        difference = np.abs(g - background)
        mask = difference > t.float_background_delta
        _, found = components(mask)
        # The component that overlaps the pasted box the most: the copy is
        # an object with holes in it (a tree's crown is mostly sky), so its
        # centre is often not foreground at all.
        best = None
        best_overlap = 0
        for comp in found:
            ox = max(0, min(comp.x1, dx1) - max(comp.x0, dx0) + 1)
            oy = max(0, min(comp.y1, dy1) - max(comp.y0, dy0) + 1)
            overlap = ox * oy
            if overlap > best_overlap:
                best_overlap = overlap
                best = comp
        comp = best
        reasons = []
        if comp is None or best_overlap == 0:
            reasons.append("no component over the pasted spot")
        else:
            extent = comp.width * comp.height
            if not (t.float_min_frac * total <= extent <= t.float_max_frac * total):
                reasons.append(f"box {extent} ({extent/total:.3%})")
            if comp.x0 <= 0 or comp.y0 <= 0 or comp.x1 >= w - 1 or comp.y1 >= h - 1:
                reasons.append("touches the frame's edge")
            if comp.width / float(max(1, comp.height)) < t.float_min_aspect:
                reasons.append(f"aspect {comp.width/max(1,comp.height):.2f}")
            surround = _surrounding_detail(detail, comp)
            if surround > t.float_surround_std:
                reasons.append(f"surround std {surround:.3f}")
            textured = local_std(g, 9) > t.float_smooth_max
            next_row = next_true_row(textured)
            gap = _open_gap(next_row, comp, h)
            if gap < t.float_min_gap:
                reasons.append(f"gap {gap:.3f}")
        key = reasons[0].split(" ")[0] if reasons else "caught"
        tally[key] = tally.get(key, 0) + 1
        where = ""
        if comp is not None:
            where = (
                f"comp=({comp.x0:4d},{comp.y0:4d})-({comp.x1:4d},{comp.y1:4d}) "
                f"size={comp.size} overlap={best_overlap}"
            )
        print(
            f"  {base.id:12s} dest=({dx0:4d},{dy0:4d})-({dx1:4d},{dy1:4d}) "
            f"plant_gap={recipe.get('gap', 0):.3f} contrast={recipe.get('contrast', 0):.3f} "
            f"{where} :: {', '.join(reasons) or 'caught'}"
        )
    print("\n=== the first reason, tallied ===")
    for key, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {key:22s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
