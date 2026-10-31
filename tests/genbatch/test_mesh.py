"""The mesh layer: read a GLB, and measure it the way the critic needs.

These are the oracle-style checks borrowed from SolidCraft (docs/research/
solidcraft.md): volume, area, centre of mass and bounding box, plus the
watertightness the Prop-maker's critic has to have before it can call a prop
a solid.
"""

from __future__ import annotations

import math

import pytest

from core.genbatch.glb import GlbError, read_glb
from core.genbatch.mesh import measure_mesh
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
