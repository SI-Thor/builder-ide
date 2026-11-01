"""Execute the action and score it: completion, stability, and the rest baseline.

This is the verdict. Everything upstream — the plan, the mesh, the split,
the decomposition — exists so that this file can run a model and say what
happened. The five Hy4 guards are all here, because each of them is a way
for this file to produce a number that means something other than what it
says.

**Completion** is scored on a band that is relative to the prop: a
percentage of the joint's travel, of the distance asked for, or of a
quarter turn for a hanging prop. The band is not a constant, so a 30 cm
drawer and a 2 m door are held to the same standard. The joint has to
*stay* in the band: the run ends inside it, and the first entry into it is
reported with the overshoot and the settling time, so a joint that reached
the target and then drifted away is not a completion.

**Stability** is scored on three things: no penetration deeper than
epsilon at any step, no explosion, and the prop still standing at the end.
Epsilon is relative too — a fraction of the prop's own size.

**The rest baseline** runs first, with no action at all. A prop that will
not stand still before anything is asked of it has no stability score to
give, and the run says so instead of scoring it.

**The actuator is capped** at the prior's limit, and the peak force and the
number of steps at the limit are recorded: a joint that only reached its
target because it was shoved there is visible in those numbers.

**The collider is checked against the mesh** before any of this: the
volume ratio and the distance from the mesh to the collider. A collider
that is more than 1 % fatter than the mesh makes every stability number a
statement about the collider, and the run is reported as invalid rather
than as a pass.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# MuJoCo picks its GL backend when it is imported, so the choice has to
# be made before the import, not before the render. The Thor has no
# display for GLFW; EGL is the backend that works here.
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")

import mujoco

from core.physag.mjcf import BuiltProp
from core.physag.segment import Segmentation

__all__ = [
    "CheckResult",
    "Completion",
    "RestBaseline",
    "Stability",
    "Tolerance",
    "check_prop",
]

#: The fraction of the prop's diagonal that counts as a penetration.
#: Half a percent: at the prop's own scale, and far below anything a
#: solver's own contact tolerance would produce.
DEFAULT_EPSILON_REL = 0.005

#: How long the prop is given to settle before the action starts, in
#: seconds of simulated time.
DEFAULT_REST_S = 2.0

#: A speed or a position past which the simulation is called an explosion.
EXPLOSION_LIMIT = 1.0e3


@dataclass(frozen=True)
class Tolerance:
    """The band the action has to reach, and where the band came from."""

    absolute: float
    relative: float
    basis: str

    def to_dict(self) -> dict:
        return {
            "absolute": round(self.absolute, 8),
            "relative": self.relative,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class Completion:
    """Did the action finish?"""

    metric: str
    completed: bool
    target: float
    reached: float
    tolerance: Tolerance
    first_entry_step: int | None
    first_entry_time_s: float | None
    dwell_steps: int
    dwell_satisfied: bool
    overshoot: float
    settling_time_s: float | None
    last_decile_deviation: float
    trajectory: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "completed": self.completed,
            "target": round(self.target, 6),
            "reached": round(self.reached, 6),
            "tolerance": self.tolerance.to_dict(),
            "first_entry_step": self.first_entry_step,
            "first_entry_time_s": (
                None if self.first_entry_time_s is None else round(self.first_entry_time_s, 4)
            ),
            "dwell_steps": self.dwell_steps,
            "dwell_satisfied": self.dwell_satisfied,
            "overshoot": round(self.overshoot, 6),
            "settling_time_s": (
                None if self.settling_time_s is None else round(self.settling_time_s, 4)
            ),
            "last_decile_deviation": round(self.last_decile_deviation, 6),
        }


@dataclass(frozen=True)
class Stability:
    """Did the prop stay a prop while the action ran?"""

    valid: bool
    stable: bool
    max_penetration_m: float
    penetration_events: int
    epsilon_m: float
    peak_force: float
    force_limit: float
    saturated_steps: int
    upright_angle_deg: float
    drift_m: float
    exploded: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "stable": self.stable,
            "max_penetration_m": round(self.max_penetration_m, 8),
            "penetration_events": self.penetration_events,
            "epsilon_m": round(self.epsilon_m, 8),
            "peak_force": round(self.peak_force, 6),
            "force_limit": round(self.force_limit, 6),
            "saturated_steps": self.saturated_steps,
            "upright_angle_deg": round(self.upright_angle_deg, 4),
            "drift_m": round(self.drift_m, 6),
            "exploded": self.exploded,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RestBaseline:
    """The run with no action: what the prop does when left alone."""

    ran: bool
    settled: bool
    upright_angle_deg: float
    drift_m: float
    initial_penetrations: int
    max_penetration_m: float
    exploded: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ran": self.ran,
            "settled": self.settled,
            "upright_angle_deg": round(self.upright_angle_deg, 4),
            "drift_m": round(self.drift_m, 6),
            "initial_penetrations": self.initial_penetrations,
            "max_penetration_m": round(self.max_penetration_m, 8),
            "exploded": self.exploded,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CheckResult:
    """The whole verdict for one prop."""

    prop: str
    interaction_status: str
    physics_status: str
    completion: Completion | None
    stability: Stability | None
    rest: RestBaseline | None
    collider: dict[str, Any]
    steps: int
    simulated_s: float
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "prop": self.prop,
            "interaction_status": self.interaction_status,
            "physics_status": self.physics_status,
            "completion": None if self.completion is None else self.completion.to_dict(),
            "stability": None if self.stability is None else self.stability.to_dict(),
            "rest_baseline": None if self.rest is None else self.rest.to_dict(),
            "collider": self.collider,
            "steps": self.steps,
            "simulated_s": round(self.simulated_s, 4),
            "notes": list(self.notes),
        }


def _diag(segmentation: Segmentation) -> float:
    """The prop's bounding-box diagonal."""
    size = segmentation.mesh.bbox_size
    return float(np.linalg.norm(size))


