"""The daytime tick: into the log, and back out of it again.

Two promises are tested here. The world that comes out of the log is the
world the arithmetic says it is, and the daytime lane yields to the night —
it must not compete with the work.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def day_ledger():
    from core.daytime.ledger import InMemoryLedger

    return InMemoryLedger()


def _night(ledger, actor, night_id: str, state: str) -> None:
    """The night lane's word: the night is working, or it is over."""
    ledger.append(
        type=f"night.{state}",
        actor=actor,
        subject={"entity_kind": "night", "entity_id": night_id},
        payload={"night_id": night_id},
    )


def test_a_tick_moves_the_clock_and_the_light(fjellvik, day_ledger):
    from core.daytime.runner import DayRunner

    runner = DayRunner(day_ledger, fjellvik, "ver_0192")
    world = runner.tick()

    assert world is not None
    assert world.tick == 1
    assert world.room.light == 8
    # and the log is where that came from
    assert runner.world() == world


def test_the_world_is_rebuilt_from_the_log(fjellvik, day_ledger):
    from core.daytime.runner import DayRunner
    from core.daytime.world import world_at

    runner = DayRunner(day_ledger, fjellvik, "ver_0192")
    for _ in range(5):
        runner.tick()

    assert runner.world() == world_at(fjellvik, "ver_0192", 5)


def test_a_second_runner_picks_the_room_up_where_it_was_left(fjellvik, day_ledger):
    from core.daytime.runner import DayRunner

    first = DayRunner(day_ledger, fjellvik, "ver_0192")
    first.tick()
    first.tick()

    # a fresh runner, same log: the room is where the log says it is
    second = DayRunner(day_ledger, fjellvik, "ver_0192")
    assert second.world() is not None
    assert second.world().tick == 2
    assert second.tick() is not None
    assert second.world().tick == 3


def test_the_daytime_yields_to_the_night(fjellvik, day_ledger, actor):
    from core.daytime.runner import DayRunner

    _night(day_ledger, actor, "night_1", "started")
    runner = DayRunner(day_ledger, fjellvik, "ver_0192")

    assert runner.tick() is None

    # the yield is in the log — the edges are the story
    yields = [e for e in day_ledger.events() if e.type == "day.yielded"]
    assert len(yields) == 1
    assert yields[0].payload["lane"] == "night"
    assert yields[0].payload["reason"]
    # and the room did not move
    assert runner.world() is None


def test_the_daytime_runs_again_when_the_night_stops(fjellvik, day_ledger, actor):
    from core.daytime.runner import DayRunner

    _night(day_ledger, actor, "night_1", "started")
    runner = DayRunner(day_ledger, fjellvik, "ver_0192")
    assert runner.tick() is None

    _night(day_ledger, actor, "night_1", "stopped")
    world = runner.tick()

    assert world is not None
    assert world.tick == 1


def test_the_budget_stops_the_room(fjellvik, day_ledger):
    from core.daytime.budget import DayBudget
    from core.daytime.runner import DayRunner

    runner = DayRunner(day_ledger, fjellvik, "ver_0192", budget=DayBudget(max_ticks=2))
    assert runner.tick() is not None
    assert runner.tick() is not None
    # the third tick is over the bar
    assert runner.tick() is None

    yields = [e for e in day_ledger.events() if e.type == "day.yielded"]
    assert yields[-1].payload["lane"] == "daytime"
    assert runner.world().tick == 2


def test_a_new_night_gives_the_room_a_new_day(fjellvik, day_ledger, actor):
    from core.daytime.budget import DayBudget
    from core.daytime.runner import DayRunner

    runner = DayRunner(
        day_ledger, fjellvik, "ver_0192", budget=DayBudget(max_ticks=1)
    )
    assert runner.tick() is not None
    assert runner.tick() is None  # over the bar for this day

    # the night runs, and the daytime stands down for it
    _night(day_ledger, actor, "night_1", "started")
    assert runner.tick() is None

    # and when the night is over, the day starts fresh
    _night(day_ledger, actor, "night_1", "stopped")
    assert runner.tick() is not None
    assert runner.world().tick == 2


def test_the_daytime_says_what_it_cost(fjellvik, day_ledger):
    from core.daytime.runner import DayRunner

    DayRunner(day_ledger, fjellvik, "ver_0192").tick()

    ticks = [e for e in day_ledger.events() if e.type == "day.tick"]
    assert len(ticks) == 1
    assert ticks[0].payload["tick"] == 1
    assert ticks[0].payload["minutes"] >= 0.0


def test_the_runner_writes_only_daytime_events(fjellvik, day_ledger):
    from core.daytime.events import DAYTIME_EVENT_TYPES
    from core.daytime.runner import DayRunner

    runner = DayRunner(day_ledger, fjellvik, "ver_0192")
    runner.tick()
    runner.tick()

    assert all(e.type in DAYTIME_EVENT_TYPES for e in day_ledger.events())
