"""tests for tools/return_screen — the letter, the ask planner, the rewind
preview, the precedent stub, and the visit marker, on a fixture ledger
shaped like the world's (the same four kinds, the same payload fields)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TOOL = REPO / "tools" / "return_screen"
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(REPO))

from letter import render, WORD_LIMIT  # noqa: E402
from ask import plan_expression  # noqa: E402
from precedent_stub import Precedent, PrecedentStatus, PrecedentStore  # noqa: E402
import worldview as wv  # noqa: E402


# ---------------------------------------------------------------- fixture

def make_ledger(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE audit (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        at TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL,
        subject TEXT NOT NULL, payload TEXT NOT NULL)""")
    base = 1793500000.0  # a fixed clock, 2026-11-02-ish
    rows = []

    def actor(aid, kind_, via):
        return json.dumps({"agent": None, "id": aid, "kind": kind_, "via": via})

    seed = actor("seed", "engineer", "cloud_author")
    judge = actor("judge@d1:d1-2B", "core", "judge")
    mediator = actor("mediator", "core", "retire")
    kite = actor("Kite", "character", "reflex")
    sprout = actor("Sprout", "character", "reflex")

    def iso(t):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

    rows.append(("tile.authored", seed, {"skill": "skill_aa", "family": "builder.stone",
                                         "title": "lay a line of cobblestone", "version": 1}))
    # an hour of healthy plays, Kite mostly
    for i in range(30):
        who = kite if i % 3 else sprout
        rows.append(("tile.played", who, {
            "at": iso(base + i * 60), "skill_id": "skill_aa", "outcome": {
                "result": "win" if i % 10 == 0 else "partial"},
            "context": {"bot": "Kite" if who is kite else "Sprout", "humans": 0},
            "cost": {"input_tokens": 0, "gpu_minutes": 0.0, "hosted_cents": 0.0}}))
        rows.append(("judge.verdict", judge, {
            "refused": False, "cost": {"input_tokens": 86, "gpu_minutes": 0.001,
                                       "hosted_cents": 0.0}}))
    # then the judge refuses for a stretch (a >=20-verdict episode, so the
    # precedent rule's floor is met), and a human shows up for a while
    for i in range(24):
        t = base + 3600 + i * 60
        rows.append(("tile.played", kite, {
            "at": iso(t), "skill_id": "skill_aa", "outcome": {"result": "lose"},
            "context": {"bot": "Kite", "humans": 1}, "cost": {}}))
        rows.append(("judge.verdict", judge, {
            "refused": True, "cost": {"input_tokens": 0, "gpu_minutes": 0.0,
                                      "hosted_cents": 0.0}}))
    rows.append(("tile.retired", mediator, {"family": "builder.stone", "skill": "skill_aa",
                                            "reason": "superseded", "plays": 3, "wins": 1}))
    conn.executemany(
        "INSERT INTO audit (id, at, actor, type, subject, payload) VALUES (?, ?, ?, ?, '{}', ?)",
        [(f"aud_{i:05d}", iso(base + i * 30), a, k, json.dumps(p))
         for i, (k, a, p) in enumerate(rows)])
    conn.commit()
    conn.close()


@pytest.fixture()
def view(tmp_path):
    db = tmp_path / "ledger.sqlite3"
    make_ledger(db)
    # the human's last block: before the ledger's first row, so "since" is everything
    player = tmp_path / "player-builds.jsonl"
    player.write_text(json.dumps({"kind": "placed", "pos": "1,2,3", "by": "Casey",
                                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                      time.gmtime(1793499900))}) + "\n")
    return wv.WorldView(db=str(db), player_log=str(player),
                        state_dir=tmp_path / "state", ttl=0)


def test_rows_and_span(view):
    rows = view.rows()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"tile.played", "judge.verdict", "tile.authored", "tile.retired"}
    assert view.span(rows)["rows"] == len(rows)


def test_last_seen_from_player_log(view):
    assert view.last_seen("Casey") == pytest.approx(1793499900, abs=2)
    assert view.last_seen("nobody") is None


def test_snapshot_and_lanes(view):
    snap = view.snapshot("Casey")
    kite = next(l for l in snap["lanes"] if l["actor"] == "Kite")
    judge = next(l for l in snap["lanes"] if l["role"] == "judge")
    assert kite["plays"] == 44  # 20 of the healthy window + 24 of the refusal window
    assert judge["refused"] == 24
    assert judge["refusal_rate"] == 0.444  # 24 of 54 — real episodes dilute too
    assert snap["threshold"]["authored"] == 1
    assert snap["threshold"]["retired"] == 1
    # the refusal episode is rated by its overlap with the window (here: all of it)
    seg = snap["refusals"][0]
    assert seg["refused_in"] == 24 and seg["verdicts_in"] == 24
    # the ledger's last refusal is 30 s before its end — inside the 10-minute
    # merge gap, so the episode counts as still running
    assert seg["still_running"] is True


