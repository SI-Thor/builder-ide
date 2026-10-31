"""The projection: the daytime world rebuilt by folding the audit log.

Core-spec v2 §1.0 makes the audit table the source of truth and every other
table a projection rebuilt by folding it. The daytime seat leans on that
harder than most: the world has **no file of its own**. The room is what
you get when you fold the log, which is why the same recipe and the same
tick reconstruct the same world — the log is the only place the world
lives.

The fold is pure — it reads events and writes nothing back — so the world
can be rebuilt at any time, including after a kill -9.
"""

from __future__ import annotations

from typing import Sequence

from .models import AuditEvent, DayChange, DayObject, DayRoom, DayWorld
from .world import advance, apply_change

__all__ = ["DayProjection"]


class DayProjection:
    """Everything the daytime seat knows, folded out of the log."""

    def __init__(self, events: Sequence[AuditEvent]) -> None:
        self.events = list(events)
        self.world: DayWorld | None = None
        #: How many times the daytime stood down for the night.
        self.yields = 0
        #: Why it stood down, last time.
        self.last_yield_reason: str | None = None
        #: The nights the log says are running. The daytime lane yields to
        #: these — the night is the work.
        self.nights_running: set[str] = set()
        #: What the daytime lane has spent, folded out of the ticks.
        self.minutes_spent = 0.0
        self.ticks_run = 0
        self._fold(self.events)

    # -- the fold ---------------------------------------------------------

    def _fold(self, events: Sequence[AuditEvent]) -> None:
        for event in events:
            if event.refused:
                continue  # a refusal commits to the log but changes nothing
            handler = getattr(self, f"_on_{event.type.replace('.', '_')}", None)
            if handler is not None:
                handler(event)

    def _on_day_world_opened(self, event: AuditEvent) -> None:
        payload = event.payload
        room = payload.get("room") or {}
        objects = tuple(
            DayObject(
                path=obj.get("path", ""),
                kind=obj.get("kind", ""),
                changes=dict(obj.get("changes") or {}),
            )
            for obj in room.get("objects") or ()
        )
        self.world = DayWorld(
            recipe_id=payload.get("recipe_id", ""),
            version_id=payload.get("version_id", ""),
            tick=0,
            room=DayRoom(
                light=int(room.get("light", 0)),
                phase=str(room.get("phase", "night")),
                objects=objects,
            ),
        )

    def _on_day_tick(self, event: AuditEvent) -> None:
        if self.world is None:
            return
        self.world = advance(self.world)
        self.ticks_run += 1
        self.minutes_spent += float(event.payload.get("minutes", 0.0))

    def _on_day_change(self, event: AuditEvent) -> None:
        if self.world is None:
            return
        payload = event.payload.get("change") or {}
        self.world = apply_change(self.world, DayChange(**payload))

    def _on_day_yielded(self, event: AuditEvent) -> None:
        self.yields += 1
        self.last_yield_reason = event.payload.get("reason")

    def _on_night_started(self, event: AuditEvent) -> None:
        self.nights_running.add(event.subject_id or event.payload.get("night_id") or "")

    def _on_night_stopped(self, event: AuditEvent) -> None:
        self.nights_running.discard(event.subject_id or event.payload.get("night_id") or "")

    # -- reads ------------------------------------------------------------

    @property
    def night_lane_busy(self) -> bool:
        """Is the night working right now? The daytime yields when it is."""
        return bool(self.nights_running)