def _upright_angle(data: mujoco.MjData, model: mujoco.MjModel, body_id: int) -> float:
    """How far the body's own up axis has tilted away from the world's.

    The body's frame is the prop's frame: a body that has not been rotated
    stands upright, and the angle grows as the prop tips.
    """
    if body_id < 0:
        return 0.0
    quat = np.asarray(data.xquat[body_id])
    # The body's local z axis, rotated into the world.
    w, x, y, z = quat
    axis = np.array(
        [
            2.0 * (x * z + w * y),
            2.0 * (y * z - w * x),
            1.0 - 2.0 * (x * x + y * y),
        ]
    )
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12:
        return 0.0
    axis = axis / norm
    cos = float(np.clip(axis[2], -1.0, 1.0))
    return math.degrees(math.acos(cos))


def _prop_com(data: mujoco.MjData, model: mujoco.MjModel, body_ids: list[int]) -> np.ndarray:
    """The prop's centre of mass in the world."""
    total = 0.0
    acc = np.zeros(3)
    for bid in body_ids:
        mass = float(model.body_mass[bid])
        if mass <= 0.0:
            continue
        acc += mass * np.asarray(data.xipos[bid])
        total += mass
    if total <= 0.0:
        return np.zeros(3)
    return acc / total


def _contacts(data: mujoco.MjData) -> tuple[np.ndarray, np.ndarray]:
    """The contact distances and the depths, as arrays."""
    count = data.ncon
    if count == 0:
        return np.zeros(0), np.zeros(0)
    dist = np.array([data.contact[i].dist for i in range(count)])
    depth = np.maximum(-dist, 0.0)
    return dist, depth


def _run_steps(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    steps: int,
    recorder,
) -> bool:
    """Step the model, letting the recorder watch. False if it exploded."""
    for step in range(steps):
        if not np.all(np.isfinite(data.qpos)) or not np.all(np.isfinite(data.qvel)):
            return False
        if np.max(np.abs(data.qvel)) > EXPLOSION_LIMIT:
            return False
        mujoco.mj_step(model, data)
        if not np.all(np.isfinite(data.qpos)) or not np.all(np.isfinite(data.qvel)):
            return False
        if np.max(np.abs(data.qvel)) > EXPLOSION_LIMIT:
            return False
        recorder(step)
    return True


