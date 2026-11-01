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
    "apply_transform",
    "mesh_components",
    "convex_hull",
    "distance_to_surface",
    "hull_volume",
    "is_closed",
    "largest_component",
    "load_mesh",
    "prop_frame_transform",
    "scale_mesh",
    "signed_volume",
    "subsample_points",
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


def prop_frame_transform(vertices: np.ndarray) -> np.ndarray:
    """The transform from a mesh's own frame into the prop frame.

    :func:`load_mesh` applies it: the standing axis is put up, and the
    bounding box's minimum corner becomes the origin. The CAD arm needs the
    same transform for the *parts*, which come from the kernel that built
    the prop rather than from the merged mesh — and the parts have to end up
    in the same frame as the mesh, or the collider stands somewhere the
    material is not.

    The transform is decided by the **merged** mesh's own shape, so it has
    to be computed from it and then applied to each part.
    """
    size = vertices.max(axis=0) - vertices.min(axis=0)
    if size[1] < size[0] and size[1] < size[2]:
        # y is the shortest, so y is up: x stays x, z becomes the new -y.
        rotation = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    else:
        rotation = np.eye(3)
    oriented = vertices @ rotation.T
    shift = oriented.min(axis=0)
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = -shift
    return matrix


def apply_transform(matrix: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    """Apply a 4x4 transform to a set of points."""
    points = np.asarray(vertices, dtype=np.float64)
    if points.size == 0:
        return points.reshape(0, 3)
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def is_closed(mesh: MeshPart) -> bool:
    """Whether the mesh's surface is closed: every edge shared by two faces.

    It matters because a closed surface has a **volume** — the divergence
    theorem gives the space it encloses — and an open one does not. A
    generated prop is a shell with holes in it, and the "volume" the
    divergence theorem gives for it is the difference of two large numbers,
    which is a number and not a volume. The guards that compare the
    collider's volume with the mesh's need to know which of the two they
    have.
    """
    triangles = mesh.triangles
    if triangles.shape[0] == 0:
        return False
    edges = np.concatenate(
        [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]], axis=0
    )
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def scale_mesh(mesh: MeshPart, size_m: float | None) -> MeshPart:
    """Scale a mesh so that its largest dimension is ``size_m`` metres.

    A generated prop arrives in the generator's own units — TRELLIS.2 puts
    its output in a unit cube, so a crate comes out a metre across. That
    is a scale, not a shape, and the physics is a statement about metres:
    a metre-wide crate falls differently from a forty-centimetre one, and
    the actuator's force limit is in newtons. The prop's real size is a
    prior, an estimate, and it is recorded as one.

    The mesh's own corner stays at the origin, so the prop frame the specs
    are written in does not move.
    """
    if size_m is None or size_m <= 0.0 or mesh.is_empty:
        return mesh
    largest = float(mesh.bbox_size.max())
    if largest <= 0.0:
        return mesh
    scale = float(size_m) / largest
    if abs(scale - 1.0) < 1e-9:
        return mesh
    return MeshPart(vertices=mesh.vertices * scale, triangles=mesh.triangles)


