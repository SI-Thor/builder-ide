"""Segment the mesh into the spec's parts, and check that the split found them.

This is where the Hy4 guard bites hardest. A geometric split cuts the prop
along the spec's axes, and the cut may well *not* isolate the functional
part: a chest's lid line in a generated chest may be at 62 % of the height
rather than the 72 % the planner expected, and the "lid" that comes out is
the top 28 % of the chest — a slice of the lid and a slice of the body.
The joint then moves the wrong body, the action completes, and the
completion rate measures a number that means nothing.

So the split is measured, not trusted. Every part comes back with:

* the connected components it fell into, and each one's share of the area —
  a part in three pieces has not been segmented;
* the IoU between the piece's box and the planner's *claim* about where the
  part is — a number that says whether the split found what was asked for;
* whether the piece sits inside the claimed region at all;
* the flags for an empty part, a fragmented part, and two parts claiming
  the same triangles.

The verdict is per part, and the moving part's verdict is the one that
decides whether the prop's completion counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.physag.geometry import (
    MeshPart,
    axis_index,
    bbox_iou,
    clip_mesh_at_plane,
    largest_component,
    surface_area,
)
from core.physag.spec import Box, Cut, InteractionSpec, Part

__all__ = [
    "PartPiece",
    "Segmentation",
    "SegmentationError",
    "segment",
    "segmentation_from_parts",
]


class SegmentationError(ValueError):
    """A split that cannot be made at all."""


#: The clearance left between two parts at the cut, in metres. A real hinge
#: has one; without it the two hulls share the cut surface and the
#: simulation reports an initial penetration that is the model's fault and
#: not the prop's.
DEFAULT_GAP_M = 0.001


@dataclass(frozen=True)
class PartPiece:
    """One part as it came out of the split, and how it was checked."""

    name: str
    role: str
    part: MeshPart
    #: The planner's claim, normalised.
    claimed: Box
    #: The piece's own box, in metres.
    bbox_min: np.ndarray
    bbox_max: np.ndarray
    #: The claim turned into metres.
    claimed_min: np.ndarray
    claimed_max: np.ndarray
    bbox_iou: float
    contained: bool
    components: int
    component_shares: tuple[float, ...]
    triangles: int
    ambiguous: bool
    notes: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        """Whether the split found the part the spec asked for.

        An empty part is never verified: there is nothing there for the
        joint to carry, and a part that reports itself as verified while
        holding no material would let the completion rate count a joint
        that moves nothing.
        """
        return (
            self.triangles > 0
            and not self.ambiguous
            and not self.notes
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "triangles": self.triangles,
            "components": self.components,
            "component_shares": [round(s, 6) for s in self.component_shares],
            "bbox_min_m": [round(float(v), 6) for v in self.bbox_min],
            "bbox_max_m": [round(float(v), 6) for v in self.bbox_max],
            "claimed_min_m": [round(float(v), 6) for v in self.claimed_min],
            "claimed_max_m": [round(float(v), 6) for v in self.claimed_max],
            "bbox_iou": round(self.bbox_iou, 6),
            "contained": self.contained,
            "ambiguous": self.ambiguous,
            "verified": self.verified,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Segmentation:
    """The whole split: every part, and the verdict on the split itself."""

    mesh: MeshPart
    pieces: dict[str, PartPiece]
    gap_m: float
    assigned_triangles: int
    total_triangles: int
    #: The mesh's area, and the parts' area together. Clipping swaps a
    #: cut face for the faces it replaced, so the two match: the parts
    #: tile the mesh.
    mesh_area: float = 0.0
    parts_area: float = 0.0
    reasons: tuple[str, ...] = ()
    #: Whether the parts were known already — because the kernel that
    #: built the prop made them, one body each — rather than cut out of
    #: the mesh. The cut is not used to clip the colliders when they are
    #: known: the two bodies do not share space, because the kernel put
    #: them where it wanted them.
    from_known_parts: bool = False

    @property
    def coverage(self) -> float:
        """The share of the mesh's area that the parts account for."""
        if self.mesh_area <= 0.0:
            return 0.0
        return self.parts_area / self.mesh_area

    @property
    def verified(self) -> bool:
        """Whether every part is a single, unambiguous piece."""
        return not self.reasons and all(p.verified for p in self.pieces.values())

    def piece(self, name: str) -> PartPiece:
        return self.pieces[name]

    def to_dict(self) -> dict:
        return {
            "gap_m": self.gap_m,
            "assigned_triangles": self.assigned_triangles,
            "total_triangles": self.total_triangles,
            "coverage": round(self.coverage, 6),
            "mesh_area": round(self.mesh_area, 6),
            "parts_area": round(self.parts_area, 6),
            "verified": self.verified,
            "reasons": list(self.reasons),
            "parts": {name: piece.to_dict() for name, piece in self.pieces.items()},
        }


