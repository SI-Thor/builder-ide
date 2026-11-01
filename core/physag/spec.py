"""The typed interaction spec: what the cloud planner writes for one prop.

The spec is the whole contract of this seat. A cloud model writes it, the
builder turns it into an MJCF, the checker executes it, and the delivery
record says which parts of it were measured and which were guessed. Nothing
else crosses the cloud/Thor line: **no language model runs on the Thor**
(CLAUDE.md, "No LLMs on the Thor").

Three things about the spec are deliberate.

**It is typed and it validates.** A spec that names a joint whose child is
not a part, an action whose target is outside the joint's limits, or a prior
with no basis, is refused at the door. The planner gets the error back and
repairs it; the builder never has to guess what a missing field meant.

**Positions are normalised.** Every position in the spec is a fraction of
the prop's own bounding box, not a number of metres. A spec written before
the mesh exists therefore survives the mesh: the generated crate is 41 cm
tall or 63 cm tall and the same "the lid is the top 22 % of the height"
means the lid in both. The builder maps the fractions to metres once, when
the mesh is in hand.

**Every prior carries its basis.** ``measured`` means the checker measured
it in the simulation; ``estimated`` means the planner guessed it; ``derived``
means it fell out of the geometry (a volume and a density). The delivery
record keeps the two apart, because "the hinge works" and "the mass is a
guess" are different claims and the record has to be able to say so.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

__all__ = [
    "Action",
    "Basis",
    "Box",
    "Cut",
    "InteractionSpec",
    "Joint",
    "Part",
    "Priors",
    "SpecError",
    "load_spec",
    "repair_is_allowed",
    "save_spec",
    "spec_diff",
]

Vec3 = tuple[float, float, float]
Axis = Literal["x", "y", "z"]
JointType = Literal["hinge", "slide", "ball", "fixed"]
ActionKind = Literal["joint", "displacement", "hang"]
Basis = Literal["measured", "estimated", "derived"]

#: The basis values a prior may carry. ``measured`` is for the checker, the
#: other two are for the planner: a guess is a guess and a derivation is
#: arithmetic, and neither is a measurement.
BASIS_VALUES: tuple[Basis, ...] = ("measured", "estimated", "derived")

#: The axis a mesh's "up" is along in the prop frame. The builder rotates a
#: mesh into this frame before anything else, so a spec never has to say.
UP_AXIS: Axis = "z"

#: The name a joint may use as its parent to mean "the world": the prop
#: hangs from a fixed point instead of standing on the floor.
WORLD_ANCHOR = "world"


class SpecError(ValueError):
    """A spec that cannot be built as written."""


@dataclass(frozen=True)
class Cut:
    """How one part is separated from the rest of the mesh.

    The split is geometric on purpose: a plane, a box, or "whatever is left".
    It is the simplest thing that can isolate a functional part, and it is
    the thing the Hy4 guards are about — a split that cuts the prop but not
    the *part* produces a joint on the wrong body, and then the completion
    rate measures nothing.

    ``plane`` cuts the mesh with an axis-aligned plane at ``at`` — a
    fraction of the mesh's extent along ``axis`` — and keeps the ``above``
    or ``below`` side. ``box`` keeps the triangles whose centroid falls
    inside the normalised box. ``rest`` keeps everything no other part
    claimed, which makes it the base.
    """

    kind: Literal["plane", "box", "rest"]
    axis: Axis = "z"
    at: float = 0.0
    keep: Literal["above", "below"] = "above"
    min: Vec3 = (0.0, 0.0, 0.0)
    max: Vec3 = (1.0, 1.0, 1.0)

    def validate(self, name: str) -> None:
        if self.kind not in ("plane", "box", "rest"):
            raise SpecError(f"part {name!r}: unknown cut kind {self.kind!r}")
        if self.kind == "plane":
            if self.axis not in ("x", "y", "z"):
                raise SpecError(f"part {name!r}: unknown cut axis {self.axis!r}")
            if not 0.0 < self.at < 1.0:
                raise SpecError(
                    f"part {name!r}: the cut at {self.at} is outside the mesh; "
                    "a fraction of the extent must lie strictly inside (0, 1)"
                )
            if self.keep not in ("above", "below"):
                raise SpecError(f"part {name!r}: unknown cut side {self.keep!r}")
        elif self.kind == "box":
            for axis, lo, hi in zip("xyz", self.min, self.max):
                if lo >= hi:
                    raise SpecError(
                        f"part {name!r}: the box is empty along {axis} "
                        f"({lo} .. {hi})"
                    )
                if lo < 0.0 or hi > 1.0:
                    raise SpecError(
                        f"part {name!r}: the box runs outside the mesh along {axis}"
                    )


@dataclass(frozen=True)
class Box:
    """A normalised box: fractions of the prop's own bounding box."""

    min: Vec3 = (0.0, 0.0, 0.0)
    max: Vec3 = (1.0, 1.0, 1.0)

    def validate(self, name: str) -> None:
        for axis, lo, hi in zip("xyz", self.min, self.max):
            if lo >= hi:
                raise SpecError(f"part {name!r}: the box is empty along {axis} ({lo} .. {hi})")
            if lo < 0.0 or hi > 1.0:
                raise SpecError(f"part {name!r}: the box runs outside the mesh along {axis}")


