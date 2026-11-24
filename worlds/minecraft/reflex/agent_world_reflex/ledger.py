"""The world's log of record.

One SQLite file, the closed event set from ``core-spec`` §1.8, and the
**tile** event types — because in this world a skill is a tile: the cloud
writes the options, the Thor learns which ones work.

| event | when |
|---|---|
| ``tile.authored`` | a skill enters the library |
| ``tile.played``  | a skill is used, with its outcome |
| ``tile.retired`` | a skill leaves the eligible set |
| ``tile.retrained`` | the chooser was refit from the log |
| ``drift.yield``  | the world stood aside: the admission rule or a drift |
|                  | pause refused work, and who was told to wait |

The library and the chooser's statistics are **folds over this log**, so
a restart loses nothing and a replay gives the same answer.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import PlayRecord, Skill

__all__ = ["WorldLedger", "builder_ide_root", "ledger_paths"]


def builder_ide_root() -> Path:
    """Where builder-ide lives on this box.

    The world's reflex is builder-ide's judge (the decision-model seam)
    and builder-ide's ledger (the log of record). The path is a
    parameter with a default, like every other door here.
    """
    configured = os.environ.get("AW_BUILDER_IDE")
    if configured:
        return Path(configured)
    return Path.home() / "src" / "builder-ide"


def ledger_paths() -> None:
    """Put builder-ide's packages on the import path."""
    root = str(builder_ide_root())
    if root not in sys.path:
        sys.path.insert(0, root)


ledger_paths()

from core.night import ledger as _night_ledger  # noqa: E402
from core.night.ledger import MAX_PAYLOAD_BYTES, SQLiteLedger  # noqa: E402
from core.records import Actor  # noqa: E402

#: The event types the world writes of its own. The log of record has a
#: closed set (§1.8) and builder-ide's copy of it does not carry these
#: three yet; the drift brief's copy of the same shared core does
#: (``~/lm-wt/drift-pause/core/records.py``, ``DRIFT_EVENT_TYPES``).
#: The world writes them, so the world's door extends the set for the
#: types it owns — one list, here, with a pointer to the definition.
#:
#: Without this the world's stand-asides were refused by the closed set
#: with ``ValueError: unknown audit event type: 'drift.yield'``, the
#: reflex caught it into an invisible field, and the log of record held
#: no evidence that any agent had ever stood aside. The drift detector
#: could not tell "could not act" from "chose not to act", so it read
#: the crew's deliberate wait as a stall and held the same agent again
#: (2026-11-02, 07:43–08:2x UTC).
WORLD_EVENT_TYPES = ("drift.yield", "drift.rule_violation", "drift.build_drift")

_night_ledger.EVENT_TYPES = frozenset(
    set(_night_ledger.EVENT_TYPES) | set(WORLD_EVENT_TYPES)
)


class WorldLedger:
    """The log of record, in the world's own words.

    The world's services are threaded: the reflex answers a batch from
    its collector thread and records a play from a request thread. A
    SQLite connection belongs to one thread, so this holds one
    connection **per thread** — the same file, the same WAL, one
    connection each. That is the usual way to share a SQLite database
    between threads, and it keeps the log a single file.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()

    @property
    def _ledger(self) -> SQLiteLedger:
        connection = getattr(self._local, "ledger", None)
        if connection is None:
            connection = SQLiteLedger(self.path)
            self._local.ledger = connection
        return connection

    # -- the door --------------------------------------------------------------

    def append(
        self,
        *,
        type: str,
        actor: Actor,
        subject: dict[str, Any],
        payload: dict[str, Any],
        artifact: dict[str, Any] | None = None,
        at: str | None = None,
    ):  # noqa: D401
        """Append one event to the log of record.

        This is the ledger protocol the judge writes through: the judge
        records its own ``judge.verdict`` rows, and it does not know
        about this world's own event types. So the door is the same door:
        one log, one append, whatever the seat.
        """
        with self._write_lock:
            return self._ledger.append(
                type=type,
                actor=actor,
                subject=subject,
                payload=payload,
                artifact=artifact,
                at=at,
            )

    # -- the writers ----------------------------------------------------------

    def authored(self, skill: Skill, *, cost_cents: int = 0) -> None:
        with self._write_lock:
            self._ledger.append(
                type="tile.authored",
                actor=Actor(kind="engineer", id=skill.author.model, via="cloud_author"),
                subject={"skill": skill.id, "family": skill.family, "version": skill.version},
                payload={
                    "skill": skill.id,
                    "family": skill.family,
                    "version": skill.version,
                    "role": skill.role,
                    "title": skill.title,
                    "kind": skill.kind,
                    "api": list(skill.api),
                    "author": skill.author.model,
                    "provider": skill.author.provider,
                    "cost_cents": cost_cents,
                    "prompt_hash": skill.author.prompt_hash,
                },
            )

    def played(self, record: PlayRecord, *, actor: str = "bot") -> None:
        with self._write_lock:
            self._ledger.append(
                type="tile.played",
                actor=Actor(kind="character", id=actor, via="reflex"),
                subject={"skill": record.skill_id, "family": ""},
                payload=record.model_dump(mode="json"),
            )

    def retired(self, skill: Skill, *, reason: str, plays: int = 0, wins: int = 0) -> None:
        with self._write_lock:
            self._ledger.append(
                type="tile.retired",
                actor=Actor(kind="core", id="mediator", via="retire"),
                subject={"skill": skill.id, "family": skill.family},
                payload={
                    "skill": skill.id,
                    "family": skill.family,
                    "version": skill.version,
                    "reason": reason,
                    "plays": plays,
                    "wins": wins,
                },
            )

    def retrained(self, *, summary: dict[str, Any]) -> None:
        with self._write_lock:
            self._ledger.append(
                type="tile.retrained",
                actor=Actor(kind="core", id="chooser", via="refit"),
                subject={"chooser": summary.get("chooser", "")},
                payload={"summary": summary},
            )

    def yielded(self, bots: list[str], why: str) -> None:
        """Record that the world stood aside, and who was told to wait.

        One event per admission decision, with every bot it covers in
        the payload. The drift detector folds these per agent so its
        stall signal can tell "could not act" from "chose not to act"
        (``docs/design/vibecode-in-world.md`` §3.4); until this event
        existed the two were the same silence. A pause is a yield too —
        the soft level of §3.5 is an agent told to hold — and the
        ``reason`` says which.
        """
        with self._write_lock:
            self._ledger.append(
                type="drift.yield",
                actor=Actor(kind="core", id="reflex", via="admission"),
                subject={"yield": "box-busy"},
                payload={"reason": why, "bots": list(bots), "count": len(bots)},
            )

    # -- the reads ------------------------------------------------------------

    def events(self, *, since_seq: int | None = None, types: Sequence[str] | None = None):
        return self._ledger.events(since_seq=since_seq, types=types)

    def plays(self) -> list[PlayRecord]:
        """The play records, folded back out of the log."""
        out: list[PlayRecord] = []
        for event in self.events(types=["tile.played"]):
            try:
                out.append(PlayRecord(**event.payload))
            except Exception:
                continue
        return out

    def authored_skills(self) -> list[str]:
        return [
            event.payload.get("skill", "")
            for event in self.events(types=["tile.authored"])
        ]

    def retired_skills(self) -> list[dict[str, Any]]:
        return [event.payload for event in self.events(types=["tile.retired"])]

    def last_seq(self) -> int:
        return self._ledger.last_seq()

    def close(self) -> None:
        self._ledger.close()
