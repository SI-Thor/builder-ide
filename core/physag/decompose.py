"""Turn a part into convex pieces, and measure whether the pieces are fair.

MuJoCo collides convex meshes only, so a part has to be cut into convex
pieces before it can be a collider. How that is done decides what the
stability score means, which is why the Hy4 guard is about it: a hull that
is fat, self-intersecting or blind to a concavity makes "nothing penetrated
past epsilon" a sentence about a shape nobody has.

The pieces here are produced in three steps.

**Hull.** A part's convex hull is a faithful stand-in when the part is
nearly convex: the hull of a smooth barrel is a fine polygon around it,
because the mesh carries hundreds of points around the barrel's girth.
Where the part really is concave, the hull bulges over the hollow, and the
depth of that bulge is measured — the distance from the part's vertices to
the hull's surface.

**Cut.** Where the bulge is too deep, the part is cut with a plane and each
side is tried again. The plane is chosen where the material has an
*edge*: the floor of a crate of walls ends and the walls begin, and the
plane between them separates the floor from the walls. The search is the
honest one — every candidate plane is tried, both children are measured,
and the cut whose children are the most faithful is taken.

**Clip.** Where a part has to stay on its own side of a cut that belongs
to the spec — the lid's plane, say — its pieces are clipped to that
half-space. The clip is done by cutting the piece's own vertices and
taking the hull of what is left, so the piece stays a proper convex solid:
a fan of triangles across the cut would leave a flat, zero-volume sliver
that MuJoCo cannot collide with.

The metrics that come out are the guard's: the volume ratio of the collider
to the mesh, the distance from the mesh to the collider, the distance from
the collider's own surface back to the mesh, and whether the pieces overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.physag.geometry import (
    ConvexPiece,
    MeshPart,
    SurfaceDistance,
    clip_mesh_at_plane,
    convex_hull,
    inside_mesh,
    distance_to_hull,
    distance_to_surface,
    distance_to_union,
    hull_metrics,
    inside_mesh,
    mesh_components,
    subsample_points,
    winding_numbers,
)

__all__ = [
    "Collider",
    "Decomposition",
    "DecompositionError",
    "clip_convex",
    "decompose_part",
    "measure_pieces",
]


class DecompositionError(ValueError):
    """A part that cannot be turned into convex pieces."""


#: How close two points have to be to count as the same point when the cut
#: face is capped. A micrometre is far below anything the simulation can
#: notice and far above float noise.
_MERGE_EPS = 1e-6


@dataclass(frozen=True)
class Collider:
    """One convex piece, ready to be written into an MJCF as a mesh."""

    vertices: np.ndarray
    faces: np.ndarray
    volume: float
    planes: np.ndarray

    @property
    def is_empty(self) -> bool:
        return self.vertices.shape[0] == 0 or self.faces.shape[0] == 0

    @classmethod
    def from_piece(cls, piece: ConvexPiece) -> "Collider":
        """A collider that is a convex piece, unchanged."""
        return cls(
            vertices=piece.vertices,
            faces=piece.faces,
            volume=piece.volume,
            planes=piece.planes,
        )


@dataclass(frozen=True)
class Decomposition:
    """A part's convex pieces, and how faithful they are to the part."""

    part_name: str
    colliders: tuple[Collider, ...]
    #: The volume of the part's own convex hull — the best a single convex
    #: piece could do.
    hull_volume: float
    #: The volume of the pieces together.
    collider_volume: float
    #: The deepest distance from the part's vertices to the collider's
    #: surface: the Hausdorff distance in one direction.
    deviation_m: float
    #: The 95th percentile of the same distances, which says whether the
    #: deepest point is an outlier or the shape.
    deviation_p95_m: float
    #: Whether the pieces overlap each other.
    overlaps: bool
    #: How deep the pieces swallow the material they cover: the hollow a
    #: convex hull fills in.
    concavity_m: float = 0.0
    #: How far the collider's own surface strays from the material it
    #: stands for: the mirror of the deviation.
    stray_m: float = 0.0
    stray_p95_m: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def piece_count(self) -> int:
        return len(self.colliders)

    def to_dict(self) -> dict:
        return {
            "part": self.part_name,
            "pieces": self.piece_count,
            "hull_volume_m3": round(self.hull_volume, 9),
            "collider_volume_m3": round(self.collider_volume, 9),
            "deviation_m": round(self.deviation_m, 6),
            "deviation_p95_m": round(self.deviation_p95_m, 6),
            "concavity_m": round(self.concavity_m, 6),
            "stray_m": round(self.stray_m, 6),
            "stray_p95_m": round(self.stray_p95_m, 6),
            "overlaps": self.overlaps,
            "notes": list(self.notes),
        }