@dataclass(frozen=True)
class Part:
    """One functional part of the prop, and how it is cut out.

    ``role`` is ``base`` for the part that stays put and ``moving`` for the
    part the joint carries. Exactly one part is the base.

    ``expect`` is the planner's *claim* about where the part is, as a
    normalised box. It is separate from ``cut`` on purpose. The cut says
    where to separate the mesh; the claim says where the functional part
    really is. The segmentation check measures the piece against the claim,
    so a planner that cut in the wrong place is caught by a number instead
    of by the eye. When it is left out, the claim is the cut's own slab.
    """

    name: str
    role: Literal["base", "moving"]
    cut: Cut
    expect: Box | None = None
    density_kg_m3: float = 700.0

    def validate(self) -> None:
        if not self.name:
            raise SpecError("a part has no name")
        if self.role not in ("base", "moving"):
            raise SpecError(f"part {self.name!r}: unknown role {self.role!r}")
        if self.density_kg_m3 <= 0.0:
            raise SpecError(f"part {self.name!r}: the density must be positive")
        self.cut.validate(self.name)
        if self.expect is not None:
            self.expect.validate(self.name)

    def claimed_box(self) -> Box:
        """The claim: the planner's box, or the cut's own slab."""
        if self.expect is not None:
            return self.expect
        cut = self.cut
        if cut.kind == "rest":
            return Box()
        if cut.kind == "box":
            return Box(min=cut.min, max=cut.max)
        slab_min = [0.0, 0.0, 0.0]
        slab_max = [1.0, 1.0, 1.0]
        index = {"x": 0, "y": 1, "z": 2}[cut.axis]
        if cut.keep == "above":
            slab_min[index] = cut.at
        else:
            slab_max[index] = cut.at
        return Box(min=(slab_min[0], slab_min[1], slab_min[2]), max=(slab_max[0], slab_max[1], slab_max[2]))


@dataclass(frozen=True)
class Joint:
    """One joint: the axis, the anchor, and the limits it may travel.

    The anchor is normalised like everything else: a fraction of the prop's
    bounding box. For a hinge it is the hinge line's point on the box; for
    a slide it is the point on the axis the part travels along.
    """

    name: str
    type: JointType
    parent: str
    child: str
    axis: Vec3
    anchor: Vec3
    low: float
    high: float
    damping: float = 0.5
    armature: float = 0.01

    def validate(self) -> None:
        if not self.name:
            raise SpecError("a joint has no name")
        if self.type not in ("hinge", "slide", "ball", "fixed"):
            raise SpecError(f"joint {self.name!r}: unknown type {self.type!r}")
        if self.parent == self.child:
            raise SpecError(f"joint {self.name!r}: the parent and the child are the same part")
        norm = sum(c * c for c in self.axis) ** 0.5
        if norm < 1e-9:
            raise SpecError(f"joint {self.name!r}: the axis has no direction")
        if self.type in ("hinge", "slide") and self.low >= self.high:
            raise SpecError(
                f"joint {self.name!r}: the limits {self.low} .. {self.high} are empty"
            )
        if self.damping < 0.0:
            raise SpecError(f"joint {self.name!r}: the damping must not be negative")
        if self.armature < 0.0:
            raise SpecError(f"joint {self.name!r}: the armature must not be negative")

    @property
    def unit_axis(self) -> Vec3:
        """The axis, normalised to unit length."""
        norm = sum(c * c for c in self.axis) ** 0.5
        return (self.axis[0] / norm, self.axis[1] / norm, self.axis[2] / norm)

    @property
    def travel(self) -> float:
        """How far the joint may travel, in its own units."""
        return self.high - self.low


