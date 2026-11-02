from datetime import datetime
from core.precedent import PrecedentStore, Precedent, PrecedentStatus, Validator, VerdictType


def test_append_only():
    store = PrecedentStore()
    p = Precedent(id="p1", gap_id="g1", decision="allow", rationale="test", keys=["test.key"])
    store.append(p)

    assert len(store.all()) == 1
    assert store.get("p1") == p


def test_match_by_key():
    store = PrecedentStore()
    p1 = Precedent(id="p1", gap_id="g1", decision="allow", rationale="ok", keys=["a", "b"], status=PrecedentStatus.ADJUDICATED)
    p2 = Precedent(id="p2", gap_id="g2", decision="deny", rationale="no", keys=["b", "c"], status=PrecedentStatus.ADJUDICATED)
    store.append(p1)
    store.append(p2)

    matches = store.match(["b"])
    assert len(matches) == 2
    matches = store.match(["nonexistent"])
    assert len(matches) == 0


def test_determinism_identical_input():
    store = PrecedentStore()
    p = Precedent(
        id="test", gap_id="gap1", decision="allow", rationale="reason",
        created_at=datetime.fromisoformat("2026-11-01T20:00:00")
    )
    h1 = p.hash()
    h2 = p.hash()
    assert h1 == h2


def test_validator_precedent_override():
    store = PrecedentStore()
    store.append(Precedent(
        id="p1", gap_id="g1", decision="deny", rationale="forbidden", keys=["proposal.upload"],
        status=PrecedentStatus.ADJUDICATED, rule_override="default.allow_upload"
    ))

    v = Validator(store, rules={"default.allow_upload": "uploads are allowed"})
    verdict = v.validate("upload file.pdf", ["proposal.upload", "default.allow_upload"])

    assert verdict.type == VerdictType.DENY
    assert "p1" in verdict.matched_precedents
    assert "default.allow_upload" not in verdict.rule_matches


def test_validator_ask_human_when_no_match():
    store = PrecedentStore()
    v = Validator(store, rules={})
    verdict = v.validate("do new thing", ["unknown.action"])

    assert verdict.type == VerdictType.ASK_HUMAN