def _dedupe(points: np.ndarray) -> np.ndarray:
    """Points with the near-duplicates removed."""
    if points.shape[0] == 0:
        return points
    seen: set[tuple[int, int, int]] = set()
    keep: list[np.ndarray] = []
    for point in points:
        key = (
            int(round(float(point[0]) * 1e7)),
            int(round(float(point[1]) * 1e7)),
            int(round(float(point[2]) * 1e7)),
        )
        if key in seen:
            continue
        seen.add(key)
        keep.append(point)
    return np.asarray(keep, dtype=np.float64).reshape(-1, 3)


def clip_convex(piece: ConvexPiece, normal: np.ndarray, offset: float) -> Collider:
    """Clip a convex piece to the half-space ``normal . x + offset <= 0``.

    The result is still convex. It is built by taking the piece's vertices
    that are inside the half-space, adding the points where the plane cuts
    through its edges, and taking the hull of what is left — so the piece is
    a proper solid with a real volume.

    The other way round — cutting the faces and capping the hole with a fan
    of triangles — was tried and dropped: the cap's centre lies in the same
    plane as the ring around it, which is exactly the shape of mesh that
    MuJoCo refuses to make a convex hull of. It also leaves a piece with no
    thickness when the plane happens to pass through a face, and a piece
    with no thickness is a piece the simulation cannot stand anything on.
    """
    normal = np.asarray(normal, dtype=np.float64)
    norm = float(np.linalg.norm(normal))
    if norm < 1e-12:
        raise DecompositionError("the clipping plane has no normal")
    normal = normal / norm
    offset = float(offset) / norm

    if piece.is_empty:
        return Collider(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), 0.0, np.zeros((0, 4)))

    vertices = piece.vertices
    signed = vertices @ normal + offset
    if signed.max() <= 0.0:
        # Already inside: nothing to clip.
        return Collider(
            vertices=vertices,
            faces=piece.faces,
            volume=piece.volume,
            planes=piece.planes,
        )
    if signed.min() > 0.0:
        # Entirely outside: the piece is gone.
        return Collider(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), 0.0, np.zeros((0, 4)))

    # The piece's edges: every pair of vertices that a face of the piece
    # joins. The plane's crossings with those edges are the new vertices
    # of the clipped solid.
    edges: set[tuple[int, int]] = set()
    for face in piece.faces:
        count = face.shape[0]
        for i in range(count):
            a = int(face[i])
            b = int(face[(i + 1) % count])
            edges.add((a, b) if a < b else (b, a))

    points: list[np.ndarray] = []
    inside = signed <= 0.0
    for index in np.nonzero(inside)[0]:
        points.append(vertices[index])
    for a, b in edges:
        sa = signed[a]
        sb = signed[b]
        if (sa < 0.0 < sb) or (sb < 0.0 < sa):
            t = sa / (sa - sb)
            points.append(vertices[a] + t * (vertices[b] - vertices[a]))

    if len(points) < 4:
        return Collider(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), 0.0, np.zeros((0, 4)))

    hull = convex_hull(np.asarray(points, dtype=np.float64))
    if hull.is_empty:
        return Collider(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), 0.0, np.zeros((0, 4)))
    return Collider.from_piece(hull)


def _cut_by_plane(part: MeshPart, normal: np.ndarray, offset: float) -> tuple[MeshPart, MeshPart]:
    """Cut a part into the part below a plane and the part above it.

    The cut is a real cut: a triangle that crosses the plane is cut in
    two, and each side keeps its own piece of it. A triangle of a CAD
    mesh can be the whole face of a crate — a quad that spans the prop
    from wall to wall — and a cut that gives such a triangle to one side
    or the other puts half of the prop's material in the wrong piece. The
    crossing points the cut makes are also the corners the piece's hull
    needs: without them the hull of a cut piece is a wedge where the
    prop's solid is a slab.
    """
    below = clip_mesh_at_plane(part, normal, offset)
    above = clip_mesh_at_plane(part, -np.asarray(normal, dtype=np.float64), -float(offset))
    return below, above


def _subsample(points: np.ndarray, limit: int = 2000) -> np.ndarray:
    """A spread-out subset of the points, for the cheap evaluations."""
    return subsample_points(points, limit)


