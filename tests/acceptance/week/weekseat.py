"""The week's seats and adapters — over the ONE store, now.

The M1 session proved the seats against one evening→night→morning; a week
added the requirement that **the melt's ledger persist across sittings**.
Both were true before the seats merged at the cost of a second ledger and
three mirrors; on the integrated core (`core.*`, one SQLite log) they are
true by construction:

* **`WeekAsker`** — the cold-start seat's ask-mode over the spine's ONE
  ledger (`core.ports.SpineLedgerPort` through the door). Each evening is a
  new *session* (the ≤ 6 budget is per sitting) on the same ledger (the
  melt is per project); every answered row lands in the log directly — the
  taste mirror is gone, the panels read the same rows the gate folds.
* **`unprompted_row`** — the owner's unprompted morning verdict, one write
  into the one log. The tags carry no `asked-by:` attribution, which is the
  point: an unprompted row counts toward *every* builder's melt (the
  gate's rule), and the week uses that to prove the melt is per builder.
* **the melt's seal policy** (`ColdStartSealer` over the vocabulary's real
  sealer) writes its `prediction.sealed` straight into the one log — the
  predictions mirror is gone; the spine's fold reads the vocabulary's
  spelling (§4's third dialect, unified at the read site).
* **`park` / `admit_ask_cards`** — the night's question queue: parking
  under the spine's blocking dam (at most 3; the fourth parks the task),
  and the decision-budget admission (G §4.3 / spec §3.2.8-7). The dam is
  the spine's own; the admission is still the adapter's half — the queue
  service that would enforce the budget AT the queue is the named missing
  piece (§3.2.8-7's builder).
* **`decisions_since`** — the attention number, counted where the product
  counts it: owner-actor decision events (parked questions answered, work
  orders kept/rejected, branches applied or stood down) — per morning, by
  seq range. The spine's own three-number line now scopes to the night the
  same way (the melt-week run's finding, fixed in `core/svc/report.py`);
  this count stays because it is the run's own independent statement.
"""

from __future__ import annotations

import time

from spec_client import CoreDoor, SpecClient, SpecError
from seats.coldstart import AskModeRunner, spine_ledger

#: The attention budget: a morning may ask for at most this many decisions
#: (G §4.3; X G6; budgets.py's DECISIONS_PER_MORNING restated for the queue).
DECISION_BUDGET = 10

#: Decision event types, and who must have acted (G §4.3's list: parked
#: questions answered, work orders kept/rejected, branches applied — a
#: kept-yesterday choice is the owner's branch.rejected, also a decision).
_DECISION_TYPES = ("question.answered", "wo.kept", "wo.rejected",
                   "branch.head.moved", "branch.rejected")


class WeekAsker(AskModeRunner):
    """Ask-mode over the ONE ledger for the whole week; a session per evening."""

    def __init__(self, seat, door: CoreDoor,
                 start: str = "2026-10-24T19:58:00Z") -> None:
        # AskModeRunner's own __init__ builds a fresh sitting at M1's fixed
        # clock; the week needs the sitting to start when its evenings do.
        self._seat = seat
        self._door = door
        self.ledger = spine_ledger(door)
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
        from core.coldstart import ColdStartGate

        return ColdStartGate(self.ledger, author="casey")

    def observations(self, builder: str, code: str) -> tuple[int, int]:
        return self.gate.observations(builder, code)


def unprompted_row(asker: WeekAsker, door: CoreDoor, *, code: str, verdict: str,
                   artifact_ref: str, param_path: str, value: str,
                   words: str | None = None) -> dict:
    """The owner's unprompted verdict — one row, one write, one log.

    No `asked-by:` tag rides the row, so the gate counts it toward every
    builder (the ledger is shared and readable; the cold-start seat's rule).
    The write is the owner-actor `taste.note.appended` the three-writer rule
    demands (§1.7) — the same event ask-mode's answers write.
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
    committed = asker.ledger.append(seat.models.AuditEvent(
        seq=0,
        id=f"aud_{seat.stubs.short_hash({'type': 'taste.note.appended', 'row': row_id})}",
        at=at, actor=seat.models.Actor(kind="owner", id="casey"),
        type="taste.note.appended",
        subject={"entity_kind": "taste_note", "entity_id": row_id},
        payload={"row": row},
    ))
    return {"row": row, "spine": committed.payload["row"]}


def reject_work_order(spec: SpecClient, wo_id: str, *, idem: str | None = None) -> dict:
    """`POST /v1/work-orders/{id}/reject` — the owner's reject (M1's client
    only ever kept; the week's owner rejects by rule, §4.2 has both)."""
    return spec._req("POST", f"/v1/work-orders/{wo_id}/reject", body={}, idem=idem)


def score_taste_bets(door: CoreDoor, branch_id: str, owner_verdict: str) -> list[str]:
    """The owner's standing exit (keep yesterday) resolves the night's taste
    bets (§1.7: the owner's keep/apply/reject is the only event that scores
    them). The apply path scores inside the spine's own apply; there is no
    reject-branch endpoint yet, so the owner's reject is scored through the
    spine's own service here — the named missing piece."""
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
    by seq range — the same scope the spine's three-number line now uses.
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
