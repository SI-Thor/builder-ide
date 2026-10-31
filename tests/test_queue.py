"""The night's task queue (§1.9, §3.2).

The queue is a projection over the log like everything else, so it can be
rebuilt after a kill -9. Three rules are load-bearing:

* a task that is handed out is not handed out twice;
* a **cut** task is not a failure — it is work the bar did not reach, and it
  is re-queued for tomorrow (D §05:0x);
* **Magnus's lane stops hard** at his fixed hour: unfinished items park with
  kid-readable cards (§1.9, G §3).
"""

from __future__ import annotations

from core.night.ledger import InMemoryLedger
from core.night.models import Rail, Task
from core.night.projection import NightProjection
from core.night.queue import TaskQueue

NIGHT = "night_2026-10-30"


def clock_at(*stamps: str):
    """A clock that hands out the given stamps in order."""
    stamps = list(stamps)

    def _now() -> str:
        return stamps.pop(0) if len(stamps) > 1 else stamps[0]

    return _now


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(
        id=task_id,
        intention=kwargs.pop("intention", "Forest the east slope, keep the oak"),
        **kwargs,
    )


def test_a_task_added_to_the_queue_is_folded_back_from_the_ledger():
    ledger = InMemoryLedger()
    queue = TaskQueue(ledger, NIGHT)
    task = queue.add(a_task())

    assert task.night == NIGHT
    assert task.state == "queued"

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001") == task


def test_the_queue_hands_out_the_tasks_in_the_order_they_were_added():
    queue = TaskQueue(InMemoryLedger(), NIGHT)
    queue.add(a_task("task_0001"))
    queue.add(a_task("task_0002"))
    assert queue.next_task().id == "task_0001"


def test_a_running_task_is_not_handed_out_again():
    queue = TaskQueue(InMemoryLedger(), NIGHT)
    queue.add(a_task("task_0001"))
    queue.add(a_task("task_0002"))
    first = queue.next_task()
    queue.mark(first.id, "running")

    assert queue.next_task().id == "task_0002"


def test_a_cut_task_carries_the_reason_the_morning_can_name():
    ledger = InMemoryLedger()
    queue = TaskQueue(ledger, NIGHT)
    queue.add(a_task("task_0001"))
    queue.cut("task_0001", "the north-lantern batch did not fit under the bar")

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "cut"
    assert projection.reason_for("task_0001") == (
        "the north-lantern batch did not fit under the bar"
    )


def test_the_kid_lane_stops_hard_and_parks_what_it_could_not_finish():
    ledger = InMemoryLedger()
    queue = TaskQueue(
        ledger,
        NIGHT,
        clock=clock_at("2026-10-30T21:40:00Z"),
    )
    queue.add(
        a_task(
            "task_0001",
            author="magnus",
            ends_at="2026-10-30T21:30:00Z",
            intention="Put the tower by the water",
        )
    )
    assert queue.next_task() is None

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "parked"
    reason = projection.reason_for("task_0001")
    assert "21:30" in reason


def test_a_task_in_the_kid_lane_before_its_hour_is_handed_out():
    queue = TaskQueue(
        InMemoryLedger(),
        NIGHT,
        clock=clock_at("2026-10-30T21:20:00Z"),
    )
    queue.add(a_task("task_0001", author="magnus", ends_at="2026-10-30T21:30:00Z"))
    assert queue.next_task().id == "task_0001"


def test_the_queue_is_rebuildable_from_the_log_alone():
    """§5.4 — the kill -9 test: everything is a fold over the ledger."""
    ledger = InMemoryLedger()
    queue = TaskQueue(ledger, NIGHT)
    queue.add(a_task("task_0001"))
    queue.add(a_task("task_0002"))
    queue.mark("task_0001", "running")

    rebuilt = TaskQueue.rebuild(ledger, NIGHT)
    assert [task.id for task in rebuilt.tasks()] == ["task_0001", "task_0002"]
    assert rebuilt.next_task().id == "task_0002"


def test_the_queue_keeps_the_ask_and_the_rail_of_every_task():
    queue = TaskQueue(InMemoryLedger(), NIGHT)
    task = queue.add(
        a_task(
            cost_estimate=Rail(gpu_minutes=30.0, wall_minutes=45.0),
            rail=Rail(gpu_minutes=40.0, wall_minutes=60.0),
        )
    )
    assert task.cost_estimate == Rail(gpu_minutes=30.0, wall_minutes=45.0)
    assert task.rail == Rail(gpu_minutes=40.0, wall_minutes=60.0)
