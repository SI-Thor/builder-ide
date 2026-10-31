"""The week's seats and bridges: one melt ledger, mirrored into the spine.

The M1 session proved the seats against one evening→night→morning. A week
adds exactly one requirement the M1 adapters did not have: **the melt's
ledger must persist across sittings** — every fold (the gate, the sealer)
re-derives from the whole week's rows, not the evening's. So this module
holds:

* **`WeekAsker`** — the cold-start seat's ask-mode over ONE in-memory
  ledger for the whole week. Each evening is a new *session* (the ≤ 6
  budget is per sitting) on the same ledger (the melt is per project).
  Every answered row is mirrored into the spine through the spine's own
  owner-only taste write path, exactly as in M1 — the bridge that
  disappears when the seats share one store.
* **`unprompted_row`** — the owner's unprompted morning verdict, written
  on both sides (seat ledger for the melt, spine for the panels). The tags
  carry no `asked-by:` attribution, which is the point: an unprompted row
  counts toward *every* builder's melt (the gate's rule), and the week uses
  that to prove the melt is per builder.
* **`mirror_seal`** — a bet sealed under the cold-start policy (confidence
  computed, never chosen) mirrored into the spine's prediction ledger so
  the tally the mornings read is the spine's own.
* **`park` / `admit_ask_cards`** — the night's question queue: parking
  under the spine's blocking dam (at most 3; the fourth parks the task),
  and the decision-budget admission (G §4.3 / spec §3.2.8-7): a night that
  would ask more decisions than the morning's budget of 10 is cut AT THE
  QUEUE — the cut tasks are named, never silently dropped.
* **`decisions_since`** — the attention number, counted where the product
  counts it: owner-actor decision events (parked questions answered, work
  orders kept/rejected, branches applied) — per morning, from the ledger.
"""

from __future__ import annotations

import time

from spec_client import CoreDoor, SpecClient, SpecError
from seats.coldstart import AskModeRunner

#: The attention budget: a morning may ask for at most this many decisions
#: (G §4.3; X G6; budgets.py's DECISIONS_PER_MORNING restated for the queue).
DECISION_BUDGET = 10

#: Decision event types, and who must have acted (G §4.3's list: parked
#: questions answered, work orders kept/rejected, branches applied — a
#: kept-yesterday choice is the owner's branch.rejected, also a decision).
_DECISION_TYPES = ("question.answered", "wo.kept", "wo.rejected",
                   "branch.head.moved", "branch.rejected")


class WeekAsker(AskModeRunner):
    """Ask-mode over one ledger for the whole week; a session per evening."""

    def __init__(self, seat, door: CoreDoor,
                 start: str = "2026-10-24T19:58:00Z") -> None:
        # AskModeRunner's own __init__ builds a fresh ledger and a clock fixed
        # at M1's sitting; the week needs both to live as long as the week.
        self._seat = seat
        self._door = door
        self.ledger = seat.stubs.InMemoryLedger()
        self.clock = seat.stubs.SteppingClock(start, step_seconds=1)
        self.mode = seat.AskMode(ledger=self.ledger, clock=self.clock,
                                 author="casey")
        self.session = self.mode.begin_session()
        self.spine_rows: list[dict] = []
        self.skipped: list[str] = []
        self.collapsed: list[dict] = []

    def new_sitting(self):
        """One evening: a fresh session on the same ledger (≤ 6 questions
        per sitting; the melt folds the whole ledger)."""
        self.session = self.mode.begin_session()
        return self.session

    # -- the melt, folded fresh whenever a question is asked ---------------------

    @property
    def gate(self):
        from core.coldstart import ColdStartGate  # materialized by siblings.load()

        return ColdStartGate(self.ledger, author="casey")

    def observations(self, builder: str, code: str) -> tuple[int, int]:
        return self.gate.observations(builder, code)


def unprompted_row(asker: WeekAsker, door: CoreDoor, *, code: str, verdict: str,
                   artifact_ref: str, param_path: str, value: str,
                   words: str | None = None) -> dict:
    """The owner's unprompted verdict — one row, written on both ledgers.

    No `asked-by:` tag rides the row, so the gate counts it toward every
    builder (the ledger is shared and readable; the cold-start seat's rule).
    The spine's copy goes through `TasteService.append_note` — owner actor,
    single writer — which is the three-writer rule on the spine's side.
    """
    seat = asker._seat
    at = asker.clock.now()
    row_id = f"tn_{seat.stubs.short_hash({'at': at, 'code': code, 'artifact': artifact_ref})}"
    row = {
        "id": row_id, "at": at, "author": "casey", "status": "active",
        "subject": {"param_path": param_path, "value": value},
        "artifact_ref": artifact_ref, "verdict": verdict, "reason_code": code,
        "words": words, "tags": ["unprompted:morning"],
    }
    asker.ledger.append(seat.models.AuditEvent(
        seq=0,
        id=f"aud_{seat.stubs.short_hash({'type': 'taste.note.appended', 'row': row_id})}",
        at=at, actor=seat.models.Actor(kind="owner", id="casey"),
        type="taste.note.appended",
        subject={"entity_kind": "taste_note", "entity_id": row_id},
        payload={"row": row},
    ))
    mirrored = door.append_taste_note(
        subject=dict(row["subject"]), artifact_ref=artifact_ref,
        verdict=verdict, reason_code=code, words=words,
        tags=list(row["tags"]),
    )
    return {"row": row, "spine": mirrored.model_dump(mode="json")}


