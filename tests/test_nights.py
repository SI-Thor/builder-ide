"""The night (§1.9, §3.2, §3.4).

The status line is the piece the spec is most specific about: four values,
computed, never narrated. ``ran as planned`` / ``ran short`` /
``ran degraded`` / ``did not run`` — plus a one-line reason, and never a
fabricated one. The night report is the same ledger read, so it can be
rebuilt at any time.
"""
from __future__ import annotations

import pytest

from core.events import core_actor, owner_actor
from core.svc.nights import NightsService
from core.svc.report import ReportBuilder
from core.svc.tasks import TasksService

STATUS_VALUES = ("ran_as_planned", "ran_short", "ran_degraded", "did_not_run")


@pytest.fixture
def nights(core):
    return NightsService(core, core.settings)


# ------------------------------------------------------------- starting

def test_starting_a_night_returns_a_preflight_line(core, nights):
    """§3.2.2: the pre-flight proposes, the owner decides."""
    out = nights.start(owner_actor("casey"), detach_after_min=30)
    assert out["night"]["state"] == "running"
    assert out["preflight_line"].startswith("PREFLIGHT:")
    assert out["preflight"]["telemetry_ok"] is False  # the blind telemetry says so


def test_the_preflight_says_it_is_blind_rather_than_guessing(core, nights):
    """Blind telemetry is None, not 0. The pre-flight says so in words."""
    out = nights.start(owner_actor("casey"))
    assert "telemetry blind" in out["preflight_line"]


def test_only_one_night_runs_at_a_time(core, nights):
    from core.errors import Refused

    nights.start(owner_actor("casey"))
    with pytest.raises(Refused):
        nights.start(owner_actor("casey"))


def test_the_slate_becomes_the_queue_when_the_night_starts(core, nights):
    """§3.2: the slate is pre-night; the tasks join the night when it runs."""
    task = TasksService(core).create(author="magnus", intention="more crates")
    assert task.state == "slated"
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    assert TasksService(core).get(task.id).state == "queued"


def test_a_task_filed_before_any_night_has_no_night(core):
    task = TasksService(core).create(author="casey", intention="check the tide")
    assert task.night is None
    assert task.state == "slated"


# ------------------------------------------------------------- the ask

def test_a_task_filed_without_an_ask_is_priced_from_the_cost_model(core):
    """The slate does not take a number from the client — it asks the model."""
    from core.night.cost import get_model

    task = TasksService(core).create(author="casey", intention="weather the harbour crates")
    band = get_model().band("prop.goal")
    assert task.kind == "prop.goal"
    assert task.ask_source == "model"
    assert task.ask_basis == band.basis
    assert task.cost_estimate.gpu_minutes == pytest.approx(band.p50.gpu_minutes)
    assert task.cost_estimate.wall_minutes == pytest.approx(band.p50.wall_minutes)
    # and the rail is the kind's p95 — the most it may spend before it is cut
    assert task.rail.gpu_minutes == pytest.approx(band.p95.gpu_minutes)


def test_a_task_can_name_the_job_kind_it_is(core):
    from core.night.cost import get_model

    task = TasksService(core).create(author="casey", intention="a picture of a crate",
                                     kind="prop.image")
    band = get_model().band("prop.image")
    assert task.kind == "prop.image"
    assert task.cost_estimate.wall_minutes == pytest.approx(band.p50.wall_minutes)


def test_a_job_kind_the_model_does_not_know_is_refused_by_name(core):
    from core.errors import Refused

    with pytest.raises(Refused) as caught:
        TasksService(core).create(author="casey", intention="a very large prop",
                                  kind="prop.gigantic")
    assert "prop.gigantic" in str(caught.value)
    assert "prop.goal" in str(caught.value)


def test_a_client_ask_becomes_an_override_and_is_recorded(core):
    """The owner's own number is kept, not overwritten — and it says so."""
    from core.models import Rail

    task = TasksService(core).create(
        author="casey", intention="one very large render",
        cost_estimate=Rail(gpu_minutes=300.0, wall_minutes=45.0),
    )
    assert task.ask_source == "override"
    assert task.ask_basis == "estimate", "a typed-in number is an estimate"
    assert task.cost_estimate.gpu_minutes == pytest.approx(300.0)
    assert task.kind == "prop.goal", "the kind it is held against is still recorded"


def test_an_override_is_held_to_its_own_number_not_to_the_model_s(core):
    """A big override must not be cut by the model's own (smaller) rail."""
    from core.models import Rail

    task = TasksService(core).create(
        author="casey", intention="one very large render",
        cost_estimate=Rail(gpu_minutes=300.0, wall_minutes=45.0),
    )
    assert task.rail.gpu_minutes == pytest.approx(300.0)
    assert task.rail.wall_minutes == pytest.approx(45.0)


# ------------------------------------------------------------- the slate's two lines

def test_the_slate_shows_the_owner_two_lines(core):
    """The owner reads what tonight will cost, and whether it fits, before
    the night starts."""
    TasksService(core).create(author="casey", intention="weather the harbour crates")
    slate = TasksService(core).slate()
    lines = slate["estimate"]["lines"]
    assert len(lines) == 2
    assert lines[0].startswith("Tonight: 1 goal")
    assert "It fits" in lines[1]
    assert slate["estimate"]["fits"] is True


