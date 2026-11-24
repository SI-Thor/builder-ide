#!/usr/bin/env python3
"""The live world's log, read only.

The community's demonstrations come from the world's ledger, and the gym
must not write to it. These checks pin both halves: that the fold is
right (a play is a play; a partial carries no reward), and that the
connection cannot write.

Run on the Thor, from the repo root:

    .venv/bin/python gym/tests/test_gym_ledger.py

Needs no world: the ledger is built here, in a temporary file, with the
world's own table shape. Takes under a second.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))

from agent_world_gym.ledger import WorldLedgerReader  # noqa: E402

FAILS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILS
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def build_ledger(path: Path, rows: list[dict]) -> None:
    """A ledger with the world's own table shape."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,"
        " at TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, subject TEXT NOT NULL,"
        " payload TEXT NOT NULL, artifact TEXT)"
    )
    for index, row in enumerate(rows):
        connection.execute(
            "INSERT INTO audit (id, at, actor, type, subject, payload) VALUES (?,?,?,?,?,?)",
            (
                f"row-{index}",
                row["at"],
                json.dumps({"kind": "character", "id": row["bot"], "via": "reflex"}),
                "tile.played",
                json.dumps({"skill": row["skill_id"], "family": ""}),
                json.dumps(row["payload"]),
            ),
        )
    connection.commit()
    connection.close()


def play(bot: str, skill_id: str, at: str, result: str, score=None, role: str = "gatherer") -> dict:
    return {
        "at": at,
        "bot": bot,
        "skill_id": skill_id,
        "payload": {
            "id": f"play_{bot}",
            "at": at,
            "skill_id": skill_id,
            "skill_version": 1,
            "context": {
                "bot": bot,
                "role": role,
                "phase": "day",
                "time_of_day": 0.5,
                "health": 20,
                "food": 20,
                "has_material": False,
                "humans": 0,
                "human_present": False,
                "confidence": 0.5,
                "chooser_reason": "the community went on",
            },
            "outcome": {
                "result": result,
                "measure": "sealed_prediction",
                "score": score,
                "detail": "",
            },
            "cost": {"wall_seconds": 1.0, "gpu_minutes": 0.0, "hosted_cents": 0},
            "chooser": "bandit/ctx-v1+judge",
            "chooser_version": "1",
            "propensity": None,
            "candidates": [],
        },
    }


def test_the_fold() -> None:
    print("the fold")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.sqlite3"
        build_ledger(
            path,
            [
                play("Pebble", "skill_aaa", "2026-11-02T10:00:00Z", "win", 1),
                play("Pebble", "skill_bbb", "2026-11-02T10:00:30Z", "lose", 0),
                play("Pebble", "skill_ccc", "2026-11-02T10:01:00Z", "partial", None),
                play("Kite", "skill_aaa", "2026-11-02T10:02:00Z", "win", 1),
            ],
        )
        reader = WorldLedgerReader(path)
        plays = reader.plays()
        check("every play is folded out", len(plays) == 4, str(len(plays)))
        check("the bot is read from the context", plays[0].bot == "Pebble", plays[0].bot)
        check("the option is read from the record", plays[0].skill_id == "skill_aaa")
        check("the facts are the context", plays[0].facts["phase"] == "day")
        check("a win is worth one", plays[0].score == 1.0, str(plays[0].score))
        check("a loss is worth nothing", plays[1].score == 0.0, str(plays[1].score))
        check("a partial carries no reward", plays[2].score is None, str(plays[2].score))


def test_the_episode_split() -> None:
    print("the episode split")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.sqlite3"
        build_ledger(
            path,
            [
                play("Pebble", "skill_aaa", "2026-11-02T10:00:00Z", "win", 1),
                play("Pebble", "skill_bbb", "2026-11-02T10:00:30Z", "win", 1),
                play("Pebble", "skill_ccc", "2026-11-02T11:30:00Z", "win", 1),
                play("Kite", "skill_aaa", "2026-11-02T11:31:00Z", "win", 1),
            ],
        )
        reader = WorldLedgerReader(path)
        episodes = reader.episodes(gap_seconds=600)
        check("a long silence ends an episode", len(episodes) == 3, str(len(episodes)))
        check("the run before the silence is one episode", len(episodes[0].plays) == 2,
              str(len(episodes[0].plays)))
        check("another bot is another episode", episodes[-1].bot == "Kite", episodes[-1].bot)
        tight = reader.episodes(gap_seconds=7200)
        check("a wider gap folds the runs together", len(tight) == 2, str(len(tight)))


def test_interleaved_bots_are_not_fragmented() -> None:
    print("interleaved bots")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.sqlite3"
        rows = []
        for index in range(6):
            # The community's four builders take turns in the log: every
            # handover is a different bot's play.
            rows.append(
                play("Pebble" if index % 2 == 0 else "Kite", "skill_aaa",
                     f"2026-11-02T10:0{index // 2}:{10 * (index % 2):02d}Z", "win", 1)
            )
        build_ledger(path, rows)
        reader = WorldLedgerReader(path)
        episodes = reader.episodes(gap_seconds=600)
        check("two bots make two episodes, not six", len(episodes) == 2, str(len(episodes)))
        check("each episode holds that bot's own plays", len(episodes[0].plays) == 3,
              str(len(episodes[0].plays)))
        check("the episodes keep the log's order", episodes[0].bot == "Pebble", episodes[0].bot)


def test_the_reader_cannot_write() -> None:
    print("the reader cannot write")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.sqlite3"
        build_ledger(path, [play("Pebble", "skill_aaa", "2026-11-02T10:00:00Z", "win", 1)])
        reader = WorldLedgerReader(path)
        try:
            connection = reader._connect()
            connection.execute("DELETE FROM audit")
        except sqlite3.OperationalError as exc:
            check("a write through the reader is refused", True)
            check("the refusal says read-only", "readonly" in str(exc).lower() or "read-only" in str(exc).lower(),
                  str(exc))
        else:
            check("a write through the reader is refused", False, "the delete went through")
        finally:
            try:
                connection.close()
            except Exception:
                pass
        check("the ledger still holds its rows", len(reader.plays()) == 1)


if __name__ == "__main__":
    test_the_fold()
    test_the_episode_split()
    test_interleaved_bots_are_not_fragmented()
    test_the_reader_cannot_write()
    print(f"\n{'all checks passed' if FAILS == 0 else f'{FAILS} check(s) FAILED'}")
    sys.exit(1 if FAILS else 0)
