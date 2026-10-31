"""The audit ledger (§1.8, §5.1, §5.2).

The ledger is the source of truth. These tests hold the properties the rest
of the spec leans on: the log is append-only and gapless, the projections
are *rebuildable* from the log alone (not assumed), a refused call commits
without changing a projection, an oversized payload spills to an artifact
instead of bloating the row, and an idempotency key never produces a second
state change.
"""
from __future__ import annotations

import pytest

from core.errors import Refused, StaleTransition, ValidationError
from core.events import MAX_PAYLOAD_BYTES, core_actor, owner_actor
from core.fold import fold_all, stores_equal


def test_seq_is_gapless_and_monotonic(core):
    for i in range(5):
        core.store.append(core.store.new_event(
            "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"},
            {"at": f"2026-10-31T00:0{i}:00Z"}))
    seqs = [e.seq for e in core.store.events_since(0)]
    assert seqs == list(range(1, len(seqs) + 1))
    assert seqs == sorted(seqs)


def test_the_log_is_append_only(core):
    """There is no update path: the only writes are appends."""
    before = core.store.max_seq()
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {}))
    assert core.store.max_seq() == before + 1
    # the row store has no mutating verb beyond the fold's own writes
    assert not hasattr(core.store, "update_event")
    assert not hasattr(core.store, "delete_event")


def test_projections_are_rebuildable_from_the_log_alone(core):
    """The property §5.2 step 1 checks at boot: fold the log into a shadow
    and compare with the live projections."""
    from core.models import Origin
    from core.svc.work_orders import WorkOrdersService

    svc = WorkOrdersService(core)
    svc.file(owner_actor("casey"), Origin(channel="text", packet="pk"), "a thing", goal="do it")

    shadow = fold_all(core.store.events_since(0), core.store.ctx)
    assert stores_equal(shadow, core.store.rows) == []


def test_a_wipe_is_repaired_by_a_rebuild(core):
    """If the projections are lost, folding the log brings them back."""
    from core.models import Origin
    from core.svc.work_orders import WorkOrdersService

    svc = WorkOrdersService(core)
    svc.file(owner_actor("casey"), Origin(channel="text", packet="pk"), "a thing")
    assert core.store.scan("work_orders")

    core.store.rows.wipe()
    assert core.store.scan("work_orders") == []

    report = core.store.boot()
    assert report["rebuilt"] is True
    assert len(core.store.scan("work_orders")) == 1


def test_a_refused_event_commits_but_changes_no_projection(core):
    ev = core.store.new_event(
        "vocab.call", core_actor(), {"entity_kind": "vocab_word", "entity_id": "w"},
        {"word": "w", "refusal_reason": "unknown word"})
    core.store.append_refused(ev)
    assert ev.refused is True
    assert core.store.max_seq() == 1
    assert core.store.scan("vocab_words") == []
    # ...and the refusal is in the log, because the edges are the story
    stored = core.store.events_since(0, types=["vocab.call"])
    assert len(stored) == 1 and stored[0].refused is True


def test_an_oversized_payload_spills_to_an_artifact(core):
    big = {"blob": "x" * (MAX_PAYLOAD_BYTES + 100)}
    ev = core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, big)
    core.store.append(ev)
    assert ev.payload_bytes() <= MAX_PAYLOAD_BYTES
    assert ev.artifact is not None
    assert core.store.artifacts.has(ev.artifact["sha256"])
    # the row itself stays small
    row = core.store.conn.execute("SELECT length(payload) AS n FROM audit").fetchone()
    assert row["n"] < MAX_PAYLOAD_BYTES


def test_an_unknown_event_type_is_refused(core):
    ev = core.store.new_event("not.a.real.type", core_actor(),
                              {"entity_kind": "x", "entity_id": "y"}, {})
    with pytest.raises(ValueError):
        ev.validate_type()


def test_an_idempotency_key_never_makes_a_second_state_change(core):
    key = "confirm:wo-1"
    calls = []

    def build(e):
        calls.append(e.seq)
        return {"ok": True, "seq": e.seq}

    for _ in range(3):
        core.store.append(core.store.new_event(
            "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"}, {}),
            idem_key=key, response_builder=build)
    assert len(calls) == 1
    assert core.store.max_seq() == 1
    cached = core.store.idem_get(key)
    assert cached is not None and cached["body"]["ok"] is True


def test_the_ledger_survives_a_reopen(core, settings):
    """The durability claim: the DB is the record, not the process."""
    core.store.append(core.store.new_event(
        "night.tick", core_actor(), {"entity_kind": "night", "entity_id": "n1"},
        {"at": "2026-10-31T00:00:00Z"}))
    seq = core.store.max_seq()
    core.store.close()

    from core.svc import Core

    again = Core.open(settings)
    try:
        assert again.store.max_seq() == seq
        assert len(again.store.events_since(0)) == seq
    finally:
        again.store.close()
