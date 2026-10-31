"""Experiment: the mesh half's sharp signals.

The first measurement of the mesh half showed why absolute thresholds cannot
work on real scenes: the clean props' inward-facing fraction reached 0.593
(vegetation is full of inward faces), the props' sizes vary by up to 5.5×
within a family, and half of them reach outside the frame — a landscape is
shot from inside it.

So the mesh checks need signals that are *categorical* rather than
gradual:

* **hollow** — a shell whose faces are turned inside out has a **negative
  signed volume**, while a correctly-wound solid's is positive. That is a
  sign, not a magnitude, and no amount of natural variation produces one.
* **clipped** — a prop the frame **cuts through** (some of its projected
  box in, some out) is different from one that is simply far away (all of
  it out), which is the normal case in a landscape.
* **wrong scale** — a prop that is an outlier **within its own family**,
  measured robustly (median and median-absolute-deviation), so one odd
  member of a varied family does not condemn the family.

Run:

    .venv/bin/python core/critic/exp_mesh_sharp.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import props_of, prop_family  # noqa: E402
from core.critic.mesh import probe_scene  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
SCENES = Path("/home/caseydigennaro/lm-critic/scenes")


def straddles(stats, obj) -> bool:
    """Does the frame cut *through* this prop?

    Some of the prop's projected box is inside the picture and some is
    outside. A prop that is wholly outside is simply off in the distance;
    a prop that is wholly inside is not cut at all.
    """
    camera = stats.camera
    if camera is None:
        return False
    inside = 0
    outside = 0
    for cx in (obj.x0, obj.x1):
        for cy in (obj.y0, obj.y1):
            for cz in (obj.z0, obj.z1):
                right, up, forward = camera.projects((cx, cy, cz))
                if forward <= 0:
                    outside += 1
                    continue
                half_w = camera.half_width * forward / camera.depth
                half_h = camera.half_height * forward / camera.depth
                if abs(right) <= half_w and abs(up) <= half_h:
                    inside += 1
                else:
                    outside += 1
    return inside > 0 and outside > 0


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    print(f"scenes: {len(blends)}\n")

    negatives = 0
    total = 0
    straddle_counts = []
    volume_signs = []
    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        props = props_of(stats)
        neg = [o for o in props if o.volume < 0]
        straddle = sum(1 for o in props if straddles(stats, o))
        total += len(props)
        negatives += len(neg)
        volume_signs.extend(o.volume for o in props)
        straddle_counts.append((blend.parent.parent.name, len(props), straddle))
        if neg:
            print(
                f"  {blend.parent.parent.name:12s} props={len(props):4d} "
                f"NEGATIVE volume: {len(neg)} -> "
                + ", ".join(o.name[:26] for o in neg[:3])
            )

    print(f"\n=== the signed volume ===")
    print(f"  props: {total}, with a negative volume: {negatives}")
    volumes = sorted(volume_signs)
    print(f"  min={volumes[0]:.4f} p50={volumes[len(volumes)//2]:.4f} max={volumes[-1]:.4f}")

    print("\n=== props the frame cuts through ===")
    for name, n, s in straddle_counts:
        print(f"  {name:12s} props={n:4d} cut through: {s}")

    print("\n=== the family-relative size, robustly ===")
    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        props = props_of(stats)
        families: dict[str, list] = {}
        for obj in props:
            families.setdefault(prop_family(obj.name), []).append(obj.diagonal)
        for fam, members in sorted(families.items()):
            if len(members) < 4:
                continue
            med = float(np.median(members))
            mad = float(np.median([abs(m - med) for m in members]))
            ratios = sorted(m / med for m in members)
            # A robust outlier: more than 4 median-absolute-deviations out.
            outliers = [m for m in members if mad > 0 and abs(m - med) > 4 * mad]
            print(
                f"  {blend.parent.parent.name:12s} {fam[:24]:26s} n={len(members):4d} "
                f"med={med:7.3f} mad={mad:6.3f} "
                f"ratio[{ratios[0]:.2f}..{ratios[-1]:.2f}] "
                f"robust-outliers={len(outliers)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