def _edge_positions(vertices: np.ndarray, tol_m: float) -> list[list[float]]:
    """The positions along each axis where the material has an edge.

    An edge of the material is where its cross-section changes: where a
    crate's floor ends and its walls begin, where one wall ends and the
    next one starts. In the material's own coordinates those are the
    places where the material is thin or absent — the edges of the gaps
    between the material's coordinates — and the quantiles, which are
    where the material's bulk is.

    The positions are taken from the part as it came in, not from a piece
    that has already been cut. A cut leaves new points on the plane it
    was made on, and those points are not edges of anything: they would
    put the next cut in the middle of a wall.
    """
    out: list[list[float]] = []
    for axis in range(3):
        values = np.sort(vertices[:, axis])
        if values.size == 0:
            out.append([])
            continue
        positions = {
            float(np.percentile(values, 20)),
            float(np.percentile(values, 35)),
            float(np.percentile(values, 50)),
            float(np.percentile(values, 65)),
            float(np.percentile(values, 80)),
        }
        if values.size >= 2:
            gaps = np.diff(values)
            wide = gaps > max(2.0 * tol_m, 1e-9)
            for index in np.nonzero(wide)[0][:8]:
                # Both edges of the gap: the material stops at one and
                # starts again at the other, and either of them is a plane
                # the material has an edge on.
                positions.add(float(values[index]))
                positions.add(float(values[index + 1]))
            # A quantile that falls inside a wide gap falls in the middle
            # of a hollow: the middle of a crate's cavity is the median
            # of the crate's coordinates, and cutting there cuts air. The
            # gap's own edges are the planes worth cutting on.
            for index in np.nonzero(wide)[0]:
                for position in list(positions):
                    if float(values[index]) < position < float(values[index + 1]):
                        positions.discard(position)
        out.append(sorted(positions))
    return out


def _candidate_cuts(
    sample: np.ndarray,
    hull: ConvexPiece,
    tol_m: float,
    axis_positions: list[list[float]] | None = None,
    max_face_candidates: int = 8,
) -> list[tuple[np.ndarray, float]]:
    """The planes worth trying to cut this piece on.

    Two kinds of candidate, and both are needed.

    A hull face that floats above the material is a hollow: cutting on it,
    down at the material's own level, takes the hollow out.

    An axis-aligned plane through the material's own coordinates is an
    **edge** of the material: the floor of a crate of walls ends and the
    walls begin, and the plane between them separates the floor from the
    walls.
    """
    cuts: list[tuple[np.ndarray, float]] = []
    vertices = sample

    # The hull's own faces are *not* candidates. A face that floats above
    # the material is a hollow, and cutting on it would be the obvious way
    # to take the hollow out — but the plane that comes out of it runs
    # through the middle of the material at an angle, and a cut like that
    # leaves two pieces whose own faces cut through the material. The
    # material's own edges are where the shape really turns, and a cut
    # there is a cut the shape agrees with.

    if axis_positions is None:
        axis_positions = _edge_positions(vertices, tol_m)
    for axis, positions in enumerate(axis_positions):
        for position in positions:
            normal = np.zeros(3)
            normal[axis] = 1.0
            cuts.append((normal, -position))
    return cuts


def _is_real(
    piece: MeshPart,
    tol_m: float,
    total_area: float = 0.0,
    min_share: float = 0.05,
) -> bool:
    """Whether a cut-off piece is a piece of the part and not a sliver.

    A cut that runs along the material's own boundary leaves a piece with
    no thickness — a face, not a solid — and the simulation cannot stand
    anything on it. A cut that takes off a sliver of the material leaves a
    piece that is faithful only because there is almost nothing in it. A
    cut that crosses a hollow leaves a piece of *air*: the hull of a
    piece of air is a box in the middle of a crate's cavity, and a
    collider that fills the cavity is exactly what the guard is there to
    catch. All three are refused.
    """
    if piece.is_empty:
        return False
    extent = piece.bbox_max - piece.bbox_min
    if float(extent.min()) < max(tol_m, 1e-4):
        return False
    if total_area > 0.0:
        area = float(piece.triangle_areas().sum())
        if area < min_share * total_area:
            return False
    return True


