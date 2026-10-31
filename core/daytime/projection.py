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
        #: The day in progress: the ticks since the last night stopped, and
        #: what they cost.
        self.day_ticks = 0
        self.day_minutes = 0.0
        #: What the day in progress did, per (kind, target).
        self.day_changes: dict[tuple[str, str], int] = {}
        self._day_light_from: str | None = None
        self._day_light_to: str | None = None
        #: The day that came before each night — "while you were away".
        self.day_before_night: dict[str, dict] = {}
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
        # The day's accounting is about the log's events, so it is counted
        # whether or not the world is there to advance.
        self.day_ticks += 1
        self.day_minutes += float(event.payload.get("minutes", 0.0))
        if self.world is None:
            return
        self.world = advance(self.world)

    def _on_day_change(self, event: AuditEvent) -> None:
        payload = event.payload.get("change") or {}
        change = DayChange(**payload)
        key = (change.kind, change.target)
        self.day_changes[key] = self.day_changes.get(key, 0) + 1
        if change.kind == "light":
            if self._day_light_from is None:
                self._day_light_from = str(change.before.get("phase", ""))
            self._day_light_to = str(change.after.get("phase", ""))
        if self.world is None:
            return
        self.world = apply_change(self.world, change)

    def _on_day_yielded(self, event: AuditEvent) -> None:
        self.yields += 1
        self.last_yield_reason = event.payload.get("reason")

    def _on_night_started(self, event: AuditEvent) -> None:
        night = self._night_id(event)
        self.nights_running.add(night)
        # A night closes the day that came before it: the daytime ticks
        # happen between one night stopping and the next one starting, and
        # this is where they are kept as "while you were away".
        self.day_before_night[night] = self._day_snapshot()

    def _on_night_stopped(self, event: AuditEvent) -> None:
        self.nights_running.discard(self._night_id(event))
        # The night is over, so the day begins: the budget starts fresh.
        self._start_new_day()

    # -- the day ----------------------------------------------------------

    def _night_id(self, event: AuditEvent) -> str:
        doc = event.payload.get("night") or {}
        return (
            event.payload.get("night_id")
            or doc.get("id")
            or event.subject_id
            or ""
        )

    def _day_snapshot(self) -> dict:
        """What the day in progress was."""
        return {
            "ticks": self.day_ticks,
            "minutes": round(self.day_minutes, 6),
            "changes": [
                {"kind": kind, "target": target, "count": count}
                for (kind, target), count in sorted(self.day_changes.items())
            ],
            "light_from": self._day_light_from,
            "light_to": self._day_light_to,
        }

    def _start_new_day(self) -> None:
        self.day_ticks = 0
        self.day_minutes = 0.0
        self.day_changes = {}
        self._day_light_from = None
        self._day_light_to = None

    # -- reads ------------------------------------------------------------

    @property
    def night_lane_busy(self) -> bool:
        """Is the night working right now? The daytime yields when it is."""
        return bool(self.nights_running)

    def day_before(self, night_id: str) -> dict:
        """The day that came before this night — "while you were away"."""
        return self.day_before_night.get(night_id) or {
            "ticks": 0,
            "minutes": 0.0,
            "changes": [],
            "light_from": None,
            "light_to": None,
        }