def mirror_seal(spec: SpecClient, sealed, *, branch_ref: str,
                render_spec: dict) -> dict:
    """A bet sealed under the melt's policy, mirrored into the spine.

    The spine's own sealer is deliberately permissive (a guess is always
    legal); the *policy* — which confidence this builder may write on this
    code tonight — is the cold-start seat's, and this mirror carries the
    policy's answer into the one ledger the mornings tally from.
    """
    return spec.seal(
        branch_ref=branch_ref,
        claim=sealed.prediction.claim,
        claim_type=sealed.prediction.claim_type,
        confidence=sealed.confidence,
        basis=sealed.basis,
        render_spec=render_spec,
    )


def mirror_score(asker: WeekAsker, seat_prediction_id: str, verdict: str) -> None:
    """Carry a verdict back into the melt's ledger.

    The spine scores the bet (the Critic for world claims, the owner for
    taste); the cold-start gate's world axis folds `prediction.scored`
    events, so the seat ledger must learn the verdict too — the melt's
    denominators are sealed AND scored bets, and both sides must agree.
    """
    seat = asker._seat
    asker.ledger.append(seat.models.AuditEvent(
        seq=0,
        id=f"aud_{seat.stubs.short_hash({'type': 'prediction.scored', 'pid': seat_prediction_id})}",
        at=asker.clock.now(),
        actor=seat.models.Actor(kind="critic", id="critic-scripted"),
        type="prediction.scored",
        subject={"entity_kind": "prediction", "entity_id": seat_prediction_id},
        payload={"prediction_id": seat_prediction_id, "verdict": verdict},
    ))


def reject_work_order(spec: SpecClient, wo_id: str, *, idem: str | None = None) -> dict:
    """`POST /v1/work-orders/{id}/reject` — the owner's reject (M1's client
    only ever kept; the week's owner rejects by rule, §4.2 has both)."""
    return spec._req("POST", f"/v1/work-orders/{wo_id}/reject", body={}, idem=idem)


def score_taste_bets(door: CoreDoor, branch_id: str, owner_verdict: str) -> list[str]:
    """The owner's apply/reject resolves the night's taste bets (§1.7: the
    owner's keep/apply/reject is the only event that scores them)."""
    predictions = door._svc("predictions")
    return predictions.score_taste_keep_on_branch(
        branch_id, door.api.events.owner_actor("casey"), owner_verdict
    )


def park(spec: SpecClient, name: str, options: list[str], *,
         blocking: bool = True, branch: str | None = None,
         by: str = "companion") -> dict:
    """Park a question under the spine's dam (at most 3 blocking open)."""
    return spec._req("POST", "/v1/questions", by=by,
                     body={"name": name, "options": options,
                           "branch": branch, "blocking": blocking})


def admit_ask_cards(spec: SpecClient, door: CoreDoor, *, cards: list[dict],
                    night_id: str, committed: int,
                    budget: int = DECISION_BUDGET) -> dict:
    """The queue's decision-budget admission (G §4.3; spec §3.2.8-7).

    Each candidate card would become one morning decision. The queue admits
    what fits beside the decisions the night's structure already committed
    (the branch choice, the work-order verdict, the blocking questions the
    dam let stand); the rest is cut AT THE QUEUE — the task goes `cut` with
    the budget named in the reason, so the report says where the cut
    happened and the reader is never the place a 40-card morning lands.
    """
    room = max(0, budget - committed)
    admitted, cut = [], []
    for i, card in enumerate(cards):
        if len(admitted) < room:
            question = park(spec, card["name"], card["options"], blocking=False,
                            branch=f"br_night{card['night']}")
            door.set_task_state(
                card["task"], "parked",
                reason="admitted under the morning's decision budget (10)",
            )
            admitted.append(question["question"]["id"])
        else:
            door.set_task_state(
                card["task"], "cut",
                reason=("cut at the queue — the morning's decision budget is 10 "
                        "(G §4.3); re-queued for tonight"),
            )
            cut.append(card["task"])
    return {"room": room, "admitted": admitted, "cut": cut,
            "night": night_id, "committed": committed}


def decisions_since(door: CoreDoor, since_seq: int) -> list[dict]:
    """The decisions the morning asked of the owner, from the ledger.

    Counted where the product counts them (G §4.3): owner-actor events that
    ask for a verdict — parked questions answered, work orders kept or
    rejected, branches applied or stood down (keep-yesterday). Per morning,
    by seq range — the spine's own three-number line counts a subset of
    these cumulatively across the project (a drift this run records, not a
    budget breach).
    """
    out = []
    for ev in door.raw_events(since_seq, list(_DECISION_TYPES)):
        actor = ev.actor
        kind = actor.get("kind") if isinstance(actor, dict) else getattr(actor, "kind", None)
        who = actor.get("id") if isinstance(actor, dict) else getattr(actor, "id", None)
        if kind != "owner" or who != "casey":
            continue
        out.append({"seq": ev.seq, "type": ev.type, "at": ev.at})
    return out


def timed(fn):
    """A one-shot timer for the per-answer Talk budget (≤ 1.5 s an answer)."""
    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0
