"""Measure a mesh the way the Prop-maker's critic has to judge it.

The checks are the ones SolidCraft's oracle set uses — volume, area, centre
of mass and bounding box (docs/research/solidcraft.md) — plus the
watertightness a generated prop has to have before it can be called a solid
at all.

Two of the measurements deserve their own words:

* **watertight** means every edge of the mesh is used by exactly two
  triangles — no hole (a *boundary* edge) and no seam (a *non-manifold*
  edge, an edge used three or more times).
* **consistently wound** is separate: the two triangles that share an edge
  must run along it in opposite directions. A mesh can be closed and still
  have one triangle flipped inside out, and then its signed volume is
  nonsense. Keeping the two apart means the report can say which of the
  two went wrong.

The volume and the centre of mass are the signed ones (the divergence
theorem): they are only the enclosed volume and the enclosed centre of mass
when the mesh is closed and consistently wound. On an open mesh they are
still computed and still reported — as measurements of what is there.

**The occupied volume is a different measurement, and it is optional.** The
signed volume answers "how much material is there"; the occupied volume
answers "how much space does the object take up". They agree on a solid and
disagree wildly on a shell: a real mug is 43 cm³ of ceramic inside a
500 cm³ cylinder, and the critic wants the second number. It is measured
by :mod:`core.genbatch.occupancy` and carried here when it was asked for,
so that the plausibility features can be read off the object rather than
off its wall.

**Two signals need Open3D** (:mod:`core.genbatch.o3d_geometry`, the ``o3d``
extra): the **self-intersection** verdict — two triangles can occupy the
same space with every edge still used exactly twice, and only that check
sees it — and the **ray-parity volume**, the winding-free fallback that is
measured when the signed volume cannot be trusted. Both answer
"unchecked"/``None`` when the wheel is absent, so a box without the extra
measures everything it always did and says what it did not.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from core.genbatch import o3d_geometry
from core.genbatch.glb import Mesh
from core.genbatch.occupancy import FillMethod, occupied

__all__ = ["MeshReport", "measure_mesh"]


class MeshReport(BaseModel):
    """What the mesh layer measured about one mesh."""

    triangles: int
    vertices: int
    #: Every edge used by exactly two triangles.
    watertight: bool = False
    #: Every edge's two triangles run along it in opposite directions.
    consistent_winding: bool = False
    #: Edges used by exactly one triangle — the holes.
    boundary_edges: int = 0
    #: Edges used by three or more triangles — the seams.
    nonmanifold_edges: int = 0
    #: Triangles with no area.
    degenerate_triangles: int = 0
    #: The self-intersection verdict: "clean", "self_intersecting", or
    #: "unchecked" — the Open3D wheel absent, the mesh over the triangle
    #: cap, or no triangles at all. Reports written before the check
    #: existed read back as "unchecked", which is what they are.
    self_intersection: Literal["clean", "self_intersecting", "unchecked"] = (
        "unchecked"
    )
    #: How many pairs of crossing triangles were found (only counted when
    #: there are any).
    self_intersection_pairs: int = 0
    #: Why the check declined, when it declined.
    self_intersection_reason: str = ""
    bbox_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bbox_max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extent: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: The signed volume: positive when the mesh is closed and outward-wound.
    volume: float = 0.0
    #: The winding-free enclosed volume by ray parity — the fallback the
    #: volume checks read when the signed volume cannot be trusted.
    #: ``None`` when the signed volume is reliable, or the ``o3d`` extra is
    #: absent.
    parity_volume: float | None = None
    #: The volume of the space the object **occupies** — the envelope of a
    #: shell, not the material in it. ``None`` when it was not measured;
    #: the signed volume is then the only volume there is.
    occupied_volume: float | None = None
    #: The centre of the occupied region, in the mesh's own units.
    occupied_centre: tuple[float, float, float] | None = None
    #: Which measure produced :attr:`occupied_volume`.
    occupied_method: str = ""
    #: The total surface area.
    area: float = 0.0
    #: The centre of mass of the enclosed solid.
    centre_of_mass: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: The largest distance between two points of the bounding box.
    diagonal: float = 0.0

    def as_dict(self) -> dict:
        return self.model_dump()

    @property
    def volume_reliable(self) -> bool:
        """Can the signed volume be trusted as *the* volume?

        The divergence theorem needs a closed, consistently wound surface
        with positive orientation **and** no self-intersection: overlapping
        triangles count their overlap twice (the reference set's storage
        shelf reads 3.9x its ray-parity volume). An "unchecked"
        self-intersection verdict does not clear the mesh — it says the
        question was not asked — so there the volume stays trusted exactly
        as it was before the check existed.
        """
        return (
            self.watertight
            and self.consistent_winding
            and self.volume > 0
            and self.self_intersection != "self_intersecting"
        )


def measure_mesh(
    mesh: Mesh,
    *,
    fill_method: FillMethod | str | None = None,
    fill_resolution: int = 64,
    selfx: bool | int | None = True,
    parity_fallback: bool = True,
) -> MeshReport:
    """Measure a mesh: topology, size, and the three solid quantities.

    ``fill_method`` is optional and, when it is given, the report also
    carries **what the object occupies** — the volume of the space it takes
    up, which is not the same number as the volume of the material in it.
    Without it the report carries the signed volume alone, and the cost of
    the measurement is what it was.

    ``selfx`` is the self-intersection check: ``True`` runs it under the
    measured triangle cap, an ``int`` runs it under that cap instead,
    ``False``/``None`` turns it off (the pre-Open3D measurement).
    ``parity_fallback`` measures the ray-parity volume — on the same grid
    as ``fill_resolution`` — when the signed volume turns out not to be
    trustworthy, so the volume checks have something honest to read. Both
    decline to "unchecked"/``None`` when the ``o3d`` extra is absent.
    """
    positions = np.asarray(mesh.positions, dtype=np.float64)
    indices = np.asarray(mesh.indices, dtype=np.int64)
    selfx_report = (
        o3d_geometry.self_intersection(mesh, cap=None)
        if selfx is False or selfx is None
        else o3d_geometry.self_intersection(
            mesh,
            cap=(
                o3d_geometry.SELF_INTERSECTION_CAP
                if selfx is True
                else int(selfx)
            ),
        )
    )
    if indices.size == 0:
        empty = MeshReport(
            triangles=0,
            vertices=int(positions.shape[0]),
            self_intersection=selfx_report.state,
            self_intersection_pairs=selfx_report.pairs,
            self_intersection_reason=selfx_report.reason,
        )
        return empty

    a = positions[indices[:, 0]]
    b = positions[indices[:, 1]]
    c = positions[indices[:, 2]]

    # -- the size of the thing ------------------------------------------
    bbox_min = positions.min(axis=0)
    bbox_max = positions.max(axis=0)
    extent = bbox_max - bbox_min
    diagonal = float(np.linalg.norm(extent))

    # -- per-triangle quantities ----------------------------------------
    cross = np.cross(b - a, c - a)
    twice_area = np.linalg.norm(cross, axis=1)
    area = float(0.5 * twice_area.sum())
    # A triangle of no area: below the box's own numerical dust.
    epsilon = max(1e-18, diagonal * 1e-12)
    degenerate = int(np.count_nonzero(twice_area <= 2.0 * epsilon))

    # The divergence theorem: the signed volume, and where the mass sits.
    six_volumes = np.einsum("ij,ij->i", a, np.cross(b, c))
    six_volume = float(six_volumes.sum())
    volume = six_volume / 6.0
    if abs(six_volume) > epsilon * epsilon:
        com = (six_volumes[:, None] * (a + b + c)).sum(axis=0) / (4.0 * six_volume)
    else:
        com = np.zeros(3)

    # -- the topology ----------------------------------------------------
    boundary, nonmanifold, consistent = _edge_report(indices, positions.shape[0])

    # -- what the object occupies ----------------------------------------
    occupied_volume: float | None = None
    occupied_centre: tuple[float, float, float] | None = None
    occupied_method = ""
    if fill_method is not None:
        occupancy = occupied(mesh, fill_method, resolution=fill_resolution)
        occupied_volume = occupancy.volume
        occupied_centre = occupancy.centre
        occupied_method = occupancy.method

    report = MeshReport(
        triangles=int(indices.shape[0]),
        vertices=int(positions.shape[0]),
        watertight=boundary == 0 and nonmanifold == 0,
        consistent_winding=consistent,
        boundary_edges=boundary,
        nonmanifold_edges=nonmanifold,
        degenerate_triangles=degenerate,
        self_intersection=selfx_report.state,
        self_intersection_pairs=selfx_report.pairs,
        self_intersection_reason=selfx_report.reason,
        bbox_min=tuple(float(x) for x in bbox_min),
        bbox_max=tuple(float(x) for x in bbox_max),
        extent=tuple(float(x) for x in extent),
        volume=volume,
        occupied_volume=occupied_volume,
        occupied_centre=occupied_centre,
        occupied_method=occupied_method,
        area=area,
        centre_of_mass=tuple(float(x) for x in com),
        diagonal=diagonal,
    )
    # The ray-parity fallback is measured only when it is needed: it costs
    # a median 18 ms and answers what the signed volume cannot.
    if parity_fallback and not report.volume_reliable:
        report.parity_volume = o3d_geometry.parity_volume(
            mesh, resolution=fill_resolution
        )
    return report


def _edge_report(indices: np.ndarray, vertex_count: int) -> tuple[int, int, bool]:
    """Count the bad edges, and say whether the mesh is consistently wound.

    Returns ``(boundary_edges, nonmanifold_edges, consistent_winding)``.
    """
    if vertex_count <= 0:
        return 0, 0, True
    directed = np.concatenate(
        [
            indices[:, [0, 1]],
            indices[:, [1, 2]],
            indices[:, [2, 0]],
        ],
        axis=0,
    )
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    # One integer key per undirected edge.
    keys = lo * np.int64(vertex_count) + hi
    unique, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)

    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))

    # A consistently wound closed mesh uses every manifold edge once in each
    # direction; count the ascending uses per edge and ask for exactly one.
    ascending = (directed[:, 0] < directed[:, 1]).astype(np.float64)
    per_edge = np.bincount(inverse, weights=ascending, minlength=unique.size)
    manifold = counts == 2
    consistent = bool(np.all(per_edge[manifold] == 1.0)) if manifold.any() else True
    return boundary, nonmanifold, consistent
