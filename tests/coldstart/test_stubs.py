"""The stubs keep the rules the real seats owe (spec §1.0, §1.8, §5.1).

These tests pin the in-memory seams to their contracts so that swapping in
the real `core-api` ledger and the real `vocab` sealer is a replacement, not
a rewrite: gapless sequence, append-only idempotency, sealed-before-render
ordering, and the taste fold's payload shape.
"""

from __future__ import annotations

import pytest

from core.coldstart import Actor, AuditEvent, InMemoryLedger, content_hash, taste_rows_from_events
from core.coldstart.stubs import LedgerError, PredictionSealer, SteppingClock, canonical_json


def _event(n: int, type_: str = "night.tick", **payload) -> AuditEvent:
    payload = {"n": n, **payload}
    return AuditEvent(
        seq=0,
        id=f"aud_{n:04d}",
        at=f"2026-10-24T20:{n // 60:02d}:{n % 60:02d}Z",
        actor=Actor(kind="core", id="test"),
        type=type_,
        subject={"entity_kind": "test", "entity_id": str(n)},
        payload=payload,
    )


class TestTheLedger:
    def test_sequence_is_monotone_and_gapless(self):
        ledger = InMemoryLedger()
        for n in range(5):
            committed = ledger.append(_event(n))
            assert committed.seq == n + 1
        assert [e.seq for e in ledger.events()] == [1, 2, 3, 4, 5]

    def test_append_only_the_same_event_twice_is_one_event(self):
        ledger = InMemoryLedger()
        first = ledger.append(_event(1))
        again = ledger.append(_event(1))
        assert again.seq == first.seq
        assert ledger.head_seq() == 1

    def test_a_reused_id_with_a_different_payload_is_refused(self):
        ledger = InMemoryLedger()
        ledger.append(_event(1))
        with pytest.raises(LedgerError, match="duplicate_event_id"):
            ledger.append(_event(1, state="running"))

    def test_a_render_job_may_not_precede_its_seal(self):
        """§5.1 — the ordering that makes a sealed bet unforgeable."""
        ledger = InMemoryLedger()
        with pytest.raises(LedgerError, match="prediction_not_sealed"):
            ledger.append(_event(1, type_="job.enqueued", prediction_id="pr_missing"))
        # a job with no prediction attached is fine (the calibration batch's CPU jobs)
        ledger.append(_event(2, type_="job.enqueued", lane="cpu"))
        assert ledger.head_seq() == 1

    def test_find_matches_the_most_recent_payload(self):
        ledger = InMemoryLedger()
        ledger.append(_event(1, type_="night.tick", state="running"))
        ledger.append(_event(2, type_="night.tick", state="running"))
        ledger.append(_event(3, type_="night.tick", state="stopping"))
        found = ledger.find("night.tick", state="running")
        assert found is not None and found.payload["n"] == 2


class TestCanonicalHashing:
    def test_sorted_keys_no_whitespace(self):
        assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'

    def test_content_hash_is_stable_and_prefixed(self):
        assert content_hash({"seed": 4471}).startswith("sha256:")
        assert content_hash({"seed": 4471}) == content_hash({"seed": 4471})
        assert content_hash({"seed": 4471}) != content_hash({"seed": 12})


class TestTheTasteFold:
    def test_rows_read_back_out_of_the_payload_shape(self, ledger, write_row):
        row = write_row(reason_code="wrong_material", verdict="reject")
        folded = taste_rows_from_events(ledger.events())
        assert len(folded) == 1
        assert folded[0].id == row.id
        assert folded[0].reason_code == "wrong_material"
        assert folded[0].kept is False
        assert folded[0].param_path == "harbor.crates"


class TestTheSealer:
    def test_a_seal_commits_before_any_render_can_exist(self, ledger):
        clock = SteppingClock("2026-10-24T20:44:00Z")
        sealer = PredictionSealer(ledger=ledger, clock=clock)
        prediction = sealer.seal(
            builder="architect",
            claim="you keep the jetty layout",
            claim_type="taste_keep",
            confidence="guess",
            basis="0 observations",
            branch_ref="br_night1@ver_0001",
            reason_code="too_clean",
        )
        assert prediction.seal_hash.startswith("sha256:")
        sealed = ledger.find("prediction.sealed", prediction_id=prediction.id)
        assert sealed is not None
        assert sealed.payload["reason_code"] == "too_clean"
        assert sealed.payload["sealed_payload"]["confidence"] == "guess"

    def test_unknown_claim_types_are_refused(self, ledger):
        sealer = PredictionSealer(ledger=ledger, clock=SteppingClock())
        with pytest.raises(Exception, match="claim_type_unknown"):
            sealer.seal(
                builder="architect",
                claim="x",
                claim_type="vibe",
                confidence="guess",
                basis="0 observations",
                branch_ref="br_x@ver_1",
            )
