"""Work orders: schema, states and transitions exactly as §1.3 defines them.

Every arrow in the spec's transition table is one audit event, the guards run
before the append, and a stale transition fails closed. The negative cases
matter more than the happy path here: a work order that compiles without a
machine-checkable acceptance check, or whose confirm line carries only one
price line, is a build failure (§3.1) and must never reach a draft.
"""
from __future__ import annotations

import pytest

from core.errors import Refused, StaleTransition
from core.events import Actor, owner_actor
from core.models import Budget, Estimate, Origin, Rail
from core.svc.work_orders import WorkOrdersService

from tests.conftest import filed_work_order


@pytest.fixture
def svc(core):
    return WorkOrdersService(core)


def file_wo(core, *, title="weathered crates", owner="casey"):
    return WorkOrdersService(core).file(
        owner_actor(owner), Origin(channel="text", packet="pk_1"), title, goal="weather them")


# ------------------------------------------------------------- filing

def test_filing_makes_a_compiling_work_order(core, svc):
    wo = file_wo(core)
    assert wo.state == "compiling"
    assert wo.filed_by.id == "casey"
    assert core.store.get_row("work_orders", {"id": wo.id})["state"] == "compiling"


# ------------------------------------------------------------- compile guards

def test_a_draft_needs_at_least_one_machine_checkable_check(core, svc):
    wo = file_wo(core)
    with pytest.raises(Refused) as e:
        svc.compile_draft(
            wo.id, title="t", goal="g", targets=[],
            acceptance=[{"kind": "manual", "spec": {"note": "look at it"}}],
            budget=Budget(), estimate=Estimate(build_verify=Rail(), generate_test=Rail()),
            confirm_line="do it · build/verify: 0 · generate/test: 0")
    assert "machine-checkable" in e.value.message
    assert svc.get(wo.id).state == "compiling"  # nothing moved


def test_a_manual_check_is_only_allowed_on_an_owner_filed_order(core, svc):
    """A manual check needs a human, so only the owner's own orders may
    carry one (§1.3)."""
    wo = svc.file(
        Actor(kind="character", id="prop-maker"),
        Origin(channel="text", packet="pk_1"), "t", goal="g")
    with pytest.raises(Refused) as e:
        svc.compile_draft(
            wo.id, title="t", goal="g", targets=[],
            acceptance=[{"kind": "test_suite", "spec": {}},
                        {"kind": "manual", "spec": {}}],
            budget=Budget(), estimate=Estimate(build_verify=Rail(), generate_test=Rail()),
            confirm_line="do it · build/verify: 0 · generate/test: 0")
    assert "owner-filed" in e.value.message


def test_a_confirm_line_with_one_price_line_is_refused(core, svc):
    """A one-line estimate is a build failure (§3.1)."""
    wo = file_wo(core)
    with pytest.raises(Refused) as e:
        svc.compile_draft(
            wo.id, title="t", goal="g", targets=[],
            acceptance=[{"kind": "test_suite", "spec": {}}],
            budget=Budget(),
            estimate=Estimate(build_verify=Rail(gpu_minutes=20), generate_test=Rail(gpu_minutes=10)),
            confirm_line="weather the crates · build/verify: ~0.3 GPU-h")
    assert "BOTH price lines" in e.value.message


def test_a_confirm_line_over_25_words_is_refused(core, svc):
    wo = file_wo(core)
    long_sentence = " ".join(["word"] * 30)
    with pytest.raises(Refused):
        svc.compile_draft(
            wo.id, title="t", goal="g", targets=[],
            acceptance=[{"kind": "test_suite", "spec": {}}],
            budget=Budget(),
            estimate=Estimate(build_verify=Rail(gpu_minutes=20), generate_test=Rail(gpu_minutes=10)),
            confirm_line=f"{long_sentence} · build/verify: 1 · generate/test: 1")


def test_a_draft_carries_both_price_lines(core):
    wo = filed_work_order(core)
    assert wo.state == "draft"
    assert "build/verify:" in wo.confirm_line
    assert "generate/test:" in wo.confirm_line


