"""The hysteresis gate: a continuous signal, a discrete state, and no flicker.

The rules under test:

* a **split threshold** (an enter threshold and an exit threshold) keeps the
  state when the signal wanders inside the band between them;
* a **minimum dwell time** keeps the state when the signal crosses the band
  and comes straight back — and it filters the short spikes;
* a **single threshold** — the same gate with the band collapsed — flickers
  on exactly the trace the split gate holds still. That is the control;
* the dwell is **paid in latency**, and the trade is measured, not argued;
* the clock is the **caller's**, so a trace replays to the same answer.
"""

from __future__ import annotations

import math

import pytest

from core.hysteresis import HysteresisGate, Level, run_trace

#: The three levels, with their bands.
LEVELS = (
    Level("dead", enter=0.00, exit=float("-inf")),
    Level("unknown", enter=0.40, exit=0.25),
    Level("alive", enter=0.75, exit=0.60),
)

#: The same levels with the bands collapsed: one threshold per level.
#: This is the control — the gate with the hysteresis taken out.
SINGLE = (
    Level("dead", enter=0.00, exit=float("-inf")),
    Level("unknown", enter=0.40, exit=0.40),
    Level("alive", enter=0.75, exit=0.75),
)

#: The sampling interval of the traces, in seconds.
STEP = 0.1

#: The spikes of the spike trace: (when it starts, how long it lasts).
#: Widths from 0.2 s to 3.0 s, so a dwell has something to filter.
SPIKES = (
    (2.0, 0.2),
    (4.0, 0.5),
    (5.0, 1.0),
    (7.0, 2.0),
    (10.0, 3.0),
    (14.0, 0.3),
    (16.0, 0.8),
    (18.0, 1.5),
)

#: Spikes with room between them, so a dwell has a clean decision to make
#: about each one: 0.3 s (too short for a one-second dwell), 1.5 s, 3.0 s,
#: and 0.6 s (long enough for a half-second dwell, too short for a
#: one-second one).
ISOLATED = (
    (2.0, 0.3),
    (6.0, 1.5),
    (12.0, 3.0),
    (20.0, 0.6),
)


def _spike_trace(
    seconds: float = 20.0, spikes=SPIKES
) -> list[tuple[float, float]]:
    """A signal that is mostly low, with spikes of growing and shrinking width."""
    readings = []
    time = 0.0
    while time <= seconds:
        high = any(
            start <= time < start + width for start, width in spikes
        )
        readings.append((0.9 if high else 0.2, time))
        time += STEP
    return readings


def _wobble_trace(seconds: float = 20.0, period: float = 0.7) -> list[tuple[float, float]]:
    """A signal that wanders across the alive threshold, again and again."""
    readings = []
    time = 0.0
    while time <= seconds:
        value = 0.75 + 0.05 * math.sin(2.0 * math.pi * time / period)
        readings.append((value, time))
        time += STEP
    return readings


def _step_trace(seconds: float = 20.0) -> list[tuple[float, float]]:
    """A clean walk: low, then high, then middle, then low again."""
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


# --- the control: one threshold flickers ------------------------------------


def test_a_single_threshold_flickers_where_the_split_gate_holds_still():
    """The control the whole gate exists for.

    The same signal, the same levels, the same clock — the only difference
    is that the control's bands are collapsed to a point, so the state
    follows the signal exactly.
    """
    trace = _spike_trace()

    control = run_trace(HysteresisGate(SINGLE), trace)
    gated = run_trace(HysteresisGate(LEVELS, dwell_up=1.0, dwell_down=1.0), trace)

    # The control moves on every spike — twice, up and back down.
    assert control.transitions == 2 * len(SPIKES)
    # And most of them are flickers: the signal came back down inside the
    # window, so the change meant nothing.
    assert control.flickers > 0.5 * control.transitions
    # The gated one keeps only the spikes that lasted longer than the
    # dwell, and nothing it keeps is a flicker.
    assert gated.transitions < control.transitions
    assert gated.flickers == 0


def test_the_split_threshold_alone_holds_the_state_inside_the_band():
    """A signal that wanders inside the band does not move the state."""
    trace = [
        (0.75 + 0.05 * math.sin(index), index * STEP) for index in range(300)
    ]
    gate = HysteresisGate(LEVELS, dwell_up=0.0, dwell_down=0.0)
    gate.step(0.9, 0.0)
    assert gate.state == "alive"

    gated = run_trace(gate, trace)
    assert gated.transitions == 0

    # And the control, whose band is a point, moves every time it crosses.
    control_gate = HysteresisGate(SINGLE)
    control_gate.step(0.9, 0.0)
    control = run_trace(control_gate, trace)
    assert control.transitions > 20


def test_the_gate_moves_when_the_signal_really_moves():
    trace = _step_trace()
    report = run_trace(HysteresisGate(LEVELS, dwell_up=0.0, dwell_down=0.0), trace)
    # Up to alive, down to unknown, down to dead.
    assert report.transitions == 3
    assert report.states[-1] == "dead"
    assert "unknown" in report.states


# --- the dwell is paid in latency -------------------------------------------


