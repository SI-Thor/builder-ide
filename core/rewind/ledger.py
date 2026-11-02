"""The ledgers a selection reads.

One row type, three readers:

* :func:`read_world_ledger` — the world's own ledger
  (``agent-world/runtime/world-ledger.sqlite3``): the ``tile.played``,
  ``judge.verdict``, ``tile.authored`` and ``tile.retired`` rows of the
  Minecraft world, read **read-only**;
* :func:`read_core_ledger` — the core's own audit ledger, the same ``audit``
  table written by the recipe store;
* :func:`read_bevy_dump` — a Bevy round log, read through ``lm dump``: the
  decisions the round recorded.

The two SQLite ledgers share a schema but not their attribution, so they are
read by two functions rather than one with a switch:

============  ==========================  ==========================
field         the world's ledger          the core's ledger
============  ==========================  ==========================
``actor``     who wrote the row           who wrote the row
              (``Pebble``, ``judge@d1``)  (``core``, ``magnus``)
``agent``     who the row is *about*      the actor's agent name
              (``context.bot``)           (``actor.agent``)
``id``        the tile or skill id        the subject's entity id
              (``subject.skill``)         (``subject.entity_id``)
``verdict``   ``win``/``lose`` for a play, the judge's choice for a
              verdict, empty otherwise     the payload's verdict
``at``        epoch seconds               epoch seconds
============  ==========================  ==========================

A round log has no dates at all: its time is **ticks**, and a selection that
carries an ISO-8601 literal is refused against it rather than compared with
nonsense.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .selection import EPOCH, TICK

__all__ = [
    "LedgerRow",
    "Ledger",
    "read_world_ledger",
    "read_core_ledger",
    "read_bevy_dump",
    "read_bevy_header",
    "ledger_from_rows",
    "parse_at",
    "EPOCH",
    "TICK",
]


def parse_at(value: str) -> float:
    """An ISO-8601 timestamp from a ledger, as epoch seconds."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


@dataclass(frozen=True)
class LedgerRow:
    """One row of a ledger, as the selection reads it."""

    seq: int
    at: float
    actor: str
    agent: str
    kind: str
    entity_id: str
    verdict: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "actor": self.actor,
            "agent": self.agent,
            "kind": self.kind,
            "id": self.entity_id,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class Ledger:
    """A ledger: its rows, the unit of its time, and where it came from."""

    rows: tuple[LedgerRow, ...]
    time_unit: str = EPOCH
    source: str = ""

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)


def ledger_from_rows(
    rows: Iterable[LedgerRow], *, time_unit: str = EPOCH, source: str = ""
) -> Ledger:
    return Ledger(rows=tuple(rows), time_unit=time_unit, source=source)


# ==================================================================== sqlite


def _connect(path: Path | str) -> sqlite3.Connection:
    """Open a ledger read-only. The reader never writes and never locks."""
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"no ledger at {resolved}")
    return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)


def _read_audit(
    path: Path | str,
    *,
    since_seq: int | None,
    until_seq: int | None,
    types: Sequence[str] | None,
) -> list[tuple[int, str, str, str, str, str]]:
    """The raw rows of an ``audit`` table: seq, at, actor, type, subject, payload."""
    connection = _connect(path)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if since_seq is not None:
            clauses.append("seq > ?")
            params.append(since_seq)
        if until_seq is not None:
            clauses.append("seq <= ?")
            params.append(until_seq)
        if types:
            clauses.append(f"type IN ({','.join('?' * len(types))})")
            params.extend(types)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"SELECT seq, at, actor, type, subject, payload FROM audit{where} ORDER BY seq",
            params,
        ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5])) for r in rows]
    finally:
        connection.close()


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _world_verdict(kind: str, payload: dict[str, Any]) -> str:
    """The verdict of a world row, in the words the world uses.

    A play's verdict is its outcome (``win``, ``lose``, ``partial``); a
    judge's verdict is the tile it chose, or ``refused`` when it refused.
    """
    if kind == "tile.played":
        outcome = payload.get("outcome") or {}
        return str(outcome.get("result") or "")
    if kind == "judge.verdict":
        if payload.get("refused"):
            return "refused"
        judgments = payload.get("judgments") or []
        if not judgments:
            return ""
        distribution = judgments[0].get("distribution") or {}
        if not distribution:
            return str(judgments[0].get("gate") or "")
        # The judge's choice is the tile it put the most weight on.
        return max(distribution.items(), key=lambda item: item[1])[0]
    return ""


def _world_agent(kind: str, payload: dict[str, Any], actor_id: str) -> str:
    """The agent a world row is about, when the row says."""
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
    return actor_id


