"""The clock the night runs on.

Two implementations: :class:`SystemClock` for a real night (waiting for a
render means waiting), and :class:`ScriptedClock` for the simulated nights —
deterministic, so a scenario replays the same way every time and the tests
can say what happened at 02:12.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "ScriptedClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """What time it is, and how to wait for it to pass."""

    def now(self) -> str:
        """The current time, RFC 3339 UTC (§1.0)."""

    def advance(self, minutes: float) -> None:
        """Wait for ``minutes`` to pass."""


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SystemClock:
    """The wall clock of the box."""

    def now(self) -> str:
        return _stamp(datetime.now(timezone.utc))

    def advance(self, minutes: float) -> None:
        if minutes > 0:
            time.sleep(minutes * 60.0)


class ScriptedClock:
    """A deterministic clock: the night moves when the night says it moves."""

    def __init__(self, start: str = "2026-10-30T21:14:00Z") -> None:
        self._current = datetime.fromisoformat(start.replace("Z", "+00:00"))

    def now(self) -> str:
        return _stamp(self._current)

    def advance(self, minutes: float) -> None:
        self._current = self._current + timedelta(minutes=minutes)
