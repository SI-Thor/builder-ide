"""The repair stage: between TRELLIS.2 and the critic.

TRELLIS.2's meshes come out of the night looking broken to any tool that
counts edges: the mini-night measured **155 k–234 k boundary edges on all
nine** of its props, and the critic's heaviest check (weight 3) scored zero
for every candidate (docs/lab/mini-night.md §3).

They are not broken. **The unwrap split the vertices at the UV seams**, and
the split copies sit at *bit-identical* positions, so the mesh is a closed
solid whose *index buffer* cannot see the closure. Welding the coincident
vertices back together closes every one of those boundary edges without
moving a single vertex.

What welding leaves behind is a handful of edges where the surface crosses
itself — three or four per prop, at the fixed [-0.5, 0.5]³ domain wall the
generator clips to. A self-crossing edge is used by four triangles, which no
solid can be. The repair splits it: the two sheets that cross there become
two closed shells that touch, each with its own copy of the edge. The
geometry does not move, so the prop looks exactly the same.

So the repair is two operations, and both of them are *topological* — the
prop's shape, its silhouette and its texture are untouched:

* **weld** — merge the vertices that sit at the same position;
* **split** — separate the edges the surface crosses itself on.

And the repair is measured, like everything else on this box: the report
carries the before and after, the wall-clock it cost, and the **silhouette
IoU** against the mesh it was given — the number that says the repair did
not quietly reshape the prop.

Nothing here needs a new dependency: it is numpy, like the measurement code
it sits next to. The alternatives that were measured (MeshFix, trimesh's
hole filling, a voxel remesh, manifold3d) are in
docs/lab/exp-mesh-repair.md, with their licences and their numbers.
"""

from __future__ import annotations

import time
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from core.genbatch.fidelity import silhouette_iou
from core.genbatch.glb import Mesh
from core.genbatch.mesh import MeshReport, measure_mesh

__all__ = [
    "RepairRecipe",
    "RepairReport",
    "RepairResult",
    "repair_mesh",
]


class RepairRecipe(BaseModel):
    """The repair stage's part of the recipe.

    It is a recipe and not a constant because the repair is a step the
    night takes: a different tolerance or a different method is a different
    recipe, and the asset's provenance says which one it was.
    """

    #: ``weld`` merges the coincident vertices and splits the edges the
    #: surface crosses itself on. ``none`` turns the stage off, which is what
    #: the "what did TRELLIS.2 hand us?" comparison needs.
    method: Literal["none", "weld"] = "weld"
    #: How far apart two vertices may be and still count as the same point,
    #: as a fraction of the prop's own bounding-box diagonal. The seams the
    #: unwrap opens are bit-identical, so anything loose enough to catch a
    #: floating-point wobble is loose enough.
    tolerance: float = Field(default=1e-6, gt=0.0)
    #: Whether the edges the surface crosses itself on are split.
    split_non_manifold: bool = True
    #: The silhouette IoU the repair must reach, relative to the mesh it was
    #: given. Below it, the repair is reported as a failure rather than
    #: quietly shipped.
    min_fidelity: float = Field(default=0.98, ge=0.0, le=1.0)
    #: How many surface samples the fidelity check draws, and how many pixels
    #: wide the silhouette grid is. Both are part of the recipe: the fidelity
    #: number is only reproducible if they are — and the grid has to be
    #: sampled densely enough that the measure is not noise.
    fidelity_samples: int = Field(default=1_000_000, ge=1)
    fidelity_resolution: int = Field(default=128, ge=8)
    fidelity_views: tuple[str, ...] = ("+x", "+y", "+z")


