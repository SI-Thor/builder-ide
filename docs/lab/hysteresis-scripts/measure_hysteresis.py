"""The numbers in ``docs/lab/exp-hysteresis-gate.md``, printed.

Run from the repo root::

    PYTHONPATH=. python docs/lab/hysteresis-scripts/measure_hysteresis.py

It needs nothing but the repo's own ``core.hysteresis`` and the standard
library. The traces are synthetic and deterministic: a signal that is
mostly low with spikes of known widths, and a signal that wanders across a
threshold.
"""

from __future__ import annotations

from core.hysteresis import HysteresisGate, Level, run_trace

#: The three levels, with their bands: enter 0.40 to be unknown and 0.75
#: to be alive; leave unknown below 0.25 and alive below 0.60.
LEVELS = (
    Level("dead", enter=0.00, exit=float("-inf")),
    Level("unknown", enter=0.40, exit=0.25),
    Level("alive", enter=0.75, exit=0.60),
)

#: The same levels with the bands collapsed to a point. This is the
#: control: a single threshold, which is what the core does today.
SINGLE = (
    Level("dead", enter=0.00, exit=float("-inf")),
    Level("unknown", enter=0.40, exit=0.40),
    Level("alive", enter=0.75, exit=0.75),
)

STEP = 0.1

#: Spikes well separated, so each one is a clean decision for the dwell.
ISOLATED = ((2.0, 0.3), (6.0, 1.5), (12.0, 3.0), (20.0, 0.6))


def spike_trace(seconds: float = 24.0, spikes=ISOLATED):
    readings = []
    time = 0.0
    while time <= seconds:
        high = any(start <= time < start + width for start, width in spikes)
        readings.append((0.9 if high else 0.2, time))
        time += STEP
    return readings


def wobble_trace(seconds: float = 20.0, period: float = 0.7):
    """A signal that wanders across the alive threshold, again and again."""
    import math

    readings = []
    time = 0.0
    while time <= seconds:
        value = 0.75 + 0.05 * math.sin(2.0 * math.pi * time / period)
        readings.append((value, time))
        time += STEP
    return readings


def step_trace(seconds: float = 20.0):
    readings = []
    time = 0.0
    while time <= seconds:
        if time < 5.0:
            value = 0.1
        elif time < 12.0:
            value = 0.9
        elif time < 16.0:
            value = 0.5
        else:
            value = 0.1
        readings.append((value, time))
        time += STEP
    return readings


def rule(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main() -> None:
    trace = spike_trace()

    rule("1. the control: a single threshold on the same trace")
    control = run_trace(HysteresisGate(SINGLE), trace)
    print(f"transitions        {control.transitions}")
    print(f"flickers           {control.flickers}")
    print(f"flicker rate       {control.flicker_rate:.3f}")
    print(f"time in each state {control.state_seconds}")

    rule("2. the split thresholds, with no dwell")
    split = run_trace(HysteresisGate(LEVELS), trace)
    print(f"transitions        {split.transitions}")
    print(f"flickers           {split.flickers}")

    rule("2b. the split thresholds on a signal that wanders near the threshold")
    wobble = wobble_trace()
    control_wobble = run_trace(HysteresisGate(SINGLE), wobble)
    split_wobble = run_trace(HysteresisGate(LEVELS), wobble)
    print(f"single threshold: {control_wobble.transitions} changes, "
          f"{control_wobble.flickers} flickers")
    print(f"split thresholds: {split_wobble.transitions} changes, "
          f"{split_wobble.flickers} flickers")
    print("  (the signal's lowest value is 0.70 and the alive band's exit")
    print("   threshold is 0.60: the state never leaves alive)")

    rule("3. the dwell, on the same trace")
    print(f"{'dwell':>7s} {'changes':>8s} {'flickers':>9s} {'mean lat':>9s} {'worst':>7s}")
    for dwell in (0.0, 0.25, 0.5, 1.0, 2.0, 5.0):
        report = run_trace(
            HysteresisGate(LEVELS, dwell_up=dwell, dwell_down=dwell), trace
        )
        print(
            f"{dwell:7.2f} {report.transitions:8d} {report.flickers:9d} "
            f"{report.mean_latency:9.3f} {report.max_latency:7.3f}"
        )

    rule("4. the spikes, and what each dwell does with them")
    print("spike widths: " + ", ".join(f"{w:.1f}s" for _s, w in ISOLATED))
    for dwell in (0.0, 0.5, 1.0, 2.0):
        report = run_trace(
            HysteresisGate(LEVELS, dwell_up=dwell, dwell_down=dwell), trace
        )
        print(f"  dwell {dwell:4.2f}s -> {report.transitions} changes, "
              f"{report.flickers} flickers")

    rule("5. a clean step, and the latency it costs")
    step = step_trace()
    for dwell in (0.0, 1.0, 4.0):
        report = run_trace(
            HysteresisGate(LEVELS, dwell_up=dwell, dwell_down=dwell), step
        )
        print(f"  dwell {dwell:4.2f}s -> {report.transitions} changes, "
              f"mean latency {report.mean_latency:.3f}s, "
              f"worst {report.max_latency:.3f}s")

    rule("6. the dwell can be asymmetric")
    gate = HysteresisGate(LEVELS, dwell_up=4.0, dwell_down=0.0)
    report = run_trace(gate, step)
    alive_at = report.states.index("alive") * STEP
    alive_index = report.states.index("alive")
    dead_index = next(
        index
        for index in range(alive_index, len(report.states))
        if report.states[index] == "dead"
    )
    print(f"  the signal steps up at t=5.0; the state moves at t={alive_at:.1f}")
    print(f"  the signal steps down at t=16.0; the state is dead by "
          f"t={dead_index * STEP:.1f}")


if __name__ == "__main__":
    main()
