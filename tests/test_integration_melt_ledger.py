"""The melt on one store — what the rewired acceptance run exposed (m1-real).

Both acceptance suites (the M1 session and the seven-night melt week) were
rewritten against the integrated core: the seats' ledgers became the spine's
ONE log through `core.ports.SpineLedgerPort`, the mirrors went away. These
tests hold the defects that removal exposed — each one passed silently while
the second ledger hid it:

* **session ids collided on one store** — `begin_session` hashed only the
  clock, so two sittings at the same moment shared a session and the second
  inherited the first's question budget from the shared `line.spoken` fold;
* **the vocabulary's seal dialect vanished in the spine's fold** — the melt's
  policy seals through the vocabulary's real sealer (flat `sealed_payload`),
  and the spine's predictions projection folded an empty row, so the tally
  grouped every melt bet under ("", "");
* **the gate could not see the spine's scores** — the spine addresses a
  scored prediction through the event subject; the gate read only a payload
  key that isn't there;
* **apply neither scored the night's taste bets nor moved the world** —
  §1.7's "the owner's apply is the only event that scores them" and §1.2's
  head move were both done by the callers, by hand, in adapter code;
* **the three-number line counted the whole project** — "15 decisions
  (budget 10)" by night 7 while no morning asked more than 10 (the
  melt-week README's first finding);
* **a promotion reset the word's capability counter** — `vocab.word.added`
  overwrote the row with `calls: 0` (the README's second finding).
"""
from __future__ import annotations

from core.coldstart import AskMode, ColdStartGate, ColdStartSealer
from core.coldstart.bank import night_one_bank
from core.events import character_actor, core_actor, owner_actor
from core.ports import SpineLedgerPort
from core.svc.nights import NightsService
from core.svc.report import ReportBuilder
from core.svc.vocab import VocabService
from core.vocab.clock import SteppingClock
from core.vocab.predictions import PredictionService
from core.vocab.words import default_entries

from tests.conftest import seed_branch, seed_nodes


def _wire_vocab(core):
    words = default_entries()
    for entry in words:
        VocabService(core).add_word(entry.model_dump(mode="json"), core_actor())
    return words


# ------------------------------------------------- the one ledger, and sessions

def test_two_sittings_at_the_same_clock_moment_are_two_sessions(core):
    """The session id folds in the ledger's head seq: on one store, a fresh
    sitting at a repeated clock moment must not inherit the previous
    sitting's question budget from the shared `line.spoken` fold."""
    ledger = SpineLedgerPort(core.store)
    clock = SteppingClock("2026-10-30T20:12:00Z", step_seconds=0)
    mode = AskMode(ledger=ledger, clock=clock, author="casey")

    first = mode.begin_session()
    asked = mode.ask_next(first, night_one_bank())
    assert type(asked).__name__ == "Asked"
    assert mode.spoken_count(first) == 1

    second = mode.begin_session()  # same clock, new sitting
    assert second.id != first.id
    assert mode.spoken_count(second) == 0


def test_ask_modes_rows_land_in_the_one_log_and_the_panels_read_them(core):
    """The mirror is gone: an answer writes `taste.note.appended` through the
    spine's own store, and the spine's taste projection — what the panels
    read — carries the same row."""
    ledger = SpineLedgerPort(core.store)
    clock = SteppingClock("2026-10-30T20:12:00Z")
    mode = AskMode(ledger=ledger, clock=clock, author="casey")
    session = mode.begin_session()
    outcome = mode.ask_next(session, night_one_bank())
    row = mode.answer(session, outcome.question.id, outcome.question.chips[0].id,
                      actor=owner_actor("casey"))

    events = core.store.events_since(0, types=["taste.note.appended"])
    assert len(events) == 1
    assert events[0].payload["row"]["reason_code"] == row.reason_code
    assert events[0].actor.id == "casey"  # the owner's own tap (§1.7)
    from core.svc.taste import TasteService
    listed = TasteService(core).list(author="casey")
    assert [r["id"] for r in listed] == [row.id]


# ------------------------------------------------- the melt's seals and scores

