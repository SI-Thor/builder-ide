"""Derived views over the audit log.

Spec §1.0: "The `audit` table is the source of truth; all other tables are
projections rebuilt by folding `audit`."

The ledger and its projections belong to `core-api` (branch `core-api`). These
folders are this seat's *read* path over that log: they rebuild the records
the vocabulary and the gate need without depending on another seat's tables
being in place yet. They are pure functions over a list of audit events.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .models import AuditEvent, Prediction
from .predictions import seal_hash_for

__all__ = ["fold_predictions", "events_of_type", "last_event_of_type"]


def events_of_type(events: Iterable[Any], *types: str) -> list[AuditEvent]:
    """Every audit event whose type is in `types`, in ledger order."""
    wanted = set(types)
    return [event for event in events if getattr(event, "type", None) in wanted]


def last_event_of_type(events: Iterable[Any], event_type: str) -> AuditEvent | None:
    """The most recent event of a type, or `None`."""
    found = None
    for event in events:
        if getattr(event, "type", None) == event_type:
            found = event
    return found


def fold_predictions(events: Sequence[Any]) -> dict[str, Prediction]:
    """Rebuild the sealed predictions from the log, keyed by `pr_` id.

    A `prediction.sealed` event carries the sealed payload verbatim; a
    `prediction.scored` event carries the verdict. The fold is the only place
    the verdict is attached, so a sealed record stays sealed (§1.7).
    """
    predictions: dict[str, Prediction] = {}
    for event in events:
        event_type = getattr(event, "type", None)
        payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
        if event_type == "prediction.sealed":
            sealed = payload.get("sealed_payload") or {}
            prediction_id = str(payload.get("prediction_id", ""))
            if not prediction_id:
                continue
            predictions[prediction_id] = Prediction(
                id=prediction_id,
                builder=str(sealed.get("builder", "")),
                at=str(sealed.get("at", event.at)),
                sealed_at=str(sealed.get("at", event.at)),
                branch_ref=str(sealed.get("branch_ref", "")),
                claim=str(sealed.get("claim", "")),
                claim_type=sealed.get("claim_type", "scale_read"),
                namespace="taste"
                if sealed.get("claim_type") == "taste_keep"
                else "world",
                confidence=sealed.get("confidence", "guess"),
                basis=str(sealed.get("basis", "0 observations")),
                render_spec=sealed.get("render_spec"),
                seal_hash=str(payload.get("seal_hash", "")),
                verdict=None,
            )
        elif event_type == "prediction.scored":
            prediction_id = str(payload.get("prediction_id", ""))
            prediction = predictions.get(prediction_id)
            if prediction is not None:
                predictions[prediction_id] = prediction.model_copy(
                    update={"verdict": payload.get("verdict")}
                )
    return predictions


def seal_intact(prediction: Prediction) -> bool:
    """True when a folded prediction still hashes to its own seal hash."""
    return prediction.seal_hash == seal_hash_for(prediction.model_dump())
