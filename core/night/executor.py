"""The executor seam — where the night's work happens.

In this seat the work is **simulated**: scripted fake tasks with injected
failures, not real renders. The seam is the part that matters. The runner
asks an executor two things — *what will this task cost and which model does
it need* (checked before the spend, §5.5) and *run it* — and when the engine
and the GPU stations land, they implement the same two methods and the night
runner does not change.

A third thing arrived with the iterator loop: the **variant**. A task is no
longer one attempt — the night renders N candidates and keeps the best — so
the seam now takes the candidate too. ``variant=None`` is the old contract
exactly: the task itself, one attempt.
"""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.night.iterate import Variant
from core.night.models import Task

__all__ = [
    "ExecutionPlan",
    "ScriptedExecutor",
    "ScriptedTask",
    "ScriptedVariant",
    "TaskExecutor",
]

TaskOutcome = Literal["kept", "reverted", "failed", "parked"]


class ExecutionPlan(BaseModel):
    """What a task will cost and what it will do."""

    model: str | None = None
    gpu_minutes: float = 0.0
    hosted_cents: int = 0
    wall_minutes: float = 0.0
    stall_minutes: float = 0.0
    stall_reason: str | None = None
    outcome: TaskOutcome = "kept"
    reason: str | None = None
    degraded: bool = False
    artifact: str | None = None
    branches: list[str] = Field(default_factory=list)
    predictions: list[dict] = Field(default_factory=list)
    verdicts: list[dict] = Field(default_factory=list)


class ScriptedVariant(BaseModel):
    """The script for one *variant* of a task.

    A field left as ``None`` is inherited from the task's own script, so a
    scenario only scripts the part it cares about — the variant that costs
    more, or the one that comes back hollow.
    """

    gpu_minutes: float | None = None
    hosted_cents: int = 0
    wall_minutes: float | None = None
    actual_wall_minutes: float | None = None
    outcome: TaskOutcome = "kept"
    reason: str | None = None
    degraded: bool = False
    artifact: str | None = None


class ScriptedTask(BaseModel):
    """The script for one simulated task.

    ``None`` costs fall back to the task's own ask (the estimate stored on the
    slate), so a scenario only scripts the part it cares about.
    """

    model: str | None = None
    gpu_minutes: float | None = None
    hosted_cents: int = 0
    wall_minutes: float | None = None
    actual_wall_minutes: float | None = None
    stall_minutes: float = 0.0
    stall_reason: str | None = None
    outcome: TaskOutcome = "kept"
    reason: str | None = None
    degraded: bool = False
    artifact: str | None = None
    branches: list[str] = Field(default_factory=list)
    predictions: list[dict] = Field(default_factory=list)
    verdicts: list[dict] = Field(default_factory=list)
    #: Per-variant scripts, by variant id.
    variants: dict[str, ScriptedVariant] = Field(default_factory=dict)


@runtime_checkable
class TaskExecutor(Protocol):
    """What the runner asks of the world."""

    def plan(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        """What this task will cost, and which model it needs.

        Called **before** the spend: admission control projects the cost and
        refuses what a rail cannot cover (§5.5). When the night is iterating,
        the cost asked for is the *variant's* cost — the candidate the night
        is about to render.
        """

    def run(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        """Do the work; report what it actually cost and what it produced."""


class ScriptedExecutor:
    """The simulated work: scripted tasks with injected failures."""

    def __init__(self, scripts: Mapping[str, ScriptedTask] | None = None) -> None:
        self._scripts: dict[str, ScriptedTask] = dict(scripts or {})

    def script(self, task_id: str, script: ScriptedTask) -> "ScriptedExecutor":
        """Add or replace one task's script; returns self, so it chains."""
        self._scripts[task_id] = script
        return self

    def plan(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        script = self._scripts.get(task.id)
        if script is None:
            return ExecutionPlan(
                gpu_minutes=task.cost_estimate.gpu_minutes,
                hosted_cents=task.cost_estimate.hosted_cents,
                wall_minutes=task.cost_estimate.wall_minutes,
            )
        plan = ExecutionPlan(
            model=script.model,
            gpu_minutes=(
                task.cost_estimate.gpu_minutes
                if script.gpu_minutes is None
                else script.gpu_minutes
            ),
            hosted_cents=script.hosted_cents,
            wall_minutes=(
                task.cost_estimate.wall_minutes
                if script.wall_minutes is None
                else script.wall_minutes
            ),
            outcome=script.outcome,
            reason=script.reason,
            degraded=script.degraded,
            artifact=script.artifact,
            stall_minutes=script.stall_minutes,
            stall_reason=script.stall_reason,
            branches=list(script.branches),
            predictions=[dict(prediction) for prediction in script.predictions],
            verdicts=[dict(verdict) for verdict in script.verdicts],
        )
        return self._with_variant(plan, script, variant)

    def run(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        if task.id not in self._scripts:
            raise KeyError(f"no script for task {task.id!r}")
        script = self._scripts[task.id]
        plan = self.plan(task, variant)
        actual = script.actual_wall_minutes
        if variant is not None:
            variant_script = script.variants.get(variant.id)
            if variant_script is not None and variant_script.actual_wall_minutes is not None:
                actual = variant_script.actual_wall_minutes
        if actual is not None:
            # The work overran its projection; the rail decides what happens
            # to it, not the script (§5.5).
            plan = plan.model_copy(update={"wall_minutes": actual})
        return plan

    def _with_variant(
        self, plan: ExecutionPlan, script: ScriptedTask, variant: Variant | None
    ) -> ExecutionPlan:
        """A variant's script over the task's own, field by field."""
        if variant is None:
            return plan
        variant_script = script.variants.get(variant.id)
        if variant_script is None:
            return plan
        updates: dict = {}
        if variant_script.gpu_minutes is not None:
            updates["gpu_minutes"] = variant_script.gpu_minutes
        if variant_script.wall_minutes is not None:
            updates["wall_minutes"] = variant_script.wall_minutes
        if variant_script.hosted_cents:
            updates["hosted_cents"] = variant_script.hosted_cents
        if variant_script.outcome != "kept":
            updates["outcome"] = variant_script.outcome
        if variant_script.reason is not None:
            updates["reason"] = variant_script.reason
        if variant_script.degraded:
            updates["degraded"] = True
        if variant_script.artifact is not None:
            updates["artifact"] = variant_script.artifact
        return plan.model_copy(update=updates)
