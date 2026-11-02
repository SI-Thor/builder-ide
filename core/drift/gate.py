"""The gate: one signal, one threshold, and the choice between a level
and a rate.

**The mechanism is not new.** ``core/hysteresis`` already owns the
band-and-dwell gate: split thresholds, a minimum dwell, the caller's
clock. This module is that gate plus the one decision §3.4 makes, which
is *what value is compared to the threshold*.

* ``mode="level"`` compares the signal's **level** to the threshold:
  fire when the signal is bad.
* ``mode="rate"`` compares the signal's **rate of change** to the
  threshold: fire when the signal *becomes* bad.

The two are not two settings of one dial. The level gate is a state; the
rate gate is a change of state, and only one of them is a trigger
(``docs/lab/exp-syzygy-keyframes.md`` §5.9). A world that is *always*
slow is not drifting; a world that *becomes* slow is. A scout whose
worst gap is ten times its median gap has been that way for the whole
run — that is its shape, not its drift.

**The rate is one-sided**, and it is one-sided for the same reason
syzygy's was: every signal here is a *badness* (higher is worse), and
only a **rise** in badness is drift. A fall is recovery, and a gate
that fires on recovery is a gate that fires on good news. The syzygy
gate is the same shape — ``conf[i-1] - conf[i] > tau``, the reader
*losing* the scene, not the reader regaining it.

Both modes are compared in the lab on the **same signal** with the
**same threshold** and the **same hysteresis**, so the only thing the
comparison changes is level against rate.

An **undefined** signal (no data for this window) is not a zero. The
gate holds its state, and the dwell timer is reset: a gap in the
evidence is not evidence of persistence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.hysteresis import HysteresisGate, Level, Transition

from .config import GateSpec

__all__ = ["DriftGate", "GateResult", "GateMode", "LEVEL", "RATE", "HYBRID", "HybridGate"]

#: Compare the signal's level to the threshold.
LEVEL = "level"
#: Compare the signal's rate of change to the threshold.
RATE = "rate"
#: Fire on the **change**, hold while the **level** is bad.
HYBRID = "hybrid"

GateMode = str


@dataclass(frozen=True)
class GateResult:
    """What one step of a gate did."""

    state: str
    changed: bool
    #: True when the state moved **into** alarm. This is a fire.
    fired: bool
    #: True when the state moved out of alarm.
    cleared: bool
    #: The signal's own value for this window.
    value: float | None
    #: The value the gate actually compared against the threshold.
    fed: float | None
    #: The state the gate is asking for.
    target: str
    #: How long the target has been asking, in seconds.
    pending_for: float


class DriftGate:
    """A signal's gate: a band, a dwell, and a choice of level or rate."""

    def __init__(
        self,
        name: str,
        spec: GateSpec,
        *,
        mode: GateMode = RATE,
    ) -> None:
        if mode not in (LEVEL, RATE):
            raise ValueError(f"unknown gate mode {mode!r}")
        self.name = name
        self.spec = spec
        self.mode = mode
        self._gate = HysteresisGate(
            [
                Level("ok", enter=float("-inf"), exit=float("-inf")),
                Level("alarm", enter=spec.enter, exit=spec.exit),
            ],
            dwell_up=spec.dwell_up,
            dwell_down=spec.dwell_down,
            name=name,
        )
        self._previous: float | None = None

    # -- the reads ------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._gate.state

    @property
    def pending(self) -> str | None:
        return self._gate.pending

    def reset(self) -> None:
        self._gate.reset()
        self._previous = None

    # -- the step --------------------------------------------------------------

    def step(self, value: float | None, now: float) -> GateResult:
        """Feed the gate one window's signal and get the state back.

        ``value`` is the signal's own value for this window — the level
        in ``LEVEL`` mode, the raw value in ``RATE`` mode. ``None`` means
        the signal is undefined here.
        """
        if value is None:
            # No evidence: hold the state, and refuse to let a pending
            # transition survive the gap.
            self._gate.reset_pending()
            return GateResult(
                state=self._gate.state,
                changed=False,
                fired=False,
                cleared=False,
                value=None,
                fed=None,
                target=self._gate.state,
                pending_for=0.0,
            )

        fed = self._feed(value)
        transition: Transition = self._gate.step(fed, now)
        fired = transition.changed and transition.state == "alarm"
        cleared = transition.changed and transition.state != "alarm"
        return GateResult(
            state=transition.state,
            changed=transition.changed,
            fired=fired,
            cleared=cleared,
            value=value,
            fed=fed,
            target=transition.target,
            pending_for=transition.pending_for,
        )

    # -- the internals ---------------------------------------------------------

    def _feed(self, value: float) -> float:
        """The number the threshold is compared against.

        In rate mode this is the **rise** of the badness, and only the
        rise: the signal is a badness (higher is worse), so a fall is
        recovery. See the module docstring.
        """
        if self.mode == LEVEL:
            return value
        previous = self._previous
        self._previous = value
        if previous is None:
            return 0.0
        if math.isinf(value) or math.isinf(previous):
            return math.inf
        return max(0.0, value - previous)

    def reset_pending(self) -> None:
        """Drop a pending transition without touching the committed state."""
        self._gate.reset_pending()


