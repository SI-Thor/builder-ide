"""The resident's durable recipe: an append-only journal, a periodic snapshot,
and a checkpoint.

This is the answer to *"what happens on a crash?"* — and it is the answer the
spike measured (WS §4.4): **the scene is a pure function of the recipe, so
recovery is a replay.**

Three files, three jobs:

``journal.jsonl``
    The truth. One line per applied change, appended and fsynced. A
    ``kill -9`` between two changes loses at most the change that was in
    flight, never an earlier one, and a torn last line is tolerated by the
    reader.

``recipe.json``
    A **snapshot**, rewritten only at a checkpoint. The spike measured what
    happens when this file is rewritten whole on every edit: 143 MiB written
    for a 255 KiB file over 1000 edits, and per-edit latency growing 4.3× as
    the file grew (WS §5.3). The journal is O(1) per edit; the snapshot is
    O(document) per checkpoint.

``checkpoint.json``
    The recovery anchor: the recipe document it covers, the journal position it
    covers, and **the scene's state digest** — so a restart can prove it
    rebuilt the scene the checkpoint describes rather than merely that a file
    existed.

Write volume is *measured*, not asserted: the journal and the snapshot are
counted separately, so the write amplification of the durable recipe is a
number this module reports rather than a claim in a comment.

The resident process never writes here. The **adapter** (in the core) owns
this directory, which keeps the spec's hard rule intact: the warm scene
server is a derived cache, never a writer (core-spec §1.9, decision 17).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["SceneJournal", "JournalEntry"]


class JournalEntry(dict):
    """One journal line. A dict, so it round-trips through JSON unchanged."""


def _atomic_write(path: Path, data: bytes) -> None:
    """Write a file so a crash never leaves a half-written one."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


class SceneJournal:
    """The durable recipe of one resident scene.

    Usage is the obvious one: :meth:`open` attaches (never truncates — a
    restart must find the journal it left), then :meth:`record_ops` /
    :meth:`record_replace` append, and :meth:`write_checkpoint` anchors a
    recovery point.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.root / "journal.jsonl"
        self.snapshot_path = self.root / "recipe.json"
        self.checkpoint_path = self.root / "checkpoint.json"
        self._handle: Any = None
        #: how many entries the journal holds (the replay cursor)
        self.entries_written = 0
        self.journal_bytes_written = 0
        self.snapshot_bytes_written = 0
        self.snapshot_writes = 0
        self.checkpoints_written = 0

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> "SceneJournal":
        """Attach to the journal on disk without discarding it.

        A **new** adapter attaching to an old journal must continue the
        sequence where the old one left it: the checkpoint's
        ``journal_entries`` is a position in *this* file, so the numbering
        cannot restart at zero under a new adapter.
        """
        if self._handle is None:
            if self.entries_written == 0 and self.journal_path.exists():
                self.entries_written = len(self.read_entries())
            self._handle = self.journal_path.open("ab")
        return self

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "SceneJournal":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing -----------------------------------------------------------

    def record_replace(self, document: dict) -> int:
        """Journal a *whole document* — the first load of a fresh resident.

        The document crosses as data (§2.2's rule): the resident never sees
        an engine-native format, and the journal stays replayable.
        """
        return self._append(
            {"kind": "replace", "recipe": document, "entries": len(document.get("entries", {}))}
        )

    def record_ops(self, ops: list[dict]) -> int:
        """Journal the ops that were applied to the resident scene.

        The ops are the *dirty set* that was applied, not the whole diff the
        caller asked about: the journal replays what happened, so it must
        record what the resident did.
        """
        return self._append({"kind": "ops", "ops": list(ops)})

    def _append(self, entry: dict) -> int:
        self.open()
        entry["seq"] = self.entries_written
        line = json.dumps(entry, sort_keys=True, default=str) + "\n"
        self._handle.write(line.encode("utf-8"))
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.entries_written += 1
        self.journal_bytes_written += len(line.encode("utf-8"))
        return entry["seq"]

    def write_checkpoint(self, *, document: dict, state_digest: str) -> dict:
        """Write a checkpoint: the document, the journal position and the
        scene's state digest.

        A checkpoint also rewrites the snapshot, so the two agree about what
        the recipe was at that moment.
        """
        self._write_snapshot(document)
        payload = {
            "version": 1,
            "journal_entries": self.entries_written,
            "document": document,
            "state_digest": state_digest,
        }
        _atomic_write(
            self.checkpoint_path,
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        )
        self.checkpoints_written += 1
        return payload

    def _write_snapshot(self, document: dict) -> None:
        data = json.dumps(
            {"version": 1, "document": document}, sort_keys=True, indent=2, default=str
        ).encode("utf-8")
        _atomic_write(self.snapshot_path, data)
        self.snapshot_bytes_written += len(data)
        self.snapshot_writes += 1

    # -- reading -----------------------------------------------------------

    def read_entries(self) -> list[JournalEntry]:
        """The journal, oldest first.

        A torn line — the half-written last line a ``kill -9`` can leave — is
        skipped, not fatal (WS §4.4: the reader skips it and the digest still
        matches).
        """
        if not self.journal_path.exists():
            return []
        out: list[JournalEntry] = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(JournalEntry(parsed))
        return out

    def read_checkpoint(self) -> dict | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def read_snapshot(self) -> dict | None:
        if not self.snapshot_path.exists():
            return None
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("document"), dict):
            return payload["document"]
        return None

    # -- the write-amplification number ------------------------------------

    def write_stats(self) -> dict:
        """The durable recipe's cost, measured.

        ``amplification`` is how many times the whole document was written
        relative to its size — the number the spike's 550× complaint was
        about. The journal's cost is reported separately: it is O(1) per edit
        and grows with the *history*, not with the document.
        """
        document_bytes = self.snapshot_path.stat().st_size if self.snapshot_path.exists() else 0
        return {
            "journal_bytes_written": self.journal_bytes_written,
            "snapshot_bytes_written": self.snapshot_bytes_written,
            "snapshot_writes": self.snapshot_writes,
            "journal_entries": self.entries_written,
            "checkpoints_written": self.checkpoints_written,
            "document_bytes": document_bytes,
            "amplification": (
                self.snapshot_bytes_written / document_bytes if document_bytes else 0.0
            ),
        }
