"""Experiment: what the camera actually cuts, in the clean scenes.

The near plane turned out to be a bad oracle: it fires on seven of the
eleven rebuilt clean scenes, because a camera standing in a landscape has
props right beside it. The alternative is the picture's own edge — a prop
the frame cuts *through*, some of it in the picture and some of it out.

This script counts both kinds of cut, per clean scene, so the rule is
chosen from a measurement rather than from an argument.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_near_plane.py
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
    near_total = 0
    frame_total = 0
    sliced_total = 0
    around_total = 0
    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        camera = stats.camera
        props = props_of(stats)
        if camera is None or not props:
            continue
        near = []
        frame = []
        sliced = []
        around = []
        for obj in props:
            box = [
                (
                    obj.x0 if i == 0 else obj.x1,
                    obj.y0 if j == 0 else obj.y1,
                    obj.z0 if k == 0 else obj.z1,
                )
                for i, j, k in CORNERS
            ]
            projected = [camera.projects(corner) for corner in box]
            forwards = [p[2] for p in projected]
            if min(forwards) < camera.clip_start < max(forwards):
                near.append(obj.name)
            if min(forwards) < 0.0 < max(forwards):
                around.append(obj.name)
            inside = 0
            for right, up, forward in projected:
                if forward <= 0:
                    continue
                half_w = camera.half_width * forward / camera.depth
                half_h = camera.half_height * forward / camera.depth
                if abs(right) <= half_w and abs(up) <= half_h:
                    inside += 1
            if 0 < inside < len(projected):
                frame.append(obj.name)
                # The frame slices the prop when the prop's own middle is
                # in the picture and part of it is not.
                centre = camera.projects(obj.centre)
                right, up, forward = centre
                if forward > 0:
                    half_w = camera.half_width * forward / camera.depth
                    half_h = camera.half_height * forward / camera.depth
                    if abs(right) <= half_w and abs(up) <= half_h:
                        sliced.append(obj.name)
        near_total += len(near)
        frame_total += len(frame)
        sliced_total += len(sliced)
        around_total += len(around)
        print(
            f"  {blend.parent.parent.name:12s} props={len(props):4d} "
            f"near-plane={len(near):3d} frame-edge={len(frame):3d} "
            f"sliced={len(sliced):3d} around-camera={len(around):3d}"
        )
        for name in sliced[:4]:
            print(f"        the frame slices: {name[:50]}")
    print(f"\n  clean props cut by the near plane: {near_total}")
    print(f"  clean props cut by the picture's edge: {frame_total}")
    print(f"  clean props the picture slices through the middle: {sliced_total}")
    print(f"  clean props the camera stands inside: {around_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
