"""The mesh layer: read a GLB, and measure it the way the critic needs.

These are the oracle-style checks borrowed from SolidCraft (docs/research/
solidcraft.md): volume, area, centre of mass and bounding box, plus the
watertightness the Prop-maker's critic has to have before it can call a prop
a solid.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.genbatch.glb import GlbError, Mesh, encode_glb, read_glb, write_glb
from core.genbatch.mesh import MeshReport, measure_mesh
from core.genbatch.o3d_geometry import open3d_available
from tests.genbatch.glb_fixtures import (
    bowtie_mesh,
    build_glb,
    cube_mesh,
    quad_mesh,
    tetra_mesh,
)


def _write(tmp_path, name, positions, indices):
    path = tmp_path / name
    path.write_bytes(build_glb(positions, indices))
    return path


def test_reads_the_positions_and_the_indices(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "cube.glb", positions, indices)

    mesh = read_glb(path).mesh

    assert mesh.vertices == 8
    assert mesh.triangles == 12
    assert mesh.positions[0].tolist() == [-0.5, -0.5, -0.5]
    assert mesh.indices[0].tolist() == [0, 2, 1]


def test_a_file_that_is_not_a_glb_is_rejected(tmp_path):
    path = tmp_path / "not.glb"
    path.write_bytes(b"this is not a glb at all")

    with pytest.raises(GlbError):
        read_glb(path)


def test_a_glb_without_a_mesh_is_rejected(tmp_path):
    path = tmp_path / "empty.glb"
    path.write_bytes(build_glb([], []))

    with pytest.raises(GlbError):
        read_glb(path).mesh


def test_a_cube_is_watertight(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "cube.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is True
    assert report.consistent_winding is True
    assert report.boundary_edges == 0
    assert report.nonmanifold_edges == 0
    assert report.triangles == 12
    assert report.vertices == 8


def test_a_flipped_triangle_makes_the_winding_inconsistent(tmp_path):
    positions, indices = cube_mesh()
    # Swap two corners of the first triangle: the mesh stays closed, but one
    # face now runs the wrong way round its edges.
    indices = list(indices)
    indices[0], indices[1] = indices[1], indices[0]
    path = _write(tmp_path, "flipped.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is True
    assert report.consistent_winding is False


def test_an_open_mesh_has_boundary_edges(tmp_path):
    positions, indices = quad_mesh()
    path = _write(tmp_path, "quad.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is False
    assert report.boundary_edges == 4
    assert report.nonmanifold_edges == 0


def test_an_edge_used_three_times_is_not_manifold(tmp_path):
    positions, indices = bowtie_mesh()
    path = _write(tmp_path, "bowtie.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is False
    assert report.nonmanifold_edges == 1


def test_the_cube_measures_as_a_cube(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "cube.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.extent == pytest.approx((1.0, 1.0, 1.0))
    assert report.volume == pytest.approx(1.0)
    assert report.area == pytest.approx(6.0)
    assert report.centre_of_mass == pytest.approx((0.0, 0.0, 0.0))
    assert report.bbox_min == pytest.approx((-0.5, -0.5, -0.5))
    assert report.bbox_max == pytest.approx((0.5, 0.5, 0.5))


def test_the_tetrahedron_measures_as_a_tetrahedron(tmp_path):
    positions, indices = tetra_mesh()
    path = _write(tmp_path, "tetra.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is True
    assert report.volume == pytest.approx(1.0 / 6.0)
    assert report.area == pytest.approx(1.5 + math.sqrt(3.0) / 2.0)


def test_a_degenerate_triangle_is_counted(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "degenerate.glb", positions, indices + [0, 1, 1])

    report = measure_mesh(read_glb(path).mesh)

    assert report.degenerate_triangles == 1


def test_the_centre_of_mass_follows_the_geometry(tmp_path):
    positions = [
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (0.0, 2.0, 0.0),
        (0.0, 0.0, 2.0),
    ]
    indices = [0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]
    path = _write(tmp_path, "tetra2.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    # A tetrahedron's centre of mass is a quarter of the way along each axis.
    assert report.centre_of_mass == pytest.approx((0.5, 0.5, 0.5))
    assert report.volume == pytest.approx(8.0 / 6.0)


# -- the Open3D-backed signals, and the writer ------------------------------


def test_the_writer_writes_what_the_reader_reads(tmp_path):
    positions, indices = cube_mesh()
    path = tmp_path / "cube.glb"
    path.write_bytes(encode_glb(np.asarray(positions), np.asarray(indices)))

    mesh = read_glb(path).mesh

    assert mesh.vertices == 8
    assert mesh.triangles == 12
    assert mesh.positions == pytest.approx(np.asarray(positions), abs=1e-6)


def test_write_glb_writes_a_mesh_file(tmp_path):
    positions, indices = cube_mesh()
    mesh = Mesh(
        positions=np.asarray(positions, dtype=np.float64),
        indices=np.asarray(indices, dtype=np.int64).reshape(-1, 3),
    )

    path = write_glb(tmp_path / "kept.glb", mesh)

    assert read_glb(path).mesh.triangles == 12
    assert path.exists()


def test_the_writer_refuses_what_the_reader_rejects():
    with pytest.raises(GlbError):
        encode_glb(np.zeros((0, 3)), np.zeros((0, 3), dtype=int))


def test_a_report_from_before_the_check_exists_reads_back_unchecked():
    # The pre-Open3D reports have no self-intersection fields at all;
    # they deserialize as "unchecked", which is what they are.
    report = MeshReport(triangles=12, vertices=8)

    assert report.self_intersection == "unchecked"
    assert report.parity_volume is None


def test_the_old_measurement_can_still_be_asked_for(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "cube.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh, selfx=False, parity_fallback=False)

    assert report.self_intersection == "unchecked"
    assert "not asked for" in report.self_intersection_reason
    assert report.parity_volume is None


@pytest.mark.skipif(not open3d_available(), reason="needs the o3d extra")
def test_a_clean_closed_mesh_needs_no_fallback(tmp_path):
    positions, indices = cube_mesh()
    path = _write(tmp_path, "cube.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.self_intersection == "clean"
    assert report.parity_volume is None
    assert report.volume_reliable is True


@pytest.mark.skipif(not open3d_available(), reason="needs the o3d extra")
def test_an_open_mesh_gets_the_parity_fallback(tmp_path):
    positions, indices = quad_mesh()
    path = _write(tmp_path, "quad.glb", positions, indices)

    report = measure_mesh(read_glb(path).mesh)

    assert report.watertight is False
    assert report.volume_reliable is False
    assert report.parity_volume is not None


@pytest.mark.skipif(not open3d_available(), reason="needs the o3d extra")
def test_a_self_intersecting_mesh_does_not_trust_its_volume(tmp_path):
    # Two closed cubes overlapping in a corner: every edge is used exactly
    # twice, the winding is consistent, and the signed volume counts the
    # overlap twice — the one defect the edge census cannot see. The
    # second cube is moved in x and z both, so no face of one lies on a
    # face of the other: the parity read then excludes the overlap region
    # entirely (a ray through it sees four crossings), which is the
    # does-not-inflate property the fallback is adopted for.
    positions, indices = cube_mesh()
    shifted = [(x + 0.25, y, z + 0.25) for x, y, z in positions]
    mesh = Mesh(
        positions=np.asarray(positions + shifted, dtype=np.float64),
        indices=np.asarray(
            list(indices) + [index + 8 for index in indices], dtype=np.int64
        ).reshape(-1, 3),
    )

    report = measure_mesh(mesh)

    assert report.self_intersection == "self_intersecting"
    assert report.self_intersection_pairs >= 1
    assert report.volume_reliable is False
    # The signed volume reads 2.0 (both cubes, overlap counted twice);
    # the parity fallback reads the symmetric difference, 0.875.
    assert report.volume == pytest.approx(2.0)
    assert report.parity_volume == pytest.approx(0.875, rel=0.1)
