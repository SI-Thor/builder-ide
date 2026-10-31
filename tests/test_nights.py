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