@dataclass(frozen=True)
class Action:
    """The action the check executes.

    ``joint`` drives one joint to a target. ``displacement`` drives a joint
    and measures how far the *body* moved — a cart rolls, and the thing
    that has to arrive somewhere is the chassis, not the wheel. ``hang``
    asks a suspended body to settle into its hanging equilibrium and stay
    there.

    ``drive`` is what the actuator is commanded to when the thing being
    measured is not the joint itself. A cart that has to roll half a metre
    is told to turn its wheel through several radians; the half a metre is
    the target, and the radians are the drive.
    """

    kind: ActionKind
    joint: str | None = None
    target: float = 0.0
    axis: Vec3 | None = None
    duration_s: float = 4.0
    tolerance_rel: float = 0.02
    dwell_steps: int = 25
    drive: float | None = None

    def validate(self) -> None:
        if self.kind not in ("joint", "displacement", "hang"):
            raise SpecError(f"unknown action kind {self.kind!r}")
        if self.kind in ("joint", "displacement") and not self.joint:
            raise SpecError(f"a {self.kind} action names no joint")
        if self.kind == "displacement":
            if self.axis is None:
                raise SpecError("a displacement action has no direction")
            norm = sum(c * c for c in self.axis) ** 0.5
            if norm < 1e-9:
                raise SpecError("the displacement action's axis has no direction")
        if self.duration_s <= 0.0:
            raise SpecError("the action's duration must be positive")
        if not 0.0 < self.tolerance_rel < 1.0:
            raise SpecError(
                f"the action's relative tolerance {self.tolerance_rel} must lie in (0, 1)"
            )
        if self.dwell_steps < 1:
            raise SpecError("the action must dwell for at least one step")


@dataclass(frozen=True)
class Priors:
    """The physical priors the planner asserts about the prop.

    Every one of these is a guess until the checker measures it, and the
    ``basis`` mapping on the spec says which it is.
    """

    mass_kg: float
    friction: float = 0.6
    actuator_force_n: float = 40.0
    actuator_torque_nm: float = 12.0
    base_static: bool = False

    def validate(self) -> None:
        if self.mass_kg <= 0.0:
            raise SpecError("the prior mass must be positive")
        if self.friction < 0.0:
            raise SpecError("the prior friction must not be negative")
        if self.actuator_force_n <= 0.0:
            raise SpecError("the prior actuator force must be positive")
        if self.actuator_torque_nm <= 0.0:
            raise SpecError("the prior actuator torque must be positive")

    def fields(self) -> tuple[str, ...]:
        return (
            "mass_kg",
            "friction",
            "actuator_force_n",
            "actuator_torque_nm",
            "base_static",
        )


