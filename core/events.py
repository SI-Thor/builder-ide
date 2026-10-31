"""AuditEvent — the one log (core-spec §1.8).

Everything the panels show is a view over this table. Event types are a
closed set; adding one is a schema change.

The record itself lives in :mod:`core.records`, with every other seat's
copy of it, so there is exactly one ``AuditEvent`` in the tree. This
module keeps the log's helpers and re-exports the names the rest of the
service imports from here.
"""
from __future__ import annotations

from typing import Any

from .canon import now_utc
from .records import EVENT_TYPES, Actor, ActorKind, AuditEvent

__all__ = [
    "EVENT_TYPES",
    "Actor",
    "ActorKind",
    "AuditEvent",
    "core_actor",
    "owner_actor",
    "character_actor",
    "MAX_PAYLOAD_BYTES",
    "spill_payload",
]


def core_actor(agent: str | None = None) -> Actor:
    return Actor(kind="core", id="core", agent=agent)


def owner_actor(actor_id: str, via: str | None = None,
                agent: str | None = None) -> Actor:
    return Actor(kind="owner", id=actor_id, via=via, agent=agent)


def character_actor(character_id: str, via: str | None = None,
                    agent: str | None = None) -> Actor:
    return Actor(kind="character", id=character_id, via=via, agent=agent)


MAX_PAYLOAD_BYTES = 4096


def spill_payload(event: AuditEvent) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """If the payload exceeds the 4 KiB cap, spill it to an artifact and
    return (slim payload referencing it, artifact descriptor). The spill is
    written by the store inside the same transaction."""
    from .canon import bytes_hash, canonical_bytes

    data = canonical_bytes(event.payload)
    if len(data) <= MAX_PAYLOAD_BYTES:
        return event.payload, None
    artifact = {
        "sha256": bytes_hash(data),
        "kind": "event.payload",
        "bytes": len(data),
    }
    slim = {"_spilled": artifact, "type": event.type}
    return slim, {"descriptor": artifact, "data": data}
