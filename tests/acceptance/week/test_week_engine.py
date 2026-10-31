"""The seven-night melt week with the **real engine** behind the render
rungs (opt-in) — plan item 14, the honest week on the real core.

The default suite keeps the fake engine (`meltweek.py` — fast, no engine
on the box required). This module is the other run:

    .venv/bin/python -m pytest tests/acceptance/week -m engine -q

`BUILDER_ENGINE` is set to `real_engine_spec(home)` — the **v2 venv on
this box** (`~/lm-wt/v2-thor`, read-only; `BUILDER_V2_HOME` overrides) —
so every render rung of the seven nights asks Infinigen 2.0 for real:
the world bet's render and the landed work order's preview, each rung 2
of the ladder (960×540, 16 spp) through Cycles on the Thor's GPU. The
session performs the **explicit pin edit** first (X R9), as M1's
real-engine run does — the week reuses M1's boot.

What this run asserts, beyond the week's own steps:

* the melt reproduced **on real renders** — the same 105 steps, the same
  questions 6 → 0, the same per-code arc, from the same one ledger;
* every render step served the real engine, every render is a real PNG
  with its measured wall in the event, and every landed order's preview
  is a real image too;
* the night's bar carries the renders' **measured** GPU/wall minutes (the
  slate's scripted ask was the fake run's number);
* the week was **budgeted from the cost model**: each night's plan
  (priced p95 from the measured bands) fit its rails, nothing cut on the
  GPU axis, and the whole week ran inside the brief's 2-hour wall budget;
* the morning status line is computed from the log for all seven nights.

Skip (not fail) when the venv is not on the box: the named missing piece
is printed, exactly like the engine seam's own refusals.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import weekbudget
from meltweek import teardown_week_world
from realweek import run_week, write_record
from script import EXPECTED_QUESTIONS, NIGHTS
from seats.engine import DEFAULT_V2_HOME

pytestmark = pytest.mark.engine

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def engine_week(tmp_path_factory):
    here = Path(__file__).resolve().parent
    home = tmp_path_factory.mktemp("week-engine-home") / "builder-ide"
    v2_home = Path(
        os.environ.get("BUILDER_V2_HOME", str(DEFAULT_V2_HOME))).expanduser()
    if not (v2_home / ".venv" / "bin" / "python").is_file():
        pytest.skip(
            f"the v2 venv is not at {v2_home} (set BUILDER_V2_HOME to point "
            "elsewhere); the real week has no engine to render with — the "
            "fake-engine week is the default suite"
        )
    run_dir = here / "run" / "engine"
    if run_dir.exists():
        import shutil

        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    ses, world, facts = run_week(home, run_dir, v2_home)
    try:
        yield world
    finally:
        write_record(run_dir, ses, world, facts)
        teardown_week_world(world)
        os.environ.pop("BUILDER_ENGINE", None)


def _week(engine_week):
    return engine_week.artifacts["session"], engine_week.artifacts["facts"]


def test_the_week_plays_end_to_end_on_the_real_engine(engine_week):
    ses, facts = _week(engine_week)
    failed = [s for s in ses.steps if not s.ok]
    assert not failed, f"{len(failed)} failed steps:\n{ses.table()}"
    assert not facts.get("failure"), facts.get("failure")
    # the seven cycles, the boot, the week — and the pin edit this run adds
    acts = {s.act for s in ses.steps}
    assert {"boot", "evening", "night", "morning", "week"} <= acts
    for act in ("evening", "night", "morning"):
        assert sum(1 for s in ses.steps if s.act == act) >= 7 * 4
    assert any(s.name == "engine-repin" for s in ses.steps), \
        "the explicit pin edit (X R9) is a step of this run"


def test_every_render_rung_served_the_real_engine(engine_week):
    ses, _ = _week(engine_week)
    render_steps = [
        s for s in ses.steps
        if any(b.endswith(("engine(render)", "engine(preview)"))
               for b in s.backends)
    ]
    assert len(render_steps) == 14, \
        f"expected a render behind every bet and every preview, got {len(render_steps)}"
    for step in render_steps:
        assert any(b.startswith("real:engine(") for b in step.backends), \
            f"{step.act}/{step.name} was not served by the real engine"


def test_every_render_is_a_real_image_with_its_measured_wall(engine_week):
    ses, _ = _week(engine_week)
    door = engine_week.door
    events = door.raw_events(0, ["render.completed"])
    assert len(events) == 7, \
        f"the seven world bets rendered {len(events)} times"
    for ev in events:
        payload = ev.payload
        assert payload["engine_flavour"] == "infinigen-2-procfunc", payload
        wall = payload.get("wall_ms")
        assert wall is not None and wall > 0, \
            f"render {payload['job_id']} has no measured wall"
        assert payload.get("timing", {}).get("label", "").startswith("measured"), \
            "the morning's box must quote a measured render"
        sha = payload["artifact"]["sha256"]
        data = door.store.artifacts.get(sha)  # hash-verified read
        assert data.startswith(PNG_MAGIC), f"{sha} is not a PNG"
        assert payload["artifact"]["bytes"] > 10_000, \
            f"{sha} is {len(data)} bytes — not a real frame"
    # and every landed order's preview is a real image too (seven mornings)
    board = engine_week.spec.work_orders()
    previews = [w for w in board if w.get("preview")]
    assert len(previews) >= 7, f"{len(previews)} previews on the board"
    for wo in previews:
        data = door.store.artifacts.get(wo["preview"]["sha256"])
        assert data.startswith(PNG_MAGIC), f"{wo['id']}'s preview is not a PNG"
        assert wo["preview"]["bytes"] > 10_000


def test_the_nights_bar_carries_the_measured_renders(engine_week):
    """The fake run's scripted 75 GPU-min a night is not this run's number:
    the bar reads the bet render's measured wall (folded from the ledger),
    and the preview's measured wall joins it after the land."""
    world = engine_week
    ses, _ = _week(world)
    records = world.week["nights"]
    renders = weekbudget.fold_renders(world.door)
    for rec in records:
        night_renders = renders.get(rec.get("night"), [])
        walls = [r["wall_ms"] for r in night_renders if r["wall_ms"]]
        assert len(walls) == 1, \
            f"night {rec['n']}: {len(walls)} measured bet renders"
        spend = rec.get("render_spend") or {}
        assert spend.get("gpu_minutes", 0) == pytest.approx(
            walls[0] / 60000.0), \
            f"night {rec['n']}'s bar did not read the measured render: {spend}"
        assert rec.get("preview_wall_ms"), \
            f"night {rec['n']}'s preview wall was not recorded"


