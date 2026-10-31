"""The nightly retrain — the loop that makes the system get better (§5).

Every night, after the world's work:

1. **fold** the night's ``tile.played`` rows into play records;
2. **refit** the chooser from them — the statistics are a fold over the
   log, so a restart loses nothing and a replay gives the same answer;
3. **rank** the tiles by their win rate, **by measure**, with the
   denominator kept and an interval on the rate;
4. **retire** the tiles that lost, with the reason and the plays they had;
5. **feed the losers back** to the cloud author: "write a better one, here
   is why it lost" — and admit what comes back as the next version of the
   family.

**One measure at a time.** The retrain is told which measure it is
training on — the critic's verdict, the owner's keep-or-undo, or a sealed
prediction that held. Mixing them would let the critic's optimism quietly
become the builder's taste, and would make every win rate ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from core.canon import now_utc
from core.records import Actor

from .author import AuthorRequest, TileAuthorProtocol
from .chooser import ContextualBandit
from .library import TileLibrary
from .models import FeedbackPacket, PlayRecord, Tile
from .plays import fold_plays
from .ports import LedgerPort
from .stats import wilson_interval

__all__ = [
    "TileScore",
    "RetrainReport",
    "retrain",
    "MEASURE_GROUPS",
    "CORE_ACTOR",
]

#: The measures, and which outcome measures belong to each of them. The
#: owner's keep and the owner's undo are the same measure — the owner's
#: verdict — with opposite outcomes.
MEASURE_GROUPS: dict[str, tuple[str, ...]] = {
    "critic": ("critic",),
    "owner": ("owner_keep", "owner_undo"),
    "sealed_prediction": ("sealed_prediction",),
}

#: Who writes the retrain row.
CORE_ACTOR = Actor(kind="core", id="tiles", via="tile")


@dataclass(frozen=True)
class TileScore:
    """How one tile did, with the denominator kept."""

    tile_id: str
    family: str
    kind: str
    plays: int
    wins: int
    partials: int
    losses: int
    win_rate: float
    measure: str
    contexts_lost: tuple[str, ...] = ()
    interval: tuple[float, float] = (0.0, 0.0)

    @property
    def basis(self) -> str:
        """The rate with its denominator — never a percentage alone."""
        return f"{self.wins}/{self.plays} won by {self.measure}"

    def line(self) -> str:
        low, high = self.interval
        return (
            f"{self.tile_id} · {self.basis} · "
            f"95% CI [{low:.2f}, {high:.2f}]"
        )


@dataclass(frozen=True)
class RetrainReport:
    """What the night's retrain did."""

    at: str
    night: str | None
    measure: str
    plays: int
    scores: tuple[TileScore, ...] = ()
    retired: tuple[str, ...] = ()
    feedback: tuple[FeedbackPacket, ...] = ()
    new_tiles: tuple[Tile, ...] = ()

    def line(self) -> str:
        """The one line the morning can show."""
        return (
            f"retrained on {self.plays} plays by {self.measure} · "
            f"{len(self.scores)} tiles scored · "
            f"{len(self.retired)} retired · "
            f"{len(self.new_tiles)} new tiles"
        )


