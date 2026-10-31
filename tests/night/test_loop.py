"""The iterator loop: a night task is no longer one attempt.

Core-spec v2 §3.2.4 gives the loop its shape — edit, predict, preview, critic,
keep or revert — and §3.2.5 gives the rails: the bar can stop the night
mid-loop, and the morning has to say where.

The rules under test:

* **N variants per round** — a task is attempted once per candidate, not
  once;
* **the best is kept** — the highest score wins, and only a variant that was
  actually kept can win;
* **warm start** — the next round refines from the winner, and the log says
  which variant each one came from;
* **ε** — the loop stops when a round gains no more than ε;
* **K** — the loop stops after K rounds;
* **the bar can cut the loop** — and the cut is named, with the round it
  happened on;
* **without a critic there is no score to keep the best of**, so the night
  runs the task once, exactly as it did before the loop existed.
"""

from __future__ import annotations

import pytest

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.iterate import (
    CriticScore,
    IterationPolicy,
    NullPowerMeter,
    ScriptedCritic,
    ScriptedVariantSource,
    Variant,
)
from core.night.ledger import InMemoryLedger
from core.night.models import Rail, Task
from core.night.projection import NightProjection
from core.night.runner import NightRunner

NIGHT = "night_2026-10-30"


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(id=task_id, intention="Weather the harbour crates", **kwargs)


def a_runner(ledger, executor, **kwargs) -> NightRunner:
    defaults = {
        "night_id": NIGHT,
        "rails": Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        "clock": ScriptedClock("2026-10-30T21:14:00Z"),
    }
    defaults.update(kwargs)
    return NightRunner(ledger, executor, **defaults)


def a_source(task_id: str = "task_0001", rounds: int = 1) -> ScriptedVariantSource:
    """The variants the night may try: three in round one, two in two, one in three."""
    catalogue = {
        1: [
            Variant(id="v1", label="seed 1024"),
            Variant(id="v2", label="seed 2048"),
            Variant(id="v3", label="seed 4096"),
        ],
        2: [
            Variant(id="w1", label="refined a"),
            Variant(id="w2", label="refined b"),
        ],
        3: [Variant(id="x1", label="refined c")],
    }
    return ScriptedVariantSource(
        {task_id: {round_no: catalogue[round_no] for round_no in range(1, rounds + 1)}}
    )


def a_critic(task_id: str = "task_0001", **scores) -> ScriptedCritic:
    return ScriptedCritic(
        {
            task_id: {
                variant_id: CriticScore(score=score, reason=f"scored {score}")
                for variant_id, score in scores.items()
            }
        }
    )


def an_executor(**kwargs) -> ScriptedExecutor:
    return ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0, **kwargs)}
    )


def jobs(ledger: InMemoryLedger, type: str) -> list:
    return [event for event in ledger.events() if event.type == type]


def test_a_task_with_a_critic_is_attempted_once_per_variant():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    assert len(jobs(ledger, "job.done")) == 3


def test_a_task_with_no_critic_is_attempted_once():
    """Without a critic there is no score to keep the best of."""
    ledger = InMemoryLedger()
    runner = a_runner(ledger, an_executor())
    runner.start([a_task()])
    runner.run()
    runner.stop()

    assert len(jobs(ledger, "job.done")) == 1


def test_the_loop_keeps_the_best_scoring_variant():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.winner_for("task_0001").variant_id == "v2"
    assert projection.task("task_0001").state == "kept"


def test_the_task_s_reason_names_the_winner_that_was_kept():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    reason = projection.reason_for("task_0001")
    assert "0.70" in reason
    assert "seed 2048" in reason


def test_the_next_round_refines_from_the_winner():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(rounds=2),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5, w1=0.8, w2=0.6),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    second_round = [
        attempt for attempt in projection.attempts_for("task_0001") if attempt.round == 2
    ]
    assert second_round, "the loop must have refined after the first round"
    assert {attempt.parent_id for attempt in second_round} == {"v2"}


