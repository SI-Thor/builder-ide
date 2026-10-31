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

from core.night.iterate import Attempt
from core.night.models import AuditEvent, IterationPolicy, Night, Rail, Task

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
        self.threshold_pct: int | None = None
        self.stall_minutes = 0.0
        self.batches: dict[str, Any] | None = None
        self.late_minutes = 0.0
        self.degraded_verdicts = 0
        self.kill_switch = False
        self.reports: list[str] = []
        self.booted = False
        self.recovered = False
        self.job_outcomes: list[dict[str, Any]] = []
        #: The iterator loop's record, per task: the winner, the rounds and
        #: where the loop stopped.
        self.iterations: dict[str, dict[str, Any]] = {}
        #: Every variant attempt, in the order the night made them.
        self.attempts: list[Attempt] = []
        self._job_requests: dict[str, dict[str, Any]] = {}
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
            iteration=(
                IterationPolicy(**payload["iteration"])
                if payload.get("iteration")
                else None
            ),
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
        kind = event.payload.get("kind")
        if kind == "stall":
            self.stall_minutes += float(event.payload.get("minutes", 0.0))
        elif kind == "batches":
            self.batches = dict(event.payload)
            self.late_minutes = float(event.payload.get("late_minutes", 0.0))

    def _on_night_task_created(self, event: AuditEvent) -> None:
        task = Task.model_validate(event.payload["task"])
        self.tasks[task.id] = task

    def _on_night_task_state(self, event: AuditEvent) -> None:
        payload = event.payload
        task = self.tasks.get(payload["task_id"])
        if task is None:
            return
        task.state = payload["state"]
        # The reason belongs to the state: a task that is merely running has
        # no reason, and must not keep the reason of the state before it.
        self.task_reasons[task.id] = payload.get("reason")
        # The loop's own record rides on the task's row: the winner, the
        # rounds it ran and where it stopped.
        if payload.get("iteration"):
            self.iterations[task.id] = dict(payload["iteration"])

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
        level = int(event.payload.get("level", 0))
        self.threshold_pct = max(self.threshold_pct or 0, level)

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

    def _on_critic_verdict(self, event: AuditEvent) -> None:
        if event.payload.get("degraded"):
            self.degraded_verdicts += 1

    def _on_job_enqueued(self, event: AuditEvent) -> None:
        payload = event.payload
        job_id = payload.get("job_id")
        if job_id:
            self._job_requests[job_id] = payload

    def _on_job_done(self, event: AuditEvent) -> None:
        payload = event.payload
        self.job_outcomes.append(payload)
        if payload.get("outcome") == "failed":
            self.failures.append(payload)
        self._fold_attempt(payload)

    def _fold_attempt(self, payload: dict[str, Any]) -> None:
        """One variant attempt out of the log: what it was and what it scored.

        The variant rides on the job's request (seeded and bounded, §1.9) and
        the score rides on the job's outcome — the two halves join here, so
        the morning can say which variant beat which.
        """
        variant_id = payload.get("variant_id")
        if not variant_id:
            return
        request = (self._job_requests.get(payload.get("job_id")) or {}).get(
            "request", {}
        )
        cost = payload.get("cost") or {}
        self.attempts.append(
            Attempt(
                task_id=payload.get("task_id", ""),
                variant_id=variant_id,
                label=request.get("label", ""),
                round=int(payload.get("round", request.get("round", 1))),
                parent_id=request.get("parent_id"),
                score=float(payload.get("score", 0.0)),
                outcome=payload.get("outcome", "kept"),
                reason=payload.get("reason"),
                critic_reason=payload.get("critic_reason", ""),
                gpu_minutes=float(cost.get("gpu_minutes", 0.0)),
                wall_minutes=float(cost.get("wall_minutes", 0.0)),
                hosted_cents=int(cost.get("hosted_cents", 0)),
                joules=payload.get("joules"),
            )
        )

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

    # -- the loop ----------------------------------------------------------

    def attempts_for(self, task_id: str) -> list[Attempt]:
        """Every variant attempt the night made for one goal, in order."""
        return [attempt for attempt in self.attempts if attempt.task_id == task_id]

    def winner_for(self, task_id: str) -> Attempt | None:
        """The variant the loop kept — the best that was actually kept."""
        record = self.iterations.get(task_id) or {}
        winner = record.get("winner") or {}
        winner_id = winner.get("variant_id")
        if not winner_id:
            return None
        for attempt in self.attempts_for(task_id):
            if attempt.variant_id == winner_id:
                return attempt
        return None

    def stop_for(self, task_id: str) -> dict[str, Any] | None:
        """Why the loop stopped: ``no improvement``, ``rail``, and where."""
        record = self.iterations.get(task_id)
        if not record:
            return None
        return record.get("stop")
