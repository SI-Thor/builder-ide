"""The builder and the checker: the model, and what the run says.

These are the tests the brief asks for — the MJCF builder and the checker
are deterministic, and neither needs a GPU. The meshes here are synthetic
boxes, so every number in the assertions is a number the test knows.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest

from core.physag.check import check_prop
from core.physag.decompose import decompose_part
from core.physag.geometry import load_mesh
from core.physag.mjcf import build_mjcf
from core.physag.pipeline import run_prop
from core.physag.segment import segment

from .fixtures import crate_mesh, write_glb
from .test_spec import make_spec

BASIS = {
    "mass_kg": "estimated",
    "friction": "estimated",
    "actuator_force_n": "estimated",
    "actuator_torque_nm": "estimated",
    "base_static": "estimated",
}


@pytest.fixture()
def crate_glb(tmp_path):
    vertices, triangles = crate_mesh()
    return write_glb(tmp_path / "crate.glb", vertices, triangles)


def _build(spec, mesh_path):
    mesh = load_mesh(mesh_path)
    segmentation = segment(mesh, spec)
    decompositions = {}
    from core.physag.pipeline import _decompose_all

    decompositions = _decompose_all(segmentation, spec, 0.004, 24)
    built = build_mjcf(spec, segmentation, decompositions)
    return built, segmentation, decompositions


def test_the_model_compiles_in_mujoco(crate_glb):
    spec = make_spec()
    built, _, _ = _build(spec, crate_glb)
    model = mujoco.MjModel.from_xml_string(built.xml)
    assert model.nbody >= 3  # the world, the body, the lid
    assert model.nu == 1


def test_the_base_is_free_unless_the_spec_says_otherwise(crate_glb):
    spec = make_spec()
    built, _, _ = _build(spec, crate_glb)
    assert built.free_base
    model = mujoco.MjModel.from_xml_string(built.xml)
    # a free joint on the base: the base can tip over
    assert model.jnt_type[0] == mujoco.mjtJoint.mjJNT_FREE


def test_a_static_base_is_welded(crate_glb):
    spec = make_spec(
        priors=spec_priors(base_static=True),
    )
    built, _, _ = _build(spec, crate_glb)
    assert not built.free_base


def spec_priors(base_static: bool = False):
    from core.physag.spec import Priors

    return Priors(
        mass_kg=12.0,
        friction=0.6,
        actuator_force_n=90.0,
        actuator_torque_nm=18.0,
        base_static=base_static,
    )


def test_the_actuator_is_capped_at_the_prior(crate_glb):
    spec = make_spec()
    built, _, _ = _build(spec, crate_glb)
    model = mujoco.MjModel.from_xml_string(built.xml)
    actuator = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_ACTUATOR, "lid_hinge_actuator"
    )
    limits = model.actuator_forcerange[actuator]
    assert limits[1] == pytest.approx(spec.priors.actuator_torque_nm)


def test_the_collider_is_not_fatter_than_the_mesh(crate_glb):
    spec = make_spec()
    built, _, _ = _build(spec, crate_glb)
    assert built.inflation <= 0.01
    assert built.collider_deviation_m < 0.02


def test_the_parts_do_not_interpenetrate_at_the_first_step(crate_glb):
    spec = make_spec()
    built, segmentation, _ = _build(spec, crate_glb)
    result = check_prop(built, segmentation, rest_s=0.5)
    assert result.rest is not None
    assert result.rest.initial_penetrations == 0


def test_the_check_reports_a_band_relative_to_the_joint(crate_glb):
    spec = make_spec()
    built, segmentation, _ = _build(spec, crate_glb)
    result = check_prop(built, segmentation, rest_s=0.5)
    completion = result.completion
    assert completion is not None
    travel = math.radians(90.0)
    assert completion.tolerance.absolute == pytest.approx(spec.action.tolerance_rel * travel)
    assert "travel" in completion.tolerance.basis


def test_the_check_records_the_peak_force_and_the_limit(crate_glb):
    spec = make_spec()
    built, segmentation, _ = _build(spec, crate_glb)
    result = check_prop(built, segmentation, rest_s=0.5)
    assert result.stability is not None
    assert result.stability.force_limit == pytest.approx(spec.priors.actuator_torque_nm)
    assert result.stability.peak_force <= result.stability.force_limit * 1.001


def test_a_prop_that_cannot_move_the_joint_does_not_complete(crate_glb):
    # The target is beyond what the actuator can do in the time given.
    spec = make_spec(
        priors=spec_priors(),
    )
    from dataclasses import replace

    spec = replace(spec, priors=spec_priors())
    spec = replace(
        spec,
        priors=spec_priors(),
    )
    tight = make_spec()
    tight = replace(tight, priors=spec_priors())
    # a very weak actuator and a very short deadline
    from core.physag.spec import Priors

    tight = replace(
        tight,
        priors=Priors(
            mass_kg=12.0,
            friction=0.6,
            actuator_force_n=1.0,
            actuator_torque_nm=0.01,
        ),
    )
    built, segmentation, _ = _build(tight, crate_glb)
    result = check_prop(built, segmentation, rest_s=0.5)
    assert result.completion is not None
    assert not result.completion.completed


def test_a_completion_that_reached_the_target_but_drifted_is_not_a_completion():
    from core.physag.check import _score_completion
    from core.physag.spec import Action

    action = Action(kind="joint", joint="j", target=1.0, dwell_steps=5)
    tolerance = type("T", (), {"absolute": 0.05, "relative": 0.02, "basis": "test"})()
    # the joint reaches the target, then leaves the band
    trajectory = [0.0, 0.5, 1.0, 1.0, 1.4, 1.6, 1.7, 1.8]
    score = _score_completion(
        action=action,
        trajectory=trajectory,
        target=1.0,
        tolerance=tolerance,
        timestep=0.002,
    )
    assert score.first_entry_step == 2
    assert not score.dwell_satisfied
    assert not score.completed


def test_a_completion_that_holds_the_band_is_a_completion():
    from core.physag.check import _score_completion
    from core.physag.spec import Action

    action = Action(kind="joint", joint="j", target=1.0, dwell_steps=5)
    tolerance = type("T", (), {"absolute": 0.05, "relative": 0.02, "basis": "test"})()
    trajectory = [0.0, 0.5, 1.0, 1.0, 0.99, 1.01, 1.0, 1.0]
    score = _score_completion(
        action=action,
        trajectory=trajectory,
        target=1.0,
        tolerance=tolerance,
        timestep=0.002,
    )
    assert score.completed
    assert score.dwell_satisfied
    assert score.first_entry_step == 2


def test_the_overrun_and_the_settling_time_are_reported():
    from core.physag.check import _score_completion
    from core.physag.spec import Action

    action = Action(kind="joint", joint="j", target=1.0, dwell_steps=3)
    tolerance = type("T", (), {"absolute": 0.05, "relative": 0.02, "basis": "test"})()
    trajectory = [0.0, 1.0, 1.2, 1.1, 1.02, 1.0, 1.0, 1.0]
    score = _score_completion(
        action=action,
        trajectory=trajectory,
        target=1.0,
        tolerance=tolerance,
        timestep=0.01,
    )
    assert score.completed
    assert score.overshoot == pytest.approx(0.2, abs=1e-6)
    assert score.settling_time_s == pytest.approx(0.01)


def test_the_decomposition_of_a_box_is_one_convex_piece():
    from .fixtures import box_mesh

    vertices, triangles = box_mesh((0.4, 0.4, 0.4))
    from core.physag.geometry import MeshPart

    part = MeshPart(vertices=vertices, triangles=triangles)
    decomp = decompose_part(part, "box", tol_m=0.002)
    assert decomp.piece_count == 1
    assert decomp.collider_volume == pytest.approx(0.064, rel=0.02)


def test_the_clipped_piece_keeps_its_volume():
    from core.physag.decompose import clip_convex
    from core.physag.geometry import convex_hull

    from .fixtures import box_mesh

    vertices, triangles = box_mesh((0.4, 0.4, 0.4))
    hull = convex_hull(vertices)
    clipped = clip_convex(hull, np.array([0.0, 0.0, -1.0]), 0.0)
    # keeping z >= 0 of a box centred on the origin keeps half of it
    assert clipped.volume == pytest.approx(0.032, rel=0.02)


def test_the_run_writes_the_model_and_the_record(crate_glb, tmp_path):
    spec = make_spec()
    out = tmp_path / "out"
    run = run_prop(spec, crate_glb, out_dir=out, allow_repair=False)
    assert (out / "model.xml").exists()
    assert run.result is not None
    assert run.timings["check_s"] > 0