def test_the_vocabulary_sealer_dialect_folds_into_the_spine_projection(core):
    """The melt's policy seals through the vocabulary's real sealer; the
    spine's fold reads both spellings, so the tally the mornings read groups
    the bets under their real builder × claim type."""
    from core.svc.predictions import PredictionsService

    ledger = SpineLedgerPort(core.store)
    clock = SteppingClock("2026-10-30T23:04:00Z")
    policy = ColdStartSealer(
        ledger=ledger, clock=clock,
        sealer=PredictionService(ledger=ledger, clock=clock))
    sealed = policy.seal_world_bet(
        builder="prop-maker", claim_type="material_read",
        claim="Weathered timber reads as weathered on all 12 crates",
        branch_ref="br_night1@ver_0002",
        render_spec={"rung": 2, "resolution": "480p", "seed": 42})

    doc = core.store.get_row("predictions", {"id": sealed.prediction.id})["payload"]
    assert doc["claim_type"] == "material_read"
    assert doc["builder"] == "prop-maker"
    tally = PredictionsService(core).tally()["tally"] if isinstance(
        PredictionsService(core).tally(), dict) else PredictionsService(core).tally()
    assert any(r["builder"] == "prop-maker" and r["claim_type"] == "material_read"
               for r in tally)

    # the spine scores it; the gate's world axis sees the score through the
    # event's subject (the spine's spelling)
    PredictionsService(core).score_world_from_critic(sealed.prediction.id, "keep")
    gate = ColdStartGate(ledger, author="casey")
    assert gate.world_counts("prop-maker", "material_read") == (1, 1)


# ------------------------------------------------- apply: §1.7 and §1.2

def test_apply_scores_the_nights_taste_bets_and_moves_the_world(client, core):
    """The owner's apply is one transaction: the head move (§5.3), the taste
    bets scored (§1.7), and the store's main following the applied head
    (§1.2) — none of it left to the caller, and no second owner decision in
    the log for the machine's follow-up."""
    from core.records import Prediction
    from core.svc.predictions import PredictionsService

    _wire_vocab(core)
    seed_branch(core, "br_night1", purpose="morning-option", head="ver_0009")

    sealed = PredictionsService(core).seal(
        character_actor("prop-maker"), "br_night1@ver_0009",
        "Weathered timber reads as weathered", "taste_keep", "guess",
        render_spec={"rung": 2, "resolution": "480p", "seed": 42})
    assert isinstance(sealed, Prediction)

    out = client.post("/v1/branches/br_night1/apply", json={},
                      headers={"Authorization": "Bearer dev-token-casey"}).json()
    assert out["taste_bets_scored"] == [sealed.id]  # §1.7, inside the apply
    row = core.store.get_row("predictions", {"id": sealed.id})
    assert row["verdict"] == "hit"

    # the world follows: the spine's apply event is the owner's one decision;
    # the store's follow-up rides a core actor (G §4.3 counts owner events)
    moves = core.store.events_since(0, types=["branch.head.moved"])
    owner_moves = [e for e in moves if e.actor.kind == "owner"]
    assert len(owner_moves) == 1


# ------------------------------------------------- the report's attention line

def test_the_three_number_line_scopes_decisions_to_the_night(core):
    """The melt-week README's first finding, fixed: the attention number
    counts this cycle's owner decisions, not the project's whole history —
    a second night reads its own morning, never night one's."""
    nights = NightsService(core, core.settings)
    first = nights.start(owner_actor("casey"))["night"]["id"]
    core.store.append(core.store.new_event(
        "question.answered", owner_actor("casey"),
        {"entity_kind": "question", "entity_id": "q1"}, {"answer": "yes"}))
    first_line = ReportBuilder(core).build(first)["doc"]["three_number_line"]
    assert first_line["attention_decisions"] == 1

    nights.stop(first, owner_actor("casey"))
    second = nights.start(owner_actor("casey"))["night"]["id"]
    second_line = ReportBuilder(core).build(second)["doc"]["three_number_line"]
    assert second_line["attention_decisions"] == 0  # night one's answer is history


# ------------------------------------------------- capability rows (X C12)

def test_a_promotion_keeps_the_calls_the_word_earned(client, core):
    """The melt-week README's second finding, fixed: `vocab.word.added` at a
    new version no longer resets the capability counter — the row's
    denominator survives its own promotion."""
    words = _wire_vocab(core)
    crates = next(w for w in words if w.word == "props.harbor.crates")
    seed_nodes(core, "br_main", [
        {"node_id": "crates_01", "entry_path": "harbor.crates", "kind": "prop_set"},
    ])
    r = client.post("/v1/vocab/call", headers={
        "Authorization": "Bearer dev-token-propmaker"},
        json={"word": "props.harbor.crates", "node": "crates_01",
              "params": {"count": 6, "style": "weathered", "from_library": 0,
                         "seed": 1}})
    assert r.status_code == 200

    from core.svc.tasks import TasksService
    assert {row["word"]: row["calls"] for row in TasksService(core).capability_rows()
            }["props.harbor.crates"] == 1

    # the keep promotes the word at version 2 (the growth beat, §2.3)
    v2 = crates.model_dump(mode="json")
    params = dict(v2["params"])
    props = dict(params.get("properties", {}))
    props["lids"] = {"type": "boolean", "default": False}
    params["properties"] = props
    VocabService(core).add_word({**v2, "version": 2, "params": params}, core_actor())

    rows = {row["word"]: row for row in TasksService(core).capability_rows()}
    assert rows["props.harbor.crates"]["calls"] == 1
    assert "built 1" in rows["props.harbor.crates"]["line"]
