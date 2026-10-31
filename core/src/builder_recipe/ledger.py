"""The ledger seam — the audit log the recipe store writes into.

The API half (half A) owns the real ledger: SQLite in WAL mode with
``synchronous=FULL``, written by a single writer process, with a gapless
``seq`` that is the resume cursor (§1.0, §5.1). The recipe store codes
against the small protocol below and nothing more.

Two implementations live here:

* :class:`InMemoryLedger` — tests and short-lived processes;
* :class:`SQLiteLedger` — a conforming reference stub of half A's ledger.
  It exists so durability and the branch-flip timing can be *measured* on this
  box rather than asserted. Half A replaces it with the real one.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from builder_recipe.canonical import canonical_bytes
from builder_recipe.events import EVENT_TYPES
from builder_recipe.models import Actor, AuditEvent

__all__ = ["Ledger", "InMemoryLedger", "SQLiteLedger", "MAX_PAYLOAD_BYTES"]

#: §1.8 — payload ≤ 4 KiB; anything bigger goes to artifacts/ and is hash-referenced.
MAX_PAYLOAD_BYTES = 4096


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@runtime_checkable
class Ledger(Protocol):
    """Append-only log of audit events."""

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
        """Append one event and return it. The change is durable on return."""

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        """The log, oldest first, optionally filtered."""

    def last_seq(self) -> int:
        """The highest sequence number written."""


def _check(type: str, payload: dict[str, Any]) -> None:
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown audit event type: {type!r}")
    size = len(canonical_bytes(payload))
    if size > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"audit payload is {size} bytes; the cap is {MAX_PAYLOAD_BYTES} — "
            "anything bigger belongs in artifacts/ and is hash-referenced"
        )


class InMemoryLedger:
    """An append-only ledger held in memory."""

    def __init__(self, clock=_utcnow) -> None:
        self._events: list[AuditEvent] = []
        self._clock = clock

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
        _check(type, payload)
        seq = len(self._events) + 1
        event = AuditEvent(
            seq=seq,
            id=f"aud_{seq:04d}",
            at=at or self._clock(),
            actor=actor,
            type=type,
            subject=subject,
            payload=payload,
            artifact=artifact,
        )
        self._events.append(event)
        return event

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        wanted = set(types) if types else None
        return [
            event
            for event in self._events
            if (since_seq is None or event.seq > since_seq)
            and (wanted is None or event.type in wanted)
        ]

    def last_seq(self) -> int:
        return len(self._events)


class SQLiteLedger:
    """A conforming stub of the API half's ledger.

    WAL + ``synchronous=FULL``: the change is fsynced before the append
    returns, which is what makes a sealed bet unforgeable (§5.1).
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS audit (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        type TEXT NOT NULL,
        subject TEXT NOT NULL,
        payload TEXT NOT NULL,
        artifact TEXT
    );
    """

    def __init__(self, path: Path | str, clock=_utcnow) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute(self._SCHEMA)

    # -- pragmas (for the durability test) --------------------------------

    def journal_mode(self) -> str:
        return str(self._connection.execute("PRAGMA journal_mode").fetchone()[0])

    def synchronous(self) -> int:
        return int(self._connection.execute("PRAGMA synchronous").fetchone()[0])

    def close(self) -> None:
        self._connection.close()

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
        _check(type, payload)
        cursor = self._connection.execute(
            "INSERT INTO audit (id, at, actor, type, subject, payload, artifact) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "",
                at or self._clock(),
                json.dumps(actor.model_dump(), sort_keys=True),
                type,
                json.dumps(subject, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                json.dumps(artifact, sort_keys=True) if artifact else None,
            ),
        )
        seq = int(cursor.lastrowid or 0)
        event_id = f"aud_{seq:04d}"
        self._connection.execute("UPDATE audit SET id = ? WHERE seq = ?", (event_id, seq))
        return AuditEvent(
            seq=seq,
            id=event_id,
            at=at or self._clock(),
            actor=actor,
            type=type,
            subject=subject,
            payload=payload,
            artifact=artifact,
        )

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if since_seq is not None:
            clauses.append("seq > ?")
            params.append(since_seq)
        if types:
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"type IN ({placeholders})")
            params.extend(types)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT seq, id, at, actor, type, subject, payload, artifact FROM audit{where} "
            "ORDER BY seq",
            params,
        ).fetchall()
        return [
            AuditEvent(
                seq=row[0],
                id=row[1],
                at=row[2],
                actor=Actor.model_validate(json.loads(row[3])),
                type=row[4],
                subject=json.loads(row[5]),
                payload=json.loads(row[6]),
                artifact=json.loads(row[7]) if row[7] else None,
            )
            for row in rows
        ]

    def last_seq(self) -> int:
        row = self._connection.execute("SELECT MAX(seq) FROM audit").fetchone()
        return int(row[0] or 0)