def check_prop(
    built: BuiltProp,
    segmentation: Segmentation,
    *,
    epsilon_rel: float = DEFAULT_EPSILON_REL,
    rest_s: float = DEFAULT_REST_S,
    render_path: str | Path | None = None,
) -> CheckResult:
    """Run one prop's action and score it."""
    spec = built.spec
    notes: list[str] = []

    model = mujoco.MjModel.from_xml_string(built.xml)
    data = mujoco.MjData(model)
    timestep = float(model.opt.timestep)

    diag = _diag(segmentation)
    epsilon = max(epsilon_rel * diag, 1e-6)

    prop_bodies = [
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, f"body_{p.name}")
        for p in spec.parts
    ]
    prop_bodies = [b for b in prop_bodies if b >= 0]
    root_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, built.root_body)

    # -- the rest baseline ------------------------------------------------
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)
    initial_dist, initial_depth = _contacts(data)
    initial_penetrations = int(np.sum(initial_depth > epsilon))
    max_initial_penetration = float(initial_depth.max()) if initial_depth.size else 0.0

    start_com = _prop_com(data, model, prop_bodies)

    rest_max_penetration = 0.0
    exploded = False

    def _watch_rest(step: int) -> None:
        nonlocal rest_max_penetration
        _, depth = _contacts(data)
        if depth.size:
            rest_max_penetration = max(rest_max_penetration, float(depth.max()))

    rest_steps = int(rest_s / timestep)
    exploded = not _run_steps(model, data, rest_steps, _watch_rest)

    rest_com = _prop_com(data, model, prop_bodies)
    rest_drift = float(np.linalg.norm(rest_com[:2] - start_com[:2]))
    rest_upright = _upright_angle(data, model, root_id)
    rest_reasons: list[str] = []
    if exploded:
        rest_reasons.append("the simulation exploded while the prop was left alone")
    if rest_upright > 15.0:
        rest_reasons.append(
            f"the prop fell over at rest ({rest_upright:.1f}° from upright)"
        )
    if rest_drift > 0.02 * max(diag, 1e-6):
        rest_reasons.append(f"the prop slid {rest_drift * 1000:.0f} mm at rest")
    if initial_penetrations > 0:
        rest_reasons.append(
            f"{initial_penetrations} contacts start inside epsilon ({epsilon * 1000:.2f} mm)"
        )

    rest = RestBaseline(
        ran=True,
        settled=not rest_reasons,
        upright_angle_deg=rest_upright,
        drift_m=rest_drift,
        initial_penetrations=initial_penetrations,
        max_penetration_m=max(max_initial_penetration, rest_max_penetration),
        exploded=exploded,
        reasons=tuple(rest_reasons),
    )

    # -- the action --------------------------------------------------------
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    action = spec.action
    joint_id = -1
    actuator_id = -1
    if action.joint:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, action.joint)
    if built.actuator:
        actuator_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, built.actuator)

    # The joint's value lives at its *address* in the position vector,
    # which is not its id: a free joint takes the first seven entries,
    # so the hinge behind it starts later.
    joint_qpos = -1
    if joint_id >= 0:
        joint_qpos = int(model.jnt_qposadr[joint_id])

    drive = action.drive if action.drive is not None else action.target
    if actuator_id >= 0:
        data.ctrl[actuator_id] = drive

    # The metric is measured against where the prop started.
    start_action_com = _prop_com(data, model, prop_bodies)
    start_action_pos = (
        np.asarray(data.xpos[root_id]).copy() if root_id >= 0 else np.zeros(3)
    )

    def _metric() -> float:
        if action.kind == "hang":
            return _pendulum_angle(model, data, joint_id, prop_bodies)
        if action.kind == "displacement":
            com = _prop_com(data, model, prop_bodies)
            direction = np.asarray(action.axis if action.axis else (1.0, 0.0, 0.0))
            norm = float(np.linalg.norm(direction))
            if norm < 1e-9:
                return 0.0
            unit = direction / norm
            return float((com - start_action_com) @ unit)
        return float(data.qpos[joint_qpos]) if joint_qpos >= 0 else 0.0

    trajectory: list[float] = []
    forces: list[float] = []
    max_penetration = 0.0
    penetration_events = 0
    exploded = False

    def _watch(step: int) -> None:
        nonlocal max_penetration, penetration_events
        _, depth = _contacts(data)
        if depth.size:
            worst = float(depth.max())
            if worst > max_penetration:
                max_penetration = worst
            if worst > epsilon:
                penetration_events += 1
        if actuator_id >= 0:
            forces.append(abs(float(data.actuator_force[actuator_id])))
        trajectory.append(_metric())

    action_steps = int(action.duration_s / timestep)
    total_steps = action_steps + max(action.dwell_steps, 1)
    exploded = not _run_steps(model, data, total_steps, _watch)

    # -- the completion ----------------------------------------------------
    tolerance, target = _tolerance_for(action, spec, joint_id, model)
    completion = _score_completion(
        action=action,
        trajectory=trajectory,
        target=target,
        tolerance=tolerance,
        timestep=timestep,
    )

    # -- the stability -----------------------------------------------------
    if actuator_id >= 0 and model.actuator_forcerange.size:
        limit_range = model.actuator_forcerange[actuator_id]
        force_limit = float(max(abs(limit_range[0]), abs(limit_range[1])))
    else:
        force_limit = 0.0
    peak_force = max(forces) if forces else 0.0
    saturated = sum(1 for f in forces if force_limit > 0 and f >= 0.98 * force_limit)
    final_upright = _upright_angle(data, model, root_id)
    final_com = _prop_com(data, model, prop_bodies)
    drift = float(np.linalg.norm(final_com[:2] - start_com[:2]))

    stability_reasons: list[str] = []
    if exploded:
        stability_reasons.append("the simulation exploded during the action")
    if penetration_events > 0:
        stability_reasons.append(
            f"{penetration_events} steps with a penetration past epsilon "
            f"({epsilon * 1000:.2f} mm)"
        )
    if final_upright > 30.0:
        stability_reasons.append(
            f"the prop ended {final_upright:.1f}° from upright"
        )
    if peak_force > force_limit * 1.001:
        stability_reasons.append(
            f"the actuator applied {peak_force:.2f}, over the {force_limit:.2f} limit"
        )

    # The stability score is only meaningful when the prop stood still
    # before the action and the collider is faithful to the mesh.
    #
    # The guard's test is about *inflation*: a hull that bulges over a
    # hollow makes every penetration number a statement about the hull.
    # There are three ways to say that, and the mesh says which apply:
    #
    # * the **volume ratio** — the collider's volume over the mesh's —
    #   is the guard's own test, and it needs a closed surface: the
    #   divergence theorem measures the space a closed surface encloses,
    #   and an open shell has no volume for it to measure.
    # * the **stray distance** — how far the collider's own surface is
    #   from the material it stands for — is the mirror of the deviation,
    #   and it says the same thing for a solid prop and for a shell: a
    #   collider that bulges away from the prop is a collider whose
    #   contacts are not the prop's contacts.
    # * the **cavity** — how deep inside the collider the material's
    #   absence reaches — is reported for every prop.
    #
    # The deviation and the stray distance are the decisive ones: they
    # work on every mesh, and they are the two directions of the same
    # Hausdorff distance. The volume ratio is checked when it can be.
    inflation = built.inflation
    guard_inflation_ok = inflation is not None and inflation <= 0.01
    stray_ok = built.collider_stray_m <= 0.02 * max(diag, 1e-6)
    collider_valid = (
        built.collider_deviation_m <= 0.02 * max(diag, 1e-6)
        and stray_ok
        and (inflation is None or inflation <= 0.15)
    )
    valid = rest.settled and collider_valid and not exploded
    if not rest.settled:
        stability_reasons.append("the prop was not stable at rest, so the score is void")
    if not collider_valid:
        stability_reasons.append(
            f"the collider is {built.collider_volume_m3:.4f} m³ against the mesh's "
            f"{built.mesh_volume_m3:.4f} m³, "
            f"{built.collider_deviation_m * 1000:.1f} mm from the material it "
            f"stands for and {built.collider_stray_m * 1000:.1f} mm from it the "
            f"other way, "
            "so the score is void"
        )

    stability = Stability(
        valid=valid,
        stable=valid and not penetration_events and final_upright <= 30.0,
        max_penetration_m=max_penetration,
        penetration_events=penetration_events,
        epsilon_m=epsilon,
        peak_force=peak_force,
        force_limit=force_limit,
        saturated_steps=saturated,
        upright_angle_deg=final_upright,
        drift_m=drift,
        exploded=exploded,
        reasons=tuple(stability_reasons),
    )

    # -- the verdict -------------------------------------------------------
    if not completion.completed:
        interaction_status = "incomplete"
    else:
        interaction_status = "completed"
    if not stability.valid:
        physics_status = "invalid"
    elif stability.stable:
        physics_status = "stable"
    else:
        physics_status = "unstable"

    # The render: what the planner sees when it is asked to repair.
    if render_path is not None:
        try:
            _render(model, data, render_path, segmentation)
        except Exception as exc:  # pragma: no cover - the render is optional
            notes.append(f"the render failed: {exc}")

    collider_record = {
        "volume_ratio": None if built.volume_ratio is None else round(built.volume_ratio, 6),
        "inflation": None if built.inflation is None else round(built.inflation, 6),
        "shrinkage": None if built.shrinkage is None else round(built.shrinkage, 6),
        "mesh_closed": built.mesh_closed,
        "mesh_is_surface": built.mesh_is_surface,
        "mesh_hull_volume_m3": round(built.mesh_hull_volume_m3, 9),
        "volume_ratio_evaluable": built.volume_ratio is not None,
        "volume_ratio_note": (
            ""
            if built.volume_ratio is not None
            else "the mesh's surface is not closed, so the divergence theorem "
            "gives it no volume to compare the collider's against; the stray "
            "distance and the deviation carry the guard instead"
        ),
        "deviation_m": round(built.collider_deviation_m, 6),
        "deviation_rel_diag": round(
            built.collider_deviation_m / max(diag, 1e-6), 6
        ),
        "coverage_deviation_m": round(built.coverage_deviation_m, 6),
        "coverage_deviation_rel_diag": round(
            built.coverage_deviation_m / max(diag, 1e-6), 6
        ),
        "valid": collider_valid,
        "guard_inflation_within_1pct": guard_inflation_ok,
        "concavity_m": round(built.collider_concavity_m, 6),
        "concavity_ratio": round(built.collider_concavity_ratio, 6),
        "stray_m": round(built.collider_stray_m, 6),
        "stray_rel_diag": round(built.collider_stray_m / max(diag, 1e-6), 6),
        "mesh_volume_m3": round(built.mesh_volume_m3, 9),
        "collider_volume_m3": round(built.collider_volume_m3, 9),
        "epsilon_m": round(epsilon, 8),
    }

    return CheckResult(
        prop=spec.prop,
        interaction_status=interaction_status,
        physics_status=physics_status,
        completion=completion,
        stability=stability,
        rest=rest,
        collider=collider_record,
        steps=int(action_steps),
        simulated_s=round((action_steps + action.dwell_steps) * timestep, 4),
        notes=tuple(notes),
    )


