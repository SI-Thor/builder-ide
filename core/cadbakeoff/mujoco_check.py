"""The action check: does the prop do the thing, in MuJoCo.

The guards from physag-lite's brief apply here:

* the actuator is force-capped at a limit taken from the prop's own mass and
  the joint's lever arm, so a joint cannot be forced through geometry;
* the tolerance is relative — a share of the joint's range for a turn, a
  share of the body's size for a slide — not an absolute angle or distance;
* there is a rest baseline: a prop that is not stable at rest has no
  stability score, and it is flagged rather than passed;
* the action's target is the frozen one from the spec, never a smaller one.

The check reads the URDF the kernel produced. The URDF is converted to MJCF
by MuJoCo's own URDF reader, and the actuators are added by the same code for
both kernels, so what is measured is the prop and its robot description, not
whoever wrote the actuator.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ActionCheck", "check_action"]

TIMESTEP = 0.001
REST_SECONDS = 0.5
ACTION_SECONDS = 3.0
DWELL_STEPS = 50


@dataclass
class ActionCheck:
    ok: bool
    completed: bool = False
    stable: bool = False
    rest_stable: bool = False
    error: str | None = None
    stage: str = "check"
    joint_values: dict[str, float] = field(default_factory=dict)
    target: float | None = None
    target_spec: float | None = None
    target_unit: str | None = None
    tolerance: float | None = None
    tolerance_kind: str | None = None
    peak_force: float | None = None
    force_cap: float | None = None
    overshoot: float | None = None
    settling_ms: float | None = None
    max_penetration: float | None = None
    penetration_eps: float | None = None
    initial_penetrations: int = 0
    initial_max_penetration_mm: float | None = None
    bbox_diagonal_mm: float | None = None
    rest_drift: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "completed": self.completed,
            "stable": self.stable,
            "rest_stable": self.rest_stable,
            "error": self.error,
            "stage": self.stage,
            "target": self.target,
            "target_spec": self.target_spec,
            "target_unit": self.target_unit,
            "tolerance": self.tolerance,
            "tolerance_kind": self.tolerance_kind,
            "peak_force": self.peak_force,
            "force_cap": self.force_cap,
            "overshoot": self.overshoot,
            "settling_ms": self.settling_ms,
            "max_penetration": self.max_penetration,
            "penetration_eps": self.penetration_eps,
            "initial_penetrations": self.initial_penetrations,
            "initial_max_penetration_mm": self.initial_max_penetration_mm,
            "bbox_diagonal_mm": self.bbox_diagonal_mm,
            "rest_drift": self.rest_drift,
        }


def _patch_mjcf(
    mjcf_text: str,
    *,
    joint_axes: dict[str, tuple[float, float, float]],
    actuators: list[dict[str, Any]],
    excludes: list[tuple[str, str]],
    gravity: float = -9.81,
    meshdir: str | None = None,
) -> str:
    """Add the actuators, the ground and the contact exclusions."""
    root = ET.fromstring(mjcf_text)
    ET.register_namespace("", "")
    if root.tag == "mujoco" and not root.attrib.get("model"):
        root.set("model", "prop")

    compiler = root.find("compiler")
    if compiler is None:
        compiler = ET.Element("compiler")
        root.insert(0, compiler)
    if meshdir:
        compiler.set("meshdir", meshdir)

    option = root.find("option")
    if option is None:
        option = ET.Element("option")
        root.insert(0, option)
    option.set("timestep", str(TIMESTEP))
    option.set("gravity", f"0 0 {gravity}")
    option.set("integrator", "implicitfast")

    # The joint axes come from the URDF, not from MuJoCo's default.
    for joint_el in root.iter("joint"):
        name = joint_el.get("name")
        if name in joint_axes:
            axis = joint_axes[name]
            joint_el.set("axis", f"{axis[0]:.9g} {axis[1]:.9g} {axis[2]:.9g}")

    actuator_el = root.find("actuator")
    if actuator_el is None:
        actuator_el = ET.SubElement(root, "actuator")
    for act in actuators:
        el = ET.SubElement(actuator_el, "position")
        el.set("joint", act["joint"])
        el.set("kp", f"{act['kp']:.9g}")
        el.set("kv", f"{act['kv']:.9g}")
        el.set("ctrlrange", f"{act['ctrl_lo']:.9g} {act['ctrl_hi']:.9g}")
        el.set("forcerange", f"{-act['force_cap']:.9g} {act['force_cap']:.9g}")

    # A link that MuJoCo's URDF reader welded to the world has no body of
    # its own; the world is what it is called there.
    body_names = {b.get("name") for b in root.iter("body") if b.get("name")}
    body_names.add("world")
    contact_el = root.find("contact")
    if contact_el is None:
        contact_el = ET.SubElement(root, "contact")
    for a, b in excludes:
        el = ET.SubElement(contact_el, "exclude")
        el.set("body1", a if a in body_names else "world")
        el.set("body2", b if b in body_names else "world")

    # The ground the prop stands on.
    worldbody = root.find("worldbody")
    if worldbody is not None and worldbody.find("geom[@name='ground']") is None:
        ground = ET.SubElement(worldbody, "geom")
        ground.set("name", "ground")
        ground.set("type", "plane")
        ground.set("size", "5 5 0.1")
        ground.set("pos", "0 0 0")
        ground.set("contype", "1")
        ground.set("conaffinity", "1")

    return ET.tostring(root, encoding="unicode")


def _urdf_joint_axes(urdf_text: str) -> dict[str, tuple[float, float, float]]:
    """The world axis of every URDF joint, from its own origin and axis."""
    from core.cadbakeoff.urdf import rpy_to_matrix

    root = ET.fromstring(urdf_text)
    out: dict[str, tuple[float, float, float]] = {}
    for joint_el in root.findall("joint"):
        name = joint_el.get("name", "")
        axis_el = joint_el.find("axis")
        axis = (1.0, 0.0, 0.0)
        if axis_el is not None and axis_el.get("xyz"):
            parts = axis_el.get("xyz").split()
            axis = (float(parts[0]), float(parts[1]), float(parts[2]))
        origin_el = joint_el.find("origin")
        rpy = (0.0, 0.0, 0.0)
        if origin_el is not None and origin_el.get("rpy"):
            parts = origin_el.get("rpy").split()
            rpy = (float(parts[0]), float(parts[1]), float(parts[2]))
        rot = rpy_to_matrix(rpy)
        out[name] = tuple(
            sum(rot[i][k] * axis[k] for k in range(3)) for i in range(3)
        )
    return out


def _urdf_joint_limits(urdf_text: str) -> dict[str, tuple[float, float, str]]:
    root = ET.fromstring(urdf_text)
    out: dict[str, tuple[float, float, str]] = {}
    for joint_el in root.findall("joint"):
        name = joint_el.get("name", "")
        limit_el = joint_el.find("limit")
        lo = hi = 0.0
        if limit_el is not None:
            lo = float(limit_el.get("lower", "0"))
            hi = float(limit_el.get("upper", "0"))
        out[name] = (lo, hi, joint_el.get("type", "fixed"))
    return out


def check_action(
    urdf_path: str | Path,
    spec: dict[str, Any],
    workdir: str | Path,
    *,
    mujoco_module: Any = None,
) -> ActionCheck:
    """Run one prop's action in MuJoCo and score it."""
    import mujoco
    import numpy as np

    urdf_path = Path(urdf_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    urdf_text = urdf_path.read_text()
    check = ActionCheck(ok=False)

    # The joints the action drives.
    action = spec["action"]
    action_joints = list(action["joints"])
    joint_limits = _urdf_joint_limits(urdf_text)
    for name in action_joints:
        if name not in joint_limits:
            check.error = f"the URDF has no joint named {name!r}"
            return check

    try:
        model = mujoco.MjModel.from_xml_path(str(urdf_path))
    except Exception as exc:  # noqa: BLE001
        check.error = f"MuJoCo could not read the URDF: {exc}"
        return check

    # The moving body's mass and size, for the force cap and the tolerance.
    joint_names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(model.njnt)
    ]
    qpos_adr = {n: model.jnt_qposadr[i] for i, n in enumerate(joint_names) if n}

    masses = []
    for body_id in range(model.nbody):
        masses.append(float(model.body_mass[body_id]))
    total_mass = sum(masses) or 1.0

    # The moving body's bounding box diagonal, from the URDF's links.
    from core.cadbakeoff.urdf import parse_urdf
    from core.cadbakeoff.stl import read_stl

    urdf_model = parse_urdf(urdf_path)
    moving = {b["name"] for b in spec["bodies"] if b["role"] == "moving"}
    diagonals = []
    for body in spec["bodies"]:
        link = urdf_model.links.get(body["name"])
        if link is None or not link.visual_mesh:
            continue
        mesh_path = urdf_path.parent / link.visual_mesh
        if not mesh_path.exists():
            continue
        box = read_stl(mesh_path).bbox
        diag = math.sqrt(sum((box[i + 3] - box[i]) ** 2 for i in range(3))) * 1000.0
        if body["name"] in moving:
            diagonals.append(diag)
    bbox_diagonal = max(diagonals) if diagonals else 100.0
    check.bbox_diagonal_mm = bbox_diagonal

    actuators: list[dict[str, Any]] = []
    for name in action_joints:
        lo, hi, jtype = joint_limits[name]
        span = abs(hi - lo) or 1.0
        if jtype == "prismatic":
            # The force to lift the moving body, with a margin.
            force_cap = max(5.0, 4.0 * total_mass * 9.81)
            lever = 0.0
        else:
            # The torque to hold the body at the target, from its lever arm.
            lever = 0.0
            for body in spec["bodies"]:
                if body["name"] not in moving:
                    continue
                com = _spec_body_com(spec, body["name"])
                origin = [float(v) for v in _joint_origin(spec, name)]
                lever = max(
                    lever,
                    math.sqrt(
                        (com[0] - origin[0]) ** 2
                        + (com[1] - origin[1]) ** 2
                        + (com[2] - origin[2]) ** 2
                    )
                    / 1000.0,
                )
            force_cap = max(0.5, 4.0 * total_mass * 9.81 * lever)
        inertia = max(total_mass * (bbox_diagonal / 1000.0 / 2.0) ** 2, 1e-6)
        kp = 50.0 * total_mass * 9.81 / max(0.01 * span, 1e-4)
        # Keep the servo stable at the timestep.
        kp = min(kp, (0.15 / TIMESTEP) ** 2 * inertia)
        kp = max(kp, 1.0)
        kv = 2.0 * math.sqrt(kp * inertia) * 0.8
        actuators.append(
            {
                "joint": name,
                "kp": kp,
                "kv": kv,
                "ctrl_lo": min(lo, hi),
                "ctrl_hi": max(lo, hi),
                "force_cap": force_cap,
            }
        )
    check.force_cap = max(a["force_cap"] for a in actuators)

    # Contact exclusions: a joint's own parent and child do not collide.
    # The names are the URDF's own link names, which the model chose.
    from core.cadbakeoff.urdf import body_link_map

    links = body_link_map(urdf_model, spec)
    excludes = []
    for joint in spec["joints"]:
        parent = links.get(joint["parent"], joint["parent"])
        child = links.get(joint["child"], joint["child"])
        excludes.append((parent, child))

    axes = _urdf_joint_axes(urdf_text)
    converted = workdir / "converted.xml"
    mujoco.mj_saveLastXML(str(converted), model)
    mjcf_text = _patch_mjcf(
        converted.read_text(),
        joint_axes=axes,
        actuators=actuators,
        excludes=excludes,
        meshdir=str(urdf_path.parent.resolve()),
    )
    (workdir / "check.mjcf").write_text(mjcf_text)
    try:
        model = mujoco.MjModel.from_xml_path(str(workdir / "check.mjcf"))
    except Exception as exc:  # noqa: BLE001
        check.error = f"MuJoCo could not read the patched model: {exc}"
        return check
    data = mujoco.MjData(model)

    # The target and the relative tolerance.
    #
    # The joint's own unit is the unit the simulation speaks: radians for a
    # turn, metres for a slide. The spec carries a slide's distance in
    # millimetres, because the whole prop is designed in millimetres, so the
    # target is converted once here. The URDF's own limits are already in the
    # joint's unit, which is why the actuator's ctrlrange needs no conversion.
    target_spec = float(action["target"])
    first = action_joints[0]
    lo, hi, jtype = joint_limits[first]
    span = abs(hi - lo) or 1.0
    if jtype == "prismatic":
        target = target_spec / 1000.0
        tolerance = 0.005 * bbox_diagonal / 1000.0  # 0.5% of the diagonal
        tolerance_kind = "0.5% of the moving body's diagonal"
        target_unit = "m"
    else:
        target = target_spec
        tolerance = 0.02 * span  # 2% of the joint's range
        tolerance_kind = "2% of the joint's range"
        target_unit = "rad"
    check.target = target
    check.target_spec = target_spec
    check.target_unit = target_unit
    check.tolerance = tolerance
    check.tolerance_kind = tolerance_kind

    def joint_value(name: str) -> float:
        adr = qpos_adr.get(name)
        if adr is None:
            return 0.0
        return float(data.qpos[adr])

    def actuate(value: float) -> None:
        for act in actuators:
            data.ctrl[actuator_index(model, act["joint"])] = value

    # The rest baseline: the prop must be still before anything is asked of it.
    rest_steps = int(REST_SECONDS / TIMESTEP)
    for act in actuators:
        data.ctrl[actuator_index(model, act["joint"])] = act["ctrl_lo"]
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    # Hy4 guard 2 (physag-lite's checker has this as "initial penetrations"):
    # a prop that starts already inside itself, or inside the floor, has no
    # stability score to give. The count is taken at the first step, before
    # anything moves, against the same epsilon the run uses.
    penetration_eps_m = 0.005 * bbox_diagonal / 1000.0
    initial_penetrations = 0
    initial_max_penetration_m = 0.0
    for i in range(data.ncon):
        dist = float(data.contact[i].dist)
        if dist < 0:
            initial_max_penetration_m = max(initial_max_penetration_m, -dist)
            if -dist > penetration_eps_m:
                initial_penetrations += 1

    for _ in range(rest_steps):
        mujoco.mj_step(model, data)
    rest_value = joint_value(first)
    check.rest_drift = abs(rest_value - (actuators[0]["ctrl_lo"]))
    check.rest_stable = bool(check.rest_drift <= tolerance and np.all(np.isfinite(data.qpos)))
    check.initial_penetrations = initial_penetrations
    check.initial_max_penetration_mm = initial_max_penetration_m * 1000.0

    # The action.
    total_steps = int(ACTION_SECONDS / TIMESTEP)
    ramp_steps = int(0.5 / TIMESTEP)
    mujoco.mj_resetData(model, data)
    peak_force = 0.0
    max_pen = 0.0
    completed = False
    completed_at = None
    dwell = 0
    overshoot = 0.0
    settled = False
    for step in range(total_steps):
        fraction = min(1.0, (step + 1) / ramp_steps)
        actuate(actuators[0]["ctrl_lo"] + fraction * (target - actuators[0]["ctrl_lo"]))
        mujoco.mj_step(model, data)
        if data.actuator_force.size:
            peak_force = max(peak_force, float(np.max(np.abs(data.actuator_force))))
        for i in range(data.ncon):
            dist = float(data.contact[i].dist)
            if dist < 0:
                max_pen = max(max_pen, -dist)
        value = joint_value(first)
        error = value - target
        if abs(error) > abs(overshoot):
            overshoot = error
        if abs(error) <= tolerance:
            dwell += 1
            if dwell >= DWELL_STEPS and not completed:
                completed = True
                completed_at = step
        else:
            dwell = 0
        if not np.all(np.isfinite(data.qpos)) or np.max(np.abs(data.qvel)) > 1e4:
            break
    if completed:
        settled = True

    check.completed = completed
    check.peak_force = peak_force
    check.max_penetration = max_pen * 1000.0
    check.penetration_eps = 0.005 * bbox_diagonal
    check.overshoot = overshoot
    check.settling_ms = (completed_at * TIMESTEP * 1000.0) if completed_at is not None else None
    check.stable = bool(
        check.rest_stable
        and np.all(np.isfinite(data.qpos))
        and check.max_penetration <= (check.penetration_eps or 0.0)
    )
    check.completed = bool(completed)
    check.peak_force = float(peak_force)
    check.max_penetration = float(max_pen * 1000.0)
    check.overshoot = float(overshoot)
    check.ok = bool(completed and check.stable)
    if not check.ok and not check.error:
        reasons = []
        if not check.rest_stable:
            reasons.append("the prop is not stable at rest")
        if not completed:
            reasons.append("the action did not reach the target")
        if check.max_penetration > (check.penetration_eps or 0.0):
            reasons.append(
                f"the prop penetrates {check.max_penetration:.2f} mm, over the "
                f"{check.penetration_eps:.2f} mm limit"
            )
        if check.initial_penetrations:
            # Hy4 guard 2: a prop that starts inside itself has no stability
            # score to give, so the run is invalid rather than a pass.
            reasons.append(
                f"{check.initial_penetrations} contacts start inside the "
                f"{check.penetration_eps:.2f} mm limit"
            )
        check.error = "; ".join(reasons)
    return check


def actuator_index(model: Any, joint_name: str) -> int:
    import mujoco

    for i in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        if name == joint_name:
            return i
    # Fall back to the order the actuators were written in.
    return 0


def _joint_origin(spec: dict[str, Any], name: str) -> list[float]:
    from core.cadbakeoff.specs import expr

    params = dict(spec["parameters"])
    params["__density__"] = spec["density_kg_m3"]
    for joint in spec["joints"]:
        if joint["name"] == name:
            return [expr(v, params) for v in joint["origin"]]
    return [0.0, 0.0, 0.0]


def _spec_body_com(spec: dict[str, Any], body_name: str) -> tuple[float, float, float]:
    from core.cadbakeoff.analytic import evaluate_prop

    props = evaluate_prop(spec)
    for body in props.bodies:
        if body.name == body_name:
            return body.centre
    return (0.0, 0.0, 0.0)
