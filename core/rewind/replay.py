"""Replay-kept: the kept events, replayed onto a fork, merged, conflicts parked.

The cherry-pick of §2.5, in four steps:

1. **Fork at the point.** A branch of the canon is cut at the rewind point.
   The canon's own branch does not move: a rewind is a fork, never a
   deletion.
2. **Select.** The events after the point are run through the selection
   expression. The ones that match are kept; the ones that do not are
   dropped, each with the reason it was dropped.
3. **Replay the kept.** The kept work — the ops of the edits that were
   committed — is applied to the fork's document. That document is the
   *theirs* of the merge: the world that would have been, had only the kept
   work happened.
4. **Merge.** The three-way merge (base = the point, ours = the canon now,
   theirs = the replayed fork) produces the cherry-picked document. A
   conflict is **parked**, never guessed: the merge refuses, the question
   goes to the ledger, and the fork stays where it was.

Nothing here moves the canon's head. The cherry-pick lands on the fork,
where the human can look at it; moving ``main`` is the owner's separate,
later step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from core.recipe.edits import apply_ops, diff_recipes
from core.recipe.errors import EditRejected, RecipeError
from core.recipe.merge import Conflict, three_way_merge
from core.recipe.models import Actor, Branch, Op, Recipe
from core.recipe.store import RecipeStore

from .fork import RewindPoint, fork_at_point, main_branch
from .ledger import LedgerRow, ledger_from_rows
from .report import Outcome, Parked, RewindReport
from .selection import Selection, select

__all__ = [
    "CherryPick",
    "QuestionSink",
    "LedgerQuestions",
    "cherry_pick",
    "replay_kept",
    "events_to_ledger",
]


class QuestionSink(Protocol):
    """Where a conflict parks its question (the recipe store's own shape)."""

    def park(
        self, *, name: str, branch: str, options: list[str], detail: str
    ) -> str: ...


class LedgerQuestions:
    """Parks a question in the ledger of record.

    The API half's question store is the store's own sink; this one writes
    the same ``question.parked`` event straight to the ledger, so the
    parking is visible to anything that folds the log — and to the next
    agent that picks the seat up.
    """

    def __init__(self, store: RecipeStore, actor: Actor, clock=None) -> None:
        self.store = store
        self.actor = actor
        self.clock = clock or (lambda: store.clock())
        self.parked: list[str] = []

    def park(
        self, *, name: str, branch: str, options: list[str], detail: str
    ) -> str:
        index = len(self.parked) + 1
        question_id = f"q_{index:04d}"
        self.store.ledger.append(
            type="question.parked",
            actor=self.actor,
            at=self.clock(),
            subject={"entity_kind": "question", "entity_id": question_id},
            payload={
                "id": question_id,
                "name": name,
                "branch": branch,
                "options": list(options),
                "blocking": True,
                "asked_by": self.actor.model_dump(mode="json"),
                "answer": None,
                "answered_at": None,
                "assumption": None,
                "detail": detail,
            },
        )
        self.parked.append(question_id)
        return question_id


@dataclass
class CherryPick:
    """What one cherry-pick did."""

    fork: Branch
    point: RewindPoint
    selection: Selection
    kept: tuple[Outcome, ...] = ()
    dropped: tuple[Outcome, ...] = ()
    parked: tuple[Parked, ...] = ()
    merged: Recipe | None = None
    conflicts: tuple[Conflict, ...] = ()
    version: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def merged_cleanly(self) -> bool:
        """True when the merge had no conflict to park."""
        return not self.conflicts

    def report(self, *, source: str = "") -> RewindReport:
        return RewindReport(
            source=source,
            point=f"{self.point.version} (seq {self.point.seq})",
            selection=self.selection.text,
            kept=self.kept,
            dropped=self.dropped,
            parked=self.parked,
            notes=self.notes,
        )


def events_to_ledger(events: Sequence[Any]) -> Any:
    """The core's audit events as a ledger the selection can read."""
    rows: list[LedgerRow] = []
    for event in events:
        actor = event.actor
        actor_dict = (
            actor.model_dump() if hasattr(actor, "model_dump") else dict(actor or {})
        )
        payload = dict(event.payload or {})
        subject = dict(event.subject or {})
        actor_id = str(actor_dict.get("id") or "")
        verdict = (
            payload.get("verdict")
            or payload.get("result")
            or payload.get("outcome")
            or ""
        )
        rows.append(
            LedgerRow(
                seq=int(event.seq or 0),
                at=_epoch_of(event.at),
                actor=actor_id,
                agent=str(actor_dict.get("agent") or actor_id),
                kind=event.type,
                entity_id=str(subject.get("entity_id") or ""),
                verdict=str(verdict),
                payload=payload,
            )
        )
    return ledger_from_rows(rows, source="the core's audit ledger")


def _epoch_of(text: str) -> float:
    from .ledger import parse_at

    return parse_at(text)


def replay_kept(
    store: RecipeStore, *, point: RewindPoint, selection: Selection
) -> tuple[list[Op], dict[int, str], list[Outcome], list[Outcome]]:
    """The kept work, as ops on the fork's document.

    Returns the ops, the reason each kept event carries, the kept outcomes
    and the dropped outcomes.
    """
    events = store.ledger.events(since_seq=point.seq)
    ledger = events_to_ledger(events)
    result = select(ledger, selection)

    committed = {
        event.payload.get("edit")
        for event in events
        if event.type == "version.committed"
    }
    kept_seqs = set(result.kept_seqs)
    ops: list[Op] = []
    reasons: dict[int, str] = {}
    for event in events:
        seq = int(event.seq or 0)
        if seq not in kept_seqs:
            continue
        if event.type == "edit.proposed":
            edit_id = event.payload.get("edit")
            if edit_id not in committed:
                reasons[seq] = "the edit was never committed, so it carries no work"
                continue
            event_ops = [
                Op.model_validate(op) for op in event.payload.get("ops", []) or []
            ]
            ops.extend(event_ops)
            reasons[seq] = f"carried {len(event_ops)} ops"
        elif event.type == "version.committed":
            reasons[seq] = "records the version the kept work produced"
        else:
            reasons[seq] = "kept; it changes no document"

    kept_outcomes = tuple(
        Outcome(
            seq=int(row.seq),
            at=str(row.payload.get("at") or ""),
            actor=row.actor,
            kind=row.kind,
            kept=True,
            reason=reasons.get(int(row.seq), "kept"),
        )
        for row in result.kept
    )
    dropped_outcomes = tuple(
        Outcome(
            seq=int(row.seq),
            at=str(row.payload.get("at") or ""),
            actor=row.actor,
            kind=row.kind,
            kept=False,
            reason=reason,
        )
        for row, reason in result.dropped
    )
    return ops, reasons, list(kept_outcomes), list(dropped_outcomes)


def cherry_pick(
    store: RecipeStore,
    *,
    point: RewindPoint,
    selection: Selection,
    actor: Actor,
    name: str = "rewind-keep",
    questions: QuestionSink | None = None,
    commit: bool = True,
) -> CherryPick:
    """Keep some of the work that happened after a point; drop the rest.

    The result is a fork of the canon at the point, holding the cherry-picked
    document when the merge was clean. A conflict is parked: the question
    goes to the ledger, the merge does not happen, and the canon does not
    move.
    """
    version = store.get_version(point.version)
    ops, reasons, kept, dropped = replay_kept(
        store, point=point, selection=selection
    )
    fork = fork_at_point(store, version=point.version, name=name, actor=actor)
    base = store.get_document(point.version)

    parked: list[Parked] = []
    notes: list[str] = []

    try:
        theirs = apply_ops(base, ops)
    except EditRejected as exc:
        detail = f"the kept work does not stand alone on the fork: {exc}"
        parked.append(
            Parked(
                name="kept-work-does-not-stand-alone",
                branch=fork.id,
                options=("keep", "drop"),
                detail=detail,
            )
        )
        _park(store, questions, actor, fork.id, parked[-1])
        return CherryPick(
            fork=fork,
            point=point,
            selection=selection,
            kept=tuple(kept),
            dropped=tuple(dropped),
            parked=tuple(parked),
            notes=tuple(notes),
        )

    main = main_branch(store, version.recipe)
    ours = store.get_document(main.head)
    merged_document, conflicts = three_way_merge(
        base.model_dump(), ours.model_dump(), theirs.model_dump()
    )

    if conflicts:
        detail = ", ".join(conflict.path for conflict in conflicts)
        question = Parked(
            name="merge-conflict",
            branch=fork.id,
            options=("ours", "theirs"),
            detail=detail,
        )
        parked.append(question)
        _park(store, questions, actor, fork.id, question)
        notes.append(
            "the merge had a conflict; the fork stayed at the point and the "
            "canon did not move"
        )
        return CherryPick(
            fork=fork,
            point=point,
            selection=selection,
            kept=tuple(kept),
            dropped=tuple(dropped),
            parked=tuple(parked),
            conflicts=tuple(conflicts),
            notes=tuple(notes),
        )

    merged = Recipe.model_validate(merged_document)
    new_version: str | None = None
    if commit:
        ops_to_apply = diff_recipes(base, merged)
        if ops_to_apply:
            try:
                committed = store.apply_edit(
                    base=fork.head,
                    ops=ops_to_apply,
                    author=actor,
                    message=f"cherry-pick: keep these ({selection.text})",
                    branch=fork.id,
                )
                new_version = committed.id
            except (EditRejected, RecipeError) as exc:
                question = Parked(
                    name="pre-flight-refused",
                    branch=fork.id,
                    options=("keep", "drop"),
                    detail=str(exc),
                )
                parked.append(question)
                _park(store, questions, actor, fork.id, question)
                notes.append("the pre-flight refused the cherry-picked document")

    return CherryPick(
        fork=fork,
        point=point,
        selection=selection,
        kept=tuple(kept),
        dropped=tuple(dropped),
        parked=tuple(parked),
        merged=merged,
        version=new_version,
        notes=tuple(notes),
    )


def _park(
    store: RecipeStore,
    questions: QuestionSink | None,
    actor: Actor,
    branch: str,
    question: Parked,
) -> None:
    """Park a question where the store can see it."""
    sink = questions or getattr(store, "questions", None)
    if sink is None:
        sink = LedgerQuestions(store, actor)
    sink.park(
        name=question.name,
        branch=question.branch or branch,
        options=list(question.options),
        detail=question.detail,
    )
