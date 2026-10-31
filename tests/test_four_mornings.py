"""The four-mornings suite (plan M2; core-spec v2 §3.4).

Every morning the product can produce has to be survivable: a power cut, a
foreign job on the GPU all night, a client that never detached, and no plan
at all each produce **the correct status line**, a one-tap recovery and zero
fabricated work (G §7 test 6). The suite runs the simulated nights and
checks those three things, plus that each report renders in the spec's
order.

The four *status values* are the spec's; the suite covers more scenarios
than four because the plan's own four (power cut / foreign job / never
detached / no plan) are not the same four as the brief's (clean / failures /
cut short by the rail / reboot). Between them they cover every morning the
product can wake up to.
"""

from __future__ import annotations

import re

from core.night.nights import (
    all_mornings,
    did_not_run_night,
    the_four_mornings,
)
from core.night.projection import NightProjection


def section_positions(html: str) -> dict[str, int]:
    return {
        match.group(1): match.start()
        for match in re.finditer(r'<section id="([a-z-]+)"', html)
    }


def test_the_four_mornings_cover_the_four_status_values():
    statuses = {night.report.status.status for night in the_four_mornings()}
    assert statuses == {"ran as planned", "ran short", "ran degraded", "did not run"}


def test_the_clean_night_says_ran_as_planned():
    night = the_four_mornings()[0]
    assert night.report.status.status == "ran as planned"
    assert night.report.status.first_line.startswith("ran as planned · ")


def test_a_night_with_failures_says_ran_short_and_names_the_failure():
    night = next(n for n in all_mornings() if n.name == "failures")
    assert night.report.status.status == "ran short"
    assert "hollow mesh" in night.report.status.reason
    assert "hollow mesh" in night.html()


def test_a_night_cut_by_the_bar_says_ran_short_and_names_the_cut():
    night = next(n for n in all_mornings() if n.name == "rail cut")
    assert night.report.status.status == "ran short"
    assert "lane-h of the ask was cut" in night.report.status.reason
    assert night.report.cut, "the cut must be named, not merely counted"


def test_a_night_interrupted_by_a_reboot_says_ran_short_and_names_the_lost_minutes():
    night = next(n for n in all_mornings() if n.name == "reboot")
    assert night.report.status.status == "ran short"
    assert "min lost" in night.report.status.reason
    assert night.report.lost_minutes > 0


def test_a_night_where_the_client_never_detached_says_ran_degraded():
    night = next(n for n in all_mornings() if n.name == "degraded")
    assert night.report.status.status == "ran degraded"
    assert "the ProArt stayed attached" in night.report.status.reason


def test_the_did_not_run_variants_are_three_different_facts():
    off = did_not_run_night("off")
    busy = did_not_run_night("busy")
    no_plan = did_not_run_night("no plan")
    unknown = did_not_run_night("unknown")

    assert off.report.status.variant == "off"
    assert busy.report.status.variant == "busy"
    assert no_plan.report.status.variant == "no plan"
    assert unknown.report.status.variant == "unknown"
    assert unknown.report.status.reason == "unknown (no telemetry)"


def test_every_did_not_run_morning_with_a_plan_re_offers_it_verbatim():
    for variant in ("off", "busy"):
        night = did_not_run_night(variant)
        assert night.report.recovery is not None
        assert "start now" in night.report.recovery
        assert "tonight" in night.report.recovery
        assert "drop it" in night.report.recovery


def test_a_morning_with_no_plan_offers_nothing_to_re_offer():
    assert did_not_run_night("no plan").report.recovery is None


def test_every_report_renders_in_the_specs_order():
    for night in all_mornings():
        positions = section_positions(night.html())
        assert positions["status"] < positions["failures"], night.name
        assert positions["failures"] < positions["cut"], night.name
        assert positions["cut"] < positions["numbers"], night.name
        assert positions["numbers"] < positions["morning"], night.name
        assert positions["morning"] < positions["tally"], night.name
        assert positions["tally"] < positions["three-numbers"], night.name


def test_no_morning_fabricates_work():
    """Every claim on the page must be in the log."""
    for night in all_mornings():
        projection = NightProjection(night.events)
        report = night.report

        logged_tasks = set(projection.tasks)
        assert {task.task_id for task in report.tasks} <= logged_tasks, night.name

        numbers = report.numbers
        assert numbers.kept_critic == len(projection.tasks_in_state("kept")), night.name
        assert numbers.reverted == len(projection.tasks_in_state("reverted")), night.name
        assert numbers.parked == len(projection.tasks_in_state("parked")), night.name
        assert numbers.cut == len(projection.tasks_in_state("cut")), night.name
        assert numbers.sealed_bets == len(projection.predictions), night.name
        assert numbers.gpu_minutes_spent == projection.spend.gpu_minutes, night.name

        for failure in report.failures:
            assert any(
                failure.artifact == logged.get("artifact")
                for logged in projection.failures
            ), night.name


def test_the_status_is_computed_from_the_log_not_narrated():
    """The same log, folded again, gives the same status (the kill -9 property)."""
    for night in all_mornings():
        projection = NightProjection(night.events)
        from core.night.status import compute_status

        assert compute_status(projection).status == night.report.status.status, night.name


def test_the_reports_carry_no_panel_side_state():
    for night in all_mornings():
        html = night.html()
        assert "<script" not in html.lower(), night.name
        assert "onclick" not in html.lower(), night.name
