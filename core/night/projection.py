"""The projection: the night rebuilt by folding the audit log.

Core-spec v2 §1.0 makes the audit table the source of truth and every other
table a projection rebuilt by folding it. The night runner leans on that
harder than any other seat: the status line, the cut and the morning report
are all folds, which is what makes them survive the failure they describe
(§3.4, §5.4).

The fold is pure — it reads events and writes nothing back — so a projection
can be rebuilt from the log at any time, including after a kill -9.
"""

from __future__ import annotations

from typing import Any, Sequence

from core.night.models import AuditEvent, Night, Rail, Task

__all__ = ["NightProjection"]


class NightProjection:
    """Everything the night runner knows, folded out of the log."""

    def __init__(self, events: Sequence[AuditEvent]) -> None:
        self.night: Night | None = None
        self.tasks: dict[str, Task] = {}
        self.task_reasons: dict[str, str] = {}
        self.ticks: list[AuditEvent] = []
        self.preflight: dict[str, Any] | None = None
        self.spend = Rail()
        self.model_loads: dict[str, int] = {}
        self.client_attached_at: str | None = None
        self.client_detached_at: str | None = None
        self.questions: list[dict[str, Any]] = []
        self.assumptions: list[dict[str, Any]] = []
        self.predictions: dict[str, dict[str, Any]] = {}
        self.failures: list[dict[str, Any]] = []
        self.branches: list[dict[str, Any]] = []
        self.work_orders: list[dict[str, Any]] = []
        self.model_changes: list[dict[str, Any]] = []
        self.thresholds: list[dict[str, Any]] = []
        self.kill_switch = False
        self.reports: list[str] = []
        self.booted = False
        self.recovered = False
        self.job_outcomes: list[dict[str, Any]] = []
        self._fold(events)

    # -- the fold ---------------------------------------------------------

    def _fold(self, events: Sequence[AuditEvent]) -> None:
        for event in events:
            handler = getattr(self, f"_on_{event.type.replace('.', '_')}", None)
            if handler is not None:
                handler(event)

    def _on_night_started(self, event: AuditEvent) -> None:
        payload = event.payload
        self.night = Night(
            id=payload["night_id"],
            started_at=event.at,
            rails=Rail(**payload.get("rails", {})),
            load_budget=dict(payload.get("load_budget", {})),
            power_mode=int(payload.get("power_mode", 0)),
            batch_start=payload.get("batch_start", "both"),
            detach_deadline=payload.get("detach_deadline"),
        )

    def _on_night_stopped(self, event: AuditEvent) -> None:
        if self.night is None:
            return
        self.night.stopped_at = event.at
        if self.night.status is None:
            self.night.status = event.payload.get("status")
        self.night.report = event.payload.get("report")

    def _on_night_preflight(self, event: AuditEvent) -> None:
        self.preflight = event.payload

    def _on_night_tick(self, event: AuditEvent) -> None:
        self.ticks.append(event)

    def _on_night_task_created(self, event: AuditEvent) -> None:
        task = Task.model_validate(event.payload["task"])
        self.tasks[task.id] = task

    def _on_night_task_state(self, event: AuditEvent) -> None:
        payload = event.payload
        task = self.tasks.get(payload["task_id"])
        if task is None:
            return
        task.state = payload["state"]
        if payload.get("reason"):
            self.task_reasons[task.id] = payload["reason"]

    def _on_budget_spend(self, event: AuditEvent) -> None:
        payload = event.payload
        axis = payload["axis"]
        amount = payload["amount"]
        self.spend = self.spend.add(
            Rail(
                gpu_minutes=amount if axis == "gpu_minutes" else 0.0,
                hosted_cents=int(amount) if axis == "hosted_cents" else 0,
                wall_minutes=amount if axis == "wall_minutes" else 0.0,
            )
        )

    def _on_budget_threshold(self, event: AuditEvent) -> None:
        self.thresholds.append(event.payload)

    def _on_kill_switch(self, event: AuditEvent) -> None:
        self.kill_switch = True

    def _on_sched_model_load(self, event: AuditEvent) -> None:
        model = event.payload["model"]
        self.model_loads[model] = self.model_loads.get(model, 0) + 1

    def _on_client_attach(self, event: AuditEvent) -> None:
        self.client_attached_at = event.at

    def _on_client_detach(self, event: AuditEvent) -> None:
        self.client_detached_at = event.at

    def _on_question_parked(self, event: AuditEvent) -> None:
        question = dict(event.payload)
        question["assumptions"] = []
        self.questions.append(question)

    def _on_assumption_recorded(self, event: AuditEvent) -> None:
        assumption = dict(event.payload)
        self.assumptions.append(assumption)
        for question in self.questions:
            if question.get("question_id") == assumption.get("question_id"):
                question["assumptions"].append(assumption["assumption"])

    def _on_prediction_sealed(self, event: AuditEvent) -> None:
        prediction = dict(event.payload)
        prediction["sealed_at"] = event.at
        self.predictions[prediction["prediction_id"]] = prediction

    def _on_prediction_scored(self, event: AuditEvent) -> None:
        prediction = self.predictions.get(event.payload["prediction_id"])
        if prediction is not None:
            prediction["verdict"] = event.payload["verdict"]

    def _on_job_done(self, event: AuditEvent) -> None:
        payload = event.payload
        self.job_outcomes.append(payload)
        if payload.get("outcome") == "failed":
            self.failures.append(payload)

    def _on_branch_created(self, event: AuditEvent) -> None:
        self.branches.append(event.payload)

    def _on_wo_landed(self, event: AuditEvent) -> None:
        self.work_orders.append(event.payload)

    def _on_model_change_noticed(self, event: AuditEvent) -> None:
        self.model_changes.append(event.payload)

    def _on_core_boot(self, event: AuditEvent) -> None:
        self.booted = True

    def _on_core_recovered(self, event: AuditEvent) -> None:
        self.recovered = True

    # -- reads ------------------------------------------------------------

    def client_state(self) -> str | None:
        """``"attached"``, ``"detached"`` or ``None`` when nothing was seen."""
        if self.client_detached_at is not None:
            return "detached"
        if self.client_attached_at is not None:
            return "attached"
        return None

    def task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def tasks_in_state(self, *states: str) -> list[Task]:
        return [task for task in self.tasks.values() if task.state in states]

    def reason_for(self, task_id: str) -> str | None:
        return self.task_reasons.get(task_id)