@dataclass(frozen=True)
class InteractionSpec:
    """Everything the loop needs to know about one prop.

    ``basis`` maps a prior's name to where the number came from
    (``measured`` / ``estimated`` / ``derived``). ``planner`` records who
    wrote the spec, with which model, and how — the honest answer is part
    of the record.
    """

    prop: str
    kind: str
    image_prompt: str
    parts: tuple[Part, ...]
    joints: tuple[Joint, ...]
    action: Action
    priors: Priors
    basis: Mapping[str, str] = field(default_factory=dict)
    planner: Mapping[str, str] = field(default_factory=dict)

    # -- validation ------------------------------------------------------

    def validate(self) -> None:
        """Refuse a spec that cannot be built. Raises :class:`SpecError`."""
        if not self.prop:
            raise SpecError("the spec has no prop name")
        if not self.parts:
            raise SpecError(f"{self.prop}: the spec names no parts")
        if not self.joints:
            raise SpecError(f"{self.prop}: the spec names no joints")

        names = [p.name for p in self.parts]
        if len(set(names)) != len(names):
            raise SpecError(f"{self.prop}: two parts share a name")
        for part in self.parts:
            part.validate()

        bases = [p for p in self.parts if p.role == "base"]
        if len(bases) != 1:
            raise SpecError(
                f"{self.prop}: {len(bases)} base parts; exactly one is needed"
            )
        if sum(1 for p in self.parts if p.cut.kind == "rest") != 1:
            raise SpecError(
                f"{self.prop}: exactly one part must be the 'rest' — the part "
                "that keeps what no other part claimed"
            )

        joint_names = [j.name for j in self.joints]
        if len(set(joint_names)) != len(joint_names):
            raise SpecError(f"{self.prop}: two joints share a name")
        for joint in self.joints:
            joint.validate()
            if joint.parent not in names and joint.parent != WORLD_ANCHOR:
                raise SpecError(
                    f"{self.prop}: joint {joint.name!r} has no parent part "
                    f"{joint.parent!r}"
                )
            if joint.child not in names:
                raise SpecError(
                    f"{self.prop}: joint {joint.name!r} has no child part "
                    f"{joint.child!r}"
                )

        self.action.validate()
        if self.action.kind in ("joint", "displacement"):
            joint = self.joint(self.action.joint or "")
            if joint is None:
                raise SpecError(
                    f"{self.prop}: the action drives joint {self.action.joint!r}, "
                    "which the spec does not define"
                )
            if joint.type == "ball":
                raise SpecError(
                    f"{self.prop}: a ball joint has no single target to drive"
                )
            if self.action.kind == "joint":
                if not joint.low <= self.action.target <= joint.high:
                    raise SpecError(
                        f"{self.prop}: the action's target {self.action.target} is "
                        f"outside joint {joint.name!r}'s limits "
                        f"{joint.low} .. {joint.high}"
                    )
            else:
                # A displacement target is a distance; it is checked against
                # the joint's travel so the action cannot ask for a slide
                # the joint cannot make.
                if not 0.0 <= self.action.target <= joint.travel:
                    raise SpecError(
                        f"{self.prop}: the action asks for {self.action.target} of "
                        f"travel; joint {joint.name!r} can only make {joint.travel}"
                    )
            if self.action.drive is not None:
                if not joint.low <= self.action.drive <= joint.high:
                    raise SpecError(
                        f"{self.prop}: the action's drive {self.action.drive} is "
                        f"outside joint {joint.name!r}'s limits "
                        f"{joint.low} .. {joint.high}"
                    )

        self.priors.validate()
        missing = [f for f in self.priors.fields() if f not in self.basis]
        if missing:
            raise SpecError(
                f"{self.prop}: no basis for {', '.join(missing)}; every prior "
                "must say whether it was measured, estimated or derived"
            )
        wrong = {
            f: b for f, b in self.basis.items() if b not in BASIS_VALUES
        }
        if wrong:
            raise SpecError(
                f"{self.prop}: unknown basis {wrong}; use one of "
                f"{', '.join(BASIS_VALUES)}"
            )

    # -- accessors -------------------------------------------------------

    def part(self, name: str) -> Part | None:
        for part in self.parts:
            if part.name == name:
                return part
        return None

    def joint(self, name: str) -> Joint | None:
        for joint in self.joints:
            if joint.name == name:
                return joint
        return None

    @property
    def base_part(self) -> Part:
        for part in self.parts:
            if part.role == "base":
                return part
        raise SpecError(f"{self.prop}: no base part")

    @property
    def moving_parts(self) -> tuple[Part, ...]:
        return tuple(p for p in self.parts if p.role == "moving")

    # -- serialisation ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The spec as plain data, ready for JSON.

        The vectors become lists, so what comes out is what JSON can hold
        and a spec that has been through a file equals the one that has
        not.
        """
        return {
            "prop": self.prop,
            "kind": self.kind,
            "image_prompt": self.image_prompt,
            "parts": [_part_to_dict(p) for p in self.parts],
            "joints": [_joint_to_dict(j) for j in self.joints],
            "action": _action_to_dict(self.action),
            "priors": asdict(self.priors),
            "basis": dict(self.basis),
            "planner": dict(self.planner),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InteractionSpec":
        """Read a spec back, refusing it if it does not validate."""
        try:
            spec = cls(
                prop=data["prop"],
                kind=data["kind"],
                image_prompt=data["image_prompt"],
                parts=tuple(
                    Part(
                        name=p["name"],
                        role=p["role"],
                        cut=Cut(**p["cut"]),
                        expect=(
                            Box(**p["expect"]) if p.get("expect") is not None else None
                        ),
                        density_kg_m3=float(p.get("density_kg_m3", 700.0)),
                    )
                    for p in data["parts"]
                ),
                joints=tuple(
                    Joint(
                        name=j["name"],
                        type=j["type"],
                        parent=j["parent"],
                        child=j["child"],
                        axis=tuple(float(c) for c in j["axis"]),  # type: ignore[arg-type]
                        anchor=tuple(float(c) for c in j["anchor"]),  # type: ignore[arg-type]
                        low=float(j["low"]),
                        high=float(j["high"]),
                        damping=float(j.get("damping", 0.5)),
                        armature=float(j.get("armature", 0.01)),
                    )
                    for j in data["joints"]
                ),
                action=Action(**data["action"]),
                priors=Priors(**data["priors"]),
                basis=dict(data.get("basis") or {}),
                planner=dict(data.get("planner") or {}),
            )
        except KeyError as exc:
            raise SpecError(f"the spec is missing {exc.args[0]!r}") from exc
        except TypeError as exc:
            raise SpecError(f"the spec has a field of the wrong shape: {exc}") from exc
        spec.validate()
        return spec

    def with_planner(self, **record: str) -> "InteractionSpec":
        """A copy of this spec with the planner's record filled in."""
        return replace(self, planner={**self.planner, **record})


