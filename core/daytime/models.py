"""The records the daytime seat owns.

The audit records live in :mod:`core.records` — one definition each, shared
with every other seat — and are re-exported here so ``from core.daytime.models
import AuditEvent`` works the way it does in the other seats.

The world's own records are these: a room, the things in it, and the small
changes that happen to them. They are frozen: a world is a state, not a
thing you edit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.records import Actor, AuditEvent

__all__ = [
    "Actor",
    "AuditEvent",
    "DayChange",
    "DayObject",
    "DayRoom",
    "DayWorld",
    "PlannedEvent",
]


class DayChange(BaseModel):
    """One small change in the room — what a tick did, and to what.

    ``kind`` is one of the closed change kinds (light, tidy, grow); ``target``
    is the recipe entry's path, or ``"room"`` for the light itself.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    target: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)


class DayObject(BaseModel):
    """One thing in the room, and what has happened to it.

    ``changes`` counts the behaviours that have fired on it: ``{"tidy": 2}``
    says a builder has tidied it twice.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    kind: str
    changes: dict[str, int] = Field(default_factory=dict)


class DayRoom(BaseModel):
    """One room: the light in it, and the things in it."""

    model_config = ConfigDict(frozen=True)

    light: int
    phase: str
    objects: tuple[DayObject, ...] = ()


class DayWorld(BaseModel):
    """One room, one clock — the whole of the daytime world.

    ``tick`` is the clock: the number of ticks the room has lived through.
    The recipe and the version it was opened on are part of the world,
    because the world is only reproducible against *those*.
    """

    model_config = ConfigDict(frozen=True)

    recipe_id: str
    version_id: str
    tick: int
    room: DayRoom


class PlannedEvent(BaseModel):
    """One event the plan calls for: its type and its payload.

    The plan is the deterministic heart of the seat: the runner turns these
    into audit events and appends them, and the projection folds them back.
    Both read the same plan, so the world that comes out of the log is the
    world the arithmetic says it is.
    """

    model_config = ConfigDict(frozen=True)

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
