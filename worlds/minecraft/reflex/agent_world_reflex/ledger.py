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

__all__ = ["WorldLedger", "builder_ide_root", "ledger_paths", "core_subject"]


def core_subject(entity_id: str, *, kind: str = "tile") -> dict[str, Any]:
    """The subject shape builder-ide's core store keeps.

    The core store persists a subject as two columns — ``subject_kind``
    and ``entity_id`` — and **drops every other key**
    (:meth:`core.store.LedgerStore._append_tx`). The world's own subject
    shape was ``{"skill": ..., "family": ...}``, so written as it stood
    the skill id would have been discarded and the row would have come
    back with an empty subject. The world's skills are builder-ide's
    tiles (see :mod:`agent_world_reflex.tiles`), so the entity kind is
    ``tile`` and the entity id is the skill id.
    """
    return {"entity_kind": kind, "entity_id": str(entity_id)}


def _as_core_subject(subject: dict[str, Any]) -> dict[str, Any]:
    """Put any subject into the core's shape, without losing its id.

    A subject that already carries ``entity_kind``/``entity_id`` is kept
    as it is. The world's old shape — ``{"skill": ..., "family": ...}`` —
    is translated. A subject with neither is refused rather than
    guessed at: a row with no id cannot be found again.
    """
    if "entity_kind" in subject or "entity_id" in subject:
        return core_subject(subject.get("entity_id", ""), kind=str(subject.get("entity_kind") or "tile"))
    skill = subject.get("skill")
    if skill:
        return core_subject(str(skill))
    raise ValueError(
        "the subject carries no id: give it entity_id, or the world's own "
        f"'skill' key (got {sorted(subject)})"
    )



def builder_ide_root() -> Path:
    """Where builder-ide lives on this box.

    The world's reflex is builder-ide's judge (the decision-model seam)
    and builder-ide's ledger (the log of record). The path is a
    parameter with a default, like every other door here.

    The default used to be ``~/src/builder-ide``, because the world was
    its own repository. The world is now a package **of** builder-ide, so
    the root is found by walking up from this file until a directory
    holding ``core/`` appears — which is builder-ide, wherever it is
    checked out. ``AW_BUILDER_IDE`` still overrides it, for a world that
    runs against a builder-ide other than the one it sits in.
    """
    configured = os.environ.get("AW_BUILDER_IDE")
    if configured:
        return Path(configured).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "core" / "__init__.py").is_file():
            return parent
    return Path.home() / "src" / "builder-ide"


def ledger_paths() -> None:
    """Put builder-ide's packages on the import path."""
    root = str(builder_ide_root())
    if root not in sys.path:
        sys.path.insert(0, root)


ledger_paths()

from core.canon import canonical_bytes  # noqa: E402
from core.night import ledger as _night_ledger  # noqa: E402
from core.night.ledger import MAX_PAYLOAD_BYTES, SQLiteLedger  # noqa: E402
from core.records import Actor  # noqa: E402

from .tiles import (  # noqa: E402
    authored_payload,
    played_payload,
    retired_payload,
    skill_to_tile,
)

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

    **Where the log lives is a door.** By default it is the world's own
    SQLite file, exactly as it was before the move. Pass ``ledger=`` to
    write somewhere else — the seam
    (:class:`worlds.minecraft.builder_ide.ledger.CoreStoreLedger`) writes
    into builder-ide's core store, so the world's decisions are in the
    log the morning report and the "why" door read.

    The rows are written in builder-ide's vocabulary either way: the
    subject is ``{"entity_kind", "entity_id"}`` (the core store keeps
    those two keys and drops the rest), and a ``tile.played`` row carries
    the core's keys next to the world's own. A row written before this
    change still reads; a row written after it reads in both.
    """

    def __init__(self, path: Path | str, *, ledger: Any | None = None) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        # The door this ledger writes through. ``None`` means the world's
        # own file; anything else is a ledger with the same protocol.
        self._door = ledger

    @property
    def _ledger(self) -> SQLiteLedger:
        """The world's own file — one connection per thread."""
        if self._door is not None:
            return self._door  # type: ignore[return-value]
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

        The subject is put into the core's shape on the way in. The core
        store keeps ``entity_kind`` and ``entity_id`` and drops every
        other key, so a subject written in the world's old shape
        (``{"skill": ..., "family": ...}``) would lose its id silently.
        """
        with self._write_lock:
            return self._ledger.append(
                type=type,
                actor=actor,
                subject=_as_core_subject(subject),
                payload=payload,
                artifact=artifact,
                at=at,
            )

    # -- the writers ----------------------------------------------------------

    def authored(self, skill: Skill, *, cost_cents: int = 0) -> None:
        """A skill enters the library.

        The row is written in builder-ide's tile vocabulary: the subject
        is the tile's id, and the payload carries the tile's **body** —
        which is what :func:`core.tiles.library.fold_library` reads a
        tile back from. The world's own keys stay beside them, so the
        rows the world wrote before this change read the same way.
        """
        tile = skill_to_tile(skill)
        with self._write_lock:
            self._ledger.append(
                type="tile.authored",
                actor=Actor(kind="engineer", id=skill.author.model, via="cloud_author"),
                subject=core_subject(tile.id),
                payload=authored_payload(tile, cost_cents=cost_cents),
            )

    def played(self, record: PlayRecord, *, actor: str = "bot") -> None:
        """A skill was used, with its outcome and its context.

        The row carries the core's keys next to the world's own, and the
        ``scope`` the judge calibration pairs this play with.
        """
        payload = played_payload(record)
        if len(canonical_bytes(payload)) > MAX_PAYLOAD_BYTES:
            # The world's own payload fitted; the core's keys did not
            # leave room. The row is written in the world's shape rather
            # than refused: a lost play is worse than a row that reads
            # in one vocabulary instead of two.
            payload = record.model_dump(mode="json")
        with self._write_lock:
            self._ledger.append(
                type="tile.played",
                actor=Actor(kind="character", id=actor, via="reflex"),
                subject=core_subject(record.skill_id),
                payload=payload,
            )

    def retired(self, skill: Skill, *, reason: str, plays: int = 0, wins: int = 0) -> None:
        """A skill leaves the eligible set, with the reason."""
        tile = skill_to_tile(skill)
        with self._write_lock:
            self._ledger.append(
                type="tile.retired",
                actor=Actor(kind="core", id="mediator", via="retire"),
                subject=core_subject(tile.id),
                payload=retired_payload(tile, reason=reason, plays=plays, wins=wins),
            )

    def retrained(self, *, summary: dict[str, Any]) -> None:
        """The chooser was refit from the log."""
        with self._write_lock:
            self._ledger.append(
                type="tile.retrained",
                actor=Actor(kind="core", id="chooser", via="refit"),
                subject=core_subject(str(summary.get("chooser") or "chooser"), kind="chooser"),
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
                subject=core_subject("box-busy", kind="yield"),
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
