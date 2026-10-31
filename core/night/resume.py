"""What survives a restart, and how a night resumes (§5.2).

The boot sequence, in the spec's five steps:

1. open the store; if the projections are dirty, rebuild them by folding the
   audit log (``projection.rebuilt``);
2. verify the artifacts the night claims — a broken reference fails loud;
3. a recovery pass over the jobs: an expired ``lease_until`` with no
   heartbeat becomes ``job.requeued``. GPU renders re-run from the seed; CPU
   steps replay byte-identically;
4. the attempts: a live seat re-attaches, otherwise attempt *n+1* in a fresh
   seat — attempt ids are never reused;
5. the night: if it is running, its rails are not exhausted and the wall
   window is open, it **resumes from the last sealed step** (the queue is
   durable); otherwise it stops cleanly and builds the report, with the
   status line and ``lost_minutes`` computed from the heartbeat gaps — never
   hidden.

What does *not* survive: GPU-resident models, TCP connections, resident scene
servers, half-finished renders (atomic — they re-run, they never resume), and
the predictions of steps that never reached a render — those die unsealed and
unscored. Never invent a verdict for work that did not happen (§5.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.night.clock import Clock
from core.night.executor import TaskExecutor
from core.night.heartbeat import lost_minutes
from core.night.ledger import Ledger
from core.night.models import Actor
from core.night.projection import NightProjection
from core.night.rails import RailBudget, ThrottleLevel
from core.night.status import StatusLine, compute_status

__all__ = ["RecoveryOutcome", "boot", "recover"]

_DEFAULT_ACTOR = Actor(kind="core", id="night-runner")


class RecoveryOutcome(BaseModel):
    """What the boot sequence decided about the night."""

    night_id: str
    action: Literal["resumed", "stopped"]
    status: StatusLine | None = None
    requeued_jobs: list[str] = Field(default_factory=list)
    requeued_tasks: list[str] = Field(default_factory=list)
    lost_minutes: float = 0.0
    reason: str = ""


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def boot(ledger: Ledger, *, clock: Clock, actor: Actor = _DEFAULT_ACTOR) -> NightProjection:
    """Step 1: open the store and rebuild the projection by folding the log."""
    ledger.append(
        type="core.boot",
        actor=actor,
        subject={"entity_kind": "core", "entity_id": "night-runner"},
        payload={},
        at=clock.now(),
    )
    projection = NightProjection(ledger.events())
    ledger.append(
        type="projection.rebuilt",
        actor=actor,
        subject={"entity_kind": "core", "entity_id": "night-runner"},
        payload={"events": projection.night is not None},
        at=clock.now(),
    )
    return projection


def recover(
    ledger: Ledger,
    executor: TaskExecutor,
    *,
    night_id: str,
    clock: Clock,
    actor: Actor = _DEFAULT_ACTOR,
) -> RecoveryOutcome:
    """The boot sequence (§5.2), and the decision about the night."""
    projection = boot(ledger, clock=clock, actor=actor)
    now = clock.now()

    requeued_jobs = _requeue_dead_jobs(ledger, projection, now=now, actor=actor)
    requeued_tasks = _requeue_running_tasks(ledger, projection, now=now, actor=actor)

    night = projection.night
    if night is None:
        return RecoveryOutcome(
            night_id=night_id,
            action="stopped",
            requeued_jobs=requeued_jobs,
            requeued_tasks=requeued_tasks,
            reason="there is no night to resume",
        )

    budget = RailBudget(ceiling=night.rails, spent=projection.spend)
    elapsed = _elapsed_minutes(night.started_at, projection)
    window_open = elapsed < night.rails.wall_minutes
    rails_left = budget.throttle_level() is not ThrottleLevel.SPENT

    if window_open and rails_left:
        return RecoveryOutcome(
            night_id=night_id,
            action="resumed",
            requeued_jobs=requeued_jobs,
            requeued_tasks=requeued_tasks,
            lost_minutes=lost_minutes(projection.ticks),
        )

    # The core ticks the window the moment it is back: the gap between the
    # last tick before the crash and this one is the lost time, and the status
    # line is computed from it (§5.2 step 5, never hidden).
    if projection.ticks:
        ledger.append(
            type="night.tick",
            actor=actor,
            subject={"entity_kind": "night", "entity_id": night_id},
            payload={"at": now, "kind": "wall"},
            at=now,
        )
        projection = NightProjection(ledger.events())

    status = compute_status(projection)
    ledger.append(
        type="night.stopped",        actor=actor,
        subject={"entity_kind": "night", "entity_id": night_id},
        payload={
            "status": status.status,
            "reason": status.reason,
            "variant": status.variant,
        },
        at=now,
    )
    return RecoveryOutcome(
        night_id=night_id,
        action="stopped",
        status=status,
        requeued_jobs=requeued_jobs,
        requeued_tasks=requeued_tasks,
        lost_minutes=lost_minutes(projection.ticks),
        reason="the window closed or the rails were spent",
    )


def _elapsed_minutes(started_at: str, projection: NightProjection) -> float:
    """How long the night has been open, by the log's own clock."""
    stamps = [event.at for event in projection.ticks]
    if projection.night is not None:
        stamps.append(projection.night.started_at)
    if not stamps:
        return 0.0
    last = max(stamps)
    return (_parse(last) - _parse(started_at)).total_seconds() / 60.0


def _requeue_dead_jobs(
    ledger: Ledger, projection: NightProjection, *, now: str, actor: Actor
) -> list[str]:
    """Step 3: a job whose lease expired with no heartbeat is requeued.

    The lease is written when the job starts and renewed by every heartbeat
    while it runs, so a job that is still alive holds a lease in the future.
    A job that started, never finished, and whose lease has run out is dead:
    the GPU render re-runs from the seed and the CPU steps replay
    byte-identically (§5.2).
    """
    leases: dict[str, str] = {}
    started: dict[str, dict] = {}
    finished: set[str] = set()
    for event in ledger.events():
        if event.type == "job.started":
            job_id = event.payload.get("job_id", event.subject.get("entity_id"))
            started[job_id] = event.payload
            if event.payload.get("lease_until"):
                leases[job_id] = event.payload["lease_until"]
        elif event.type == "job.done":
            finished.add(event.payload.get("job_id"))
        elif event.type == "night.tick":
            renewed = event.payload.get("renewed")
            if renewed:
                leases[renewed["job_id"]] = renewed["lease_until"]

    requeued: list[str] = []
    for job_id, payload in started.items():
        if job_id in finished:
            continue
        lease = leases.get(job_id) or payload.get("lease_until")
        if lease is None or _parse(lease) > _parse(now):
            continue
        ledger.append(
            type="job.requeued",
            actor=actor,
            subject={"entity_kind": "job", "entity_id": job_id},
            payload={"job_id": job_id, "reason": "the lease expired with no heartbeat"},
            at=now,
        )
        requeued.append(job_id)
    return requeued


def _requeue_running_tasks(
    ledger: Ledger, projection: NightProjection, *, now: str, actor: Actor
) -> list[str]:
    """A task that was running when the box died goes back in the queue.

    GPU renders re-run from the seed and CPU steps replay byte-identically,
    so the work is redone rather than half-believed (§5.2).
    """
    requeued: list[str] = []
    for task in projection.tasks.values():
        if task.state != "running":
            continue
        ledger.append(
            type="night.task.state",
            actor=actor,
            subject={"entity_kind": "task", "entity_id": task.id},
            payload={
                "task_id": task.id,
                "state": "queued",
                "reason": "re-queued after the restart — the work re-runs from the seed",
            },
            at=now,
        )
        requeued.append(task.id)
    return requeued