def test_marks_include_skills_refusals_presence(view):
    snap = view.snapshot("Casey")
    kinds = [m["kind"] for m in snap["marks"]]
    assert "skill.admitted" in kinds
    assert "skill.retired" in kinds
    assert "judge.refusing" in kinds
    assert "human.present" in kinds


def test_letter_within_150_words_one_question(view):
    facts = view.snapshot("Casey")
    letter = render(facts)
    assert letter["within_limit"], letter["word_count"]
    assert letter["word_count"] <= WORD_LIMIT
    assert letter["question"].endswith("?")
    # the fixture's judge refuses only 10 of 40 — not a refusal letter; the
    # surprise is whatever the rules pick next (drift if any alarm fired, else skills)
    assert letter["surprise_kind"] in {"refusal", "drift", "skills"}
    assert letter["paragraphs"], "the letter has a body"


def test_ask_planner_builds_selections():
    now = 1793600000.0
    plan = plan_expression("what did Kite play in the last 3 hours?", now - 7200, now)
    assert "actor in (Kite)" in plan["expression"]
    assert "kind in (tile.played)" in plan["expression"]
    assert "at >= 1793589200" in plan["expression"]

    plan = plan_expression("how did the judge refuse since I left", now - 100, now)
    assert "actor in (judge@d1:d1-2B" in plan["expression"]

    plan = plan_expression("anything about skill_aabbcc11", 0, now)
    assert "id = skill_aabbcc11" in plan["expression"]

    plan = plan_expression("everything", 0, now)
    assert plan["defaulted"] and plan["expression"] == "at >= 0"


def test_ask_answer_pulls_a_slice(view):
    from ask import answer
    result = answer("what did Sprout play?", view, "Casey")
    assert result["by_actor"] == {"Sprout": 10}
    assert result["matched"] < result["of_total_rows"]
    assert result["fraction_of_ledger"] < 0.2
    assert "Sprout (10)" in result["summary"]


def test_rewind_preview_never_deletes_and_names_the_fork(view):
    from rewind_api import preview
    rows = view.rows()
    half = rows[len(rows) // 2]
    out = preview(rows, at_epoch=half["at"], actors=["Kite"], kinds=["tile.played"])
    assert out["point"]["seq"] == half["seq"]
    assert out["kept_by_kind"] == {"tile.played": out["kept"]}
    assert out["kept_by_actor"] == {"Kite": out["kept"]}
    assert out["dropped"] == out["rows_after_point"] - out["kept"]
    assert out["fork"].startswith("rewind/")
    assert "nothing is deleted" in out["guarantee"]


def test_precedent_stub_round_trip(tmp_path):
    store = PrecedentStore(tmp_path / "prec.jsonl")
    p = Precedent(id="prec_1", gap_id="g1", decision="d", rationale="r",
                  keys=["k"], metadata={"options": []})
    store.append(p)
    assert store.get("prec_1").status == PrecedentStatus.PROPOSED
    assert store.pending() and store.pending()[0].id == "prec_1"
    ruled = store.adjudicate("prec_1", "keep_bandit", "Casey", "because")
    assert ruled.status == PrecedentStatus.ADJUDICATED
    assert ruled.metadata["ruling"] == "keep_bandit"
    assert not store.pending()
    assert store.match(["k"]) and store.match(["k"])[0].id == "prec_1"
    assert store.adjudicate("prec_1", "x", "y") is None  # already ruled
    # one JSONL line per event, append-only
    assert len((tmp_path / "prec.jsonl").read_text().splitlines()) == 2


def test_precedent_seed_only_asks_what_the_ledger_justifies(view, tmp_path):
    import precedent_stub as ps
    store = PrecedentStore(tmp_path / "prec.jsonl")
    snap = view.snapshot("Casey")
    # the fixture's absence overlapped one >=50% episode of >=20 verdicts: ask once
    seeded = ps.seed_questions(store, snap)
    assert len(seeded) == 1
    assert seeded[0].keys == ["judge-refusal", "fallback-policy"]
    assert seeded[0].gap_id.startswith("judge-refusal@")
    assert "still refusing" in seeded[0].decision  # the episode is inside the merge gap
    assert ps.seed_questions(store, snap) == []  # never re-asked per episode
    # a ledger with no overlapping episode asks nothing
    snap["refusals"] = []
    assert ps.seed_questions(store, snap) == []


def test_visits_are_written_and_read(view):
    view.state_dir.mkdir(parents=True, exist_ok=True)
    with (view.state_dir / "visits.jsonl").open("a") as fh:
        fh.write(json.dumps({"at": "2026-11-02T02:00:00Z", "human": "Casey"}) + "\n")
    assert view.last_seen("Casey") == pytest.approx(
        wv.parse_at("2026-11-02T02:00:00Z"), abs=2)
    kinds = [m["kind"] for m in view.marks(view.rows(), None)]
    assert "visit.opened" in kinds