def subsample_points(points: np.ndarray, limit: int = 2000) -> np.ndarray:
    """A spread-out subset of the points, for the cheap evaluations.

    The stride keeps the subset spread over the shape rather than taking a
    corner of it, and it is deterministic: the same mesh always gives the
    same subset. A measurement taken over the subset is an estimate of
    the same measurement over everything, and where the estimate is used
    for a bound the record says it was a sample.
    """
    if points.shape[0] <= limit:
        return points
    stride = max(1, points.shape[0] // limit)
    return points[::stride]


class SurfaceDistance:
    """The distance from points to a mesh's surface.

    The trees are built once and reused: the decomposition asks the same
    question hundreds of times, and rebuilding the trees each time is the
    difference between a minute and an hour.

    The distance to the nearest *vertex* is not the distance to the
    surface: the middle of a large flat panel is far from the panel's
    corners and a few millimetres from the panel itself. So the nearest
    triangles are found through the trees and the exact point-to-triangle
    distance is computed for those.

    Two trees are used, because one is not enough. The tree over the
    triangles' **centres** finds the triangle whose middle is near, and the
    tree over the **vertices** finds the triangle whose corner is near. A
    big triangle can be right next to the point and have its centre far
    away — the centre of a long plank is half a plank away from its end —
    and a search over centres alone would then miss it and report the
    distance to the plank's *other* side instead. Both searches are made,
    and the smaller of the two distances is the answer.
    """

    #: How many vertices to look at when a point is close to a corner.
    vertex_neighbours = 4
    #: The most triangles one vertex may be part of. A vertex of a closed
    #: mesh has six; a vertex where the mesh was cut may have more.
    max_incident = 8

    def __init__(self, mesh: MeshPart, neighbours: int = 8) -> None:
        from scipy.spatial import cKDTree

        self.neighbours = int(neighbours)
        self.vertices = mesh.vertices
        self.triangles = mesh.triangles
        self.empty = mesh.triangles.shape[0] == 0
        if self.empty:
            self.tree = None
            self.vertex_tree = None
            self.centres = np.zeros((0, 3))
            self.vertex_triangles = np.zeros((0, self.max_incident), dtype=np.int64)
            return
        a = self.vertices[self.triangles[:, 0]]
        b = self.vertices[self.triangles[:, 1]]
        c = self.vertices[self.triangles[:, 2]]
        self.centres = (a + b + c) / 3.0
        self.tree = cKDTree(self.centres)
        self.vertex_tree = cKDTree(self.vertices)

        # The triangles' outward normals, and whether the mesh is a closed
        # solid. A closed mesh knows which side of its surface is inside,
        # and the distance to it can be signed: a point inside the material
        # is *inside* it, and a point in the air is outside. That is the
        # difference between a collider's face that lies within the
        # material and one that lies across a hollow, and the two look the
        # same to an unsigned distance.
        raw = np.cross(b - a, c - a)
        lengths = np.linalg.norm(raw, axis=1)
        lengths[lengths == 0.0] = 1.0
        self.normals = raw / lengths[:, None]
        self.closed = is_closed(mesh)
        if self.closed:
            volume = signed_volume(self.vertices, self.triangles)
            if volume < 0.0:
                # The mesh is wound the other way round: turn the normals
                # so that they point out of the material.
                self.normals = -self.normals

        # The triangles each vertex is part of, padded to a fixed width so
        # that the candidates can be gathered in one array. The pairs are
        # generated in triangle order and sorted by vertex with a stable
        # sort, so each vertex's triangles arrive in the same order the
        # per-triangle walk would have given, and the padding keeps the
        # first ``width`` of them.
        counts = np.zeros(self.vertices.shape[0], dtype=np.int64)
        np.add.at(counts, self.triangles.ravel(), 1)
        width = max(int(counts.max()) if counts.size else 0, 1)
        pair_vertex = self.triangles.ravel()
        pair_triangle = np.repeat(
            np.arange(self.triangles.shape[0], dtype=np.int64), 3
        )
        order = np.argsort(pair_vertex, kind="stable")
        sorted_vertex = pair_vertex[order]
        sorted_triangle = pair_triangle[order]
        starts = np.zeros(self.vertices.shape[0] + 1, dtype=np.int64)
        np.cumsum(counts, out=starts[1:])
        within = np.arange(sorted_vertex.shape[0], dtype=np.int64) - starts[sorted_vertex]
        keep = within < width
        self.vertex_triangles = np.full(
            (self.vertices.shape[0], width), -1, dtype=np.int64
        )
        self.vertex_triangles[sorted_vertex[keep], within[keep]] = sorted_triangle[keep]


    def __call__(self, points: np.ndarray) -> np.ndarray:
        """How far each point is from the surface."""
        points = np.asarray(points, dtype=np.float64)
        if points.shape[0] == 0:
            return np.zeros(0)
        if self.empty or self.tree is None:
            return np.full(points.shape[0], np.inf)

        k = min(self.neighbours, self.centres.shape[0])
        _distances, centres = self.tree.query(points, k=k)
        if k == 1:
            centres = centres.reshape(-1, 1)

        # The triangles around the nearest vertices: the ones a search over
        # centres can miss.
        kv = min(self.vertex_neighbours, self.vertices.shape[0])
        _vd, vertex_ids = self.vertex_tree.query(points, k=kv)
        if kv == 1:
            vertex_ids = vertex_ids.reshape(-1, 1)
        near = self.vertex_triangles[vertex_ids].reshape(points.shape[0], -1)

        candidates = np.concatenate([centres, near], axis=1)
        valid = candidates >= 0
        safe = np.where(valid, candidates, 0)

        a = self.vertices[self.triangles[:, 0]][safe]
        b = self.vertices[self.triangles[:, 1]][safe]
        c = self.vertices[self.triangles[:, 2]][safe]

        p = points[:, None, :]
        ab = b - a
        ac = c - a
        ap = p - a

        d1 = np.einsum("pkc,pkc->pk", ab, ap)
        d2 = np.einsum("pkc,pkc->pk", ac, ap)
        bp = p - b
        d3 = np.einsum("pkc,pkc->pk", ab, bp)
        d4 = np.einsum("pkc,pkc->pk", ac, bp)
        cp = p - c
        d5 = np.einsum("pkc,pkc->pk", ab, cp)
        d6 = np.einsum("pkc,pkc->pk", ac, cp)

        va = d3 * d6 - d5 * d4
        vb = d5 * d2 - d1 * d6
        vc = d1 * d4 - d3 * d2

        closest = np.empty((points.shape[0], candidates.shape[1], 3), dtype=points.dtype)
        done = np.zeros((points.shape[0], candidates.shape[1]), dtype=bool)

        region_a = (d1 <= 0) & (d2 <= 0)
        region_b = (d3 >= 0) & (d4 <= d3)
        region_c = (d6 >= 0) & (d5 <= d6)
        edge_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        edge_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        edge_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)

        with np.errstate(divide="ignore", invalid="ignore"):
            t_ab = np.where(d1 - d3 != 0, d1 / (d1 - d3), 0.0)
            t_ac = np.where(d2 - d6 != 0, d2 / (d2 - d6), 0.0)
            denom = (d4 - d3) + (d5 - d6)
            t_bc = np.where(denom != 0, (d4 - d3) / np.where(denom != 0, denom, 1.0), 0.0)

        choices = (
            (region_a, a),
            (region_b, b),
            (region_c, c),
            (edge_ab, a + t_ab[:, :, None] * ab),
            (edge_ac, a + t_ac[:, :, None] * ac),
            (edge_bc, b + t_bc[:, :, None] * (c - b)),
        )

        for mask, value in choices:
            take = mask & ~done & valid
            if take.any():
                closest[take] = value[take]
                done |= take

        interior = ~done & valid
        if interior.any():
            total = va + vb + vc
            safe_total = np.where(total != 0, total, 1.0)
            v = np.where(total != 0, vb / safe_total, 0.0)
            w = np.where(total != 0, vc / safe_total, 0.0)
            closest[interior] = (a + v[:, :, None] * ab + w[:, :, None] * ac)[interior]

        # The slots left invalid keep whatever ``np.empty`` put there, and
        # the norm over them can overflow on its way to a value the two
        # masks below throw away — so the warning they raise is noise.
        with np.errstate(over="ignore", invalid="ignore"):
            distances = np.linalg.norm(p - closest, axis=2)
        # A candidate whose corner data was degenerate can leave a nan in
        # its distance, and the min over a row with a nan in it is a nan:
        # the nan candidates are the invalid ones or the degenerate ones,
        # and neither has a distance worth keeping.
        distances = np.where(np.isfinite(distances), distances, np.inf)
        distances = np.where(valid, distances, np.inf)
        nearest = distances.min(axis=1)
        if not self.closed:
            return nearest
        # Which side of the surface each point is on. The triangle that
        # gave the smallest distance says which way "out" is.
        best = np.argmin(np.where(valid, distances, np.inf), axis=1)
        rows = np.arange(points.shape[0])
        normals = self.normals[safe[rows, best]]
        corners = self.vertices[self.triangles[:, 0]][safe[rows, best]]
        side = np.sign(np.einsum("nc,nc->n", points - corners, normals))
        side[side == 0.0] = 1.0
        return nearest * side