def test_the_week_was_budgeted_from_the_cost_model(engine_week):
    ses, facts = _week(engine_week)
    checks = weekbudget.fits(NIGHTS)
    assert len(checks) == 7 and all(checks), \
        "a night's plan must fit its rails before the week runs"
    estimates = weekbudget.week_estimate(NIGHTS)
    assert all("GPU-h" in e.line_one and "It fits" in e.line_two
               for e in estimates), [e.lines() for e in estimates]
    rows = weekbudget.night_rows(engine_week, ses.steps)
    # the estimate is the p95 band (scene renders); the measured object
    # renders came in under it — the gap is the finding, not a failure
    for row, est in zip(rows, estimates):
        assert row["render_count"] == 2, \
            f"night {row['n']} rendered {row['render_count']} times, not twice"
        assert row["measured_gpu_minutes"] <= est.ask.gpu_minutes, \
            (f"night {row['n']} measured {row['measured_gpu_minutes']:.3f} "
             f"GPU-min against a {est.ask.gpu_minutes:.2f} p95 ask")
    # and the brief's own budget: the whole week inside ~2 hours of wall
    assert facts["run_wall_s"] <= weekbudget.WEEK_WALL_BUDGET_MIN * 60, \
        f"the week took {facts['run_wall_s'] / 60:.1f} min of wall"


def test_the_melt_reproduced_on_real_renders(engine_week):
    ses, _ = _week(engine_week)
    records = engine_week.week["nights"]
    assert [r.get("questions", 0) for r in records] == list(EXPECTED_QUESTIONS)
    attention = [r.get("attention", 0) for r in records]
    assert attention[0] > attention[-1] and all(
        r.get("decisions", 0) <= 10 for r in records)
    assert all(r.get("standing") for r in records)
    assert engine_week.week["table"], "the melt table folded"


def test_the_status_line_is_computed_for_all_seven_nights(engine_week):
    ses, _ = _week(engine_week)
    door = engine_week.door
    for rec in engine_week.week["nights"]:
        night_id = rec.get("night")
        status = door._svc("nights").compute_status(night_id)
        computed = str(status.get("status") or "").replace("_", " ").strip()
        assert computed == rec.get("status"), \
            f"night {rec['n']}: the report's {rec.get('status')!r} is not " \
            f"what the log computes ({computed!r})"
        assert re.search(r"\d", status.get("line", "")), status.get("line")