def measure_pieces(
    pieces: list[Collider],
    material: MeshPart,
    deviation_point_limit: int = 20000,
    surface_sample_limit: int = 200,
) -> dict[str, float]:
    """How faithful a set of convex pieces is to the material they stand for.

    Two directions, because either one alone can be fooled.

    The **deviation** is from the material to the collider: how far a
    vertex of the material is from the nearest piece. It says whether the
    collider misses material — a lid that was cut off and not put back.

    The **stray** is from the collider to the material: how far the
    collider's own surface is from the material's surface. It says whether
    the collider bulges — a hull that bridges the gap between a crate's
    slats has a surface in mid-air, and that surface is what the
    simulation's contacts are measured against.

    The **concavity** is how deep inside the pieces the material's own
    surface lies: the hollow a convex hull fills in. It is a diagnostic
    rather than the guard, because the stray already says the same thing
    from the other side.
    """
    out = {
        "deviation_m": 0.0,
        "deviation_p95_m": 0.0,
        "stray_m": 0.0,
        "stray_p95_m": 0.0,
        "concavity_m": 0.0,
    }
    if not pieces or material.is_empty:
        return out

    # The material is measured on its **surface**, not on its vertices. A
    # vertex is a corner, and a prop's corners are few: a CAD crate's
    # whole wall structure hangs on sixteen of them, and a collider that
    # misses the wall between two corners has every corner covered and
    # no wall at all. The surface is where the contacts happen, so the
    # surface is what the collider has to stand on.
    sample = _sample_mesh(material, deviation_point_limit)
    planes = [piece.planes for piece in pieces if piece.planes.shape[0] > 0]
    if planes and sample.shape[0] > 0:
        distances = distance_to_union(sample, planes)
        finite = distances[np.isfinite(distances)]
        if finite.size:
            out["deviation_m"] = float(finite.max())
            out["deviation_p95_m"] = float(np.percentile(finite, 95))

    stray, stray_p95 = _stray_distance(pieces, material)
    out["stray_m"] = stray
    out["stray_p95_m"] = stray_p95
    out["concavity_m"] = _hollow_depth(pieces, material, 0.0)
    return out


