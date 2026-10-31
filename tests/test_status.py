"""The status line — computed from the ledger, never narrated (§3.4).

The four values are the spec's: ``ran as planned``, ``ran short``, ``ran
degraded``, ``did not run``. The last one has three variants, because from
the owner's chair they are three different facts: **off**, **busy** and **no
plan** — dark ≠ asleep ≠ busy, stated in words, never colour alone.

Nothing here is written by the night runner; it is read out of the log, so it
survives the failure it is describing (§3.4, §5.4).
"""

from __future__ import annotations

from core.night.status import compute_status


def test_a_night_that_never_started_and_had_no_plan_says_did_not_run_no_plan(night):
    status = compute_status(night.projection())
    assert status.status == "did not run"
    assert status.variant == "no plan"
    assert status.reason == "no plan was started."


def test_a_night_that_never_started_but_had_a_plan_says_the_box_was_off(night):
    night.task("task_0001", at="2026-10-30T20:45:00Z", state="slated", night=None)
    status = compute_status(night.projection())
    assert status.status == "did not run"
    assert status.variant == "off"
    assert "nothing was lost" in status.reason
    assert "unstarted" in status.reason


def test_a_night_with_no_ticks_says_unknown_and_never_guesses(night):
    night.start()
    status = compute_status(night.projection())
    assert status.status == "did not run"
    assert status.variant == "unknown"
    assert status.reason == "unknown (no telemetry)"


def test_a_lane_held_by_a_foreign_job_all_night_says_busy(night):
    night.start()
    night.preflight(lane_free=False, proposal="start late")
    night.tick("2026-10-30T21:20:00Z")
    night.tick("2026-10-30T21:30:00Z")
    status = compute_status(night.projection())
    assert status.status == "did not run"
    assert status.variant == "busy"
    assert "queued and was never admitted" in status.reason


def test_a_clean_night_says_ran_as_planned(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.task("task_0001")
    night.task_state("task_0001", "kept", at="2026-10-30T21:40:00Z")
    status = compute_status(night.projection())
    assert status.status == "ran as planned"
    assert "nothing failed" in status.reason


def test_a_clean_night_with_two_parked_questions_says_so(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.task("task_0001")
    night.task_state("task_0001", "kept", at="2026-10-30T21:40:00Z")
    night.task("task_0002")
    night.task_state("task_0002", "parked", at="2026-10-30T21:50:00Z", reason="waiting on Casey")
    night.task("task_0003")
    night.task_state("task_0003", "parked", at="2026-10-30T21:50:00Z", reason="waiting on Casey")
    status = compute_status(night.projection())
    assert status.status == "ran as planned"
    assert status.reason == "nothing failed · 2 parked"


def test_a_night_with_a_hard_failure_says_ran_short(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.task("task_0001")
    night.task_state("task_0001", "reverted", at="2026-10-30T21:40:00Z")
    night.ledger.append(
        type="job.done",
        actor=night.ledger.events()[0].actor,
        subject={"entity_kind": "job", "entity_id": "job_0001"},
        payload={
            "job_id": "job_0001",
            "task_id": "task_0001",
            "outcome": "failed",
            "reason": "hollow mesh from the image-to-3D model",
            "artifact": "artifacts/ab/ab1234.png",
        },
    )
    status = compute_status(night.projection())
    assert status.status == "ran short"
    assert "hollow mesh" in status.reason


def test_a_night_cut_by_the_bar_says_ran_short_and_names_the_cut(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.task("task_0001", cost_estimate={"gpu_minutes": 102.0, "hosted_cents": 0, "wall_minutes": 90.0})
    night.task_state(
        "task_0001",
        "cut",
        at="2026-10-30T22:00:00Z",
        reason="the north-lantern batch did not fit under the bar",
    )
    status = compute_status(night.projection())
    assert status.status == "ran short"
    assert "1.7 lane-h of the ask was cut" in status.reason
    assert "re-queued for tonight" in status.reason


def test_a_night_that_stalled_on_the_lane_says_ran_degraded(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.tick("2026-10-30T02:12:00Z", kind="stall", minutes=41.0, note="model-load cap hit")
    night.task("task_0001")
    night.task_state("task_0001", "kept", at="2026-10-30T02:30:00Z")
    status = compute_status(night.projection())
    assert status.status == "ran degraded"
    assert "stalled 41 min" in status.reason
    assert "nothing failed outright" in status.reason


def test_batches_that_started_late_after_the_deadline_say_ran_degraded(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.tick("2026-10-30T21:30:00Z")
    night.tick("2026-10-30T21:40:00Z")
    night.tick(
        "2026-10-30T21:44:00Z",
        kind="batches",
        late_minutes=40.0,
        cause="the ProArt stayed attached",
    )
    night.task("task_0001")
    night.task_state("task_0001", "kept", at="2026-10-30T22:00:00Z")
    status = compute_status(night.projection())
    assert status.status == "ran degraded"
    assert "40 min late" in status.reason
    assert "the ProArt stayed attached" in status.reason


def test_scripted_only_verdicts_make_the_night_degraded_not_short(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    night.verdict(degraded=True)
    status = compute_status(night.projection())
    assert status.status == "ran degraded"
    assert "scripted-only" in status.reason


def test_a_reboot_says_ran_short_and_names_the_lost_minutes(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T01:00:00Z")
    night.tick("2026-10-30T01:10:00Z")
    night.tick("2026-10-30T02:10:00Z")
    status = compute_status(night.projection())
    assert status.status == "ran short"
    assert "50 min lost" in status.reason


def test_the_first_line_renders_in_the_specs_shape(night):
    night.start()
    night.preflight()
    night.tick("2026-10-30T21:20:00Z")
    status = compute_status(night.projection())
    assert status.first_line == "ran as planned · nothing failed"


def test_the_first_line_uses_an_em_dash_for_the_other_three_statuses(night):
    night.start()
    night.preflight(lane_free=False, proposal="start late")
    night.tick("2026-10-30T21:20:00Z")
    status = compute_status(night.projection())
    assert status.first_line.startswith("did not run — ")
