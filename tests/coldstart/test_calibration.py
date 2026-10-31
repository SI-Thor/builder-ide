"""The calibration batch: seeded defects, nightly growth, the FP/FN table (§1.9, §3.5).

Plan item 12's pass condition — "the reference set's FP/FN table publishes
its first row" — is what these tests hold up, together with the properties
that make the row mean anything: the members are deterministic, the defects
are planted and known, the growth is sized to the unused lane and never
duplicates, every verdict wears `verdict@scripted` on its face, and the
table is a fold over the audit log.
"""

from __future__ import annotations

from collections import Counter

from core.coldstart import (
    CALIBRATION_QUEUE_POSITION,
    COST_PER_MEMBER,
    TARGET_REFERENCE_SET,
    CalibrationService,
    Rail,
    ReferenceMember,
    ScriptedChecks,
    calibration_table,
    grow_reference_set,
    plan_nightly_growth,
    seed_members,
)
from core.coldstart.stubs import content_hash


class TestTheReferenceSet:
    def test_members_are_deterministic_in_index_and_seed(self):
        assert seed_members(12) == seed_members(12)

    def test_ids_are_unique(self):
        members = seed_members(30)
        assert len({m.id for m in members}) == 30

    def test_the_rotation_covers_all_three_defects_plus_clean(self):
        counts = Counter(m.defect or "clean" for m in seed_members(12))
        assert counts == {
            "hollow_mesh": 3,
            "wrong_scale": 3,
            "broken_constraint": 3,
            "clean": 3,
        }

    def test_planted_defects_sit_beyond_the_checks_thresholds(self):
        for member in seed_members(12):
            checks = {r.check: r.fired for r in ScriptedChecks().run(member)}
            if member.defect is None:
                assert not any(checks.values()), member.id
            else:
                targeted = {
                    "hollow_mesh": "watertight",
                    "wrong_scale": "scale_bounds",
                    "broken_constraint": "constraint",
                }[member.defect]
                assert checks[targeted] is True, member.id
                others = [fired for name, fired in checks.items() if name != targeted]
                assert not any(others), member.id  # one planted defect, one signal

    def test_a_borderline_defect_sits_just_inside_the_threshold(self):
        members = seed_members(12, borderline_every=6)
        graded = [m for m in members if m.defect == "wrong_scale" and not m.detectable]
        assert len(graded) == 1
        assert 0.85 <= graded[0].params["scale_ratio"] <= 1.15  # the check cannot see it


class TestNightlyGrowth:
    def test_sized_to_the_unused_lane(self):
        ceiling = Rail(wall_minutes=480.0)
        # 3 wall-minutes left at [e] 0.5 per member → 6 members
        assert plan_nightly_growth(existing=0, ceiling=ceiling, spent=Rail(wall_minutes=477.0)) == 6
        # a rich lane grows by the night cap, not beyond it
        assert plan_nightly_growth(existing=0, ceiling=ceiling, spent=Rail()) == 8
        # nothing left, nothing grown
        assert plan_nightly_growth(existing=0, ceiling=ceiling, spent=Rail(wall_minutes=479.8)) == 0

    def test_the_set_stops_at_its_target(self):
        assert (
            plan_nightly_growth(
                existing=TARGET_REFERENCE_SET, ceiling=Rail(wall_minutes=480.0), spent=Rail()
            )
            == 0
        )

    def test_a_zero_cost_axis_does_not_bind(self):
        # CPU-lane scripted checks cost no GPU-minutes by design
        assert COST_PER_MEMBER.gpu_minutes == 0.0
        assert (
            plan_nightly_growth(
                existing=0,
                ceiling=Rail(gpu_minutes=0.0, wall_minutes=4.0),
                spent=Rail(),
            )
            == 8
        )

    def test_the_batch_is_the_queues_third_item(self):
        assert CALIBRATION_QUEUE_POSITION == 3

    def test_growth_never_duplicates_an_existing_member(self):
        night_one = grow_reference_set(
            [], night="night_2026-10-24", ceiling=Rail(wall_minutes=4.0), spent=Rail()
        )
        assert len(night_one) == 8
        night_two = grow_reference_set(
            list(night_one), night="night_2026-10-25", ceiling=Rail(wall_minutes=2.0), spent=Rail()
        )
        assert len(night_two) == 4
        assert not {m.id for m in night_one} & {m.id for m in night_two}
        assert all(m.night == "night_2026-10-25" for m in night_two)


