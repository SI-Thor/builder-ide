"""Digest the comparison: the agreements, the timings, the verdict numbers.

Reads ``results/results.json`` (written by ``compare.py``) and prints the
aggregates the report quotes: reader agreement, watertight agreement and
its causes, volume/hull/visual agreements, self-intersection cost,
simplification cost, the reference-set reproduction, and the grid fills
normalised against the grid's own volume (Open3D's voxel grid is
isotropic-cell and rounds each axis up, so a grid fill against the exact
bounding box can exceed 100 % — against the grid's own volume it cannot).

Usage::

    ~/lm-wt/open3d-critic/.venv/bin/python docs/lab/open3d-critic/summarize.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import open3d as o3d

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

from compare import RESOLUTION, read_glb, to_o3d  # noqa: E402


def grid_fill_normalised(mesh: o3d.geometry.TriangleMesh) -> tuple[float, float]:
    """The visual-hull fill against the grid's own volume, and that volume."""
    lo = np.asarray(mesh.get_min_bound(), dtype=np.float64)
    extent = np.asarray(mesh.get_max_bound(), dtype=np.float64) - lo
    longest = float(np.max(extent))
    if longest <= 0.0:
        return 0.0, 0.0
    cell = longest / RESOLUTION
    counts = np.maximum(np.ceil(extent / cell).astype(int), 1)
    grid_volume = float(np.prod(counts)) * cell**3
    grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh(mesh, voxel_size=cell)
    surface = np.zeros(tuple(counts), dtype=bool)
    for voxel in grid.get_voxels():
        surface[tuple(np.clip(np.asarray(voxel.grid_index), 0, counts - 1))] = True
    hull = (surface.any(axis=2)[:, :, None]
            & surface.any(axis=1)[:, None, :]
            & surface.any(axis=0)[None, :, :])
    volume = int(np.count_nonzero(hull)) * cell**3
    return volume / grid_volume, grid_volume