def test_the_slate_shows_where_each_ask_came_from(core):
    TasksService(core).create(author="casey", intention="weather the harbour crates")
    row = TasksService(core).slate()["rows"][0]
    assert row["kind"] == "prop.goal"
    assert row["ask_source"] == "model"
    assert row["overridden"] is False
    assert row["marked"] == "", "a measured price is not an estimate"


def test_an_override_is_shown_next_to_the_model_price(core):
    """The owner sees what the box says the work costs beside the number
    they filed."""
    from core.models import Rail

    TasksService(core).create(
        author="casey", intention="one very large render",
        cost_estimate=Rail(gpu_minutes=300.0, wall_minutes=45.0),
    )
    row = TasksService(core).slate()["rows"][0]
    assert row["overridden"] is True
    assert row["marked"] == "[e]", "every estimate is marked until it is measured"
    assert row["ask"]["gpu_minutes"] == pytest.approx(300.0)
    assert row["model_ask"]["gpu_minutes"] < 300.0


def test_a_slate_that_does_not_fit_names_the_cut(core):
    from core.models import Rail

    TasksService(core).create(
        author="casey", intention="the impossible render",
        cost_estimate=Rail(gpu_minutes=900.0, wall_minutes=900.0),
    )
    slate = TasksService(core).slate()
    assert slate["estimate"]["fits"] is False
    assert "It does not fit" in slate["estimate"]["line_two"]
    assert slate["estimate"]["cut"], "the cut is named"


def test_a_slate_that_does_not_fit_is_refused_with_the_cut_named(core, nights):
    """The refusal happens before the night spends anything, and it names the
    goal that falls off the end."""
    from core.errors import Refused
    from core.models import Rail

    started = nights.start(core_actor())
    nid = started["night"]["id"]
    TasksService(core).create(
        author="casey", intention="the impossible render",
        cost_estimate=Rail(gpu_minutes=900.0, wall_minutes=900.0),
    )
    with pytest.raises(Refused) as caught:
        TasksService(core).attach_slate_to_night(nid)
    assert "does not fit" in str(caught.value)
    assert "the impossible render" in str(caught.value)
    # and nothing was cut silently: the goal is still on the slate
    assert [t.intention for t in TasksService(core).slated_tasks()] == [
        "the impossible render"]


def test_a_night_that_does_not_fit_is_not_started(core, nights):
    from core.errors import Refused
    from core.models import Rail

    TasksService(core).create(
        author="casey", intention="the impossible render",
        cost_estimate=Rail(gpu_minutes=900.0, wall_minutes=900.0),
    )
    with pytest.raises(Refused):
        nights.start(core_actor())
    assert [n for n in core.store.scan("nights") if n.get("state") == "running"] == []


def test_the_night_start_writes_the_two_lines_into_the_log(core, nights):
    """The morning quotes the two lines the owner read this evening."""
    TasksService(core).create(author="casey", intention="weather the harbour crates")
    started = nights.start(core_actor())
    assert len(started["estimate"]["lines"]) == 2
    events = core.store.events_since(0, types=["night.started"])
    payload = events[-1].payload
    assert payload["estimate"]["lines"][0].startswith("Tonight: 1 goal")


# ------------------------------------------------------------- the status line

def test_a_night_with_no_heartbeats_did_not_run(core, nights):
    """No ticks and blind telemetry: the status is uncertain, never invented."""
    out = nights.start(owner_actor("casey"))
    status = nights.compute_status(out["night"]["id"])
    assert status["status"] == "did_not_run"
    assert "unknown (no telemetry)" in status["line"]


