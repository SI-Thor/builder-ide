"""Experiment: the clipped-geometry margin, clean against planted.

The rule is "the picture cuts a prop near its middle". The margin is how
near the picture's edge a prop's middle lies, in that prop's own
half-width. This script measures the margin over the clean scenes and over
the scenes with a prop cut in half, so the threshold is a measurement.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_clip_margin.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import _cut_margin, props_of  # noqa: E402
from core.critic.mesh import apply_mesh_defect, probe_scene  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
SCENES = Path("/home/caseydigennaro/lm-critic/scenes")


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    clean: list[float] = []
    planted: list[float] = []
    for blend in blends:
        stats = probe_scene(str(blend), python=PYTHON)
        props = props_of(stats)
        if not props:
            continue
        margins = [m for m in (_cut_margin(stats.camera, o) for o in props) if m is not None]
        margins.sort()
        print(f"  {blend.parent.parent.name:12s} props={len(props):4d} cut={len(margins):3d}")
        if margins:
            print(
                f"      margins: min={margins[0]:.3f} p50={margins[len(margins)//2]:.3f} "
                f"max={margins[-1]:.3f}"
            )
        clean.extend(margins)
        broken, _ = apply_mesh_defect(stats, "clipped_geometry", seed=7)
        broken_props = props_of(broken)
        worst = None
        for obj in broken_props:
            margin = _cut_margin(broken.camera, obj)
            if margin is None:
                continue
            if worst is None or margin < worst:
                worst = margin
        if worst is not None:
            planted.append(worst)
    clean.sort()
    planted.sort()
    print(f"\n  clean margins: n={len(clean)}")
    if clean:
        print(
            f"      min={clean[0]:.4f} p50={clean[len(clean)//2]:.4f} max={clean[-1]:.4f}"
        )
    print(f"  planted margins: n={len(planted)}")
    if planted:
        print(
            f"      min={planted[0]:.4f} p50={planted[len(planted)//2]:.4f} "
            f"max={planted[-1]:.4f}"
        )
    print("\n  the separation:")
    for threshold in (0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20):
        fp = sum(1 for m in clean if m <= threshold)
        tp = sum(1 for m in planted if m <= threshold)
        print(
            f"      <= {threshold:5.3f}: clean {fp:3d}/{len(clean):3d}, "
            f"planted {tp:3d}/{len(planted):3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
