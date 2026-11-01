#!/usr/bin/env python3
"""Does a crate lid hinged about Y work, and one hinged about X?

The crate's spec says the lid hinge runs along Y at the back edge. A lid on
the back edge of a box should turn about the back edge itself, which runs
along X. This measures both, so the spec is settled by the simulator rather
than by an argument.

    python -m core.cadbakeoff.axis_probe
"""

from __future__ import annotations

import json
import pathlib
import sys

from core.cadbakeoff.build import build_solidcraft
from core.cadbakeoff.mujoco_check import check_action
from core.cadbakeoff.specs import PROPS
from core.cadbakeoff.validate import load_registry

ROOT = pathlib.Path.home() / "lm-wt/cad-bakeoff"
CLI = ROOT / "solidcraft/target/release/solidcraft-cli"
REGISTRY = ROOT / "registry.json"

SCRIPT = [
    {"command": "parameters.add", "params": {"name": "width", "expression": "400", "unit": "mm"}},
    {"command": "parameters.add", "params": {"name": "depth", "expression": "300", "unit": "mm"}},
    {"command": "parameters.add", "params": {"name": "height", "expression": "250", "unit": "mm"}},
    {"command": "parameters.add", "params": {"name": "plank", "expression": "18", "unit": "mm"}},
    {"command": "solid.box", "params": {"length": "width", "width": "depth", "height": "plank", "corner": ["-width/2", "-depth/2", "0"], "body_name": "floor"}},
    {"command": "solid.box", "params": {"length": "width", "width": "plank", "height": "height - 2*plank", "corner": ["-width/2", "-depth/2 + plank", "plank"], "body_name": "wall_front"}},
    {"command": "solid.box", "params": {"length": "width", "width": "plank", "height": "height - 2*plank", "corner": ["-width/2", "depth/2 - plank", "plank"], "body_name": "wall_back"}},
    {"command": "solid.combine", "params": {"target": "floor", "tools": ["wall_front", "wall_back"], "operation": "join"}},
    {"command": "solid.box", "params": {"length": "width", "width": "depth", "height": "plank", "corner": ["-width/2", "-depth/2", "height - plank"], "body_name": "lid"}},
    {"command": "material.create", "params": {"name": "PropWood", "density_g_cm3": 0.7}},
    {"command": "material.assign", "params": {"bodies": ["floor", "lid"], "material": "PropWood"}},
    {"command": "component.from_bodies", "params": {"bodies": ["floor", "lid"]}},
    # The axis is the only thing that changes between the two runs.
    {"command": "joint.create", "params": {"type": "revolute", "a": {"occurrence": "floor", "point": [0, 150, 232], "z": [0, 1, 0]}, "b": {"occurrence": "lid", "point": [0, 150, 232], "z": [0, 1, 0]}, "limits": [[0, 90]], "flip": True, "name": "lid_hinge"}},
    {"command": "file.export", "params": {"path": "robot.urdf", "format": "urdf"}},
]


def with_axis(axis: list[int]) -> list[dict]:
    out = json.loads(json.dumps(SCRIPT))
    for command in out:
        if command["command"] == "joint.create":
            command["params"]["a"]["z"] = axis
            command["params"]["b"]["z"] = axis
    return out


def main() -> int:
    registry = load_registry(REGISTRY)
    spec = json.loads(json.dumps(PROPS["crate"]))
    for axis, label in (([0, 1, 0], "along Y (the spec today)"), ([1, 0, 0], "along X (the back edge)")):
        work = ROOT / "work" / f"axis_probe_{''.join(str(v) for v in axis)}"
        work.mkdir(parents=True, exist_ok=True)
        script = work / "script.json"
        script.write_text(json.dumps({"commands": with_axis(axis)}, indent=1))
        build = build_solidcraft("crate", script, work, cli=CLI, registry=registry)
        print(f"axis {axis} {label}: built = {build.ok} error = {build.error}")
        if not build.ok:
            continue
        urdf = work / "robot.urdf"
        print("   urdf:", urdf.exists())
        check = check_action(urdf, spec, work / "check")
        print(
            f"   action ok={check.ok} completed={check.completed} stable={check.stable} "
            f"pen={check.max_penetration} eps={check.penetration_eps} error={check.error}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
