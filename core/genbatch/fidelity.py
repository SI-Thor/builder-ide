"""How much of the prop survived the repair: the silhouette IoU.

A repair that makes a prop watertight can still ruin it — a voxel remesh at
the wrong resolution rounds a lantern into a blob, and a hole fill that bulges
outwards changes what the prop looks like. The number that catches that is
the **silhouette IoU**: the overlap between the object's outline before the
repair and after it, seen from several directions.

The silhouette of a mesh is the union of the projections of its surface onto
the view plane. It can be measured without a renderer: sample the surface,
project the samples, and splat them into a pixel grid. The grid that fills in
is the object's outline; the overlap of two grids is the IoU.

**The grid has to be sampled densely enough, or the measure is noise.** A
silhouette of 40 k pixels drawn with 200 k samples leaves a third of the
pixels unhit, and which pixels those are depends on the order the triangles
happen to be in: two meshes with *identical* geometry scored an IoU of 0.51
that way. The fix is samples per pixel, not samples: at 128 × 128 with a
million samples every pixel of the outline is covered many times over, and
the same mesh measured against itself scores 1.000000 whatever order its
triangles are in. Both are checked in the tests.

Three more things make it reproducible rather than noisy:

* the sampling is **area-weighted** over the triangles, so the density on the
  surface is uniform and a dense patch does not get more samples than a flat
  one;
* the seed is fixed, so the same mesh always gives the same silhouette;
* the mesh is fitted to the **same bounding box** in both pictures, so a
  repair that shrinks or grows the prop is measured, not hidden.
"""

from __future__ import annotations

import numpy as np

from core.genbatch.glb import Mesh

__all__ = [
    "VIEWS",
    "sample_count",
    "sample_surface",
    "silhouette",
    "silhouette_iou",
    "silhouettes",
]

#: The views the fidelity check looks from: (right, up, towards). Six
#: axis-aligned directions — enough to catch a repair that flattens or
#: shears the prop, cheap enough to run on every prop of a night.
VIEWS: dict[str, tuple[tuple[float, float, float], ...]] = {
    "+x": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "-x": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
    "+y": ((1, 0, 0), (0, 0, 1), (0, 1, 0)),
    "-y": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "+z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-z": ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
}


def sample_surface(
    positions: np.ndarray,
    indices: np.ndarray,
    count: int,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample points on a mesh's surface, and the normal of each one.

    The points are drawn area-weighted over the triangles and uniformly
    inside their triangle, so the density on the surface is uniform.
    """
    if indices.shape[0] == 0:
        raise ValueError("the mesh has no triangles to sample")
    rng = np.random.default_rng(seed)
    a = positions[indices[:, 0]]
    b = positions[indices[:, 1]]
    c = positions[indices[:, 2]]
    cross = np.cross(b - a, c - a)
    twice_area = np.linalg.norm(cross, axis=1)
    total = float(twice_area.sum())
    if total <= 0:
        raise ValueError("the mesh has no area to sample")
    # Which triangle each sample lands on, drawn with a probability
    # proportional to the triangle's area. The cumulative distribution is
    # searched rather than drawn through ``multinomial``, which builds an
    # array as big as the sample count times the triangle count.
    cumulative = np.cumsum(twice_area / total)
    cumulative[-1] = 1.0
    triangle = np.searchsorted(cumulative, rng.random(count), side="right")
    triangle = np.clip(triangle, 0, indices.shape[0] - 1)
    u = rng.random(triangle.size)
    v = rng.random(triangle.size)
    flip = u + v > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    points = (
        a[triangle] * (1.0 - u - v)[:, None]
        + b[triangle] * u[:, None]
        + c[triangle] * v[:, None]
    )
    normals = cross[triangle] / np.maximum(twice_area[triangle], 1e-300)[:, None]
    return points, normals


def _frame(
    bounds: tuple[np.ndarray, np.ndarray], view: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float, float, float]:
    """The view's axes and the rectangle the bounding box covers in it."""
    right, up, towards = (np.asarray(v, dtype=np.float64) for v in VIEWS[view])
    lo, hi = bounds
    corners = np.array(
        [
            [x, y, z]
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])
        ]
    )
    us = corners @ right
    vs = corners @ up
    return (
        right,
        up,
        towards,
        float(us.min()),
        float(us.max()),
        float(vs.min()),
        float(vs.max()),
    )