def decompose_part(
    part: MeshPart,
    part_name: str,
    tol_m: float,
    max_pieces: int = 32,
    max_depth: int = 8,
    hull_point_limit: int = 4000,
    deviation_point_limit: int = 5000,
    surface_sample_limit: int = 200,
    search_point_limit: int = 800,
    trace: list | None = None,
) -> Decomposition:
    """Cut a part into convex pieces, each within ``tol_m`` of the part.

    The search is the honest one: every candidate cut is tried, both
    children are measured, and the cut whose *worst* child is the most
    faithful is taken. A part that is already nearly convex — a lid, a
    door panel, a board — comes back as a single piece, because no cut
    improves on its hull.

    A generated prop carries hundreds of thousands of triangles, and a
    convex hull of all of them costs more than the whole rest of the
    loop. The hull is therefore built from a spread-out subset of the
    vertices; the subset's points are on the surface, so the hull they
    make is inscribed in the same way the full hull would be, and the
    fidelity is *measured* afterwards against every vertex.
    """
    if part.is_empty:
        return Decomposition(
            part_name=part_name,
            colliders=(),
            hull_volume=0.0,
            collider_volume=0.0,
            deviation_m=0.0,
            deviation_p95_m=0.0,
            overlaps=False,
            notes=("the part is empty",),
        )

    notes: list[str] = []
    whole_hull = convex_hull(_subsample(part.vertices, hull_point_limit))
    pieces: list[Collider] = []
    # The material's own components are the first cut: a crate's floor
    # and its four walls are five things, and one hull of the five
    # swallows the space in the middle of the crate. The components are
    # already there — the split is free.
    components = mesh_components(part)
    # The distance to the material's surface, for the whole part: the
    # question the decomposition keeps asking is "does this hull stand in
    # for the material", and the answer is about the hull's *surface* and
    # not about the material's depth below it. A box of walls has all of
    # its material on the hull's outside, so the depth is zero while the
    # hull's top face is floating over the whole cavity.
    surface = SurfaceDistance(part)
    # The planes worth cutting on, from the part's own coordinates: the
    # material's edges. They are worked out once, because a cut leaves new
    # points on its own plane and those points are not edges.
    axis_positions = _edge_positions(part.vertices, tol_m)

    def _score(
        vertices: np.ndarray,
        material: MeshPart | None = None,
        cuts: list[tuple[np.ndarray, float]] | None = None,
        limit: int | None = None,
    ) -> tuple[ConvexPiece, float, float]:
        """The hull of a piece, and how faithful it is to the material.

        Two numbers, and a piece is only as good as the worse of them.

        The **stray** is from the hull's own surface to the material's
        surface: how far the hull bulges away from the material it
        stands for. The faces that lie on a cut plane are left out of
        the search's number: they are the boundary between two pieces of
        the same material, and how far they are from the material's
        surface is a statement about the material's own thickness, not
        about the collider bulging. The full stray keeps them, and it is
        the number the guard uses.

        The **coverage** is the other way round: how far the material's
        own surface is from the hull. A hull that misses the material — a
        wedge where the prop's solid is a slab — has a small stray and a
        large coverage, and the second number is the one that catches it.
        """
        limit = limit or hull_point_limit
        sample = _subsample(vertices, max(limit, deviation_point_limit))
        hull = convex_hull(_subsample(sample, limit))
        if hull.is_empty:
            return hull, float("inf"), float("inf")
        points = _sample_faces(hull, surface_sample_limit)
        if points.shape[0] == 0:
            return hull, 0.0, 0.0
        distances = surface(points)

        # The faces on a cut plane are left out: they are the boundary
        # between two pieces of the same material, and how far they are
        # from the material's surface is a statement about the material's
        # own thickness, not about the collider bulging. What the cut
        # face *covers* — the hollow it spans — is the hollow measure
        # below.
        on_cut = np.zeros(points.shape[0], dtype=bool)
        for normal, offset in cuts or []:
            on_cut |= np.abs(points @ normal + offset) <= 1e-6
        outer = distances[~on_cut] if (~on_cut).any() else distances
        if getattr(surface, "closed", False):
            # A closed mesh knows which side of its surface is inside, so
            # a face that lies within the material is not a stray.
            stray = float(max(float(outer.max()), 0.0))
        else:
            stray = float(np.percentile(outer, 95))

        coverage = 0.0
        if material is not None and not material.is_empty:
            own = _sample_mesh(material, surface_sample_limit)
            if own.shape[0] > 0:
                # A point the hull stands over is covered, however deep
                # inside the hull it is: the cavity of a crate is inside
                # the hull of a crate and the collider does not have to
                # reach it. A point the hull does not stand over is as
                # far out as it is from the hull.
                gaps = distance_to_union(own, [hull.planes])
                finite = gaps[np.isfinite(gaps)]
                if finite.size:
                    coverage = float(np.percentile(finite, 95))
        if trace is not None:
            trace.append(
                {
                    "event": "score",
                    "vertices": int(vertices.shape[0]),
                    "stray_mm": round(stray * 1000, 3),
                    "coverage_mm": round(coverage * 1000, 3),
                    "closed": bool(getattr(surface, "closed", False)),
                    "hull_bbox": [round(float(v), 4) for v in hull.vertices.min(axis=0)]
                    + [round(float(v), 4) for v in hull.vertices.max(axis=0)],
                }
            )
        return hull, max(stray, coverage), float(np.percentile(distances, 95))

    def _recurse(
        piece: MeshPart,
        depth: int,
        cuts: list[tuple[np.ndarray, float]] | None = None,
    ) -> None:
        cuts = list(cuts or [])
        if piece.is_empty:
            return
        if len(pieces) >= max_pieces or depth >= max_depth:
            hull = convex_hull(_subsample(piece.vertices, hull_point_limit))
            if not hull.is_empty:
                pieces.append(Collider.from_piece(hull))
                notes.append(
                    f"a piece reached the depth limit ({max_depth}) and was "
                    "left as one hull"
                )
            return

        hull, outer_stray, _full_stray = _score(piece.vertices, piece, cuts, search_point_limit)
        if hull.is_empty:
            return
        if trace is not None:
            trace.append(
                {
                    "event": "piece",
                    "depth": depth,
                    "outer_stray_mm": round(outer_stray * 1000, 3),
                    "vertices": int(piece.vertices.shape[0]),
                    "bbox": [round(float(v), 4) for v in piece.bbox_min]
                    + [round(float(v), 4) for v in piece.bbox_max],
                }
            )
        if outer_stray <= tol_m:
            # The hull stands in for the material: its surface does not
            # stray from the material by more than the tolerance.
            final = convex_hull(_subsample(piece.vertices, hull_point_limit))
            if not final.is_empty:
                pieces.append(Collider.from_piece(final))
            return

        # A cut is worth making when it makes a piece **faithful**: when
        # the child's hull hugs its own material. That is progress, even
        # when the other child is no better than it was — and it is the
        # only way a ring of material comes apart. A crate's four walls
        # are one hull until a cut takes one wall away, and until then no
        # measure of the whole improves.
        #
        # So the cuts are ranked by how much they achieve: a cut that
        # makes both children faithful beats one that makes one, and a
        # cut that makes neither is no cut at all. Within a rank the
        # smaller total wins — the total being the stray distance
        # weighed by the size of the piece it was measured on.
        best: tuple[tuple[int, float], np.ndarray, float, float] | None = None
        total_area = float(piece.triangle_areas().sum())
        for normal, offset in _candidate_cuts(
            _subsample(piece.vertices, 2000), hull, tol_m, axis_positions
        ):
            below, above = _cut_by_plane(piece, normal, offset)
            if not _is_real(below, tol_m, total_area) or not _is_real(
                above, tol_m, total_area
            ):
                if trace is not None:
                    trace.append(
                        {
                            "event": "cut_refused",
                            "axis": int(np.argmax(np.abs(normal))),
                            "at": round(float(offset), 6),
                            "why": "the cut would leave a sliver",
                        }
                    )
                continue
            hull_below, stray_below, _ = _score(
                below.vertices, below, cuts + [(normal, offset)], search_point_limit
            )
            hull_above, stray_above, _ = _score(
                above.vertices, above, cuts + [(-normal, -offset)], search_point_limit
            )
            if hull_below.is_empty or hull_above.is_empty:
                continue
            faithful_below = stray_below <= tol_m
            faithful_above = stray_above <= tol_m
            if faithful_below and faithful_above:
                tier = 0
            elif faithful_below or faithful_above:
                tier = 1
            else:
                tier = 2
            total = stray_below * float(hull_below.volume) + stray_above * float(
                hull_above.volume
            )
            key = (tier, total)
            if trace is not None:
                trace.append(
                    {
                        "event": "cut_tried",
                        "axis": int(np.argmax(np.abs(normal))),
                        "at": round(float(offset), 6),
                        "tier": tier,
                        "stray_below_mm": round(stray_below * 1000, 3),
                        "stray_above_mm": round(stray_above * 1000, 3),
                    }
                )
            if best is None or key < best[0]:
                best = (key, normal, offset, total)

        current = outer_stray * float(hull.volume)
        if best is None or (best[0][0] >= 2 and best[0][1] >= current):
            # No cut makes a piece faithful and none of them improves on
            # the piece as it is; keeping the hull is the honest answer,
            # and it is recorded.
            final = convex_hull(_subsample(piece.vertices, hull_point_limit))
            if not final.is_empty:
                pieces.append(Collider.from_piece(final))
            notes.append(
                f"a piece whose surface strays {outer_stray * 1000:.1f} mm from "
                "the material could not be cut further and was left as one hull"
            )
            return

        _key, normal, offset, _total = best
        if trace is not None:
            trace.append(
                {
                    "event": "cut_taken",
                    "axis": int(np.argmax(np.abs(normal))),
                    "at": round(float(offset), 6),
                    "depth": depth,
                }
            )
        below, above = _cut_by_plane(piece, normal, offset)
        _recurse(below, depth + 1, cuts=clips_of(cuts, normal, offset))
        _recurse(above, depth + 1, cuts=clips_of(cuts, normal, offset, flip=True))

    def clips_of(
        cuts: list[tuple[np.ndarray, float]],
        normal: np.ndarray,
        offset: float,
        flip: bool = False,
    ) -> list[tuple[np.ndarray, float]]:
        """The cut planes a child carries, with the child's own side."""
        if flip:
            return cuts + [(-np.asarray(normal), -float(offset))]
        return cuts + [(np.asarray(normal), float(offset))]

    for component in components:
        _recurse(component, 0)

    if not pieces:
        raise DecompositionError(f"part {part_name!r}: no convex piece could be made")

    # A piece that is mostly hollow is a piece of air: the cavity in the
    # middle of a crate is a box of nothing, and its hull is a box that
    # fills the crate's cavity. Dropping it is safe only where the
    # material it stands over is covered by the pieces that remain — for
    # a crate's cavity that holds, because the walls carry their own
    # pieces, and for a lattice it does not: the hull left standing over
    # two pales is mostly the gap between them, and it is the only piece
    # over either pale.
    #
    # So the test is the counterfactual the guard itself would run: with
    # the piece gone, is any sampled point of the material left farther
    # from what remains than the tolerance? The max, not a percentile —
    # the deviation the guard measures later is the max, and a piece whose
    # material is "mostly" covered is exactly the piece whose last five
    # per cent the guard would catch.
    kept: list[Collider] = []
    hollows: list[tuple[Collider, float]] = []
    for piece in pieces:
        hollow = _piece_hollow(piece, part, surface)
        if hollow > tol_m:
            hollows.append((piece, hollow))
        else:
            kept.append(piece)

    if hollows:
        sample = _sample_mesh(part, deviation_point_limit)
    for piece, hollow in hollows:
        if kept:
            gaps = distance_to_union(sample, [p.planes for p in kept])
            finite = gaps[np.isfinite(gaps)]
            covered = float(finite.max()) if finite.size else float("inf")
        else:
            covered = float("inf")  # nothing else covers anything yet
        if covered <= tol_m:
            notes.append(
                f"a piece that was mostly hollow ({hollow * 1000:.1f} mm deep) "
                "was dropped: it was the inside of the prop, not the prop"
            )
            continue
        kept.append(piece)
        notes.append(
            f"a piece that was mostly hollow ({hollow * 1000:.1f} mm deep) was "
            "kept: the material under it is covered by nothing else"
        )
    if kept:
        pieces = kept

    measured = measure_pieces(pieces, part, deviation_point_limit, surface_sample_limit)
    collider_volume = float(sum(p.volume for p in pieces))
    overlaps = _pieces_overlap(pieces)

    return Decomposition(
        part_name=part_name,
        colliders=tuple(pieces),
        hull_volume=float(whole_hull.volume),
        collider_volume=collider_volume,
        deviation_m=measured["deviation_m"],
        deviation_p95_m=measured["deviation_p95_m"],
        concavity_m=measured["concavity_m"],
        stray_m=measured["stray_m"],
        stray_p95_m=measured["stray_p95_m"],
        overlaps=overlaps,
        notes=tuple(notes),
    )


