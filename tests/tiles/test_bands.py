"""Pincher's score bands on top of the retrieval: execute, confirm, compile.

The rules under test:

* the band is a **split threshold** — a score above ``tau_hi`` executes, a
  score below ``tau_lo`` compiles, and the gap between them confirms;
* the band **holds**: a score that wobbles across a threshold does not
  change the standing, because the hysteresis gate is what holds it
  (``core/hysteresis``, the way ``core/judge`` holds its escalation);
* the **band is held per subject** — a tile that scores badly in one
  context does not drag the band down in another;
* a score below ``tau_lo`` means **compile**: file a request to the cloud
  author for a new tile, and do not play anything;
* a score in the middle means **confirm**: the tile is played, but the
  play is marked as one that was confirmed rather than executed directly.
"""

from __future__ import annotations

import pytest

from core.tiles.bands import (
    BandConfig,
    BandDecision,
    BandGate,
    DEFAULT_BAND,
    DEFAULT_TAU_HI,
    DEFAULT_TAU_LO,
)


def test_the_defaults_are_pincher_s_bands():
    """Pincher's own thresholds: 0.80 executes, 0.55 confirms."""
    assert DEFAULT_TAU_HI == 0.80
    assert DEFAULT_TAU_LO == 0.55


def test_a_score_above_the_high_line_executes():
    gate = BandGate()
    decision = gate.step_for("weathered crates", 0.92, now=0.0)
    assert decision.band == "execute"


def test_a_score_in_the_gap_confirms():
    gate = BandGate()
    decision = gate.step_for("weathered crates", 0.70, now=0.0)
    assert decision.band == "confirm"


def test_a_score_below_the_low_line_compiles():
    gate = BandGate()
    decision = gate.step_for("weathered crates", 0.20, now=0.0)
    assert decision.band == "compile"


def test_the_band_says_which_score_it_read():
    gate = BandGate()
    decision = gate.step_for("weathered crates", 0.92, now=0.0)
    assert decision.score == 0.92
    assert isinstance(decision, BandDecision)


def test_the_band_is_held_per_subject():
    """One context's bad score does not move another's band."""
    gate = BandGate()
    gate.step_for("stained crates", 0.10, now=0.0)
    decision = gate.step_for("weathered crates", 0.95, now=0.0)
    assert decision.band == "execute"


def test_a_wobbling_score_does_not_flicker_the_band():
    """The gate holds the standing: this is the flicker it exists for."""
    gate = BandGate()
    gate.step_for("weathered crates", 0.92, now=0.0)
    # 0.78 is inside the gap, so a naive threshold would drop to "confirm".
    decision = gate.step_for("weathered crates", 0.78, now=1.0)
    assert decision.band == "execute"


def test_a_far_enough_fall_does_move_the_band():
    """The band is held, not frozen: a real fall still moves it."""
    gate = BandGate()
    gate.step_for("weathered crates", 0.92, now=0.0)
    decision = gate.step_for("weathered crates", 0.30, now=1.0)
    assert decision.band == "compile"


def test_the_band_is_configurable():
    """The thresholds are a parameter, because the scores are a measurement."""
    gate = BandGate(config=BandConfig(tau_hi=0.60, tau_lo=0.40))
    assert gate.step_for("t", 0.65, now=0.0).band == "execute"
    assert gate.step_for("t", 0.50, now=0.0).band == "confirm"
    assert gate.step_for("t", 0.10, now=0.0).band == "compile"


def test_the_band_width_is_the_gap_below_the_high_line():
    """The band is the width under tau_hi, the way the judge's band is."""
    config = BandConfig(tau_hi=0.80, tau_lo=0.55, band=DEFAULT_BAND)
    gate = BandGate(config=config)
    gate.step_for("t", 0.90, now=0.0)
    # 0.80 - band is the sticking band: inside it, the standing holds.
    assert gate.step_for("t", 0.80 - DEFAULT_BAND + 0.01, now=1.0).band == "execute"


def test_a_config_with_the_wrong_order_is_refused():
    with pytest.raises(ValueError):
        BandConfig(tau_hi=0.40, tau_lo=0.80)


def test_a_config_with_a_band_reaching_the_low_line_is_refused():
    with pytest.raises(ValueError):
        BandConfig(tau_hi=0.80, tau_lo=0.55, band=0.30)


def test_the_band_remembers_where_it_was():
    """The standing is a state that persists, so it can be read back."""
    gate = BandGate()
    gate.step_for("t", 0.92, now=0.0)
    assert gate.standing_for("t") == "execute"
    assert gate.standing_for("other") == "compile"


def test_the_band_is_reset_per_subject():
    gate = BandGate()
    gate.step_for("t", 0.92, now=0.0)
    gate.reset_for("t")
    assert gate.standing_for("t") == "compile"


def test_a_reset_band_starts_in_the_safe_band():
    """A cold subject compiles: it does not execute on a cold reading."""
    gate = BandGate()
    gate.reset_for("t")
    assert gate.standing_for("t") == "compile"


def test_the_band_reports_the_score_it_was_given():
    gate = BandGate()
    decision = gate.step_for("t", 0.93, now=0.0)
    assert decision.score == pytest.approx(0.93)


def test_the_decision_says_whether_the_band_moved():
    gate = BandGate()
    first = gate.step_for("t", 0.10, now=0.0)
    assert first.changed is True
    second = gate.step_for("t", 0.11, now=1.0)
    assert second.changed is False
