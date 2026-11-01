"""The geometry the builder works on: meshes, cuts, hulls, and the metrics.

Everything here is deterministic and needs no GPU, which is the point: the
builder and the checker can be tested on a laptop.

The mesh itself is read with the Prop-maker's own GLB reader
(:mod:`core.genbatch.glb`), so this seat does not carry a second glTF
parser. TRELLIS.2 writes one mesh per file, which is the one we measure.

Two measurements deserve their own words, because the stability score is
made of them.

**A cut leaves a hole.** Cutting a closed mesh with a plane opens it: the
part is no longer a closed solid, so its signed volume (the divergence
theorem) is no longer a volume. The volume that matters for the collider is
the *hull's* volume, and the fidelity of the collider is the ratio of the
hulls' volume to the mesh's volume — that ratio is what says whether the
collider is fat, thin, or true.

**A hull is inscribed.** The convex hull of a part's vertices contains the
part, so a hull is never thinner than the thing it wraps; it is fatter only
where the part was concave. That is the inflation the Hy4 guard measures:
the collider must not be more than 1 % fatter than the mesh it stands in
for, or "nothing penetrated past epsilon" is a statement about a shape
nobody has.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import ConvexHull

from core.genbatch.glb import GlbError, read_glb

__all__ = [
    "ConvexPiece",
    "GeometryError",
    "MeshPart",
    "convex_hull",
    "hull_volume",
    "largest_component",
    "load_mesh",
    "signed_volume",
    "surface_area",
]

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


class GeometryError(ValueError):
    """A mesh we cannot work with."""


@dataclass(frozen=True)
class MeshPart:
    """A piece of a mesh: vertices and triangles, nothing else.

    ``vertices`` is ``(n, 3)`` float64 and ``triangles`` is ``(m, 3)``
    int64. The triangles index into the vertices.
    """

    vertices: np.ndarray
    triangles: np.ndarray

    @property
    def is_empty(self) -> bool:
        return self.vertices.shape[0] == 0 or self.triangles.shape[0] == 0

    @property
    def triangle_count(self) -> int:
        """How many triangles the piece has."""
        return int(self.triangles.shape[0])

    @property
    def vertex_count(self) -> int:
        """How many vertices the piece has."""
        return int(self.vertices.shape[0])

    @property
    def bbox_min(self) -> np.ndarray:
        if self.is_empty:
            return np.zeros(3)
        return self.vertices.min(axis=0)

    @property
    def bbox_max(self) -> np.ndarray:
        if self.is_empty:
            return np.zeros(3)
        return self.vertices.max(axis=0)

    @property
    def bbox_size(self) -> np.ndarray:
        return self.bbox_max - self.bbox_min

    @property
    def centroid(self) -> np.ndarray:
        if self.is_empty:
            return np.zeros(3)
        return self.vertices.mean(axis=0)

    def subset(self, keep: np.ndarray) -> "MeshPart":
        """The part made of the triangles in ``keep`` (a boolean mask).

        The vertices are renumbered, so the result shares nothing with the
        mesh it came from except its shape.
        """
        if self.is_empty:
            return self
        tris = self.triangles[keep]
        if tris.shape[0] == 0:
            return MeshPart(vertices=np.zeros((0, 3)), triangles=np.zeros((0, 3), dtype=np.int64))
        used = np.unique(tris)
        remap = np.full(self.vertices.shape[0], -1, dtype=np.int64)
        remap[used] = np.arange(used.shape[0], dtype=np.int64)
        return MeshPart(vertices=self.vertices[used], triangles=remap[tris])

    def translated(self, offset: np.ndarray) -> "MeshPart":
        """The same shape, moved."""
        return MeshPart(vertices=self.vertices + offset, triangles=self.triangles)

    def triangle_centroids(self) -> np.ndarray:
        """The centroid of every triangle: ``(m, 3)``."""
        if self.is_empty:
            return np.zeros((0, 3))
        return self.vertices[self.triangles].mean(axis=1)

    def triangle_areas(self) -> np.ndarray:
        """The area of every triangle: ``(m,)``."""
        if self.is_empty:
            return np.zeros(0)
        v0 = self.vertices[self.triangles[:, 0]]
        v1 = self.vertices[self.triangles[:, 1]]
        v2 = self.vertices[self.triangles[:, 2]]
        return 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)


@dataclass(frozen=True)
class ConvexPiece:
    """One convex piece of a decomposition, ready to be a MuJoCo mesh.

    ``vertices`` are the hull's points and ``faces`` the triangles of the
    hull's surface, wound outwards.
    """

    vertices: np.ndarray
    faces: np.ndarray
    volume: float
    #: The hull's half-spaces as ``(n, 4)`` rows of ``[normal, offset]``,
    #: with ``normal . x + offset <= 0`` inside. Used to measure how far a
    #: point is from the hull's surface.
    planes: np.ndarray

    @property
    def is_empty(self) -> bool:
        return self.vertices.shape[0] == 0


def load_mesh(path: str | Path) -> MeshPart:
    """Read a GLB into a :class:`MeshPart`.

    The mesh is moved so that its bounding box's minimum corner is the
    origin, and so that ``z`` is up: the prop frame the specs are written
    in. Doing it here means no other module has to know how a generated
    mesh arrives.
    """
    path = Path(path)
    try:
        glb = read_glb(path)
        mesh = glb.mesh
    except GlbError as exc:
        raise GeometryError(str(exc)) from exc

    vertices = np.asarray(mesh.positions, dtype=np.float64)
    triangles = np.asarray(mesh.indices, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise GeometryError(f"{path}: the vertex array is {vertices.shape}, not (n, 3)")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise GeometryError(f"{path}: the index array is {triangles.shape}, not (m, 3)")

    vertices = _orient(vertices)
    vertices = vertices - vertices.min(axis=0)
    return MeshPart(vertices=vertices, triangles=triangles)


def _orient(vertices: np.ndarray) -> np.ndarray:
    """Put the mesh's standing axis upright.

    A generated prop arrives in whatever orientation the generator chose. A
    crate lying on its side and a crate standing are the same prop; the
    specs, the joints and the "stays upright" check all assume the prop
    stands. The rule is the mesh's own shape: the shortest bbox axis is the
    one that is standing up, because a prop is longer or wider than it is
    tall.

    The swap keeps the frame right-handed — a mirror would flip every
    triangle's winding, and the signed volume with it.
    """
    size = vertices.max(axis=0) - vertices.min(axis=0)
    if size[1] < size[0] and size[1] < size[2]:
        # y is the shortest, so y is up: x stays x, z becomes the new -y.
        return vertices[:, [0, 2, 1]] * np.array([1.0, -1.0, 1.0])
    return vertices


def signed_volume(vertices: np.ndarray, triangles: np.ndarray) -> float:
    """The volume of a closed mesh, by the divergence theorem.

    The formula — the sum of the signed tetrahedra from a reference point
    to every triangle — is only the enclosed volume when the reference
    point is *inside* the mesh. A mesh whose corner sits at the origin
    (which is where the builder puts every mesh) has the origin on its
    boundary at best, and a clipped piece can have it well outside, where
    the formula measures something else entirely. So the reference point
    is the mean of the vertices, which is inside any convex shape and
    close enough to the middle for anything else.
    """
    if triangles.shape[0] == 0 or vertices.shape[0] == 0:
        return 0.0
    reference = vertices.mean(axis=0)
    v0 = vertices[triangles[:, 0]] - reference
    v1 = vertices[triangles[:, 1]] - reference
    v2 = vertices[triangles[:, 2]] - reference
    return float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)


def surface_area(part: MeshPart) -> float:
    """The total area of a mesh's triangles."""
    if part.is_empty:
        return 0.0
    return float(part.triangle_areas().sum())


