"""What do TRELLIS.2's open meshes actually look like?

Counts the boundary loops of every mesh the mini-night made: how many loops,
how big each one is in *area* and in *space*, and how much of the surface the
open part covers. The repair method that works depends entirely on the answer.

Run: .venv/bin/python docs/lab/mesh-repair-scripts/probe_boundaries.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.glb import read_glb

OUT = Path.home() / "lm-wt/trellis/out/genbatch"
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


def boundary_loops(indices: np.ndarray, n_vertices: int):
    """The boundary loops of a mesh: each loop's vertex indices, in order."""
    directed = np.concatenate(
        [indices[:, [0, 1]], indices[:, [1, 2]], indices[:, [2, 0]]], axis=0
    )
    lo = np.minimum(directed[:, 0], directed[:, 1])
    hi = np.maximum(directed[:, 0], directed[:, 1])
    keys = lo * np.int64(n_vertices) + hi
    uniq, inv, counts = np.unique(keys, return_inverse=True, return_counts=True)
    n_edges = int(uniq.size)
    # A directed edge is on a boundary when its undirected edge is used once.
    bdir = directed[counts[inv] == 1]
    n_boundary = int(np.count_nonzero(counts == 1))
    # A directed boundary edge (a -> b); the loop continues b -> c.
    nxt = {int(a): int(b) for a, b in bdir}
    seen: set[int] = set()
    loops: list[list[int]] = []
    for start in nxt:
        if start in seen:
            continue
        loop: list[int] = []
        node = start
        while node not in seen:
            seen.add(node)
            loop.append(node)
            node = nxt.get(node)
            if node is None:
                break
        loops.append(loop)
    return loops, n_boundary, n_edges


def loop_area_3d(loop: np.ndarray) -> float:
    """The area of a loop's best-fit-plane polygon, in 3-D.

    The loop's points are projected onto their own best-fit plane (a PCA of
    the points), and the projected polygon is measured with the shoelace
    formula. This is the hole's area in the surface it interrupts.
    """
    if loop.shape[0] < 3:
        return 0.0
    centred = loop - loop.mean(axis=0)
    # The plane's normal is the smallest principal axis.
    _, _, vh = np.linalg.svd(centred, full_matrices=False)
    normal = vh[-1]
    axis_u, axis_v = vh[0], vh[1]
    u = centred @ axis_u
    v = centred @ axis_v
    x, y = u, v
    return float(
        0.5
        * abs(
            np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))
        )
    )


def main() -> None:
    for name in MESHES:
        path = OUT / name
        if not path.exists():
            print(f"{name}: MISSING")
            continue
        mesh = read_glb(path).mesh
        loops, n_boundary, n_edges = boundary_loops(mesh.indices, mesh.vertices)
        positions = mesh.positions
        a = positions[mesh.indices[:, 0]]
        b = positions[mesh.indices[:, 1]]
        c = positions[mesh.indices[:, 2]]
        mesh_area = float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
        extent = positions.max(axis=0) - positions.min(axis=0)
        diag = float(np.linalg.norm(extent))

        sizes = np.array([len(loop) for loop in loops])
        areas = np.array(
            [loop_area_3d(positions[loop]) for loop in loops], dtype=np.float64
        )
        # The largest distance inside a loop, in units of the mesh's diagonal.
        chords = []
        for loop in loops:
            pts = positions[loop]
            if pts.shape[0] < 2:
                chords.append(0.0)
                continue
            d = pts[:, None, :] - pts[None, :, :]
            chords.append(float(np.sqrt((d**2).sum(axis=-1)).max()))
        chords = np.array(chords)
        total_hole_area = float(areas.sum())

        print(
            f"{name}\n"
            f"  tris {mesh.triangles:,}  verts {mesh.vertices:,}  edges {n_edges:,}\n"
            f"  boundary edges {n_boundary:,} ({n_boundary / n_edges:.1%} of all edges)\n"
            f"  loops {len(loops):,}  edges/loop: median {int(np.median(sizes))}, "
            f"p90 {int(np.percentile(sizes, 90))}, max {sizes.max():,}\n"
            f"  surface area {mesh_area:.5f}  hole area {total_hole_area:.6f} "
            f"({total_hole_area / mesh_area:.3%} of the surface)\n"
            f"  biggest hole: {areas.max():.3e} area, chord {chords.max() / diag:.4f} "
            f"of the diagonal\n"
            f"  hole area p50 {np.median(areas):.3e}  p90 {np.percentile(areas, 90):.3e}"
        )


if __name__ == "__main__":
    main()