def test_the_state_follows_the_signal_only_after_the_dwell():
    """The dwell is a delay, and the delay is measurable."""
    trace = _step_trace()
    report = run_trace(HysteresisGate(LEVELS, dwell_up=2.0, dwell_down=2.0), trace)
    assert report.transitions == 3
    # The step is at t=5; the state moves two seconds later.
    assert report.mean_latency == pytest.approx(2.0, abs=STEP)
    assert report.max_latency == pytest.approx(2.0, abs=STEP)


def test_the_dwell_filters_the_short_spikes_and_keeps_the_long_ones():
    """The trade, measured on one trace.

    Four isolated spikes: 0.3 s, 1.5 s, 3.0 s and 0.6 s wide. A dwell of
    one second keeps the two long ones and drops the two short ones; a
    dwell of half a second also keeps the 0.6 s one.
    """
    trace = _spike_trace(seconds=24.0, spikes=ISOLATED)

    report = run_trace(HysteresisGate(LEVELS, dwell_up=1.0, dwell_down=1.0), trace)
    assert report.transitions == 4  # the 1.5 s and the 3.0 s spike, up and down
    assert report.flickers == 0

    # A dwell of half a second keeps one more spike -- and that spike is
    # still a flicker, because it comes back down inside the window. **A
    # dwell shorterens the excursion; it does not remove the flicker.** The
    # dwell that removes it is the one longer than the spike.
    looser = run_trace(HysteresisGate(LEVELS, dwell_up=0.5, dwell_down=0.5), trace)
    assert looser.transitions == 6
    assert looser.flickers == 1

    # And no dwell at all keeps every one of them.
    raw = run_trace(HysteresisGate(LEVELS, dwell_up=0.0, dwell_down=0.0), trace)
    assert raw.transitions == 8


def test_a_dwell_that_exceeds_the_signal_spends_means_the_state_never_moves():
    """A dwell longer than the signal's commitment loses the information."""
    trace = _step_trace()
    report = run_trace(HysteresisGate(LEVELS, dwell_up=30.0, dwell_down=30.0), trace)
    assert report.transitions == 0
    assert report.states[-1] == "dead"


# --- the dwell can be asymmetric --------------------------------------------


def test_the_dwell_can_be_asymmetric():
    """A liveness signal should not be dropped by a dip, nor held past it."""
    trace = _step_trace()
    gate = HysteresisGate(LEVELS, dwell_up=4.0, dwell_down=0.0)
    report = run_trace(gate, trace)

    # It went up only after four seconds...
    alive_at = report.states.index("alive") * STEP
    assert alive_at >= 5.0 + 4.0 - STEP
    # ...and it came down at once: the signal dropped to 0.5 at t=12 and
    # the state was down on the next reading.
    alive_index = report.states.index("alive")
    dead_index = next(
        index
        for index in range(alive_index, len(report.states))
        if report.states[index] == "dead"
    )
    assert dead_index * STEP <= 16.0 + STEP


# --- the mechanics -----------------------------------------------------------


def test_a_pending_state_is_not_a_state():
    """The gate reports what the signal wants, and does not pretend."""
    gate = HysteresisGate(LEVELS, dwell_up=5.0, dwell_down=5.0)
    transition = gate.step(0.9, 0.0)
    assert transition.state == "dead"
    assert transition.target == "alive"
    assert transition.changed is False
    assert gate.pending == "alive"

    later = gate.step(0.9, 5.0)
    assert later.state == "alive"
    assert later.changed is True
    assert later.latency == pytest.approx(5.0)


def test_the_dwell_has_to_be_served_by_the_same_target():
    """A target that changes resets the clock."""
    gate = HysteresisGate(LEVELS, dwell_up=2.0, dwell_down=2.0)
    gate.step(0.9, 0.0)
    gate.step(0.5, 1.0)
    transition = gate.step(0.9, 1.5)
    assert transition.state == "dead"
    # The alive target has only been asking since t=1.5, not since t=0.
    assert transition.pending_for == pytest.approx(0.0, abs=STEP)


def test_the_levels_must_not_overlap():
    with pytest.raises(ValueError):
        HysteresisGate(
            (
                Level("low", enter=0.0, exit=0.5),
                Level("high", enter=0.4, exit=0.9),
            )
        )
    with pytest.raises(ValueError):
        Level("backwards", enter=0.2, exit=0.8)
    with pytest.raises(ValueError):
        HysteresisGate((Level("only", enter=0.0, exit=-1.0),))


def test_the_gate_replays_to_the_same_answer():
    """The clock is the caller's, so a trace replays."""
    trace = _spike_trace()
    first = run_trace(HysteresisGate(LEVELS, dwell_up=1.0, dwell_down=1.0), trace)
    second = run_trace(HysteresisGate(LEVELS, dwell_up=1.0, dwell_down=1.0), trace)
    assert first.states == second.states
    assert first.transitions == second.transitions


def test_a_gate_can_be_reset():
    gate = HysteresisGate(LEVELS, dwell_up=0.0, dwell_down=0.0)
    gate.step(0.9, 0.0)
    assert gate.state == "alive"
    gate.reset()
    assert gate.state == "dead"
    assert gate.pending is None


def test_the_report_keeps_its_denominator():
    trace = _spike_trace()
    report = run_trace(HysteresisGate(SINGLE), trace)
    assert report.transitions > 0
    assert 0.0 <= report.flicker_rate <= 1.0
    assert report.state_seconds
    assert report.seconds == pytest.approx(20.0, abs=STEP)