class HybridGate:
    """Fire on the **change**, hold while the **level** is bad.

    **Why this gate exists.** The lab measured both of the other modes
    on the world's own ledger, and each one is wrong in a way the
    other one is right about:

    * the **rate** gate is a trigger. It fires when the signal becomes
      bad, which is exactly right — a level gate is a state, and only
      a change of state is a trigger. But a drift that *stays* bad
      stops changing, so the rate gate's own signal falls back to zero
      and the alarm clears while the world is still off track. A four
      hour wedge was detected at its onset and forgotten.
    * the **level** gate is a state. It holds, so it does not forget a
      sustained drift — but it also latches on the whole time, and a
      signal that is *permanently* high (the scout's worst gap is ten
      times its median gap, and always has been) leaves it on for
      good.

    So the trigger and the hold want different quantities: **the rate
    decides when to fire, and the level decides when to let go.** The
    band-and-dwell discipline is the same one ``core/hysteresis``
    keeps — the target has to want to happen for the dwell time
    before it happens — and the clock is the caller's, so a trace
    replays to the same answer.
    """

    def __init__(
        self,
        name: str,
        *,
        enter_rate: float,
        exit_level: float,
        dwell_up: float = 0.0,
        dwell_down: float = 0.0,
    ) -> None:
        if exit_level < 0.0:
            raise ValueError("the exit level is a value")
        self.name = name
        self.enter_rate = enter_rate
        self.exit_level = exit_level
        self.dwell_up = dwell_up
        self.dwell_down = dwell_down
        self.state = "ok"
        self._pending: str | None = None
        self._pending_since = 0.0
        self._previous: float | None = None

    @property
    def pending(self) -> str | None:
        return self._pending

    def reset(self) -> None:
        self.state = "ok"
        self._pending = None
        self._pending_since = 0.0
        self._previous = None

    def reset_pending(self) -> None:
        """Drop a pending transition, keeping the committed state."""
        self._pending = None
        self._pending_since = 0.0

    def step(self, value: float | None, now: float) -> GateResult:
        """Feed the gate one window's signal value."""
        if value is None:
            self.reset_pending()
            return GateResult(
                state=self.state,
                changed=False,
                fired=False,
                cleared=False,
                value=None,
                fed=None,
                target=self.state,
                pending_for=0.0,
            )
        previous = self._previous
        self._previous = value
        if previous is None:
            rate = 0.0
        elif math.isinf(value) or math.isinf(previous):
            rate = math.inf
        else:
            # One-sided: only a rise in the badness is drift.
            rate = max(0.0, value - previous)

        if self.state == "ok":
            target = "alarm" if rate >= self.enter_rate else "ok"
            fed = rate
        else:
            target = "ok" if value < self.exit_level else "alarm"
            fed = value

        changed = False
        if target == self.state:
            self._pending = None
        else:
            if self._pending != target:
                self._pending = target
                self._pending_since = now
            dwell = self.dwell_up if target == "alarm" else self.dwell_down
            if now - self._pending_since >= dwell:
                self.state = target
                changed = True
                self._pending = None

        return GateResult(
            state=self.state,
            changed=changed,
            fired=changed and self.state == "alarm",
            cleared=changed and self.state != "alarm",
            value=value,
            fed=fed,
            target=target,
            pending_for=0.0 if self._pending is None else now - self._pending_since,
        )