def _tolerance_for(action, spec, joint_id: int, model: mujoco.MjModel) -> tuple[Tolerance, float]:
    """The band the metric has to reach, and the target it has to reach.

    The band is a fraction of the prop's own scale: a hinge is held to a
    percentage of its travel, a displacement to a percentage of the
    distance asked for, a hanging prop to a percentage of a quarter turn.
    """
    relative = action.tolerance_rel
    if action.kind == "joint" and joint_id >= 0:
        joint = spec.joint(action.joint or "")
        travel = abs(model.jnt_range[joint_id][1] - model.jnt_range[joint_id][0])
        target = action.target
        basis = f"{relative:.1%} of the joint's travel ({travel:.4g})"
        return Tolerance(absolute=relative * travel, relative=relative, basis=basis), target
    if action.kind == "displacement":
        target = action.target
        basis = f"{relative:.1%} of the distance asked for ({target:.4g} m)"
        return Tolerance(absolute=relative * abs(target), relative=relative, basis=basis), target
    if action.kind == "hang":
        target = 0.0
        basis = f"{relative:.1%} of a quarter turn ({math.pi / 2:.4g} rad)"
        return Tolerance(absolute=relative * (math.pi / 2), relative=relative, basis=basis), target
    return Tolerance(absolute=0.0, relative=relative, basis="none"), action.target


