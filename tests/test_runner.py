"""The night runner: the night's lifecycle, its rails and its detach rule.

The rules under test are the spec's:

* the pre-flight **proposes, never decides** (§3.2.2);
* **big batches start on client detach or the deadline**, whichever is first
  (§1.9, RV patch 10) — the morning names it when the client never left;
* **admission is before spend** and the queue stops at the bar, with the cut
  named (§5.5, X C11);
* the **load cap** parks a task rather than swapping a model again (§5.5);
* a **sealed bet is committed before its render job is enqueued** (§5.1).
"""

from __future__ import annotations

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.ledger import InMemoryLedger
from core.night.models import Rail, Task
from core.night.projection import NightProjection
from core.night.runner import NightRunner

NIGHT = "night_2026-10-30"


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(
        id=task_id,
        intention=kwargs.pop("intention", "Forest the east slope, keep the oak"),
        **kwargs,
    )


def a_runner(ledger, executor, **kwargs) -> NightRunner:
    defaults = {
        "night_id": NIGHT,
        "rails": Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        "clock": ScriptedClock("2026-10-30T21:14:00Z"),
    }
    defaults.update(kwargs)
    return NightRunner(ledger, executor, **defaults)


def test_starting_a_night_writes_the_started_event_with_its_rails_and_deadline():
    ledger = InMemoryLedger()
    runner = a_runner(ledger, ScriptedExecutor({}))
    night = runner.start([a_task()])

    assert night.id == NIGHT
    assert night.rails.gpu_minutes == 360.0
    assert night.detach_deadline == "2026-10-30T21:44:00Z"

    event = ledger.events()[0]
    assert event.type == "night.started"
    assert event.payload["rails"]["wall_minutes"] == 560.0


def test_the_client_is_attached_at_the_start_and_the_preflight_never_decides():
    ledger = InMemoryLedger()
    runner = a_runner(ledger, ScriptedExecutor({}))
    runner.start([a_task()])

    projection = NightProjection(ledger.events())
    assert projection.client_state() == "attached"
    assert projection.preflight["proposal"] is None
    assert projection.preflight["queue_depth"] == 1


def test_a_task_runs_and_its_spend_is_recorded_against_the_night():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = a_runner(ledger, executor)
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "kept"
    assert projection.spend.gpu_minutes == 30.0
    assert projection.spend.wall_minutes == 45.0


def test_a_task_whose_projected_cost_does_not_fit_the_night_rail_is_cut():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=400.0, wall_minutes=45.0)}
    )
    runner = a_runner(ledger, executor, rails=Rail(gpu_minutes=360.0, wall_minutes=560.0))
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "cut"
    assert "cut" in projection.reason_for("task_0001")


def test_a_task_whose_projected_cost_does_not_fit_its_own_rail_is_cut():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=90.0, wall_minutes=45.0)}
    )
    runner = a_runner(ledger, executor)
    runner.start([a_task(rail=Rail(gpu_minutes=40.0, wall_minutes=60.0))])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "cut"


def test_the_batches_wait_for_the_client_and_start_when_it_detaches():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    detach_at = "2026-10-30T21:24:00Z"

    def presence(now: str) -> str:
        if now >= detach_at:
            ledger.append(
                type="client.detach",
                actor=ledger.events()[0].actor,
                subject={"entity_kind": "client", "entity_id": "proart"},
                payload={"client": "proart"},
                at=now,
            )
            return "detached"
        return "attached"

    runner = a_runner(ledger, executor, presence=presence)
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    batches = [tick for tick in projection.ticks if tick.payload.get("kind") == "batches"]
    assert batches[0].payload["trigger"] == "detach"
    assert batches[0].payload["late_minutes"] == 10.0


def test_the_batches_start_at_the_deadline_when_the_client_never_detaches():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = a_runner(ledger, executor, presence=lambda now: "attached")
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    batches = [tick for tick in projection.ticks if tick.payload.get("kind") == "batches"]
    assert batches[0].payload["trigger"] == "deadline"
    assert batches[0].payload["cause"] == "the ProArt stayed attached"
    assert batches[0].payload["late_minutes"] == 30.0


def test_the_model_load_cap_parks_a_task_that_would_load_the_model_again():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0, model="trellis2"),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0, model="trellis2"),
        }
    )
    runner = a_runner(ledger, executor)
    runner.start([a_task("task_0001"), a_task("task_0002")])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "kept"
    assert projection.task("task_0002").state == "parked"
    assert "load" in projection.reason_for("task_0002").lower()


def test_at_the_eighty_percent_bar_the_queue_stops_and_the_rest_are_cut():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=300.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = a_runner(ledger, executor, rails=Rail(gpu_minutes=360.0, wall_minutes=560.0))
    runner.start([a_task("task_0001"), a_task("task_0002")])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "kept"
    assert projection.task("task_0002").state == "cut"
    assert "80" in projection.reason_for("task_0002")


def test_a_task_that_runs_past_its_own_rail_is_stopped_at_the_rail():
    """The seat hard-kills at the per-attempt rail (§5.5)."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                actual_wall_minutes=300.0,
            )
        }
    )
    runner = a_runner(ledger, executor)
    runner.start([a_task("task_0001", rail=Rail(gpu_minutes=40.0, wall_minutes=60.0))])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "cut"
    assert "rail" in projection.reason_for("task_0001")


def test_a_sealed_bet_is_committed_before_its_render_job_is_enqueued():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                model="trellis2",
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
    runner = a_runner(ledger, executor)
    runner.start([a_task()])
    runner.run()
    runner.stop()

    events = ledger.events()
    sealed = next(event for event in events if event.type == "prediction.sealed")
    enqueued = next(event for event in events if event.type == "job.enqueued")
    assert sealed.seq < enqueued.seq


def test_stopping_the_night_computes_the_status_from_the_log():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = a_runner(ledger, executor)
    runner.start([a_task()])
    runner.run()
    status = runner.stop()

    assert status.status == "ran as planned"
    stopped = ledger.events()[-1]
    assert stopped.type == "night.stopped"
    assert stopped.payload["status"] == "ran as planned"
