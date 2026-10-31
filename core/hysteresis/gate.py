"""A gate between a continuous signal and a discrete state.

**The problem.** The core has continuous confidences and discrete states
side by side, and it keeps converting between them: a builder's confidence
in a claim, a root's liveness, a tile's standing. Every one of those
conversions is a **threshold**, and a threshold on a noisy signal
**flickers**: the signal dips a hair below the line, the state flips, the
signal comes back, the state flips again. Each flip is a fact written to
the log, a tile retired and un-retired, a claim spoken and withdrawn.

**The fix, and it is two numbers and a clock.**

1. **Split thresholds.** Each state has an *enter* threshold and an *exit*
   threshold, and the gap between them is the state's **band**. To move up
   into a state the signal has to reach its enter threshold; to move down
   out of it, the signal has to fall below its exit threshold. A signal
   that wanders inside a band does not move the state at all — which is
   exactly the behaviour a threshold near the signal's noise floor cannot
   have.
2. **A minimum dwell time.** Even a split threshold flips if the signal
   crosses the band, wanders back, and crosses again. So a state change
   has to *want* to happen for a while before it happens: the candidate
   state has to be the target for the dwell time before it is committed.
   The cost is latency, and the cost is real and is measured rather than
   argued about.

**The dwell can be asymmetric**, and for a liveness signal it should be:
a root that has just been attested alive should not be dropped by a
momentary dip, and a root that has just been found dead should not wait
to say so. ``dwell_up`` and ``dwell_down`` are separate for that reason.

**This module does not decide what the states mean.** It is the mechanism:
the levels, their bands, and the clock. What a level means is the
caller's — ``alive``/``unknown``/``dead`` for the WHY kernel,
``active``/``retired`` for a tile, ``high``/``medium``/``low`` for a
confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = ["HysteresisGate", "Level", "Transition"]


@dataclass(frozen=True)
class Level:
    """One discrete state, with the band that enters it and leaves it.

    ``enter`` is the value at or above which the state may be entered from
    below. ``exit`` is the value below which the state must be left
    downwards. The gap between a level's ``exit`` and the next level up's
    ``enter`` is the **sticking band**: inside it the state does not
    change.

    The lowest level's ``exit`` is conventionally ``-inf``: there is
    nothing below it to fall into.
    """

    name: str
    enter: float
    exit: float

    def __post_init__(self) -> None:
        if self.exit > self.enter:
            raise ValueError(
                f"level {self.name!r}: the exit threshold ({self.exit}) is "
                f"above the enter threshold ({self.enter}); the band would "
                "be the wrong way round"
            )


@dataclass(frozen=True)
class Transition:
    """What one step of the gate did."""

    #: The state after the step.
    state: str
    #: Whether the state changed on this step.
    changed: bool
    #: The state the signal is asking for, whether or not it was
    #: committed. A pending state is not a state.
    target: str
    #: How long the target has been asking, in seconds.
    pending_for: float
    #: How long the committed state waited for its target, when it just
    #: changed. ``None`` when it did not change.
    latency: float | None = None


class HysteresisGate:
    """A discrete state driven by a continuous signal, with bands and a dwell.

    ``levels`` is ordered from the lowest to the highest. The gate starts
    in the lowest level.

    The two dwell times are the price of stability:

    * ``dwell_up`` — how long a state must be *asking* to be entered
      before it is entered;
    * ``dwell_down`` — how long it must be asking to be left before it is
      left.

    Both are in seconds of the caller's clock, and both are compared
    against the caller's timestamps: the gate has no clock of its own,
    because a gate that keeps its own time cannot be replayed.
    """

    def __init__(
        self,
        levels: Sequence[Level],
        *,
        dwell_up: float = 0.0,
        dwell_down: float = 0.0,
        name: str = "",
    ) -> None:
        if len(levels) < 2:
            raise ValueError("a gate needs at least two levels")
        if dwell_up < 0.0 or dwell_down < 0.0:
            raise ValueError("a dwell time is a duration")
        self.levels = tuple(levels)
        for lower, higher in zip(self.levels, self.levels[1:]):
            if lower.exit > higher.enter:
                raise ValueError(
                    f"levels {lower.name!r} and {higher.name!r} overlap: the "
                    "lower one's exit threshold is above the higher one's "
                    "enter threshold"
                )
        self.dwell_up = float(dwell_up)
        self.dwell_down = float(dwell_down)
        self.name = name
        self.state = self.levels[0].name
        self._pending: str | None = None
        self._pending_since: float = 0.0
        self._latency: float | None = None

    # -- the reads -------------------------------------------------------------

    @property
    def pending(self) -> str | None:
        """The state the signal is asking for, if it is not the current one."""
        return self._pending

    def reset(self) -> None:
        """Back to the lowest level, with nothing pending."""
        self.state = self.levels[0].name
        self._pending = None
        self._pending_since = 0.0
        self._latency = None

    # -- the step --------------------------------------------------------------

    def step(self, value: float, now: float) -> Transition:
        """Feed the gate one reading and get the state back.

        ``value`` is the continuous signal and ``now`` is the caller's
        clock. The gate decides what the signal is asking for (the
        **target**), and commits it only if the target has been asking for
        the dwell time.
        """
        target = self._target_for(value)
        latency: float | None = None
        changed = False

        if target == self.state:
            self._pending = None
            self._latency = None
        else:
            if self._pending != target:
                self._pending = target
                self._pending_since = now
            dwell = self.dwell_up if self._is_above(target) else self.dwell_down
            waited = now - self._pending_since
            if waited >= dwell:
                self.state = target
                changed = True
                latency = waited
                self._pending = None
                self._latency = None
            else:
                self._latency = waited

        pending_for = (
            0.0 if self._pending is None else now - self._pending_since
        )
        return Transition(
            state=self.state,
            changed=changed,
            target=target,
            pending_for=pending_for,
            latency=latency,
        )

    # -- the internals ---------------------------------------------------------

    def _is_above(self, target: str) -> bool:
        """True when the target is above the current state."""
        order = [level.name for level in self.levels]
        return order.index(target) > order.index(self.state)

    def _target_for(self, value: float) -> str:
        """The state the signal is asking for.

        From the current state:

        * **up**: the highest level whose *enter* threshold the value has
          reached;
        * **down**: the highest level below the current one whose *enter*
          threshold the value has still reached — which is how the bands
          work: a value that has fallen below the current level's exit
          cannot be in it, but it may not have fallen past the level
          below's enter either, and that is the sticking band;
        * **otherwise**: the current state.
        """
        order = [level.name for level in self.levels]
        index = order.index(self.state)
        current = self.levels[index]

        if index + 1 < len(self.levels) and value >= self.levels[index + 1].enter:
            target_index = index + 1
            while (
                target_index + 1 < len(self.levels)
                and value >= self.levels[target_index + 1].enter
            ):
                target_index += 1
            return self.levels[target_index].name

        if value < current.exit:
            target_index = index
            while target_index > 0 and value < self.levels[target_index].enter:
                target_index -= 1
            return self.levels[target_index].name

        return current.name
