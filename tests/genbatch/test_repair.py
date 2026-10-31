"""The repair stage: between TRELLIS.2 and the critic.

The mini-night found that TRELLIS.2's meshes were never watertight — 155 k
to 234 k boundary edges on every one of them — and that the critic's heaviest
check therefore scored zero for every candidate (docs/lab/mini-night.md §3).

The repair stage is what makes that check mean something again. It has three
jobs, and each is tested here:

* it **welds** the vertices the UV unwrap split apart, which closes the
  boundary edges without moving anything;
* it **splits** the edges the surface crosses itself on, which are the only
  thing left that is not manifold;
* it **measures** what it did — the wall-clock, and the silhouette IoU
  against the mesh it was given, so a repair that reshapes the prop is
  caught rather than shipped.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.genbatch.critic import judge
from core.genbatch.fidelity import silhouette_iou
from core.genbatch.glb import Mesh
from core.genbatch.mesh import measure_mesh
from core.genbatch.models import PropRequest
from core.genbatch.repair import RepairRecipe, repair_mesh
from tests.genbatch.glb_fixtures import cube_mesh, quad_mesh, tetra_mesh


def _mesh(positions, indices) -> Mesh:
    return Mesh(
        positions=np.asarray(positions, dtype=np.float64),
        indices=np.asarray(indices, dtype=np.int64).reshape(-1, 3),
    )


def _seam_cube() -> Mesh:
    """A cube with one vertex split in two, the way an unwrap leaves it.

    The unwrap opens a seam by giving a vertex two copies — one per side of
    the seam — at the same position. The cube's geometry is untouched, but
    the index buffer can no longer see the edges that meet at that vertex.
    """
    positions, indices = cube_mesh()
    positions = list(positions)
    faces = [list(indices[i : i + 3]) for i in range(0, len(indices), 3)]
    copy = len(positions)
    positions.append(positions[0])
    # The fan around vertex 0 is six faces; the last three of them go to the
    # copy, so the seam opens along two edges.
    for face in (faces[0], faces[1], faces[9]):
        face[face.index(0)] = copy
    return _mesh(positions, [row for face in faces for row in face])


def _crossed_tetrahedra() -> Mesh:
    """Two tetrahedra that share an edge: the surface crosses itself there.

    Each tetrahedron is closed on its own; together they share one edge, and
    that edge is used by four triangles — the shape of the self-crossing the
    repair has to split.
    """
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.5, 0.5, 0.5),
        (0.5, -0.5, -0.5),
    ]
    # The second tetrahedron shares the first one's edge (0, 1).
    indices = [
        0, 2, 1,
        0, 1, 3,
        0, 3, 2,
        1, 2, 3,
        0, 4, 1,
        0, 1, 5,
        0, 5, 4,
        1, 4, 5,
    ]
    return _mesh(positions, indices)


def test_the_weld_closes_the_boundary_edges_the_unwrap_opened():
    mesh = _seam_cube()

    before = measure_mesh(mesh)
    result = repair_mesh(mesh, RepairRecipe())
    after = result.report.after

    assert before.boundary_edges > 0
    assert before.watertight is False
    assert after is not None
    assert after.boundary_edges == 0
    assert after.watertight is True
    assert after.consistent_winding is True
    assert result.report.welded_vertices == 1


def test_the_weld_does_not_move_anything():
    mesh = _seam_cube()

    result = repair_mesh(mesh, RepairRecipe())

    before = result.report.before
    after = result.report.after
    assert after is not None
    # The same surface, the same solid — only the index buffer changed.
    assert after.area == pytest.approx(before.area)
    assert after.volume == pytest.approx(before.volume)
    assert after.triangles == before.triangles


def test_the_repair_reports_the_outline_it_kept():
    mesh = _seam_cube()

    result = repair_mesh(mesh, RepairRecipe())

    # Nothing moved, so the silhouette is the same outline.
    assert result.report.fidelity == pytest.approx(1.0, abs=1e-6)
    assert result.report.ok is True
    assert result.report.seconds > 0


def test_the_repair_refuses_to_ship_a_prop_it_could_not_repair():
    # A quad has a real hole: there is no coincident vertex to weld and no
    # missing geometry to invent, so the repair says so rather than claiming
    # a solid it did not make.
    positions, indices = quad_mesh()

    result = repair_mesh(_mesh(positions, indices), RepairRecipe())

    assert result.report.ok is False
    assert "boundary" in result.report.reason
    assert result.report.after is not None
    assert result.report.after.watertight is False


def test_the_repair_stage_can_be_turned_off():
    mesh = _seam_cube()

    result = repair_mesh(mesh, RepairRecipe(method="none"))

    assert result.report.welded_vertices == 0
    assert result.mesh is mesh
    assert result.report.after is not None
    assert result.report.after.boundary_edges > 0


def test_the_repair_splits_an_edge_the_surface_crosses_itself_on():
    mesh = _crossed_tetrahedra()

    before = measure_mesh(mesh)
    result = repair_mesh(mesh, RepairRecipe())
    after = result.report.after

    assert before.nonmanifold_edges == 1
    assert after is not None
    assert after.nonmanifold_edges == 0
    assert after.boundary_edges == 0
    # The crossing is undone by giving the pinched vertex a second copy,
    # which splits the crossing edge with it.
    assert (
        result.report.pinched_vertices_split + result.report.nonmanifold_edges_split
    ) >= 1
    # The geometry did not move: the two shells still touch where they did.
    assert after.area == pytest.approx(before.area)


def test_the_fidelity_measure_notices_a_prop_that_changed_shape():
    cube = _mesh(*cube_mesh())
    quad = _mesh(*quad_mesh())

    # A cube and a flat square share no outline.
    assert silhouette_iou(cube, quad, samples=200_000) < 0.5
    assert silhouette_iou(cube, cube, samples=200_000) == pytest.approx(1.0)


def test_the_fidelity_measure_is_not_measuring_its_own_noise():
    # The silhouette is drawn by sampling the surface, so a grid that is
    # sampled too thinly measures the sampling and not the shape: two meshes
    # with identical geometry but a different triangle order scored 0.51
    # before the grid was made dense enough. It must not do that now.
    positions, indices = cube_mesh()
    mesh = _mesh(positions, indices)
    order = np.random.default_rng(0).permutation(len(indices) // 3)
    shuffled = _mesh(positions, list(np.asarray(indices).reshape(-1, 3)[order]))

    assert silhouette_iou(mesh, shuffled, resolution=128, samples=1_000_000) > 0.98


def test_the_critic_holds_the_repaired_prop_to_its_outline():
    request = PropRequest(id="crate", prompt="a weathered wooden crate")
    mesh = _seam_cube()
    result = repair_mesh(mesh, request.repair)

    verdict = judge(result.report.after, request, result.report)

    checks = {check.name: check for check in verdict.checks}
    assert checks["watertight"].passed is True
    assert checks["repair_fidelity"].passed is True
    assert checks["repair_fidelity"].score == pytest.approx(1.0)


def test_the_critic_fails_a_prop_whose_repair_did_not_succeed():
    request = PropRequest(id="crate", prompt="a weathered wooden crate")
    positions, indices = quad_mesh()
    result = repair_mesh(_mesh(positions, indices), request.repair)

    verdict = judge(result.report.after, request, result.report)

    checks = {check.name: check for check in verdict.checks}
    assert checks["watertight"].passed is False
    assert "repair" in checks["watertight"].detail


def test_the_fidelity_check_is_graded_not_pass_or_fail():
    request = PropRequest(
        id="crate",
        prompt="a weathered wooden crate",
        repair=RepairRecipe(min_fidelity=0.99),
    )
    mesh = _seam_cube()
    result = repair_mesh(mesh, request.repair)
    # A repair that came short of the floor still says how short it was.
    result.report.fidelity = 0.5

    verdict = judge(result.report.after, request, result.report)

    check = next(c for c in verdict.checks if c.name == "repair_fidelity")
    assert check.passed is False
    assert 0.0 < check.score < 1.0
