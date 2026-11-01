"""Build the MJCF: bodies, joints, convex colliders, and the actuator.

The builder is the part of the loop that never needs a GPU and never needs
a language model. It takes a spec and the geometry the segmentation and the
decomposition produced, and writes a model the checker can execute.

Three decisions are worth stating, because each of them is a way to make
the numbers lie.

**The base is free unless the spec says it is fixed.** A prop standing on
a floor with its base welded to the world cannot topple, and then "stays
upright at rest" is a fact about the model rather than about the prop. The
default is a free base that has to earn its stability.

**The actuator is capped.** The position actuator's force range comes from
the spec's priors, so a joint that is blocked cannot be forced through: the
simulator saturates the force and the joint stops short of the target, and
the completion fails for the right reason.

**The pieces are clipped to their own half-spaces.** Each part's collider
stays on its own side of the cut, with the clearance the segmentation left.
Two parts cannot interpenetrate at the first step, so a penetration the
simulation reports is the prop's doing and not the builder's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from core.physag.decompose import Collider, Decomposition
from core.physag.geometry import (
    MeshPart,
    convex_hull,
    distance_to_union,
    is_closed,
    signed_volume,
    subsample_points,
)
from core.physag.segment import Segmentation
from core.physag.spec import WORLD_ANCHOR, InteractionSpec, Joint, SpecError

__all__ = [
    "BuiltProp",
    "BuildError",
    "GeomSpec",
    "build_mjcf",
]

#: The world anchor's name is the spec's: a joint whose parent is it
#: hangs the prop from a fixed point in the world instead of standing it
#: on the floor.
__all__ = [*globals().get("__all__", []), "WORLD_ANCHOR"]


class BuildError(ValueError):
    """A model that cannot be built from the spec and the geometry."""


@dataclass(frozen=True)
class GeomSpec:
    """One convex collider, as it will appear in the MJCF."""

    name: str
    part: str
    vertices: np.ndarray
    faces: np.ndarray
    density: float
    volume: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "part": self.part,
            "vertices": int(self.vertices.shape[0]),
            "faces": int(self.faces.shape[0]),
            "volume_m3": round(self.volume, 9),
            "density_kg_m3": round(self.density, 3),
        }


@dataclass(frozen=True)
class BuiltProp:
    """The model the checker will run, and what went into it."""

    spec: InteractionSpec
    xml: str
    geoms: tuple[GeomSpec, ...]
    bodies: tuple[str, ...]
    joints: tuple[str, ...]
    actuator: str | None
    action_joint: str | None
    total_mass_kg: float
    collider_volume_m3: float
    mesh_volume_m3: float
    root_body: str
    free_base: bool
    #: Whether the mesh's surface is closed. A closed surface has a volume
    #: and an open one does not, so the volume ratio below is only a
    #: statement about the collider when this is true.
    mesh_closed: bool = True
    #: The volume of the mesh's own convex hull: the space the prop
    #: occupies, whatever shape its surface is.
    mesh_hull_volume_m3: float = 0.0
    #: The same hollow the collider fills in, as a share of the part's own
    #: extent. The share is what the guard is about: a collider that
    #: swallows half the prop is no longer standing in for it, while a
    #: collider that bridges the prop's own gaps — the space between a
    #: crate's slats — is doing what a convex decomposition has to do.
    collider_concavity_ratio: float = 0.0
    #: How far the mesh's own vertices are from the collider's surface:
    #: the Hausdorff distance in the direction that matters, because a
    #: collider that is blind to a hollow shows up here.
    collider_deviation_m: float = 0.0
    coverage_deviation_m: float = 0.0
    #: How deep the collider swallows the material it covers: the hollow
    #: a convex hull fills in.
    collider_concavity_m: float = 0.0
    anchor_m: np.ndarray | None = None
    notes: tuple[str, ...] = ()

    @property
    def volume_ratio(self) -> float | None:
        """The collider's volume over the mesh's.

        ``None`` when the mesh's surface is not closed: a shell with holes
        in it has no volume for the divergence theorem to measure, and
        dividing the collider's volume by a number that is not a volume
        would be a number about nothing. The record says so, and the
        guards that do work on an open mesh — the distance from the
        material to the collider, and the depth of the hollow the collider
        fills in — carry the guard instead.
        """
        if not self.mesh_closed:
            return None
        if self.mesh_volume_m3 <= 0.0:
            return None
        return self.collider_volume_m3 / self.mesh_volume_m3

    @property
    def inflation(self) -> float | None:
        """How much fatter the collider is than the mesh.

        The Hy4 guard is about *inflation*: a hull that bulges over a
        hollow makes "nothing penetrated past epsilon" a statement about
        the hull. A collider that is a little thin is a different fault
        and is reported as ``shrinkage``.
        """
        ratio = self.volume_ratio
        if ratio is None:
            return None
        return ratio - 1.0

    @property
    def shrinkage(self) -> float | None:
        """How much thinner the collider is than the mesh."""
        ratio = self.volume_ratio
        if ratio is None:
            return None
        return max(0.0, 1.0 - ratio)

    def to_dict(self) -> dict:
        return {
            "bodies": list(self.bodies),
            "joints": list(self.joints),
            "actuator": self.actuator,
            "action_joint": self.action_joint,
            "total_mass_kg": round(self.total_mass_kg, 4),
            "collider_volume_m3": round(self.collider_volume_m3, 9),
            "mesh_volume_m3": round(self.mesh_volume_m3, 9),
            "mesh_closed": self.mesh_closed,
            "mesh_hull_volume_m3": round(self.mesh_hull_volume_m3, 9),
            "volume_ratio": None if self.volume_ratio is None else round(self.volume_ratio, 6),
            "inflation": None if self.inflation is None else round(self.inflation, 6),
            "shrinkage": None if self.shrinkage is None else round(self.shrinkage, 6),
            "collider_deviation_m": round(self.collider_deviation_m, 6),
            "coverage_deviation_m": round(self.coverage_deviation_m, 6),
            "collider_concavity_m": round(self.collider_concavity_m, 6),
            "collider_concavity_ratio": round(self.collider_concavity_ratio, 6),
            "root_body": self.root_body,
            "free_base": self.free_base,
            "anchor_m": None if self.anchor_m is None else [round(float(v), 6) for v in self.anchor_m],
            "geoms": [g.to_dict() for g in self.geoms],
            "notes": list(self.notes),
        }


def _fmt_vector(values: Iterable[float]) -> str:
    return " ".join(f"{float(v):.8g}" for v in values)


def _fmt_faces(faces: np.ndarray) -> str:
    return " ".join(f"{int(a)} {int(b)} {int(c)}" for a, b, c in faces)


def _fmt_vertices(vertices: np.ndarray) -> str:
    return " ".join(f"{float(x):.8g} {float(y):.8g} {float(z):.8g}" for x, y, z in vertices)


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _joint_gains(spec: InteractionSpec, joint: Joint, inertia: float) -> tuple[float, float]:
    """The actuator's stiffness and damping for a joint.

    The gains come from the priors rather than from a constant: the
    actuator's limit divided by the travel gives the stiffness at which
    the limit alone is enough to move the joint across its range, and the
    damping that makes that stiffness critical. A heavy part then gets a
    slower, steadier joint than a light one.
    """
    if joint.type == "slide":
        limit = spec.priors.actuator_force_n
        travel = max(abs(joint.low), abs(joint.high), 1e-6)
    else:
        limit = spec.priors.actuator_torque_nm
        travel = max(abs(joint.low), abs(joint.high), 1e-6)
    kp = 0.5 * limit / travel
    kv = 2.0 * float(np.sqrt(max(kp * max(inertia, 1e-6), 0.0)))
    return kp, kv


def _part_inertia(part: MeshPart, mass: float) -> float:
    """A rough inertia about the part's own centre, for the damping.

    The exact inertia is MuJoCo's job — it computes it from the colliders.
    This is only used to pick a damping that is not absurd.
    """
    if part.is_empty:
        return mass * 1e-3
    size = part.bbox_size
    characteristic = float(np.mean(size))
    return mass * (characteristic**2) / 12.0


def build_mjcf(
    spec: InteractionSpec,
    segmentation: Segmentation,
    decompositions: dict[str, Decomposition],
    *,
    timestep: float = 0.002,
    friction: float | None = None,
    floor_size: float = 0.0,
) -> BuiltProp:
    """Write the model for one prop.

    ``segmentation`` gives the pieces; ``decompositions`` gives each part's
    convex pieces. Both are in the prop's frame, where the mesh's bounding
    box's minimum corner is the origin and ``z`` is up.
    """
    spec.validate()
    notes: list[str] = []

    size = segmentation.mesh.bbox_size
    origin = segmentation.mesh.bbox_min

    # Which part is the child of which joint: the tree the builder writes.
    parent_joint: dict[str, Joint] = {}
    for joint in spec.joints:
        if joint.child in parent_joint:
            raise BuildError(
                f"{spec.prop}: part {joint.child!r} is the child of two joints"
            )
        parent_joint[joint.child] = joint

    roots = [p.name for p in spec.parts if p.name not in parent_joint]
    if len(roots) != 1:
        raise BuildError(
            f"{spec.prop}: the parts form {len(roots)} trees; exactly one is needed"
        )
    root_name = roots[0]

    # The mass: the planner's total, split between the parts by the
    # volume each one's collider takes up.
    total_collider_volume = 0.0
    for name, decomp in decompositions.items():
        total_collider_volume += sum(c.volume for c in decomp.colliders)
    if total_collider_volume <= 0.0:
        raise BuildError(f"{spec.prop}: the colliders have no volume")

    total_mass = spec.priors.mass_kg
    friction = spec.priors.friction if friction is None else friction

    geoms: list[GeomSpec] = []
    body_geoms: dict[str, list[GeomSpec]] = {p.name: [] for p in spec.parts}

    for part in spec.parts:
        decomp = decompositions.get(part.name)
        if decomp is None:
            raise BuildError(f"{spec.prop}: part {part.name!r} was never decomposed")
        part_volume = sum(c.volume for c in decomp.colliders)
        part_mass = total_mass * (part_volume / total_collider_volume)
        density = part_mass / part_volume if part_volume > 0.0 else 0.0
        for index, piece in enumerate(decomp.colliders):
            geom = GeomSpec(
                name=f"{part.name}_collider_{index}",
                part=part.name,
                vertices=piece.vertices,
                faces=piece.faces,
                density=density,
                volume=piece.volume,
            )
            geoms.append(geom)
            body_geoms[part.name].append(geom)

    # Each body's frame, as an offset in the prop frame. The root's frame
    # is the prop frame itself unless the prop hangs, in which case it is
    # the hook. A fixed joint welds a part to its parent's frame; a moving
    # joint puts the child's frame at the joint's anchor.
    def _anchor_of(joint: Joint) -> np.ndarray:
        return origin + np.asarray(joint.anchor, dtype=np.float64) * size

    offsets: dict[str, np.ndarray] = {}
    children: dict[str, list[str]] = {p.name: [] for p in spec.parts}

    def _resolve(part_name: str) -> np.ndarray:
        if part_name in offsets:
            return offsets[part_name]
        joint = parent_joint.get(part_name)
        if joint is None:
            offset = np.zeros(3)
        elif joint.parent == WORLD_ANCHOR:
            offset = _anchor_of(joint)
        elif joint.type == "fixed":
            offset = _resolve(joint.parent)
        else:
            offset = _anchor_of(joint)
        offsets[part_name] = offset
        return offset

    for part in spec.parts:
        _resolve(part.name)
    for part in spec.parts:
        joint = parent_joint.get(part.name)
        if joint is not None and joint.parent != WORLD_ANCHOR:
            children[joint.parent].append(part.name)

    # The mesh assets.
    asset_lines: list[str] = []
    for geom in geoms:
        asset_lines.append(
            f'    <mesh name="{_xml_escape(geom.name)}" '
            f'vertex="{_fmt_vertices(geom.vertices)}" face="{_fmt_faces(geom.faces)}"/>'
        )

    def _emit_body(part_name: str, depth: int) -> list[str]:
        """A part's body, its joint, its colliders, and its children."""
        pad = "  " * depth
        joint = parent_joint.get(part_name)
        offset = offsets[part_name]
        lines: list[str] = []

        if joint is not None and joint.parent != WORLD_ANCHOR:
            # The part's place in its parent's frame.
            parent_offset = offsets[joint.parent]
            body_pos = offset - parent_offset
        else:
            body_pos = offset

        lines.append(
            f'{pad}<body name="body_{_xml_escape(part_name)}" pos="{_fmt_vector(body_pos)}">'
        )
        inner = "  " * (depth + 1)

        if joint is not None and joint.type != "fixed":
            if joint.type == "ball":
                joint_attrs = f'name="{_xml_escape(joint.name)}" type="ball"'
            else:
                limit = f"{joint.low:.8g} {joint.high:.8g}"
                joint_attrs = (
                    f'name="{_xml_escape(joint.name)}" type="{joint.type}" '
                    f'axis="{_fmt_vector(joint.unit_axis)}" range="{limit}" '
                    f'damping="{joint.damping:.8g}" armature="{joint.armature:.8g}"'
                )
            lines.append(f'{inner}<joint {joint_attrs} pos="0 0 0"/>')
        elif joint is None and not spec.priors.base_static:
            lines.append(f"{inner}<freejoint/>")
        elif joint is None:
            notes.append("the base is fixed to the world because the spec says so")

        # The colliders: the mesh's own frame, moved back from the body's.
        for geom in body_geoms[part_name]:
            lines.append(
                f'{inner}<geom name="{_xml_escape(geom.name)}" type="mesh" '
                f'mesh="{_xml_escape(geom.name)}" '
                f'pos="{_fmt_vector(-offset)}" density="{geom.density:.8g}"/>'
            )

        for child in children.get(part_name, []):
            lines.extend(_emit_body(child, depth + 1))

        lines.append(f"{pad}</body>")
        return lines

    def _emit_root(root_name: str) -> list[str]:
        """The root body, hung from a fixed anchor when the spec says so."""
        joint = parent_joint.get(root_name)
        if joint is not None and joint.parent == WORLD_ANCHOR:
            pad = "  " * 2
            anchor = offsets[root_name]
            lines = [f'{pad}<body name="{WORLD_ANCHOR}_anchor" pos="{_fmt_vector(anchor)}">']
            inner = "  " * 3
            lines.append(f'{inner}<body name="body_{_xml_escape(root_name)}" pos="0 0 0">')
            body_inner = "  " * 4
            if joint.type != "fixed":
                joint_attrs = f'name="{_xml_escape(joint.name)}" type="ball"'
                lines.append(f'{body_inner}<joint {joint_attrs} pos="0 0 0"/>')
            for geom in body_geoms[root_name]:
                lines.append(
                    f'{body_inner}<geom name="{_xml_escape(geom.name)}" type="mesh" '
                    f'mesh="{_xml_escape(geom.name)}" '
                    f'pos="{_fmt_vector(-anchor)}" density="{geom.density:.8g}"/>'
                )
            for child in children.get(root_name, []):
                lines.extend(_emit_body(child, 4))
            lines.append(f"{inner}</body>")
            lines.append(f"{pad}</body>")
            return lines
        return _emit_body(root_name, 2)

    # The actuator.
    actuator_lines: list[str] = []
    actuator_name: str | None = None
    action_joint: str | None = None
    if spec.action.kind in ("joint", "displacement") and spec.action.joint:
        action_joint = spec.action.joint
        joint = spec.joint(action_joint)
        if joint is None:
            raise BuildError(f"{spec.prop}: the action names no joint {action_joint!r}")
        inertia = _part_inertia(
            segmentation.pieces[joint.child].part if joint.child in segmentation.pieces else MeshPart(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)),
            total_mass,
        )
        kp, kv = _joint_gains(spec, joint, inertia)
        limit = (
            spec.priors.actuator_force_n
            if joint.type == "slide"
            else spec.priors.actuator_torque_nm
        )
        drive = spec.action.drive if spec.action.drive is not None else spec.action.target
        ctrl_lo = min(joint.low, drive)
        ctrl_hi = max(joint.high, drive)
        actuator_name = f"{action_joint}_actuator"
        actuator_lines.append(
            f'  <position name="{_xml_escape(actuator_name)}" joint="{_xml_escape(action_joint)}" '
            f'kp="{kp:.8g}" kv="{kv:.8g}" ctrlrange="{ctrl_lo:.8g} {ctrl_hi:.8g}" '
            f'forcelimited="true" forcerange="{-limit:.8g} {limit:.8g}"/>'
        )

    bodies: list[str] = []
    joints: list[str] = []
    for part in spec.parts:
        bodies.append(f"body_{part.name}")
    for joint in spec.joints:
        joints.append(joint.name)

    # The base is free when the prop stands on the floor and the spec does
    # not say it is static. A welded base cannot topple, and then "stays
    # upright" would be a fact about the model rather than about the prop.
    root_joint = parent_joint.get(root_name)
    free_base = root_joint is None and not spec.priors.base_static

    lines: list[str] = []
    lines.append(f'<mujoco model="{_xml_escape(spec.prop)}">')
    lines.append('  <compiler angle="radian" autolimits="true"/>')
    lines.append(
        f'  <option timestep="{timestep:.8g}" gravity="0 0 -9.81" integrator="implicitfast"/>'
    )
    lines.append("  <default>")
    lines.append(f'    <geom condim="4" friction="{friction:.6g} 0.005 0.0001" rgba="0.8 0.8 0.85 1"/>')
    lines.append("  </default>")
    lines.append("  <asset>")
    lines.extend(asset_lines)
    lines.append("  </asset>")
    lines.append("  <worldbody>")
    lines.append('    <light pos="0 0 3" dir="0 0 -1" diffuse="0.8 0.8 0.8"/>')
    lines.append('    <light pos="1 -1 2" dir="-1 1 -1" diffuse="0.3 0.3 0.3"/>')
    lines.append(
        f'    <geom name="floor" type="plane" size="0 0 {max(floor_size, 0.05):.6g}" '
        f'friction="{friction:.6g} 0.005 0.0001" rgba="0.25 0.25 0.28 1"/>'
    )
    lines.extend(_emit_root(root_name))
    lines.append("  </worldbody>")
    if actuator_lines:
        lines.append("  <actuator>")
        lines.extend(actuator_lines)
        lines.append("  </actuator>")
    lines.append("</mujoco>")

    xml = "\n".join(lines) + "\n"

    # How faithful is the collider to the mesh it stands for?
    #
    # `collider_deviation_m` is the distance from each part's own material
    # to that part's collider: the Hausdorff distance the guard asks for,
    # measured against the thing the collider is supposed to be. The
    # clearance at the cut is inside it, and the clearance is a known and
    # recorded number.
    #
    # `coverage_deviation_m` is the distance from the whole mesh to the
    # collider, which also contains the material that the cut gave away —
    # the strip between the cut and the clearance.
    deviation = 0.0
    concavity = 0.0
    #: The hollow the collider fills in, as a share of the part's own
    #: extent. The share is what the guard is about: a collider that
    #: swallows half the prop is no longer standing in for it, while a
    #: collider that bridges the prop's own gaps — the space between a
    #: crate's slats — is doing what a convex decomposition has to do.
    concavity_ratio = 0.0
    for name, decomp in decompositions.items():
        deviation = max(deviation, decomp.deviation_m)
        concavity = max(concavity, decomp.concavity_m)
        part = segmentation.pieces.get(name)
        if part is not None and not part.part.is_empty:
            extent = float(np.linalg.norm(part.part.bbox_size))
            if extent > 1e-9:
                concavity_ratio = max(concavity_ratio, decomp.concavity_m / extent)

    mesh_vertices = segmentation.mesh.vertices
    coverage = 0.0
    if mesh_vertices.shape[0] > 0:
        # The distance to the **union** of the colliders: a vertex that any
        # piece covers is covered. Measuring to each piece and taking the
        # worst would report a vertex that one hull stands over as far from
        # the collider, because it happens to be outside the other hulls.
        planes = [
            piece.planes
            for decomp in decompositions.values()
            for piece in decomp.colliders
            if piece.planes.shape[0] > 0
        ]
        if planes:
            # The mesh's vertices are sampled: the whole set is hundreds of
            # thousands of points and the pieces are dozens, and the
            # measurement is their product.
            sample = subsample_points(mesh_vertices, 20000)
            nearest = distance_to_union(sample, planes)
            finite = nearest[np.isfinite(nearest)]
            if finite.size:
                coverage = float(finite.max())

    mesh_closed = is_closed(segmentation.mesh)
    hull_volume = 0.0
    if segmentation.mesh.vertices.shape[0] > 0:
        hull = convex_hull(segmentation.mesh.vertices)
        hull_volume = float(hull.volume)

    return BuiltProp(
        spec=spec,
        xml=xml,
        geoms=tuple(geoms),
        bodies=tuple(bodies),
        joints=tuple(joints),
        actuator=actuator_name,
        action_joint=action_joint,
        total_mass_kg=total_mass,
        collider_volume_m3=total_collider_volume,
        mesh_volume_m3=volume_of(segmentation.mesh),
        mesh_closed=mesh_closed,
        mesh_hull_volume_m3=hull_volume,
        root_body=f"body_{root_name}",
        free_base=free_base,
        collider_deviation_m=deviation,
        coverage_deviation_m=coverage,
        collider_concavity_m=concavity,
        collider_concavity_ratio=concavity_ratio,
        anchor_m=offsets.get(root_name),
        notes=tuple(notes),
    )


def volume_of(mesh: MeshPart) -> float:
    """The volume of a closed mesh, by the divergence theorem."""
    return signed_volume(mesh.vertices, mesh.triangles)
