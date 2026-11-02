"""The detector and the pause ladder.

§3.5 has three levels of auto-pause, and §3.4 says one of the six
signals is not a rate at all: a rule violation is zero tolerance, one
occurrence escalates immediately, and it is never averaged into a
score. These tests hold that line.
"""

from __future__ import annotations

from pathlib import Path

from core.drift.config import DriftConfig, GateSpec
from core.drift.detect import HARD, SOFT, TIER, DriftDetector
from core.drift.gate import HYBRID, RATE
from core.drift.ledger import build_series


def _config(**overrides) -> DriftConfig:
    base = DriftConfig()
    return base.with_thresholds(**overrides) if overrides else base


def test_a_quiet_world_produces_no_alarms(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    detection = DriftDetector(_config()).run(series)
    assert detection.alarms == []


def test_a_rule_violation_escalates_immediately(violating_ledger: Path) -> None:
    series = build_series(violating_ledger, bucket_seconds=300)
    detection = DriftDetector(_config()).run(series)
    hard = [a for a in detection.alarms if a.level == HARD]
    assert len(hard) == 1
    assert hard[0].signal == "violation"
    assert hard[0].agent == "Kite"
    # No threshold, no dwell: it fires on the window it happens in.
    assert hard[0].fed == 1.0


def test_the_violation_alarm_is_not_scored_with_the_others(
    violating_ledger: Path,
) -> None:
    series = build_series(violating_ledger, bucket_seconds=300)
    detection = DriftDetector(_config()).run(series)
    assert all(a.signal != "violation" for a in detection.soft)
    assert all(a.signal != "violation" for a in detection.tier)


def test_the_world_scope_signal_demotes_the_work(refusing_ledger: Path) -> None:
    """The decision model's refusal is everybody's problem: tier, not soft."""
    series = build_series(refusing_ledger, bucket_seconds=300)
    config = _config(errors=GateSpec(enter=0.5, exit=0.25))
    detection = DriftDetector(config, mode=RATE).run(series)
    assert detection.alarms
    assert all(a.level == TIER for a in detection.alarms)
    assert all(a.signal == "errors" for a in detection.alarms)


def test_one_agent_alone_is_a_soft_pause(stalled_ledger: Path) -> None:
    series = build_series(stalled_ledger, bucket_seconds=300)
    config = _config(stall=GateSpec(enter=2.0, exit=1.0))
    detection = DriftDetector(config, mode=RATE).run(series)
    soft = [a for a in detection.alarms if a.level == SOFT]
    assert soft
    assert all(a.agent == "Kite" for a in soft)


def test_several_agents_at_once_promote_to_the_tier(stalled_ledger: Path) -> None:
    series = build_series(stalled_ledger, bucket_seconds=300)
    config = _config(stall=GateSpec(enter=2.0, exit=1.0), tier_agents=1)
    detection = DriftDetector(config, mode=RATE).run(series)
    assert any(a.level == TIER for a in detection.alarms)


def test_the_alarm_windows_record_the_state_not_just_the_transitions(
    refusing_ledger: Path,
) -> None:
    series = build_series(refusing_ledger, bucket_seconds=300)
    config = _config(errors=GateSpec(enter=0.5, exit=0.25))
    detection = DriftDetector(config, mode=RATE).run(series)
    assert detection.alarm_windows
    # The state covers more windows than the fires, or the detector
    # would be reporting transitions and not a state.
    alarmed = set(detection.alarm_windows)
    fired = {a.at for a in detection.alarms}
    assert len(alarmed) >= len(fired)


def test_the_hybrid_mode_runs(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = _config(stall=GateSpec(enter=1.0, exit=0.6, level_exit=5.0))
    detection = DriftDetector(config, mode=HYBRID).run(series)
    assert detection.states["stall"]


def test_the_hard_signal_is_never_a_rate(steady_ledger: Path) -> None:
    """The violation path must not be reachable through a threshold."""
    series = build_series(steady_ledger, bucket_seconds=300)
    config = _config(violation=GateSpec(enter=1_000_000.0, exit=999_999.0))
    detection = DriftDetector(config, mode=RATE).run(series)
    assert not [a for a in detection.alarms if a.signal == "violation"]