def _piece_hollow(piece: Collider, material: MeshPart, surface: SurfaceDistance) -> float:
    """How deep a hollow the piece fills in.

    A closed material knows which side of its surface is inside, and the
    winding number says which side a point is on however far it is from
    the surface: a point of the piece that lies in the air is a hollow
    the piece has swallowed, and a point that lies within the material is
    not. An open material has no inside to speak of, and the measure
    falls back on the distance from the piece's inside to the material's
    surface.
    """
    if piece.is_empty or piece.volume <= 0.0:
        return 0.0
    points = _sample_piece(piece, 120)
    if points.shape[0] == 0:
        return 0.0
    if getattr(surface, "closed", False):
        # A point right on the surface is wound around half a turn, and
        # the points near it are between: they are neither in the air nor
        # in the material, and they say nothing about the hollow.
        wound = winding_numbers(points, material)
        outside = np.abs(wound) < 0.25
        if not outside.any():
            return 0.0
        depths = surface(points[outside])
        return float(max(float(depths.max()), 0.0))
    depths = surface(points)
    return float(np.percentile(depths, 95))


def _hollow_depth(
    pieces: list[Collider],
    material: MeshPart,
    tol_m: float,
    samples_per_piece: int = 400,
) -> float:
    """How deep a hollow the collider fills in.

    The depth of a material vertex below the hull's surface cannot see a
    hollow: a crate's walls are *on* the hull's outside, so every one of
    their vertices sits on the surface and the depth is zero — while the
    collider has swallowed the crate's whole interior.

    The hollow is in the *interior* of the collider, and the measure has to
    look there. So the pieces are sampled inside — points drawn uniformly
    from each piece's own volume — and each sample is measured against the
    material it stands for. The deepest such distance is how far inside a
    hollow the collider reaches: near zero for a solid prop, and the
    prop's own thickness for a shell.

    The distance is to the material's **surface**, not to its vertices:
    the middle of a panel is millimetres from the panel and far from its
    corners, and a measure that said "far from the corners" would call a
    flat panel a cavity.
    """
    if not pieces or material.is_empty:
        return 0.0

    deepest = 0.0
    for piece in pieces:
        if piece.is_empty or piece.volume <= 0.0:
            continue
        points = _sample_piece(piece, samples_per_piece)
        if points.shape[0] == 0:
            continue
        distances = distance_to_surface(points, material)
        finite = distances[np.isfinite(distances)]
        if finite.size:
            deepest = max(deepest, float(np.max(finite)))
    return deepest


