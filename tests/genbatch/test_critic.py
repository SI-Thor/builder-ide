"""The scripted critic: the judgement that picks the night's winner.

The critic is a set of checks, each graded from 0 to 1, so two props that
both fail the same check can still be told apart — a binary pass/fail would
make the winner arbitrary whenever every prop fails the same way.

The checks are the brief's three (watertightness, the triangle budget, the
bounding box against the request) plus the oracle-style ones SolidCraft
uses: volume, area and centre of mass (docs/research/solidcraft.md).
"""

from __future__ import annotations

import pytest

from core.genbatch.critic import PropCritic, judge
from core.genbatch.mesh import MeshReport
from core.genbatch.models import PropRequest
from core.genbatch.store import PropStore
from core.night.iterate import CriticScore, Variant
from core.records import Task


def _report(**overrides) -> MeshReport:
    """A cube: closed, consistently wound, 12 triangles, volume 1."""
    base = dict(
        triangles=12,
        vertices=8,
        watertight=True,
        consistent_winding=True,
        boundary_edges=0,
        nonmanifold_edges=0,
        degenerate_triangles=0,
        bbox_min=(-0.5, -0.5, -0.5),
        bbox_max=(0.5, 0.5, 0.5),
        extent=(1.0, 1.0, 1.0),
        volume=1.0,
        area=6.0,
        centre_of_mass=(0.0, 0.0, 0.0),
        diagonal=1.7320508075688772,
    )
    base.update(overrides)
    return MeshReport(**base)


def _request(**overrides) -> PropRequest:
    base = dict(id="crate", prompt="a weathered wooden crate")
    base.update(overrides)
    return PropRequest(**base)


def _checks(verdict, name):
    return next(check for check in verdict.checks if check.name == name)


def test_a_perfect_prop_scores_full_marks():
    request = _request(expected_aspect=(1.0, 1.0, 1.0), triangle_budget=12)

    verdict = judge(_report(), request)

    assert verdict.score == pytest.approx(1.0)
    assert all(check.passed for check in verdict.checks)


def test_a_mesh_with_a_hole_fails_the_watertight_check():
    request = _request(expected_aspect=(1.0, 1.0, 1.0))

    verdict = judge(
        _report(watertight=False, boundary_edges=4, volume=0.0), request
    )

    check = _checks(verdict, "watertight")
    assert check.passed is False
    assert check.score == 0.0
    assert "boundary" in check.detail
    assert verdict.score < 1.0


def test_a_mesh_over_the_budget_fails_the_budget_check():
    request = _request(expected_aspect=(1.0, 1.0, 1.0), triangle_budget=10)

    verdict = judge(_report(), request)

    check = _checks(verdict, "triangle_budget")
    assert check.passed is False
    assert "12" in check.detail and "10" in check.detail


def test_the_wrong_shape_is_caught_against_the_request():
    # A shield is flat: the request says so, and the prop came out cubic.
    request = _request(expected_aspect=(1.0, 1.0, 0.1))

    verdict = judge(_report(), request)

    check = _checks(verdict, "bbox_aspect")
    assert check.passed is False
    assert check.score < 1.0
    assert "aspect" in check.detail


def test_the_shape_check_is_skipped_when_the_request_states_no_shape():
    request = _request()

    verdict = judge(_report(), request)

    assert "bbox_aspect" not in {check.name for check in verdict.checks}
    assert verdict.score == pytest.approx(1.0)


def test_a_shell_is_caught_by_the_volume_check():
    request = _request(expected_aspect=(1.0, 1.0, 1.0), fill_ratio=(0.05, 0.9))

    verdict = judge(_report(volume=0.001), request)

    check = _checks(verdict, "solid_volume")
    assert check.passed is False


def test_a_centre_of_mass_outside_the_box_is_caught():
    request = _request(expected_aspect=(1.0, 1.0, 1.0))

    verdict = judge(_report(centre_of_mass=(0.9, 0.9, 0.9)), request)

    check = _checks(verdict, "centre_of_mass")
    assert check.passed is False


def test_an_impossible_surface_is_caught():
    # A closed solid cannot have less surface than a sphere of the same
    # volume; a mesh that does is not measuring what it thinks it is.
    request = _request(expected_aspect=(1.0, 1.0, 1.0))

    verdict = judge(_report(area=2.0), request)

    check = _checks(verdict, "surface")
    assert check.passed is False


def test_degenerate_triangles_are_counted_against_the_prop():
    request = _request(expected_aspect=(1.0, 1.0, 1.0))

    verdict = judge(_report(degenerate_triangles=3), request)

    check = _checks(verdict, "degenerate")
    assert check.passed is False
    assert check.score == pytest.approx(0.75)


def test_the_verdict_names_what_failed():
    request = _request(expected_aspect=(1.0, 1.0, 0.1), triangle_budget=5)

    verdict = judge(_report(), request)

    assert "watertight" not in verdict.reason
    assert "triangle" in verdict.reason
    assert "aspect" in verdict.reason


def test_the_critic_scores_a_variant_through_the_core_seam():
    request = _request(expected_aspect=(1.0, 1.0, 1.0))
    task = Task(id="prop:crate", intention="a weathered wooden crate")
    variant = Variant(id="prop:crate_r1_v1", seed=1)
    store = PropStore()
    store.record_mesh("prop:crate", variant.id, _report())
    critic = PropCritic(requests={"prop:crate": request}, store=store)

    score = critic.score(task, variant)

    assert isinstance(score, CriticScore)
    assert score.score == pytest.approx(1.0)


def test_the_critic_does_not_invent_a_score_for_a_prop_it_never_measured():
    task = Task(id="prop:crate", intention="a weathered wooden crate")
    variant = Variant(id="prop:crate_r1_v1", seed=1)
    critic = PropCritic(requests={"prop:crate": _request()}, store=PropStore())

    score = critic.score(task, variant)

    assert score.score == 0.0
    assert "no mesh" in score.reason.lower()
