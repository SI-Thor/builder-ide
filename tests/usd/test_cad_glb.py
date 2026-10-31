"""The CAD chain: build123d → STEP → GLB, and the bounds that must agree.

The brief's pass/fail: *the GLB opens and its bounding box matches the
part*. These tests check that, and the two neighbours of it — the STEP
master and the USD mesh — because a GLB that is the right shape in the wrong
place is worse than no GLB at all.

The chain has three coordinate conventions, and the test is careful about
all three:

* CAD (OCCT, build123d) is **Z-up** and the part is authored in **metres**;
* the STEP master is written in **millimetres** — OCCT's STEP length unit —
  with build123d scaling the metres-authored shape into it;
* the GLB and the USD mesh are **Y-up** and in **metres**, the glTF and USD
  conventions.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from builder_usd import cad
from builder_usd.glb import read_glb
from builder_usd.verify import open_stage

TOLERANCE = 1e-6  # a micrometre in metres — glTF stores float32

#: The tessellation's own slack: a polygon inscribed in a cylinder is a
#: little smaller than the cylinder, so the mesh's bounds sit just inside the
#: part's true bounds. The deflection is 0.5 mm, and the chord error is well
#: under that.
TESSELLATION_SLACK = 1e-3

#: The parts of the demo recipe, with the parameters it authors them with.
DEMO_PARTS = {
    "crate_lid": {"length": 0.6, "width": 0.4, "thickness": 0.02},
    "mooring_post": {"height": 0.9, "diameter": 0.14},
    "hinge_bracket": {
        "length": 0.12,
        "width": 0.08,
        "thickness": 0.008,
        "hole_diameter": 0.012,
        "hole_offset": 0.04,
    },
}


def _yup_bounds(shape) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The part's bounds in the world frame: Y-up, metres."""
    box = shape.bounding_box()
    low = (float(box.min.X), float(box.min.Y), float(box.min.Z))
    high = (float(box.max.X), float(box.max.Y), float(box.max.Z))
    # CAD is Z-up; the world is Y-up: (x, y, z) -> (x, z, -y).
    return (low[0], low[2], -high[1]), (high[0], high[2], -low[1])


def _close(first, second, tolerance=TOLERANCE) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(first, second))


@pytest.mark.parametrize("name", sorted(DEMO_PARTS))
def test_the_glb_opens(demo_stage, name):
    path = demo_stage / "assets" / f"{name}.glb"
    info = read_glb(path)
    assert info.version == 2
    assert info.length == path.stat().st_size
    assert info.triangles > 0, "the GLB holds no triangles"
    assert info.meshes > 0
    assert "Open CASCADE" in info.generator


@pytest.mark.parametrize("name", sorted(DEMO_PARTS))
def test_the_glb_has_uvs(demo_stage, name):
    """rev-cad §1: build123d exports glTF with material UVs."""
    info = read_glb(demo_stage / "assets" / f"{name}.glb")
    assert info.has_uvs, f"{name}.glb carries no TEXCOORD_0"


@pytest.mark.parametrize("name", sorted(DEMO_PARTS))
def test_the_glb_bounding_box_matches_the_part(demo_stage, name):
    """The GLB's bounds are the part's bounds, in the world frame.

    The tessellation inscribes a polygon in the part's curved faces, so the
    mesh's bounds sit *inside* the true bounds by less than the deflection —
    never outside. Both halves are checked.
    """
    shape = cad.build_part(name, DEMO_PARTS[name])
    low, high = _yup_bounds(shape)
    info = read_glb(demo_stage / "assets" / f"{name}.glb")

    for axis in range(3):
        assert info.bbox_min[axis] >= low[axis] - TOLERANCE, (
            f"{name}: glb min {info.bbox_min[axis]} is outside the part {low[axis]}"
        )
        assert info.bbox_max[axis] <= high[axis] + TOLERANCE, (
            f"{name}: glb max {info.bbox_max[axis]} is outside the part {high[axis]}"
        )
        assert abs(info.bbox_max[axis] - info.bbox_min[axis]) == pytest.approx(
            high[axis] - low[axis], abs=TESSELLATION_SLACK
        ), f"{name}: glb extent on axis {axis} does not match the part"


