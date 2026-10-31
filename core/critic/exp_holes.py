"""Experiment: why a planted hole is missed.

The check looks for a compact, uniform, dark blob inside a surface. When
a planted hole is not found, one of its four conditions failed: the area,
the contrast against the surface, the interior's uniformity, or the
presence of a blob at all. This script names which.

Run:

    .venv/bin/python core/critic/exp_holes.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import DEFAULT_THRESHOLDS, _check_dark_holes, components  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import box_mean, load_rgb, luma  # noqa: E402


def main() -> int:
    t = DEFAULT_THRESHOLDS
    bases = harvest()
    print(f"bases: {len(bases)}\n")
    missed = 0
    for base in bases:
        image = load_rgb(base.image_path)
        broken, recipe = defects.apply(
            image, defects.plan("holes", base_id=base.id, seed=902)
        )
        outcome = _check_dark_holes(broken, t)
        if outcome.fired:
            continue
        missed += 1
        g = luma(broken)
        surface = box_mean(g, 9)
        diff = surface - g
        mask = diff > t.hole_delta
        labels, found = components(mask)
        reasons = []
        for cx, cy, radius in recipe["holes"]:
            window = (slice(cy - radius, cy + radius + 1), slice(cx - radius, cx + radius + 1))
            selected = labels[window] == labels[cy, cx]
            if not selected.any():
                reasons.append(f"no blob at ({cx},{cy}) r={radius}")
                continue
            contrast = float(diff[window][selected].mean())
            spread = float(g[window][selected].std())
            area = int(selected.sum())
            if area < t.hole_min_area:
                reasons.append(f"area {area}")
            elif contrast < t.hole_min_contrast:
                reasons.append(f"contrast {contrast:.3f}")
            elif spread > t.hole_uniform_std:
                reasons.append(f"spread {spread:.3f}")
            else:
                reasons.append("ok")
        print(f"  {base.id:12s} :: {' '.join(reasons)}")
    print(f"\n  missed: {missed}/{len(bases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
