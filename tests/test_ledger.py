"""The ledger seam: the append-only log the night runner writes into.

The API half (core-api seat) owns the real ledger — SQLite in WAL mode with
``synchronous=FULL``, written by a single writer, with a gapless ``seq`` that
is the resume cursor (core-spec v2 §1.0, §5.1). This seat codes against the
small protocol and ships conforming stubs, so the night runner can be built
and measured before the real ledger lands.
"""

from __future__ import annotations

import pytest

from core.night.events import EVENT_TYPES, NIGHT_RUNNER_EVENT_TYPES
from core.night.ledger import (
    MAX_PAYLOAD_BYTES,
    InMemoryLedger,
    Ledger,
    SQLiteLedger,
)
from core.night.models import Actor

CORE = Actor(kind="core", id="night-runner")


def append(ledger, type="night.started", payload=None, **kwargs):
    return ledger.append(
        type=type,
        actor=CORE,
        subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
        payload=payload if payload is not None else {},
        **kwargs,
    )


def test_the_ledger_is_append_only_and_numbers_gaplessly():
    ledger = InMemoryLedger()
    first = append(ledger)
    second = append(ledger)
    assert (first.seq, second.seq) == (1, 2)
    assert (first.id, second.id) == ("aud_0001", "aud_0002")
    assert ledger.last_seq() == 2


def test_events_are_returned_oldest_first_and_can_be_filtered():
    ledger = InMemoryLedger()
    append(ledger, type="night.started")
    append(ledger, type="night.tick", payload={"at": "2026-10-30T21:20:00Z"})
    append(ledger, type="night.stopped")

    assert [event.type for event in ledger.events()] == [
        "night.started",
        "night.tick",
        "night.stopped",
    ]
    assert [event.type for event in ledger.events(types=["night.tick"])] == ["night.tick"]
    assert [event.seq for event in ledger.events(since_seq=1)] == [2, 3]


def test_an_unknown_event_type_is_refused():
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        append(ledger, type="night.exploded")


def test_a_payload_over_four_kib_is_refused():
    ledger = InMemoryLedger()
    with pytest.raises(ValueError):
        append(ledger, payload={"blob": "x" * (MAX_PAYLOAD_BYTES + 1)})


def test_the_night_runner_only_emits_event_types_the_spec_allows():
    assert NIGHT_RUNNER_EVENT_TYPES <= EVENT_TYPES


def test_the_sqlite_stub_is_a_conforming_ledger():
    ledger = SQLiteLedger(":memory:")
    assert isinstance(ledger, Ledger)
    append(ledger)
    assert ledger.last_seq() == 1


def test_the_sqlite_stub_is_durable_wal_and_full_sync(tmp_path):
    """§5.1 — the change is fsynced before the append returns."""
    ledger = SQLiteLedger(tmp_path / "core.db")
    assert ledger.journal_mode() == "wal"
    assert ledger.synchronous() == 2  # FULL (SQLite: 0=OFF 1=NORMAL 2=FULL 3=EXTRA)
    append(ledger, payload={"n": 1})
    ledger.close()

    reopened = SQLiteLedger(tmp_path / "core.db")
    events = reopened.events()
    assert [event.payload for event in events] == [{"n": 1}]
    assert reopened.last_seq() == 1


def test_the_sqlite_stub_survives_a_reopen_with_a_gapless_sequence(tmp_path):
    path = tmp_path / "core.db"
    first = SQLiteLedger(path)
    append(first)
    append(first)
    first.close()

    second = SQLiteLedger(path)
    append(second)
    assert [event.seq for event in second.events()] == [1, 2, 3]
    second.close()
