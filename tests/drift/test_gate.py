"""The gate: level against rate, the band, the dwell, and the hybrid.

The claims under test are the ones the lab note rests on:

* a **rate** gate fires on a change and not on a level that has always
  been there;
* a **level** gate fires on a level;
* the band stops the alarm from flickering;
* an undefined signal holds the state and drops the pending
  transition;
* the **hybrid** fires on the change and holds while the level is bad.
"""

from __future__ import annotations

import math

import pytest

from core.drift.config import GateSpec
from core.drift.gate import HYBRID, LEVEL, RATE, DriftGate, HybridGate


def test_the_rate_gate_fires_on_a_change_not_on_a_level() -> None:
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0), mode=RATE)
    # A level that sits at 10 forever: the rate is zero, so the gate
    # never asks for the alarm.
    now = 0.0
    for _ in range(20):
        result = gate.step(10.0, now)
        now += 300.0
        assert not result.fired
    assert gate.state == "ok"


def test_the_rate_gate_fires_when_the_signal_changes() -> None:
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0), mode=RATE)
    gate.step(1.0, 0.0)
    result = gate.step(5.0, 300.0)
    assert result.fired
    assert gate.state == "alarm"


def test_the_rate_gate_does_not_fire_on_a_recovery() -> None:
    """Only a rise in the badness is drift; a fall is recovery."""
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0), mode=RATE)
    gate.step(10.0, 0.0)
    result = gate.step(1.0, 300.0)
    assert not result.fired
    assert gate.state == "ok"


def test_the_level_gate_fires_on_a_level() -> None:
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0), mode=LEVEL)
    gate.step(1.0, 0.0)
    result = gate.step(5.0, 300.0)
    assert result.fired
    assert gate.state == "alarm"


def test_the_level_gate_fires_on_a_level_that_was_always_there() -> None:
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0), mode=LEVEL)
    now = 0.0
    fired = False
    for _ in range(20):
        result = gate.step(10.0, now)
        now += 300.0
        fired = fired or result.fired
    assert fired
    assert gate.state == "alarm"


def test_the_band_stops_the_alarm_flickering() -> None:
    """A signal that wanders inside the band must not clear the alarm."""
    gate = DriftGate("stall", GateSpec(enter=10.0, exit=8.0, dwell_down=600.0), mode=LEVEL)
    gate.step(10.0, 0.0)
    assert gate.state == "alarm"
    # 9.0 is inside the band (below the enter threshold, above the
    # exit threshold): the alarm holds.
    for step in range(1, 10):
        result = gate.step(9.0, step * 300.0)
        assert gate.state == "alarm"
        assert not result.cleared


def test_the_alarm_clears_below_the_exit_threshold() -> None:
    gate = DriftGate("stall", GateSpec(enter=10.0, exit=8.0, dwell_down=600.0), mode=LEVEL)
    gate.step(10.0, 0.0)
    assert gate.state == "alarm"
    gate.step(7.0, 300.0)
    # The dwell has not been served yet.
    assert gate.state == "alarm"
    gate.step(7.0, 1200.0)
    assert gate.state == "ok"


def test_an_undefined_signal_holds_the_state_and_drops_the_pending() -> None:
    gate = DriftGate("stall", GateSpec(enter=2.0, exit=1.0, dwell_up=600.0), mode=LEVEL)
    gate.step(1.0, 0.0)
    result = gate.step(None, 300.0)
    assert result.value is None
    assert gate.state == "ok"
    # The pending was dropped, so a later value does not ride on the
    # gap's evidence.
    assert gate.pending is None


def test_the_first_value_has_no_rate() -> None:
    gate = DriftGate("stall", GateSpec(enter=0.0, exit=0.0), mode=RATE)
    result = gate.step(100.0, 0.0)
    assert result.fed == 0.0


def test_an_infinite_value_does_not_produce_a_nan() -> None:
    gate = DriftGate("spend", GateSpec(enter=1.0, exit=0.5), mode=RATE)
    gate.step(1.0, 0.0)
    result = gate.step(math.inf, 300.0)
    assert not math.isnan(result.fed)
    assert math.isinf(result.fed)


def test_the_hybrid_fires_on_the_change_and_holds_on_the_level() -> None:
    gate = HybridGate("stall", enter_rate=2.0, exit_level=5.0, dwell_up=0.0, dwell_down=0.0)
    gate.step(1.0, 0.0)
    result = gate.step(6.0, 300.0)
    assert result.fired
    assert gate.state == "alarm"
    # The signal has stopped changing, but it is still bad: the alarm
    # holds. This is the case the rate gate gets wrong.
    result = gate.step(6.0, 600.0)
    assert not result.cleared
    assert gate.state == "alarm"
    # The level comes back to normal: the alarm lets go.
    result = gate.step(1.0, 900.0)
    assert result.cleared
    assert gate.state == "ok"


def test_the_hybrid_does_not_fire_on_a_level_that_was_always_there() -> None:
    gate = HybridGate("stall", enter_rate=2.0, exit_level=5.0, dwell_up=0.0, dwell_down=0.0)
    now = 0.0
    for _ in range(20):
        result = gate.step(10.0, now)
        now += 300.0
        assert not result.fired
    assert gate.state == "ok"


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        DriftGate("stall", GateSpec(enter=1.0, exit=0.5), mode="sideways")


def test_the_band_the_wrong_way_round_is_refused() -> None:
    with pytest.raises(ValueError):
        GateSpec(enter=1.0, exit=2.0)