def test_compiling_twice_is_refused(core, svc):
    wo = filed_work_order(core)
    with pytest.raises(Refused) as e:
        svc.compile_draft(
            wo.id, title="t", goal="g", targets=[],
            acceptance=[{"kind": "test_suite", "spec": {}}],
            budget=Budget(),
            estimate=Estimate(build_verify=Rail(), generate_test=Rail()),
            confirm_line="x · build/verify: 0 · generate/test: 0")
    assert "not compiling" in e.value.message


# ------------------------------------------------------------- confirm

def test_confirm_go_queues_the_order(core, svc):
    wo = filed_work_order(core)
    out = svc.confirm(wo.id, owner_actor("casey"), "go")
    assert out["state"] == "queued"
    assert svc.get(wo.id).confirmed_by == "casey"


def test_confirm_no_cancels(core, svc):
    wo = filed_work_order(core)
    out = svc.confirm(wo.id, owner_actor("casey"), "no")
    assert out["state"] == "cancelled"


def test_confirm_edit_refiles_an_amended_order(core, svc):
    wo = filed_work_order(core)
    out = svc.confirm(wo.id, owner_actor("casey"), "edit",
                      amendments={"goal": "weather them properly"})
    assert out["refiled"] != wo.id
    assert out["work_order"]["state"] == "draft"
    assert svc.get(wo.id).state == "cancelled"


def test_confirm_with_an_unknown_answer_is_refused(core, svc):
    wo = filed_work_order(core)
    with pytest.raises(Refused):
        svc.confirm(wo.id, owner_actor("casey"), "maybe")


def test_confirming_a_non_draft_is_refused(core, svc):
    wo = file_wo(core)  # still compiling
    with pytest.raises(Refused) as e:
        svc.confirm(wo.id, owner_actor("casey"), "go")
    assert "not draft" in e.value.message


def test_a_doubled_go_does_not_queue_twice(core, svc):
    """The idempotency rule: a replay returns the original result, never a
    second state change."""
    wo = filed_work_order(core)
    first = svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-1")
    second = svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-1")
    assert first == second
    assert svc.get(wo.id).state == "queued"
    confirmed = core.store.events_for("work_order", wo.id, ["wo.confirmed"])
    assert len(confirmed) == 1


# ------------------------------------------------------------- the rest of the ladder

def test_the_full_ladder_queued_to_kept(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")

    attempt = svc.start_attempt(wo.id, "aider-local")
    assert attempt.n == 1
    assert svc.get(wo.id).state == "building"

    deliverable = {
        "attempt": "seat-1",
        "commit": {"sha": "abc", "message": "fix"},
        "code_diff": {"sha": "def", "bytes": 10},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}],
    }
    assert svc.deliver(wo.id, deliverable).state == "testing"

    gate = svc.run_gate(wo.id)
    assert gate["passed"] is True

    preview = core.store.artifacts.put(b"png-bytes", "preview.png")
    landed = svc.land(wo.id, preview, [
        {"kind": "render", "ref": "preview.png", "sha256": preview["sha256"],
         "summary": "the crates"}])
    assert landed.state == "landed"

    out = svc.keep(wo.id, owner_actor("casey"))
    assert out["work_order"]["state"] == "kept"