@pytest.mark.parametrize("name", sorted(DEMO_PARTS))
def test_the_usd_mesh_bounding_box_matches_the_part(demo_stage, name):
    shape = cad.build_part(name, DEMO_PARTS[name])
    low, high = _yup_bounds(shape)
    mesh = cad.tessellate(shape)
    for axis in range(3):
        assert mesh.bbox_min[axis] >= low[axis] - TOLERANCE
        assert mesh.bbox_max[axis] <= high[axis] + TOLERANCE
        assert abs(mesh.bbox_max[axis] - mesh.bbox_min[axis]) == pytest.approx(
            high[axis] - low[axis], abs=TESSELLATION_SLACK
        )

    stage = open_stage(demo_stage / "root.usda")
    prim = stage.GetPrimAtPath("/World/harbor/crate_stack/mesh")
    if prim and name == "crate_lid":
        points = prim.GetAttribute("points").Get()
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]
        assert math.isclose(min(xs), low[0], abs_tol=TESSELLATION_SLACK)
        assert math.isclose(max(xs), high[0], abs_tol=TESSELLATION_SLACK)
        assert math.isclose(min(ys), low[1], abs_tol=TESSELLATION_SLACK)
        assert math.isclose(max(ys), high[1], abs_tol=TESSELLATION_SLACK)
        assert math.isclose(min(zs), low[2], abs_tol=TESSELLATION_SLACK)
        assert math.isclose(max(zs), high[2], abs_tol=TESSELLATION_SLACK)


def test_the_step_master_is_written_in_millimetres(demo_stage):
    """OCCT's STEP length unit is the millimetre; the shape is scaled into it."""
    text = (demo_stage / "assets" / "crate_lid.step").read_text(encoding="utf-8")
    assert text.startswith("ISO-10303-21;")
    assert "SI_UNIT(.MILLI.,.METRE.)" in text
    assert "1970-01-01T00:00:00" in text


def test_the_step_master_holds_the_right_size(demo_stage):
    """The master and the GLB are the same part at two scales."""
    import re

    text = (demo_stage / "assets" / "crate_lid.step").read_text(encoding="utf-8")
    numbers = re.findall(r"CARTESIAN_POINT\('',\(([^)]*)\)", text)
    values = []
    for triple in numbers:
        parts = [float(v) for v in triple.split(",")]
        if len(parts) == 3:  # the 2D points are pcurves, not geometry
            values.append(tuple(parts))
    xs = [v[0] for v in values]
    ys = [v[1] for v in values]
    zs = [v[2] for v in values]
    # The STEP is in millimetres: 0.6 m wide, 0.4 m deep, 0.06 m tall (the handle).
    assert max(xs) - min(xs) == pytest.approx(600.0, abs=1e-3), "the STEP is not 600 mm wide"
    assert max(ys) - min(ys) == pytest.approx(400.0, abs=1e-3), "the STEP is not 400 mm deep"
    assert max(zs) - min(zs) == pytest.approx(60.0, abs=1e-3), "the STEP is not 60 mm tall"


def test_the_part_is_built_from_a_closed_set_of_scripts():
    with pytest.raises(ValueError):
        cad.build_part("not_a_part", {})
    with pytest.raises(ValueError):
        cad.build_part("hinge_bracket", {"not_a_parameter": 1.0})


def test_the_parts_share_a_script_when_they_are_the_same(tmp_path, demo_source_and_records):
    """Two entries with the same script share one asset — the stage cache's cousin."""
    from builder_usd.compile import compile_recipe

    source, records = demo_source_and_records
    result = compile_recipe(source, tmp_path / "stage", records)
    glb_paths = {asset.glb.path for asset in result.assets.values()}
    assert len(glb_paths) == len(result.assets), "one asset was compiled twice"