def _inset(
    pieces: dict[str, MeshPart],
    cuts: list[tuple[str, Cut]],
    size: np.ndarray,
    gap: float,
) -> dict[str, MeshPart]:
    """Open a clearance at every cut, on both sides.

    The vertices within a band of the cut move away from it, by ``gap`` each
    way. The two parts then stand ``2 * gap`` apart, and the hulls that
    stand in for them do not share a surface.
    """
    if gap <= 0.0:
        return pieces
    band = 2.0 * gap
    moved = {name: part.vertices.copy() for name, part in pieces.items()}
    for owner, cut in cuts:
        if cut.kind == "plane":
            index = axis_index(cut.axis)
            at = cut.at * size[index]
            for name, verts in moved.items():
                if name == owner:
                    near = np.abs(verts[:, index] - at) <= band
                    if cut.keep == "above":
                        verts[near, index] += gap
                    else:
                        verts[near, index] -= gap
                else:
                    near = np.abs(verts[:, index] - at) <= band
                    if cut.keep == "above":
                        verts[near, index] -= gap
                    else:
                        verts[near, index] += gap
        elif cut.kind == "box":
            lo = np.asarray(cut.min) * size
            hi = np.asarray(cut.max) * size
            for name, verts in moved.items():
                if name == owner:
                    # The part inside the box moves deeper into it.
                    for axis in range(3):
                        near_lo = np.abs(verts[:, axis] - lo[axis]) <= band
                        near_hi = np.abs(verts[:, axis] - hi[axis]) <= band
                        verts[near_lo, axis] += gap
                        verts[near_hi, axis] -= gap
                else:
                    # Everything outside the box moves away from its faces.
                    for axis in range(3):
                        near_lo = np.abs(verts[:, axis] - lo[axis]) <= band
                        near_hi = np.abs(verts[:, axis] - hi[axis]) <= band
                        verts[near_lo, axis] -= gap
                        verts[near_hi, axis] += gap
    out: dict[str, MeshPart] = {}
    for name, part in pieces.items():
        out[name] = MeshPart(vertices=moved[name], triangles=part.triangles)
    return out


def _part_region(
    mesh: MeshPart,
    part: Part,
    all_parts: list[Part],
    size: np.ndarray,
) -> MeshPart:
    """The mesh's material that belongs to one part.

    A part's own cut says where its material is; every *other* part's
    cut says where it is not. The pieces therefore tile the mesh: the
    material at the cut is split between the two sides of it, with the
    triangles that straddle the plane flattened onto it.
    """
    current = mesh
    for other in all_parts:
        cut = other.cut
        if cut.kind == "rest":
            continue
        owner = other.name == part.name
        if cut.kind == "plane":
            index = axis_index(cut.axis)
            at = cut.at * size[index]
            normal = np.zeros(3)
            normal[index] = 1.0
            if cut.keep == "above":
                # The cut keeps z >= at.
                if owner:
                    current = clip_mesh_at_plane(current, -normal, at)
                else:
                    current = clip_mesh_at_plane(current, normal, -at)
            else:
                if owner:
                    current = clip_mesh_at_plane(current, normal, -at)
                else:
                    current = clip_mesh_at_plane(current, -normal, at)
        else:  # a box cut
            lo = np.asarray(cut.min) * size
            hi = np.asarray(cut.max) * size
            for index in range(3):
                normal = np.zeros(3)
                normal[index] = 1.0
                if owner:
                    # Inside the box: x >= lo and x <= hi.
                    current = clip_mesh_at_plane(current, -normal, lo[index])
                    current = clip_mesh_at_plane(current, normal, -hi[index])
                else:
                    # Outside the box: x <= lo and x >= hi.
                    current = clip_mesh_at_plane(current, normal, -lo[index])
                    current = clip_mesh_at_plane(current, -normal, hi[index])
    return current