class TestTheBatchRun:
    def test_each_member_is_a_cpu_job_and_a_scripted_verdict(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        members = seed_members(4)
        verdicts = service.run_batch(members, night="night_2026-10-24")
        assert len(verdicts) == 4
        jobs = ledger.events(types=["job.enqueued"])
        assert len(jobs) == 4
        assert all(job.payload["lane"] == "cpu" for job in jobs)
        assert all(
            event.payload["label"] == "verdict@scripted"
            and event.payload["degraded"] == "scripted"
            for event in verdicts
        )
        # the ground truth rides in the event: the fold needs nothing else
        assert all("planted" in event.payload for event in verdicts)


class TestTheTable:
    def test_a_clean_batch_publishes_its_first_row(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        members = seed_members(12)
        service.run_batch(members, night="night_2026-10-24")
        table, event = service.publish(night="night_2026-10-24")

        by_check = {row.check: row.counts for row in table.rows}
        assert by_check["watertight"].tp == 3 and by_check["watertight"].tn == 3
        assert by_check["scale_bounds"].tp == 3 and by_check["scale_bounds"].tn == 3
        assert by_check["constraint"].tp == 3 and by_check["constraint"].tn == 3
        assert table.totals.fn == 0 and table.totals.fp == 0
        assert table.in_band  # the baseline: exact on its own synthetic set
        assert all(row.label == "verdict@scripted" for row in table.rows)

        # publishing is a content-addressed artifact, not a promise (§1.0)
        assert event.artifact is not None
        assert event.artifact["sha256"] == content_hash(table.as_dict())
        assert event.artifact["bytes"] > 0

    def test_the_table_is_a_fold_over_the_ledger_alone(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        service.run_batch(seed_members(12), night="night_2026-10-24")
        folded = calibration_table(ledger.events(), night="night_2026-10-24")
        published = service.publish(night="night_2026-10-24")[0]
        assert folded == published  # kill -9, rebuild, same row

    def test_a_missed_seed_is_an_honest_false_negative(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        # index 5 is a severity-graded wrong_scale the check cannot see
        service.run_batch(
            seed_members(12, borderline_every=6), night="night_2026-10-24"
        )
        table = calibration_table(ledger.events(), night="night_2026-10-24")
        scale = {row.check: row.counts for row in table.rows}["scale_bounds"]
        assert scale.tp == 2 and scale.fn == 1
        assert scale.fn_rate == 1 / 3
        assert not table.in_band  # "catch the seeded defects" is the band

    def test_a_fired_check_on_a_clean_member_is_a_false_positive(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        lying_clean = ReferenceMember(
            id="ref_fp_probe",
            index=99,
            defect=None,  # ground truth: clean
            params={"hollow": True, "scale_ratio": 1.0, "load_factor": 2.0},
            seed=1,
            night="night_2026-10-24",
        )
        members = [lying_clean, *seed_members(3, start_index=100)]
        service.run_batch(members, night="night_2026-10-24")
        table = calibration_table(ledger.events(), night="night_2026-10-24")
        watertight = {row.check: row.counts for row in table.rows}["watertight"]
        # one clean member rejected: fp 1 of 1 clean — far outside the band
        assert watertight.fp == 1 and watertight.tn == 0
        assert watertight.fp_rate == 1.0
        assert not table.in_band

    def test_nights_do_not_bleed_into_each_other(self, ledger, clock):
        service = CalibrationService(ledger=ledger, clock=clock)
        service.run_batch(seed_members(4), night="night_2026-10-24")
        service.run_batch(
            seed_members(4, start_index=4, borderline_every=3), night="night_2026-10-25"
        )
        first = calibration_table(ledger.events(), night="night_2026-10-24")
        second = calibration_table(ledger.events(), night="night_2026-10-25")
        assert first.totals != second.totals
        assert second.night == "night_2026-10-25"
