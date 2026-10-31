"""The clock.

Timestamps are RFC 3339 UTC (spec §1.0). Everything that stamps a time takes a
`Clock`, so a test can order events exactly — the sealed-before-render
ordering is only meaningful if the clock is under the test's control.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "SystemClock", "SteppingClock", "FixedClock", "format_rfc3339"]


@runtime_checkable
class Clock(Protocol):
    """Anything that can say what time it is, in RFC 3339 UTC."""

    def now(self) -> str:  # pragma: no cover - protocol
        ...


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

    Used by tests: two events never share a timestamp, so "sealed before the
    render" is a strict inequality and not an accident of the wall clock.
    """

    def __init__(self, start: str = "2026-10-30T21:20:00Z", step_seconds: int = 1) -> None:
        self._now = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> str:
        value = format_rfc3339(self._now)
        self._now += self._step
        return value

    def peek(self) -> str:
        """The current time without advancing it."""
        return format_rfc3339(self._now)


class FixedClock:
    """A clock that always says the same thing."""

    def __init__(self, moment: str = "2026-10-30T21:20:00Z") -> None:
        self._moment = moment

    def now(self) -> str:
        return self._moment
