"""The night's task queue (core-spec v2 §1.9, §3.2).

A task is a row of the owner's plan. It exists before the night (RV patch
11: ``night`` is ``None`` and ``state`` is ``"slated"`` on the plan slate) and
becomes a queued task when the night takes it.

The queue keeps to three rules that the rest of the night leans on:

* a task that is handed out is not handed out twice;
* a **cut** task is not a failure — it is work the bar did not reach, and it
  is re-queued for tomorrow (D §05:0x), so its reason has to survive to the
  morning;
* **Magnus's lane stops hard** at his fixed hour: whatever is unfinished
  parks with kid-readable cards rather than running on (§1.9, G §3).

Everything here is written to the log, so the queue can be rebuilt from the
ledger alone after a kill -9 (§5.4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.night.ledger import Ledger
from core.night.models import Actor, Task, TaskState
from core.night.projection import NightProjection

__all__ = ["TaskQueue", "KID_AUTHOR"]

#: The kid's lane: a reserved slice inside the night's lane (§1.9, §3.2.3).
KID_AUTHOR = "magnus"

_DEFAULT_ACTOR = Actor(kind="scheduler", id="night-runner")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


class TaskQueue:
    """The night's queue of tasks, projected over the audit log."""

    def __init__(
        self,
        ledger: Ledger,
        night_id: str,
        *,
        clock=_utcnow,
        actor: Actor = _DEFAULT_ACTOR,
    ) -> None:
        self._ledger = ledger
        self.night_id = night_id
        self._clock = clock
        self._actor = actor
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []

    # -- construction ------------------------------------------------------

    @classmethod
    def rebuild(
        cls,
        ledger: Ledger,
        night_id: str,
        *,
        clock=_utcnow,
        actor: Actor = _DEFAULT_ACTOR,
    ) -> "TaskQueue":
        """Rebuild the queue from the log alone — the kill -9 property (§5.4)."""
        queue = cls(ledger, night_id, clock=clock, actor=actor)
        projection = NightProjection(ledger.events())
        for task_id, task in projection.tasks.items():
            queue._tasks[task_id] = task
            queue._order.append(task_id)
        return queue

    # -- writes ------------------------------------------------------------

    def add(self, task: Task) -> Task:
        """Take a slated task into the night."""
        task.night = self.night_id
        if task.state == "slated":
            task.state = "queued"
        self._ledger.append(
            type="night.task.created",
            actor=self._actor,
            subject={"entity_kind": "task", "entity_id": task.id},
            payload={"task": task.model_dump()},
            at=self._clock(),
        )
        self._tasks[task.id] = task
        self._order.append(task.id)
        return task

    def mark(
        self,
        task_id: str,
        state: TaskState,
        reason: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Record a task's state change — one event, one row (§5.1).

        ``extra`` carries the task's own record with the row: the iteration
        loop's winner, its rounds and where it stopped. It is part of the
        task's row, not a second story told elsewhere.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id!r}")
        payload: dict = {"task_id": task_id, "state": state}
        if reason:
            payload["reason"] = reason
        if extra:
            payload.update(extra)
        self._ledger.append(
            type="night.task.state",
            actor=self._actor,
            subject={"entity_kind": "task", "entity_id": task_id},
            payload=payload,
            at=self._clock(),
        )
        task.state = state

    def cut(self, task_id: str, reason: str) -> None:
        """The bar did not reach this task; it waits for tomorrow (D §05:0x)."""
        self.mark(task_id, "cut", reason)

    def park(self, task_id: str, reason: str) -> None:
        """Blocked on a decision or on the kid's hour; it waits for the morning."""
        self.mark(task_id, "parked", reason)

    # -- reads -------------------------------------------------------------

    def tasks(self) -> list[Task]:
        """The tasks, in the order they were taken into the night."""
        return [self._tasks[task_id] for task_id in self._order]

    def next_task(self) -> Task | None:
        """The next task to run, or ``None`` when the queue is empty.

        The kid's lane closes hard: a task of his that is still queued after
        his hour parks with a card he can read, and the queue moves on.
        """
        now = _parse(self._clock())
        for task_id in self._order:
            task = self._tasks[task_id]
            if task.state != "queued":
                continue
            if task.author == KID_AUTHOR and task.ends_at:
                if now > _parse(task.ends_at):
                    self.park(
                        task_id,
                        f"Magnus's lane ended at {task.ends_at[11:16]} — "
                        f"this one waits for tomorrow.",
                    )
                    continue
            return task
        return None