def segment(
    mesh: MeshPart,
    spec: InteractionSpec,
    gap_m: float = DEFAULT_GAP_M,
) -> Segmentation:
    """Split a mesh into the spec's parts, and measure the split.

    The parts tile the mesh: each one is the material inside its own cut
    and outside every other part's cut, and the triangles at a cut are
    split between the two sides of it. Two parts claiming the same
    material is a contradiction in the spec, and it is reported rather
    than silently resolved.
    """
    if mesh.is_empty:
        raise SegmentationError("the mesh is empty")

    size = mesh.bbox_size
    origin = mesh.bbox_min
    reasons: list[str] = []

    raw: dict[str, MeshPart] = {}
    for part in spec.parts:
        raw[part.name] = _part_region(mesh, part, list(spec.parts), size)

    # Two parts claiming the same material is a contradiction. It shows up
    # as two parts whose boxes overlap deeply.
    for i, first in enumerate(spec.parts):
        for second in spec.parts[i + 1 :]:
            a = raw[first.name]
            b = raw[second.name]
            if a.is_empty or b.is_empty:
                continue
            lo = np.maximum(a.bbox_min, b.bbox_min)
            hi = np.minimum(a.bbox_max, b.bbox_max)
            if np.all(hi > lo):
                reasons.append(
                    f"parts {first.name!r} and {second.name!r} claim overlapping "
                    "material"
                )

    cuts = [(p.name, p.cut) for p in spec.parts if p.cut.kind != "rest"]
    moved = _inset(raw, cuts, size, gap_m)

    assigned = sum(int(piece.triangle_count) for piece in raw.values())
    mesh_area = surface_area(mesh)
    parts_area = sum(surface_area(piece) for piece in raw.values())

    pieces: dict[str, PartPiece] = {}
    for part in spec.parts:
        piece = moved[part.name]
        if piece.is_empty:
            reasons.append(f"part {part.name!r} came out empty")
        pieces[part.name] = _piece_record(part, piece, origin, size)

    return Segmentation(
        mesh=mesh,
        pieces=pieces,
        gap_m=gap_m,
        assigned_triangles=assigned,
        total_triangles=int(mesh.triangle_count),
        mesh_area=mesh_area,
        parts_area=parts_area,
        reasons=tuple(reasons),
        from_known_parts=True,
    )


def _piece_record(
    part: Part,
    piece: MeshPart,
    origin: np.ndarray,
    size: np.ndarray,
    claims_gate: bool = True,
) -> PartPiece:
    """Measure one part against the claim the spec makes about it.

    The same measurement runs whether the part came out of a geometric cut
    or out of the CAD kernel that built it: the planner's claim about where
    the part is is still a claim, and the CAD arm is exactly the case where
    checking it is worthwhile — the geometry is exact, so a poor claim is
    the planner's and not the kernel's.

    ``claims_gate`` decides what the measurement *does* to the verdict. In
    the segmentation arm the claim is all there is — the cut was made on
    the claim, so a part that does not sit where the claim says is a part
    the cut may not have found, and it fails the mapping. In the CAD arm
    the parts are the kernel's, the mapping is exact by construction, and
    the claim mismatch is the planner's, not the build's: it is recorded
    (the IoU and the containment are in the part's own record) and scored
    as claim accuracy, but it does not void the mapping.
    """
    notes: list[str] = []
    if piece.is_empty:
        # The part's own record says so too: the split-level reason is one
        # line in the run's log, and the part-level note is what the verdict
        # for that part is built on.
        notes.append("the part came out empty")
    components = 0
    shares: tuple[float, ...] = ()
    ambiguous = False

    # The piece is kept whole: dropping the smaller blobs would throw away
    # material the collider has to stand for. The fragmentation is measured
    # instead, and the flag lands on the part that moves — a base that fell
    # into two blobs still supports the prop, but a moving part that fell
    # into two is not the part the spec named.
    #
    # The bar for "this is really in pieces" is the same one the ambiguity
    # rule uses: the largest piece has to hold 90 % of the area. A handful
    # of stray triangles on the far side of a cut is what a clip leaves
    # behind — four triangles out of six hundred thousand — and voiding a
    # mapping over that would make the guard refuse to measure anything.
    # The number of pieces and their shares are in the record either way.
    if not piece.is_empty:
        _kept, components, share_list = largest_component(piece)
        shares = tuple(share_list)
        if components > 1 and shares[0] < 0.9:
            if claims_gate:
                notes.append(
                    f"the split fell into {components} pieces; the largest holds "
                    f"{shares[0]:.0%} of the area"
                )
                if part.role == "moving":
                    notes.append("the part is ambiguous: no piece dominates")
                    ambiguous = True
            # When the claims do not gate, the part is the kernel's own
            # body: the fragmentation is what the kernel made, and the
            # kernel moves it as one. The counts and shares are in the
            # record either way.
        if piece.triangle_count == 0:
            notes.append("the part has no triangles")

    claim = part.claimed_box()
    claimed_min = origin + np.asarray(claim.min) * size
    claimed_max = origin + np.asarray(claim.max) * size
    if piece.is_empty:
        bbox_min = np.zeros(3)
        bbox_max = np.zeros(3)
    else:
        bbox_min = piece.bbox_min
        bbox_max = piece.bbox_max

    iou = 0.0
    contained = False
    if not piece.is_empty:
        iou = bbox_iou(bbox_min, bbox_max, claimed_min, claimed_max)
        contained = bool(
            np.all(bbox_min >= claimed_min - 1e-9) and np.all(bbox_max <= claimed_max + 1e-9)
        )
        if part.role == "moving":
            if iou < 0.5 and claims_gate:
                notes.append(f"the piece covers {iou:.0%} of the region the spec claimed")
            if not contained and claims_gate:
                notes.append("the piece reaches outside the region the spec claimed")

    return PartPiece(
        name=part.name,
        role=part.role,
        part=piece,
        claimed=claim,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        claimed_min=claimed_min,
        claimed_max=claimed_max,
        bbox_iou=iou,
        contained=contained,
        components=components,
        component_shares=shares,
        triangles=int(piece.triangle_count),
        ambiguous=ambiguous,
        notes=tuple(notes),
    )


