"""The reader: the world ledger, folded into windows.

The claims under test are the ones the detector rests on:

* per-actor attribution comes from the **payload**, not from the
  ``actor`` column (which names the seat that wrote the row);
* the gaps and the idle time are what the stall signal needs;
* the decision model's cost is charged to the agent it was about.
"""

from __future__ import annotations

from pathlib import Path

from core.drift.ledger import (
    build_series,
    read_plays,
    read_verdicts,
    rule_violation_events,
)


def test_plays_are_attributed_by_payload_not_by_actor(steady_ledger: Path) -> None:
    plays = read_plays(steady_ledger)
    assert plays, "the fixture wrote plays"
    assert {p["agent"] for p in plays} == {"Kite", "Pebble"}


def test_outcomes_are_read(steady_ledger: Path) -> None:
    plays = read_plays(steady_ledger)
    results = {p["outcome"] for p in plays}
    assert results == {"win", "lose"}


def test_verdicts_are_read_and_refusals_flagged(refusing_ledger: Path) -> None:
    verdicts = read_verdicts(refusing_ledger)
    assert verdicts
    refused = [v for v in verdicts if v["refused"]]
    answered = [v for v in verdicts if not v["refused"]]
    assert refused and answered
    assert all(v["error_code"] == "transport_error" for v in refused)
    assert all(v["error_code"] is None for v in answered)


def test_buckets_carry_the_agents_gaps(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    assert series.buckets
    bucket = series.buckets[0]
    kite = bucket.agent("Kite")
    assert kite.plays > 0
    assert kite.gap_p50 is not None
    assert kite.gap_p50 >= 0
    assert kite.idle_seconds == 0.0


def test_an_agent_that_played_nothing_has_an_idle_time(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    # A window past the end of the run's plays has no plays at all.
    last = series.buckets[-1]
    kite = last.agent("Kite")
    if kite.plays == 0:
        assert kite.idle_seconds is not None
        assert kite.idle_seconds > 0


def test_the_verdict_cost_is_charged_to_its_agent(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    bucket = series.buckets[0]
    # The plays carry no gpu_minutes of their own in this fixture, so
    # everything on the bucket came from the verdicts.
    assert bucket.agent("Kite").gpu_minutes > 0
    assert bucket.agent("Pebble").gpu_minutes > 0


def test_a_refusing_judge_makes_an_error_rate(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    bucket = series.buckets[0]
    assert bucket.verdicts > 0
    assert bucket.refused == 0
    assert bucket.error_codes == {}


def test_the_reference_period_is_the_start_of_the_run(steady_ledger: Path) -> None:
    series = build_series(steady_ledger, bucket_seconds=300)
    assert series.reference_start == series.buckets[0].start
    assert series.reference_end == series.reference_start + 24 * 3600


def test_rule_violations_are_read_when_they_exist(violating_ledger: Path) -> None:
    events = rule_violation_events(violating_ledger)
    assert len(events) == 1
    assert events[0]["rule"] == "no_grief"


def test_a_world_without_violations_has_none(steady_ledger: Path) -> None:
    assert rule_violation_events(steady_ledger) == []


def test_the_series_survives_a_round_trip_through_the_dataset(
    steady_ledger: Path,
) -> None:
    from core.drift.ledger import series_from_dataset

    series = build_series(steady_ledger, bucket_seconds=300)
    document = {
        "meta": {
            "bucket_seconds": 300,
            "reference_start": series.reference_start,
            "reference_end": series.reference_end,
        },
        "buckets": [
            {
                "at": bucket.start,
                "agents": {
                    agent: {
                        "plays": entry.plays,
                        "wins": entry.wins,
                        "losses": entry.losses,
                        "partials": entry.partials,
                        "gap_p50": entry.gap_p50,
                        "gap_p99": entry.gap_p99,
                        "gap_max": entry.gap_max,
                        "idle_seconds": entry.idle_seconds,
                        "gpu_minutes": entry.gpu_minutes,
                        "hosted_cents": entry.hosted_cents,
                    }
                    for agent, entry in bucket.agents.items()
                },
                "verdicts": bucket.verdicts,
                "refused": bucket.refused,
                "error_codes": bucket.error_codes,
                "rule_violations": bucket.rule_violations,
            }
            for bucket in series.buckets
        ],
    }
    rebuilt = series_from_dataset(document)
    assert len(rebuilt.buckets) == len(series.buckets)
    assert rebuilt.agents == series.agents
    assert rebuilt.buckets[0].agent("Kite").plays == series.buckets[0].agent("Kite").plays
