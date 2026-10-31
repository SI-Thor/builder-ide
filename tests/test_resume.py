"""What survives a restart, and how a night resumes (§5.2).

The boot sequence is five steps: open the store and rebuild the projection by
folding the log; verify the artifacts the night claims; requeue the jobs whose
lease expired with no heartbeat; re-attach or restart the attempts; and then
the night itself — if it is still running, its rails are not exhausted and
the wall window is open, it resumes from the last sealed step; otherwise it
stops cleanly and builds the report **with the status line and
``lost_minutes`` computed from the heartbeat gaps, never hidden**.
"""

from __future__ import annotations

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.ledger import InMemoryLedger
from core.night.models import Actor, Rail, Task
from core.night.projection import NightProjection
from core.night.resume import recover
from core.night.runner import NightRunner

NIGHT = "night_2026-10-30"
CORE = Actor(kind="core", id="night-runner")


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(
        id=task_id,
        intention=kwargs.pop("intention", "Forest the east slope, keep the oak"),
        **kwargs,
    )


class CrashingExecutor(ScriptedExecutor):
    """Dies on the second task, the way a power cut does — once."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.crashed = False

    def run(self, task):
        if task.id == "task_0002" and not self.crashed:
            self.crashed = True
            raise RuntimeError("the box rebooted")
        return super().run(task)


def test_a_restart_rebuilds_the_projection_from_the_log_alone():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task()])
    runner.run()

    outcome = recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    assert outcome.action in ("resumed", "stopped")
    types = [event.type for event in ledger.events()]
    assert "core.boot" in types
    assert "projection.rebuilt" in types


def test_a_task_that_was_running_when_the_box_died_goes_back_in_the_queue():
    ledger = InMemoryLedger()
    executor = CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task("task_0001"), a_task("task_0002")])
    try:
        runner.run()
    except RuntimeError:
        pass

    outcome = recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    assert outcome.action == "resumed"
    assert "task_0002" in outcome.requeued_tasks
    projection = NightProjection(ledger.events())
    assert projection.task("task_0002").state == "queued"


def test_the_crashed_job_is_requeued_when_the_box_comes_back():
    """The job's lease expired with no heartbeat — it is requeued (§5.2 step 3)."""
    ledger = InMemoryLedger()
    executor = CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task("task_0001"), a_task("task_0002")])
    try:
        runner.run()
    except RuntimeError:
        pass

    outcome = recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:30:00Z"),
    )
    assert "job_0002" in outcome.requeued_jobs
    assert any(event.type == "job.requeued" for event in ledger.events())


def test_a_job_whose_lease_expired_is_requeued():
    ledger = InMemoryLedger()
    ledger.append(
        type="job.started",
        actor=CORE,
        subject={"entity_kind": "job", "entity_id": "job_0001"},
        payload={
            "job_id": "job_0001",
            "task_id": "task_0001",
            "lease_until": "2026-10-30T22:00:00Z",
            "heartbeat_at": "2026-10-30T21:50:00Z",
        },
    )
    outcome = recover(
        ledger,
        ScriptedExecutor({}),
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    assert "job_0001" in outcome.requeued_jobs
    assert any(event.type == "job.requeued" for event in ledger.events())


def test_a_night_with_rails_and_time_left_resumes():
    ledger = InMemoryLedger()
    executor = CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task("task_0001"), a_task("task_0002")])
    try:
        runner.run()
    except RuntimeError:
        pass

    outcome = recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    assert outcome.action == "resumed"
    assert outcome.reason == ""


def test_a_night_with_no_rails_left_stops_cleanly_and_names_the_lost_minutes():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=30.0, wall_minutes=60.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task()])
    runner.run()

    outcome = recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-31T01:00:00Z"),
    )
    assert outcome.action == "stopped"
    assert outcome.status is not None
    assert outcome.status.status == "ran short"
    assert "min lost" in outcome.status.reason


def test_the_recovery_writes_its_rows_with_the_nights_clock():
    """Every row the boot sequence writes carries the night's clock, not the
    machine's — otherwise the morning's wall time is a lie."""
    ledger = InMemoryLedger()
    executor = CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task("task_0001"), a_task("task_0002")])
    try:
        runner.run()
    except RuntimeError:
        pass

    recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:30:00Z"),
    )
    for event in ledger.events():
        assert event.at.startswith("2026-10-30"), event.at
        assert event.at < "2026-11-01", event.at


def test_the_resumed_night_finishes_its_queue_and_says_what_it_lost():
    ledger = InMemoryLedger()
    executor = CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task("task_0001"), a_task("task_0002")])
    try:
        runner.run()
    except RuntimeError:
        pass

    recover(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    resumed = NightRunner.resume(
        ledger,
        executor,
        night_id=NIGHT,
        clock=ScriptedClock("2026-10-30T23:00:00Z"),
    )
    resumed.run()
    status = resumed.stop()

    assert status.status == "ran short"
    assert "min lost" in status.reason
    projection = NightProjection(ledger.events())
    assert projection.task("task_0002").state == "kept"