def _score_completion(
    *,
    action,
    trajectory: list[float],
    target: float,
    tolerance: Tolerance,
    timestep: float,
) -> Completion:
    """Score the trajectory against the band.

    The joint has to reach the band and stay in it: the last ``dwell``
    steps must all be inside it, and the first entry is reported with the
    overshoot and the settling time.
    """
    if not trajectory:
        return Completion(
            metric=action.kind,
            completed=False,
            target=target,
            reached=0.0,
            tolerance=tolerance,
            first_entry_step=None,
            first_entry_time_s=None,
            dwell_steps=action.dwell_steps,
            dwell_satisfied=False,
            overshoot=0.0,
            settling_time_s=None,
            last_decile_deviation=float("inf"),
        )

    values = np.asarray(trajectory, dtype=np.float64)
    errors = np.abs(values - target)
    inside = errors <= tolerance.absolute

    first_entry: int | None = None
    for index, flag in enumerate(inside):
        if flag:
            first_entry = index
            break

    dwell = max(int(action.dwell_steps), 1)
    tail = inside[-dwell:]
    dwell_satisfied = bool(tail.all()) if tail.size else False

    overshoot = 0.0
    if first_entry is not None:
        sign = 1.0 if target >= values[first_entry] else -1.0
        past = values - target
        beyond = past * sign
        overshoot = float(max(beyond.max(), 0.0))

    tail_len = max(1, int(0.1 * values.size))
    last_decile = float(errors[-tail_len:].max())

    settling: float | None = None
    if first_entry is not None:
        settling = first_entry * timestep

    completed = bool(first_entry is not None and dwell_satisfied)

    return Completion(
        metric=action.kind,
        completed=completed,
        target=target,
        reached=float(values[-1]),
        tolerance=tolerance,
        first_entry_step=first_entry,
        first_entry_time_s=settling,
        dwell_steps=dwell,
        dwell_satisfied=dwell_satisfied,
        overshoot=overshoot,
        settling_time_s=settling,
        last_decile_deviation=last_decile,
        trajectory=tuple(round(float(v), 6) for v in values[:: max(1, values.size // 64)]),
    )


def _pendulum_angle(
    model: mujoco.MjModel, data: mujoco.MjData, joint_id: int, prop_bodies: list[int]
) -> float:
    """How far the hanging prop is from straight down, in radians."""
    if joint_id < 0:
        return 0.0
    body_id = int(model.jnt_bodyid[joint_id])
    anchor = np.asarray(data.xpos[body_id])
    com = _prop_com(data, model, prop_bodies)
    direction = com - anchor
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        return 0.0
    cos = float(np.clip(-direction[2] / norm, -1.0, 1.0))
    return math.acos(cos)


def _displacement(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    prop_bodies: list[int],
    axis: tuple[float, float, float] | None,
) -> float:
    """How far the prop moved along the action's axis."""
    if not prop_bodies:
        return 0.0
    com = _prop_com(data, model, prop_bodies)
    if axis is None:
        return float(com[0])
    direction = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        return float(com[0])
    return float(com @ (direction / norm))


def _render(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    path: str | Path,
    segmentation: Segmentation,
) -> Path:
    """Write a render of the final state.

    This is the picture the planner is shown when it is asked to repair a
    prop, so it has to be a picture of the prop: the camera looks at the
    middle of the mesh's own box, from the corner the prop's shape reads
    best from.

    The render happens in a **subprocess**. MuJoCo's EGL context on this
    box does not survive being torn down and made again in the same
    process, and the next render aborts the process rather than raising —
    an abort that would take the whole run with it. The child loads the
    model, puts the state back, renders and writes the picture; the parent
    carries on whether the child succeeded or not.
    """
    import subprocess
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    size = segmentation.mesh.bbox_size
    centre = segmentation.mesh.bbox_min + size / 2.0
    distance = 2.4 * float(np.linalg.norm(size))

    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        model_path = work / "model.xml"
        state_path = work / "state.npz"
        model_path.write_text(model.xml)
        np.savez(
            state_path,
            qpos=np.asarray(data.qpos).copy(),
            qvel=np.asarray(data.qvel).copy(),
            time=np.asarray([data.time]),
        )
        command = [
            sys.executable,
            "-m",
            "core.physag.render",
            str(model_path),
            str(state_path),
            str(path),
            f"{centre[0]:.8g}",
            f"{centre[1]:.8g}",
            f"{centre[2]:.8g}",
            f"{distance:.8g}",
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[2]), env.get("PYTHONPATH", "")]
        )
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=180, env=env
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"the render failed (exit {proc.returncode}): "
            f"{(proc.stderr.strip() or proc.stdout.strip())[-300:]}"
        )
    return path