def sample_count(triangles: int, cap: int, resolution: int = 128) -> int:
    """How many samples to draw for a mesh of this size.

    What the silhouette needs is **samples per pixel**, not samples: a pixel
    of the outline is covered by a fraction of a triangle, so it is only
    reliably hit if enough samples land near it. Twenty samples for every
    pixel of the grid is enough for the boundary pixels to stop flickering;
    the cap is the recipe's, and a mesh with more triangles than that gets
    sampled in proportion to its own detail.

    A mesh is only ever measured against itself, so the count is a function
    of the mesh and the recipe — the same pair always gives the same number.
    """
    by_pixels = 20 * resolution * resolution
    by_detail = 4 * triangles
    return int(min(cap, max(by_pixels, by_detail)))


def _mask(
    points: np.ndarray,
    view: str,
    resolution: int,
    bounds: tuple[np.ndarray, np.ndarray],
) -> np.ndarray:
    """The pixels a set of surface points covers from one view."""
    right, up, _towards, u_min, u_max, v_min, v_max = _frame(bounds, view)
    u = (points @ right - u_min) / max(u_max - u_min, 1e-12)
    v = (points @ up - v_min) / max(v_max - v_min, 1e-12)
    x = np.clip((u * (resolution - 1)).astype(np.int64), 0, resolution - 1)
    y = np.clip((v * (resolution - 1)).astype(np.int64), 0, resolution - 1)
    mask = np.zeros(resolution * resolution, dtype=bool)
    mask[y * resolution + x] = True
    return mask.reshape(resolution, resolution)


def silhouette(
    mesh: Mesh,
    view: str,
    resolution: int = 128,
    samples: int = 1_000_000,
    seed: int = 7,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """One view's silhouette of a mesh, as a boolean pixel grid."""
    if bounds is None:
        bounds = (mesh.positions.min(axis=0), mesh.positions.max(axis=0))
    count = sample_count(mesh.indices.shape[0], samples, resolution)
    points, _ = sample_surface(mesh.positions, mesh.indices, count, seed=seed)
    return _mask(points, view, resolution, bounds)


def silhouettes(
    mesh: Mesh,
    views: tuple[str, ...] = ("+x", "+y", "+z"),
    resolution: int = 128,
    samples: int = 1_000_000,
    seed: int = 7,
) -> dict[str, np.ndarray]:
    """The silhouettes of a mesh from several views, on a shared bounding box.

    The bounding box is the mesh's own, so two meshes measured this way are
    compared in the same frame — a repair that resizes the prop shows up.
    The surface is sampled once and projected into every view.
    """
    bounds = (mesh.positions.min(axis=0), mesh.positions.max(axis=0))
    count = sample_count(mesh.indices.shape[0], samples, resolution)
    points, _ = sample_surface(mesh.positions, mesh.indices, count, seed=seed)
    return {view: _mask(points, view, resolution, bounds) for view in views}


def silhouette_iou(
    before: Mesh,
    after: Mesh,
    views: tuple[str, ...] = ("+x", "+y", "+z"),
    resolution: int = 128,
    samples: int = 1_000_000,
    seed: int = 7,
) -> float:
    """How much of the prop's outline survived a repair.

    The IoU of the silhouettes, averaged over the views. 1.0 means the repair
    changed nothing a camera could see.
    """
    # One shared frame for both meshes: the before-mesh's box.
    bounds = (before.positions.min(axis=0), before.positions.max(axis=0))
    count = sample_count(before.indices.shape[0], samples, resolution)
    before_points, _ = sample_surface(before.positions, before.indices, count, seed=seed)
    after_points, _ = sample_surface(after.positions, after.indices, count, seed=seed)
    scores: list[float] = []
    for view in views:
        first = _mask(before_points, view, resolution, bounds)
        second = _mask(after_points, view, resolution, bounds)
        union = int(np.count_nonzero(first | second))
        if union == 0:
            continue
        scores.append(float(np.count_nonzero(first & second)) / union)
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))
