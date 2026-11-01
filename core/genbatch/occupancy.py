"""What the object **occupies**, not what its shell is made of.

**The problem this solves.** A real mug is a shell: its wall encloses 43 cm³
of ceramic, not the 826 cm³ its bounding box holds. The critic's
``fill_ratio`` divides a mesh's **signed volume** by its bounding box, so a
real mug reads 0.052 and a solid toy mug reads 0.68 — and a prior fitted on
generated solids calls every real object a ghost (docs/lab/exp-critic-shells.md).

The signed volume is the right measure for a *solid* and the wrong measure
for a *shell*: it answers "how much material is there", while the question
the critic asks is "how much of the space does the object take up".

**The measures.** Three of them, and which one is right is a question for a
measurement and not for a preference:

``convex`` (the default)
    the **convex hull** of the object's vertices, over the bounding box.
    For a convex solid this is the solid's own fill ratio, so the numbers
    the toy set already carries stay meaningful; for a shell it is the
    envelope, which is what the critic wants. It over-estimates for a
    concave object — the hull of an L-shaped bracket is a box — and it
    under-estimates nothing: the hull always contains the object, so the
    occupied volume is never below the material's. It needs scipy, which
    the Thor's venvs carry (aarch64 wheels, 1.18.1);
``visual``
    the **visual hull** — the intersection of the object's three
    axis-aligned silhouettes, computed in numpy from the triangles
    themselves. It is within 0.1 % on a mug (the envelope of a cup is its
    cylinder) and it *sees* a concavity (the L-bracket's notch), but a
    sparse object defeats it: a lattice fixture's silhouettes are full of
    gaps, and the gaps are reachable from outside, so its silhouette
    collapses and it reads as a splinter rather than as the frame it is.
    numpy only;
``signed``
    the shell's own signed volume — the measure this replaces, kept so the
    before-and-after can be measured on the same meshes.

**What the measurement said.** Over the 38 sampled real SimReady assets
(docs/lab/exp-critic-shells.md), the fill ratios are: ``signed`` — median
0.1442, **23 of 38 below 0.2**; ``visual`` — median 0.4485, 11 of 38 below
0.2; ``convex`` — median 0.6154, **none below 0.2**, and the lowest is
0.3070. With the prior fitted on the union of the toy approved set and the
sample, ``convex`` flags the ghost (0.0385) and **1 of 38** real assets
(2.6 %); the toy prior alone, reading the same occupied features, flags
all 38. The hull won, and the other two are kept as parameters.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import numpy as np

from core.genbatch.glb import Mesh

__all__ = [
    "DEFAULT_FILL_METHOD",
    "FILL_METHODS",
    "FillMethod",
    "Occupancy",
    "occupied",
    "visual_hull_volume",
]

#: The measures of "what the object occupies".
FILL_METHODS: tuple[str, ...] = ("convex", "visual", "signed")

FillMethod = Literal["convex", "visual", "signed"]

#: The measure the critic uses by default — the one the measurement chose.
DEFAULT_FILL_METHOD: FillMethod = "convex"

#: The grid's longest side, in cells. The occupancy grid is cubic in the
#: cell count and anisotropic in the cell size: each axis gets the same
#: number of cells, so a long thin object is sampled finely along its
#: short axes and coarsely along its long one.
DEFAULT_RESOLUTION = 64

#: How many rasterised samples one chunk may hold. The rasteriser expands
#: every triangle into the cells its bounding box covers, so a mesh with a
#: few very large triangles can ask for a lot at once; the work is done in
#: chunks so the peak allocation stays bounded. The chunk holds about
#: seventeen arrays of one sample each, so a million samples is roughly
#: 140 MB of working set — a bound the shared box can afford.
_SAMPLE_BUDGET = 1_000_000


@dataclass(frozen=True)
class Occupancy:
    """How much space the object takes up, and where its mass sits."""

    #: The volume of the occupied region, in the mesh's own units.
    volume: float
    #: The centre of the occupied region — the object's centre of bulk.
    centre: tuple[float, float, float]
    #: Which measure produced this.
    method: str
    #: The grid the measure used, in cells along the longest axis.
    resolution: int
    #: The wall-clock the measure cost, in seconds.
    seconds: float

    def as_dict(self) -> dict:
        return {
            "volume": self.volume,
            "centre": list(self.centre),
            "method": self.method,
            "resolution": self.resolution,
            "seconds": self.seconds,
        }


def occupied(
    mesh: Mesh,
    method: FillMethod | str = DEFAULT_FILL_METHOD,
    *,
    resolution: int = DEFAULT_RESOLUTION,
) -> Occupancy:
    """Measure what the object occupies.

    ``method`` is one of :data:`FILL_METHODS`. ``convex`` is the default:
    the convex hull, which is what the measurement chose
    (docs/lab/exp-critic-shells.md). ``visual`` is the numpy-only one, for
    a box without scipy.
    """
    if method not in FILL_METHODS:
        raise ValueError(
            f"unknown fill method {method!r}; the measures are {FILL_METHODS}"
        )
    if resolution < 4:
        raise ValueError("the occupancy grid needs at least four cells a side")

    started = time.perf_counter()
    positions = np.asarray(mesh.positions, dtype=np.float64)
    indices = np.asarray(mesh.indices, dtype=np.int64)

    if positions.size == 0 or indices.size == 0:
        return Occupancy(
            volume=0.0,
            centre=(0.0, 0.0, 0.0),
            method=method,
            resolution=resolution,
            seconds=time.perf_counter() - started,
        )

    if method == "signed":
        volume, centre = _signed_occupancy(positions, indices)
    elif method == "convex":
        volume, centre = _convex_occupancy(positions, resolution)
    else:
        volume, centre = _visual_occupancy(positions, indices, resolution)

    return Occupancy(
        volume=float(volume),
        centre=tuple(float(value) for value in centre),
        method=method,
        resolution=int(resolution),
        seconds=time.perf_counter() - started,
    )


# -- the measures ------------------------------------------------------------


def _signed_occupancy(
    positions: np.ndarray, indices: np.ndarray
) -> tuple[float, np.ndarray]:
    """The shell's own signed volume — the measure this replaces.

    Kept as a parameter so the before-and-after can be measured on the same
    meshes. On an open mesh the number is meaningless, and that is the
    point: it is what the critic was reading.
    """
    a = positions[indices[:, 0]]
    b = positions[indices[:, 1]]
    c = positions[indices[:, 2]]
    six = np.einsum("ij,ij->i", a, np.cross(b, c))
    total = float(six.sum())
    volume = total / 6.0
    if abs(total) > 0.0:
        centre = (six[:, None] * (a + b + c)).sum(axis=0) / (4.0 * total)
    else:
        centre = positions.mean(axis=0)
    return volume, centre


def _convex_occupancy(
    positions: np.ndarray, resolution: int
) -> tuple[float, np.ndarray]:
    """The convex hull of the vertices — scipy, an optional extra.

    An over-estimate for every concave object, and the price of that is
    paid in discrimination: the hull of an L-shaped bracket is a box.

    The hull's **centre of bulk** is its volume centroid, computed from
    qhull's own surface triangulation: the hull is a cone from an interior
    point over its facets, and the volume centroid of that sum is the
    volume-weighted mean of the pieces' centroids. The bounding box's
    middle would be a substitute, and a wrong one for an object whose
    mass is not spread evenly.
    """
    try:
        from scipy.spatial import ConvexHull
    except ImportError as exc:  # pragma: no cover - the extra is optional
        raise ImportError(
            "the 'convex' fill method needs scipy; the 'visual' method is "
            "numpy only and needs nothing"
        ) from exc

    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    extent = hi - lo
    if np.any(extent <= 0.0):
        return 0.0, positions.mean(axis=0)
    hull = ConvexHull(positions)
    volume = float(hull.volume)

    # The mean of the hull's vertices is inside it — the hull is convex and
    # a mean of points is a convex combination of them.
    vertices = np.asarray(hull.vertices, dtype=np.int64)
    simplices = np.asarray(hull.simplices, dtype=np.int64)
    if vertices.size == 0 or simplices.size == 0:
        return volume, lo + extent * 0.5
    inside = positions[vertices].mean(axis=0)

    corners = positions[simplices]
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    tetrahedra = np.abs(
        np.einsum("ij,ij->i", b - inside, np.cross(c - inside, a - inside))
    ) / 6.0
    total = float(tetrahedra.sum())
    if total <= 0.0:
        return volume, lo + extent * 0.5
    centres = (inside + a + b + c) / 4.0
    centre = (tetrahedra[:, None] * centres).sum(axis=0) / total
    return volume, centre


def _visual_occupancy(
    positions: np.ndarray, indices: np.ndarray, resolution: int
) -> tuple[float, np.ndarray]:
    """The visual hull: the intersection of the three axis silhouettes."""
    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    extent = hi - lo
    if np.any(extent <= 0.0):
        return 0.0, positions.mean(axis=0)

    normalised = (positions - lo) / np.maximum(extent, 1e-12)

    # mask[a, b] is the silhouette down the third axis, with the a axis
    # across and the b axis up: mask[row=b, column=a].
    silhouettes = {}
    for a, b in ((0, 1), (0, 2), (1, 2)):
        silhouettes[(a, b)] = _silhouette(
            normalised[:, [a, b]], indices, resolution
        )

    m01 = silhouettes[(0, 1)]
    m02 = silhouettes[(0, 2)]
    m12 = silhouettes[(1, 2)]
    occupied_voxels = (
        m01.T[:, :, None] & m02.T[:, None, :] & m12[None, :, :]
    )

    cell = extent / float(resolution)
    volume = float(occupied_voxels.sum()) * float(cell[0] * cell[1] * cell[2])

    if not occupied_voxels.any():
        return volume, lo + extent * 0.5

    counts = occupied_voxels.sum(axis=(0, 2))
    weights = (np.arange(resolution) + 0.5) * cell[0]
    centre_x = float((counts * weights).sum() / counts.sum())
    counts = occupied_voxels.sum(axis=(0, 1))
    weights = (np.arange(resolution) + 0.5) * cell[1]
    centre_y = float((counts * weights).sum() / counts.sum())
    counts = occupied_voxels.sum(axis=(1, 2))
    weights = (np.arange(resolution) + 0.5) * cell[2]
    centre_z = float((counts * weights).sum() / counts.sum())

    return volume, np.array([centre_x, centre_y, centre_z]) + lo


def _silhouette(
    points: np.ndarray, indices: np.ndarray, resolution: int
) -> np.ndarray:
    """The projection of the mesh onto a plane, as a grid of cells.

    The grid cell ``(row, column)`` covers the unit square's cell of that
    index, and a cell is marked when the **centre** of it falls inside one
    of the projected triangles.

    The marked cells are then **filled**: the silhouette of an object is the
    region its outline encloses, and the outline alone is not enough. A
    mug's wall, seen down its axis, projects onto a circle — a curve with no
    area — so the projection of the surface is a ring one cell wide and the
    hull built from it would be the intersection of three rings, which is
    nothing at all. Filling from the outside fixes it: the cells the
    outside cannot reach are inside the silhouette, so the mug's silhouette
    is the disc its outline encloses.
    """
    mask = np.zeros((resolution, resolution), dtype=bool)
    if indices.size == 0:
        return mask

    px = points[:, 0] * resolution
    py = points[:, 1] * resolution

    triangles = indices
    tx = px[triangles]
    ty = py[triangles]

    x0 = np.clip(np.floor(tx.min(axis=1)).astype(np.int64), 0, resolution - 1)
    x1 = np.clip(np.ceil(tx.max(axis=1)).astype(np.int64) - 1, 0, resolution - 1)
    y0 = np.clip(np.floor(ty.min(axis=1)).astype(np.int64), 0, resolution - 1)
    y1 = np.clip(np.ceil(ty.max(axis=1)).astype(np.int64) - 1, 0, resolution - 1)

    width = (x1 - x0 + 1).astype(np.int64)
    height = (y1 - y0 + 1).astype(np.int64)
    counts = width * height

    # The triangles are done in chunks so that a mesh with a few very large
    # triangles cannot ask for the whole expansion at once.
    order = np.argsort(counts, kind="stable")
    cumulative = np.cumsum(counts[order])
    start = 0
    while start < triangles.shape[0]:
        limit = int(cumulative[start - 1]) if start else 0
        end = int(np.searchsorted(cumulative, limit + _SAMPLE_BUDGET, side="right"))
        if end <= start:
            end = start + 1
        chunk = order[start:end]
        start = end

        _rasterise_chunk(mask, px, py, triangles[chunk], x0[chunk], x1[chunk],
                         y0[chunk], y1[chunk], width[chunk], height[chunk],
                         counts[chunk])

    return _fill_from_outside(mask)


def _fill_from_outside(mask: np.ndarray) -> np.ndarray:
    """The cells the outside cannot reach — the filled silhouette.

    The flood starts at the grid's border and spreads through the cells the
    surface did not mark, one cell at a time. What it cannot reach is
    inside the silhouette. The iteration is a dilation, so it is numpy
    rather than a Python queue: the worst case is one pass per cell of
    depth, and each pass is a handful of shifts over the grid.

    **A silhouette that covers the whole border has no way in.** A square
    frame — a shelf rack seen from the front — marks every cell on the
    grid's edge, so there is no free border cell to start from and the
    result is the whole grid, holes included. That is the safe direction:
    the occupied region is over-estimated, so an object reads as fuller
    than it is and is judged more ordinary, not less.
    """
    if not mask.any():
        return mask

    border = np.zeros_like(mask)
    border[0, :] = True
    border[-1, :] = True
    border[:, 0] = True
    border[:, -1] = True

    reached = border & ~mask
    free = ~mask
    while True:
        grown = reached.copy()
        grown[1:, :] |= reached[:-1, :]
        grown[:-1, :] |= reached[1:, :]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= free
        if grown.sum() == reached.sum():
            break
        reached = grown

    return ~reached


def _rasterise_chunk(
    mask: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
    triangles: np.ndarray,
    x0: np.ndarray,
    x1: np.ndarray,
    y0: np.ndarray,
    y1: np.ndarray,
    width: np.ndarray,
    height: np.ndarray,
    counts: np.ndarray,
) -> None:
    """Mark the cells whose centre falls inside one of the triangles."""
    total = int(counts.sum())
    if total == 0:
        return

    triangle = np.repeat(np.arange(triangles.shape[0]), counts)
    starts = np.cumsum(counts) - counts
    within = np.arange(total, dtype=np.int64) - np.repeat(starts, counts)
    span = np.repeat(width, counts)
    cell_x = np.repeat(x0, counts) + within % span
    cell_y = np.repeat(y0, counts) + within // span

    # The cell centres, in the projected plane's own units.
    qx = (cell_x + 0.5)
    qy = (cell_y + 0.5)

    ax = px[triangles[:, 0]][triangle]
    ay = py[triangles[:, 0]][triangle]
    bx = px[triangles[:, 1]][triangle]
    by = py[triangles[:, 1]][triangle]
    cx = px[triangles[:, 2]][triangle]
    cy = py[triangles[:, 2]][triangle]

    # The three edge functions: each is twice the signed area of the
    # triangle made by the point and the opposite edge.
    e0 = (bx - qx) * (cy - qy) - (cx - qx) * (by - qy)
    e1 = (cx - qx) * (ay - qy) - (ax - qx) * (cy - qy)
    e2 = (ax - qx) * (by - qy) - (bx - qx) * (ay - qy)
    winding = e0 + e1 + e2

    inside = (e0 * winding >= 0.0) & (e1 * winding >= 0.0) & (e2 * winding >= 0.0)
    inside &= winding != 0.0

    mask[cell_y[inside], cell_x[inside]] = True
