"""The ledger seam: append-only events, the closed type set, durability.

The API half owns the real ledger (SQLite, WAL, ``synchronous=FULL``, one
writer). This file pins the *interface* the recipe store codes against, and
the reference stub that implements it here so the durability and the timing
can be measured on this box.
"""

from __future__ import annotations

import pytest

from core.recipe.events import EVENT_TYPES, RECIPE_EVENT_TYPES
from core.recipe.ledger import InMemoryLedger, SQLiteLedger
from core.recipe.models import Actor, Op, Recipe
from core.recipe.store import RecipeStore


def _actor() -> Actor:
    return Actor(kind="owner", id="casey")


def test_appending_assigns_a_monotone_gapless_sequence():
    ledger = InMemoryLedger()
    first = ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    second = ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    assert (first.seq, second.seq) == (1, 2)


def test_events_can_be_filtered_by_type():
    ledger = InMemoryLedger()
    ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    ledger.append(type="version.committed", actor=_actor(), subject={}, payload={})
    assert [e.type for e in ledger.events(types=["version.committed"])] == [
        "version.committed"
    ]


def test_events_can_be_read_from_a_cursor():
    ledger = InMemoryLedger()
    ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    assert [e.seq for e in ledger.events(since_seq=1)] == [2]


def test_a_payload_over_four_kib_is_refused():
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        ledger.append(
            type="core.boot", actor=_actor(), subject={}, payload={"blob": "x" * 5000}
        )


def test_an_event_type_outside_the_closed_set_is_refused():
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        ledger.append(type="recipe.cooked", actor=_actor(), subject={}, payload={})


def test_the_sqlite_ledger_survives_a_reopen(tmp_path):
    ledger = SQLiteLedger(tmp_path / "core.db")
    ledger.append(type="core.boot", actor=_actor(), subject={}, payload={"i": 1})
    reopened = SQLiteLedger(tmp_path / "core.db")
    events = reopened.events()
    assert len(events) == 1
    assert events[0].payload == {"i": 1}


def test_the_sqlite_ledger_runs_in_wal_with_full_synchronisation(tmp_path):
    path = tmp_path / "core.db"
    ledger = SQLiteLedger(path)
    ledger.append(type="core.boot", actor=_actor(), subject={}, payload={})
    journal = ledger.journal_mode()
    synchronous = ledger.synchronous()
    assert journal.lower() == "wal"
    assert synchronous == 2  # FULL


def test_the_store_only_emits_event_types_from_the_closed_set(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    emitted = {event.type for event in store.ledger.events()}
    assert emitted <= EVENT_TYPES
    assert emitted & RECIPE_EVENT_TYPES == emitted - {"core.boot"}


def test_the_recipe_events_the_spec_names_are_all_in_the_closed_set():
    for event_type in (
        "edit.proposed",
        "edit.validated",
        "version.committed",
        "branch.created",
        "branch.head.moved",
        "branch.rejected",
        "branch.proposed",
        "constraint.failed",
    ):
        assert event_type in EVENT_TYPES
