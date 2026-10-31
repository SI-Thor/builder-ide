"""The week's budget from the cost model — the arithmetic, checked.

These run in the default suite (no engine, no box): the bands are the
recorded ones, each night's plan is priced from them at p95, the plan
fits the night's rails, and the whole week's wall ask sits inside the
brief's two-hour budget. The last test renders the table on the played
(fake-engine) week — whose renders measured nothing, so the measured
columns read zero and the table says so rather than inventing numbers.
"""

from __future__ import annotations

from core.night.cost.model import get_model

import weekbudget
from meltweek import play_week
from script import NIGHTS


def test_the_asks_come_from_the_recorded_bands_not_typed_numbers():
    model = get_model()
    band = model.rung(2)
    plan = weekbudget.night_plan(NIGHTS[0], model=model)
    assert [j.kind for j in plan.jobs] == ["rung.2", "rung.2",
                                           "critic.verdict"]
    for job in plan.jobs[:2]:  # the bet render and the preview
        assert job.ask.gpu_minutes == band.p95.gpu_minutes
        assert job.ask.wall_minutes == band.p95.wall_minutes
        assert job.ask.hosted_cents == 0  # everything on this week is local
    critic = plan.jobs[2]
    cb = model.critic_verdict()
    assert critic.ask.gpu_minutes == cb.p95.gpu_minutes
    assert critic.model is None  # no model load — the verdict is a write


def test_every_night_fits_its_rails_and_the_two_lines_read():
    checks = weekbudget.fits(NIGHTS)
    assert len(checks) == 7 and all(checks)
    for est in weekbudget.week_estimate(NIGHTS):
        assert est.fits and not est.cut and not est.parked
        assert "GPU-h of the" in est.line_one, est.line_one
        assert "$0.00" in est.line_one, est.line_one
        assert "It fits" in est.line_two, est.line_two


def test_the_weeks_ask_fits_the_briefs_two_hour_budget():
    ask_wall = sum(e.ask.wall_minutes for e in weekbudget.week_estimate(NIGHTS))
    assert ask_wall <= weekbudget.WEEK_WALL_BUDGET_MIN, \
        f"the seven nights ask {ask_wall:.1f} wall-min — the brief's budget " \
        f"is {weekbudget.WEEK_WALL_BUDGET_MIN:.0f}"


def test_the_budget_table_renders_on_the_played_week(world):
    if not world.week.get("nights") or len(world.week["nights"]) < 7:
        play_week(world)  # pragma: no cover — the session test already played it
    table = weekbudget.render_budget_table(
        world, world.artifacts["steps"], NIGHTS)
    assert table.count("\n") >= 14
    # the fake engine measured nothing: the table shows zeros and says the
    # renders ran, it never shows a measured wall it does not have
    rows = weekbudget.night_rows(world, world.artifacts["steps"])
    assert all(r["render_count"] == 0 and r["measured_gpu_minutes"] == 0.0
               for r in rows)
    assert all(r["cut_tasks"] == 0 for r in rows[1:]), \
        "only night one cuts, and its cut is the decision budget's"
    assert rows[0]["cut_tasks"] == 7
