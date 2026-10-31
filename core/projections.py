"""Projection tables (§1.0): everything except ``audit`` is a projection
rebuilt by folding the audit log. Rows carry typed key columns (for
compare-and-swap and lookups) plus the entity snapshot as canonical JSON.

Two RowStore implementations exist on purpose: the SQLite one is the live
projection; the in-memory one is the shadow used by boot verification
(§5.2 step 1) so "projections are rebuildable from audit alone" is checked,
not assumed.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from .canon import canonical_json

SCHEMA_VERSION = "2"

# (table, pk columns, extra typed columns) — snapshot column is always `payload`.
PROJECTION_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "work_orders": (("id",), ("state",)),
    "questions": (("id",), ("open", "blocking")),
    "predictions": (("id",), ("verdict",)),
    "taste_notes": (("id",), ("author", "status")),
    "taste_authors": (("author",), ("ratified",)),
    "tasks": (("id",), ("state", "night", "author")),
    "nights": (("id",), ("state",)),
    "budget": (("night",), ()),
    "jobs": (("id",), ("state",)),
    "branches": (("id",), ("head", "purpose", "protected")),
    "vocab_words": (("word",), ("status", "version")),
    "assets": (("id",), ()),
    "node_refs": (("branch", "node_id"), ("entry_path", "kind", "orphaned")),
    "packets": (("id",), ("sha256",)),
    "client_presence": (("actor",), ("attached",)),
    "critic_verdicts": (("id",), ("night", "branch", "verdict", "degraded")),
}

FOLD_TABLES = list(PROJECTION_TABLES)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit(
  seq INTEGER PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  type TEXT NOT NULL,
  subject_kind TEXT,
  subject_id TEXT,
  payload TEXT NOT NULL,
  artifact TEXT,
  refused INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS audit_type_idx ON audit(type);
CREATE INDEX IF NOT EXISTS audit_subject_idx ON audit(subject_kind, subject_id);
CREATE INDEX IF NOT EXISTS audit_actor_idx ON audit(type, actor);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency(
  key TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  status INTEGER NOT NULL,
  response TEXT NOT NULL,
  at TEXT NOT NULL
);
"""

for _table, (_pks, _cols) in PROJECTION_TABLES.items():
    _col_sql = ",\n  ".join(
        [f"{c} TEXT" if c not in ("updated_seq", "open", "blocking", "protected", "ratified", "orphaned", "attached", "degraded", "version") else f"{c} INTEGER" for c in _pks + _cols]
        + ["updated_seq INTEGER NOT NULL", "payload TEXT NOT NULL"]
    )
    SCHEMA_SQL += f"\nCREATE TABLE IF NOT EXISTS {_table}(\n  {_col_sql},\n  PRIMARY KEY({', '.join(_pks)})\n);"

INTEGER_COLUMNS = {
    "updated_seq", "open", "blocking", "protected", "ratified", "orphaned",
    "attached", "degraded", "version",
}


class RowStore(Protocol):
    def get(self, table: str, pk: dict[str, Any]) -> dict | None: ...
    def put(self, table: str, pk: dict[str, Any], row: dict) -> None: ...
    def delete(self, table: str, pk: dict[str, Any]) -> None: ...
    def scan(self, table: str) -> list[dict]: ...
    def wipe(self) -> None: ...


class MemoryRowStore:
    """Shadow store for verification and tests."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[tuple, dict]] = {t: {} for t in FOLD_TABLES}

    @staticmethod
    def _key(pk: dict[str, Any]) -> tuple:
        return tuple(sorted((k, v) for k, v in pk.items()))

    def get(self, table: str, pk: dict[str, Any]) -> dict | None:
        return self.tables[table].get(self._key(pk))

    def put(self, table: str, pk: dict[str, Any], row: dict) -> None:
        self.tables[table][self._key(pk)] = dict(row)

    def delete(self, table: str, pk: dict[str, Any]) -> None:
        self.tables[table].pop(self._key(pk), None)

    def scan(self, table: str) -> list[dict]:
        return [dict(r) for r in self.tables[table].values()]

    def wipe(self) -> None:
        self.tables = {t: {} for t in FOLD_TABLES}


class SqliteRowStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _pk_cols(self, table: str) -> tuple[str, ...]:
        return PROJECTION_TABLES[table][0]

    def _row_to_db(self, table: str, pk: dict, row: dict) -> tuple[dict, str]:
        values: dict[str, Any] = {}
        for col in self._pk_cols(table) + PROJECTION_TABLES[table][1]:
            values[col] = row.get(col)
        values["updated_seq"] = row.get("updated_seq", 0)
        values["payload"] = row.get("payload")
        if isinstance(values.get("payload"), (dict, list)):
            values["payload"] = canonical_json(values["payload"])
        placeholders = ", ".join("?" for _ in values)
        cols = ", ".join(values.keys())
        return values, f"INSERT OR REPLACE INTO {table}({cols}) VALUES({placeholders})"

    def get(self, table: str, pk: dict[str, Any]) -> dict | None:
        pks = self._pk_cols(table)
        where = " AND ".join(f"{c} = ?" for c in pks)
        cur = self.conn.execute(f"SELECT * FROM {table} WHERE {where}", [pk[c] for c in pks])
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, row))
        return out

    def put(self, table: str, pk: dict[str, Any], row: dict) -> None:
        values, sql = self._row_to_db(table, pk, row)
        self.conn.execute(sql, list(values.values()))

    def delete(self, table: str, pk: dict[str, Any]) -> None:
        pks = self._pk_cols(table)
        where = " AND ".join(f"{c} = ?" for c in pks)
        self.conn.execute(f"DELETE FROM {table} WHERE {where}", [pk[c] for c in pks])

    def scan(self, table: str) -> list[dict]:
        cur = self.conn.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def wipe(self) -> None:
        for table in FOLD_TABLES:
            self.conn.execute(f"DELETE FROM {table}")
