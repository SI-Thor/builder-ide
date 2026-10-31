"""The cold-start seat (`core.coldstart`): the opener and ask-mode.

Two pieces of the evening, both the seat's own code — and, since the seats
merged, both over **the spine's one ledger**:

* **The cold open** (`openline.py`, §3.5 / G §7 test 1) — the Companion's
  first line is computed from *counts* the adapter reads out of the spine's
  ledger. There is no parameter through which an adjective about the owner
  could enter the line; the test asserts the three rules (zero denominator,
  nothing about the owner, exactly one offer of four seeds).
* **Ask-mode** (`askmode.py`, §3.5 / G §7 tests 2–3) — the ≤ 6 two-chip
  questions, strictly one at a time, a skip writes nothing, every answer an
  owner-written taste row. The policy runs on the seat's code over the
  core's `SpineLedgerPort` (`core.ports`): `line.spoken` and
  `taste.note.appended` are in the spine's closed set (§1.8), the row rides
  `payload["row"]` (the one spelling, INTEGRATION.md §4), and the spine's
  own fold projects the rows the panels read — **the mirror bridge is gone;
  there is one ledger**.
"""

from __future__ import annotations

from typing import Any

from spec_client import CoreDoor


def spine_ledger(door: CoreDoor):
    """cold-start's `LedgerPort` over the spine's one store — the core's own
    adapter (`core.ports.SpineLedgerPort`), reached through the door so a
    reopen re-roots it."""
    from core.ports import SpineLedgerPort

    return _DoorLedger(door, SpineLedgerPort)


class _DoorLedger:
    """Route the core's adapter through the door, so the kill-9 reopen
    re-roots it onto the reopened store without the holder knowing."""

    def __init__(self, door: CoreDoor, adapter) -> None:
        self._door = door
        self._adapter = adapter

    def _rebind(self):
        from core.ports import SpineLedgerPort

        store = self._door.core.store
        if getattr(self._adapter, "_store", None) is not store:
            self._adapter = SpineLedgerPort(store)
        return self._adapter

    def append(self, event) -> Any:
        return self._rebind().append(event)

    def head_seq(self) -> int:
        return self._rebind().head_seq()

    def events(self, *, since_seq: int | None = None, types=None) -> list[Any]:
        return self._rebind().events(since_seq=since_seq, types=types)

    def find(self, event_type: str, **match: Any):
        return self._rebind().find(event_type, **match)


class ColdOpenView:
    """The first screen, over the spine's taste events (§3.5)."""

    def __init__(self, seat: "ColdStartSeat", door: CoreDoor) -> None:
        self._seat = seat
        self._door = door

    def line_and_starters(self) -> dict:
        """The opener, recomputed from whatever the spine ledger holds now."""
        events = self._spine_events_as_coldstart()
        cold = self._seat.companion_opening(events, author="casey")
        return {
            "line": cold.line,
            "starters": [
                {"name": s.name, "seed": s.seed} for s in cold.starters
            ],
            "taste_rows": cold.taste_rows,
            "kept": cold.kept,
        }

    def _spine_events_as_coldstart(self) -> list[Any]:
        models = self._seat.models
        out = []
        for ev in self._door.raw_events(0, ["taste.note.appended"]):
            payload = dict(ev.payload)
            row = dict(payload.get("row") or {})
            # the spine's own writer (TasteService) leaves at/status to the
            # defaults; the fold fills them from the event — same defaults
            row.setdefault("status", "active")
            row.setdefault("at", ev.at)
            out.append(
                models.AuditEvent(
                    seq=ev.seq, id=ev.id, at=ev.at,
                    actor=models.Actor(kind="owner", id=row.get("author", "casey")),
                    type="taste.note.appended",
                    subject={"entity_kind": "taste_note", "entity_id": row.get("id", ev.id)},
                    payload={"row": row},
                )
            )
        return out


class AskModeRunner:
    """One ask-mode sitting: the seat's policy, the spine's one ledger."""

    def __init__(self, seat: "ColdStartSeat", door: CoreDoor) -> None:
        self._seat = seat
        self._door = door
        self.ledger = spine_ledger(door)
        self.clock = seat.stubs.SteppingClock("2026-10-30T20:12:00Z")
        self.mode = seat.AskMode(ledger=self.ledger, clock=self.clock, author="casey")
        self.session = self.mode.begin_session()
        self.spine_rows: list[dict] = []
        self.skipped: list[str] = []
        self.collapsed: list[dict] = []

    def ask_next(self, bank):
        return self.mode.ask_next(self.session, bank)

    def answer(self, question, chip_id: str) -> dict:
        """One tap (≤ 1.5 s): the owner's row, written straight into the
        one ledger — the spine's fold projects it for every reader."""
        from dataclasses import asdict

        actor = self._seat.models.Actor(kind="owner", id="casey")
        row = self.mode.answer(self.session, question.id, chip_id, actor=actor)
        committed = self.ledger.events(types=["taste.note.appended"])[-1]
        spine_row = committed.payload["row"]
        self.spine_rows.append(spine_row)
        return {"row": asdict(row), "spine": spine_row}

    def skip(self, question_id: str) -> None:
        self.mode.skip(self.session, question_id)
        self.skipped.append(question_id)


class ColdStartSeat:
    """Handles onto `core.coldstart`'s own modules."""

    def __init__(self, seats) -> None:
        cs = seats.coldstart
        self.companion_opening = cs.companion_opening
        self.AskMode = cs.AskMode
        self.models = cs.models
        self.stubs = cs.stubs
        self.bank = cs.night_one_bank()
