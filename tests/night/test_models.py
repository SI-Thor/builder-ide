"""The scheduler's records (core-spec v2 §1.9).

These tests pin the shapes the night runner depends on: the three-axis rail
and its arithmetic, and the states the queue and the report read.
"""

from __future__ import annotations

import pytest

from core.night.models import Actor, Job, Night, Rail, Task


def test_rail_adds_three_axes():
    spent = Rail(gpu_minutes=12.5, hosted_cents=3, wall_minutes=40.0).add(
        Rail(gpu_minutes=2.5, hosted_cents=1, wall_minutes=5.0)
    )
    assert spent == Rail(gpu_minutes=15.0, hosted_cents=4, wall_minutes=45.0)


def test_rail_subtracts_to_the_remaining_budget():
    ceiling = Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0)
    spent = Rail(gpu_minutes=120.0, hosted_cents=0, wall_minutes=60.0)
    assert ceiling.subtract(spent) == Rail(
        gpu_minutes=240.0, hosted_cents=0, wall_minutes=500.0
    )


def test_rail_fits_is_false_when_one_axis_is_over():
    ceiling = Rail(gpu_minutes=10.0, hosted_cents=0, wall_minutes=60.0)
    assert ceiling.fits(Rail(gpu_minutes=9.0, wall_minutes=59.0))
    assert not ceiling.fits(Rail(gpu_minutes=11.0, wall_minutes=10.0))


def test_rail_is_zero_only_when_every_axis_is_zero():
    assert Rail().is_zero
    assert not Rail(gpu_minutes=0.1).is_zero
    assert not Rail(hosted_cents=1).is_zero
    assert not Rail(wall_minutes=1.0).is_zero


def test_task_exists_before_any_night_with_the_ask_stored():
    """RV patch 11 — the slate is first-class; the ask is what the morning cuts against."""
    task = Task(id="task_0001", intention="Forest the east slope, keep the oak")
    assert task.night is None
    assert task.state == "slated"
    assert task.cost_estimate == Rail()


def test_night_carries_rails_a_load_budget_and_no_status_yet():
    night = Night(
        id="night_2026-10-30",
        started_at="2026-10-30T21:14:00Z",
        rails=Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        load_budget={"trellis2": 1},
    )
    assert night.status is None
    assert night.state == "starting"
    assert night.batch_start == "both"


def test_job_defaults_to_the_thor_and_the_cpu_lane_is_not_the_default():
    job = Job(id="job_0001", lane="gpu", model="trellis2")
    assert job.worker == "thor"
    assert job.state == "queued"
    assert job.outputs == []


def test_actor_is_frozen_so_an_event_cannot_be_retold():
    actor = Actor(kind="scheduler", id="night-runner")
    with pytest.raises(Exception):
        actor.id = "someone-else"
