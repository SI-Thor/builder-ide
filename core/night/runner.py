"""The night runner: the night's lifecycle, its rails and its detach rule.

The night is the part of the product where nobody is watching. Everything
here is written to the log, because the morning has to be able to say what
happened without anybody's memory of it (§5.1, §5.4).

The rules the runner keeps, in the order it keeps them:

* the **pre-flight proposes, never decides** (§3.2.2) — it reports the lane,
  the queue depth and the detach deadline, and it does not choose;
* **big batches start on client detach or the deadline, whichever is first**
  (§1.9, RV patch 10). If the client never left, the morning says so;
* **admission is before spend** (§5.5): a task whose projected cost the rail
  cannot cover is cut, not started and killed, and the cut is named;
* the **load cap** parks a task that would swap a model again rather than
  thrashing the weight (§5.5);
* **the throttle is graduated** — 80% drains, 95% stops, 100% writes the
  report now;
* a **sealed bet is committed before its render job is enqueued** (§5.1) —
  that ordering is what makes a bet unforgeable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Literal, Mapping, Sequence

from core.night.clock import Clock
from core.night.executor import ExecutionPlan, TaskExecutor
from core.night.heartbeat import Heartbeat
from core.night.ledger import Ledger
from core.night.models import Actor, Night, Rail, Task
from core.night.projection import NightProjection
from core.night.queue import TaskQueue
from core.night.rails import LoadBudget, RailBudget, ThrottleLevel
from core.night.status import StatusLine, compute_status

__all__ = ["NightRunner"]

_DEFAULT_ACTOR = Actor(kind="scheduler", id="night-runner")

#: How often the core ticks the window (§3.4: admission is re-checked on a
#: 10-minute tick).
TICK_INTERVAL_MINUTES = 10

#: How long a job's claim on the seat is valid without a heartbeat (§5.2
#: step 3). The heartbeat renews it while the job runs.
LEASE_MINUTES = 15


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _plus_minutes(stamp: str, minutes: float) -> str:
    moment = _parse(stamp) + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class NightRunner:
    """Runs one night: start, pre-flight, queue, stop, report."""

    def __init__(
        self,
        ledger: Ledger,
        executor: TaskExecutor,
        *,
        night_id: str,
        rails: Rail,
        clock: Clock,
        load_budget: Mapping[str, int] | None = None,
        detach_deadline_minutes: int = 30,
        batch_start: Literal["detach", "deadline", "both"] = "both",
        power_mode: int = 0,
        presence: Callable[[str], str] | None = None,
        lane_free: Callable[[str], bool] | None = None,
        actor: Actor = _DEFAULT_ACTOR,
        tick_interval_minutes: int = TICK_INTERVAL_MINUTES,
        lease_minutes: int = LEASE_MINUTES,
    ) -> None:
        self._ledger = ledger
        self._executor = executor
        self.night_id = night_id
        self.rails = rails
        self.clock = clock
        self.load_budget = dict(load_budget or {})
        self.detach_deadline_minutes = detach_deadline_minutes
        self.batch_start = batch_start
        self.power_mode = power_mode
        self._presence = presence
        self._lane_free = lane_free
        self._actor = actor
        self.tick_interval_minutes = tick_interval_minutes
        self.lease_minutes = lease_minutes
        self._running_job: str | None = None

        self.budget = RailBudget(ceiling=rails)
        self.loads = LoadBudget(caps=self.load_budget)
        self.heartbeat = Heartbeat(ledger, night_id, clock=clock.now, actor=actor)
        self.queue: TaskQueue | None = None
        self.night: Night | None = None
        self.status: StatusLine | None = None
        self._job_counter = 0
        self._recorded_thresholds: set[int] = set()
        self._lane_blocked = False

    # -- the log -----------------------------------------------------------

    @classmethod
    def resume(
        cls,
        ledger: Ledger,
        executor: TaskExecutor,
        *,
        night_id: str,
        clock: Clock,
        actor: Actor = _DEFAULT_ACTOR,
        **kwargs,
    ) -> "NightRunner":
        """Rebuild a running night from the log, and carry on (§5.2 step 5).

        The rails, the spend, the load counts and the queue are all folds, so
        a resumed night knows what it has already spent without anybody
        telling it.
        """
        projection = NightProjection(ledger.events())
        night = projection.night
        rails = night.rails if night else Rail()
        load_budget = night.load_budget if night else {}
        runner = cls(
            ledger,
            executor,
            night_id=night_id,
            rails=rails,
            clock=clock,
            load_budget=load_budget,
            actor=actor,
            **kwargs,
        )
        runner.budget = RailBudget(ceiling=rails, spent=projection.spend)
        runner.loads = LoadBudget.from_counts(load_budget, projection.model_loads)
        runner.queue = TaskQueue.rebuild(ledger, night_id, clock=clock.now)
        runner.night = night
        runner._job_counter = len(
            [event for event in ledger.events() if event.type == "job.enqueued"]
        )
        return runner

    @property
    def projection(self) -> NightProjection:
        """The night as the log says it is."""
        return NightProjection(self._ledger.events())

    def _append(self, type: str, payload: dict, at: str | None = None) -> None:
        self._ledger.append(
            type=type,
            actor=self._actor,
            subject={"entity_kind": "night", "entity_id": self.night_id},
            payload=payload,
            at=at,
        )

    # -- the lifecycle -----------------------------------------------------

    def start(self, tasks: Sequence[Task] | None = None) -> Night:
        """``night.started`` — the night begins, and the rails are set."""
        started_at = self.clock.now()
        detach_deadline = _plus_minutes(started_at, self.detach_deadline_minutes)
        self._append(
            "night.started",
            {
                "night_id": self.night_id,
                "rails": self.rails.model_dump(),
                "load_budget": self.load_budget,
                "power_mode": self.power_mode,
                "batch_start": self.batch_start,
                "detach_deadline": detach_deadline,
            },
            at=started_at,
        )
        self.night = Night(
            id=self.night_id,
            started_at=started_at,
            rails=self.rails,
            load_budget=dict(self.load_budget),
            power_mode=self.power_mode,
            batch_start=self.batch_start,
            detach_deadline=detach_deadline,
            state="running",
        )
        # The ProArt is watching the night; the core owns the power mode for
        # the window (§5.5).
        self._append("client.attach", {"client": "proart"}, at=started_at)
        self._append("power.mode.set", {"mode": self.power_mode}, at=started_at)

        self.queue = TaskQueue(self._ledger, self.night_id, clock=self.clock.now)
        for task in tasks or []:
            self.queue.add(task)

        self._preflight()
        return self.night

    def _preflight(self) -> None:
        """Report the lane, the queue and the deadline. Decide nothing (§3.2.2)."""
        now = self.clock.now()
        free = self._lane_is_free(now)
        proposal = None if free else "start late"
        self._append(
            "night.preflight",
            {
                "lane_free": free,
                "lane_load": 0.0 if free else 1.0,
                "queue_depth": len(self.queue.tasks()) if self.queue else 0,
                "telemetry": True,
                "detach_deadline": self.night.detach_deadline if self.night else None,
                "proposal": proposal,
            },
            at=now,
        )

    def run(self) -> None:
        """The night: wait for the batches, then work the queue."""
        if self.queue is None:
            raise RuntimeError("the night has not started")
        self._wait_for_batches()
        if self._lane_blocked:
            return
        while True:
            level = self.budget.throttle_level()
            if level is not ThrottleLevel.NOMINAL:
                self._cut_the_rest(level)
                break
            task = self.queue.next_task()
            if task is None:
                break
            plan = self._admit(task)
            if plan is None:
                continue
            self._run_task(task, plan)

    def stop(self) -> StatusLine:
        """``night.stopped`` — and the status, computed from the log."""
        status = compute_status(self.projection)
        self._append(
            "night.stopped",
            {
                "status": status.status,
                "reason": status.reason,
                "variant": status.variant,
            },
            at=self.clock.now(),
        )
        self.status = status
        return status

    # -- the wait ----------------------------------------------------------

    def _wait_for_batches(self) -> None:
        """Big batches start on detach or the deadline, whichever is first."""
        deadline = self.night.detach_deadline if self.night else None
        if self._batches_already_started():
            # The night was interrupted after the batches started; carry on
            # with the work, not with the wait (§5.2).
            return
        while True:
            now = self.clock.now()
            if not self._lane_is_free(now):
                # A foreign job holds the lane: ours queues and is never
                # admitted. The queue admits when the lane frees, re-checked on
                # the tick (§3.4) — until the deadline, then the night is over.
                if deadline and now >= deadline:
                    self._lane_blocked = True
                    return
                self._advance_ticking(self.tick_interval_minutes)
                continue
            if self.batch_start in ("detach", "both") and self._client_present(now) == "detached":
                self._batches_tick("detach", now)
                return
            if deadline and now >= deadline:
                self._batches_tick("deadline", now)
                return
            self._advance_ticking(self.tick_interval_minutes)

    def _batches_already_started(self) -> bool:
        """True when the log says the big batches have already started."""
        return any(
            event.payload.get("kind") == "batches" for event in self._ledger.events()
        )

    def _batches_tick(self, trigger: str, now: str) -> None:
        started_at = self.night.started_at if self.night else now
        late = (_parse(now) - _parse(started_at)).total_seconds() / 60.0
        cause = (
            "the client detached"
            if trigger == "detach"
            else "the ProArt stayed attached"
        )
        self.heartbeat.batches_started(late_minutes=late, cause=cause, trigger=trigger)

    def _client_present(self, now: str) -> str:
        """Ask the client half whether the ProArt is still watching.

        The default evening: the owner closes the client and goes to bed. When
        the seam says the client is gone, the fact is recorded in the log —
        presence is a durable fact, not a memory (§3.4).
        """
        if self._presence is not None:
            presence = self._presence(now)
        else:
            presence = "detached"
        if presence == "detached" and self.projection.client_state() != "detached":
            self._append("client.detach", {"client": "proart"}, at=now)
        return presence

    def _lane_is_free(self, now: str) -> bool:
        if self._lane_free is None:
            return True
        return self._lane_free(now)

    # -- the queue ---------------------------------------------------------

    def _admit(self, task: Task) -> ExecutionPlan | None:
        """Admission before spend: refuse what a rail cannot cover (§5.5)."""
        plan = self._executor.plan(task)
        cost = Rail(
            gpu_minutes=plan.gpu_minutes,
            hosted_cents=plan.hosted_cents,
            wall_minutes=plan.wall_minutes,
        )
        if not task.rail.is_zero and not task.rail.fits(cost):
            self.queue.cut(
                task.id,
                f"{task.intention} did not fit its own rail — re-queued for tonight",
            )
            return None
        if not self.budget.can_admit(cost):
            ask_hours = task.cost_estimate.gpu_minutes / 60.0
            bar = self._recorded_thresholds or {80}
            self.queue.cut(
                task.id,
                f"{ask_hours:.1f} lane-h of the ask was cut at the {max(bar)}% bar; "
                f"{task.intention} is re-queued for tonight",
            )
            return None
        if plan.model and not self.loads.can_load(plan.model):
            self.queue.park(
                task.id,
                f"waiting for {plan.model} to drain — the load cap is one load a night",
            )
            return None
        return plan

    def _cut_the_rest(self, level: ThrottleLevel) -> None:
        """The bar stopped the night; the rest waits for tomorrow."""
        pct = {ThrottleLevel.DRAINING: 80, ThrottleLevel.STOPPING: 95, ThrottleLevel.SPENT: 100}[
            level
        ]
        self._record_threshold(pct)
        for task in self.queue.tasks():
            if task.state != "queued":
                continue
            self.queue.cut(
                task.id,
                f"the {pct}% bar stopped new work — {task.intention} is re-queued for tonight",
            )

    def _record_threshold(self, pct: int) -> None:
        if pct in self._recorded_thresholds:
            return
        self._recorded_thresholds.add(pct)
        self._append("budget.threshold", {"level": pct}, at=self.clock.now())

    def _record_spend(self, cost: Rail) -> None:
        now = self.clock.now()
        if cost.gpu_minutes:
            self._append(
                "budget.spend",
                {"axis": "gpu_minutes", "amount": cost.gpu_minutes, "scope": "night"},
                at=now,
            )
        if cost.hosted_cents:
            self._append(
                "budget.spend",
                {"axis": "hosted_cents", "amount": cost.hosted_cents, "scope": "night"},
                at=now,
            )
        if cost.wall_minutes:
            self._append(
                "budget.spend",
                {"axis": "wall_minutes", "amount": cost.wall_minutes, "scope": "night"},
                at=now,
            )
        level = self.budget.throttle_level()
        pct = {
            ThrottleLevel.DRAINING: 80,
            ThrottleLevel.STOPPING: 95,
            ThrottleLevel.SPENT: 100,
        }.get(level)
        if pct:
            self._record_threshold(pct)

    # -- the work ----------------------------------------------------------

    def _run_task(self, task: Task, plan: ExecutionPlan) -> None:
        now = self.clock.now()
        self._job_counter += 1
        job_id = f"job_{self._job_counter:04d}"
        # The bet is sealed and committed before the render job exists (§5.1).
        for prediction in plan.predictions:
            self._append(
                "prediction.sealed",
                {
                    "prediction_id": prediction["prediction_id"],
                    "builder": prediction.get("builder", task.owner_character),
                    "claim_type": prediction.get("claim_type", "shadow_count"),
                    "claim": prediction.get("claim", ""),
                    "confidence": prediction.get("confidence", "guess"),
                    "basis": prediction.get("basis", "0 observations"),
                    "task_id": task.id,
                },
                at=now,
            )

        self._append(
            "job.enqueued",
            {
                "job_id": job_id,
                "task_id": task.id,
                "lane": "gpu" if plan.model else "cpu",
                "model": plan.model,
                "cost": {
                    "gpu_minutes": plan.gpu_minutes,
                    "hosted_cents": plan.hosted_cents,
                    "wall_minutes": plan.wall_minutes,
                },
            },
            at=now,
        )
        if plan.model:
            self._append("sched.model.load", {"model": plan.model}, at=now)
        # The claim on the seat is a lease, and the heartbeat renews it while
        # the job runs (§5.2 step 3).
        self._append(
            "job.started",
            {
                "job_id": job_id,
                "task_id": task.id,
                "lease_until": _plus_minutes(now, self.lease_minutes),
                "heartbeat_at": now,
            },
            at=now,
        )
        self.queue.mark(task.id, "running")
        self._running_job = job_id
        try:
            # The work itself: the executor runs it and reports what it cost.
            # If the box dies here, the night dies with it — and the time the
            # work would have taken is the time the morning will call lost.
            actual = self._executor.run(task)
        finally:
            self._running_job = None
        actual_cost = Rail(
            gpu_minutes=actual.gpu_minutes,
            hosted_cents=actual.hosted_cents,
            wall_minutes=actual.wall_minutes,
        )

        # The core keeps ticking the window while the work runs (§3.4).
        if plan.stall_minutes:
            # The batch waited on the lane. The core was alive the whole time,
            # so this is contention, not lost time — and it is named (§3.3).
            self.heartbeat.stall(plan.stall_minutes, note=plan.stall_reason)
            self._advance_ticking(plan.stall_minutes)
        self._advance_ticking(plan.wall_minutes)
        done_at = self.clock.now()

        self.budget.spend(actual_cost)
        self._record_spend(actual_cost)
        if plan.model:
            self.loads.record_load(plan.model)

        outcome = actual.outcome
        overrun = 0.0
        if not task.rail.is_zero and actual.wall_minutes > task.rail.wall_minutes:
            # The seat hard-kills at the per-attempt rail (§5.5): the work is
            # stopped, not trusted, and it waits for tomorrow.
            overrun = actual.wall_minutes - task.rail.wall_minutes
            outcome = "cut"
        self._append(
            "job.done",
            {
                "job_id": job_id,
                "task_id": task.id,
                "outcome": "failed" if outcome == "failed" else outcome,
                "reason": actual.reason,
                "artifact": actual.artifact,
                "cost": actual_cost.model_dump(),
            },
            at=done_at,
        )

        for branch in actual.branches:
            self._append(
                "branch.created",
                {"branch": branch, "task_id": task.id},
                at=done_at,
            )

        for verdict in actual.verdicts:
            self._append(
                "critic.verdict",
                {
                    "prediction_id": verdict["prediction_id"],
                    "verdict": verdict["verdict"],
                    "degraded": bool(verdict.get("degraded", actual.degraded)),
                    "summary": verdict.get("summary", "verdict@scripted"),
                    "task_id": task.id,
                },
                at=done_at,
            )
            self._append(
                "prediction.scored",
                {
                    "prediction_id": verdict["prediction_id"],
                    "verdict": verdict["verdict"],
                },
                at=done_at,
            )

        # The night's keep or revert is a **verdict** write, never a taste
        # write (§1.7): the owner scores taste in the morning.
        state = "reverted" if outcome == "failed" else outcome
        reason = actual.reason
        if overrun:
            reason = f"the seat stopped it at its own rail — {overrun:.0f} min over"
        self.queue.mark(task.id, state, reason)

    # -- time --------------------------------------------------------------

    def _advance_ticking(self, minutes: float) -> None:
        """Move the clock forward, ticking the window as it goes.

        Each tick renews the lease of the job that is running, so a live job
        is never mistaken for a dead one when the box comes back (§5.2).
        """
        remaining = minutes
        while remaining > 0:
            step = min(self.tick_interval_minutes, remaining)
            self.clock.advance(step)
            remaining -= step
            renewal = None
            if self._running_job is not None:
                renewal = {
                    "job_id": self._running_job,
                    "lease_until": _plus_minutes(self.clock.now(), self.lease_minutes),
                }
            if renewal is None:
                self.heartbeat.tick()
            else:
                self.heartbeat.tick(renewed=renewal)
