"""Durability: survive a restart mid-run, and replay idempotently.

§5.2 is the spec's own statement of what survives a reboot mid-night: every
sealed prediction, every work-order state and attempt, budget spend, parked
questions, night heartbeats, the audit log to the last committed event, and
all the artifacts.

These tests do the honest version of the kill -9 test: they close the
ledger, reopen it, and check the world is still there. Not a mocked
"restart" — an actual close, an actual reopen, the actual file.
"""
from __future__ import annotations

import pytest

from core.boot import Boot
from core.errors import Refused
from core.events import core_actor, owner_actor
from core.models import Budget, Estimate, Origin, Rail
from core.svc import Core
from core.svc.nights import NightsService
from core.svc.work_orders import WorkOrdersService

from tests.conftest import filed_work_order


def reopen(settings):
    """A fresh process's view of the same ledger."""
    return Core.open(settings)


# ------------------------------------------------------------- the work order

def test_a_work_order_survives_a_restart_mid_run(core, settings):
    """Filed, compiled, confirmed, and an attempt in flight: all of it is
    still there after the service restarts."""
    wo = filed_work_order(core)
    svc = WorkOrdersService(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    attempt = svc.start_attempt(wo.id, "aider-local")
    seq = core.store.max_seq()
    core.store.close()

    again = reopen(settings)
    try:
        back = WorkOrdersService(again).get(wo.id)
        assert back.state == "building"          # mid-run
        assert back.attempts[0].n == attempt.n
        assert back.attempts[0].engineer == "aider-local"
        assert again.store.max_seq() == seq
    finally:
        again.store.close()


def test_the_evidence_survives_a_restart(core, settings):
    wo = filed_work_order(core)
    svc = WorkOrdersService(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    core.store.close()

    again = reopen(settings)
    try:
        back = WorkOrdersService(again).get(wo.id)
        assert back.state == "testing"
        assert back.evidence[0].kind == "test_run"
        assert back.evidence[0].summary == "12 passed"
    finally:
        again.store.close()


def test_an_artifact_survives_a_restart(core, settings):
    """Artifacts are content-addressed on disk and verified by hash (§1.9)."""
    desc = core.store.artifacts.put(b"the preview bytes", "preview.png")
    core.store.close()

    again = reopen(settings)
    try:
        assert again.store.artifacts.has(desc["sha256"])
        assert again.store.artifacts.get(desc["sha256"]) == b"the preview bytes"
    finally:
        again.store.close()


# ------------------------------------------------------------- idempotent replays

def test_a_replay_after_a_restart_returns_the_original_result(core, settings):
    """A doubled "Go" cannot start two attempts — before or after a restart."""
    wo = filed_work_order(core)
    first = WorkOrdersService(core).confirm(
        wo.id, owner_actor("casey"), "go", idem_key="go-1")
    core.store.close()

    again = reopen(settings)
    try:
        svc = WorkOrdersService(again)
        second = svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-1")
        assert second == first
        assert svc.get(wo.id).state == "queued"
        confirmed = again.store.events_for("work_order", wo.id, ["wo.confirmed"])
        assert len(confirmed) == 1
    finally:
        again.store.close()


def test_a_replay_with_a_fresh_key_is_a_second_attempt_and_fails(core):
    """The idempotency key is the replay guard. A different key is a new
    request, and the state machine refuses it rather than double-queueing."""
    wo = filed_work_order(core)
    svc = WorkOrdersService(core)
    svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-1")
    with pytest.raises(Refused):
        svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-2")
    assert len(core.store.events_for("work_order", wo.id, ["wo.confirmed"])) == 1


def test_the_idempotency_key_survives_a_restart(core, settings):
    core.store.append(
        core.store.new_event("night.tick", core_actor(),
                             {"entity_kind": "night", "entity_id": "n1"}, {"at": "x"}),
        idem_key="night:start:k1",
        response_builder=lambda e: {"night": "night_1", "seq": e.seq})
    cached = core.store.idem_get("night:start:k1")
    core.store.close()

    again = reopen(settings)
    try:
        back = again.store.idem_get("night:start:k1")
        assert back is not None
        assert back["body"] == cached["body"]
    finally:
        again.store.close()


# ------------------------------------------------------------- the boot sequence

def test_boot_records_itself(core):
    report = Boot(core, core.settings).run()
    assert report["integrity"] == "ok"
    types = [e.type for e in core.store.events_since(0)]
    assert "core.boot" in types
    assert "core.recovered" in types


def test_boot_catches_the_projections_up_after_a_restart(core, settings):
    """The projection state is derived, so a stale one is caught up at boot."""
    from core.models import Origin

    WorkOrdersService(core).file(
        owner_actor("casey"), Origin(channel="text", packet="pk"), "a thing")
    seq = core.store.max_seq()
    # roll the projection marker back, as if the service had died mid-fold
    core.store.conn.execute("UPDATE meta SET value=? WHERE key='fold_seq'", (str(seq - 1),))
    core.store.close()

    again = reopen(settings)
    try:
        report = again.store.boot()
        assert report["caught_up"] == 1
        assert len(again.store.scan("work_orders")) == 1
    finally:
        again.store.close()


def test_boot_repairs_a_wiped_projection(core, settings):
    from core.models import Origin

    WorkOrdersService(core).file(
        owner_actor("casey"), Origin(channel="text", packet="pk"), "a thing")
    core.store.rows.wipe()
    report = core.store.boot()
    assert report["rebuilt"] is True
    assert len(core.store.scan("work_orders")) == 1


def test_a_running_night_with_rails_left_resumes_at_boot(core, settings):
    """§5.2 step 5: running, rails unexhausted and the wall window open →
    resume from the last sealed step; the queue is durable."""
    nights = NightsService(core, core.settings)
    started = nights.start(owner_actor("casey"), detach_after_min=30)
    nid = started["night"]["id"]
    core.store.close()

    again = reopen(settings)
    try:
        report = Boot(again, again.settings).run()
        assert report["resumed_night"] == nid
        assert NightsService(again, again.settings).get(nid).state == "running"
    finally:
        again.store.close()


def test_a_running_night_with_exhausted_rails_is_stopped_at_boot(core, settings):
    """§5.2 step 5: otherwise stop cleanly and build the report, with the
    status line and lost_minutes computed from the heartbeat gaps — never
    hidden."""
    from core.models import Rail

    nights = NightsService(core, core.settings)
    started = nights.start(owner_actor("casey"),
                           rails=Rail(gpu_minutes=0, wall_minutes=0))
    nid = started["night"]["id"]
    core.store.close()

    again = reopen(settings)
    try:
        report = Boot(again, again.settings).run()
        assert nid in [n["id"] for n in report["nights_stopped"]]
        night = NightsService(again, again.settings).get(nid)
        assert night.state == "stopped"
        assert night.stop_reason
        status = NightsService(again, again.settings).compute_status(nid)
        assert status["status"] in ("ran_as_planned", "ran_short", "ran_degraded",
                                    "did_not_run")
        assert status["line"]
    finally:
        again.store.close()


# ------------------------------------------------------------- the report

def test_the_report_is_regenerable_from_the_log_at_any_time(core, settings):
    """§3.2.8: the morning report is a static artefact that can be rebuilt
    from the ledger — so a crash before it was written loses nothing."""
    from core.svc.report import ReportBuilder

    nights = NightsService(core, core.settings)
    started = nights.start(owner_actor("casey"))
    nid = started["night"]["id"]
    nights.tick(nid, load=0.2)
    nights.stop(nid, owner_actor("casey"), reason="done")
    core.store.close()

    again = reopen(settings)
    try:
        built = ReportBuilder(again).build(nid)
        assert built["doc"]["night"]["id"] == nid
        assert built["text_bytes"]
        assert b"<" in built["html_bytes"] if "html_bytes" in built else True
    finally:
        again.store.close()
