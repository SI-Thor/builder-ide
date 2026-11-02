"""The snapshot is where the world's state and the world's story meet.

A rewind point on the world ledger is a **row** — a place in the world's
story. A snapshot is a **state** — the world's files at a moment. The two
are joined by the ledger's ``seq``: the manifest records the ledger's head
when the snapshot was taken, so a point in the story can be matched to the
nearest snapshot at or before it.

Then the work that came after. A snapshot at seq *S* and a rewind point at
seq *P* (*P* > *S*) mean the world has to be put back to *S* and the work
between *S* and *P* put back on top of it. Which of that work can be put
back is what this module answers, and the answer has three kinds:

``reappliable``
    a world mutation we know how to make again — a **block placement** by
    a bot, which mineflayer can do given the coordinates and the block
    name;
``recorded``
    a row the ledger already keeps and the world does not hold — a judge's
    verdict, a skill being authored or retired. Nothing to replay: the
    ledger *is* the record. The plan lists them so that "kept" is not
    mistaken for "replayed";
``lost``
    a world mutation that cannot be made again — a mined block, a mob
    that was killed, an item that despawned, the time of day moving on.
    The restore takes these away and nothing puts them back.

**Where the coordinates come from.** The ledger's rows do not carry them: a
``tile.played`` row says which skill ran on which bot, and the outcome in
words ("oak_log +0 (wanted 1)"), but not where a block was put. So the
plan reads a **placement journal** — the world mutations the bots
recorded, with their coordinates — and joins it to the ledger by bot and
time. A row with no journal entry is *lost*, because the ledger cannot say
what it did to the world. That is the honest state of the world today, and
this build makes it explicit rather than guessing.

The join is a convention, not a schema: the same kind of attribution
convention the drift detector uses. A journal entry is matched to the
ledger row of the same bot whose time is closest, within a window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from mcsnap.manifest import MANIFEST_NAME, Manifest, read_manifest

from .ledger import Ledger, LedgerRow, read_world_ledger
from .selection import Selection, parse, select

__all__ = [
    "Placement",
    "ReappliableOp",
    "RewindPlan",
    "nearest_snapshot_at_or_before",
    "read_manifests",
    "read_placements",
    "rewind_plan",
    "rewind_plan_from_store",
    "DEFAULT_WINDOW_SECONDS",
    "RECORDED_KINDS",
]


#: How far apart a journal entry and a ledger row may be and still be
#: taken to be the same play. The bots' action happens between the
#: decision and the row that records it, so the window is a few seconds.
DEFAULT_WINDOW_SECONDS = 10.0

#: The event kinds that are *records*, not world state.
RECORDED_KINDS = frozenset({"judge.verdict", "tile.authored", "tile.retired"})


@dataclass(frozen=True)
class Placement:
    """One world mutation, as a bot recorded it.

    A placement journal is a JSON Lines file: one object per line, with
    ``at`` (ISO-8601 or epoch), ``bot``, ``op`` (``place`` or ``mine``),
    ``block``, and the coordinates ``x``, ``y``, ``z``.

    ``seq`` is the ledger row the bot wrote for this placement. A bot
    that records it makes the join exact; a journal without it is joined
    by time instead.
    """

    at: float
    bot: str
    op: str
    block: str
    x: int
    y: int
    z: int
    skill: str = ""
    seq: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Placement":
        at = data.get("at")
        if isinstance(at, (int, float)):
            moment = float(at)
        else:
            from .ledger import parse_at

            moment = parse_at(str(at))
        seq = data.get("seq")
        return cls(
            at=moment,
            bot=str(data.get("bot", "")),
            op=str(data.get("op", "")),
            block=str(data.get("block", "")),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            z=int(data.get("z", 0)),
            skill=str(data.get("skill", "")),
            seq=int(seq) if isinstance(seq, (int, float)) else None,
        )


@dataclass(frozen=True)
class ReappliableOp:
    """A world mutation that can be put back."""

    seq: int
    at: float
    actor: str
    op: str
    block: str
    x: int
    y: int
    z: int
    skill: str = ""
    source: str = "placement journal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "actor": self.actor,
            "op": self.op,
            "block": self.block,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "skill": self.skill,
            "source": self.source,
        }


@dataclass(frozen=True)
class RewindPlan:
    """What a rewind to a point would do, and what it could not do."""

    point_seq: int
    snapshot_id: str | None = None
    snapshot_seq: int | None = None
    snapshot_dir: str | None = None
    kept: tuple[LedgerRow, ...] = ()
    reappliable: tuple[ReappliableOp, ...] = ()
    recorded: tuple[LedgerRow, ...] = ()
    lost: tuple[tuple[LedgerRow, str], ...] = ()
    dropped: tuple[tuple[LedgerRow, str], ...] = ()
    after_point: int = 0
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    note: str = ""

    @property
    def lost_count(self) -> int:
        return len(self.lost)

    def to_dict(self) -> dict[str, Any]:
        """The plan as plain data — for the CLI, the report and the journal."""
        return {
            "point_seq": self.point_seq,
            "snapshot_id": self.snapshot_id,
            "snapshot_seq": self.snapshot_seq,
            "snapshot_dir": self.snapshot_dir,
            "kept": len(self.kept),
            "reappliable": [op.to_dict() for op in self.reappliable],
            "recorded": [row.seq for row in self.recorded],
            "lost": [
                {"seq": row.seq, "kind": row.kind, "actor": row.actor, "reason": reason}
                for row, reason in self.lost
            ],
            "dropped": [
                {"seq": row.seq, "kind": row.kind, "actor": row.actor, "reason": reason}
                for row, reason in self.dropped
            ],
            "after_point": self.after_point,
            "window_seconds": self.window_seconds,
            "note": self.note,
        }


# ==================================================================== snapshots


def read_manifests(store: str | Path) -> list[Manifest]:
    """Every snapshot in a store, with its manifest."""
    root = Path(store)
    manifests: list[Manifest] = []
    if not root.is_dir():
        return manifests
    for directory in sorted(root.iterdir()):
        manifest_path = directory / MANIFEST_NAME
        if manifest_path.is_file():
            manifests.append(read_manifest(manifest_path))
    return manifests


def nearest_snapshot_at_or_before(
    snapshots: Iterable[Manifest], point_seq: int
) -> Manifest | None:
    """The snapshot at or before a ledger row — the one to restore.

    The choice is by the ledger's own order: the snapshot whose ``seq`` is
    the greatest that is still ``<=`` the point. A snapshot with no ledger
    row cannot be placed in the story and is not eligible.
    """
    eligible = [
        manifest
        for manifest in snapshots
        if manifest.ledger_seq is not None and manifest.ledger_seq <= point_seq
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda manifest: int(manifest.ledger_seq or 0))


# ==================================================================== journal


def read_placements(path: str | Path | None) -> list[Placement]:
    """Read a placement journal: the world mutations the bots recorded."""
    if path is None:
        return []
    resolved = Path(path)
    if not resolved.is_file():
        return []
    placements: list[Placement] = []
    for line in resolved.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        placements.append(Placement.from_dict(data))
    placements.sort(key=lambda item: item.at)
    return placements


def _match_placement(
    row: LedgerRow, placements: Sequence[Placement], window: float
) -> Placement | None:
    """The journal entry that belongs to a ledger row, if there is one.

    Two ways to join, in this order:

    **By the row's own seq.** A bot that records the ledger row it wrote
    for a placement makes the join exact, and nothing else can go wrong.
    This is the path the private world's bots take.

    **By time**, for a journal that does not carry the seq. The row's
    time is the *decision's* time and the journal's is the *action's*,
    and the ledger's time has second resolution while the journal's has
    milliseconds — so a row can sit up to a second *before* the action
    it records. An entry at or after the row's time is therefore a
    better match than an entry before it, even one that is nearer.
    """
    for placement in placements:
        if placement.seq is None or int(placement.seq) != int(row.seq):
            continue
        if placement.bot and row.actor and placement.bot != row.actor:
            continue
        return placement

    best: Placement | None = None
    best_score: tuple[int, float] | None = None
    for placement in placements:
        if placement.bot and row.actor and placement.bot != row.actor:
            continue
        distance = abs(placement.at - row.at)
        if distance > window:
            continue
        score = (0 if placement.at >= row.at else 1, distance)
        if best_score is None or score < best_score:
            best = placement
            best_score = score
    return best


def classify_event(
    row: LedgerRow,
    placements: Sequence[Placement],
    *,
    window: float = DEFAULT_WINDOW_SECONDS,
) -> tuple[str, str, Placement | None]:
    """What a ledger row means for a restore: ``(verdict, reason, placement)``.

    The verdict is one of ``reappliable``, ``recorded`` or ``lost``.
    """
    if row.kind in RECORDED_KINDS:
        return (
            "recorded",
            f"a {row.kind} row is a record the ledger keeps; it is not world state",
            None,
        )
    placement = _match_placement(row, placements, window)
    if placement is None:
        return (
            "lost",
            "the ledger does not say what this play did to the world, and no "
            "placement journal entry is close enough to it",
            None,
        )
    if placement.op == "place":
        return (
            "reappliable",
            "a block placement, which mineflayer can make again",
            placement,
        )
    if placement.op in ("mine", "break"):
        return (
            "lost",
            "a mined block: what was there cannot be invented, so the restore "
            "leaves the space empty",
            placement,
        )
    return (
        "lost",
        f"no mechanism for a {placement.op} op",
        placement,
    )


# ==================================================================== the plan


def rewind_plan(
    point_seq: int,
    snapshots: Sequence[Manifest],
    ledger: Ledger,
    *,
    selection: Selection | None = None,
    placements: Sequence[Placement] = (),
    window: float = DEFAULT_WINDOW_SECONDS,
) -> RewindPlan:
    """The plan for rewinding the world to a ledger row.

    The world is restored to the nearest snapshot at or before the point,
    and the kept work between that snapshot and the point is put back on
    top of it. Everything the restore cannot put back is named.
    """
    snapshot = nearest_snapshot_at_or_before(snapshots, point_seq)
    if snapshot is None:
        return RewindPlan(
            point_seq=point_seq,
            note=(
                "there is no snapshot at or before this point, so the world "
                "cannot be put back to it"
            ),
            window_seconds=window,
        )
    snapshot_seq = int(snapshot.ledger_seq or 0)

    kept_seqs: set[int] | None = None
    reasons: dict[int, str] = {}
    if selection is not None:
        result = select(ledger, selection)
        kept_seqs = {int(row.seq) for row in result.kept}
        reasons = {int(row.seq): reason for row, reason in result.dropped}

    kept: list[LedgerRow] = []
    dropped: list[tuple[LedgerRow, str]] = []
    reappliable: list[ReappliableOp] = []
    recorded: list[LedgerRow] = []
    lost: list[tuple[LedgerRow, str]] = []
    after_point = 0

    for row in ledger.rows:
        seq = int(row.seq)
        if seq > point_seq:
            after_point += 1
            continue
        if seq <= snapshot_seq:
            continue  # already in the snapshot's world
        is_kept = kept_seqs is None or seq in kept_seqs
        if not is_kept:
            dropped.append((row, reasons.get(seq, "not kept by the selection")))
            continue
        kept.append(row)
        verdict, reason, placement = classify_event(row, placements, window=window)
        if verdict == "recorded":
            recorded.append(row)
        elif verdict == "reappliable" and placement is not None:
            reappliable.append(
                ReappliableOp(
                    seq=seq,
                    at=row.at,
                    actor=row.actor,
                    op=placement.op,
                    block=placement.block,
                    x=placement.x,
                    y=placement.y,
                    z=placement.z,
                    skill=placement.skill,
                )
            )
        else:
            lost.append((row, reason))

    return RewindPlan(
        point_seq=point_seq,
        snapshot_id=snapshot.snapshot_id,
        snapshot_seq=snapshot_seq,
        snapshot_dir=str(Path(snapshot.world_dir).parent / snapshot.snapshot_id),
        kept=tuple(kept),
        reappliable=tuple(reappliable),
        recorded=tuple(recorded),
        lost=tuple(lost),
        dropped=tuple(dropped),
        after_point=after_point,
        window_seconds=window,
        note=(
            "the ledger is append-only and is not touched: the rows after the "
            "point stay in the ledger, but the world goes back before them"
        ),
    )


def rewind_plan_from_store(
    store: str | Path,
    ledger_path: str | Path,
    *,
    point_seq: int,
    selection_text: str | None = None,
    placements_path: str | Path | None = None,
    window: float = DEFAULT_WINDOW_SECONDS,
) -> RewindPlan:
    """The plan, read from a snapshot store and the world's ledger.

    This is the shape the command line uses: the store holds the
    snapshots, the ledger holds the story, and the placement journal (if
    there is one) holds the coordinates.
    """
    snapshots = read_manifests(store)
    ledger = read_world_ledger(ledger_path)
    selection = parse(selection_text) if selection_text else None
    placements = read_placements(placements_path)
    return rewind_plan(
        point_seq,
        snapshots,
        ledger,
        selection=selection,
        placements=placements,
        window=window,
    )