def _stray_distance(
    pieces: list[Collider],
    material: MeshPart,
    samples_per_piece: int = 120,
) -> tuple[float, float]:
    """How far the collider's own surface strays from the material.

    This is the mirror of the deviation: the deviation asks whether the
    collider misses material, and this asks whether the collider bulges
    away from it. A hull that bridges the gap between a crate's slats has
    a surface in mid-air, and that surface is what the simulation's
    contacts are measured against — so a collider that strays is a
    collider whose "nothing penetrated past epsilon" is a statement about
    the collider.

    The measure is of the *surface*, not of the interior, so it says the
    same thing for a solid prop and for a shell: a solid prop's collider
    sits on its material and strays by nothing, and a shell's collider
    strays by the gap it bridges.

    The pieces' faces are sampled — points drawn on the triangles, with
    each triangle picked in proportion to its area — and each is measured
    against the material's surface.
    """
    if not pieces or material.is_empty:
        return 0.0, 0.0

    surface = SurfaceDistance(material)
    distances: list[float] = []
    for piece in pieces:
        if piece.is_empty or piece.faces.shape[0] == 0:
            continue
        points = _sample_faces(piece, samples_per_piece)
        if points.shape[0] == 0:
            continue
        measured = surface(points)
        if getattr(surface, "closed", False):
            # A closed material knows which side is inside: a collider
            # face that lies within the material is not a stray.
            measured = np.where(measured > 0.0, measured, 0.0)
        distances.extend(float(v) for v in measured)

    if not distances:
        return 0.0, 0.0
    values = np.asarray(distances, dtype=np.float64)
    return float(values.max()), float(np.percentile(values, 95))