def triangle_components(part: MeshPart) -> tuple[np.ndarray, int]:
    """Label each triangle by the connected component it belongs to.

    Two triangles are in the same component when they share a vertex. The
    labelling is what makes the segmentation check honest: a part that
    comes back in three pieces has not been segmented, it has been cut in
    the wrong place.
    """
    if part.is_empty:
        return np.zeros(0, dtype=np.int64), 0
    edges = np.concatenate(
        [part.triangles[:, [0, 1]], part.triangles[:, [1, 2]], part.triangles[:, [2, 0]]],
        axis=0,
    )
    n = part.vertices.shape[0]
    graph = coo_matrix(
        (np.ones(edges.shape[0], dtype=np.int8), (edges[:, 0], edges[:, 1])),
        shape=(n, n),
    )
    _, labels = connected_components(graph, directed=False)
    tri_labels = labels[part.triangles[:, 0]]
    _, tri_labels = np.unique(tri_labels, return_inverse=True)
    return tri_labels.astype(np.int64), int(tri_labels.max()) + 1


def largest_component(part: MeshPart) -> tuple[MeshPart, int, list[float]]:
    """The biggest connected component of a part, and how the rest shared out.

    Returns the component, the number of components, and each component's
    share of the area. A part cut in one piece has one component and a
    single share of 1.0; a part cut in two has two, and the smaller one is
    the ambiguity the guard is about.
    """
    if part.is_empty:
        return part, 0, []
    labels, count = triangle_components(part)
    areas = part.triangle_areas()
    totals = np.zeros(count)
    np.add.at(totals, labels, areas)
    grand = float(totals.sum())
    shares = sorted((float(t) / grand for t in totals if grand > 0.0), reverse=True)
    biggest = int(np.argmax(totals))
    keep = labels == biggest
    return part.subset(keep), count, shares


