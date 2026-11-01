"""The critic seat's records: bases, members, checks, verdicts.

Plan item 12 (week 2): *the critic's calibration set, first members* — a
fixed reference set of ~30 renders with seeded defects through scripted
checks, publishing false-positive/false-negative rates. The brief for this
seat upgrades the plan's wording in one way: the members are **real renders**
from the overnight Infinigen sweep on the Thor, not recipe fragments, so the
numbers are about the images the critic will actually be handed.

Four kinds of record live here:

    BaseRender      one real render in the sweep, with its hash (the source)
    ReferenceMember one *member* of the reference set: a base plus a seeded
                    defect (or a clean control) plus the recipe of that defect
    CheckOutcome    one scripted check's measurement on one member
    CriticVerdict   the critic's judgement of one member, `verdict@scripted`

The seeded defect classes are the brief's list, sorted by **where the defect
lives** — in the pixels or in the geometry — because that is what decides
which checks can see it:

* image defects are planted in the render's pixels and are seen by the image
  checks;
* mesh defects are planted in the scene's geometry and are seen by the mesh
  checks (watertightness, scale bounds) — the checks the cold-start seat
  already owns, read against a *measured* mesh instead of a typed param.

The counting rule is the cold-start seat's (see
:mod:`core.coldstart.calibration`): a planted defect of class K that check
``DEFECT_TARGETS[K]`` does not fire on is a **false negative**, including a
defect the check could not see at all; a check firing on a member carrying a
*different* class of planted defect is excluded from all four counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "DefectKind",
    "DefectLayer",
    "IMAGE_DEFECTS",
    "MESH_DEFECTS",
    "DEFECT_KINDS",
    "DEFECT_TARGETS",
    "BaseRender",
    "ReferenceMember",
    "CheckOutcome",
    "CriticVerdict",
    "MeshObject",
    "CameraInfo",
    "MeshStats",
    "INFRASTRUCTURE",
    "is_prop",
    "prop_family",
]

#: The seeded defect classes. The image classes are planted in the pixels of
#: a real render; the mesh classes need the scene's geometry.
DefectKind = Literal[
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
    "wrong_scale",
    "hollow_mesh",
    "clipped_geometry",
]

#: Where the defect lives — and therefore which checks can see it.
DefectLayer = Literal["image", "mesh"]

#: Defects planted in the render's pixels. Every one of them is deterministic
#: in `(base, seed)`: the same sweep render always yields the same broken
#: image, so the reference set is reproducible rather than merely repeatable.
IMAGE_DEFECTS: tuple[str, ...] = (
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
)

#: Defects planted in the scene's geometry. They need the scene's mesh, which
#: the sweep deletes when a scene finishes (see :mod:`core.critic.mesh`), so
#: a member of these classes is only possible while a live ``scene.blend``
#: exists — the manifest says which.
MESH_DEFECTS: tuple[str, ...] = ("wrong_scale", "hollow_mesh", "clipped_geometry")

DEFECT_KINDS: tuple[str, ...] = IMAGE_DEFECTS + MESH_DEFECTS

#: Which check targets which defect class — the reference set's ground truth.
#: The two mesh rows are the cold-start seat's own checks, carried over.
DEFECT_TARGETS: dict[str, str] = {
    "black_frame": "black_frame",
    "noise_fireflies": "fireflies",
    "missing_object": "flat_patch",
    "holes": "dark_holes",
    "texture_swap": "patch_seam",
    "floating_object": "floating_blob",
    "wrong_scale": "scale_bounds",
    "hollow_mesh": "watertight",
    "clipped_geometry": "edge_cut",
}


@dataclass(frozen=True)
class BaseRender:
    """One real render from the sweep — the source a member is derived from.

    The sweep is read-only (the brief says so, and the sweep is another
    night's work), so the harvester only ever *reads* it: the id, the path
    and the hash are what the reference set pins, and the hash is what makes
    the member's provenance checkable later ("the same bytes, the same
    member").
    """

    id: str
    """The sweep's own name for the scene: ``<scene>-s<seed>``."""

    scene: str
    seed: int
    image_path: str
    image_sha256: str
    width: int
    height: int
    mesh_path: str | None = None
    """The scene's ``scene.blend`` if one is live, else ``None``."""

    mesh_sha256: str | None = None

    done: bool = False
    """True when the sweep marked the whole scene finished (``DONE``).

    A scene still in flight has already produced its render — and still has
    its ``scene.blend``, which the sweep deletes when the scene finishes.
    That is the only window in which a mesh-level member is possible.
    """

    @property
    def has_mesh(self) -> bool:
        return self.mesh_path is not None


@dataclass(frozen=True)
class ReferenceMember:
    """One member of the reference set: a base render plus one seeded defect.

    A member with ``defect=None`` is a **clean control** — the clean half of
    the band ("reject no more than a set fraction of the clean ones"). Every
    member carries the recipe of its defect so that the broken image can be
    re-derived from the base render alone: the set is a recipe, and the
    renders are its cache.
    """

    id: str
    base_id: str
    defect: DefectKind | None
    layer: DefectLayer
    seed: int
    recipe: dict[str, Any] = field(default_factory=dict)
    derived_sha256: str | None = None
    """The hash of the *derived* image, once it has been materialised."""

    night: str | None = None
    """The night this member was added — the growth is a night-runner thing."""

    @property
    def clean(self) -> bool:
        return self.defect is None

    @property
    def target_check(self) -> str | None:
        if self.defect is None:
            return None
        return DEFECT_TARGETS[self.defect]


@dataclass(frozen=True)
class CheckOutcome:
    """One scripted check's measurement on one member.

    ``applicable=False`` means the check had nothing to measure — a mesh
    check on a member with no mesh. That is **not** a pass: it is a skipped
    measurement, and the fold counts it as such (a skipped check on a
    defective member is a false negative, because the defect is real).
    """

    check: str
    fired: bool
    detail: str
    measured: dict[str, float] = field(default_factory=dict)
    applicable: bool = True


@dataclass(frozen=True)
class CriticVerdict:
    """The scripted critic's judgement of one member.

    ``verdict@scripted`` is on its face because no critic model has been
    chosen and measured yet (X R4: the critic is "the largest unchosen
    dependency in the whole stack"). This row is the baseline that the
    choice has to beat — plan item 18's number.

    ``layer`` says where the member's defect lives — in the pixels or in the
    geometry — so the fold can measure a critic only on the layers it can
    actually see.

    ``edits`` is the verdict's **continuation**: the typed edits the critic
    proposes alongside the finding, in the closed vocabulary of
    :mod:`core.critic.edits`. A verdict that only says what is wrong is a
    complaint; a verdict that also says what to do about it is a move.
    """

    member_id: str
    base_id: str
    defect: DefectKind | None
    checks: tuple[CheckOutcome, ...]
    label: str = "verdict@scripted"
    degraded: str = "scripted"
    layer: str = "image"
    edits: tuple[Any, ...] = ()
    """The continuation: typed edits, in :mod:`core.critic.edits`."""

    @property
    def fired_checks(self) -> tuple[str, ...]:
        return tuple(c.check for c in self.checks if c.fired)

    @property
    def detected(self) -> bool:
        """Did the check that targets this member's defect fire?"""
        target = DEFECT_TARGETS.get(self.defect or "")
        if target is None:
            return False
        return any(c.check == target and c.fired for c in self.checks)

    def outcome(self, check: str) -> CheckOutcome | None:
        for c in self.checks:
            if c.check == check:
                return c
        return None


#: The scene's **infrastructure**, not its props: the terrain, the sky, the
#: liquid, the camera rig. Infinigen's terrain is a heightfield — an open
#: surface, never watertight — and the sky is a shell around the world. The
#: mesh checks are about *props* (the rocks, trees and bushes a scene is
#: populated with), so the infrastructure is excluded by name.
INFRASTRUCTURE = ("Terrain", "atmosphere", "emitter", "liquid", "camrig")


def is_prop(name: str) -> bool:
    """Is this object a prop rather than the scene's infrastructure?"""
    return not any(key in name for key in INFRASTRUCTURE)


def prop_family(name: str) -> str:
    """The asset family a prop belongs to.

    ``BoulderFactory(490645449).spawn_placeholder(3)`` and ``Tree.281`` are
    each one family; the instance index at the end is not part of it. A
    family is a set of props that *should* be the same size — the same rock,
    the same bush — so it is the right thing to compare sizes within.
    """
    base = name.split(".")[0]
    base = re.sub(r"\(\d+\)$", "", base)
    base = base.split("(")[0]
    return base


# -- the mesh half ------------------------------------------------------------


@dataclass(frozen=True)
class MeshObject:
    """One object of the scene, as the mesh probe measured it.

    The probe runs inside Blender (the engine's own interpreter) and writes
    these numbers out; the core never imports bpy, so the seam is a JSON
    file rather than a dependency.
    """

    name: str
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float
    watertight: bool = True
    vertices: int = 0
    faces: int = 0
    inward: float = 0.0
    """The fraction of the shell's faces pointing *inwards*.

    This is what separates a **hollow** shell from an **open** one. Infinigen's
    terrain and its eroded rock shells are open surfaces — they are not
    watertight, and they never will be — but every one of their faces points
    outwards. A hollow prop has faces pointing back at its own centre.
    """
    volume: float = 0.0
    """The mesh's signed volume. Positive for a correctly-wound solid."""

    @property
    def size(self) -> tuple[float, float, float]:
        return (self.x1 - self.x0, self.y1 - self.y0, self.z1 - self.z0)

    @property
    def diagonal(self) -> float:
        dx, dy, dz = self.size
        return float((dx * dx + dy * dy + dz * dz) ** 0.5)

    @property
    def centre(self) -> tuple[float, float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0, (self.z0 + self.z1) / 2.0)

    @property
    def floor_gap(self) -> float:
        """How far the object's lowest point sits above the scene's floor.

        A prop that hovers is the floating-object defect in the geometry.
        """
        return float(self.z0)


@dataclass(frozen=True)
class CameraInfo:
    """The scene's camera — the oracle for "is this object cut by the frame?".

    The frame's world bounds are computed from the camera's position, its
    rotation and the render's aspect, which is enough to ask whether an
    object's bounding box crosses the picture's edge (the clipped-geometry
    defect).
    """

    location: tuple[float, float, float]
    forward: tuple[float, float, float]
    up: tuple[float, float, float]
    right: tuple[float, float, float]
    half_width: float
    half_height: float
    depth: float
    clip_start: float = 0.1
    """The distance at which the renderer starts cutting geometry.

    A prop that straddles this plane is sliced by the camera — the
    **clipped geometry** defect. Nothing in the measured clean scenes does.
    """

    def projects(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        """A world point in camera space: (right, up, forward)."""
        loc = self.location
        rel = (point[0] - loc[0], point[1] - loc[1], point[2] - loc[2])
        right = sum(a * b for a, b in zip(rel, self.right))
        up = sum(a * b for a, b in zip(rel, self.up))
        forward = sum(a * b for a, b in zip(rel, self.forward))
        return (right, up, forward)


@dataclass(frozen=True)
class MeshStats:
    """What the probe read out of a scene's ``scene.blend``."""

    objects: tuple[MeshObject, ...] = ()
    camera: CameraInfo | None = None
    frame_width: int = 0
    frame_height: int = 0

    @property
    def empty(self) -> bool:
        return not self.objects
