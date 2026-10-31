"""The store of record: one SQLite database, WAL mode, synchronous=FULL,
written by a single writer process (§1.0, §5.1).

Write path (§5.1), one transaction per state change:
  append the audit row → spill oversized payloads to artifacts → apply the
  fold to projections → record the idempotency key → COMMIT (fsync).
Side effects (bus notifications, seats, jobs) happen only after commit.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactStore
from .canon import canonical_json, new_id, now_utc
from .errors import ValidationError
from .events import MAX_PAYLOAD_BYTES, AuditEvent, spill_payload
from .fold import FoldContext, apply_event, fold_all, stores_equal
from .projections import (
    FOLD_TABLES,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    SqliteRowStore,
)


class EventBus:
    """Post-commit nudge for SSE. The DB is the only source of truth (the
    feed is the log); the stream polls the ledger and uses this only to
    wake early, so it stays correct across processes and restarts."""

    def __init__(self) -> None:
        self._cond = threading.Condition()

    def notify(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def wait(self, timeout: float) -> None:
        with self._cond:
            self._cond.wait(timeout)


class LedgerStore:
    def __init__(self, db_path: str | Path, artifacts: ArtifactStore,
                 kid_actors: frozenset[str] = frozenset({"magnus"})):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = artifacts
        self.kid_actors = kid_actors
        self._write_lock = threading.RLock()
        # isolation_level=None puts the driver in autocommit mode: it never
        # opens a transaction on our behalf, so the BEGIN/COMMIT pairs below
        # are the *only* transaction boundaries. In the driver's default
        # legacy mode an implicit transaction can be left open by any stray
        # write, and `append()` — which commits only when it opened the
        # transaction itself — would silently never commit (the data would
        # roll back at close). §5.1 wants one transaction per state change,
        # and that means owning them exactly.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._configure()
        self.rows = SqliteRowStore(self.conn)
        self.ctx = FoldContext(artifacts=artifacts, kid_actors=kid_actors)
        self.bus = EventBus()

    # ------------------------------------------------------------- lifecycle

    def _configure(self) -> None:
        cur = self.conn
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.executescript(SCHEMA_SQL)
        cur.commit()
        if self._meta("schema_version") is None:
            self._set_meta("schema_version", SCHEMA_VERSION)

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, str(value))
        )

    def close(self) -> None:
        with self._write_lock:
            self.conn.close()

    # ------------------------------------------------------------- reads

    def max_seq(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq),0) AS s FROM audit").fetchone()
        return int(row["s"])

    def fold_seq(self) -> int:
        return int(self._meta("fold_seq") or 0)

    def events_since(self, since_seq: int, types: list[str] | None = None,
                     limit: int = 10000) -> list[AuditEvent]:
        sql = "SELECT * FROM audit WHERE seq > ?"
        args: list[Any] = [since_seq]
        if types:
            sql += f" AND type IN ({','.join('?' for _ in types)})"
            args += list(types)
        sql += " ORDER BY seq ASC LIMIT ?"
        args.append(limit)
        return [self._row_to_event(r) for r in self.conn.execute(sql, args)]

    def events_for(self, entity_kind: str, entity_id: str,
                   types: list[str] | None = None) -> list[AuditEvent]:
        sql = "SELECT * FROM audit WHERE subject_kind=? AND subject_id=?"
        args: list[Any] = [entity_kind, entity_id]
        if types:
            sql += f" AND type IN ({','.join('?' for _ in types)})"
            args += list(types)
        sql += " ORDER BY seq ASC"
        return [self._row_to_event(r) for r in self.conn.execute(sql, args)]

    def count_events(self, types: list[str], since_at: str | None = None,
                     actor_id: str | None = None, payload_where: str = "",
                     payload_args: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS c FROM audit WHERE type IN ({','.join('?' for _ in types)})"
        args: list[Any] = list(types)
        if since_at:
            sql += " AND at >= ?"
            args.append(since_at)
        if actor_id:
            sql += " AND actor LIKE ?"
            args.append(f'%\"id\": \"{actor_id}\"%')
        if payload_where:
            sql += f" AND {payload_where}"
            args += list(payload_args)
        return int(self.conn.execute(sql, args).fetchone()["c"])

    def get_event(self, event_id: str) -> AuditEvent | None:
        row = self.conn.execute("SELECT * FROM audit WHERE id=?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def _row_to_event(self, row: sqlite3.Row) -> AuditEvent:
        payload = json.loads(row["payload"])
        artifact = json.loads(row["artifact"]) if row["artifact"] else None
        return AuditEvent(
            seq=int(row["seq"]), id=row["id"], at=row["at"],
            actor=json.loads(row["actor"]), type=row["type"],
            subject={"entity_kind": row["subject_kind"] or "", "entity_id": row["subject_id"] or ""},
            payload=payload, artifact=artifact, refused=bool(row["refused"]),
        )

    # ------------------------------------------------------------- entity reads

    def get_row(self, table: str, pk: dict) -> dict | None:
        row = self.rows.get(table, pk)
        if row is None:
            return None
        out = dict(row)
        if isinstance(out.get("payload"), str):
            out["payload"] = json.loads(out["payload"])
        return out

    def scan(self, table: str) -> list[dict]:
        out = []
        for row in self.rows.scan(table):
            r = dict(row)
            if isinstance(r.get("payload"), str):
                r["payload"] = json.loads(r["payload"])
            out.append(r)
        return out

    # ------------------------------------------------------------- the write path

    def idem_get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT status, response FROM idempotency WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        return {"__replay__": True, "status": row["status"], "body": json.loads(row["response"])}

    def append(
        self,
        event: AuditEvent,
        *,
        idem_key: str | None = None,
        response_builder: Callable[[AuditEvent], Any] | None = None,
    ) -> tuple[AuditEvent, Any]:
        """Commit one state change: audit row + fold + idempotency in ONE
        transaction (or join the caller's open batch()). Returns (committed
        event with seq, response). Raises StaleTransition (rolled back,
        nothing committed)."""
        event.validate_type()
        if event.payload_bytes() > MAX_PAYLOAD_BYTES:
            slim, spill = spill_payload(event)
            if spill:
                self.artifacts.put(spill["data"], "event.payload")
                event.payload = slim
                event.artifact = spill["descriptor"]
            else:  # defense in depth: spill refused to shrink below cap
                raise ValidationError(
                    f"payload over {MAX_PAYLOAD_BYTES} bytes even after spill"
                )
        with self._write_lock:
            began = not self.conn.in_transaction
            if began:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                result = self._append_tx(event, idem_key, response_builder)
                if began:
                    self.conn.execute("COMMIT")
            except Exception:
                if began and self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
        if began:
            self.bus.notify()
        return result

    def _append_tx(self, event: AuditEvent, idem_key: str | None,
                   response_builder: Callable[[AuditEvent], Any] | None) -> tuple[AuditEvent, Any]:
        if idem_key is not None:
            hit = self.conn.execute(
                "SELECT status, response FROM idempotency WHERE key=?", (idem_key,)
            ).fetchone()
            if hit:
                return event, {"__replay__": True, "status": hit["status"],
                               "body": json.loads(hit["response"])}
        cur = self.conn.execute(
            "INSERT INTO audit(id, at, actor, type, subject_kind, subject_id,"
            " payload, artifact, refused) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                event.id, event.at, canonical_json(event.actor.model_dump()),
                event.type, event.subject.get("entity_kind", ""),
                event.subject.get("entity_id", ""), canonical_json(event.payload),
                canonical_json(event.artifact) if event.artifact else None,
                1 if event.refused else 0,
            ),
        )
        seq = cur.lastrowid
        event.seq = seq
        apply_event(event, self.rows, self.ctx)
        self._set_meta("fold_seq", str(seq))
        response = None
        if idem_key is not None and response_builder is not None:
            response = response_builder(event)
            self.conn.execute(
                "INSERT INTO idempotency(key, event_id, status, response, at)"
                " VALUES(?,?,?,?,?)",
                (idem_key, event.id, 200, canonical_json(response), now_utc()),
            )
        return event, response

    @contextmanager
    def batch(self):
        """A multi-event operation commits as ONE transaction (§1.7: the
        promotion is one core transaction; §5.1: one transaction per state
        change). Appends inside the batch join it; the idempotency row
        written by the last append commits atomically with all of them."""
        with self._write_lock:
            began = not self.conn.in_transaction
            if began:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                if began:
                    self.conn.execute("COMMIT")
            except Exception:
                if began and self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
        if began:
            self.bus.notify()

    def append_refused(self, event: AuditEvent) -> AuditEvent:
        """Commit a refusal (edges are the story) without any projection
        change. Used for out-of-schema calls, kid free text, stale CAS."""
        event.refused = True
        event, _ = self.append(event)
        return event

    # ------------------------------------------------------------- taste erasure

    def erase_taste_author(self, author: str, actor_json: dict, compensating: AuditEvent,
                           idem_key: str | None = None) -> AuditEvent:
        """§1.0's single immutability exception: redact one author's taste
        payloads AND append the compensating taste.erased event in ONE
        transaction; the fold excludes the redacted rows everywhere."""
        with self._write_lock:
            began = not self.conn.in_transaction
            if began:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                if idem_key is not None:
                    hit = self.conn.execute(
                        "SELECT status, response FROM idempotency WHERE key=?", (idem_key,)
                    ).fetchone()
                    if hit:
                        if began:
                            self.conn.execute("ROLLBACK")
                        return compensating
                rows = self.conn.execute(
                    "SELECT seq, payload FROM audit WHERE type='taste.note.appended' AND refused=0"
                ).fetchall()
                redacted = 0
                for r in rows:
                    payload = json.loads(r["payload"])
                    note = payload.get("row", payload)
                    if note.get("author") != author or payload.get("redacted"):
                        continue
                    payload["redacted"] = True
                    payload["row"] = {"id": note.get("id", ""), "author": author,
                                       "redacted": True}
                    self.conn.execute(
                        "UPDATE audit SET payload=? WHERE seq=?",
                        (canonical_json(payload), r["seq"]),
                    )
                    redacted += 1
                compensating.subject = {"entity_kind": "taste_author", "entity_id": author}
                compensating.payload = {"author": author, "redacted_rows": redacted}
                compensating.validate_type()
                cur = self.conn.execute(
                    "INSERT INTO audit(id, at, actor, type, subject_kind, subject_id,"
                    " payload, artifact, refused) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        compensating.id, compensating.at,
                        canonical_json(compensating.actor.model_dump()), compensating.type,
                        compensating.subject["entity_kind"], compensating.subject["entity_id"],
                        canonical_json(compensating.payload), None, 0,
                    ),
                )
                seq = cur.lastrowid
                compensating.seq = seq
                apply_event(compensating, self.rows, self.ctx)
                self._set_meta("fold_seq", str(seq))
                # cached idempotent responses for taste endpoints may hold
                # pre-erase payloads — a cache, not the record; purge it.
                self.conn.execute("DELETE FROM idempotency WHERE key LIKE 'taste:%'")
                if idem_key is not None:
                    self.conn.execute(
                        "INSERT INTO idempotency(key, event_id, status, response, at)"
                        " VALUES(?,?,?,?,?)",
                        (idem_key, compensating.id, 200,
                         canonical_json({"author": author, "erased": True,
                                         "compensating_event": compensating.id}),
                         now_utc()),
                    )
                if began:
                    self.conn.execute("COMMIT")
            except Exception:
                if began and self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
        self.bus.notify()
        return compensating

    # ------------------------------------------------------------- boot (§5.2)

    def boot(self) -> dict:
        """Boot sequence steps 1 (projection catch-up/rebuild) executed by the
        store; recovery steps 3–5 (jobs, attempts, nights) live in boot.py."""
        report: dict[str, Any] = {"caught_up": 0, "rebuilt": False, "repaired": False}
        with self._write_lock:
            max_seq = self.max_seq()
            fold_seq = self.fold_seq()
            if fold_seq > max_seq:  # DB restored/replaced under us
                with self._txn():
                    self._full_rebuild()
                report["rebuilt"] = True
            elif fold_seq < max_seq:
                with self._txn():
                    pending = self.events_since(fold_seq)
                    for ev in pending:
                        apply_event(ev, self.rows, self.ctx)
                    self._set_meta("fold_seq", str(max_seq))
                report["caught_up"] = len(pending)
            diffs = self._verify()
            if diffs:
                with self._txn():
                    self._full_rebuild()
                report["rebuilt"] = True
                report["repaired"] = True
                report["diffs"] = diffs[:10]
        return report

    @contextmanager
    def _txn(self):
        """One explicit write transaction. Joins an open transaction if there
        is one, so a batch is still one transaction (§5.1)."""
        with self._write_lock:
            began = not self.conn.in_transaction
            if began:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                if began:
                    self.conn.execute("COMMIT")
            except Exception:
                if began and self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise

    def _verify(self) -> list[str]:
        events = self.events_since(0)
        shadow = fold_all(events, self.ctx)
        return stores_equal(shadow, self.rows)

    def _full_rebuild(self) -> None:
        events = self.events_since(0)
        shadow = fold_all(events, self.ctx)
        self.rows.wipe()
        for table in FOLD_TABLES:
            for row in shadow.scan(table):
                self.rows.put(table, {k: row[k] for k in row if k not in ("payload", "updated_seq")}, row)
        self._set_meta("fold_seq", str(self.max_seq()))

    # ------------------------------------------------------------- helpers

    def new_event(self, type_: str, actor: Any, subject: dict, payload: dict,
                  artifact: dict | None = None) -> AuditEvent:
        return AuditEvent(
            id=new_id("audit"), actor=actor, type=type_, subject=subject,
            payload=payload, artifact=artifact,
        )