def convex_hull(points: np.ndarray) -> ConvexPiece:
    """The convex hull of a point set, as a piece ready for MuJoCo."""
    if points.shape[0] < 4:
        return ConvexPiece(
            vertices=np.zeros((0, 3)),
            faces=np.zeros((0, 3), dtype=np.int64),
            volume=0.0,
            planes=np.zeros((0, 4)),
        )
    try:
        hull = ConvexHull(points)
    except Exception as exc:  # pragma: no cover - qhull's own error text
        raise GeometryError(f"the convex hull failed: {exc}") from exc
    # scipy's simplices index the points that were handed in, not the
    # hull's own vertex list, so the indices have to be remapped before
    # the two can be used together.
    remap = np.full(points.shape[0], -1, dtype=np.int64)
    remap[hull.vertices] = np.arange(hull.vertices.shape[0], dtype=np.int64)
    vertices = points[hull.vertices]
    faces = remap[hull.simplices].astype(np.int64)

    # scipy's hull triangles are wound *inwards* — half of them point at
    # the inside and half away, so a mesh built from them has no
    # consistent orientation, and a volume computed from it is nonsense.
    # Every face is checked against the hull's own centre and flipped
    # when it faces the wrong way.
    centre = vertices.mean(axis=0)
    fixed: list[list[int]] = []
    for tri in faces:
        a, b, c = vertices[tri]
        normal = np.cross(b - a, c - a)
        face_centre = (a + b + c) / 3.0
        if float(normal @ (face_centre - centre)) < 0.0:
            fixed.append([int(tri[0]), int(tri[2]), int(tri[1])])
        else:
            fixed.append([int(tri[0]), int(tri[1]), int(tri[2])])
    faces = np.asarray(fixed, dtype=np.int64)

    planes = np.asarray(hull.equations, dtype=np.float64)
    return ConvexPiece(
        vertices=vertices,
        faces=faces,
        volume=float(hull.volume),
        planes=planes,
    )


def hull_volume(points: np.ndarray) -> float:
    """The volume of the convex hull of a point set (0.0 if degenerate)."""
    return convex_hull(points).volume


def distance_to_hull(points: np.ndarray, planes: np.ndarray) -> np.ndarray:
    """The signed distance from points to a convex hull's boundary.

    Negative inside, positive outside, and the magnitude is the distance
    to the nearest face — which is what "how far is this vertex from the
    collider" means.
    """
    if planes.shape[0] == 0 or points.shape[0] == 0:
        return np.full(points.shape[0], np.inf)
    normals = planes[:, :3]
    offsets = planes[:, 3]
    gaps = points @ normals.T + offsets  # (n_points, n_planes); <= 0 inside
    # Inside a hull, the distance to the surface is the *smallest* gap, not
    # the largest; outside it is the largest violation. Taking the absolute
    # value of the largest gap gives both.
    return np.abs(gaps.max(axis=1))


