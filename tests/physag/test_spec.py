"""The spec: what it accepts, what it refuses, and what it freezes.

The spec is the contract, so the tests are about the contract: a spec
that names a joint with no child is refused, a prior with no basis is
refused, and a repair that moves the action is caught.
"""

from __future__ import annotations

import math

import pytest

from core.physag.spec import (
    Action,
    Box,
    Cut,
    InteractionSpec,
    Joint,
    Part,
    Priors,
    SpecError,
    load_spec,
    repair_is_allowed,
    save_spec,
    spec_diff,
)

BASIS = {
    "mass_kg": "estimated",
    "friction": "estimated",
    "actuator_force_n": "estimated",
    "actuator_torque_nm": "estimated",
    "base_static": "estimated",
}


def make_spec(**overrides) -> InteractionSpec:
    """A valid crate spec, with the given fields replaced."""
    data = {
        "prop": "crate",
        "kind": "crate",
        "image_prompt": "a weathered wooden crate",
        "parts": (
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="plane", axis="z", at=0.8, keep="above"),
                expect=Box(min=(0.0, 0.0, 0.8), max=(1.0, 1.0, 1.0)),
            ),
        ),
        "joints": (
            Joint(
                name="lid_hinge",
                type="hinge",
                parent="body",
                child="lid",
                axis=(1.0, 0.0, 0.0),
                anchor=(0.5, 0.0, 0.8),
                low=0.0,
                high=math.radians(90.0),
            ),
        ),
        "action": Action(kind="joint", joint="lid_hinge", target=math.radians(90.0)),
        "priors": Priors(mass_kg=12.0, friction=0.6, actuator_force_n=90.0, actuator_torque_nm=18.0),
        "basis": dict(BASIS),
        "planner": {"model": "test"},
    }
    data.update(overrides)
    return InteractionSpec(**data)


def test_a_valid_spec_validates():
    make_spec().validate()


def test_the_parts_must_name_a_joint_that_exists():
    with pytest.raises(SpecError, match="no parent part"):
        make_spec(
            joints=(
                Joint(
                    name="lid_hinge",
                    type="hinge",
                    parent="nowhere",
                    child="lid",
                    axis=(1.0, 0.0, 0.0),
                    anchor=(0.5, 0.0, 0.8),
                    low=0.0,
                    high=1.0,
                ),
            )
        ).validate()


def test_the_action_target_must_be_inside_the_joint_limits():
    with pytest.raises(SpecError, match="outside joint"):
        make_spec(action=Action(kind="joint", joint="lid_hinge", target=3.0)).validate()


def test_every_prior_must_say_where_it_came_from():
    with pytest.raises(SpecError, match="no basis"):
        make_spec(basis={"mass_kg": "estimated"}).validate()


def test_an_unknown_basis_is_refused():
    basis = dict(BASIS)
    basis["mass_kg"] = "guessed"
    with pytest.raises(SpecError, match="unknown basis"):
        make_spec(basis=basis).validate()


def test_exactly_one_base_and_one_rest():
    parts = (
        Part(name="body", role="moving", cut=Cut(kind="rest")),
        Part(name="lid", role="moving", cut=Cut(kind="plane", axis="z", at=0.8, keep="above")),
    )
    with pytest.raises(SpecError, match="base parts"):
        make_spec(parts=parts).validate()


def test_the_spec_round_trips_through_json(tmp_path):
    spec = make_spec()
    path = save_spec(spec, tmp_path / "crate.json")
    again = load_spec(path)
    assert again.to_dict() == spec.to_dict()


def test_a_spec_that_does_not_validate_is_refused_on_the_way_in(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"prop": "crate"}')
    with pytest.raises(SpecError):
        load_spec(path)


def test_a_repair_may_not_move_the_action():
    before = make_spec()
    after = make_spec(action=Action(kind="joint", joint="lid_hinge", target=math.radians(45.0)))
    allowed, moved = repair_is_allowed(before, after)
    assert not allowed
    assert "action.target" in moved


def test_a_repair_may_not_widen_the_joint_limits():
    before = make_spec()
    joint = Joint(
        name="lid_hinge",
        type="hinge",
        parent="body",
        child="lid",
        axis=(1.0, 0.0, 0.0),
        anchor=(0.5, 0.0, 0.8),
        low=0.0,
        high=math.radians(120.0),
    )
    after = make_spec(joints=(joint,))
    allowed, moved = repair_is_allowed(before, after)
    assert not allowed
    assert "joint.lid_hinge.high" in moved


def test_a_repair_may_not_give_itself_more_time():
    before = make_spec()
    after = make_spec(
        action=Action(
            kind="joint", joint="lid_hinge", target=math.radians(90.0), duration_s=30.0
        )
    )
    allowed, _ = repair_is_allowed(before, after)
    assert not allowed


def test_a_repair_may_change_the_priors():
    before = make_spec()
    after = make_spec(
        priors=Priors(
            mass_kg=12.0,
            friction=0.6,
            actuator_force_n=90.0,
            actuator_torque_nm=40.0,
        )
    )
    allowed, moved = repair_is_allowed(before, after)
    assert allowed
    assert moved == []
    diff = spec_diff(before, after)
    assert "priors.actuator_torque_nm" in diff["changed"]


def test_a_repair_may_change_the_segmentation():
    before = make_spec()
    after = make_spec(
        parts=(
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="plane", axis="z", at=0.7, keep="above"),
                expect=Box(min=(0.0, 0.0, 0.7), max=(1.0, 1.0, 1.0)),
            ),
        )
    )
    allowed, _ = repair_is_allowed(before, after)
    assert allowed


def test_the_claim_is_the_cut_when_the_planner_gives_none():
    part = Part(name="lid", role="moving", cut=Cut(kind="plane", axis="z", at=0.8, keep="above"))
    claim = part.claimed_box()
    assert claim.min[2] == pytest.approx(0.8)
    assert claim.max[2] == pytest.approx(1.0)


def test_a_cut_outside_the_mesh_is_refused():
    with pytest.raises(SpecError, match="outside the mesh"):
        Part(
            name="lid",
            role="moving",
            cut=Cut(kind="plane", axis="z", at=1.4, keep="above"),
        ).validate()
