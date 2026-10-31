"""Measure the mesh half's candidate signals across every rebuilt scene.

The mesh checks must be **absolute** measurements — a check that compares a
scene against a stored baseline would know the answer, and the whole point
is that the critic sees a scene it has never seen. So the thresholds have
to clear the natural variation of real scenes on their own.

This script prints, per scene, the distribution of the three candidate
signals:

* ``inward`` — the fraction of a prop's faces pointing inwards (a hollow
  shell);
* ``fill`` — the prop's volume over its bounding box's volume (a hollow
  shell encloses far less than a solid one);
* ``outside`` — the fraction of a prop's projected area that falls outside
  the frame (geometry the frame cuts through).

Run:

    .venv/bin/python core/critic/exp_mesh_signals.py
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


def projected_outside(stats, obj) -> float:
    """The fraction of a prop's projected box that falls outside the frame.

    The prop's box is projected into camera space and compared with the
    picture's bounds at its own depth. A prop that is merely *near* the
    frame's edge sticks out a little; a prop the frame has cut through
    loses half of itself.
    """
    camera = stats.camera
    if camera is None:
        return 0.0
    corners = [
        (x, y, z)
        for x in (obj.x0, obj.x1)
        for y in (obj.y0, obj.y1)
        for z in (obj.z0, obj.z1)
    ]
    inside = 0
    total = 0
    for cx in (obj.x0, obj.x1):
        for cy in (obj.y0, obj.y1):
            for cz in (obj.z0, obj.z1):
                right, up, forward = camera.projects((cx, cy, cz))
                if forward <= 0:
                    continue
                half_w = camera.half_width * forward / camera.depth
                half_h = camera.half_height * forward / camera.depth
                total += 1
                if abs(right) <= half_w and abs(up) <= half_h:
                    inside += 1
    if total == 0:
        return 0.0
    return 1.0 - inside / total


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    print(f"scenes: {len(blends)}\n")

    inward_all: list[float] = []
    fill_all: list[float] = []
    outside_all: list[float] = []
    family_ratio: dict[str, list[float]] = {}

    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        props = props_of(stats)
        inward = []
        fill = []
        outside = []
        families: dict[str, list] = {}
        for obj in props:
            inward.append(obj.inward)
            dx, dy, dz = obj.size
            box = dx * dy * dz
            fill.append(abs(obj.volume) / box if box > 1e-9 else 0.0)
            outside.append(projected_outside(stats, obj))
            families.setdefault(prop_family(obj.name), []).append(obj.diagonal)
        inward_all.extend(inward)
        fill_all.extend(fill)
        outside_all.extend(outside)
        for members in families.values():
            if len(members) < 2:
                continue
            diagonals = sorted(members)
            med = diagonals[len(diagonals) // 2] or 1.0
            for d in diagonals:
                family_ratio.setdefault(str(blend.parent.parent.name), []).append(d / med)
        print(
            f"  {blend.parent.parent.name:12s} props={len(props):4d} "
            f"inward max={max(inward, default=0):.3f} "
            f"fill min={min(fill, default=0):.3f} "
            f"outside max={max(outside, default=0):.3f}"
        )

    print("\n=== across every clean scene ===")
    for name, values in (
        ("inward", inward_all),
        ("fill", fill_all),
        ("outside", outside_all),
    ):
        values = sorted(values)
        print(
            f"  {name:8s} n={len(values):5d} min={values[0]:8.3f} "
            f"p50={values[len(values)//2]:8.3f} "
            f"p95={values[int(len(values)*0.95)]:8.3f} max={values[-1]:8.3f}"
        )

    print("\n=== the family-relative size ratio, per scene ===")
    for scene, values in sorted(family_ratio.items()):
        values = sorted(values)
        print(
            f"  {scene:12s} n={len(values):5d} min={values[0]:6.2f} "
            f"p50={values[len(values)//2]:6.2f} p95={values[int(len(values)*0.95)]:6.2f} "
            f"max={values[-1]:8.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
