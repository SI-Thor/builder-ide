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
    # rate, floored at zero: windows at or above the reference read 0
    # (no badness, however the rate moved inside that zone — an
    # improving agent must never alarm), and the decline reads positive
    # once the agent stops winning.
    assert min(values) == 0
    assert max(values) > 0
    assert values[-1] > values[0]


def test_an_agent_above_its_own_reference_has_no_badness(
    declining_ledger: Path,
) -> None:
    """The one-sided floor, at the seam the live world hit.

    Pebble's 2026-11-02 06:45 alarm fired on a *rise from far above the
    reference to slightly above it* — an improving agent, alarmed. The
    floor makes every at-or-above-reference window exactly 0, so the
    rate gate's rise across them is 0 too and cannot fire.
    """
    series = build_series(declining_ledger, bucket_seconds=300)
    config = DriftConfig(min_scored_plays=1)
    points = SuccessSignal().compute(series, config, _reference(series))
    above = [p.value for p in points if p.scope == "Kite" and p.value is not None]
    assert above
    assert all(value >= 0 for value in above)
    assert min(above) == 0


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


# -- the yields: the stall signal forgives a wait the world chose -------------


def test_a_wait_the_world_chose_is_not_a_stall(yielding_ledger: Path) -> None:
    """Two silences, one ledger, and only the yields tell them apart.

    The fixture waits twice: ten minutes with a yield every minute
    (the box busy — the world behaving correctly), then seven minutes
    of unexplained silence. The stall signal must stay quiet across
    the first and rise on the second.
    """
    series = build_series(yielding_ledger, bucket_seconds=300)
    points = StallSignal().compute(series, DriftConfig(), _reference(series))
    kite = {p.at: p.value for p in points if p.scope == "Kite"}
    forgiven = [kite.get(bucket.start) for bucket in series.buckets[0:4]]
    assert all(value is None or value <= 5.0 for value in forgiven), forgiven
    unexplained = [kite.get(bucket.start) for bucket in series.buckets[4:6]]
    assert any(value is not None and value > 5.0 for value in unexplained), unexplained


def test_one_yield_in_the_silence_does_not_excuse_all_of_it(
    stalled_ledger: Path,
) -> None:
    """The excuse is per gap and per window, not a blanket amnesty.

    A single yield point in the middle of a long silence excuses the
    gap it falls inside and the window it falls in — not the windows
    on either side, which stay unexplained.
    """
    from core.drift.ledger import read_plays

    plays = sorted(float(p["at"]) for p in read_plays(stalled_ledger))
    big = max(range(len(plays) - 1), key=lambda i: plays[i + 1] - plays[i])
    mid = (plays[big] + plays[big + 1]) / 2.0
    series = build_series(
        stalled_ledger,
        bucket_seconds=300,
        extra_yields=[{"at": mid, "agent": "Kite"}],
    )
    idles = [
        bucket.agent("Kite").idle_seconds
        for bucket in series.buckets
        if bucket.agent("Kite").plays == 0
    ]
    excused = [value for value in idles if value is None]
    counted = [value for value in idles if value is not None]
    assert len(excused) == 1, "exactly one silent window carries the yield"
    assert counted, "the rest of the silence stays unexplained"