def test_a_night_with_heartbeats_and_nothing_wrong_ran_as_planned(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    status = nights.compute_status(nid)
    assert status["status"] == "ran_as_planned"
    assert status["line"] == "ran as planned"


def test_a_cut_task_makes_the_night_ran_short(core, nights):
    """The cut is named: the morning says what was dropped."""
    task = TasksService(core).create(author="casey", intention="forest the east slope")
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    core.store.append(core.store.new_event(
        "night.task.state", core_actor(), {"entity_kind": "task", "entity_id": task.id},
        {"to": "cut", "night": nid}))
    status = nights.compute_status(nid)
    assert status["status"] == "ran_short"
    assert "cut" in status["reason"]


def test_a_degraded_verdict_makes_the_night_ran_degraded(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    core.store.append(core.store.new_event(
        "critic.verdict", core_actor(), {"entity_kind": "node", "entity_id": "n1"},
        {"verdict": "keep", "degraded": True, "reason_code": "too_busy"}))
    status = nights.compute_status(nid)
    assert status["status"] == "ran_degraded"
    assert "scripted" in status["reason"]


def test_the_status_is_always_one_of_four_values(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    for tick in (None, "load"):
        if tick:
            nights.tick(nid, load=0.1)
        assert nights.compute_status(nid)["status"] in STATUS_VALUES


# ------------------------------------------------------------- stopping

def test_stopping_a_night_commits_the_branches_and_writes_the_report(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    stopped = nights.stop(nid, owner_actor("casey"), reason="done")
    assert stopped["night"]["state"] == "stopped"
    assert stopped["night"]["stop_reason"] == "done"
    assert stopped["status"]["status"] in STATUS_VALUES
    assert stopped["report"]["night"]["id"] == nid


def test_stopping_a_night_writes_the_calibration_report(core, nights):
    """The nightly job writes the calibration report beside the morning.

    The night's own log is the only input: the confidence's calibration is
    read out of the judgments the night made and the outcomes that
    answered them, so the report cannot disagree with the morning.
    """
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    stopped = nights.stop(nid, owner_actor("casey"), reason="done")
    calibration = stopped["calibration"]
    assert calibration["confidence_definition"] == "top_probability"
    assert calibration["n_judgments"] == 0
    assert calibration["cells"] == []
    assert calibration["drift"] == []


class _StoreLedger:
    """The judge's ledger port, over the core's own store.

    The judge package writes one audit type; this is the door it goes
    through when the log of record is the core's store rather than the
    in-memory ledger its own tests use.
    """

    def __init__(self, store):
        self._store = store

    def append(self, *, type, actor, subject, payload, artifact=None, at=None):
        event = self._store.new_event(type, actor, subject, payload, artifact)
        if at is not None:
            event.at = at
        committed, _ = self._store.append(event)
        return committed

    def events(self, *, since_seq=None, types=None):
        return self._store.events_since(
            since_seq or 0, types=list(types) if types else None
        )

    def last_seq(self):
        events = self._store.events_since(0)
        return events[-1].seq if events else 0


def test_the_nights_calibration_report_reads_the_nights_judgments(core, nights):
    """A judgment the night made, answered by an outcome, is scored."""
    from core.judge.backends import BackendReply, FakeBackend
    from core.judge.judge import Judge
    from core.judge.models import Question

    class Scripted(FakeBackend):
        def __init__(self):
            super().__init__()
            self.name = "d1"
            self.model = "d1-2B"

        def ask(self, state, questions):
            distributions = {q.qid: {"true": 0.9, "false": 0.1} for q in questions}
            confidences = {q.qid: 0.9 for q in questions}
            return BackendReply(
                backend=self.name,
                model=self.model,
                distributions=distributions,
                confidences=confidences,
                input_tokens=1,
                wall_seconds=0.001,
            )

    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    judge = Judge(Scripted(), ledger=_StoreLedger(core.store))
    judge.judge(
        task="alive",
        state="s",
        questions=[Question(qid="alive", kind="noul", instructions="The root is alive.")],
        scope="art_1",
    )
    core.store.append(
        core.store.new_event(
            "critic.verdict",
            core_actor("critic"),
            {"entity_kind": "artifact", "entity_id": "art_1"},
            {"verdict": "keep", "scope": "art_1"},
        )
    )
    stopped = nights.stop(nid, owner_actor("casey"), reason="done")
    calibration = stopped["calibration"]
    assert calibration["n_judgments"] == 1
    assert calibration["n_scored"] == 1
    assert calibration["cells"][0]["cell"]["task"] == "alive"


def test_stopping_a_night_twice_is_idempotent(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.stop(nid, owner_actor("casey"))
    again = nights.stop(nid, owner_actor("casey"))
    assert again["already_stopped"] is True


def test_stopping_an_unknown_night_is_a_404(core, nights):
    from core.errors import NotFound

    with pytest.raises(NotFound):
        nights.stop("night_nope", owner_actor("casey"))


# ------------------------------------------------------------- the report

def test_the_report_leads_with_the_status_line(core, nights):
    """§3.2.8: the first content line is the computed status, not a title."""
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    nights.stop(nid, owner_actor("casey"))
    built = ReportBuilder(core).build(nid)
    assert built["doc"]["status_line"]["status"] in STATUS_VALUES
    text = built["text_bytes"].decode("utf-8")
    assert built["doc"]["status_line"]["line"] in text


def test_the_report_splits_critic_keeps_from_owner_keeps(core, nights):
    """RV patch 2: the kept-count is split, so "8/10 kept" cannot hide who."""
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    core.store.append(core.store.new_event(
        "critic.verdict", core_actor(), {"entity_kind": "node", "entity_id": "n1"},
        {"verdict": "keep", "reason_code": "too_busy"}))
    built = ReportBuilder(core).build(nid)
    numbers = built["doc"]["night_numbers"]
    assert numbers["critic_keeps"] == 1
    assert numbers["owner_keeps"] == 0
    assert "critic-keeps" in numbers["line"]


def test_the_report_is_the_same_ledger_read_in_text_mode(core, nights):
    out = nights.start(owner_actor("casey"))
    nid = out["night"]["id"]
    nights.tick(nid, load=0.2)
    built = ReportBuilder(core).build(nid)
    text = built["text_bytes"].decode("utf-8")
    assert nid in text
    assert built["doc"]["night"]["id"] in text
