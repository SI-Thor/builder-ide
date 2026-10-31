"""The heartbeat — the core writes a row for the whole window (§3.4).

**The morning's status line is computed from the ledger, not written by
whoever is awake to write it** — which is what makes it survive the failure it
is describing. The heartbeat is the input to that computation: a wall-clock
row plus every sealed step, and the *gaps* between the rows are what a reboot
leaves behind (§5.2 step 5).

The tick payload carries a ``kind`` so one row type can carry the night's
truth without a new event type: ``wall`` (the tick), ``sealed-step`` (a bet
was sealed), ``stall`` (lane contention, with the minutes it cost) and
``batches`` (the big batches finally started, and how late).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from core.night.ledger import Ledger
from core.night.models import Actor, AuditEvent

__all__ = ["Heartbeat", "tick_gaps", "lost_minutes", "TICK_INTERVAL_MINUTES"]

#: The core ticks the window every ten minutes (§3.4: admission is
#: re-checked on a 10-minute tick).
TICK_INTERVAL_MINUTES = 10

_DEFAULT_ACTOR = Actor(kind="core", id="night-runner")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


class Heartbeat:
    """Writes ``night.tick`` rows into the log."""

    def __init__(
        self,
        ledger: Ledger,
        night_id: str,
        *,
        clock=_utcnow,
        actor: Actor = _DEFAULT_ACTOR,
    ) -> None:
        self._ledger = ledger
        self.night_id = night_id
        self._clock = clock
        self._actor = actor

    def tick(self, *, kind: str = "wall", note: str | None = None, **extra) -> AuditEvent:
        payload: dict = {"at": self._clock(), "kind": kind}
        if note is not None:
            payload["note"] = note
        payload.update(extra)
        return self._ledger.append(
            type="night.tick",
            actor=self._actor,
            subject={"entity_kind": "night", "entity_id": self.night_id},
            payload=payload,
            at=payload["at"],
        )

    def stall(self, minutes: float, *, note: str | None = None) -> AuditEvent:
        """A batch waited on the lane; the minutes it waited are recorded."""
        return self.tick(kind="stall", note=note, minutes=minutes)

    def batches_started(
        self, *, late_minutes: float = 0.0, cause: str | None = None
    ) -> AuditEvent:
        """The big batches started — on detach, or at the deadline."""
        return self.tick(kind="batches", late_minutes=late_minutes, cause=cause)


def tick_gaps(ticks: Sequence[AuditEvent]) -> list[float]:
    """The minutes between consecutive ticks, oldest first."""
    gaps: list[float] = []
    for earlier, later in zip(ticks, ticks[1:]):
        minutes = (_parse(later.at) - _parse(earlier.at)).total_seconds() / 60.0
        gaps.append(minutes)
    return gaps


def lost_minutes(
    ticks: Sequence[AuditEvent], *, expected_interval_minutes: int = TICK_INTERVAL_MINUTES
) -> float:
    """The minutes the box was not answering for — the hole a reboot leaves.

    A tick that lands on the interval is the night working; the time *past*
    the interval is time nobody was there to spend.
    """
    total = 0.0
    for gap in tick_gaps(ticks):
        total += max(0.0, gap - expected_interval_minutes)
    return total