def segmentation_from_parts(
    mesh: MeshPart,
    parts: dict[str, MeshPart],
    spec: InteractionSpec,
    gap_m: float = 0.0,
) -> Segmentation:
    """Build the split from parts that are already known.

    The CAD arm knows where the parts are: the kernel that built the prop
    made them, one body each, so the split is exact rather than guessed.

    The split is still *measured*. The planner's claim about where the
    moving part is is a claim, and in the CAD arm it is the one thing that
    can still be wrong — the geometry is exact, so a poor claim is the
    planner's and not the kernel's. The claim is scored, not obeyed: the
    IoU and the containment land in every part's record, the arm reports
    claim accuracy beside its completion rate, and the mapping itself is
    voided only by what would void it in any arm — a part that came out
    empty. A kernel body that fell into pieces is noted, because the
    record keeps the fact, but the kernel moves the body as one and the
    mapping is not ambiguous about who moves.

    The parts are placed in the mesh's own frame, and the gap is not opened:
    the kernel's bodies already stand where it put them.
    """
    if mesh.is_empty:
        raise SegmentationError("the mesh is empty")

    size = mesh.bbox_size
    origin = mesh.bbox_min
    reasons: list[str] = []

    missing = [part.name for part in spec.parts if part.name not in parts]
    if missing:
        raise SegmentationError(
            f"{spec.prop}: no geometry for the part(s) {', '.join(missing)}"
        )

    pieces: dict[str, PartPiece] = {}
    for part in spec.parts:
        piece = parts[part.name]
        if piece.is_empty:
            reasons.append(f"part {part.name!r} came out empty")
        # The claims do not gate here: the parts are the kernel's, so a
        # claim that misses them is the planner's error, and it is scored
        # as claim accuracy rather than voiding the mapping.
        pieces[part.name] = _piece_record(
            part, piece, origin, size, claims_gate=False
        )

    assigned = sum(int(piece.triangle_count) for piece in parts.values())
    mesh_area = surface_area(mesh)
    parts_area = sum(surface_area(piece) for piece in parts.values())

    return Segmentation(
        mesh=mesh,
        pieces=pieces,
        gap_m=gap_m,
        assigned_triangles=assigned,
        total_triangles=int(mesh.triangle_count),
        mesh_area=mesh_area,
        parts_area=parts_area,
        reasons=tuple(reasons),
        from_known_parts=True,
    )


def part_of(spec: InteractionSpec, name: str) -> Part:
    """The spec's part by name."""
    part = spec.part(name)
    if part is None:
        raise SegmentationError(f"{spec.prop}: no part named {name!r}")
    return part
