"""The play record — one use of a tile, written to the log (§3 of the design).

This is the only thing that teaches anything, so the write path is careful
about three things:

* **the option must exist.** A tile that is not in the library cannot be
  played, and a retired tile cannot be played. The library admitted it
  (and wrote ``tile.authored``) before the play exists — the ordering that
  makes the log readable afterwards.
* **the context travels with the play.** A play without its context cannot
  be learned from; that is the whole difference between a contextual bandit
  and a lookup table.
* **a play that does not fit is refused, not truncated.** The ledger caps a
  payload at 4 KiB (§1.8). A truncated context is a lie about the context.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.canon import canonical_bytes, now_utc
from core.records import Actor

from .library import MAX_PAYLOAD_BYTES, TileLibrary
from .models import Outcome, PlayCost, PlayRecord, Tile, TileRefusal, build_play_record
from .ports import LedgerPort

__all__ = ["record_play", "fold_plays", "PLAY_EVENT_TYPE"]

#: The one audit type a play writes.
PLAY_EVENT_TYPE = "tile.played"


def record_play(
    *,
    ledger: LedgerPort,
    library: TileLibrary,
    tile: Tile,
    context: Mapping[str, Any],
    outcome: Outcome,
    cost: PlayCost | None = None,
    chooser: str = "",
    chooser_version: str = "",
    night: str | None = None,
    at: str | None = None,
    propensity: float | None = None,
    candidates: Sequence[str] = (),
    scope: str | None = None,
) -> PlayRecord:
    """Record one use of a tile and write it to the log.

    The tile must be in the library and must be active: an option that was
    never admitted, or one that has been retired, is not something a
    decision model may play.
    """
    admitted = library.get(tile.id)
    if admitted is None:
        raise TileRefusal(
            "tile_not_admitted", f"{tile.id} was never admitted to the library"
        )
    if admitted.status != "active":
        raise TileRefusal(
            "tile_retired", f"{tile.id} was retired at {admitted.retired_at}"
        )

    moment = at or now_utc()
    record = build_play_record(
        at=moment,
        tile=admitted,
        context=context,
        outcome=outcome,
        cost=cost,
        chooser=chooser,
        chooser_version=chooser_version,
        night=night,
        propensity=propensity,
        candidates=candidates,
        scope=scope,
    )

    payload = _play_payload(record)
    size = len(canonical_bytes(payload))
    if size > MAX_PAYLOAD_BYTES:
        raise TileRefusal(
            "play_payload_too_large",
            f"the play's payload is {size} bytes; the cap is {MAX_PAYLOAD_BYTES}",
        )

    ledger.append(
        type=PLAY_EVENT_TYPE,
        actor=Actor(kind="core", id=chooser or "tile-chooser", via="tile"),
        subject={"entity_kind": "tile", "entity_id": record.tile_id},
        payload=payload,
        at=moment,
    )
    return record


def fold_plays(events: Sequence[Any]) -> tuple[PlayRecord, ...]:
    """The play records, folded out of the log (§3).

    The log is the source of truth, so this is how the chooser and the
    retrain read what happened — after a restart, or on another box, the
    answer is the same.
    """
    records: list[PlayRecord] = []
    for event in events:
        if getattr(event, "type", None) != PLAY_EVENT_TYPE:
            continue
        payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
        records.append(_play_from_payload(payload, getattr(event, "at", "")))
    return tuple(records)


def _play_payload(record: PlayRecord) -> dict[str, Any]:
    """The payload of a ``tile.played`` row."""
    return {
        "play_id": record.id,
        "tile_id": record.tile_id,
        "tile_version": record.tile_version,
        "context": dict(record.context),
        "outcome": record.outcome.model_dump(),
        "cost": record.cost.model_dump(),
        "chooser": record.chooser,
        "chooser_version": record.chooser_version,
        "night": record.night,
        "propensity": record.propensity,
        "candidates": list(record.candidates),
        "scope": record.scope,
    }


def _play_from_payload(payload: Mapping[str, Any], at: str) -> PlayRecord:
    """Rebuild a play record from a ``tile.played`` payload."""
    try:
        return PlayRecord(
            id=str(payload["play_id"]),
            at=str(payload.get("at") or at),
            tile_id=str(payload["tile_id"]),
            tile_version=int(payload.get("tile_version", 1)),
            context=dict(payload.get("context") or {}),
            outcome=Outcome.model_validate(payload["outcome"]),
            cost=PlayCost.model_validate(payload.get("cost") or {}),
            chooser=str(payload.get("chooser", "")),
            chooser_version=str(payload.get("chooser_version", "")),
            night=payload.get("night"),
            propensity=(
                None
                if payload.get("propensity") is None
                else float(payload["propensity"])
            ),
            candidates=tuple(str(t) for t in (payload.get("candidates") or ())),
            scope=None if payload.get("scope") is None else str(payload.get("scope")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TileRefusal(
            "play_record_malformed", f"a tile.played row does not read back: {exc}"
        ) from exc