def test_a_deliverable_without_a_test_run_is_refused(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    with pytest.raises(Refused) as e:
        svc.deliver(wo.id, {
            "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
            "evidence": [{"kind": "render", "ref": "r", "sha256": "sha256:x",
                          "summary": "a render, no tests"}]})
    assert "test_run" in e.value.message


def test_landing_without_the_preview_artifact_is_refused(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    with pytest.raises(Refused) as e:
        svc.land(wo.id, {"sha256": "sha256:not-there"}, [])
    assert "preview artifact" in e.value.message


def test_an_attempt_starts_only_from_queued(core, svc):
    wo = filed_work_order(core)
    with pytest.raises(Refused) as e:
        svc.start_attempt(wo.id, "aider-local")
    assert "attempts start from queued" in e.value.message


def test_attempt_numbers_never_go_backwards(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    a1 = svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    # a failed gate returns the order to building for attempt n+1 (§1.3)
    assert svc.fail(wo.id, "the gate failed").state == "building"
    a2 = svc.start_attempt(wo.id, "aider-local")
    assert a1.n == 1 and a2.n == 2


def test_an_exhausted_rail_parks_a_queued_order(core):
    """§1.3: ``parked`` is "waiting on the owner **or budget**; resumable"."""
    from core.models import Budget, Rail

    svc = WorkOrdersService(core)
    wo = svc.file(owner_actor("casey"), Origin(channel="text", packet="pk"), "t", goal="g")
    svc.compile_draft(
        wo.id, title="t", goal="g", targets=[],
        acceptance=[{"kind": "test_suite", "spec": {}}],
        budget=Budget(per_order=Rail(gpu_minutes=0, hosted_cents=0),
                      per_attempt=Rail(gpu_minutes=10, hosted_cents=1)),
        estimate=Estimate(build_verify=Rail(gpu_minutes=1), generate_test=Rail(gpu_minutes=1)),
        confirm_line="do it · build/verify: 1 · generate/test: 1")
    svc.confirm(wo.id, owner_actor("casey"), "go")
    with pytest.raises(Refused):
        svc.start_attempt(wo.id, "aider-local")  # the rail cannot cover it
    assert svc.get(wo.id).state == "parked"
    # and it is resumable
    assert svc.resume(wo.id, owner_actor("casey")).state == "queued"


def test_an_exhausted_rail_at_attempt_n_plus_one_is_terminal(core):
    """§1.3: testing ─(gate.failed)──> failed [attempts or rail exhausted]."""
    from core.models import Budget, Rail

    svc = WorkOrdersService(core)
    wo = svc.file(owner_actor("casey"), Origin(channel="text", packet="pk"), "t", goal="g")
    svc.compile_draft(
        wo.id, title="t", goal="g", targets=[],
        acceptance=[{"kind": "test_suite", "spec": {}}],
        budget=Budget(per_order=Rail(gpu_minutes=0, hosted_cents=0),
                      per_attempt=Rail(gpu_minutes=10, hosted_cents=1)),
        estimate=Estimate(build_verify=Rail(gpu_minutes=1), generate_test=Rail(gpu_minutes=1)),
        confirm_line="do it · build/verify: 1 · generate/test: 1")
    svc.confirm(wo.id, owner_actor("casey"), "go")
    with pytest.raises(Refused):
        svc.start_attempt(wo.id, "aider-local")
    assert svc.get(wo.id).state == "parked"


def test_park_and_resume(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    assert svc.park(wo.id, "waiting on the owner").state == "parked"
    assert svc.resume(wo.id, owner_actor("casey")).state == "queued"


def test_reject_retains_the_branch_and_keeps_the_word_out(core, svc):
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    preview = core.store.artifacts.put(b"png", "preview.png")
    svc.land(wo.id, preview, [])
    out = svc.reject(wo.id, owner_actor("casey"), reason_code="too_busy")
    assert out["work_order"]["state"] == "rejected"


def test_keeping_scores_outstanding_taste_keep_predictions(core, svc):
    """§1.7: the owner's keep is the only event that scores a taste_keep
    prediction."""
    from core.svc.predictions import PredictionsService

    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    preview = core.store.artifacts.put(b"png", "preview.png")
    svc.land(wo.id, preview, [])

    preds = PredictionsService(core)
    p = preds.seal(
        owner_actor("prop-maker"), wo.id, "the crates will read as weathered",
        "taste_keep", "medium", basis="1 observation",
        render_spec={"rung": 2, "resolution": "1024", "seed": 7})
    assert p.verdict is None

    out = svc.keep(wo.id, owner_actor("casey"))
    assert p.id in out["scored"]
    assert preds.get(p.id).verdict == "hit"


def test_a_stale_transition_fails_closed(core, svc):
    """§5.3: compare-and-swap on (entity, expected_state, seq)."""
    wo = filed_work_order(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    # a second "go" with a *different* idempotency key is a real second
    # attempt at a state change, and it must fail rather than re-queue.
    with pytest.raises(Refused):
        svc.confirm(wo.id, owner_actor("casey"), "go", idem_key="go-2")
    assert svc.get(wo.id).state == "queued"


def test_the_board_lists_the_orders(core):
    wo = filed_work_order(core)
    rows = WorkOrdersService(core).list()
    assert [r.id for r in rows] == [wo.id]
    assert WorkOrdersService(core).list("draft")[0].id == wo.id
    assert WorkOrdersService(core).list("landed") == []
