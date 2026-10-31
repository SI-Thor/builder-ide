"""The bake-off: every repair method the brief names, on the mini-night's nine.

The question the mini-night left open: TRELLIS.2's meshes were never
watertight, so what should the pipeline do about it? The brief names the
candidates — trimesh's hole filling, MeshFix, manifold3d, a voxel remesh — and
asks for the same four numbers for each of them on the nine meshes the
mini-night made:

* **watertight** — no boundary edges and no non-manifold edges, and the
  winding consistent, and a positive volume;
* **triangles** — how many the method leaves;
* **fidelity** — the silhouette IoU against the mesh it was given;
* **CPU time** — what the method costs the night's CPU lane.

The box's load average is recorded beside every measurement, because on this
box the load moves the wall-clock.

Run: .venv/bin/python docs/lab/mesh-repair-scripts/bake_off.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.fidelity import silhouette_iou
from core.genbatch.glb import Mesh, read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.repair import RepairRecipe, repair_mesh

TRELLIS_OUT = Path.home() / "lm-wt/trellis/out/genbatch"
RESULTS = Path("artifacts/mesh-repair/bake_off.json")

MESHES = [
    "crate_s1064508603_00004_.glb",
    "crate_s455794046_00002_.glb",
    "crate_s833331073_00002_.glb",
    "lantern_s1427939119_00002_.glb",
    "lantern_s424809304_00002_.glb",
    "lantern_s913610340_00002_.glb",
    "anvil_s1597230408_00002_.glb",
    "anvil_s64961400_00002_.glb",
    "anvil_s6984999_00002_.glb",
]


def load_average() -> float:
    """The box's one-minute load average."""
    try:
        return float(Path("/proc/loadavg").read_text().split()[0])
    except OSError:
        return 0.0


def measure(name: str, mesh: Mesh, seconds: float, load: float) -> dict:
    """The four numbers, plus what else the measurement can tell us."""
    report = measure_mesh(mesh)
    return {
        "method": name,
        "seconds": round(seconds, 3),
        "load": round(load, 2),
        "vertices": report.vertices,
        "triangles": report.triangles,
        "boundary_edges": report.boundary_edges,
        "nonmanifold_edges": report.nonmanifold_edges,
        "consistent_winding": report.consistent_winding,
        "volume": round(report.volume, 8),
        "area": round(report.area, 8),
        "watertight": bool(
            report.watertight and report.consistent_winding and report.volume > 0
        ),
    }


def fidelity_of(before: Mesh, after: Mesh) -> float:
    """The silhouette IoU of the repaired mesh against the original."""
    return round(
        silhouette_iou(
            before,
            after,
            views=("+x", "+y", "+z"),
            resolution=128,
            samples=1_000_000,
        ),
        6,
    )


# -- the candidates --------------------------------------------------------


def method_none(mesh: Mesh) -> Mesh:
    """What TRELLIS.2 handed over, untouched."""
    return mesh


def method_weld(mesh: Mesh) -> Mesh:
    """The repair this seat wrote: weld the seams, split the crossings."""
    return repair_mesh(mesh, RepairRecipe()).mesh


def method_trimesh_fill(mesh: Mesh) -> Mesh:
    """trimesh's hole filling (MIT)."""
    import trimesh

    source = trimesh.Trimesh(vertices=mesh.positions, faces=mesh.indices, process=False)
    # ``use_fan`` fills holes of any size, not just the single-quad ones.
    trimesh.repair.fill_holes(source, use_fan=True)
    return Mesh(
        positions=np.asarray(source.vertices, dtype=np.float64),
        indices=np.asarray(source.faces, dtype=np.int64),
    )


def method_pymeshfix(mesh: Mesh) -> Mesh:
    """MeshFix, through pymeshfix (AGPL-3.0 — measured, not shipped)."""
    import pymeshfix

    fixer = pymeshfix.MeshFix(mesh.positions, mesh.indices)
    fixer.repair(joincomp=True, remove_smallest_components=False)
    return Mesh(
        positions=np.asarray(fixer.v, dtype=np.float64),
        indices=np.asarray(fixer.f, dtype=np.int64),
    )


