"""The hysteresis gate: a continuous signal, a discrete state, and no flicker.

    from core.hysteresis import HysteresisGate, Level, run_trace

    gate = HysteresisGate(
        [
            Level("dead", enter=0.00, exit=float("-inf")),
            Level("unknown", enter=0.40, exit=0.25),
            Level("alive", enter=0.75, exit=0.60),
        ],
        dwell_up=2.0,
        dwell_down=0.5,
        name="root-liveness",
    )
    transition = gate.step(0.81, now=12.5)
    print(transition.state)

The note is in `core/hysteresis/README.md`.
"""

from __future__ import annotations

from .gate import HysteresisGate, Level, Transition
from .metrics import TraceReport, run_trace

__all__ = [
    "HysteresisGate",
    "Level",
    "TraceReport",
    "Transition",
    "run_trace",
]
