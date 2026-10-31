"""What a gate does to a signal: the flicker it removes and the latency it adds.

Two numbers, and they trade against each other:

* **flicker** — the state changes that mean nothing. A change that is
  reversed within a short window is a flicker: the signal went over the
  line and came back, and both crossings are now facts in the log. The
  window is a parameter, because "a flicker" is only meaningless relative
  to how long the state was going to last anyway.
* **latency** — how long the state took to follow the signal once the
  signal had actually changed its mind. The dwell time is paid here.

A gate is worth its dwell only if the flicker it removes is worth more
than the latency it adds, and **that is a measurement, not an argument**.
This module makes it: run a trace through the gate and count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .gate import HysteresisGate, Transition

__all__ = ["TraceReport", "run_trace"]


@dataclass(frozen=True)
class TraceReport:
    """What one trace did to one gate."""

    #: The state after each reading.
    states: tuple[str, ...]
    #: How many times the state changed.
    transitions: int
    #: How many of those changes were reversed within the window — the
    #: flickers.
    flickers: int
    #: The mean and the worst delay between the signal changing its mind
    #: and the state following it.
    mean_latency: float
    max_latency: float
    #: The trace's length in seconds.
    seconds: float
    #: How long the gate spent in each state.
    state_seconds: Mapping[str, float]
    #: The window a reversal had to happen inside to count as a flicker.
    window: float

    @property
    def flicker_rate(self) -> float:
        """The flickers per transition, with the denominator kept."""
        if not self.transitions:
            return 0.0
        return self.flickers / self.transitions

    def line(self) -> str:
        """The one line the morning can show."""
        return (
            f"{self.transitions} changes, {self.flickers} flickers "
            f"· mean latency {self.mean_latency:.3f}s "
            f"· worst {self.max_latency:.3f}s"
        )


def run_trace(
    gate: HysteresisGate,
    readings: Sequence[tuple[float, float]],
    *,
    window: float = 1.0,
) -> TraceReport:
    """Run a trace of ``(value, seconds)`` through a gate and measure it.

    ``window`` is how long a change has to be reversed to count as a
    flicker. One second is the default because it is the order of the
    thing this gate is for: a confidence reading that wobbles for a
    moment.
    """
    if window < 0.0:
        raise ValueError("a window is a duration")

    states: list[str] = []
    changes: list[tuple[int, str, str, float]] = []
    latencies: list[float] = []
    spent: dict[str, float] = {}
    previous_state: str | None = None
    previous_time: float | None = None

    for value, now in readings:
        transition: Transition = gate.step(value, now)
        states.append(transition.state)
        spent[transition.state] = spent.get(transition.state, 0.0)
        if previous_state is not None and previous_time is not None:
            spent[transition.state] += max(0.0, now - previous_time)
        if transition.changed and previous_state is not None:
            changes.append(
                (len(states) - 1, previous_state, transition.state, now)
            )
            if transition.latency is not None:
                latencies.append(transition.latency)
        previous_state = transition.state
        previous_time = now

    # A change is a flicker when the state comes back to where it was
    # within the window.
    flickers = 0
    for index, (_, was, became, when) in enumerate(changes):
        for later_index, _, back, later_when in changes[index + 1 :]:
            if later_when - when > window:
                break
            if back == was:
                flickers += 1
                break

    seconds = readings[-1][1] - readings[0][1] if readings else 0.0
    return TraceReport(
        states=tuple(states),
        transitions=len(changes),
        flickers=flickers,
        mean_latency=(sum(latencies) / len(latencies)) if latencies else 0.0,
        max_latency=max(latencies) if latencies else 0.0,
        seconds=seconds,
        state_seconds=spent,
        window=window,
    )
