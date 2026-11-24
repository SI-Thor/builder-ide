"""The world's log of record, written through builder-ide's core store.

The world used to keep its own ledger: a SQLite file with an ``audit``
table, written by the world's own copy of the append protocol. That file
is the world's, so builder-ide could not see it — the morning report and
the "why" door read builder-ide's log, and the Minecraft builders' 70,000
-odd decisions were not in it.

This module is the seam. It offers the world's ledger the one door
builder-ide already has — :class:`core.store.LedgerStore`, the store of
record — behind the same protocol every other seat codes against
(:class:`core.tiles.ports.LedgerPort`), so the world's rows land in
builder-ide's log with their type, their actor and their payload intact.

Two things the seam has to get right, and both are about **not losing
the subject**:

* The core store persists a subject as two columns, ``subject_kind`` and
  ``entity_id`` (:meth:`core.store.LedgerStore._append_tx`). Any other key
  is dropped on the way in. The world's own subject shape was
  ``{"skill": ..., "family": ...}``, so written as it stood the skill id
  would have been silently discarded and every row would have come back
  with an empty subject. :func:`core_subject` is the shape that survives.
* The core store refuses a payload over 4 KiB by **spilling** it to
  artifacts/ and hash-referencing it, where the world's own ledger raised
  instead. That is the better behaviour and it is kept.

The reader at the bottom of this module reads the core store's own schema
back, so the "why" door — builder-ide's rewind seat, which explains a row
— can be pointed at the store the world writes to.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from core.canon import new_id, now_utc
from core.records import Actor, AuditEvent

__all__ = [
    "CoreStoreLedger",
    "core_subject",
    "read_core_store_ledger",
    "WORLD_ENTITY_KIND",
]

#: What a world's skill is called in builder-ide's log: a **tile**. The
#: world's skills and builder-ide's tiles are the same record (see
#: :mod:`agent_world_reflex.tiles`), so one name is used everywhere.
WORLD_ENTITY_KIND = "tile"


def core_subject(entity_id: str, *, kind: str = WORLD_ENTITY_KIND) -> dict[str, Any]:
    """The subject shape the core store keeps.

    The core store holds ``entity_kind`` and ``entity_id`` and nothing
    else; every other key is dropped when the row is written
    (:meth:`core.store.LedgerStore._append_tx`). Anything else a caller
    wants to say about the row belongs in the payload, where it is read
    back.
    """
    return {"entity_kind": kind, "entity_id": str(entity_id)}


class CoreStoreLedger:
    """builder-ide's log of record, behind the world's ledger protocol.

    This is the same shape as :class:`core.svc.recipes.SpineRecipeLedger`
    — the recipe seat's bridge into the core store — with one addition:
    the events are read back in **pages**, because the core store's
    ``events_since`` caps a read at 10,000 rows and a silent cap on a log
    of record is a lie about the log.
    """

    #: How many rows one read asks for. The core store's own default is
    #: 10,000; the pages are read until the log runs out.
    PAGE = 10000

    def __init__(self, store: Any) -> None:
        self._store = store

    # -- the protocol ------------------------------------------------------

    def append(
        self,
        *,
        type: str,
        actor: Actor,
        subject: dict[str, Any],
        payload: dict[str, Any],
        artifact: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> AuditEvent:
        """Append one event and return it as committed."""
        event = AuditEvent(
            id=new_id("audit"),
            at=at or now_utc(),
            actor=actor,
            type=type,
            subject=subject,
            payload=payload,
            artifact=artifact,
        )
        committed, _ = self._store.append(event)
        return committed

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        """The committed events, oldest first, optionally filtered."""
        wanted = list(types) if types is not None else None
        out: list[AuditEvent] = []
        cursor = int(since_seq or 0)
        while True:
            page = self._store.events_since(cursor, types=wanted, limit=self.PAGE)
            if not page:
                break
            out.extend(page)
            cursor = page[-1].seq
            if len(page) < self.PAGE:
                break
        return out

    def last_seq(self) -> int:
        """The highest sequence number written."""
        return int(self._store.max_seq())

    # -- the store itself ---------------------------------------------------

    @property
    def store(self) -> Any:
        """The core store this ledger writes into."""
        return self._store


def read_core_store_ledger(
    path: Path | str,
    *,
    since_seq: int | None = None,
    until_seq: int | None = None,
    types: Sequence[str] | None = None,
) -> Any:
    """Read the core store's log back, as the rewind seat reads a ledger.

    The core store's ``audit`` table holds the subject in two columns, so
    the rows are re-joined here into the shape
    :class:`core.rewind.ledger.LedgerRow` expects. The result is a
    :class:`core.rewind.ledger.Ledger`, which is what the selection and
    the "why" door take.

    The database is opened **read-only** (``mode=ro``): the world may be
    running, and a reader never locks it.
    """
    from core.rewind.ledger import Ledger, LedgerRow
    from core.rewind.ledger import EPOCH, parse_at

    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"no ledger at {resolved}")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if since_seq is not None:
            clauses.append("seq > ?")
            params.append(int(since_seq))
        if until_seq is not None:
            clauses.append("seq <= ?")
            params.append(int(until_seq))
        if types:
            clauses.append(f"type IN ({','.join('?' * len(types))})")
            params.extend(types)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            "SELECT seq, at, actor, type, subject_kind, subject_id, payload "
            f"FROM audit{where} ORDER BY seq",
            params,
        ).fetchall()
    finally:
        connection.close()

    out: list[LedgerRow] = []
    for seq, at, actor_text, kind, subject_kind, subject_id, payload_text in rows:
        actor = _loads(actor_text)
        payload = _loads(payload_text)
        actor_id = str(actor.get("id") or "")
        out.append(
            LedgerRow(
                seq=int(seq),
                at=parse_at(str(at)),
                actor=actor_id,
                agent=_agent_of(kind, payload, actor),
                kind=str(kind),
                entity_id=str(subject_id or ""),
                verdict=_verdict_of(kind, payload),
                payload=payload,
            )
        )
    return Ledger(rows=tuple(out), time_unit=EPOCH, source=str(resolved))


def _loads(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return dict(text)
    try:
        value = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _agent_of(kind: str, payload: dict[str, Any], actor: dict[str, Any]) -> str:
    """Who the row is *about* — the world's builder, or the actor."""
    if kind == "tile.played":
        context = payload.get("context") or {}
        bot = context.get("bot")
        if bot:
            return str(bot)
    if kind == "judge.verdict":
        judgments = payload.get("judgments") or []
        for judgment in judgments:
            qid = judgment.get("qid")
            if qid:
                return str(qid)
    return str(actor.get("agent") or actor.get("id") or "")


def _verdict_of(kind: str, payload: dict[str, Any]) -> str:
    """What the row decided, in the words the selection reads."""
    if kind == "tile.played":
        outcome = payload.get("outcome") or {}
        return str(outcome.get("result") or "")
    if kind == "judge.verdict":
        judgments = payload.get("judgments") or []
        for judgment in judgments:
            answer = judgment.get("answer")
            if answer:
                return str(answer)
    return str(payload.get("verdict") or payload.get("result") or "")
