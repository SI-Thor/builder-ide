"""The six signals: what each one is computed from, and which two the
world ledger cannot carry.
"""

from __future__ import annotations

from pathlib import Path

from core.drift.config import DriftConfig
from core.drift.ledger import build_series
from core.drift.signals import (
    BuildDriftSignal,
    ErrorSignal,
    SpendSignal,
    StallSignal,
    SuccessSignal,
    ViolationSignal,
    build_signals,
)


def _reference(series) -> tuple[float, float]:
    return (series.reference_start, series.reference_end)


def test_there_are_six_signals_and_they_are_the_ones_the_note_names() -> None:
    names = [signal.name for signal in build_signals()]
    assert names == ["stall", "success", "errors", "violation", "spend", "build"]


def test_two_of_the_six_are_not_computable_from_the_ledger() -> None:
    signals = {signal.name: signal for signal in build_signals()}
    assert signals["violation"].computable is False
    assert signals["build"].computable is False
    assert signals["stall"].computable is True
    assert signals["success"].computable is True
    assert signals["errors"].computable is True
    assert signals["spend"].computable is True
    # The reason is written down, not implied.
    assert signals["build"].reason


def test_the_stall_signal_is_the_gap_over_the_agents_own_median(
    steady_ledger: Path,
) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig()
    points = StallSignal().compute(series, config, _reference(series))
    values = [p.value for p in points if p.value is not None]
    assert values
    # The fixture plays every ten seconds, so the ratio is 1.
    assert all(abs(v - 1.0) < 0.6 for v in values), values


def test_the_stall_signal_rises_when_the_agent_stops(stalled_ledger: Path) -> None:
    series = build_series(stalled_ledger, bucket_seconds=300)
    config = DriftConfig()
    points = StallSignal().compute(series, config, _reference(series))
    by_bucket = {p.at: p.value for p in points if p.scope == "Kite"}
    values = [v for v in by_bucket.values() if v is not None]
    assert max(values) > min(values) * 3, values


def test_the_success_signal_is_the_drop_below_the_agents_own_rate(
    declining_ledger: Path,
) -> None:
    series = build_series(declining_ledger, bucket_seconds=300)
    config = DriftConfig(min_scored_plays=1)
    points = SuccessSignal().compute(series, config, _reference(series))
    values = [p.value for p in points if p.scope == "Kite" and p.value is not None]
    assert values
    # The agent wins for the first half of the run and stops winning in
    # the second. The drop is the reference rate minus this window's
    # rate, so it is negative while the agent beats its own reference
    # and positive once it stops winning.
    assert min(values) <= 0
    assert max(values) > 0
    assert values[-1] > values[0]


def test_an_agent_at_its_own_baseline_has_no_drop(steady_ledger: Path) -> None:
    """Pebble never wins in the fixture, so it is at its own baseline."""
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig(min_scored_plays=1)
    points = SuccessSignal().compute(series, config, _reference(series))
    pebble = [p.value for p in points if p.scope == "Pebble" and p.value is not None]
    assert pebble
    assert all(abs(value) < 1e-9 for value in pebble)


def test_the_success_signal_is_undefined_without_enough_plays(
    steady_ledger: Path,
) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig(min_scored_plays=10_000)
    points = SuccessSignal().compute(series, config, _reference(series))
    assert all(p.value is None for p in points)


def test_the_error_signal_is_the_refusal_rate(refusing_ledger: Path) -> None:
    series = build_series(refusing_ledger, bucket_seconds=300)
    config = DriftConfig()
    points = ErrorSignal().compute(series, config, _reference(series))
    values = [p.value for p in points if p.value is not None]
    assert values
    # The judge answers first and then refuses, so the rate rises from
    # nothing to everything.
    assert min(values) < 0.5
    assert abs(max(values) - 1.0) < 1e-9


def test_the_error_signal_is_undefined_without_enough_verdicts(
    steady_ledger: Path,
) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig(min_verdicts=10_000)
    points = ErrorSignal().compute(series, config, _reference(series))
    assert all(p.value is None for p in points)


def test_the_spend_signal_is_the_cost_per_decision(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig()
    points = SpendSignal().compute(series, config, _reference(series))
    values = [p.value for p in points if p.value is not None]
    assert values
    # Every window of the fixture costs exactly its reference, so the
    # ratio is one.
    assert all(abs(value - 1.0) < 0.5 for value in values), values


def test_the_violation_signal_reads_the_hard_path(violating_ledger: Path) -> None:
    series = build_series(violating_ledger, bucket_seconds=300)
    config = DriftConfig()
    points = ViolationSignal().compute(series, config, _reference(series))
    values = [p.value for p in points if p.value is not None]
    assert values == [1.0]


def test_the_build_signal_has_nothing_to_say(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    config = DriftConfig()
    assert BuildDriftSignal().compute(series, config, _reference(series)) == []
