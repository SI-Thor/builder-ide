"""The live world's log of record, read only.

The community's plays are in the world's ledger: one SQLite file, the
closed event set, with a row for every play — 70,000-odd of them by
2026-11-02. The gym reads that file and writes nothing to it: the
connection is opened in SQLite's read-only mode (``mode=ro``), so the
database itself cannot be written even by accident.

This is where the community's demonstrations come from. A **teaching
frame** here is one play: the state facts the reflex saw, the option it
chose, and what the world measured afterwards. The world's own log is the
only place those three sit together.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = ["LedgerPlay", "LedgerEpisode", "WorldLedgerReader"]


@dataclass(frozen=True)
class LedgerPlay:
    """One play, as the community's log recorded it."""

    seq: int
    at: str
    bot: str
    role: str
    skill_id: str
    facts: dict[str, Any]
    outcome: dict[str, Any]

    @property
    def result(self) -> str:
        return str(self.outcome.get("result", "partial"))

    @property
    def score(self) -> float | None:
        """The world's reward for this play: one number, or none.

        The same arithmetic as ``PlayRecord.reward``: a partial carries no
        reward, because "we could not measure this" is not "this wins half
        the time".
        """
        score = self.outcome.get("score")
        if score is not None:
            try:
                return float(score)
            except (TypeError, ValueError):
                return None
        if self.result == "partial":
            return None
        return {"win": 1.0, "lose": 0.0}.get(self.result)

    @property
    def when(self) -> datetime:
        stamp = self.at.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return datetime.fromtimestamp(0, tz=timezone.utc)


@dataclass
class LedgerEpisode:
    """A run of plays by one bot, in the order they happened."""

    bot: str
    plays: list[LedgerPlay] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.plays)

    @property
    def first_at(self) -> str:
        return self.plays[0].at if self.plays else ""

    @property
    def last_at(self) -> str:
        return self.plays[-1].at if self.plays else ""


class WorldLedgerReader:
    """The world's log of record, read only."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        # ``mode=ro``: the database cannot be written through this
        # connection. The WAL sidecar may still be touched by SQLite's
        # own locking, which is not a write to the log of record.
        uri = f"file:{self.path}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=30.0)

    def plays(self, *, since_seq: int | None = None) -> list[LedgerPlay]:
        """Every play in the log, oldest first."""
        query = (
            "SELECT seq, at, payload FROM audit WHERE type = 'tile.played'"
        )
        params: list[Any] = []
        if since_seq is not None:
            query += " AND seq > ?"
            params.append(int(since_seq))
        query += " ORDER BY seq"

        out: list[LedgerPlay] = []
        with self._connect() as connection:
            for seq, at, payload in connection.execute(query, params):
                try:
                    record = json.loads(payload)
                except (TypeError, ValueError):
                    continue
                context = dict(record.get("context") or {})
                out.append(
                    LedgerPlay(
                        seq=int(seq),
                        at=str(record.get("at") or at),
                        bot=str(context.get("bot", "")),
                        role=str(context.get("role", "")),
                        skill_id=str(record.get("skill_id", "")),
                        facts=context,
                        outcome=dict(record.get("outcome") or {}),
                    )
                )
        return out

    def episodes(
        self,
        *,
        gap_seconds: float = 600.0,
        min_plays: int = 1,
        limit: int | None = None,
        plays: Sequence[LedgerPlay] | None = None,
    ) -> list[LedgerEpisode]:
        """The community's plays, folded into episodes.

        An episode is one bot's run of plays with no silence longer than
        ``gap_seconds`` in it. The world ticks every two seconds and a
        play lands every few tens of seconds, so ten minutes of silence
        means the world moved on; the split is a reading of the log, not a
        fact the log states, and the gap is a parameter so it can be
        changed and said out loud.

        The four builders **interleave** in the log, so the split is per
        bot and then on the silence. Splitting on the log's order alone
        would make every handover between two bots a new episode — 43,000
        episodes of one play each, which is not what a demonstration is.
        """
        rows = list(plays) if plays is not None else self.plays()
        by_bot: dict[str, list[LedgerPlay]] = {}
        for play in rows:
            by_bot.setdefault(play.bot, []).append(play)

        episodes: list[LedgerEpisode] = []
        for bot, stream in by_bot.items():
            current: LedgerEpisode | None = None
            previous: LedgerPlay | None = None
            for play in stream:
                if (
                    current is None
                    or previous is None
                    or (play.when - previous.when).total_seconds() > gap_seconds
                ):
                    current = LedgerEpisode(bot=bot, plays=[])
                    episodes.append(current)
                current.plays.append(play)
                previous = play
        episodes = [episode for episode in episodes if len(episode) >= min_plays]
        episodes.sort(key=lambda episode: episode.plays[0].seq)
        if limit is not None:
            episodes = episodes[:limit]
        return episodes

    def skill_ids(self, plays: Iterable[LedgerPlay] | None = None) -> list[str]:
        """Every option the community chose, in the log."""
        rows = list(plays) if plays is not None else self.plays()
        return sorted({play.skill_id for play in rows if play.skill_id})
