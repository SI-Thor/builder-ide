"""In-memory stand-ins for the sibling seats' work.

Each class below is headed by the branch that owns the real implementation.
None of them are toys: they keep the rules cold start leans on — a gapless,
append-only sequence; sealed-before-render ordering; the three-writer rule on
taste rows — so the tests here keep their meaning when the real seats land
and the stubs are deleted (the merge procedure is in the README's stub table).

| stub | real owner | notes |
|---|---|---|
| `canonical_json` / `content_hash` / `short_hash` | `vocab` (`core/vocab/hashing.py`) | the canonical form must stay byte-identical — every seal hash depends on it |
| `SystemClock` / `SteppingClock` / `FixedClock` | `vocab` (`core/vocab/clock.py`) | RFC 3339 UTC, injectable |
| `InMemoryLedger` | `core-api` (branch `core-api`) | gapless `seq`, append-only, §5.1 ordering |
| `taste_rows_from_events` | `vocab` (`core/vocab/taste.py`) | the read side of `taste.note.appended` |
| `PredictionSealer` | `vocab` (`core/vocab/predictions.py`) | sealing + the three-writer rule; same refusal codes |
| `Rail` | `night-runner` (`core/night/models.py`) | the night's three spend axes |
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

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
]


# -- hashing — vocab's `core/vocab/hashing.py` ------------------------------


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 (spec §1.0)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """The UTF-8 bytes of `canonical_json` — what a hash is taken over."""
    return canonical_json(value).encode("utf-8")


def content_hash(value: Any) -> str:
    """`sha256:<hex>` over the canonical JSON of `value` (spec §1.0)."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def short_hash(value: Any, length: int = 12) -> str:
    """A short, deterministic id fragment: ids are content-derived wherever the
    record is immutable, so a rebuild of the same night produces the same ids."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()[:length]


# -- clocks — vocab's `core/vocab/clock.py` ---------------------------------


def format_rfc3339(moment: datetime) -> str:
    """RFC 3339 UTC, second precision: `2026-10-30T21:08:39Z`."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class SystemClock:
    """The wall clock."""

    def now(self) -> str:
        return format_rfc3339(datetime.now(timezone.utc))


class SteppingClock:
    """A clock that advances by a fixed step on every reading.

    Two events never share a timestamp, so "sealed before the render" is a
    strict inequality and not an accident of the wall clock.
    """

    def __init__(self, start: str = "2026-10-24T19:58:00Z", step_seconds: int = 1) -> None:
        self._now = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> str:
        value = format_rfc3339(self._now)
        self._now += self._step
        return value


class FixedClock:
    """A clock that always says the same thing."""

    def __init__(self, moment: str = "2026-10-24T19:58:00Z") -> None:
        self._moment = moment

    def now(self) -> str:
        return self._moment


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


# -- the taste ledger's read side — vocab's `core/vocab/taste.py` -----------


def taste_rows_from_events(events: Sequence[Any]) -> list[Any]:
    """Read taste rows out of `taste.note.appended` audit events.

    Kept field-for-field identical to the `vocab` seat's fold: the row lives
    in `payload["row"]` and every projection on either side of the merge must
    keep reading that shape.
    """
    from .models import TasteRow  # local import: models is stable, avoids a cycle at import time

    rows = []
    for event in events:
        if getattr(event, "type", None) != "taste.note.appended":
            continue
        payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
        row = payload.get("row")
        if not isinstance(row, Mapping):
            continue
        rows.append(TasteRow(
                id=str(row.get("id", event.id)),
                at=str(row.get("at", event.at)),
                author=str(row.get("author", "")),
                status=row.get("status", "active"),
                subject=dict(row.get("subject", {})),
                artifact_ref=str(row.get("artifact_ref", "")),
                verdict=row.get("verdict", "keep"),
                reason_code=str(row.get("reason_code", "")),
                words=row.get("words"),
                tags=tuple(row.get("tags", ()) or ()),
            )
        )
    return rows


# -- sealed predictions — vocab's `core/vocab/predictions.py` ---------------


#: §1.7 — the fields the seal hash covers, including `render_spec` (RV patch 16).
SEALED_FIELDS: tuple[str, ...] = (
    "builder",
    "at",
    "branch_ref",
    "claim",
    "claim_type",
    "confidence",
    "basis",
    "render_spec",
)

_CLAIM_TYPES = (
    "shadow_count",
    "scale_read",
    "clutter_density",
    "material_read",
    "era_read",
    "light_read",
    "weather_read",
    "taste_keep",
)