class RepairReport(BaseModel):
    """What the repair did, and what it cost."""

    method: str = "weld"
    #: The wall-clock the repair took, on the CPU lane.
    seconds: float = 0.0
    vertices_before: int = 0
    vertices_after: int = 0
    triangles: int = 0
    #: How many coincident vertices were merged.
    welded_vertices: int = 0
    #: How many boundary edges the weld closed.
    boundary_edges_closed: int = 0
    #: How many zero-volume flaps — faces that were there twice — came out.
    degenerate_faces_collapsed: int = 0
    #: How many pinched vertices were given a copy of themselves.
    pinched_vertices_split: int = 0
    #: How many self-crossing edges were split.
    nonmanifold_edges_split: int = 0
    #: The silhouette IoU against the mesh the repair was given.
    fidelity: float = 1.0
    #: The mesh as it was, and the mesh as it is now.
    before: MeshReport | None = None
    after: MeshReport | None = None
    #: False when the repair could not be trusted — the prop is left as it
    #: was, and the reason says why.
    ok: bool = True
    reason: str = ""


class RepairResult:
    """The repaired mesh and the report of the repair."""

    __slots__ = ("mesh", "report")

    def __init__(self, mesh: Mesh, report: RepairReport) -> None:
        self.mesh = mesh
        self.report = report


def _weld(
    positions: np.ndarray, indices: np.ndarray, tolerance: float
) -> tuple[np.ndarray, np.ndarray, int]:
    """Merge the vertices that sit at the same place.

    Returns the welded positions, the welded indices, and how many vertices
    were merged away. The first vertex of each group is the one that
    survives, so a group of bit-identical vertices keeps its exact
    coordinates — no averaging, no drift.
    """
    extent = positions.max(axis=0) - positions.min(axis=0)
    scale = float(np.linalg.norm(extent))
    if scale <= 0:
        return positions, indices, 0
    # Snap to a grid whose cell is the tolerance, then merge by cell.
    keys = np.round(positions / (tolerance * scale)).astype(np.int64)
    _unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    count = int(inverse.max()) + 1
    # The first original vertex of each group wins.
    order = np.argsort(inverse, kind="stable")
    starts = np.searchsorted(inverse[order], np.arange(count))
    firsts = order[starts]
    welded_positions = positions[firsts]
    welded_indices = inverse[indices]
    return welded_positions, welded_indices, int(positions.shape[0] - count)


def _edge_table(indices: np.ndarray, vertex_count: int):
    """The mesh's edges, and how many triangles use each one."""
    directed = np.concatenate(
        [indices[:, [0, 1]], indices[:, [1, 2]], indices[:, [2, 0]]], axis=0
    )
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    keys = lo * np.int64(vertex_count) + hi
    unique, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    return directed, unique, inverse, counts


def _faces_around(indices: np.ndarray, vertex: int) -> np.ndarray:
    """The faces that touch a vertex."""
    return np.flatnonzero((indices == vertex).any(axis=1))


def _candidate_pairings(
    indices: np.ndarray, faces: np.ndarray, a: int, b: int
) -> list[list[np.ndarray]]:
    """The ways the triangles on a crossed edge could pair into sheets.

    A sheet's two triangles traverse the edge in opposite directions — that
    is what keeps the winding consistent once the edge is split — so only
    pairings that respect that are offered.
    """
    forward: list[int] = []
    backward: list[int] = []
    for face in faces:
        triple = [int(v) for v in indices[face]]
        # A triangle's edges are cyclic: (t0,t1), (t1,t2), (t2,t0).
        directed_use = (triple[0], triple[1]) == (a, b) or (
            triple[1], triple[2]
        ) == (a, b) or (triple[2], triple[0]) == (a, b)
        (forward if directed_use else backward).append(int(face))
    if len(forward) != len(backward):
        return []
    pairs: list[list[np.ndarray]] = []

    def match(
        remaining_forward: list[int], remaining_backward: list[int], chosen: list[np.ndarray]
    ):
        if not remaining_forward:
            pairs.append(list(chosen))
            return
        head = remaining_forward[0]
        for position, other in enumerate(remaining_backward):
            match(
                remaining_forward[1:],
                remaining_backward[:position] + remaining_backward[position + 1 :],
                chosen + [np.asarray([head, other])],
            )

    match(forward, list(backward), [])
    return pairs