def clip_mesh_at_plane(part: MeshPart, normal: np.ndarray, offset: float) -> MeshPart:
    """The part of a mesh on one side of a plane.

    The triangles that straddle the plane are cut, not assigned: the part
    that crosses the cut is flattened onto the plane, so the two sides of
    the cut share a surface exactly and the pieces tile the mesh instead
    of overlapping it. A cut that assigns whole triangles by their
    centroids leaves the material near the plane in the wrong piece, and
    the clearance the builder opens at the cut then has nothing to open.
    """
    if part.is_empty:
        return part
    normal = np.asarray(normal, dtype=np.float64)
    norm = float(np.linalg.norm(normal))
    if norm < 1e-12:
        raise GeometryError("the clipping plane has no normal")
    normal = normal / norm
    offset = float(offset) / norm

    vertices = part.vertices
    signed = vertices @ normal + offset

    new_vertices: list[np.ndarray] = []
    new_faces: list[tuple[int, int, int]] = []
    # A hash of the rounded coordinates, so a point that has been seen is
    # found in constant time: a linear scan makes this quadratic, and a
    # generated mesh has hundreds of thousands of vertices.
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

    for tri in part.triangles:
        polygon = [(vertices[c], signed[c]) for c in tri]
        clipped: list[np.ndarray] = []
        count = len(polygon)
        for i in range(count):
            point, s = polygon[i]
            nxt_point, nxt_s = polygon[(i + 1) % count]
            if s <= 0.0:
                clipped.append(point)
            if (s < 0.0 < nxt_s) or (nxt_s < 0.0 < s):
                t = s / (s - nxt_s)
                clipped.append(point + t * (nxt_point - point))
        if len(clipped) < 3:
            continue
        ids = [_index(p) for p in clipped]
        for i in range(1, len(ids) - 1):
            tri_ids = (ids[0], ids[i], ids[i + 1])
            if len(set(tri_ids)) == 3:
                new_faces.append(tri_ids)

    if not new_faces:
        return MeshPart(vertices=np.zeros((0, 3)), triangles=np.zeros((0, 3), dtype=np.int64))
    out_vertices = np.asarray(new_vertices, dtype=np.float64)
    out_faces = np.asarray(new_faces, dtype=np.int64)
    used = np.unique(out_faces)
    remap = np.full(out_vertices.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(used.shape[0], dtype=np.int64)
    return MeshPart(vertices=out_vertices[used], triangles=remap[out_faces])


def hull_metrics(points: np.ndarray, planes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """How a set of points sits against one convex hull: outside and inside.

    The first array is the distance from each point to the hull's surface
    for the points that are **outside** it — the material the collider
    misses. The second is the depth for the points that are **inside**
    it — how deep the hull swallows the material it covers, which is the
    hollow a single hull fills in.
    """
    if planes.shape[0] == 0 or points.shape[0] == 0:
        return np.zeros(points.shape[0]), np.zeros(points.shape[0])
    normals = planes[:, :3]
    offsets = planes[:, 3]
    gaps = points @ normals.T + offsets
    worst = gaps.max(axis=1)
    inside = worst <= 0.0
    outside = np.where(inside, 0.0, worst)
    # The nearest face is the one whose gap is closest to zero, which is
    # the largest gap: every other face is further away.
    depth = np.where(inside, -worst, 0.0)
    return outside, depth


def distance_to_union(points: np.ndarray, pieces: list[np.ndarray]) -> np.ndarray:
    """How far each point is from the *outside* of a union of convex pieces.

    A point that is inside one of the pieces is covered: its distance is
    zero, because the collider stands over the material there. A point
    that is outside every piece is as far from the union as it is from
    the nearest piece's surface. The second number is the one that says
    whether the collider misses material.

    The depth of the covered points is the other half of the story: how
    deep the collider swallows the material it covers. That is the local
    face of the inflation the volume ratio measures globally.
    """
    if points.shape[0] == 0:
        return np.zeros(0)
    if not pieces:
        return np.full(points.shape[0], np.inf)

    covered = np.zeros(points.shape[0], dtype=bool)
    depth = np.zeros(points.shape[0])
    outside = np.full(points.shape[0], np.inf)

    for planes in pieces:
        if planes.shape[0] == 0:
            continue
        normals = planes[:, :3]
        offsets = planes[:, 3]
        gaps = points @ normals.T + offsets
        worst = gaps.max(axis=1)
        inside = worst <= 0.0
        covered |= inside
        # How far inside: the distance to the nearest face.
        depth = np.where(inside, np.maximum(depth, -gaps.min(axis=1)), depth)
        outside = np.minimum(outside, np.where(inside, np.inf, worst))

    return np.where(covered, 0.0, outside)


def bbox_iou(a_min: np.ndarray, a_max: np.ndarray, b_min: np.ndarray, b_max: np.ndarray) -> float:
    """The intersection over union of two axis-aligned boxes."""
    lo = np.maximum(a_min, b_min)
    hi = np.minimum(a_max, b_max)
    inter = np.prod(np.maximum(hi - lo, 0.0))
    va = np.prod(np.maximum(a_max - a_min, 0.0))
    vb = np.prod(np.maximum(b_max - b_min, 0.0))
    union = va + vb - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def axis_index(axis: str) -> int:
    """The index of an axis name."""
    try:
        return _AXIS_INDEX[axis]
    except KeyError as exc:
        raise GeometryError(f"unknown axis {axis!r}") from exc