_CONFIDENCES = ("guess", "low", "medium", "high")


def seal_hash_for(payload: Mapping[str, Any]) -> str:
    """§1.7 — sha256 over the canonical JSON of the sealed fields."""
    return content_hash({field: payload.get(field) for field in SEALED_FIELDS})


class SealRefusal(Exception):
    """A prediction write refused. Closed reason codes, as in `core/vocab`."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class PredictionSealer:
    """Writes sealed predictions through the ledger seam.

    Behaviorally identical to the `vocab` seat's `PredictionService` (branch
    `vocab`, `core/vocab/predictions.py`): same refusal codes, same event
    payload shape, same hash. The cold-start melt policy sits *on top* of
    this seam (`sealing.ColdStartSealer`), never inside it.
    """

    def __init__(self, *, ledger: Any, clock: Any) -> None:
        self._ledger = ledger
        self._clock = clock

    def seal(
        self,
        *,
        builder: str,
        claim: str,
        claim_type: str,
        confidence: str,
        basis: str,
        branch_ref: str,
        render_spec: Mapping[str, Any] | None = None,
        reason_code: str | None = None,
        actor: Actor | None = None,
        at: str | None = None,
    ) -> Prediction:
        if claim_type not in _CLAIM_TYPES:
            raise SealRefusal("claim_type_unknown", f"{claim_type!r} is not a claim type")
        if confidence not in _CONFIDENCES:
            raise SealRefusal("confidence_unknown", f"{confidence!r} is not a confidence")

        now = at or self._clock.now()
        payload = {
            "builder": builder,
            "at": now,
            "branch_ref": branch_ref,
            "claim": claim,
            "claim_type": claim_type,
            "confidence": confidence,
            "basis": basis,
            "render_spec": dict(render_spec) if render_spec is not None else None,
        }
        seal_hash = seal_hash_for(payload)
        prediction = Prediction(
            id=f"pr_{short_hash(payload)}",
            builder=builder,
            at=now,
            sealed_at=now,
            branch_ref=branch_ref,
            claim=claim,
            claim_type=claim_type,  # type: ignore[arg-type]
            namespace="taste" if claim_type == "taste_keep" else "world",
            confidence=confidence,  # type: ignore[arg-type]
            basis=basis,
            render_spec=dict(render_spec) if render_spec is not None else None,
            seal_hash=seal_hash,
        )

        event_payload: dict[str, Any] = {
            "prediction_id": prediction.id,
            "seal_hash": seal_hash,
            "claim_type": prediction.claim_type,
            "namespace": prediction.namespace,
            "sealed_payload": payload,
        }
        if reason_code is not None:
            event_payload["reason_code"] = reason_code

        self._ledger.append(
            AuditEvent(
                seq=0,  # the ledger assigns the sequence
                id=f"aud_{short_hash({'type': 'prediction.sealed', 'pid': prediction.id})}",
                at=now,
                actor=actor or Actor(kind="character", id=builder, via="word"),
                type="prediction.sealed",
                subject={"entity_kind": "prediction", "entity_id": prediction.id},
                payload=event_payload,
            )
        )
        return prediction


# -- the night's rails — night-runner's `core/night/models.py` --------------


class Rail(BaseModel):
    """The night's three spend axes (§1.3, §5.5): GPU-minutes from the model
    registry's measured cost table, hosted cents, wall minutes.

    Field-for-field the `night-runner` seat's `Rail` (branch `night-runner`,
    `core/night/models.py`); the calibration batch is sized against it below
    (`calibration.plan_nightly_growth`).
    """

    model_config = ConfigDict(frozen=True)

    gpu_minutes: float = 0.0
    hosted_cents: int = 0
    wall_minutes: float = 0.0

    def add(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=self.gpu_minutes + other.gpu_minutes,
            hosted_cents=self.hosted_cents + other.hosted_cents,
            wall_minutes=self.wall_minutes + other.wall_minutes,
        )

    def subtract(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=max(0.0, self.gpu_minutes - other.gpu_minutes),
            hosted_cents=max(0, self.hosted_cents - other.hosted_cents),
            wall_minutes=max(0.0, self.wall_minutes - other.wall_minutes),
        )

    def fits(self, ask: "Rail") -> bool:
        """True when ``ask`` fits inside this rail (used as a ceiling)."""
        return (
            ask.gpu_minutes <= self.gpu_minutes
            and ask.hosted_cents <= self.hosted_cents
            and ask.wall_minutes <= self.wall_minutes
        )
