"""The confidence gate as policy: τ per (backend, model, task), a ladder,
and a standing that does not flicker.

E1 (lab-cascade, folded into liquid-study §1.4) is where the default
comes from: on the action gate, **every** d1-2B error sat below
confidence 0.5 — above 0.5 it was 196/196 exactly right, so a gate at
0.5 caught 100 % of the errors with 2 % of the traffic. "Act at or
above τ, escalate below" is that measurement, made policy.

Where a judgment drives a state that persists across ticks, the raw
threshold would flicker straight into the ledger (liquid-study Part 3,
item 3): the standing gate wraps :mod:`core.hysteresis` — the
mechanism built and measured for exactly this — with the confidence as
the continuous signal.
"""

from __future__ import annotations

import pytest

from core.judge.backends import FakeBackend
from core.judge.gate import (
    DEFAULT_TAU,
    ConfidencePolicy,
    EscalationLadder,
    StandingConfig,
    StandingGate,
)


# --- the policy ---------------------------------------------------------------


def test_the_default_tau_is_e1s_half():
    assert DEFAULT_TAU == 0.5


def test_tau_is_looked_up_per_backend_model_then_task_then_default():
    policy = ConfidencePolicy(
        taus={
            ("d1", "d1-2B", "tiles.shortlist"): 0.40,
            ("jev", "jev-latest", "*"): 0.70,
        }
    )
    # the exact (backend, model, task) key wins
    assert policy.tau_for("d1", "d1-2B", "tiles.shortlist") == 0.40
    # then (backend, model, *)
    assert policy.tau_for("jev", "jev-latest", "anything.else") == 0.70
    # then the default from E1
    assert policy.tau_for("d1", "d1-2B", "critic.verify") == DEFAULT_TAU
    assert policy.tau_for("clef", "clef-flash", "anything") == DEFAULT_TAU


def test_act_is_at_or_above_tau():
    policy = ConfidencePolicy()
    assert policy.decision(confidence=0.5) == "act"
    assert policy.decision(confidence=0.9) == "act"
    assert policy.decision(confidence=0.4999) == "escalate"


def test_a_judgment_with_no_confidence_is_escalated_not_silent():
    """A backend that reports no confidence cannot be trusted past a gate.

    Treating ``None`` as confident would be a default that biases
    nobody can see — the same lie a missing propensity would be.
    """
    policy = ConfidencePolicy()
    assert policy.decision(confidence=None) == "escalate"


# --- the ladder ---------------------------------------------------------------


def test_the_ladder_names_its_rungs_in_order():
    first, second = FakeBackend(), FakeBackend()
    ladder = EscalationLadder(rungs=[("d1", first), ("jev", second)])
    assert [name for name, _ in ladder.rungs] == ["d1", "jev"]
    assert ladder.next_after("d1") is second
    assert ladder.next_after("jev") is None
    assert ladder.next_after("unknown") is None


def test_a_ladder_needs_at_least_one_rung():
    with pytest.raises(ValueError):
        EscalationLadder(rungs=[])


# --- the standing gate (hysteresis) -------------------------------------------


def test_the_standing_uses_the_hysteresis_mechanism_with_tau_as_the_enter_line():
    gate = StandingGate(tau=0.5, band=0.1, dwell_up=2.0)
    # below the exit line: the standing is escalate
    assert gate.step(0.30, now=0.0).state == "escalate"
    # inside the band (0.40..0.50): the standing does not move
    assert gate.step(0.45, now=1.0).state == "escalate"
    # above tau with the dwell unserved: pending, not committed
    transition = gate.step(0.60, now=2.0)
    assert transition.target == "act"
    assert transition.state == "escalate"
    # the dwell served: the standing commits
    assert gate.step(0.60, now=2.0 + gate.dwell_up).state == "act"
    # back inside the band: the standing holds (no flicker)
    assert gate.step(0.45, now=5.0).state == "act"


def test_the_standing_commits_after_the_dwell_and_reports_latency():
    gate = StandingGate(tau=0.5, band=0.1, dwell_up=3.0)
    gate.step(0.60, now=0.0)
    gate.step(0.55, now=1.0)
    transition = gate.step(0.70, now=3.0)
    assert transition.changed
    assert transition.state == "act"
    assert transition.latency == pytest.approx(3.0)


def test_the_standing_is_per_subject():
    gate = StandingGate(tau=0.5, band=0.1, dwell_up=0.0)
    gate.step_for("tiles/left", 0.9, now=0.0)
    gate.step_for("tiles/right", 0.2, now=0.0)
    assert gate.standing_for("tiles/left") == "act"
    assert gate.standing_for("tiles/right") == "escalate"