def retrain(
    *,
    events: Sequence[Any],
    library: TileLibrary,
    ledger: LedgerPort | None = None,
    chooser: ContextualBandit | None = None,
    author: TileAuthorProtocol | None = None,
    measure: str = "critic",
    min_plays: int = 3,
    retire_below: float = 0.34,
    retire: bool = True,
    goal: str = "",
    clock: Callable[[], str] = now_utc,
) -> RetrainReport:
    """Run the night's learning loop.

    ``events`` is the log to learn from — the whole log, not just tonight,
    because a chooser that forgets is a chooser that has to learn again.
    """
    if measure not in MEASURE_GROUPS:
        raise ValueError(f"{measure!r} is not a measure the retrain can train on")

    wanted = MEASURE_GROUPS[measure]
    records = [record for record in fold_plays(events) if record.outcome.measure in wanted]

    if chooser is not None:
        chooser.fit(records)

    scores = _score(records, library, measure, chooser)
    # Only a tile that is still an option can be a loser tonight: a tile
    # that was retired last night has already had its feedback, and asking
    # the cloud to replace it again every night is how a family's history
    # turns into noise.
    losers = [
        score
        for score in scores
        if score.plays >= min_plays
        and score.win_rate < retire_below
        and _is_active(library, score.tile_id)
    ]
    feedback = _feedback_packets(losers, library, measure)

    retired: list[str] = []
    if retire:
        for score in losers:
            tile = library.require(score.tile_id)
            library.retire(
                tile.id,
                reason=(
                    f"lost {score.losses}/{score.plays} by the {score.measure}"
                ),
            )
            retired.append(tile.id)

    new_tiles: list[Tile] = []
    if author is not None and feedback:
        request = AuthorRequest(
            goal=goal or "write a better tile for the families that lost",
            words=tuple(
                sorted({word for packet in feedback for word in packet.words})
            ),
            feedback=tuple(feedback),
        )
        for tile in author.write(request):
            new_tiles.append(library.add(tile))

    report = RetrainReport(
        at=clock(),
        night=_night_of(records),
        measure=measure,
        plays=len(records),
        scores=tuple(scores),
        retired=tuple(retired),
        feedback=tuple(feedback),
        new_tiles=tuple(new_tiles),
    )

    if ledger is not None:
        ledger.append(
            type="tile.retrained",
            actor=CORE_ACTOR,
            subject={"entity_kind": "night", "entity_id": report.night or "night"},
            payload={
                "at": report.at,
                "night": report.night,
                "measure": measure,
                "plays": report.plays,
                "scored": len(report.scores),
                "retired": list(report.retired),
                "new_tiles": [tile.id for tile in report.new_tiles],
            },
        )
    return report


# --- internals ---------------------------------------------------------------


def _score(
    records: Sequence[PlayRecord],
    library: TileLibrary,
    measure: str,
    chooser: ContextualBandit | None,
) -> list[TileScore]:
    """Rank the tiles, with the denominator and an interval on each rate."""
    grouped: dict[str, list[PlayRecord]] = {}
    for record in records:
        grouped.setdefault(record.tile_id, []).append(record)

    scores: list[TileScore] = []
    for tile_id, tile_records in grouped.items():
        wins = sum(1 for r in tile_records if r.outcome.result == "win")
        partials = sum(1 for r in tile_records if r.outcome.result == "partial")
        losses = sum(1 for r in tile_records if r.outcome.result == "lose")
        plays = len(tile_records)

        contexts_lost: list[str] = []
        if chooser is not None:
            for record in tile_records:
                if record.outcome.result == "win":
                    continue
                bucket = chooser.bucket(record.context)
                if bucket not in contexts_lost:
                    contexts_lost.append(bucket)

        tile = library.get(tile_id)
        scores.append(
            TileScore(
                tile_id=tile_id,
                family=tile.family if tile else "",
                kind=tile.kind if tile else "",
                plays=plays,
                wins=wins,
                partials=partials,
                losses=losses,
                win_rate=wins / plays if plays else 0.0,
                measure=measure,
                contexts_lost=tuple(contexts_lost),
                interval=wilson_interval(wins, plays),
            )
        )
    scores.sort(key=lambda score: (-score.win_rate, -score.plays, score.tile_id))
    return scores


def _is_active(library: TileLibrary, tile_id: str) -> bool:
    """True when the tile is in the library and still an option."""
    tile = library.get(tile_id)
    return tile is not None and tile.status == "active"


def _feedback_packets(
    losers: Sequence[TileScore], library: TileLibrary, measure: str
) -> list[FeedbackPacket]:
    """The packets the cloud author gets: what lost, where, and by how much."""
    packets: list[FeedbackPacket] = []
    for score in losers:
        tile = library.get(score.tile_id)
        packets.append(
            FeedbackPacket(
                tile_id=score.tile_id,
                family=score.family,
                kind=tile.kind if tile else "recipe_edit",  # type: ignore[arg-type]
                words=tile.words if tile else (),
                plays=score.plays,
                wins=score.wins,
                win_rate=score.win_rate,
                measure=measure,
                contexts=score.contexts_lost,
                request=(
                    "write a better tile for this family; here is why it lost: "
                    f"{score.wins}/{score.plays} won by the {measure}"
                ),
            )
        )
    return packets


def _night_of(records: Sequence[PlayRecord]) -> str | None:
    for record in records:
        if record.night:
            return record.night
    return None