def read_world_ledger(
    path: Path | str,
    *,
    since_seq: int | None = None,
    until_seq: int | None = None,
    types: Sequence[str] | None = None,
) -> Ledger:
    """The world's ledger, read read-only.

    ``types`` filters the event kinds; ``since_seq`` and ``until_seq`` take
    a range of the ledger's rows. The rows come back in ledger order.
    """
    rows: list[LedgerRow] = []
    for seq, at, actor_text, kind, subject_text, payload_text in _read_audit(
        path, since_seq=since_seq, until_seq=until_seq, types=types
    ):
        actor = _loads(actor_text)
        subject = _loads(subject_text)
        payload = _loads(payload_text)
        actor_id = str(actor.get("id") or "")
        entity_id = (
            subject.get("skill")
            or payload.get("skill_id")
            or subject.get("entity_id")
            or ""
        )
        rows.append(
            LedgerRow(
                seq=seq,
                at=parse_at(at),
                actor=actor_id,
                agent=_world_agent(kind, payload, actor_id),
                kind=kind,
                entity_id=str(entity_id),
                verdict=_world_verdict(kind, payload),
                payload=payload,
            )
        )
    return Ledger(rows=tuple(rows), time_unit=EPOCH, source=str(path))


def read_core_ledger(
    path: Path | str,
    *,
    since_seq: int | None = None,
    until_seq: int | None = None,
    types: Sequence[str] | None = None,
) -> Ledger:
    """The core's own audit ledger, read read-only."""
    rows: list[LedgerRow] = []
    for seq, at, actor_text, kind, subject_text, payload_text in _read_audit(
        path, since_seq=since_seq, until_seq=until_seq, types=types
    ):
        actor = _loads(actor_text)
        subject = _loads(subject_text)
        payload = _loads(payload_text)
        actor_id = str(actor.get("id") or "")
        agent = str(actor.get("agent") or actor_id)
        verdict = (
            payload.get("verdict")
            or payload.get("result")
            or payload.get("outcome")
            or ""
        )
        rows.append(
            LedgerRow(
                seq=seq,
                at=parse_at(at),
                actor=actor_id,
                agent=agent,
                kind=kind,
                entity_id=str(subject.get("entity_id") or ""),
                verdict=str(verdict),
                payload=payload,
            )
        )
    return Ledger(rows=tuple(rows), time_unit=EPOCH, source=str(path))


# ==================================================================== bevy


def _source_name(source: Any) -> str:
    """The name of a decision's source: ``agent:3``, ``human:1``, ``system``."""
    if isinstance(source, dict):
        for kind, value in source.items():
            if kind in ("Agent", "Human"):
                return f"{kind.lower()}:{value}"
            if kind == "System":
                return "system"
    if isinstance(source, str):
        return source.lower()
    return ""


def _kind_of(decision: dict[str, Any]) -> tuple[str, str]:
    """The decision's kind, and the tag inside it.

    ``{"ActionOn": {"GoTo": {...}}}`` is the kind ``ActionOn`` and the tag
    ``GoTo``; ``{"Marker": 7}`` is the kind ``Marker`` and the tag ``7``.
    """
    kind = decision.get("kind")
    if not isinstance(kind, dict) or not kind:
        return "", ""
    name = next(iter(kind))
    inner = kind[name]
    if isinstance(inner, dict) and len(inner) == 1:
        return name, str(next(iter(inner)))
    if isinstance(inner, (str, int, float, bool)):
        return name, str(inner)
    return name, name


def read_bevy_dump(text: str, *, source: str = "") -> Ledger:
    """Read a Bevy round log's decisions, as ``lm dump`` prints them.

    The dump is JSON Lines. The first line may be the round's identity
    (``lm dump --header``); the rest are the decisions, in the order the log
    recorded them. A decision line is
    ``{"arrived": <tick>, "decision": {...}}`` — the format
    ``lm run --inject`` reads, so a dump can be fed straight back.
    """
    rows: list[LedgerRow] = []
    index = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            item = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(item, dict) or "decision" not in item:
            continue  # the header line
        decision = item["decision"]
        if not isinstance(decision, dict):
            continue
        arrived = int(item.get("arrived") or 0)
        apply_tick = int(decision.get("apply_tick") or arrived)
        # The sequencer applies a decision on its own tick when it arrived in
        # time, and on its arrival tick when it was late.
        at = apply_tick if apply_tick >= arrived else arrived
        kind, tag = _kind_of(decision)
        index += 1
        rows.append(
            LedgerRow(
                seq=index,
                at=float(at),
                actor=_source_name(decision.get("source")),
                agent=_source_name(decision.get("source")),
                kind=kind,
                entity_id=tag,
                verdict="",
                payload={
                    "arrived": arrived,
                    "apply_tick": apply_tick,
                    "decision_seq": decision.get("seq"),
                    "decision": decision,
                },
            )
        )
    return Ledger(rows=tuple(rows), time_unit=TICK, source=source)


def read_bevy_header(text: str) -> dict[str, Any]:
    """The round's identity, as ``lm dump --header`` prints it."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            item = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(item, dict) and "decision" not in item:
            return item
    return {}
