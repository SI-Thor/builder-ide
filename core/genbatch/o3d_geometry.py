"""The Open3D-backed geometry: the three uses the sweep adopted, no more.

``docs/lab/exp-open3d-critic.md`` measured Open3D 0.20 against the critic's
own kernels on 45 meshes (7.41 M triangles) and found the shared quantities
identical to 4.4e-15 — so there is nothing to re-fit, and nothing here
replaces a measurement. What the critic adopts is what it lacked:

* :func:`self_intersection` — the only check that can see two triangles
  occupying the same space. 34 of the 38 reference meshes self-intersect,
  11 of them closed, and their signed volume counts the overlapped material
  twice (the worst reads 3.9x its ray-parity volume).
* :func:`parity_volume` — a volume that needs no closure and no winding:
  a ray leaves an inside cell after an odd number of crossings. It answers
  on meshes the divergence theorem is nonsense on, in median 18 ms.
* :func:`quadric_diet` — quadric decimation for mesh diet and LODs. Never
  for re-measuring: the diet opened 14 of the 19 closed meshes in the
  sweep, so a verdict read on a dieted mesh is a verdict about the diet.

The dependency rides as the ``o3d`` extra, pinned ``open3d==0.20.0``: that
is the only release with a cp312 aarch64 wheel, so the pin is
load-bearing. Every read here answers ``unchecked`` or ``None`` when the
wheel is absent — the critic still runs, and its report says what it did
not measure rather than guessing.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel

from core.genbatch.glb import Mesh

__all__ = [
    "SELF_INTERSECTION_CAP",
    "SelfIntersection",
    "open3d_available",
    "parity_volume",
    "quadric_diet",
    "self_intersection",
]

#: The triangle count above which the self-intersection check declines to
#: answer. From the sweep's own timing: below 200 k triangles the check is
#: affordable on the critic's path (median 0.16 s, max 18.5 s, n = 34);
#: above it the tail is unbounded (801 s at 1.33 M, 596 s at 1 M —
#: docs/lab/exp-open3d-critic.md §3.1). The cap is a measurement, not a
#: scaling model.
SELF_INTERSECTION_CAP = 200_000

#: The probe cache for the wheel: ``False`` = not probed yet, ``None`` =
#: absent, the module = present. Probed lazily so importing this module
#: costs nothing when the extra is not installed.
_O3D: Any = False


def _open3d() -> Any:
    """The open3d module, or ``None`` when the wheel is not installed."""
    global _O3D
    if _O3D is False:
        try:
            import open3d as module

            _O3D = module
        except ImportError:
            _O3D = None
    return _O3D


def open3d_available() -> bool:
    """Is the ``o3d`` extra installed on this box?"""
    return _open3d() is not None


def to_o3d(positions: np.ndarray, indices: np.ndarray) -> Any:
    """The same mesh as Open3D sees it — identical arrays, no reader.

    The sweep's own conversion: whatever the numbers say below was said to
    a mesh built this way, so the critic builds it the same way.
    """
    open3d = _open3d()
    return open3d.geometry.TriangleMesh(
        open3d.utility.Vector3dVector(
            np.ascontiguousarray(positions, dtype=np.float64)
        ),
        open3d.utility.Vector3iVector(
            np.ascontiguousarray(indices, dtype=np.int32)
        ),
    )


class SelfIntersection(BaseModel):
    """The self-intersection verdict, and what it is a verdict about.

    ``state`` is one of:

    * ``"clean"`` — no two triangles of the mesh cross;
    * ``"self_intersecting"`` — at least one pair does (``pairs`` says how
      many were found);
    * ``"unchecked"`` — the question was not answered, and ``reason`` says
      why (the wheel is absent, the mesh is over the triangle cap, or the
      mesh has no triangles at all).
    """

    state: Literal["clean", "self_intersecting", "unchecked"] = "unchecked"
    #: How many pairs of crossing triangles were found — counted only when
    #: there are any, because the count re-runs the check.
    pairs: int = 0
    #: The triangles of the mesh the verdict is about.
    checked_triangles: int = 0
    #: Why the check declined, when it declined.
    reason: str = ""


def self_intersection(
    mesh: Mesh, *, cap: int | None = SELF_INTERSECTION_CAP
) -> SelfIntersection:
    """Do any two triangles of the mesh cross each other?

    Above ``cap`` triangles the verdict is ``unchecked``, not a decimated
    stand-in: the check's cost above the cap is why the cap exists (801 s
    at 1.33 M triangles), and a quadric stand-in would be a verdict about
    a different mesh — the diet opened 14 of 19 closed meshes in the sweep
    (§3.5), so it can both hide and create crossings. An unanswered
    question stays unanswered.

    ``cap=None`` disables the check outright (the caller that wants the
    pre-Open3D measurement back).
    """
    open3d = _open3d()
    if open3d is None:
        return SelfIntersection(reason="open3d is not installed — the o3d extra")
    if mesh.triangles == 0:
        return SelfIntersection(reason="the mesh has no triangles")
    if cap is None:
        return SelfIntersection(
            checked_triangles=mesh.triangles,
            reason="the check was not asked for",
        )
    if mesh.triangles > cap:
        return SelfIntersection(
            checked_triangles=mesh.triangles,
            reason=(
                f"{mesh.triangles:,} triangles is over the {cap:,}-triangle "
                "cap; the check's cost is unbounded above it and a decimated "
                "stand-in would be a verdict about a different mesh "
                "(docs/lab/exp-open3d-critic.md §3.1, §3.5)"
            ),
        )
    open3d_mesh = to_o3d(mesh.positions, mesh.indices)
    if not open3d_mesh.is_self_intersecting():
        return SelfIntersection(state="clean", checked_triangles=mesh.triangles)
    # The pair count re-runs the check inside, so it is only asked for when
    # the answer is yes and the number has something to report.
    pairs = len(open3d_mesh.get_self_intersecting_triangles())
    return SelfIntersection(
        state="self_intersecting",
        pairs=pairs,
        checked_triangles=mesh.triangles,
    )


def parity_volume(mesh: Mesh, *, resolution: int = 64) -> float | None:
    """The **enclosed** volume, by ray parity, needing no winding.

    A ray is cast from every cell centre of the same grid the occupancy
    measure uses (``resolution`` cells along the longest axis) along +z; a
    cell is inside when the crossings ahead of it are odd. That is the
    divergence theorem asked of a rasteriser: it answers on meshes the
    signed volume is nonsense on — open, flipped, self-intersecting — and
    on a closed self-intersecting mesh it is the conservative number (it
    does not count overlapped material twice).

    It is an interior measure, not an envelope: the hollow mug reads its
    ceramic, not the cylinder it occupies. ``None`` when the wheel is
    absent or the mesh has no size.

    The semantics are the sweep's ``raycast_interior``
    (``docs/lab/open3d-critic/compare.py``), kept identical so the numbers
    line up with the report.
    """
    open3d = _open3d()
    if open3d is None or mesh.triangles == 0:
        return None
    legacy = to_o3d(mesh.positions, mesh.indices)
    lo = np.asarray(legacy.get_min_bound(), dtype=np.float64)
    extent = np.asarray(legacy.get_max_bound(), dtype=np.float64) - lo
    longest = float(np.max(extent))
    if longest <= 0.0:
        return None
    cell = longest / resolution
    counts = np.maximum(np.ceil(extent / cell).astype(int), 1)

    centres_x = lo[0] + (np.arange(counts[0]) + 0.5) * cell
    centres_y = lo[1] + (np.arange(counts[1]) + 0.5) * cell
    centres_z = lo[2] + (np.arange(counts[2]) + 0.5) * cell
    gx, gy, gz = np.meshgrid(centres_x, centres_y, centres_z, indexing="ij")
    origins = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    from open3d.t.geometry import RaycastingScene

    scene = RaycastingScene()
    scene.add_triangles(open3d.t.geometry.TriangleMesh.from_legacy(legacy))
    direction = np.tile(
        np.array([0.0, 0.0, 1.0], dtype=np.float32), (origins.shape[0], 1)
    )

    crossings = np.empty(origins.shape[0], dtype=np.int64)
    chunk = 1 << 16
    for start in range(0, origins.shape[0], chunk):
        stop = start + chunk
        rays = open3d.core.Tensor(
            np.concatenate(
                [origins[start:stop].astype(np.float32), direction[start:stop]],
                axis=1,
            )
        )
        crossings[start:stop] = scene.count_intersections(rays).numpy()
    inside = int(np.count_nonzero(crossings % 2 == 1))
    return float(inside * cell**3)


def quadric_diet(
    mesh: Mesh, *, fraction: float = 0.1, min_triangles: int = 1
) -> Mesh:
    """The mesh decimated to a fraction of its triangles, by quadric error.

    For mesh diet and LODs — display and storage — **never** for
    re-measuring: the diet opened 14 of the 19 closed meshes in the sweep,
    so watertightness and volume read on a dieted mesh are properties of
    the diet. ``min_triangles`` is the floor, so a small prop cannot be
    decimated to nothing (the sweep's 12-triangle cube collapsed to 0
    triangles at a target of 1).

    Raises ``RuntimeError`` when the wheel is absent: a step that was
    asked for is a step that has to run.
    """
    open3d = _open3d()
    if open3d is None:
        raise RuntimeError("the diet stage needs open3d — the o3d extra")
    if mesh.triangles == 0:
        return mesh
    target = max(min_triangles, int(round(mesh.triangles * fraction)))
    target = min(target, mesh.triangles)
    simple = to_o3d(mesh.positions, mesh.indices).simplify_quadric_decimation(
        target
    )
    positions = np.asarray(simple.vertices, dtype=np.float64).reshape(-1, 3)
    indices = np.asarray(simple.triangles, dtype=np.int64).reshape(-1, 3)
    return Mesh(positions=positions, indices=indices)
