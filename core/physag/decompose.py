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

**Cut.** Where the bulge is too deep, the part is cut with the plane of the
hull face that floats highest above the material, and each side is tried
again. The face that floats highest is where the part is most concave, so
cutting there removes the hollow instead of shaving a corner.

**Clip.** Each piece is then clipped to its own half-space, so that the
pieces of two parts cannot overlap at the cut. A hull is allowed to bulge
past the plane a part was cut on — the rim of a chest does — and two such
bulges would interpenetrate at the first step of every simulation and be
reported as the prop's fault. Clipping keeps each piece inside the region
its part owns, with the clearance the builder left at the cut.

The metrics that come out are the guard's: the volume ratio of the collider
to the mesh, the distance from the mesh to the collider, and whether the
pieces overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.physag.geometry import (
    ConvexPiece,
    MeshPart,
    convex_hull,
    distance_to_hull,
    distance_to_union,
    hull_metrics,
)

__all__ = [
    "Collider",
    "Decomposition",
    "DecompositionError",
    "clip_convex",
    "decompose_part",
    "overlap_volume_estimate",
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

    The result is still convex, and it is closed: the new face where the
    plane cut through the piece is capped with a fan of triangles, so the
    piece's volume is a volume and not a guess.
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

    new_vertices: list[np.ndarray] = []
    new_faces: list[tuple[int, int, int]] = []
    cut_points: list[np.ndarray] = []
    # A hash of the rounded coordinates, so a point that has been seen is
    # found in constant time.
    index_of: dict[tuple[int, int, int], int] = {}

    def _index(point: np.ndarray) -> int:
        key = (
            int(round(float(point[0]) * 1e7)),
            int(round(float(point[1]) * 1e7)),
            int(round(float(point[2]) * 1e7)),
        )
        found = index_of.get(key)
        if found is not None:
            return found
        index_of[key] = len(new_vertices)
        new_vertices.append(point)
        return len(new_vertices) - 1

    for face in piece.faces:
        polygon = []
        for corner in face:
            point = vertices[corner]
            polygon.append((point, signed[corner]))
        clipped: list[np.ndarray] = []
        count = len(polygon)
        for i in range(count):
            point, s = polygon[i]
            nxt_point, nxt_s = polygon[(i + 1) % count]
            if s <= 0.0:
                clipped.append(point)
            if (s < 0.0 < nxt_s) or (nxt_s < 0.0 < s):
                t = s / (s - nxt_s)
                crossing = point + t * (nxt_point - point)
                clipped.append(crossing)
                cut_points.append(crossing)
        if len(clipped) < 3:
            continue
        ids = [_index(p) for p in clipped]
        for i in range(1, len(ids) - 1):
            tri = (ids[0], ids[i], ids[i + 1])
            if len(set(tri)) == 3:
                new_faces.append(tri)

    if not new_faces:
        return Collider(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), 0.0, np.zeros((0, 4)))

    verts = np.asarray(new_vertices, dtype=np.float64)
    faces = np.asarray(new_faces, dtype=np.int64)

    # Cap the cut: the cross-section of a convex body by a plane is a
    # convex polygon, so a fan around its centroid closes the piece.
    if cut_points:
        ring = _dedupe(np.asarray(cut_points, dtype=np.float64))
        if ring.shape[0] >= 3:
            centre = ring.mean(axis=0)
            # An orthonormal basis for the cut plane.
            helper = np.array([1.0, 0.0, 0.0])
            if abs(float(normal @ helper)) > 0.9:
                helper = np.array([0.0, 1.0, 0.0])
            u = np.cross(normal, helper)
            u /= max(float(np.linalg.norm(u)), 1e-12)
            w = np.cross(normal, u)
            angles = np.arctan2((ring - centre) @ w, (ring - centre) @ u)
            order = np.argsort(angles)
            ring = ring[order]
            centre_id = _index(centre)
            for i in range(ring.shape[0]):
                a = _index(ring[i])
                b = _index(ring[(i + 1) % ring.shape[0]])
                if len({centre_id, a, b}) == 3:
                    new_faces.append((centre_id, a, b))
        faces = np.asarray(new_faces, dtype=np.int64)
        verts = np.asarray(new_vertices, dtype=np.float64)

    # Drop the vertices no face uses, and renumber.
    used = np.unique(faces)
    remap = np.full(verts.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(used.shape[0], dtype=np.int64)
    verts = verts[used]
    faces = remap[faces]

    volume = _closed_volume(verts, faces)
    hull = convex_hull(verts)
    planes = hull.planes if not hull.is_empty else np.zeros((0, 4))
    return Collider(vertices=verts, faces=faces, volume=volume, planes=planes)


def _closed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """The volume of a closed triangle mesh, by the divergence theorem.

    The reference point is the mean of the vertices, so the formula
    measures the enclosed volume rather than the volume of the
    tetrahedra a corner-anchored origin would make.
    """
    if faces.shape[0] == 0 or vertices.shape[0] == 0:
        return 0.0
    reference = vertices.mean(axis=0)
    v0 = vertices[faces[:, 0]] - reference
    v1 = vertices[faces[:, 1]] - reference
    v2 = vertices[faces[:, 2]] - reference
    return float(abs(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum()) / 6.0)


def _cut_by_plane(part: MeshPart, normal: np.ndarray, offset: float) -> tuple[MeshPart, MeshPart]:
    """Cut a part into the part below a plane and the part above it."""
    normal = np.asarray(normal, dtype=np.float64)
    norm = float(np.linalg.norm(normal))
    normal = normal / norm
    offset = float(offset) / norm
    signed = part.vertices @ normal + offset
    centroids = part.vertices[part.triangles].mean(axis=1)
    centre_signed = centroids @ normal + offset
    below = centre_signed <= 0.0
    return part.subset(below), part.subset(~below)


def _subsample(points: np.ndarray, limit: int = 2000) -> np.ndarray:
    """A spread-out subset of the points, for the cheap evaluations.

    The stride keeps the subset spread over the shape rather than taking a
    corner of it, and it is deterministic: the same piece always gives the
    same subset.
    """
    if points.shape[0] <= limit:
        return points
    stride = max(1, points.shape[0] // limit)
    return points[::stride]


def _deviation(vertices: np.ndarray, planes: np.ndarray) -> tuple[float, np.ndarray]:
    """How far the vertices are from the hull's surface, and the distances."""
    if planes.shape[0] == 0 or vertices.shape[0] == 0:
        return 0.0, np.zeros(0)
    dist = distance_to_hull(vertices, planes)
    return float(dist.max()), dist


def _candidate_cuts(
    sample: np.ndarray,
    hull: ConvexPiece,
    distances: np.ndarray,
    tol_m: float,
    max_face_candidates: int = 10,
) -> list[tuple[np.ndarray, float]]:
    """The planes worth trying to cut this piece on.

    Two kinds of candidate, and both are needed. A hull face that floats
    above the material is a hollow: cutting on it, down at the material's
    own level, takes the hollow out. An axis-aligned plane through the
    vertices that are deepest inside the hull is a notch: cutting across
    it separates the walls of the notch from each other, which is the only
    way a ring of material becomes two convex bars instead of one fat box.
    """
    cuts: list[tuple[np.ndarray, float]] = []
    vertices = sample

    # The hull of a sampled part has thousands of faces, and every one of
    # them is a candidate cut. Only the ones that float highest above the
    # material are worth trying: they are where the part is hollow.
    floating: list[tuple[float, np.ndarray, float]] = []
    for plane in hull.planes:
        normal = plane[:3]
        offset = plane[3]
        signed = vertices @ normal + offset
        gap = float(-signed.max()) if signed.size else 0.0
        if gap > tol_m:
            floating.append((gap, normal.copy(), offset))
    floating.sort(key=lambda item: -item[0])
    for gap, normal, offset in floating[:max_face_candidates]:
        # Cut at the material's level, a little above its deepest vertex,
        # so the plane passes through the material.
        cuts.append((normal, offset + gap - 0.5 * tol_m))

    if distances.size:
        deep = distances >= max(tol_m, float(np.percentile(distances, 75)))
        if deep.any():
            for axis in range(3):
                values = vertices[deep, axis]
                if values.size == 0:
                    continue
                for position in (float(np.median(values)), float(values.mean())):
                    normal = np.zeros(3)
                    normal[axis] = 1.0
                    cuts.append((normal.copy(), -position))
                    cuts.append((-normal.copy(), position))
    return cuts


def _clipped(
    hull: ConvexPiece,
    clips: list[tuple[np.ndarray, float]],
) -> Collider:
    """A hull, clipped to every half-space it was cut on.

    Two pieces of the same part must not share space: a hull bulges over
    the plane it was cut on, and the bulge of the lower piece would sit
    inside the upper one. A piece carries the cuts of every step on the
    way down, so it is inside its own half-space of each of them and the
    pieces are a partition of the part rather than a pile of overlapping
    hulls.
    """
    if not clips:
        return Collider(
            vertices=hull.vertices,
            faces=hull.faces,
            volume=hull.volume,
            planes=hull.planes,
        )
    clipped = hull
    for normal, offset in clips:
        clipped = clip_convex(clipped, normal, offset)
    if clipped.is_empty:
        return Collider(
            vertices=np.zeros((0, 3)),
            faces=np.zeros((0, 3), dtype=np.int64),
            volume=0.0,
            planes=np.zeros((0, 4)),
        )
    return clipped


def decompose_part(
    part: MeshPart,
    part_name: str,
    tol_m: float,
    max_pieces: int = 32,
    max_depth: int = 8,
    hull_point_limit: int = 2500,
    deviation_point_limit: int = 5000,
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

    def _score(
        vertices: np.ndarray,
        clips: list[tuple[np.ndarray, float]] | None = None,
    ) -> tuple[ConvexPiece, float, float, np.ndarray, np.ndarray]:
        # The hull and the measurement both work on a subset: the distance
        # from every vertex to every hull face is a product of the two
        # sizes, and a generated mesh has hundreds of thousands of
        # vertices.
        sample = _subsample(vertices, max(hull_point_limit, deviation_point_limit))
        hull = convex_hull(_subsample(sample, hull_point_limit))
        if hull.is_empty:
            return hull, float("inf"), float("inf"), np.zeros(0), np.zeros(0)
        # The vertices the cut created sit on the cut plane, inside the
        # piece, and they are not the material's surface. They would
        # measure as a hollow that is not there.
        keep = np.ones(sample.shape[0], dtype=bool)
        for normal, offset in clips or []:
            on_plane = np.abs(sample @ normal + offset) <= 1e-4
            keep &= ~on_plane
        surface = sample[keep] if keep.any() else sample
        outside, depth = hull_metrics(surface, hull.planes)
        concavity = float(depth.max()) if depth.size else 0.0
        deviation = float(outside.max()) if outside.size else 0.0
        return hull, concavity, deviation, surface, depth

    def _recurse(
        piece: MeshPart,
        depth: int,
        clips: list[tuple[np.ndarray, float]] | None = None,
    ) -> None:
        clips = list(clips or [])
        if piece.is_empty:
            return
        if len(pieces) >= max_pieces or depth >= max_depth:
            hull = convex_hull(_subsample(piece.vertices, hull_point_limit))
            if not hull.is_empty:
                pieces.append(_clipped(hull, clips))
                if depth >= max_depth:
                    notes.append(
                        f"a piece reached the depth limit ({max_depth}) and was "
                        "left as one hull"
                    )
            return

        hull, concavity, deviation, sample, distances = _score(piece.vertices, clips)
        if hull.is_empty:
            return
        if concavity <= tol_m:
            # The hull does not swallow a hollow deeper than the
            # tolerance, so it stands in for the material.
            pieces.append(_clipped(hull, clips))
            return

        best: tuple[float, np.ndarray, float] | None = None
        for normal, offset in _candidate_cuts(sample, hull, distances, tol_m):
            below, above = _cut_by_plane(piece, normal, offset)
            if below.is_empty or above.is_empty:
                continue
            _, conc_below, _, _, _ = _score(below.vertices, clips + [(normal, offset)])
            _, conc_above, _, _, _ = _score(above.vertices, clips + [(-normal, -offset)])
            worst = max(conc_below, conc_above)
            if best is None or worst < best[0]:
                best = (worst, normal, offset)

        if best is None or best[0] >= concavity:
            # No cut improves on the hull; keeping the hull is the honest
            # answer, and it is recorded.
            pieces.append(_clipped(hull, clips))
            notes.append(
                f"a concave piece ({concavity * 1000:.1f} mm deep in its hull) "
                "could not be cut further and was left as one hull"
            )
            return

        _, normal, offset = best
        below, above = _cut_by_plane(piece, normal, offset)
        _recurse(below, depth + 1, clips=clips + [(normal, offset)])
        _recurse(above, depth + 1, clips=clips + [(-normal, -offset)])

    _recurse(part, 0)

    if not pieces:
        raise DecompositionError(f"part {part_name!r}: no convex piece could be made")

    # Measure the result against the part: every vertex of the material,
    # sampled, against the pieces that stand in for it. A vertex the
    # collider covers is covered; a vertex it misses is as far out as it
    # is from the nearest piece.
    material = _subsample(part.vertices, deviation_point_limit)
    planes = [piece.planes for piece in pieces if piece.planes.shape[0] > 0]
    if planes:
        distances = distance_to_union(material, planes)
        deviation = float(distances.max()) if distances.size else 0.0
        p95 = float(np.percentile(distances, 95)) if distances.size else 0.0
    else:
        deviation = 0.0
        p95 = 0.0

    collider_volume = float(sum(p.volume for p in pieces))
    overlaps = _pieces_overlap(pieces)
    hollow = _hollow_depth(pieces, part, tol_m)

    return Decomposition(
        part_name=part_name,
        colliders=tuple(pieces),
        hull_volume=float(whole_hull.volume),
        collider_volume=collider_volume,
        deviation_m=deviation,
        deviation_p95_m=p95,
        concavity_m=hollow,
        overlaps=overlaps,
        notes=tuple(notes),
    )


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

    The material is measured against its **vertices**, through a tree. For
    a generated prop the vertices are millimetres apart, so the distance to
    the nearest vertex is the distance to the surface to within a
    millimetre, which is finer than the tolerance the guard uses.
    """
    if not pieces or material.is_empty:
        return 0.0
    from scipy.spatial import cKDTree

    vertices = material.vertices
    if vertices.shape[0] > 60000:
        stride = max(1, vertices.shape[0] // 60000)
        vertices = vertices[::stride]
    tree = cKDTree(vertices)

    deepest = 0.0
    for piece in pieces:
        if piece.is_empty or piece.volume <= 0.0:
            continue
        points = _sample_piece(piece, samples_per_piece)
        if points.shape[0] == 0:
            continue
        distances, _ = tree.query(points)
        deepest = max(deepest, float(np.max(distances)))
    return deepest


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
