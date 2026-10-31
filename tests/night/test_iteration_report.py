"""The morning's iteration cards: the winner, and what it beat.

A night task is no longer one attempt, so the morning has to answer two
questions the owner would otherwise have to guess at:

* **which one did we keep?** — the winner, with its score and the round it
  came from;
* **what did it beat?** — the runner-ups, their scores, and why they lost.

And it has to say **where the loop stopped** — on a gain that fell below ε,
on the bar, or because the rounds ran out — because a loop that stopped early
and a loop that finished look the same from the outside.

The numbers behind it are the data the depth policy is tuned from: the
quality gained in each round, and the joules each round cost (still
unmeasured — lab round 3 supplies the Thor's rails).
"""

from __future__ import annotations

import pytest

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.iterate import (
    CriticScore,
    ScriptedCritic,
    ScriptedVariantSource,
    Variant,
)
from core.night.ledger import InMemoryLedger
from core.night.models import Rail, Task
from core.night.report import build_report, render_html, render_text
from core.night.runner import NightRunner

NIGHT = "night_2026-10-30"

CATALOGUE = {
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


def run_an_iterating_night(scores: dict[str, float], **kwargs) -> list:
    """A night whose loop runs to whatever the scores make it run to."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    source = ScriptedVariantSource({"task_0001": CATALOGUE})
    critic = ScriptedCritic(
        {
            "task_0001": {
                variant_id: CriticScore(score=score, reason=f"scored {score}")
                for variant_id, score in scores.items()
            }
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=kwargs.pop("rails", Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0)),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
        variant_source=source,
        critic=critic,
        **kwargs,
    )
    runner.start(
        [
            Task(
                id="task_0001",
                intention="Weather the harbour crates",
                cost_estimate=Rail(gpu_minutes=30.0, hosted_cents=0, wall_minutes=45.0),
            )
        ]
    )
    runner.run()
    runner.stop()
    return ledger.events()


def the_loop_that_finds_a_better_variant() -> dict[str, float]:
    """Round three beats the first try by a clear margin."""
    return {
        "v1": 0.42,
        "v2": 0.55,
        "v3": 0.50,
        "w1": 0.71,
        "w2": 0.60,
        "x1": 0.72,
    }


def test_the_morning_names_the_winner_the_loop_kept():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    assert len(report.iterations) == 1
    card = report.iterations[0]
    assert card.task_id == "task_0001"
    assert card.intention == "Weather the harbour crates"
    assert card.winner.variant_id == "x1"
    assert card.winner.score == 0.72
    assert card.winner.round == 3


def test_the_morning_names_what_the_winner_beat():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    beaten = {runner_up.variant_id: runner_up for runner_up in card.runner_ups}
    assert "v1" in beaten, "the first try must be among the things it beat"
    assert beaten["v1"].score == 0.42
    assert "0.30" in beaten["v1"].why


def test_the_morning_says_why_a_runner_up_lost():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    beaten = {runner_up.variant_id: runner_up for runner_up in card.runner_ups}
    assert "below the winner" in beaten["v2"].why


def test_the_morning_says_that_a_runner_up_was_the_warm_start():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    beaten = {runner_up.variant_id: runner_up for runner_up in card.runner_ups}
    assert "warm start" in beaten["w1"].why
    assert "round 3" in beaten["w1"].why


def test_the_morning_shows_the_quality_gained_in_each_round():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    assert [row.round for row in card.rounds] == [1, 2, 3]
    assert [row.gain for row in card.rounds] == [
        pytest.approx(0.55),
        pytest.approx(0.16),
        pytest.approx(0.01),
    ]


def test_the_morning_says_where_the_loop_stopped():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    assert card.stop == "no improvement"
    assert "gain" in card.stop_detail


def test_the_morning_says_the_bar_cut_the_loop_short():
    """The rail can cut a loop, and the morning has to say where (§3.2.5)."""
    report = build_report(
        run_an_iterating_night(
            {"v1": 0.42, "v2": 0.55, "v3": 0.50},
            rails=Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=560.0),
        )
    )
    card = report.iterations[0]
    assert card.stop == "rail"
    assert "80%" in card.stop_detail


def test_the_joules_field_is_measured_from_the_rails():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    card = report.iterations[0]
    assert card.joules is not None
    assert card.joules > 0
    assert all(row.joules is not None for row in card.rounds)
    assert "not measured" not in render_html(report)


def test_the_numbers_carry_the_iteration_counts():
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    numbers = report.numbers
    assert numbers.iterated_tasks == 1
    assert numbers.variants_scored == 6
    assert numbers.quality_gained == pytest.approx(0.30)


def test_the_night_says_where_its_extra_wall_time_went():
    """A night that ran long says the long was the loop, not a mystery."""
    report = build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant()))
    assert report.numbers.wall_overrun_minutes == 225.0
    assert "went on 6 variants" in render_html(report)
    assert "went on 6 variants" in render_text(report)


def test_a_night_with_no_loop_has_no_iteration_card():
    ledger = InMemoryLedger()
    runner = NightRunner(
        ledger,
        ScriptedExecutor({"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}),
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([Task(id="task_0001", intention="Weather the harbour crates")])
    runner.run()
    runner.stop()

    report = build_report(ledger.events())
    assert report.iterations == []
    assert report.numbers.iterated_tasks == 0


def test_the_page_shows_the_winner_and_what_it_beat():
    html = render_html(build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant())))
    assert "refined c" in html
    assert "seed 1024" in html
    assert "below the winner" in html


def test_the_text_mode_shows_the_winner_and_what_it_beat():
    text = render_text(build_report(run_an_iterating_night(the_loop_that_finds_a_better_variant())))
    assert "refined c" in text
    assert "below the winner" in text
