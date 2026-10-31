"""The sibling seats' pieces this seat built against — now the real ones.

Every stand-in below had a real owner named in the README's stub table; the
seats have merged, so the bodies are gone and the names resolve to the real
implementations. What remains a stand-in is the in-memory ledger: the spine's
SQLite store (``core.store``) stays the log of record, and this seat's unit
tests run on a conforming in-process ledger that keeps the one invariant
beyond bookkeeping — §5.1's sealed-before-render ordering.

| name | now |
|---|---|
| ``canonical_json`` / ``canonical_bytes`` / ``content_hash`` / ``short_hash`` | :mod:`core.vocab.hashing` (itself :mod:`core.canon`) |
| ``SystemClock`` / ``SteppingClock`` / ``FixedClock`` / ``format_rfc3339`` | :mod:`core.vocab.clock` |
| ``taste_rows_from_events`` | :mod:`core.vocab.taste` — the read side of ``taste.note.appended`` |
| ``PredictionSealer`` / ``SealRefusal`` | :mod:`core.vocab.predictions` — ``PredictionService`` / ``PredictionRefusal`` |
| ``Rail`` | :mod:`core.records` — the one three-axis rail |
| ``InMemoryLedger`` / ``LedgerError`` | still here (see above) |
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.records import Rail
from core.vocab.clock import FixedClock, SteppingClock, SystemClock, format_rfc3339
from core.vocab.hashing import canonical_bytes, canonical_json, content_hash, short_hash
from core.vocab.predictions import (
    SEALED_FIELDS,
    PredictionRefusal,
    PredictionService,
    seal_hash_for,
)
from core.vocab.taste import taste_rows_from_events

from .models import Actor, AuditEvent, Prediction

__all__ = [
    "canonical_json",
    "canonical_bytes",
    "content_hash",
    "short_hash",
    "SystemClock",
    "SteppingClock",
    "FixedClock",
    "format_rfc3339",
    "LedgerError",
    "InMemoryLedger",
    "taste_rows_from_events",
    "SealRefusal",
    "PredictionSealer",
    "Rail",
    "SEALED_FIELDS",
    "seal_hash_for",
]

#: The vocabulary seat's sealer, under this seat's historical name.
PredictionSealer = PredictionService
SealRefusal = PredictionRefusal

# -- the ledger — core-api's (branch `core-api`) ----------------------------


class LedgerError(Exception):
    """The ledger refused an append. Carries a closed reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class InMemoryLedger:
    """A single-writer, append-only audit log with a gapless `seq`.

    Implements `ports.LedgerPort`. The one invariant it enforces beyond
    bookkeeping is §5.1's ordering: a `job.enqueued` that references a
    prediction with no committed `prediction.sealed` is refused — a render
    may not exist before the bet it is meant to test.
    """

    def __init__(self, *, events: Sequence[AuditEvent] = ()) -> None:
        self._events: list[AuditEvent] = []
        self._by_id: dict[str, AuditEvent] = {}
        for event in events:
            self.append(event)

    def append(self, event: AuditEvent) -> AuditEvent:
        existing = self._by_id.get(event.id)
        if existing is not None:
            # Idempotency (§5.3): the same event twice is one event.
            if existing.payload == event.payload and existing.type == event.type:
                return existing
            raise LedgerError("duplicate_event_id", f"{event.id} already exists")

        if event.type == "job.enqueued":
            self._require_sealed_before_render(event)

        committed = event.model_copy(update={"seq": self.head_seq() + 1})
        self._events.append(committed)
        self._by_id[committed.id] = committed
        return committed

    def head_seq(self) -> int:
        return self._events[-1].seq if self._events else 0

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        wanted = set(types) if types is not None else None
        return [
            event
            for event in self._events
            if (since_seq is None or event.seq > since_seq)
            and (wanted is None or event.type in wanted)
        ]

    def find(self, event_type: str, **match: Any) -> AuditEvent | None:
        for event in reversed(self._events):
            if event.type != event_type:
                continue
            if all(event.payload.get(key) == value for key, value in match.items()):
                return event
        return None

    def _require_sealed_before_render(self, event: AuditEvent) -> None:
        """§5.1 — a render job may not reference an unsealed prediction."""
        prediction_id = event.payload.get("prediction_id")
        if prediction_id is None:
            return
        sealed = self.find("prediction.sealed", prediction_id=prediction_id)
        if sealed is None:
            raise LedgerError(
                "prediction_not_sealed",
                f"{prediction_id} has no committed prediction.sealed event",
            )
