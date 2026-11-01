#!/usr/bin/env python3
"""The CAD arm: the same planner, the same checker, CAD geometry instead.

The TRELLIS arm guesses where the parts of a prop are, because a generated
mesh does not say. The CAD arm does not have to guess: the kernel that
built the prop made the parts, one body each, and the URDF says which
body is which and where the joint is.

So the arms differ in one thing — where the geometry comes from — and share
everything else: the same plans, the same priors, the same decomposition,
the same MJCF builder, the same checker, the same repair rule, the same
delivery record.

What the CAD arm does *not* get for free is the planner's claim about
where the moving part is. The geometry is exact, so the claim is still a
claim, and it is still measured against the geometry the kernel produced.
That is the one thing the CAD arm can say that the TRELLIS arm cannot: it
separates "the planner guessed the part wrongly" from "the mesh is not
what the planner thought".

The designs come from cad-bakeoff's recorded cloud answers
(``out/gen/<prop>.solidcraft.json``); this seat does not write CAD
scripts, it builds them and runs them through its own checker.

Usage::

    python docs/lab/physag-lite/run_cad_arm.py \\
        --designs ~/lm-wt/cad-bakeoff/out/gen \\
        --specs docs/lab/physag-lite/specs \\
        --out artifacts/physag-lite/run-cad
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.physag.geometry import (  # noqa: E402
    MeshPart,
    apply_transform,
    prop_frame_transform,
)
from core.physag.pipeline import delivery_for, run_prop  # noqa: E402
from core.physag.spec import (  # noqa: E402
    Action,
    Cut,
    InteractionSpec,
    Joint,
    Part,
    load_spec,
)

SOLIDCRAFT = Path("~/lm-wt/cad-bakeoff/solidcraft/target/release/solidcraft-cli").expanduser()


# ---------------------------------------------------------------------------
# URDF
# ---------------------------------------------------------------------------


def _rpy_to_matrix(rpy: tuple[float, float, float]) -> np.ndarray:
    """The rotation matrix for a URDF fixed-axis rpy, in radians."""
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def _transform(xyz: tuple[float, float, float], rpy: tuple[float, float, float]) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = _rpy_to_matrix(rpy)
    matrix[:3, 3] = np.asarray(xyz, dtype=np.float64)
    return matrix


def _origin_of(element: ET.Element | None) -> tuple[np.ndarray, tuple[float, float, float]]:
    if element is None:
        return np.zeros(3), (0.0, 0.0, 0.0)
    xyz = np.asarray(
        [float(v) for v in element.get("xyz", "0 0 0").split()], dtype=np.float64
    )
    rpy = tuple(float(v) for v in element.get("rpy", "0 0 0").split())
    while len(rpy) < 3:
        rpy = rpy + (0.0,)
    return xyz, rpy  # type: ignore[return-value]


@dataclass
class UrdfLink:
    name: str
    mesh: Path
    #: The link's own mesh origin (its ``<visual>``/``<collision>`` origin).
    local: np.ndarray
    #: The link's place in the robot's frame.
    world: np.ndarray


@dataclass
class UrdfJoint:
    name: str
    kind: str
    parent: str
    child: str
    origin_xyz: np.ndarray
    origin_rpy: tuple[float, float, float]
    axis: np.ndarray
    low: float
    high: float


@dataclass
class Urdf:
    links: dict[str, UrdfLink]
    joints: dict[str, UrdfJoint]
    #: The link that everything hangs off.
    root: str


def _read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import trimesh

    mesh = trimesh.load(path, force="mesh")
    return (
        np.asarray(mesh.vertices, dtype=np.float64),
        np.asarray(mesh.faces, dtype=np.int64),
    )


def parse_urdf(path: Path) -> Urdf:
    """Read a URDF: the links with meshes, and the joints between them."""
    root = ET.parse(path).getroot()
    base = path.parent

    joints: dict[str, UrdfJoint] = {}
    for element in root.findall("joint"):
        xyz, rpy = _origin_of(element.find("origin"))
        axis_element = element.find("axis")
        axis = np.asarray(
            [float(v) for v in (axis_element.get("xyz", "1 0 0") if axis_element is not None else "1 0 0").split()],
            dtype=np.float64,
        )
        limit = element.find("limit")
        low = float(limit.get("lower", "0.0")) if limit is not None else 0.0
        high = float(limit.get("upper", "0.0")) if limit is not None else 0.0
        parent = element.find("parent")
        child = element.find("child")
        joints[element.get("name", "")] = UrdfJoint(
            name=element.get("name", ""),
            kind=element.get("type", "fixed"),
            parent=parent.get("link", "") if parent is not None else "",
            child=child.get("link", "") if child is not None else "",
            origin_xyz=xyz,
            origin_rpy=rpy,
            axis=axis,
            low=low,
            high=high,
        )

    links: dict[str, UrdfLink] = {}
    for element in root.findall("link"):
        name = element.get("name", "")
        geometry = element.find("collision")
        if geometry is None:
            geometry = element.find("visual")
        if geometry is None:
            continue
        mesh_element = geometry.find("geometry/mesh")
        if mesh_element is None:
            continue
        filename = mesh_element.get("filename", "")
        xyz, rpy = _origin_of(geometry.find("origin"))
        links[name] = UrdfLink(
            name=name,
            mesh=base / filename,
            local=_transform(tuple(xyz), rpy),
            world=np.eye(4),
        )

    # The world transform of each link: the chain of joints down to it.
    by_child = {joint.child: joint for joint in joints.values()}

    def _resolve(name: str) -> np.ndarray:
        link = links.get(name)
        if link is not None and not np.allclose(link.world, np.eye(4)):
            return link.world
        joint = by_child.get(name)
        if joint is None:
            return np.eye(4)
        parent_world = _resolve(joint.parent)
        world = parent_world @ _transform(tuple(joint.origin_xyz), joint.origin_rpy)
        if name in links:
            links[name].world = world
        return world

    roots = [name for name in links if name not in by_child]
    root_name = roots[0] if roots else ""
    for name in list(links):
        _resolve(name)

    return Urdf(links=links, joints=joints, root=root_name)


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def build_design(design: Path, workdir: Path) -> tuple[Path | None, str | None]:
    """Run the SolidCraft design and write the URDF beside its meshes."""
    workdir.mkdir(parents=True, exist_ok=True)
    script = json.loads(design.read_text())
    commands = list(script.get("commands", []))
    if not any(
        c.get("command") == "file.export"
        and str(c.get("params", {}).get("path", "")).endswith(".urdf")
        for c in commands
        if isinstance(c, dict)
    ):
        commands.append(
            {"command": "file.export", "params": {"path": "robot.urdf", "format": "urdf"}}
        )
    commands.append({"command": "assembly.mass_properties", "params": {}})
    target = workdir / "script.json"
    target.write_text(json.dumps({"commands": commands}, indent=1))

    proc = subprocess.run(
        [str(SOLIDCRAFT), "run", str(target), "--out", "prop.step", "--results"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=900,
    )
    (workdir / "stdout.txt").write_text(proc.stdout)
    (workdir / "stderr.txt").write_text(proc.stderr)
    if proc.returncode != 0:
        message = (proc.stderr.strip() or proc.stdout.strip() or "the build failed")[:600]
        return None, message
    urdf = workdir / "robot.urdf"
    if not urdf.exists():
        return None, "the build wrote no URDF"
    return urdf, None


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------


@dataclass
class CadProp:
    """A prop the CAD kernel built, in the prop frame."""

    mesh: MeshPart
    parts: dict[str, MeshPart]
    joint: UrdfJoint
    anchor: np.ndarray
    axis: np.ndarray
    low: float
    high: float


def _mesh_parts(
    urdf: Urdf, moving_link: str
) -> tuple[MeshPart, dict[str, MeshPart], np.ndarray, np.ndarray, float, float]:
    """The prop's mesh and its parts, in the prop frame."""
    raw: dict[str, np.ndarray] = {}
    faces: dict[str, np.ndarray] = {}
    for name, link in urdf.links.items():
        vertices, triangles = _read_stl(link.mesh)
        world = link.world @ link.local
        raw[name] = apply_transform(world, vertices)
        faces[name] = triangles

    merged = np.concatenate([raw[name] for name in raw], axis=0)
    matrix = prop_frame_transform(merged)
    merged_prop = apply_transform(matrix, merged)

    parts: dict[str, MeshPart] = {}
    merged_faces: list[np.ndarray] = []
    offset = 0
    for name in raw:
        vertices = apply_transform(matrix, raw[name])
        # The part's own triangles index its own vertices; the merged
        # mesh's index the merged ones.
        parts[name] = MeshPart(vertices=vertices, triangles=faces[name])
        merged_faces.append(faces[name] + offset)
        offset += vertices.shape[0]

    # The joint's anchor and axis, in the prop frame.
    joint = None
    for candidate in urdf.joints.values():
        if candidate.child == moving_link and candidate.kind != "fixed":
            joint = candidate
            break
    if joint is None:
        raise ValueError("the URDF has no moving joint to that link")

    parent_world = urdf.links[joint.parent].world if joint.parent in urdf.links else np.eye(4)
    anchor_world = parent_world[:3, :3] @ joint.origin_xyz + parent_world[:3, 3]
    axis_in_parent = _rpy_to_matrix(joint.origin_rpy) @ joint.axis
    axis_world = parent_world[:3, :3] @ axis_in_parent
    norm = float(np.linalg.norm(axis_world))
    if norm > 1e-9:
        axis_world = axis_world / norm

    origin = merged_prop.min(axis=0)
    size = merged_prop.max(axis=0) - origin
    anchor_norm = (apply_transform(matrix, anchor_world[None, :])[0] - origin) / np.maximum(size, 1e-9)

    return (
        MeshPart(
            vertices=merged_prop,
            triangles=(
                np.concatenate(merged_faces, axis=0)
                if merged_faces
                else np.zeros((0, 3), dtype=np.int64)
            ),
        ),
        parts,
        anchor_norm,
        axis_world,
        joint.low,
        joint.high,
    )


