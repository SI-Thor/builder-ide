"""The cold-start seat (branch `cold-start`): the opener and ask-mode.

Two pieces of the evening, both the sibling's own code:

* **The cold open** (`openline.py`, §3.5 / G §7 test 1) — the Companion's
  first line is computed from *counts* the adapter reads out of the spine's
  ledger. There is no parameter through which an adjective about the owner
  could enter the line; the test asserts the three rules (zero denominator,
  nothing about the owner, exactly one offer of four seeds).
* **Ask-mode** (`askmode.py`, §3.5 / G §7 tests 2–3) — the ≤ 6 two-chip
  questions, strictly one at a time, a skip writes nothing, every answer an
  owner-written taste row. The policy runs on the sibling's code; each
  answered row is mirrored into the spine through the spine's own taste
  write path (`TasteService.append_note` — owner-only, single writer), so
  the spine's `/v1/ledger/taste` and the evening's ledger agree row for
  row. That mirror is the thin bridge; when the seats merge it disappears
  because there is only one ledger.
"""

from __future__ import annotations

from typing import Any

from spec_client import CoreDoor


class ColdOpenView:
    """The first screen, over the spine's taste events (§3.5)."""

    def __init__(self, seat: "ColdStartSeat", door: CoreDoor) -> None:
        self._seat = seat
        self._door = door

    def line_and_starters(self) -> dict:
        """The opener, recomputed from whatever the spine ledger holds now.

        The translation spine-event → coldstart-event is the adapter's whole
        job here: the seats' payload spellings differ (`note` vs `row`), and
        this is exactly the kind of drift the acceptance run exists to name.
        """
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
            note = payload.get("note") or payload.get("row") or {}
            # cold-start's fold reads payload["row"]; give it the row shape
            row = dict(note)
            row.setdefault("status", "active")
            row.setdefault("at", ev.at)
            out.append(
                models.AuditEvent(
                    seq=ev.seq, id=ev.id, at=ev.at,
                    actor=models.Actor(kind="owner", id=payload.get("author", "casey")),
                    type="taste.note.appended",
                    subject={"entity_kind": "taste_note", "entity_id": note.get("id", ev.id)},
                    payload={"row": row},
                )
            )
        return out


class AskModeRunner:
    """One ask-mode sitting: the sibling's policy, the spine's ledger."""

    def __init__(self, seat: "ColdStartSeat", door: CoreDoor) -> None:
        self._seat = seat
        self._door = door
        self.ledger = seat.stubs.InMemoryLedger()
        self.clock = seat.stubs.SteppingClock("2026-10-30T20:12:00Z")
        self.mode = seat.AskMode(ledger=self.ledger, clock=self.clock, author="casey")
        self.session = self.mode.begin_session()
        self.spine_rows: list[dict] = []
        self.skipped: list[str] = []
        self.collapsed: list[dict] = []

    def ask_next(self, bank):
        return self.mode.ask_next(self.session, bank)

    def answer(self, question, chip_id: str) -> dict:
        """One tap (≤ 1.5 s): the owner's row, mirrored into the spine."""
        from dataclasses import asdict

        actor = self._seat.models.Actor(kind="owner", id="casey")
        row = self.mode.answer(self.session, question.id, chip_id, actor=actor)
        mirrored = self._door.append_taste_note(
            subject=dict(row.subject),
            artifact_ref=row.artifact_ref,
            verdict=row.verdict,
            reason_code=row.reason_code,
            words=row.words,
            tags=list(row.tags),
        )
        spine_row = mirrored.model_dump(mode="json")
        self.spine_rows.append(spine_row)
        return {"row": asdict(row), "spine": spine_row}

    def skip(self, question_id: str) -> None:
        self.mode.skip(self.session, question_id)
        self.skipped.append(question_id)


class ColdStartSeat:
    """Handles onto branch `cold-start`'s own modules."""

    def __init__(self, seats) -> None:
        cs = seats.coldstart
        self.companion_opening = cs.companion_opening
        self.AskMode = cs.AskMode
        self.models = cs.models
        self.stubs = cs.stubs
        self.bank = cs.night_one_bank()
