"""Experiment: can a *severely* clipped prop be told from a clean one?

Every camera-cutting rule fires on clean scenes: 98 clean props are cut by
the near plane, 149 by the picture's edge, 73 are sliced through the middle.
So the question is whether the *severity* of the cut separates: a prop the
picture cuts just at its edge is ordinary scenery, while a prop the picture
cuts **in half** is a prop that was badly placed.

The measure is the distance from the prop's middle to the picture's edge,
over the prop's own projected half-width: near zero means the picture cuts
the prop through its middle.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_clip_severity.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import props_of  # noqa: E402
from core.critic.mesh import probe_scene  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
SCENES = Path("/home/caseydigennaro/lm-critic/scenes")

CORNERS = (
    (0, 0, 0),
    (0, 0, 1),
    (0, 1, 0),
    (0, 1, 1),
    (1, 0, 0),
    (1, 0, 1),
    (1, 1, 0),
    (1, 1, 1),
)


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    severities: list[float] = []
    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        camera = stats.camera
        props = props_of(stats)
        if camera is None or not props:
            continue
        scene = []
        for obj in props:
            projected = [
                camera.projects(
                    (
                        obj.x0 if i == 0 else obj.x1,
                        obj.y0 if j == 0 else obj.y1,
                        obj.z0 if k == 0 else obj.z1,
                    )
                )
                for i, j, k in CORNERS
            ]
            rights = [p[0] for p in projected]
            ups = [p[1] for p in projected]
            forwards = [p[2] for p in projected]
            if min(forwards) <= 0:
                continue
            depth = sum(forwards) / len(forwards)
            half_w = camera.half_width * depth / camera.depth
            half_h = camera.half_height * depth / camera.depth
            if half_w <= 0 or half_h <= 0:
                continue
            right, up, _f = camera.projects(obj.centre)
            # How far the prop's middle is from the picture's edge, over the
            # prop's own projected half-width.
            to_right = (half_w - right) / (max(rights) - min(rights) + 1e-9) * 2
            to_left = (half_w + right) / (max(rights) - min(rights) + 1e-9) * 2
            to_top = (half_h - up) / (max(ups) - min(ups) + 1e-9) * 2
            to_bottom = (half_h + up) / (max(ups) - min(ups) + 1e-9) * 2
            margin = max(min(to_right, to_left), min(to_top, to_bottom))
            inside = abs(right) <= half_w and abs(up) <= half_h
            if inside and margin < 1.0:
                scene.append((margin, obj.name))
        severities.extend(m for m, _ in scene)
        print(f"  {blend.parent.parent.name:12s} props={len(props):4d} cut inside={len(scene):3d}")
        for margin, name in sorted(scene)[:3]:
            print(f"        margin {margin:.3f}  {name[:46]}")
    severities.sort()
    print(f"\n  clean props cut inside the picture: {len(severities)}")
    if severities:
        print(
            f"  margin: min={severities[0]:.3f} p50={severities[len(severities)//2]:.3f} "
            f"max={severities[-1]:.3f}"
        )
        for cut in (0.1, 0.2, 0.3, 0.4, 0.5):
            count = sum(1 for m in severities if m < cut)
            print(f"    margin < {cut:.1f}: {count} clean props")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