def build_cad_prop(urdf_path: Path, base_part: str, moving_part: str) -> CadProp:
    """Read a URDF into a prop with its parts, its joint and its anchor."""
    urdf = parse_urdf(urdf_path)
    moving_link = None
    for joint in urdf.joints.values():
        if joint.kind != "fixed" and joint.child in urdf.links:
            moving_link = joint.child
            break
    if moving_link is None:
        raise ValueError("the URDF has no moving joint")

    mesh, parts, anchor, axis, low, high = _mesh_parts(urdf, moving_link)

    # The base is everything that is not the moving link: the kernel may
    # have made it several bodies, and they are all the thing that holds
    # the moving one up.
    base_vertices = []
    base_faces = []
    offset = 0
    for name, part in parts.items():
        if name == moving_link:
            continue
        base_vertices.append(part.vertices)
        base_faces.append(part.triangles + offset)
        offset += part.vertices.shape[0]
    base = MeshPart(
        vertices=np.concatenate(base_vertices, axis=0) if base_vertices else np.zeros((0, 3)),
        triangles=np.concatenate(base_faces, axis=0) if base_faces else np.zeros((0, 3), dtype=np.int64),
    )

    return CadProp(
        mesh=mesh,
        parts={base_part: base, moving_part: parts[moving_link]},
        joint=next(j for j in urdf.joints.values() if j.child == moving_link),
        anchor=anchor,
        axis=axis,
        low=low,
        high=high,
    )


