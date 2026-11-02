"""Compare Open3D's geometry answers with the critic's own, per mesh.

**What this measures.** For every mesh in the critic's reference set (the 38
SimReady assets the plausibility prior was fitted on), five fresh SimReady
packages the prior never saw (``fetch_extra_samples.py``), and two controls
whose volumes are written down (a unit cube and the hollow mug), both stacks
answer the same questions on the **same vertex and index arrays**:

* **watertight** — the critic's edge census (`core.genbatch.mesh`) against
  Open3D's `is_watertight`; the two words mean different things (closed
  versus valid solid boundary — Open3D also demands vertex-manifoldness
  and no self-intersections), so both sides' parts are recorded beside
  the flag;
* **volume** — the divergence-theorem signed volume both sides, Open3D's
  `get_volume` only answering where it believes the mesh is closed;
* **occupancy** — the critic's convex-hull envelope (scipy) against Open3D's
  hull, the critic's ``visual`` measure against the same semantic on
  Open3D's voxel grid (the intersection of the three axis projections),
  and Open3D's **ray-parity interior**
  (`t.geometry.RaycastingScene.count_intersections`) as a winding-free
  enclosed volume — a different quantity (the material, not the space),
  kept because a rasteriser that answers it without the winding is
  something the critic's divergence theorem cannot do;
* **self-intersection** — Open3D's `is_self_intersecting`; the critic has no
  equivalent today, so the column is a capability, not a comparison;
* **simplification** — Open3D's quadric decimation to 10 % of the triangles,
  timed, with the watertight flag and the volume drift it leaves behind.

The GLB reading is compared too, on the whole file: the critic's
whole-asset reader (`Glb.asset`) against `o3d.io.read_triangle_mesh` — the
multi-primitive question (a reader that stops at the first primitive
measures a fragment of the forklift).

**Usage** (the worktree's venv, which holds open3d and the critic's own
dependencies)::

    ~/lm-wt/open3d-critic/.venv/bin/python docs/lab/open3d-critic/compare.py
    ~/lm-wt/open3d-critic/.venv/bin/python docs/lab/open3d-critic/compare.py --quick

Writes ``results/results.json`` beside this file and prints one line per
mesh as it goes. CPU-only; peak RSS is recorded in the result.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import open3d as o3d  # noqa: E402

from core.genbatch.glb import Mesh, read_glb  # noqa: E402
from core.genbatch.mesh import measure_mesh  # noqa: E402
from core.genbatch.occupancy import occupied  # noqa: E402

#: Where the reference GLBs and the five extras live.
GLB_DIR = Path.home() / "lm-wt" / "simready-survey" / "data" / "glb"
EXTRA_DIR = Path.home() / "lm-wt" / "simready-survey" / "data" / "glb-extra"
REFERENCE_JSON = REPO / "core" / "genbatch" / "simready-reference.json"

#: The critic's occupancy grid: 64 cells along the longest axis.
RESOLUTION = 64

#: The simplification target, as a share of the mesh's triangles.
SIMPLIFY_TO = 0.10


def box_state() -> dict:
    memory = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    memory[key] = int(rest.split()[0]) * 1024
    except OSError:
        pass
    import os

    return {
        "machine": "NVIDIA Jetson AGX Thor, aarch64, 14 Neoverse cores",
        "kernel": platform.release(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "open3d": o3d.__version__,
        "load_average": [round(v, 2) for v in os.getloadavg()],
        "mem_available_gb": round(memory.get("MemAvailable", 0) / 1024**3, 1),
        "mem_total_gb": round(memory.get("MemTotal", 0) / 1024**3, 1),
    }


def rss_peak_mb() -> float:
    try:
        for line in open("/proc/self/status", encoding="utf-8"):
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def rel_diff(a: float | None, b: float | None) -> float | None:
    """|a − b| / max(|a|, |b|), or None when either side is missing."""
    if a is None or b is None:
        return None
    scale = max(abs(a), abs(b))
    if scale == 0.0:
        return 0.0
    return abs(a - b) / scale


def to_o3d(positions: np.ndarray, indices: np.ndarray) -> o3d.geometry.TriangleMesh:
    """The same mesh, as Open3D sees it — identical arrays, no reader."""
    mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.ascontiguousarray(positions, dtype=np.float64)),
        o3d.utility.Vector3iVector(np.ascontiguousarray(indices, dtype=np.int32)),
    )
    return mesh


def hull_volume(mesh: o3d.geometry.TriangleMesh) -> tuple[float, float]:
    """The convex hull's volume, and the seconds it took.

    The hull mesh Open3D returns inherits the input's duplicated vertices,
    which can leave unreferenced points and degenerate faces — enough for
    Open3D's own watertight flag to refuse `get_volume`. The hull is convex
    and closed by construction, so after a cleanup pass the volume is read
    by Open3D, and if it still refuses, by the divergence theorem over the
    hull's own triangles.
    """
    started = time.perf_counter()
    result = mesh.compute_convex_hull()
    hull = result[0] if isinstance(result, tuple) else result
    hull.remove_duplicated_vertices()
    hull.remove_degenerate_triangles()
    hull.remove_unreferenced_vertices()
    try:
        volume = float(hull.get_volume())
    except RuntimeError:
        vertices = np.asarray(hull.vertices, dtype=np.float64)
        triangles = np.asarray(hull.triangles, dtype=np.int64)
        a, b, c = (vertices[triangles[:, i]] for i in range(3))
        volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    return abs(volume), time.perf_counter() - started


def grid_visual_hull(mesh: o3d.geometry.TriangleMesh) -> tuple[float, int, float]:
    """The **visual hull** on Open3D's voxel grid, at RESOLUTION cells along
    the longest axis — the critic's own occupancy semantic, rasterised.

    The occupied volume the critic wants is the visual hull: every cell
    whose projection falls inside the object's silhouette along all three
    axes (the cup's void counts — the mug *occupies* its cylinder). Two
    Open3D-native readings that sound like the answer are not it, and both
    were measured before saying so: ray parity gives the **enclosed solid**
    (the ceramic, not the cylinder), and reachability of the surface voxel
    grid gives the **sealed regions** (the cup is open to the sky, so a
    real mug reads −53 % — that dead end is in the report). This function
    takes the surface voxels Open3D's `VoxelGrid` marks and intersects
    their three axis projections — the same shape as the critic's
    ``visual`` measure, on Open3D's rasteriser.
    """
    lo = np.asarray(mesh.get_min_bound(), dtype=np.float64)
    extent = np.asarray(mesh.get_max_bound(), dtype=np.float64) - lo
    longest = float(np.max(extent))
    if longest <= 0.0:
        return 0.0, 0, 0.0
    cell = longest / RESOLUTION
    counts = np.maximum(np.ceil(extent / cell).astype(int), 1)

    started = time.perf_counter()
    grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh(mesh, voxel_size=cell)
    surface = np.zeros(tuple(counts), dtype=bool)
    for voxel in grid.get_voxels():
        # A sample exactly on the max bound lands one past the last cell
        # (floor(extent/cell) == counts); clip it back onto the boundary
        # layer, or that face's silhouette is one cell short.
        index = np.clip(np.asarray(voxel.grid_index), 0, counts - 1)
        surface[tuple(index)] = True

    silhouette_xy = surface.any(axis=2)  # looking along z
    silhouette_xz = surface.any(axis=1)  # looking along y
    silhouette_yz = surface.any(axis=0)  # looking along x
    hull = silhouette_xy[:, :, None] & silhouette_xz[:, None, :] & silhouette_yz[None, :, :]
    seconds = time.perf_counter() - started
    cells = int(np.count_nonzero(hull))
    return cells * cell**3, cells, seconds


def raycast_interior(mesh: o3d.geometry.TriangleMesh) -> tuple[float, int, float]:
    """The **enclosed solid** at RESOLUTION cells, by ray parity — the
    same grid the critic's occupancy uses.

    A ray is cast from every cell centre along +z through Open3D's
    raycasting scene (`t.geometry.RaycastingScene.count_intersections`);
    a cell is inside when the crossings ahead of it are odd. This is the
    divergence-theorem volume asked of a rasteriser: it needs no winding
    and no orientation, so it still answers on a mesh whose triangles are
    flipped — but on a thin closed sheet (a door skin, a mug wall) it
    measures the material, not the space the object takes up. It is an
    **interior** measure, not an envelope; the envelope is
    :func:`voxel_envelope`.
    """
    from open3d.t.geometry import RaycastingScene

    lo = np.asarray(mesh.get_min_bound(), dtype=np.float64)
    extent = np.asarray(mesh.get_max_bound(), dtype=np.float64) - lo
    longest = float(np.max(extent))
    if longest <= 0.0:
        return 0.0, 0, 0.0
    cell = longest / RESOLUTION
    counts = np.maximum(np.ceil(extent / cell).astype(int), 1)

    centres_x = lo[0] + (np.arange(counts[0]) + 0.5) * cell
    centres_y = lo[1] + (np.arange(counts[1]) + 0.5) * cell
    centres_z = lo[2] + (np.arange(counts[2]) + 0.5) * cell
    gx, gy, gz = np.meshgrid(centres_x, centres_y, centres_z, indexing="ij")
    origins = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    tmesh = o3d.t.geometry.TriangleMesh.from_legacy(mesh)
    scene = RaycastingScene()
    scene.add_triangles(tmesh)
    direction = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (origins.shape[0], 1))

    started = time.perf_counter()
    crossings = np.empty(origins.shape[0], dtype=np.int64)
    chunk = 1 << 16
    for start in range(0, origins.shape[0], chunk):
        stop = start + chunk
        rays = o3d.core.Tensor(
            np.concatenate([origins[start:stop].astype(np.float32), direction[start:stop]],
                           axis=1))
        crossings[start:stop] = scene.count_intersections(rays).numpy()
    seconds = time.perf_counter() - started
    inside = int(np.count_nonzero(crossings % 2 == 1))
    return inside * cell**3, inside, seconds


def measure_one(name: str, group: str, mesh: Mesh, path: str | None) -> dict:
    """Both stacks' answers for one mesh, on the same arrays."""
    positions = np.asarray(mesh.positions, dtype=np.float64)
    indices = np.asarray(mesh.indices, dtype=np.int64)
    o3d_mesh = to_o3d(positions, indices)

    row: dict = {"name": name, "group": group, "path": path,
                 "triangles": int(indices.shape[0]),
                 "vertices": int(positions.shape[0])}

    # -- the critic's own pass: topology, signed volume, occupancy ---------
    started = time.perf_counter()
    report = measure_mesh(mesh)
    ours_mesh_seconds = time.perf_counter() - started
    occ = occupied(mesh, "convex", resolution=RESOLUTION)
    occ_visual = occupied(mesh, "visual", resolution=RESOLUTION)
    box_volume = float(np.prod(np.asarray(report.extent, dtype=np.float64)))

    # -- Open3D's answers ---------------------------------------------------
    # The self-intersection test is the expensive one here (~80 s on a
    # 300 k-triangle mesh under load), and Open3D's is_watertight runs it
    # again inside, as does get_volume on every call. It is computed once,
    # and the watertight flag derived from the definition Open3D's own
    # source states and this box verified on a closed, self-intersecting
    # mesh: edge-manifold AND vertex-manifold AND not self-intersecting.
    started = time.perf_counter()
    self_intersecting = bool(o3d_mesh.is_self_intersecting())
    selfx_seconds = time.perf_counter() - started
    o3d_edge_manifold = bool(o3d_mesh.is_edge_manifold(allow_boundary_edges=False))
    o3d_vertex_manifold = bool(o3d_mesh.is_vertex_manifold())
    o3d_orientable = bool(o3d_mesh.is_orientable())
    o3d_watertight = o3d_edge_manifold and o3d_vertex_manifold and not self_intersecting
    o3d_topo_seconds = time.perf_counter() - started

    o3d_volume: float | None = None
    if o3d_watertight:
        # get_volume re-runs the watertight check inside (another
        # self-intersection pass); only closed meshes pay it, and they are
        # the few.
        try:
            o3d_volume = float(o3d_mesh.get_volume())
        except RuntimeError:
            o3d_volume = None
    o3d_area = float(o3d_mesh.get_surface_area())

    o3d_hull_volume, o3d_hull_seconds = hull_volume(o3d_mesh)
    o3d_ray_volume, o3d_ray_cells, o3d_ray_seconds = raycast_interior(o3d_mesh)
    o3d_grid_volume, o3d_grid_cells, o3d_grid_seconds = grid_visual_hull(o3d_mesh)

    # -- quadric simplification to 10 % -------------------------------------
    target = max(1, int(round(SIMPLIFY_TO * row["triangles"])))
    started = time.perf_counter()
    simple = o3d_mesh.simplify_quadric_decimation(target)
    simplify_seconds = time.perf_counter() - started
    simple_volume = None
    try:
        simple_volume = float(simple.get_volume())
    except RuntimeError:
        simple_volume = None

    row["topology"] = {
        "ours": {"watertight": bool(report.watertight),
                 "boundary_edges": report.boundary_edges,
                 "nonmanifold_edges": report.nonmanifold_edges,
                 "consistent_winding": bool(report.consistent_winding),
                 "degenerate_triangles": report.degenerate_triangles,
                 "seconds": round(ours_mesh_seconds, 4)},
        "o3d": {"watertight": o3d_watertight,
                "edge_manifold_closed": o3d_edge_manifold,
                "vertex_manifold": o3d_vertex_manifold,
                "orientable": o3d_orientable,
                "seconds": round(o3d_topo_seconds, 4)},
        # Two different questions: ours asks "is every edge used exactly
        # twice" (closed); Open3D additionally demands vertex-manifoldness
        # and no self-intersections (a valid solid boundary).
        "watertight_agrees": bool(report.watertight) == o3d_watertight,
    }
    row["volume"] = {
        "ours_signed": report.volume,
        "o3d_get_volume": o3d_volume,
        "rel_diff": rel_diff(report.volume, o3d_volume),
        "ours_area": report.area,
        "o3d_area": o3d_area,
        "area_rel_diff": rel_diff(report.area, o3d_area),
    }
    row["occupancy"] = {
        "box_volume": box_volume,
        "ours_convex": occ.volume,
        "ours_convex_seconds": round(occ.seconds, 4),
        "o3d_hull": o3d_hull_volume,
        "o3d_hull_seconds": round(o3d_hull_seconds, 4),
        "hull_rel_diff": rel_diff(occ.volume, o3d_hull_volume),
        "o3d_raycast_interior": o3d_ray_volume,
        "o3d_raycast_cells": o3d_ray_cells,
        "o3d_raycast_seconds": round(o3d_ray_seconds, 4),
        "ours_visual": occ_visual.volume,
        "ours_visual_seconds": round(occ_visual.seconds, 4),
        "o3d_grid_visual": o3d_grid_volume,
        "o3d_grid_seconds": round(o3d_grid_seconds, 4),
        "visual_rel_diff": rel_diff(occ_visual.volume, o3d_grid_volume),
        "fill_ratio_ours": occ.volume / box_volume if box_volume > 0 else None,
        "fill_ratio_grid_visual": o3d_grid_volume / box_volume if box_volume > 0 else None,
    }
    row["self_intersection"] = {
        "o3d": self_intersecting, "o3d_seconds": round(selfx_seconds, 4),
        "ours": None,  # the critic has no self-intersection check today
    }
    row["simplify"] = {
        "target": target,
        "out_triangles": len(simple.triangles),
        "seconds": round(simplify_seconds, 4),
        "watertight_after": bool(simple.is_watertight()),
        "volume_after": simple_volume,
        "volume_rel_drift": rel_diff(o3d_volume, simple_volume),
    }
    return row


def read_and_compare(name: str, group: str, path: Path, recorded: dict | None) -> dict:
    """Read the GLB both ways, then measure on the critic's own arrays."""
    started = time.perf_counter()
    mesh = read_glb(path).asset
    ours_read_seconds = time.perf_counter() - started

    started = time.perf_counter()
    o3d_read = o3d.io.read_triangle_mesh(str(path))
    o3d_read_seconds = time.perf_counter() - started

    row = measure_one(name, group, mesh, str(path))
    read_o3d_tris = len(o3d_read.triangles)
    ours_positions = np.asarray(mesh.positions, dtype=np.float64)
    o3d_positions = np.asarray(o3d_read.vertices, dtype=np.float64)
    if o3d_positions.size and ours_positions.size:
        bbox_gap = float(np.max(np.abs(
            np.stack([ours_positions.min(axis=0), ours_positions.max(axis=0)])
            - np.stack([o3d_positions.min(axis=0), o3d_positions.max(axis=0)]))))
    else:
        bbox_gap = None
    row["read"] = {
        "ours_seconds": round(ours_read_seconds, 4),
        "o3d_seconds": round(o3d_read_seconds, 4),
        "ours_triangles": row["triangles"],
        "o3d_triangles": read_o3d_tris,
        "triangles_agree": read_o3d_tris == row["triangles"],
        "o3d_vertices": len(o3d_read.vertices),
        "bbox_max_gap": bbox_gap,
        "o3d_reader_watertight": bool(o3d_read.is_watertight()) if read_o3d_tris else None,
        "ours_reader_watertight": row["topology"]["ours"]["watertight"],
    }
    if recorded is not None:
        row["reference_agreement"] = {
            "recorded_signed_volume": recorded.get("signed_volume"),
            "signed_rel_diff": rel_diff(
                row["volume"]["ours_signed"], recorded.get("signed_volume")),
            "recorded_occupied_volume": recorded.get("occupied_volume"),
            "occupied_rel_diff": rel_diff(
                row["occupancy"]["ours_convex"], recorded.get("occupied_volume")),
            "recorded_watertight": recorded.get("watertight"),
            "watertight_agrees": (
                recorded.get("watertight") == row["topology"]["ours"]["watertight"]),
        }
    return row


def control_rows() -> list[dict]:
    """The two controls whose volumes can be written down."""
    from tests.genbatch.glb_fixtures import cube_mesh, mug_mesh

    rows = []
    cube_positions, cube_indices = cube_mesh()
    cube = measure_one(
        "control-cube", "control",
        Mesh(positions=np.asarray(cube_positions, dtype=np.float64),
             indices=np.asarray(cube_indices, dtype=np.int64).reshape(-1, 3)),
        None)
    cube["analytic"] = {"occupied_volume": 1.0, "signed_volume": 1.0}
    rows.append(cube)

    outer, inner, height, bottom = 0.04, 0.035, 0.09, 0.005
    mug_positions, mug_indices = mug_mesh(outer, inner, height, bottom)
    mug = measure_one(
        "control-hollow-mug", "control",
        Mesh(positions=np.asarray(mug_positions, dtype=np.float64),
             indices=np.asarray(mug_indices, dtype=np.int64).reshape(-1, 3)),
        None)
    import math
    envelope = math.pi * outer**2 * height
    ceramic = math.pi * (outer**2 - inner**2) * (height - bottom) + math.pi * inner**2 * bottom
    mug["analytic"] = {"occupied_volume": envelope, "signed_volume": ceramic}
    rows.append(mug)
    return rows


def _progress(row: dict, done: int, total: int) -> None:
    """One line per mesh, so a running log shows where it is."""
    topo = row["topology"]
    occ = row["occupancy"]
    print(
        f"[{done:>2}/{total}] {row['name'][:40]:40s} "
        f"tris {row['triangles']:>8} "
        f"wt {int(topo['ours']['watertight'])}/{int(topo['o3d']['watertight'])} "
        f"hull_d {fmt_pct(occ['hull_rel_diff'])} "
        f"vish {fmt_pct(occ['fill_ratio_grid_visual'])} "
        f"selfx {int(row['self_intersection']['o3d'])} "
        f"simpl {row['simplify']['seconds']:>7.2f}s",
        flush=True,
    )


def fmt_pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{100 * value:5.2f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="the first three reference meshes only")
    args = parser.parse_args()

    o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)

    reference = {a["name"]: a for a in json.loads(REFERENCE_JSON.read_text())["assets"]}
    paths = sorted(GLB_DIR.glob("*.glb"))
    if args.quick:
        paths = paths[:3]

    state_start = box_state()
    total = len(paths) + (0 if args.quick else len(list(EXTRA_DIR.glob("*.glb"))) + 2)
    done = 0
    rows = []
    for p in paths:
        row = read_and_compare(p.stem, "reference", p, reference.get(p.stem))
        rows.append(row)
        done += 1
        _progress(row, done, total)
    if not args.quick:
        for p in sorted(EXTRA_DIR.glob("*.glb")):
            row = read_and_compare(p.stem, "extra", p, None)
            rows.append(row)
            done += 1
            _progress(row, done, total)
        for row in control_rows():
            rows.append(row)
            done += 1
            _progress(row, done, total)
    state_end = box_state()

    document = {
        "meta": {
            "started": state_start,
            "ended": state_end,
            "resolution": RESOLUTION,
            "simplify_to": SIMPLIFY_TO,
            "watertight_definitions": {
                "ours": "every edge used by exactly two triangles (closed)",
                "o3d": ("edge-manifold, vertex-manifold and not "
                        "self-intersecting (a valid solid boundary)"),
            },
            "rss_peak_mb": round(rss_peak_mb(), 1),
            "meshes": len(rows),
        },
        "meshes": rows,
    }
    out = Path(__file__).resolve().parent / "results" / "results.json"
    out.write_text(json.dumps(document, indent=2))
    print(f"wrote {out} — {len(rows)} meshes, peak RSS {document['meta']['rss_peak_mb']} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
