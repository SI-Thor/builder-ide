"""The seam: what was stubbed, and what the stubs guarantee.

Two other seats are building the core in parallel — `core-api` (the ledger,
the API, the events) and `core-recipe` (the recipe store, typed edits, the
recipe hash). This file pins the behaviour of the in-memory stubs that stand
in for them, so that when the real implementations land, the tests keep their
meaning and the swap is a one-line change.

The stubbed invariants are the ones the vocabulary seat's guarantees rest on:
a gapless sequence, an append-only log, the **sealed-before-render ordering**,
a canonical recipe hash, and a head that only moves forward.
"""

from __future__ import annotations

import pytest

from core.vocab import (
    InMemoryLedger,
    InMemoryRecipeStore,
    InMemoryScheduler,
    LedgerPort,
    RecipeStorePort,
    SchedulerPort,
    SteppingClock,
    VocabularyRegistry,
    default_entries,
)
from core.vocab.hashing import content_hash
from core.vocab.models import Actor, AuditEvent, Branch, RecipeEdit, Op
from core.vocab.seed import RECIPE_DOCUMENT
from core.vocab.stubs import LedgerError


def _event(event_id: str, event_type: str = "core.boot", **payload):
    return AuditEvent(
        seq=0,
        id=event_id,
        at="2026-10-30T21:00:00Z",
        actor=Actor(kind="core", id="core"),
        type=event_type,
        subject={"entity_kind": "core", "entity_id": "core"},
        payload=payload,
    )


# --- the protocols ---------------------------------------------------------------


def test_the_stubs_satisfy_the_protocols():
    ledger = InMemoryLedger()
    assert isinstance(ledger, LedgerPort)

    store = InMemoryRecipeStore(document=RECIPE_DOCUMENT, branches=[])
    assert isinstance(store, RecipeStorePort)

    scheduler = InMemoryScheduler(ledger=ledger, clock=SteppingClock())
    assert isinstance(scheduler, SchedulerPort)


# --- the ledger (core-api's seam) ------------------------------------------------


def test_the_sequence_is_monotone_and_gapless():
    ledger = InMemoryLedger()
    for index in range(5):
        ledger.append(_event(f"aud_{index}"))
    assert [event.seq for event in ledger.events()] == [1, 2, 3, 4, 5]
    assert ledger.head_seq() == 5


def test_the_log_is_append_only_and_readable_from_a_cursor():
    ledger = InMemoryLedger()
    ledger.append(_event("aud_1"))
    ledger.append(_event("aud_2"))
    assert [event.id for event in ledger.events(since_seq=1)] == ["aud_2"]
    assert ledger.find("core.boot") is not None


def test_replaying_an_event_is_idempotent():
    ledger = InMemoryLedger()
    ledger.append(_event("aud_1", "vocab.call", word="props.harbor.crates"))
    ledger.append(_event("aud_1", "vocab.call", word="props.harbor.crates"))
    assert len(ledger.events()) == 1


def test_the_same_id_with_a_different_payload_is_refused():
    ledger = InMemoryLedger()
    ledger.append(_event("aud_1", "vocab.call", word="props.harbor.crates"))
    with pytest.raises(LedgerError) as error:
        ledger.append(_event("aud_1", "vocab.call", word="props.harbor.racks"))
    assert error.value.reason == "duplicate_event_id"


def test_a_render_without_a_seal_is_refused():
    ledger = InMemoryLedger()
    with pytest.raises(LedgerError) as error:
        ledger.append(_event("aud_job", "job.enqueued", prediction_id="pr_nope"))
    assert error.value.reason == "prediction_not_sealed"


def test_a_render_after_a_seal_is_accepted():
    ledger = InMemoryLedger()
    ledger.append(_event("aud_seal", "prediction.sealed", prediction_id="pr_x"))
    ledger.append(_event("aud_job", "job.enqueued", prediction_id="pr_x"))
    assert ledger.find("job.enqueued") is not None


# --- the recipe store (core-recipe's seam) ---------------------------------------


def _store(**kwargs):
    registry = VocabularyRegistry(default_entries())
    return InMemoryRecipeStore(
        document=RECIPE_DOCUMENT,
        branches=[
            Branch(
                id="br_main",
                name="main",
                recipe="rcp_fjellvik",
                head="ver_root",
                purpose="main",
                created_by=Actor(kind="owner", id="casey"),
            )
        ],
        validator=registry.validate_document,
        **kwargs,
    )


def test_a_version_hashes_its_canonical_document():
    store = _store()
    root = store.root_version
    assert store.version(root).root_hash == content_hash(RECIPE_DOCUMENT)
    assert store.version(root).parent is None
    assert store.version(root).edit is None


def test_an_edit_is_committed_as_a_new_version_with_a_new_hash():
    store = _store()
    base = store.head("br_main")
    edit = RecipeEdit(
        id="ed_1",
        base=base,
        ops=[Op(op="set", path="harbor.crates.params.count", value=12)],
        author=Actor(kind="character", id="prop-maker", via="word"),
        message="12 crates",
    )
    version = store.apply_edit(edit)
    assert version.parent == base
    assert version.root_hash == content_hash(store.document(version.id))
    assert version.root_hash != store.version(base).root_hash


def test_the_store_refuses_an_edit_that_leaves_the_schema():
    store = _store()
    base = store.head("br_main")
    edit = RecipeEdit(
        id="ed_bad",
        base=base,
        ops=[Op(op="set", path="harbor.crates.params.count", value=999)],
        author=Actor(kind="character", id="prop-maker", via="word"),
        message="999 crates",
    )
    with pytest.raises(Exception) as error:
        store.apply_edit(edit)
    assert "out_of_range" in str(error.value)


def test_a_head_only_moves_forward():
    store = _store()
    base = store.head("br_main")
    first = store.apply_edit(
        RecipeEdit(
            id="ed_1",
            base=base,
            ops=[Op(op="set", path="harbor.crates.params.count", value=12)],
            author=Actor(kind="character", id="prop-maker", via="word"),
            message="12 crates",
        )
    )
    second = store.apply_edit(
        RecipeEdit(
            id="ed_2",
            base=first.id,
            ops=[Op(op="set", path="harbor.crates.params.style", value="stained")],
            author=Actor(kind="character", id="prop-maker", via="word"),
            message="stained",
        )
    )
    store.move_head("br_main", first.id)
    assert store.head("br_main") == first.id
    with pytest.raises(ValueError):
        store.move_head("br_main", base)  # backwards is refused
    store.move_head("br_main", second.id)
    assert store.head("br_main") == second.id