def cad_spec(
    plan: InteractionSpec,
    cad: CadProp,
    base_part: str,
    moving_part: str,
) -> InteractionSpec:
    """The plan, with the CAD arm's geometry and joint.

    The planner's *claims* — the ``expect`` boxes, the priors, the action's
    band — are kept: they are what the CAD arm measures the CAD against.
    The geometry and the joint come from the kernel, because the kernel is
    the authority on both.

    The action and the joint limits are the planner's, not the CAD's: the
    repair rule freezes them, and the completion rate is a statement about
    the props the planner asked for. The target is the planner's target,
    clipped to the CAD joint's own range — the kernel says how far the
    hinge goes, and a target outside it would measure nothing.
    """
    parts = []
    for part in plan.parts:
        name = base_part if part.role == "base" else moving_part
        # The base is what no other part claimed; the moving part keeps
        # the plan's cut, which is the planner's claim about where it is.
        # The cut does not clip anything in this arm — the geometry is
        # exact — but the spec still has to say where the planner thought
        # the part was, and that is what the claim is measured against.
        parts.append(
            Part(
                name=name,
                role=part.role,
                cut=Cut(kind="rest") if part.role == "base" else part.cut,
                expect=part.expect,
                density_kg_m3=part.density_kg_m3,
            )
        )

    joints = []
    for joint in plan.joints:
        low = max(joint.low, cad.low)
        high = min(joint.high, cad.high)
        if high <= low:
            low, high = cad.low, cad.high
        joints.append(
            Joint(
                name=joint.name,
                type=joint.type,
                parent=base_part if joint.parent == plan.parts[0].name else moving_part,
                child=moving_part if joint.child != plan.parts[0].name else base_part,
                axis=tuple(float(v) for v in cad.axis),
                anchor=tuple(float(v) for v in cad.anchor),
                low=low,
                high=high,
                damping=joint.damping,
                armature=joint.armature,
            )
        )

    action = plan.action
    if action.joint:
        joint = joints[0]
        target = min(max(action.target, joint.low), joint.high)
        action = Action(
            kind=action.kind,
            joint=action.joint,
            target=target,
            axis=action.axis,
            duration_s=action.duration_s,
            tolerance_rel=action.tolerance_rel,
            dwell_steps=action.dwell_steps,
            drive=action.drive,
        )

    return InteractionSpec(
        prop=plan.prop,
        kind=plan.kind,
        image_prompt=plan.image_prompt,
        parts=tuple(parts),
        joints=tuple(joints),
        action=action,
        priors=plan.priors,
        basis=dict(plan.basis),
        planner=plan.planner,
    )


