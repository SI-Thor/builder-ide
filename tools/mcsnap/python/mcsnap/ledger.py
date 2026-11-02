"""The world ledger's head — the join between a snapshot and the story.

A snapshot of the world's *state* and the ledger's *story* are two
different things, and a rewind needs both: the state to put back, and the
story to know which work came after it. The join is the ledger's ``seq``.

This module reads one number — the highest ``seq`` a ledger holds — and
nothing else. It opens the ledger **read-only** (``mode=ro``), because the
world's ledger is live and is never locked by a reader: a snapshot must not
be able to stall the world it is snapshotting.

The full reader lives in :mod:`core.rewind.ledger`; that one reads every
row and is the right tool for a selection. This one is the cheap cursor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

__all__ = ["ledger_head"]


def ledger_head(path: str | Path) -> dict[str, Any]:
    """The ledger's highest row: its ``seq`` and the time it was written.

    A ledger with no rows is not an error — it is a world that has not
    happened yet — and it comes back with ``seq`` of ``None``.
    """
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"no ledger at {resolved}")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT seq, at FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error as error:
        raise RuntimeError(f"{resolved} has no readable audit table: {error}") from error
    finally:
        connection.close()
    if row is None:
        return {"path": str(resolved), "seq": None, "at": None}
    return {"path": str(resolved), "seq": int(row[0]), "at": str(row[1])}
