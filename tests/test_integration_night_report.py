"""The merge's own proof: the runner's morning report renders from the
spine's real ledger.

Before the seats merged, the night runner folded its own log and the spine
(core-api) kept another; the m1 acceptance run called that out ("there are
more ledgers than one"). This is the test that integration closes it with:
one evening's worth of events — written by the spine's own services into its
real store — folded by the runner's projection and rendered into the morning
report, with the computed status line §3.4 demands. Nothing is scripted on
the runner's side; its seams (executor, critic) are not used, only the fold
and the renderer.
"""
from __future__ import annotations

from core.events import Actor, owner_actor
from core.models import Rail
from core.night.projection import NightProjection
from core.night.report import build_report, render_html, render_text
from core.night.status import compute_status
from core.svc.budget import BudgetService
from core.svc.nights import NightsService
from core.svc.predictions import PredictionsService
from core.svc.tasks import TasksService


def _an_evening(core, actor) -> tuple[str, str, str]:
    """One evening through the spine's own doors: a slated goal, a night,
    a sealed bet that the critic scores, spend against the bar, a load."""
    tasks = TasksService(core)
    task = tasks.create(author="casey", owner_character="prop-maker",
                        intention="Forest the east slope, keep the oak",
                        cost_estimate=Rail(gpu_minutes=30.0, wall_minutes=45.0))

    nights = NightsService(core, core.settings)
    night_id = nights.start(actor, load_budget={"trellis2": 1})["night"]["id"]

    predictions = PredictionsService(core)
    sealed = predictions.seal(
        actor, branch_ref="br_main@ver_root",
        claim="the crates read as weathered wood", claim_type="material_read",
        confidence="guess", basis="0 observations",
        render_spec={"rung": 2, "resolution": 1024, "seed": 4471})
    predictions.score(sealed.id, "hit",
                      scored_by=Actor(kind="critic", id="critic"))

    budget = BudgetService(core)
    budget.record_spend(night_id, {"gpu_minutes": 45.5, "hosted_cents": 0,
                                   "wall_minutes": 62.0}, job="job_1")
    budget.model_load(night_id, "trellis2")

    tasks.set_state(task.id, "kept", reason="the loop's winner, kept by the critic")
    nights.stop(night_id, actor, reason="rails spent")
    return night_id, task.id, sealed.id


def test_the_morning_report_renders_from_the_spines_own_ledger(core):
    actor = owner_actor("casey")
    night_id, task_id, prediction_id = _an_evening(core, actor)

    events = core.store.events_since(0)
    projection = NightProjection(events)
    report = build_report(events)
    status = compute_status(projection)

    # the night the spine wrote is the night the fold reads
    assert projection.night is not None
    assert projection.night.id == night_id
    assert projection.spend.gpu_minutes == 45.5
    assert projection.model_loads == {"trellis2": 1}

    # the sealed bet, its score and the kept goal all came through
    assert projection.predictions[prediction_id]["verdict"] == "hit"
    assert projection.task(task_id).state == "kept"

    # the status line is COMPUTED from those events (§3.4), one of the four
    assert status.status in ("ran as planned", "ran short", "ran degraded", "did not run")

    # and the report renders — html, json (the model), text (the same read)
    assert night_id in render_text(report)
    assert night_id in render_html(report)
    assert report.tasks[0].task_id == task_id


def test_the_report_is_the_same_read_after_a_cold_reopen(core, settings):
    """The kill -9 property (§5.4), at the fold level: a fresh process that
    sees only the ledger renders the identical report."""
    actor = owner_actor("casey")
    _an_evening(core, actor)
    before = build_report(core.store.events_since(0)).model_dump(mode="json")
    core.store.close()

    from tests.test_durability import reopen  # the spine's own reopen helper

    again = reopen(settings)
    try:
        after = build_report(again.store.events_since(0)).model_dump(mode="json")
    finally:
        again.store.close()
    assert after == before