def _vector(values) -> list[float]:
    """A vector as plain numbers."""
    return [float(v) for v in values]


def _part_to_dict(part: Part) -> dict:
    data = asdict(part)
    if part.expect is not None:
        data["expect"] = {"min": _vector(part.expect.min), "max": _vector(part.expect.max)}
    data["cut"] = {
        "kind": part.cut.kind,
        "axis": part.cut.axis,
        "at": part.cut.at,
        "keep": part.cut.keep,
        "min": _vector(part.cut.min),
        "max": _vector(part.cut.max),
    }
    return data


def _joint_to_dict(joint: Joint) -> dict:
    data = asdict(joint)
    data["axis"] = _vector(joint.axis)
    data["anchor"] = _vector(joint.anchor)
    return data


def _action_to_dict(action: Action) -> dict:
    data = asdict(action)
    if action.axis is not None:
        data["axis"] = _vector(action.axis)
    return data


def save_spec(spec: InteractionSpec, path: str | Path) -> Path:
    """Write a spec to disk as JSON, with its planner's record beside it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec.to_dict(), indent=2, sort_keys=False) + "\n")
    return path


def load_spec(path: str | Path) -> InteractionSpec:
    """Read a spec from disk, refusing it if it does not validate."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"{path}: cannot be read ({exc})") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path}: a spec must be a JSON object")
    return InteractionSpec.from_dict(data)


def spec_diff(before: InteractionSpec, after: InteractionSpec) -> dict[str, Any]:
    """What changed between two specs, field by field.

    The repair round uses this to show what the planner changed and to catch
    the one change that would make the comparison meaningless: a repair that
    moves the action or the joint limits is not a repair of the physics, it
    is the check being made easier, and the prop must not count towards the
    completion rate.
    """

    def _flatten(spec: InteractionSpec) -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for part in spec.parts:
            for key, value in asdict(part).items():
                flat[f"part.{part.name}.{key}"] = value
        for joint in spec.joints:
            for key, value in asdict(joint).items():
                flat[f"joint.{joint.name}.{key}"] = value
        for key, value in asdict(spec.action).items():
            flat[f"action.{key}"] = value
        for key, value in asdict(spec.priors).items():
            flat[f"priors.{key}"] = value
        return flat

    old, new = _flatten(before), _flatten(after)
    changed = {
        key: {"from": old.get(key), "to": new.get(key)}
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key)
    }
    frozen = _frozen_keys(before)
    action_changed = sorted(k for k in changed if k in frozen)
    return {
        "changed": changed,
        "action_changed": bool(action_changed),
        "action_changed_fields": action_changed,
    }


def _frozen_keys(spec: InteractionSpec) -> set[str]:
    """The fields a repair round may not touch.

    The action and the joint limits are frozen: a repair may change the
    priors or the segmentation, but if it may change the target then the
    check can always be made to pass, and the completion rate stops
    measuring the prop. The action's *time* and its *tolerance* are
    frozen for the same reason — a longer deadline or a wider band is the
    same cheat as a smaller target.
    """
    keys = {
        "action.kind",
        "action.joint",
        "action.target",
        "action.axis",
        "action.duration_s",
        "action.tolerance_rel",
        "action.dwell_steps",
    }
    for joint in spec.joints:
        keys.add(f"joint.{joint.name}.low")
        keys.add(f"joint.{joint.name}.high")
        keys.add(f"joint.{joint.name}.type")
        keys.add(f"joint.{joint.name}.axis")
    return keys


#: The prior fields a repair round is allowed to change.
REPAIRABLE_PRIORS = frozenset(
    {"mass_kg", "friction", "actuator_force_n", "actuator_torque_nm", "base_static"}
)


def repair_is_allowed(before: InteractionSpec, after: InteractionSpec) -> tuple[bool, list[str]]:
    """Whether a repaired spec keeps the action and the limits frozen.

    Returns the verdict and the fields that moved. A repair that moved one
    of them is reported, and the prop is excluded from the completion rate.
    """
    diff = spec_diff(before, after)
    return (not diff["action_changed"]), list(diff["action_changed_fields"])


def sequence_of(values: Sequence[float]) -> Vec3:
    """Three numbers as a vector, refusing anything that is not three."""
    if len(values) != 3:
        raise SpecError(f"expected three numbers, got {len(values)}")
    return (float(values[0]), float(values[1]), float(values[2]))