# ---------------------------------------------------------------------------
# The arm
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--designs", required=True, type=Path, help="the SolidCraft designs")
    parser.add_argument("--specs", required=True, type=Path, help="where the plans are")
    parser.add_argument("--out", required=True, type=Path, help="where to write the records")
    parser.add_argument("--work", type=Path, default=None, help="where to build")
    parser.add_argument("--props", default="", help="a space-separated list; default: every plan")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    work_root = args.work or (args.out / "build")

    if args.props:
        props = args.props.split()
    else:
        props = sorted(
            p.stem for p in args.specs.glob("*.json") if not p.stem.endswith(".repair")
        )

    records: list[dict[str, Any]] = []
    for prop in props:
        plan_path = args.specs / f"{prop}.json"
        design_path = args.designs / f"{prop}.solidcraft.json"
        if not plan_path.exists():
            print(f"!! {prop}: no plan at {plan_path}", file=sys.stderr)
            continue
        if not design_path.exists():
            print(f"!! {prop}: no CAD design at {design_path}", file=sys.stderr)
            continue

        plan = load_spec(plan_path)
        base_part = next((p.name for p in plan.parts if p.role == "base"), "body")
        moving_part = next((p.name for p in plan.parts if p.role == "moving"), "lid")

        print(f"== {prop} (cad)")
        started = time.perf_counter()
        urdf_path, error = build_design(design_path, work_root / prop)
        if urdf_path is None:
            print(f"!! {prop}: the CAD build failed: {error}", file=sys.stderr)
            records.append(
                {
                    "prop": prop,
                    "arm": "cad",
                    "interaction_status": "not_run",
                    "physics_status": "invalid",
                    "counted": False,
                    "error": error,
                    "notes": ["the CAD build failed"],
                }
            )
            continue

        try:
            cad = build_cad_prop(urdf_path, base_part, moving_part)
        except Exception as exc:
            print(f"!! {prop}: the URDF could not be read: {exc}", file=sys.stderr)
            records.append(
                {
                    "prop": prop,
                    "arm": "cad",
                    "interaction_status": "not_run",
                    "physics_status": "invalid",
                    "counted": False,
                    "error": str(exc),
                    "notes": ["the URDF could not be read"],
                }
            )
            continue

        spec = cad_spec(plan, cad, base_part, moving_part)

        prop_dir = args.out / prop
        prop_dir.mkdir(parents=True, exist_ok=True)
        try:
            run = run_prop(
                spec,
                urdf_path,  # the mesh is already in memory; the path is unused
                out_dir=prop_dir,
                planner=None,
                parts=cad.parts,
                mesh=cad.mesh,
            )
        except Exception as exc:
            print(f"!! {prop}: {type(exc).__name__}: {exc}", file=sys.stderr)
            (prop_dir / "error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
            records.append(
                {
                    "prop": prop,
                    "arm": "cad",
                    "interaction_status": "not_run",
                    "physics_status": "invalid",
                    "counted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "notes": ["the prop did not build"],
                }
            )
            continue
        wall = time.perf_counter() - started

        delivery = delivery_for(run, arm="cad")
        delivery.timings["wall_s"] = round(wall, 3)
        delivery.timings["cad_build_s"] = round(run.timings.get("load_mesh_s", 0.0), 4)
        delivery.save(prop_dir / "delivery.json")

        result = run.result
        print(
            f"   interaction={delivery.interaction_status} "
            f"physics={delivery.physics_status} "
            f"completed={result.completion.completed if result else None} "
            f"wall={wall:.1f}s"
        )
        for name, piece in run.segmentation.pieces.items():
            print(
                f"      {name}: triangles={piece.triangles} iou={piece.bbox_iou:.2f} "
                f"verified={piece.verified}"
            )
        if result is not None:
            for reason in result.stability.reasons:
                print(f"      ! {reason}")
        records.append(delivery.to_dict())

    counted = [r for r in records if r.get("counted")]
    completed = [r for r in counted if r.get("interaction_status") == "completed"]
    stable = [r for r in counted if r.get("physics_status") == "stable"]
    valid = [r for r in counted if r.get("physics_status") in ("stable", "unstable")]

    summary = {
        "arm": "cad",
        "props": len(records),
        "counted": len(counted),
        "completed": len(completed),
        "completion_rate": round(len(completed) / len(counted), 4) if counted else None,
        "stable": len(stable),
        "stable_of_counted": round(len(stable) / len(counted), 4) if counted else None,
        "physics_valid_of_counted": round(len(valid) / len(counted), 4) if counted else None,
        "not_counted": [r["prop"] for r in records if not r.get("counted")],
        "statuses": {
            r["prop"]: {
                "interaction_status": r.get("interaction_status"),
                "physics_status": r.get("physics_status"),
                "counted": r.get("counted"),
            }
            for r in records
        },
        "wall_s_total": round(sum(r.get("timings", {}).get("wall_s", 0.0) for r in records), 2),
        "wall_s_per_prop": round(
            sum(r.get("timings", {}).get("wall_s", 0.0) for r in records) / len(records), 2
        )
        if records
        else None,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