def _collapse_degenerate_faces(
    indices: np.ndarray,
) -> tuple[np.ndarray, int]:
    """Remove the faces that are there twice.

    A generator that dual-contours a voxel grid can leave a triangle in the
    mesh **twice**: once each way round. The two copies enclose no volume —
    they cancel — and the surface pinches to a line along their shared edge.
    The copy is a zero-volume flap, and a flap is not a surface: removing it
    takes the pinch away and leaves the solid's volume exactly where it was.

    Returns the faces to keep and how many were removed.
    """
    if indices.shape[0] == 0:
        return indices, 0
    ordered = np.sort(indices, axis=1)
    _unique, inverse, counts = np.unique(
        ordered, axis=0, return_inverse=True, return_counts=True
    )
    inverse = inverse.ravel()
    duplicated = counts > 1
    if not duplicated.any():
        return indices, 0
    drop = duplicated[inverse]
    return indices[~drop], int(np.count_nonzero(drop))


def _split_pinched_vertices(
    positions: np.ndarray, indices: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int]:
    """Split the vertices the surface pinches at.

    Around a vertex the surface is a disc of faces joined edge to edge. Where
    two sheets cross, that disc is two discs glued along the crossing edge:
    the vertex is *pinched*. Giving each piece its own copy of the vertex
    un-pinches it, and it splits the crossing edges at the same time — each
    copy of the vertex carries its own faces, so each crossing edge becomes
    several edges with two faces each.

    The copies sit at the same place, so the geometry does not move.
    """
    vertex_count = positions.shape[0]
    _directed, unique, _inverse, counts = _edge_table(indices, vertex_count)
    crossed = unique[counts > 2]
    if crossed.size == 0:
        return positions, indices, 0
    candidates = np.unique(
        np.concatenate([crossed // vertex_count, crossed % vertex_count])
    )
    new_positions = list(positions)
    new_indices = indices.copy()
    split_count = 0
    for vertex in candidates:
        vertex = int(vertex)
        faces = _faces_around(new_indices, vertex)
        if faces.size == 0:
            continue
        # The edges through the vertex, and the faces that use them.
        through: dict[tuple[int, int], list[int]] = {}
        for face in faces:
            for other in new_indices[face]:
                if int(other) == vertex:
                    continue
                key = (min(vertex, int(other)), max(vertex, int(other)))
                through.setdefault(key, []).append(int(face))
        crossed_here = {key for key, users in through.items() if len(users) > 2}
        if not crossed_here:
            continue
        # The fan around the vertex, with the crossing edges taken out.
        neighbours: dict[int, set[int]] = {int(f): set() for f in faces}
        for key, users in through.items():
            if key in crossed_here or len(users) != 2:
                continue
            neighbours[users[0]].add(users[1])
            neighbours[users[1]].add(users[0])
        pieces: list[set[int]] = []
        seen: set[int] = set()
        for face in faces:
            face = int(face)
            if face in seen:
                continue
            stack = [face]
            piece: set[int] = set()
            while stack:
                current = stack.pop()
                if current in piece:
                    continue
                piece.add(current)
                seen.add(current)
                stack.extend(neighbours[current] - piece)
            pieces.append(piece)
        if len(pieces) < 2:
            continue
        for piece in pieces[1:]:
            copy = len(new_positions)
            new_positions.append(new_positions[vertex].copy())
            for face in piece:
                new_indices[face] = np.where(
                    new_indices[face] == vertex, copy, new_indices[face]
                )
            split_count += 1
    return np.asarray(new_positions, dtype=np.float64), new_indices, split_count


def _split_non_manifold(
    positions: np.ndarray, indices: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int]:
    """Split the edges the surface crosses itself on.

    An edge used by more than two triangles is where two sheets of the
    surface cross. Splitting it gives each sheet its own copy of the edge —
    and its own copy of the edge's two vertices — so each edge is used by
    exactly two triangles again. The geometry does not move: the two shells
    still touch, exactly where they did.

    Returns the new positions, the new indices, and how many edges were
    split.
    """
    vertex_count = positions.shape[0]
    split_count = 0
    for _ in range(16):
        directed, unique, inverse, counts = _edge_table(indices, vertex_count)
        bad = np.flatnonzero(counts > 2)
        if bad.size == 0:
            break
        edge = int(unique[bad[0]])
        a, b = int(edge // vertex_count), int(edge % vertex_count)

        # The triangles on this edge. The directed-edge table is three blocks
        # of one entry per triangle, so the triangle an occurrence belongs to
        # is its position inside its block.
        occurrences = np.flatnonzero(inverse == bad[0])
        faces = np.unique(occurrences % indices.shape[0])
        if faces.size < 4 or faces.size % 2 != 0:
            # An odd number cannot be paired into sheets; leave it be rather
            # than guess.
            break
        # Which way round the edge each triangle goes, and which pairing of
        # them into sheets is the one the surface actually has.
        fan = None
        sheets = None
        for candidate in _candidate_pairings(indices, faces, a, b):
            trial = _fan_sheets(indices, positions, a, b, candidate)
            if trial is not None:
                sheets = candidate
                fan = trial
                break
        if sheets is None or fan is None:
            break
        fan_a, fan_b = fan

        new_positions = list(positions)
        new_indices = indices.copy()
        for number, _sheet in enumerate(sheets):
            if number == 0:
                continue
            new_a = len(new_positions)
            new_positions.append(positions[a].copy())
            new_b = len(new_positions)
            new_positions.append(positions[b].copy())
            # Every face of this sheet that touches a or b takes the copies.
            for face in fan_a[number]:
                new_indices[face] = np.where(
                    new_indices[face] == a, new_a, new_indices[face]
                )
            for face in fan_b[number]:
                new_indices[face] = np.where(
                    new_indices[face] == b, new_b, new_indices[face]
                )
        positions = np.asarray(new_positions, dtype=np.float64)
        indices = new_indices
        vertex_count = positions.shape[0]
        split_count += 1
    return positions, indices, split_count


def _fan_sheets(
    indices: np.ndarray,
    positions: np.ndarray,
    a: int,
    b: int,
    sheets: list[np.ndarray],
):
    """Split the fan around a crossing edge's two vertices into its sheets.

    Around a vertex the surface is a disc of faces joined edge to edge. A
    vertex where two sheets cross has a disc that is two discs glued at the
    crossing edge; take that edge out and the two fall apart. This returns,
    for each of the edge's two vertices, the faces of each sheet.
    """
    result = []
    for vertex, other in ((a, b), (b, a)):
        faces = _faces_around(indices, vertex)
        if faces.size == 0:
            return None
        # The edges through the vertex, and the faces that use them.
        through: dict[tuple[int, int], list[int]] = {}
        for face in faces:
            triple = indices[face]
            for other_vertex in triple:
                if int(other_vertex) == vertex:
                    continue
                key = (min(vertex, int(other_vertex)), max(vertex, int(other_vertex)))
                through.setdefault(key, []).append(int(face))
        # The fan: faces joined to each other through an edge at the vertex,
        # ignoring the crossing edge itself.
        neighbours: dict[int, set[int]] = {int(f): set() for f in faces}
        for key, users in through.items():
            if key == (min(vertex, other), max(vertex, other)):
                continue
            if len(users) == 2:
                neighbours[users[0]].add(users[1])
                neighbours[users[1]].add(users[0])
        # The components of that fan.
        seen: set[int] = set()
        components: list[set[int]] = []
        for face in faces:
            face = int(face)
            if face in seen:
                continue
            stack = [face]
            component: set[int] = set()
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                seen.add(current)
                stack.extend(neighbours[current] - component)
            components.append(component)
        # The sheet each component belongs to: the one that holds one of the
        # faces on the crossing edge. A component that mixes two sheets
        # cannot be told apart, and guessing would split the wrong faces.
        sheets_of: list[int] = []
        for component in components:
            owners = set()
            for number, sheet in enumerate(sheets):
                if component & set(int(f) for f in sheet):
                    owners.add(number)
            if len(owners) != 1:
                return None
            sheets_of.append(owners.pop())
        # Group the components by the sheet they belong to.
        grouped: list[set[int]] = [set() for _ in sheets]
        for component, owner in zip(components, sheets_of):
            grouped[owner] |= component
        result.append(grouped)
    return result


def repair_mesh(mesh: Mesh, recipe: RepairRecipe | None = None) -> RepairResult:
    """Repair a mesh: make it a closed solid without changing what it looks like.

    The result carries the repaired mesh and a report: what changed, what it
    cost, and how much of the prop's outline survived.
    """
    recipe = recipe or RepairRecipe()
    started = time.perf_counter()
    before = measure_mesh(mesh)
    report = RepairReport(
        method=recipe.method,
        vertices_before=mesh.vertices,
        triangles=mesh.triangles,
        before=before,
    )
    if recipe.method == "none":
        report.seconds = time.perf_counter() - started
        report.after = before
        report.reason = "the repair stage was turned off"
        return RepairResult(mesh=mesh, report=report)

    positions, indices, welded = _weld(
        mesh.positions, mesh.indices, recipe.tolerance
    )
    report.welded_vertices = welded
    if recipe.split_non_manifold:
        # A face that is there twice is a zero-volume flap; it comes out
        # first, because a flap is what pins the surface in the first place.
        indices, collapsed = _collapse_degenerate_faces(indices)
        report.degenerate_faces_collapsed = collapsed
        # A pinched vertex is where two sheets cross; each of its pieces gets
        # its own copy, which splits the crossing edges as well.
        positions, indices, pinched = _split_pinched_vertices(positions, indices)
        report.pinched_vertices_split = pinched
        # Whatever still crosses gets its own copy of the edge.
        positions, indices, split = _split_non_manifold(positions, indices)
        report.nonmanifold_edges_split = split
    after = measure_mesh(Mesh(positions=positions, indices=indices))
    report.after = after
    report.vertices_after = int(positions.shape[0])
    report.boundary_edges_closed = before.boundary_edges - after.boundary_edges

    fidelity = silhouette_iou(
        mesh,
        Mesh(positions=positions, indices=indices),
        views=recipe.fidelity_views,
        resolution=recipe.fidelity_resolution,
        samples=recipe.fidelity_samples,
    )
    report.fidelity = fidelity
    report.seconds = time.perf_counter() - started
    if fidelity < recipe.min_fidelity:
        report.ok = False
        report.reason = (
            f"the repair changed the prop's outline — silhouette IoU "
            f"{fidelity:.4f} against a floor of {recipe.min_fidelity:.2f}"
        )
    elif not after.watertight:
        report.ok = False
        report.reason = (
            f"the repair left {after.boundary_edges} boundary edges and "
            f"{after.nonmanifold_edges} non-manifold edges"
        )
    elif not after.consistent_winding or after.volume <= 0:
        report.ok = False
        report.reason = "the repaired mesh is not a consistently wound solid"
    else:
        report.reason = (
            f"welded {welded:,} coincident vertices, took out "
            f"{report.degenerate_faces_collapsed} zero-volume flaps, split "
            f"{report.pinched_vertices_split} pinched vertices and "
            f"{report.nonmanifold_edges_split} self-crossing edges; the "
            f"outline is {fidelity:.4f} of the original"
        )
    return RepairResult(mesh=Mesh(positions=positions, indices=indices), report=report)