def _sample_mesh(mesh: MeshPart, count: int) -> np.ndarray:
    """Points drawn on a mesh's triangles, in proportion to their area."""
    if count <= 0 or mesh.triangles.shape[0] == 0:
        return np.zeros((0, 3))
    vertices = mesh.vertices
    triangles = mesh.triangles
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total = float(areas.sum())
    if total <= 0.0:
        return np.zeros((0, 3))
    rng = np.random.default_rng(20261101)
    picks = rng.choice(triangles.shape[0], size=count, p=areas / total)
    u = rng.random((count, 1))
    v = rng.random((count, 1))
    over = u + v > 1.0
    u[over] = 1.0 - u[over]
    v[over] = 1.0 - v[over]
    return a[picks] + u * (b[picks] - a[picks]) + v * (c[picks] - a[picks])


def _sample_faces(piece: Collider, count: int) -> np.ndarray:
    """Points drawn on a convex piece's faces, in proportion to their area."""
    if count <= 0 or piece.faces.shape[0] == 0:
        return np.zeros((0, 3))
    vertices = piece.vertices
    triangles = piece.faces
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total = float(areas.sum())
    if total <= 0.0:
        return np.zeros((0, 3))

    rng = np.random.default_rng(20261101)
    picks = rng.choice(triangles.shape[0], size=count, p=areas / total)
    u = rng.random((count, 1))
    v = rng.random((count, 1))
    over = u + v > 1.0
    u[over] = 1.0 - u[over]
    v[over] = 1.0 - v[over]
    return (
        a[picks]
        + u * (b[picks] - a[picks])
        + v * (c[picks] - a[picks])
    )


def _sample_piece(piece: Collider, count: int) -> np.ndarray:
    """Points drawn uniformly from a convex piece's volume.

    The piece is a mesh, so the sampling is by rejection: a point is drawn
    in the piece's box and kept when it is inside every face of the piece.
    The faces are few — a convex piece has as many faces as it has
    corners — so the test is cheap.
    """
    if count <= 0 or piece.is_empty:
        return np.zeros((0, 3))
    lo = piece.vertices.min(axis=0)
    hi = piece.vertices.max(axis=0)
    planes = piece.planes
    rng = np.random.default_rng(20261101)
    if planes.shape[0] == 0:
        return np.zeros((0, 3))
    out: list[np.ndarray] = []
    for _ in range(12):
        if sum(len(chunk) for chunk in out) >= count:
            break
        candidates = rng.random((count * 2, 3)) * (hi - lo) + lo
        signed = candidates @ planes[:, :3].T + planes[:, 3]
        inside = np.all(signed <= 1e-9, axis=1)
        if inside.any():
            out.append(candidates[inside])
    if not out:
        return np.zeros((0, 3))
    return np.concatenate(out, axis=0)[:count]


def _pieces_overlap(pieces: list[Collider]) -> bool:
    """Whether two convex pieces of the same part share space.

    The test is the separating axis theorem, reduced to the question that
    matters here: is there a direction along which the two pieces do not
    overlap? If not, they share space.
    """
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            a, b = pieces[i], pieces[j]
            if a.is_empty or b.is_empty:
                continue
            if _convex_overlap(a, b):
                return True
    return False


def _convex_overlap(a: Collider, b: Collider) -> bool:
    """Whether two convex bodies share space, by the separating axis test."""
    for collider, other in ((a, b), (b, a)):
        if collider.planes.shape[0] == 0:
            continue
        normals = collider.planes[:, :3]
        offsets = collider.planes[:, 3]
        gaps = other.vertices @ normals.T + offsets
        if gaps.min() >= -1e-6:
            # Every vertex of `other` is outside this face: a separating
            # plane exists, so the two do not share space. Pieces that
            # touch at the cut share a plane, and touching is not
            # overlapping.
            return False
    return True
