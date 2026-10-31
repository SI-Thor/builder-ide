"""Three more mornings: the loop that wins, the bar that cuts it, the loop that stalls.

The four-mornings suite covers the mornings the *status line* has to survive.
These three cover the mornings the **iterator loop** has to survive:

* **iteration wins** — the loop found a better variant than the first try,
  and the morning says which one it kept and what it beat;
* **the rail cuts the loop** — the bar stopped the loop short, and the
  morning says so instead of pretending the night did what it meant to;
* **the loop stalls** — the score stopped improving, so the loop stopped
  early, and the morning says that too.

A morning that hides any of the three is a morning that lies about the
night, and the night runner's whole promise is that it does not (§3.4).
"""

from __future__ import annotations

from core.night.nights import (
    all_mornings,
    iteration_night,
    iteration_rail_cut_night,
    iteration_stalled_night,
)
from core.night.projection import NightProjection


def a_night(name: str):
    return next(night for night in all_mornings() if night.name == name)


def test_a_night_where_iteration_finds_a_better_variant_names_the_winner():
    night = iteration_night()
    assert len(night.report.iterations) == 1
    card = night.report.iterations[0]
    assert card.winner.round == 3, "the winner must come from a later round"
    assert card.winner.score > 0.7
    assert "refined c" in night.html()


def test_a_night_where_iteration_finds_a_better_variant_says_what_it_beat():
    night = iteration_night()
    card = night.report.iterations[0]
    beaten = {runner_up.variant_id for runner_up in card.runner_ups}
    assert "v1" in beaten, "the first try must be named among the things it beat"
    assert card.quality_gained > 0.2


def test_a_night_where_iteration_finds_a_better_variant_still_says_ran_as_planned():
    night = iteration_night()
    assert night.report.status.status == "ran as planned"


def test_a_night_where_the_rail_cuts_the_loop_says_ran_short():
    night = iteration_rail_cut_night()
    assert night.report.status.status == "ran short"
    assert "bar" in night.report.status.reason
    assert "loop" in night.report.status.reason


def test_a_night_where_the_rail_cuts_the_loop_says_where_it_was_cut():
    night = iteration_rail_cut_night()
    card = night.report.iterations[0]
    assert card.stop == "rail"
    assert "80%" in card.stop_detail
    assert "stopped" in night.html()


def test_a_night_where_the_rail_cuts_the_loop_still_keeps_the_winner_it_has():
    night = iteration_rail_cut_night()
    card = night.report.iterations[0]
    assert card.winner.variant_id, "the work it did keep must still be kept"
    assert card.winner.round == 1


def test_a_night_where_the_loop_stalls_says_where_it_stopped():
    night = iteration_stalled_night()
    card = night.report.iterations[0]
    assert card.stop == "no improvement"
    assert "gain" in card.stop_detail
    assert "stopped" in night.html()


def test_a_night_where_the_loop_stalls_does_not_run_another_round():
    night = iteration_stalled_night()
    projection = NightProjection(night.events)
    rounds = {attempt.round for attempt in projection.attempts_for("task_0001")}
    assert rounds == {1, 2}, "the loop must stop before opening a third round"


def test_a_night_where_the_loop_stalls_is_still_ran_as_planned():
    """The loop stopping on its own rule is the plan working, not a failure."""
    night = iteration_stalled_night()
    assert night.report.status.status == "ran as planned"


def test_every_iteration_morning_reports_the_joules_it_measured():
    """Lab round 3 supplied the rails, so the morning quotes a number."""
    for night in (iteration_night(), iteration_rail_cut_night(), iteration_stalled_night()):
        for card in night.report.iterations:
            assert card.joules is not None, night.name
            assert card.joules > 0, night.name
        assert "not measured" not in night.html(), night.name
        assert "J" in night.html(), night.name
