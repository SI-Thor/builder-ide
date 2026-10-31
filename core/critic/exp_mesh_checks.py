"""Experiment: the mesh checks, scored on the rebuilt scenes.

The clean half and the defective half, on the same ten scenes: every mesh
check must stay quiet on a clean scene and fire on the member that carries
its own defect.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_mesh_checks.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import DEFAULT_THRESHOLDS, MESH_CHECKS  # noqa: E402
from core.critic.mesh import apply_mesh_defect, probe_scene  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
SCENES = Path("/home/caseydigennaro/lm-critic/scenes")

DEFECTS = ("wrong_scale", "hollow_mesh", "clipped_geometry")


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    print(f"scenes: {len(blends)}\n")
    tally = {defect: [0, 0] for defect in DEFECTS}
    clean_fired = {check.__name__: 0 for check in MESH_CHECKS}

    for blend in blends:
        name = blend.parent.parent.name
        stats = probe_scene(str(blend), python=PYTHON)
        if not stats.objects:
            print(f"  {name:12s} no geometry")
            continue
        line = [f"  {name:12s}"]
        for check in MESH_CHECKS:
            outcome = check(stats, DEFAULT_THRESHOLDS)
            if outcome.fired:
                clean_fired[check.__name__] += 1
            line.append(f"{check.__name__}={'FIRE' if outcome.fired else 'quiet'}")
        for defect in DEFECTS:
            try:
                broken, recipe = apply_mesh_defect(stats, defect, seed=7)
            except Exception as exc:  # noqa: BLE001
                line.append(f"{defect}=skip({type(exc).__name__})")
                continue
            target = {
                "wrong_scale": "check_scale_bounds",
                "hollow_mesh": "check_watertight",
                "clipped_geometry": "check_edge_cut",
            }[defect]
            fired = False
            for check in MESH_CHECKS:
                if check.__name__ != target:
                    continue
                fired = check(broken, DEFAULT_THRESHOLDS).fired
            tally[defect][0] += int(fired)
            tally[defect][1] += 1
            line.append(f"{defect}={'caught' if fired else 'MISSED'}")
        print(" ".join(line))

    print("\n=== the clean half ===")
    for check, count in clean_fired.items():
        print(f"  {check:20s} fired on {count}/{len(blends)} clean scenes")
    print("\n=== the defective half ===")
    for defect, (caught, total) in tally.items():
        print(f"  {defect:20s} caught {caught}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