def test_the_standing_starts_at_escalate():
    """A cold standing is the safe one: escalate until the signal earns act."""
    gate = StandingGate(tau=0.5, band=0.1)
    assert gate.standing == "escalate"


# --- the adopted configuration (the sweep's choice, tests first) --------------


def test_the_adopted_standing_config_is_the_sweep_s_choice():
    """The default is a measurement, not a taste.

    The real d1 traces replayed through the gate (exp-hysteresis-d1; the
    sweep table and its results JSON are beside the harness): at the
    traces' calibrated τ the raw τ gate flickers 66 times in 240 ticks on
    the 2B recording, and this shape leaves one flicker with the raw
    gate's catch and agreement kept and both latency bounds met — band
    0.15, dwell_up 2 ticks, dwell_down 0 (the band holds the shallow
    wobble; the dwell_up earns act; a real drop is not delayed). τ stays
    E1's default until a task's own calibration names another.
    """
    assert StandingConfig() == StandingConfig(
        tau=DEFAULT_TAU, band=0.15, dwell_up=2.0, dwell_down=0.0
    )
    # the gate the wiring builds by default carries the adopted numbers
    gate = StandingGate()
    assert (gate.tau, gate.band, gate.dwell_up, gate.dwell_down) == (
        DEFAULT_TAU,
        0.15,
        2.0,
        0.0,
    )


def test_a_wandering_confidence_no_longer_flips_the_standing_state():
    """The brief's first wired behaviour, on the adopted configuration.

    The signal warms into `act` and then wanders across τ every other
    tick without ever falling below the exit line — the raw τ gate (the
    current policy) flips on every crossing and writes a fact per flip;
    the standing holds.
    """
    gate = StandingGate()
    wander = [0.9, 0.9, 0.9, 0.55, 0.42, 0.55, 0.42, 0.55, 0.42]
    for tick, value in enumerate(wander):
        gate.step(value, now=tick)

    assert gate.standing == "act"  # the wobble never dropped it
    standing_changes = 0
    fresh = StandingGate()
    for tick, value in enumerate(wander):
        if fresh.step(value, now=tick).changed:
            standing_changes += 1
    # the only change in the whole series is the warm-up commit
    assert standing_changes == 1

    raw = ConfidencePolicy()
    raw_words = [raw.decision(confidence=value) for value in wander]
    raw_flips = sum(
        1 for before, after in zip(raw_words, raw_words[1:]) if before != after
    )
    assert raw_flips >= 4  # the raw gate flip-flops across the same series


def test_a_real_drop_still_escalates_within_the_latency_bound():
    """The brief's second wired behaviour: a sustained drop commits within
    the bound (2 ticks), not eventually, never."""
    gate = StandingGate()
    for tick, value in enumerate([0.9, 0.9, 0.9]):
        gate.step(value, now=tick)
    assert gate.standing == "act"

    transition = gate.step(0.30, now=3.0)
    assert transition.changed
    assert transition.state == "escalate"
    assert transition.latency <= 2.0

    # and with a down-dwell configured, the commitment still lands inside
    # the bound: a 2-tick dwell serves two readings, then commits at
    # latency 2.0 — the bound, not past it
    gated = StandingGate(dwell_down=2.0)
    gated.step(0.9, now=0.0)  # dwell_up defaults to 2.0; warm it
    gated.step(0.9, now=1.0)
    gated.step(0.9, now=2.0)
    assert gated.standing == "act"
    first = gated.step(0.30, now=3.0)
    assert not first.changed  # the dwell is being served
    second = gated.step(0.30, now=4.0)
    assert not second.changed  # still being served
    third = gated.step(0.30, now=5.0)
    assert third.changed and third.state == "escalate"
    assert third.latency == pytest.approx(2.0)
    assert third.latency <= 2.0


def test_the_standing_config_validates_its_numbers():
    with pytest.raises(ValueError):
        StandingConfig(tau=0.5, band=0.5)  # the band reaches tau itself
    with pytest.raises(ValueError):
        StandingConfig(tau=0.5, band=-0.1)
    with pytest.raises(ValueError):
        StandingConfig(tau=0.0)
    with pytest.raises(ValueError):
        StandingConfig(dwell_up=-1.0)
    with pytest.raises(ValueError):
        StandingConfig(dwell_down=-1.0)