def test_the_loop_stops_when_the_score_stops_improving():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(rounds=2),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5, w1=0.7, w2=0.6),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.stop_for("task_0001")["reason"] == "no improvement"
    assert len(projection.attempts_for("task_0001")) == 5, "round three must not run"


def test_the_loop_stops_after_the_policy_s_rounds():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(rounds=3),
        critic=a_critic(v1=0.4, v2=0.5, v3=0.45, w1=0.6, w2=0.55, x1=0.7),
        iteration=IterationPolicy(variants_per_round=3, max_rounds=2, min_gain=0.02),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.stop_for("task_0001")["reason"] == "rounds exhausted"
    assert {attempt.round for attempt in projection.attempts_for("task_0001")} == {1, 2}


def test_the_bar_cuts_the_loop_short_and_the_cut_is_named():
    """The rail can cut a loop; the morning has to say where (§3.2.5)."""
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
        rails=Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=560.0),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    stop = projection.stop_for("task_0001")
    assert stop["reason"] == "rail"
    assert "80%" in stop["detail"]
    assert projection.task("task_0001").state == "kept"
    assert len(projection.attempts_for("task_0001")) == 3, "round two must not run"


def test_a_critic_without_a_variant_source_is_refused():
    """Half a loop is not a loop — say so instead of running one attempt."""
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        a_runner(ledger, an_executor(), critic=a_critic(v1=0.4))


def test_the_depth_policy_is_written_into_the_night_s_rails():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4),
        iteration=IterationPolicy(variants_per_round=2, max_rounds=4, min_gain=0.05),
    )
    runner.start([a_task()])

    started = ledger.events()[0]
    assert started.type == "night.started"
    assert started.payload["iteration"] == {
        "variants_per_round": 2,
        "max_rounds": 4,
        "min_gain": 0.05,
    }


def test_the_log_records_the_quality_gained_per_round():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(rounds=3),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5, w1=0.8, w2=0.6, x1=0.82),
        iteration=IterationPolicy(variants_per_round=3, max_rounds=2, min_gain=0.02),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    rounds = projection.iterations["task_0001"]["rounds"]
    assert [row["round"] for row in rounds] == [1, 2]
    assert [row["gain"] for row in rounds] == [pytest.approx(0.7), pytest.approx(0.1)]


def test_the_joules_field_is_measured_from_the_boards_rails():
    """Lab round 3 supplied the rails, so the night measures its own joules."""
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    rounds = projection.iterations["task_0001"]["rounds"]
    assert rounds[0]["joules"] is not None
    assert rounds[0]["joules"] > 0


def test_a_night_with_no_meter_keeps_the_joules_unmeasured():
    """A runner given the null meter reads nothing — and says so."""
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
        power_meter=NullPowerMeter(),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    rounds = projection.iterations["task_0001"]["rounds"]
    assert rounds[0]["joules"] is None


def test_a_loop_where_nothing_was_kept_reverts_the_task():
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                outcome="failed",
                reason="hollow mesh from the image-to-3D model",
            )
        }
    )
    runner = a_runner(
        ledger,
        executor,
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    projection = NightProjection(ledger.events())
    assert projection.task("task_0001").state == "reverted"
    assert projection.winner_for("task_0001") is None


def test_the_variants_are_recorded_in_the_log_with_their_scores():
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    done = jobs(ledger, "job.done")
    assert [event.payload["variant_id"] for event in done] == ["v1", "v2", "v3"]
    assert [event.payload["score"] for event in done] == [0.4, 0.7, 0.5]


def test_the_variant_rides_on_the_job_request():
    """The variant is the job's request — seeded and bounded (§1.9)."""
    ledger = InMemoryLedger()
    runner = a_runner(
        ledger,
        an_executor(),
        variant_source=a_source(),
        critic=a_critic(v1=0.4, v2=0.7, v3=0.5),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()

    enqueued = jobs(ledger, "job.enqueued")
    assert enqueued[0].payload["request"]["variant_id"] == "v1"
    assert enqueued[0].payload["request"]["round"] == 1