def stats(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (f"median {statistics.median(values):.3e} "
            f"max {max(values):.3e} (n={len(values)})")


def main() -> int:
    document = json.loads((HERE / "results" / "results.json").read_text())
    rows = document["meshes"]
    meta = document["meta"]
    print(f"== meta ==")
    print(f"meshes {meta['meshes']}  rss peak {meta['rss_peak_mb']} MB")
    print(f"load start {meta['started']['load_average']} "
          f"avail {meta['started']['mem_available_gb']} GB | "
          f"load end {meta['ended']['load_average']} "
          f"avail {meta['ended']['mem_available_gb']} GB")

    total_tris = sum(r["triangles"] for r in rows)
    print("\n== readers ==  total tris "
          f"{sum(r['triangles'] for r in rows if r.get('read')):,}")
    files = [r for r in rows if r.get("read")]
    agree = [r for r in files if r["read"]["triangles_agree"]]
    gaps = [r["read"]["bbox_max_gap"] for r in files]
    ours_read = sum(r["read"]["ours_seconds"] for r in files)
    o3d_read = sum(r["read"]["o3d_seconds"] for r in files)
    print(f"triangle count agrees: {len(agree)}/{len(files)} files; "
          f"max bbox gap {max(gaps):.2e} m")
    print(f"read seconds: ours {ours_read:.2f}  o3d {o3d_read:.2f}")

    print("\n== watertight ==")
    agree_wt = [r for r in rows if r["topology"]["watertight_agrees"]]
    dis = [r for r in rows if not r["topology"]["watertight_agrees"]]
    ours_closed = [r for r in rows if r["topology"]["ours"]["watertight"]]
    o3d_closed = [r for r in rows if r["topology"]["o3d"]["watertight"]]
    dis_cause = [r["name"] for r in dis
                 if r["topology"]["ours"]["watertight"]
                 and not r["topology"]["o3d"]["watertight"]]
    dis_other = [r["name"] for r in dis if r["name"] not in dis_cause]
    print(f"agrees {len(agree_wt)}/{len(rows)}; ours closed {len(ours_closed)}, "
          f"o3d closed {len(o3d_closed)}")
    print(f"disagreements, ours-closed/o3d-open (self-intersecting): {len(dis_cause)}")
    print(f"disagreements, the other way: {dis_other}")

    print("\n== volumes ==")
    both = [r for r in rows if r["volume"]["o3d_get_volume"] is not None]
    vol_diffs = [r["volume"]["rel_diff"] for r in both]
    area_diffs = [r["volume"]["area_rel_diff"] for r in rows]
    print(f"signed volume both-present: {len(both)}/{len(rows)}; "
          f"rel diff {stats(vol_diffs)}")
    print(f"surface area rel diff {stats(area_diffs)}")

    hull_diffs = [r["occupancy"]["hull_rel_diff"] for r in rows]
    print(f"hull (scipy ours vs o3d): {stats(hull_diffs)}")
    hull_secs = [r["occupancy"]["o3d_hull_seconds"] for r in rows]
    ours_hull_secs = [r["occupancy"]["ours_convex_seconds"] for r in rows]
    print(f"hull seconds: ours(scipy) {stats(ours_hull_secs)}  o3d {stats(hull_secs)}")

    vis_diffs = [r["occupancy"]["visual_rel_diff"] for r in rows]
    print(f"visual hull (ours numpy vs o3d grid): rel diff {stats(vis_diffs)}")
    sparse = ["IV_pole_a01", "storage_shelf_basic_a01", "dishware_mug_a01",
              "sign_hospital_board_b02"]
    for name in sparse:
        row = next(r for r in rows if r["name"] == name)
        occ = row["occupancy"]
        print(f"  {name:28s} ours-visual {occ['ours_visual']:.6f} "
              f"o3d-grid {occ['o3d_grid_visual']:.6f} "
              f"hull {occ['ours_convex']:.6f}")

    print("\n== grid fills, normalised against the grid's own volume ==")
    fills = []
    for row in rows:
        if row["group"] == "control":
            mesh = None  # the controls are not files; their fills are exact enough
            continue
        mesh = read_glb(row["path"]).asset
        fill, grid_volume = grid_fill_normalised(to_o3d(mesh.positions, mesh.indices))
        fills.append((row["name"], fill, row["occupancy"]["fill_ratio_ours"]))
    below02 = [f for f in fills if f[1] < 0.2]
    print(f"grid visual fill: min {min(f[1] for f in fills):.3f} "
          f"median {statistics.median(f[1] for f in fills):.3f} "
          f"max {max(f[1] for f in fills):.3f}; below 0.2: {len(below02)}")
    print(f"below 0.2 by name: {[f[0] for f in below02]}")

    print("\n== ray-parity interior vs signed volume (both on closed meshes) ==")
    ray_vs_signed = []
    for row in rows:
        interior = row["occupancy"]["o3d_raycast_interior"]
        signed = row["volume"]["ours_signed"]
        if row["topology"]["ours"]["watertight"] and abs(signed) > 0:
            ray_vs_signed.append(abs(interior - signed) / max(abs(interior), abs(signed)))
    print(f"rel diff {stats(ray_vs_signed)}")
    ray_secs = [r["occupancy"]["o3d_raycast_seconds"] for r in rows]
    print(f"raycast seconds {stats(ray_secs)}")

    print("\n== self-intersection ==")
    selfx = [r for r in rows if r["self_intersection"]["o3d"]]
    secs = [r["self_intersection"]["o3d_seconds"] for r in rows]
    print(f"self-intersecting: {len(selfx)}/{len(rows)}; "
          f"seconds {stats(secs)}; total {sum(secs):.0f}s")
    worst = sorted(rows, key=lambda r: -r["self_intersection"]["o3d_seconds"])[:3]
    print("slowest:", [(w["name"], round(w["self_intersection"]["o3d_seconds"], 1),
                        w["triangles"]) for w in worst])

    print("\n== simplification (quadric to 10 %) ==")
    simp_secs = [r["simplify"]["seconds"] for r in rows]
    real = [r for r in rows if r["name"] != "control-cube"]
    total_out = sum(r["simplify"]["out_triangles"] for r in real)
    simp_real = sum(r["simplify"]["seconds"] for r in real)
    preserved = [r for r in real
                 if r["topology"]["ours"]["watertight"]
                 and r["simplify"]["watertight_after"]]
    closed_rows = [r for r in real if r["topology"]["ours"]["watertight"]]
    drift = [r["simplify"]["volume_rel_drift"] for r in real
             if r["simplify"]["volume_rel_drift"] is not None]
    print(f"seconds {stats([r['simplify']['seconds'] for r in real])}; "
          f"total {simp_real:.0f}s for "
          f"{sum(r['triangles'] for r in real):,} -> {total_out:,} tris")
    print(f"watertight preserved: {len(preserved)}/{len(closed_rows)} closed meshes")
    print(f"volume drift after simplify {stats(drift)} "
          "(the 12-triangle control cube collapses to 0 triangles at a "
          "target of 1 and is excluded)")

    print("\n== reference reproduction (the 38 recorded rows) ==")
    ref = [r for r in rows if "reference_agreement" in r]
    occ_diff = [r["reference_agreement"]["occupied_rel_diff"] for r in ref]
    signed_diff = [r["reference_agreement"]["signed_rel_diff"] for r in ref]
    wt_agree = [r for r in ref if r["reference_agreement"]["watertight_agrees"]]
    print(f"occupied volume rel diff {stats(occ_diff)}")
    print(f"signed volume rel diff {stats(signed_diff)}")
    print(f"watertight agrees {len(wt_agree)}/{len(ref)}")

    print("\n== whole-pipeline seconds (sum over meshes) ==")
    # topo seconds already include the one self-intersection pass
    ours_total = sum(r["topology"]["ours"]["seconds"] for r in rows) + ours_read
    ours_occ = sum(r["occupancy"]["ours_convex_seconds"]
                   + r["occupancy"]["ours_visual_seconds"] for r in rows)
    o3d_total = (sum(r["topology"]["o3d"]["seconds"] for r in rows) + o3d_read
                 + sum(simp_secs) + sum(hull_secs) + sum(ray_secs))
    print(f"ours (read+measure+2 occupancies): {ours_total + ours_occ:.0f}s")
    print(f"o3d (read+topo incl selfx+simplify+hull+ray): {o3d_total:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
