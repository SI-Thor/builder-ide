"""The Open3D-backed geometry: the three uses the sweep adopted.

The tests run in two regimes. The **declined** regime (the wheel absent,
the mesh over the cap) is forced by monkeypatching the probe cache, so it
is deterministic on every box. The **measured** regime needs the ``o3d``
extra and skips without it — the numbers it asserts (the parity volume of
a cube, the diet's triangle target) are the sweep's own semantics
(docs/lab/exp-open3d-critic.md).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.genbatch import o3d_geometry
from core.genbatch.glb import Mesh
from core.genbatch.mesh import measure_mesh
from tests.genbatch.glb_fixtures import cube_mesh, mug_mesh, revolve

needs_o3d = pytest.mark.skipif(
    not o3d_geometry.open3d_available(), reason="needs the o3d extra"
)


def _mesh(positions, indices) -> Mesh:
    return Mesh(
        positions=np.asarray(positions, dtype=np.float64).reshape(-1, 3),
        indices=np.asarray(indices, dtype=np.int64).reshape(-1, 3),
    )


def _cube() -> Mesh:
    positions, indices = cube_mesh()
    return _mesh(positions, indices)


def _crossing() -> Mesh:
    """A flat triangle and a vertical blade through it: one crossing pair."""
    positions = [
        (-1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, -1.0, 0.0),
        (-0.3, -0.1, -1.0),
        (0.3, -0.1, -1.0),
        (0.0, -0.1, 1.0),
    ]
    indices = [
        0, 1, 2,
        3, 4, 5,
    ]
    return _mesh(positions, indices)


def _grid(triangles: int) -> Mesh:
    """A flat grid of ~``triangles`` triangles — cheap to build, no crossings."""
    side = int(math.isqrt(triangles // 2)) + 1
    x, y = np.meshgrid(
        np.arange(side + 1, dtype=np.float64),
        np.arange(side + 1, dtype=np.float64),
        indexing="ij",
    )
    positions = np.stack([x.ravel(), y.ravel(), np.zeros(x.size)], axis=1)
    i, j = np.meshgrid(np.arange(side), np.arange(side), indexing="ij")
    v00 = (i * (side + 1) + j).ravel()
    v01 = v00 + 1
    v10 = v00 + side + 1
    v11 = v10 + 1
    indices = np.concatenate(
        [
            np.stack([v00, v10, v01], axis=1),
            np.stack([v01, v10, v11], axis=1),
        ],
        axis=0,
    )
    return Mesh(positions=positions, indices=indices.astype(np.int64))


# -- the declined regime: deterministic on every box ------------------------


def test_without_the_wheel_the_check_says_unchecked(monkeypatch):
    monkeypatch.setattr(o3d_geometry, "_O3D", None)

    verdict = o3d_geometry.self_intersection(_cube())

    assert verdict.state == "unchecked"
    assert "o3d" in verdict.reason


def test_without_the_wheel_parity_declines(monkeypatch):
    monkeypatch.setattr(o3d_geometry, "_O3D", None)

    assert o3d_geometry.parity_volume(_cube()) is None


def test_without_the_wheel_the_diet_refuses_to_run(monkeypatch):
    monkeypatch.setattr(o3d_geometry, "_O3D", None)

    with pytest.raises(RuntimeError, match="o3d"):
        o3d_geometry.quadric_diet(_cube(), fraction=0.5)


def test_a_mesh_over_the_cap_is_unchecked_not_decimated():
    over = _grid(o3d_geometry.SELF_INTERSECTION_CAP * 2)

    verdict = o3d_geometry.self_intersection(over)

    assert verdict.state == "unchecked"
    assert "cap" in verdict.reason
    assert verdict.checked_triangles == over.triangles
    # The reason has to say why it did not decimate either: a stand-in
    # verdict would be about a different mesh.
    assert "different mesh" in verdict.reason


def test_a_tighter_cap_declines_the_same_way():
    verdict = o3d_geometry.self_intersection(_cube(), cap=10)

    assert verdict.state == "unchecked"
    assert "10" in verdict.reason


def test_an_empty_mesh_is_unchecked():
    empty = Mesh(
        positions=np.zeros((0, 3), dtype=np.float64),
        indices=np.zeros((0, 3), dtype=np.int64),
    )

    verdict = o3d_geometry.self_intersection(empty)

    assert verdict.state == "unchecked"
    assert verdict.reason


def test_the_check_can_be_turned_off():
    verdict = o3d_geometry.self_intersection(_cube(), cap=None)

    assert verdict.state == "unchecked"
    assert "not asked for" in verdict.reason


# -- the measured regime: needs the o3d extra -------------------------------


@needs_o3d
def test_a_clean_mesh_reads_clean():
    verdict = o3d_geometry.self_intersection(_cube())

    assert verdict.state == "clean"
    assert verdict.checked_triangles == 12


@needs_o3d
def test_two_crossing_triangles_are_found():
    verdict = o3d_geometry.self_intersection(_crossing())

    assert verdict.state == "self_intersecting"
    assert verdict.pairs >= 1


@needs_o3d
def test_the_parity_volume_of_a_cube_is_the_cube():
    # A cube aligned to the grid: every cell is unambiguously inside, so
    # the parity volume is exact at any resolution.
    assert o3d_geometry.parity_volume(_cube(), resolution=16) == pytest.approx(1.0)


@needs_o3d
def test_parity_needs_no_winding():
    positions, indices = cube_mesh()
    indices = list(indices)
    indices[0], indices[1] = indices[1], indices[0]  # one face flipped

    volume = o3d_geometry.parity_volume(_mesh(positions, indices), resolution=16)

    # The signed volume of this mesh is nonsense (a flipped face); the
    # parity volume is still the cube.
    assert volume == pytest.approx(1.0)


@needs_o3d
def test_parity_answers_on_a_shell():
    volume = o3d_geometry.parity_volume(_mesh(*mug_mesh()), resolution=64)

    # The enclosed solid of the hollow mug is its ceramic — a small
    # fraction of the box it occupies, and not zero.
    assert volume is not None
    box = 0.08 * 0.08 * 0.09
    assert 0.0 < volume < box


@needs_o3d
def test_the_diet_lands_on_its_target():
    dense = _mesh(*revolve(
        [
            (0.5 + 0.4 * math.cos(2.0 * math.pi * i / 64),
             0.5 + 0.4 * math.sin(2.0 * math.pi * i / 64))
            for i in range(64)
        ],
        segments=96,
    ))

    dieted = o3d_geometry.quadric_diet(dense, fraction=0.1, min_triangles=100)

    assert 0.9 * 0.1 * dense.triangles <= dieted.triangles <= 1.05 * 0.1 * dense.triangles


@needs_o3d
def test_the_diet_keeps_the_volume_of_a_smooth_solid():
    dense = _mesh(*revolve(
        [
            (0.5 + 0.4 * math.cos(2.0 * math.pi * i / 64),
             0.5 + 0.4 * math.sin(2.0 * math.pi * i / 64))
            for i in range(64)
        ],
        segments=96,
    ))
    before = measure_mesh(dense, selfx=False, parity_fallback=False)

    dieted = o3d_geometry.quadric_diet(dense, fraction=0.1, min_triangles=100)
    after = measure_mesh(dieted, selfx=False, parity_fallback=False)

    assert abs(after.volume - before.volume) / before.volume < 0.05


@needs_o3d
def test_the_diet_floor_stops_a_small_prop_collapsing():
    cube = _cube()

    # A 12-triangle cube asked down to a hundredth would collapse to
    # nothing (the sweep saw exactly that); the floor holds it up.
    dieted = o3d_geometry.quadric_diet(cube, fraction=0.01, min_triangles=1000)

    assert dieted.triangles == 12


@needs_o3d
def test_the_diet_of_an_empty_mesh_is_the_empty_mesh():
    empty = Mesh(
        positions=np.zeros((0, 3), dtype=np.float64),
        indices=np.zeros((0, 3), dtype=np.int64),
    )

    assert o3d_geometry.quadric_diet(empty, fraction=0.1).triangles == 0
