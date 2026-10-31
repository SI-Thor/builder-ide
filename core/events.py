"""AuditEvent — the one log (core-spec §1.8).

Everything the panels show is a view over this table. Event types are a
closed set; adding one is a schema change.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .canon import now_utc

# The closed set, verbatim from §1.8 ("New in v2" types included).
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # work orders
        "wo.filed", "wo.compiled", "wo.questioned", "wo.confirmed", "wo.queued",
        "wo.attempt.started", "wo.attempt.delivered", "wo.testing", "wo.landed",
        "wo.kept", "wo.rejected", "wo.parked", "wo.resumed", "wo.failed",
        "wo.cancelled",
        # recipe (appended by the recipe half; folded here)
        "edit.proposed", "edit.validated", "version.committed", "branch.created",
        "branch.head.moved", "branch.rejected", "branch.proposed",
        "constraint.failed",
        # predictions
        "prediction.sealed", "prediction.scored",
        # taste
        "taste.note.appended", "taste.erased", "taste.ratified",
        # vocabulary
        "vocab.word.added", "vocab.word.status", "vocab.call",
        # night
        "night.started", "night.stopped", "night.preflight", "night.tick",
        "night.task.created", "night.task.state", "line.spoken",
        # scheduler (appended by the runner half; folded here)
        "sched.model.load", "sched.model.unload", "sched.demote", "job.enqueued",
        "job.started", "job.done", "job.requeued", "render.completed",
        "scene.loaded", "scene.evicted", "power.mode.set",
        # critic
        "critic.verdict",
        # budget
        "budget.spend", "budget.threshold", "kill.switch",
        # assets
        "asset.created", "asset.licence.checked",
        # questions
        "question.parked", "question.answered", "assumption.recorded",
        # continuity
        "model.change.noticed",
        # client
        "client.attach", "client.detach",
        # system
        "core.boot", "core.recovered", "projection.rebuilt", "integrity.failure",
        "call.refused",
    }
)

ActorKind = Literal["owner", "character", "engineer", "critic", "core", "scheduler", "client"]


class Actor(BaseModel):
    """Who did it. Actor ids: owner actors are per person (casey, magnus)."""

    kind: ActorKind
    id: str
    via: str | None = None  # word | wo when a character acts through one


def core_actor() -> Actor:
    return Actor(kind="core", id="core")


def owner_actor(actor_id: str) -> Actor:
    return Actor(kind="owner", id=actor_id)


def character_actor(character_id: str, via: str | None = None) -> Actor:
    return Actor(kind="character", id=character_id, via=via)


MAX_PAYLOAD_BYTES = 4096


class AuditEvent(BaseModel):
    seq: int | None = None  # assigned at commit; gapless per project (§1.8)
    id: str = Field(min_length=4)
    at: str = Field(default_factory=now_utc)
    actor: Actor
    type: str
    subject: dict[str, str]  # {entity_kind, entity_id}
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] | None = None  # {sha256, kind, bytes}
    # Refused events (the vocab.call precedent: "refused calls included —
    # the edges are the story") commit to the log but change no projection.
    refused: bool = False

    def validate_type(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.type!r}; the set is closed (§1.8)")

    @property
    def subject_id(self) -> str:
        """The subject's entity id. Named to match the audit table's
        `subject_kind`/`subject_id` columns, so the fold can read the
        subject the same way it writes it."""
        return self.subject.get("entity_id", "")

    @property
    def subject_kind(self) -> str:
        return self.subject.get("entity_kind", "")

    def payload_bytes(self) -> int:
        from .canon import canonical_bytes

        return len(canonical_bytes(self.payload))


def spill_payload(event: AuditEvent) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """If the payload exceeds the 4 KiB cap, spill it to an artifact and
    return (slim payload referencing it, artifact descriptor). The spill is
    written by the store inside the same transaction."""
    from .canon import canonical_bytes, bytes_hash

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