def method_manifold3d(mesh: Mesh) -> Mesh:
    """manifold3d's manifold constructor (Apache-2.0).

    manifold3d takes the mesh as the generator made it — vertices split at
    the UV seams — and is told which vertices are the same point through
    ``merge_from_vert``/``merge_to_vert``, which is what the library's own
    UV-seam support is for. So this candidate gets the whole job, not half
    of it.
    """
    import manifold3d

    scale = float(np.linalg.norm(mesh.positions.max(axis=0) - mesh.positions.min(axis=0)))
    keys = np.round(mesh.positions / (1e-6 * scale)).astype(np.int64)
    _unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    order = np.argsort(inverse, kind="stable")
    firsts = order[np.searchsorted(inverse[order], np.arange(int(inverse.max()) + 1))]
    merge_from = np.setdiff1d(np.arange(mesh.vertices), firsts).astype(np.uint32)
    merge_to = firsts[inverse[merge_from]].astype(np.uint32)
    source = manifold3d.Mesh(
        vert_properties=mesh.positions.astype(np.float32),
        tri_verts=mesh.indices.astype(np.uint32),
        merge_from_vert=merge_from,
        merge_to_vert=merge_to,
    )
    solid = manifold3d.Manifold(source)
    out = solid.to_mesh()
    if out.vert_properties.shape[0] == 0:
        raise ValueError("manifold3d refused the mesh")
    return Mesh(
        positions=np.asarray(out.vert_properties, dtype=np.float64),
        indices=np.asarray(out.tri_verts, dtype=np.int64),
    )


def method_voxel(mesh: Mesh, resolution: int = 128) -> Mesh:
    """A voxel remesh: fill a grid, then march cubes out of it."""
    import trimesh

    source = trimesh.Trimesh(vertices=mesh.positions, faces=mesh.indices, process=False)
    extent = source.bounds[1] - source.bounds[0]
    pitch = float(max(extent)) / resolution
    voxels = source.voxelized(pitch, method="subdivide")
    filled = voxels.fill()
    remeshed = filled.marching_cubes
    # The marching cubes come out in the grid's own coordinates; the grid's
    # transform puts them back in the world the prop was generated in.
    remeshed.apply_transform(filled.transform)
    return Mesh(
        positions=np.asarray(remeshed.vertices, dtype=np.float64),
        indices=np.asarray(remeshed.faces, dtype=np.int64),
    )


ALL_CANDIDATES = [
    ("none", method_none),
    ("weld", method_weld),
    ("trimesh_fill_holes", method_trimesh_fill),
    ("pymeshfix", method_pymeshfix),
    ("manifold3d", method_manifold3d),
    ("voxel_128", method_voxel),
]


def candidates() -> list:
    """The candidates to run. ``--only`` and ``--skip`` narrow the list."""
    only = None
    skip: set[str] = set()
    argv = sys.argv[1:]
    for index, arg in enumerate(argv):
        if arg == "--only" and index + 1 < len(argv):
            only = argv[index + 1]
        if arg == "--skip" and index + 1 < len(argv):
            skip.add(argv[index + 1])
    chosen = ALL_CANDIDATES
    if only:
        chosen = [c for c in chosen if c[0] == only]
    if skip:
        chosen = [c for c in chosen if c[0] not in skip]
    return chosen


def main() -> None:
    rows: list[dict] = []
    for mesh_name in MESHES:
        path = TRELLIS_OUT / mesh_name
        if not path.exists():
            print(f"{mesh_name}: missing")
            continue
        original = read_glb(path).mesh
        for method, function in candidates():
            load = load_average()
            started = time.perf_counter()
            error = ""
            try:
                repaired = function(original)
            except Exception as exc:  # a method that cannot do the job is a result
                error = f"{type(exc).__name__}: {exc}"
                repaired = None
            seconds = time.perf_counter() - started
            row = {"mesh": mesh_name}
            if repaired is None:
                row.update(
                    {
                        "method": method,
                        "seconds": round(seconds, 3),
                        "load": round(load, 2),
                        "error": error,
                        "watertight": False,
                    }
                )
            else:
                row.update(measure(method, repaired, seconds, load))
                row["fidelity"] = fidelity_of(original, repaired)
                row["error"] = error
            rows.append(row)
            print(
                f"{mesh_name:36s} {method:20s} "
                f"wt={str(row.get('watertight')):5s} "
                f"tris={row.get('triangles', 0):>8,} "
                f"bnd={row.get('boundary_edges', -1):>7,} "
                f"nm={row.get('nonmanifold_edges', -1):>3,} "
                f"iou={row.get('fidelity', 0.0):.4f} "
                f"{row['seconds']:>7.2f}s load {row['load']:.1f}"
                + (f"  {error}" if error else "")
            )
    # Merge into whatever is already there, so one method can be re-run on
    # its own without throwing the others away.
    existing: list[dict] = []
    if RESULTS.exists():
        try:
            existing = json.loads(RESULTS.read_text())
        except json.JSONDecodeError:
            existing = []
    merged = {
        (row["mesh"], row["method"]): row for row in existing if "method" in row
    }
    for row in rows:
        merged[(row["mesh"], row["method"])] = row
    ordered = [merged[key] for key in sorted(merged)]
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(ordered, indent=1))
    print(f"\nwrote {RESULTS}")


if __name__ == "__main__":
    main()
