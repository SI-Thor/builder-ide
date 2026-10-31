"""The executor seam — where the night's work happens.

In this seat the work is **simulated**: scripted fake tasks with injected
failures, not real renders (§"Tasks are simulated in this job"). The seam is
the important part — the runner asks an executor what a task will cost and
which model it needs *before* the spend, then runs it. When the engine and
the GPU stations land, they implement the same two methods and the night
runner does not change.
"""

from __future__ import annotations

import pytest

from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.models import Task


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(
        id=task_id,
        intention=kwargs.pop("intention", "Forest the east slope, keep the oak"),
        **kwargs,
    )


def test_a_scripted_task_plans_the_cost_it_will_spend():
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0, model="trellis2")}
    )
    plan = executor.plan(a_task())
    assert plan.gpu_minutes == 30.0
    assert plan.wall_minutes == 45.0
    assert plan.model == "trellis2"
    assert plan.outcome == "kept"


def test_an_injected_failure_is_planned_with_its_reason():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=12.0,
                wall_minutes=20.0,
                outcome="failed",
                reason="hollow mesh from the image-to-3D model",
                artifact="artifacts/ab/ab1234.png",
            )
        }
    )
    plan = executor.plan(a_task())
    assert plan.outcome == "failed"
    assert plan.reason == "hollow mesh from the image-to-3D model"
    assert plan.artifact == "artifacts/ab/ab1234.png"


def test_an_unscripted_task_costs_its_own_ask_and_is_kept():
    executor = ScriptedExecutor({})
    plan = executor.plan(a_task(cost_estimate={"gpu_minutes": 5.0, "wall_minutes": 9.0}))
    assert plan.gpu_minutes == 5.0
    assert plan.wall_minutes == 9.0
    assert plan.outcome == "kept"
    assert plan.model is None


def test_a_script_may_carry_the_sealed_bets_and_their_verdicts():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                predictions=[
                    {
                        "prediction_id": "pr_0001",
                        "builder": "prop-maker",
                        "claim_type": "shadow_count",
                        "claim": "the crates will read weathered",
                        "confidence": "guess",
                        "basis": "0 observations",
                    }
                ],
                verdicts=[{"prediction_id": "pr_0001", "verdict": "hit"}],
            )
        }
    )
    plan = executor.plan(a_task())
    assert plan.predictions[0]["prediction_id"] == "pr_0001"
    assert plan.verdicts[0]["verdict"] == "hit"


def test_a_degraded_verdict_is_carried_on_the_plan():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                verdicts=[{"prediction_id": "pr_0001", "verdict": "hit", "degraded": True}],
            )
        }
    )
    assert executor.plan(a_task()).verdicts[0]["degraded"] is True


def test_the_plan_carries_the_branches_the_task_opened():
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(branches=["br_07f2", "br_07f3"])}
    )
    assert executor.plan(a_task()).branches == ["br_07f2", "br_07f3"]


def test_running_a_task_advances_the_clock_by_the_work_it_did():
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    plan = executor.plan(a_task())
    assert plan.wall_minutes == 45.0


def test_a_task_that_is_not_in_the_script_raises_when_asked_to_run_it():
    executor = ScriptedExecutor({})
    with pytest.raises(KeyError):
        executor.run(a_task())
