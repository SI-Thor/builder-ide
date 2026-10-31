"""The heartbeat: the core writes a row for the whole window (§3.4).

The morning's status line is computed from the ledger, not written by whoever
is awake to write it — which is what makes it survive the failure it is
describing. The heartbeat is the input to that computation: a wall-clock row
plus every sealed step, and the gaps between the rows are what a reboot
leaves behind.
"""

from __future__ import annotations

from core.night.heartbeat import Heartbeat, lost_minutes, tick_gaps
from core.night.ledger import InMemoryLedger
from core.night.projection import NightProjection

NIGHT = "night_2026-10-30"


def test_a_tick_is_a_row_in_the_log_carrying_the_wall_clock():
    ledger = InMemoryLedger()
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: "2026-10-30T21:20:00Z")
    event = heartbeat.tick()

    assert event.type == "night.tick"
    assert event.payload == {"at": "2026-10-30T21:20:00Z", "kind": "wall"}
    assert NightProjection(ledger.events()).ticks == [event]


def test_a_sealed_step_is_ticked_with_its_kind():
    ledger = InMemoryLedger()
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: "2026-10-30T21:20:00Z")
    heartbeat.tick(kind="sealed-step", note="pr_0001 sealed")
    assert ledger.events()[0].payload["kind"] == "sealed-step"
    assert ledger.events()[0].payload["note"] == "pr_0001 sealed"


def test_the_gaps_between_ticks_are_measured_in_minutes():
    ledger = InMemoryLedger()
    stamps = iter(["2026-10-30T21:00:00Z", "2026-10-30T21:10:00Z", "2026-10-30T21:40:00Z"])
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: next(stamps))
    heartbeat.tick()
    heartbeat.tick()
    heartbeat.tick()

    assert tick_gaps(NightProjection(ledger.events()).ticks) == [10.0, 30.0]


def test_lost_minutes_count_the_time_past_the_expected_interval():
    """A reboot leaves a hole in the heartbeat; the hole is the lost time."""
    ledger = InMemoryLedger()
    stamps = iter(["2026-10-30T21:00:00Z", "2026-10-30T21:10:00Z", "2026-10-30T22:10:00Z"])
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: next(stamps))
    heartbeat.tick()
    heartbeat.tick()
    heartbeat.tick()

    assert lost_minutes(NightProjection(ledger.events()).ticks) == 50.0


def test_a_clean_night_loses_nothing():
    ledger = InMemoryLedger()
    stamps = iter(["2026-10-30T21:00:00Z", "2026-10-30T21:10:00Z", "2026-10-30T21:20:00Z"])
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: next(stamps))
    heartbeat.tick()
    heartbeat.tick()
    heartbeat.tick()

    assert lost_minutes(NightProjection(ledger.events()).ticks) == 0.0


def test_a_stall_is_ticked_with_the_minutes_it_cost():
    ledger = InMemoryLedger()
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: "2026-10-30T02:12:00Z")
    heartbeat.stall(41.0, note="model-load cap hit")

    event = ledger.events()[0]
    assert event.payload["kind"] == "stall"
    assert event.payload["minutes"] == 41.0


def test_the_batches_starting_late_is_ticked_with_the_delay():
    ledger = InMemoryLedger()
    heartbeat = Heartbeat(ledger, NIGHT, clock=lambda: "2026-10-30T21:44:00Z")
    heartbeat.batches_started(late_minutes=40.0, cause="the client never detached")

    event = ledger.events()[0]
    assert event.payload["kind"] == "batches"
    assert event.payload["late_minutes"] == 40.0
    assert event.payload["cause"] == "the client never detached"