def distance_to_surface(points: np.ndarray, mesh: MeshPart, neighbours: int = 8) -> np.ndarray:
    """How far each point is from the mesh's surface."""
    return SurfaceDistance(mesh, neighbours)(points)


def winding_numbers(points: np.ndarray, mesh: MeshPart) -> np.ndarray:
    """How many times each point is wound around by the mesh's surface.

    The winding number is the signed sum of the solid angles the mesh's
    triangles subtend at the point: it is zero for a point outside a
    closed mesh and one for a point inside it. It is the honest way to
    ask "is this point in the material", because the answer does not
    depend on how close the point is to the surface — the test of "which
    side of the nearest triangle's plane" does, and gets it wrong for a
    point in the middle of a solid.

    It costs a pass over every triangle for every point, so it is for the
    questions that are asked a few hundred times, not for the ones that
    are asked a hundred thousand times.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.shape[0] == 0 or mesh.triangles.shape[0] == 0:
        return np.zeros(points.shape[0])
    a = mesh.vertices[mesh.triangles[:, 0]][None, :, :] - points[:, None, :]
    b = mesh.vertices[mesh.triangles[:, 1]][None, :, :] - points[:, None, :]
    c = mesh.vertices[mesh.triangles[:, 2]][None, :, :] - points[:, None, :]
    la = np.linalg.norm(a, axis=2)
    lb = np.linalg.norm(b, axis=2)
    lc = np.linalg.norm(c, axis=2)
    numerator = np.einsum("ntc,ntc->nt", a, np.cross(b, c))
    denominator = la * lb * lc
    angles = np.arctan2(numerator, denominator)
    return angles.sum(axis=1) / (2.0 * np.pi)


def inside_mesh(points: np.ndarray, mesh: MeshPart) -> np.ndarray:
    """Whether each point is inside a closed mesh.

    A point is inside when the mesh's surface winds around it once. The
    sign of the winding number says which way the surface is wound, so
    the test is the size of it and not its sign: a mesh wound the other
    way round is still a mesh that has the point inside.
    """
    return np.abs(winding_numbers(points, mesh)) > 0.5


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


def mesh_components(part: MeshPart) -> list[MeshPart]:
    """Every connected component of a part, biggest first.

    A part that is really several things — the floor of a crate and its
    four walls — is one piece of geometry but not one convex shape, and a
    single hull of it swallows the space in the middle. Splitting the
    material into the pieces it is really made of is the first cut, and
    it is free: the components are already there.
    """
    if part.is_empty:
        return []
    labels, count = triangle_components(part)
    if count <= 1:
        return [part]
    areas = part.triangle_areas()
    totals = np.zeros(count)
    np.add.at(totals, labels, areas)
    order = np.argsort(-totals)
    out: list[MeshPart] = []
    for index in order:
        component = part.subset(labels == index)
        if not component.is_empty:
            out.append(component)
    return out


def _thicken(points: np.ndarray, thickness_m: float) -> np.ndarray | None:
    """Thicken a flat point set into a slab, or ``None`` if it cannot be.

    The plane is the one the points lie in, found from the smallest
    singular value of the centred points, and the slab is the set plus
    its mirror image across that plane.

    The caller only gets here when qhull failed or returned a hull with
    no volume — it has already decided the set is effectively flat, so
    this does not second-guess it: a sheet that *bows* slightly still has
    no volume worth speaking of, and refusing to thicken it turns a
    panel into an exception. The direction the points move least is the
    sheet's own normal, whatever its third singular value is.
    """
    if points.shape[0] < 3 or thickness_m <= 0.0:
        return None
    centre = points.mean(axis=0)
    centred = points - centre
    try:
        _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover - a singular matrix
        return None
    if _s.size < 3 or not np.isfinite(_s).all():
        return None
    normal = vt[2]
    return np.concatenate([points, points + normal * thickness_m], axis=0)


def convex_hull(points: np.ndarray, thickness_m: float = 0.002) -> ConvexPiece:
    """The convex hull of a point set, as a piece ready for MuJoCo.

    A flat point set has no hull in the strict sense — its volume is zero
    and qhull refuses it — and a flat point set is what a **panel** is: a
    door, a lid, a board. So a set that is flat to within a hair is
    thickened by a hair along its own plane's normal, and the piece is a
    thin slab. The slab is thicker than the panel by ``thickness_m``,
    which is the same order as the clearance the split opens at a cut, and
    the record says the piece was thickened.
    """
    if points.shape[0] < 4:
        return ConvexPiece(
            vertices=np.zeros((0, 3)),
            faces=np.zeros((0, 3), dtype=np.int64),
            volume=0.0,
            planes=np.zeros((0, 4)),
        )
    try:
        hull = ConvexHull(points)
        if float(hull.volume) <= 1e-12:
            # A flat point set has a hull with no volume: a door, a lid,
            # a board. The piece has to be a slab for the simulation to
            # have anything to stand on, so it is given a thickness.
            raise ValueError("the hull has no volume")
    except Exception:
        thickened = _thicken(points, thickness_m)
        if thickened is None:
            raise GeometryError("the convex hull failed: the points are flat")
        points = thickened
        hull = ConvexHull(points)
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

    The cut is a real cut: a triangle that crosses the plane is cut in
    two, and the piece of it that is on this side is kept. A cut that
    assigns whole triangles by their centroids leaves the material near
    the plane in the wrong piece, and the clearance the builder opens at
    the cut then has nothing to open.

    The triangles that do not cross the plane are kept whole and their
    vertices are carried over unchanged; only the crossing triangles are
    dealt with one at a time. A generated prop has hundreds of thousands
    of triangles and only a few of them cross any one plane, so the split
    between the two is what keeps this cheap.
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
    triangles = part.triangles

    triangle_signed = signed[triangles]
    wholly_inside = np.all(triangle_signed <= 0.0, axis=1)
    partly_inside = np.any(triangle_signed <= 0.0, axis=1)
    crossing = np.nonzero(partly_inside & ~wholly_inside)[0]

    kept = triangles[wholly_inside]
    used = np.unique(kept) if kept.shape[0] else np.zeros(0, dtype=np.int64)
    remap = np.full(vertices.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(used.shape[0], dtype=np.int64)

    # The vertices that are carried over unchanged come first, so that the
    # faces of the triangles that did not cross the plane can be renumbered
    # with a plain lookup. The points the cut makes are appended after
    # them, and the index of a point is its place in that list.
    carried = vertices[used] if used.size else np.zeros((0, 3), dtype=np.float64)
    new_points: list[np.ndarray] = []
    out_faces: list[tuple[int, int, int]] = []
    if kept.shape[0]:
        for row in remap[kept]:
            out_faces.append((int(row[0]), int(row[1]), int(row[2])))

    # A hash of the rounded coordinates, so a point that has been seen is
    # found in constant time: a linear scan makes this quadratic, and a
    # generated mesh has hundreds of thousands of vertices.
    index_of: dict[tuple[int, int, int], int] = {}

    def _key(point: np.ndarray) -> tuple[int, int, int]:
        return (
            int(round(float(point[0]) * 1e7)),
            int(round(float(point[1]) * 1e7)),
            int(round(float(point[2]) * 1e7)),
        )

    # A point the cut makes can land exactly on a vertex the mesh
    # already had. It is the same point, so it is the same vertex: two
    # vertices in one place would cut the mesh in two, and the piece would
    # fall apart into pieces that do not touch.
    carried_index: dict[tuple[int, int, int], int] = {}
    for position, vertex in enumerate(vertices[used]):
        carried_index.setdefault(_key(vertex), int(position))

    def _index(point: np.ndarray) -> int:
        key = _key(point)
        found = index_of.get(key)
        if found is not None:
            return found
        found = carried_index.get(key)
        if found is not None:
            index_of[key] = found
            return found
        index_of[key] = carried.shape[0] + len(new_points)
        new_points.append(point)
        return index_of[key]

    for index in crossing:
        triangle = triangles[index]
        polygon = [(vertices[c], signed[c]) for c in triangle]
        clipped: list[np.ndarray] = []
        for i in range(3):
            point, s = polygon[i]
            nxt_point, nxt_s = polygon[(i + 1) % 3]
            if s <= 0.0:
                clipped.append(point)
            if (s < 0.0 < nxt_s) or (nxt_s < 0.0 < s):
                t = s / (s - nxt_s)
                clipped.append(point + t * (nxt_point - point))
        if len(clipped) < 3:
            continue
        ids = [_index(p) for p in clipped]
        for i in range(1, len(ids) - 1):
            tri = (ids[0], ids[i], ids[i + 1])
            if len(set(tri)) == 3:
                out_faces.append(tri)

    if not out_faces:
        return MeshPart(vertices=np.zeros((0, 3)), triangles=np.zeros((0, 3), dtype=np.int64))
    stacked = (
        np.concatenate(
            [np.atleast_2d(carried)] + [np.atleast_2d(pt) for pt in new_points], axis=0
        )
        if new_points
        else carried
    )
    faces = np.asarray(out_faces, dtype=np.int64)
    return MeshPart(vertices=stacked, triangles=faces)


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

    A generated prop has hundreds of thousands of vertices and a
    decomposition has tens of pieces, so the loop over the pieces is the
    hot one. It keeps only the points that are still uncovered: a point
    that one piece stands over is answered, and there is no need to ask
    the rest.
    """
    if points.shape[0] == 0:
        return np.zeros(0)
    if not pieces:
        return np.full(points.shape[0], np.inf)

    covered = np.zeros(points.shape[0], dtype=bool)
    outside = np.full(points.shape[0], np.inf)
    active = np.arange(points.shape[0])

    for planes in pieces:
        if planes.shape[0] == 0 or active.size == 0:
            continue
        normals = planes[:, :3]
        offsets = planes[:, 3]
        gaps = points[active] @ normals.T + offsets
        worst = gaps.max(axis=1)
        inside = worst <= 0.0
        if inside.any():
            covered[active[inside]] = True
        still = ~inside
        if still.any():
            index = active[still]
            outside[index] = np.minimum(outside[index], worst[still])
            active = index

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
