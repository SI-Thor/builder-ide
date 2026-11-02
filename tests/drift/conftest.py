"""A small, made-up world ledger, so the tests do not need the real one.

The real ledger is 113 MB and it is *running*; a test that reads it
would be a test that depends on a live world. So the fixture builds a
tiny SQLite file with the same shape — one ``audit`` table, the same
event types, the same payload keys — and the tests read that.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

BASE = 1_700_000_000.0  # a fixed epoch second, so nothing depends on now


def _stamp(offset: float) -> str:
    from datetime import datetime, timezone

    return (
        datetime.fromtimestamp(BASE + offset, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S")
        + "Z"
    )


def _play(agent: str, offset: float, result: str = "win", gpu: float = 0.001) -> dict:
    return {
        "at": _stamp(offset),
        "actor": json.dumps({"id": agent, "kind": "character", "via": "reflex"}),
        "type": "tile.played",
        "subject": json.dumps({"skill": "skill_x"}),
        "payload": json.dumps(
            {
                "context": {"bot": agent},
                "outcome": {"result": result},
                "cost": {
                    "gpu_minutes": gpu,
                    "hosted_cents": 0.0,
                    "wall_seconds": 0.01,
                },
            }
        ),
    }


def _verdict(
    agent: str | None,
    offset: float,
    refused: bool = False,
    error: str | None = None,
    gpu: float = 0.001,
) -> dict:
    payload = {
        "author": "judge@d1:d1-2B",
        "refused": refused,
        "error": {"code": error} if error else None,
        "judgments": [{"qid": agent, "confidence": 0.7}] if agent else [],
        "cost": {"gpu_minutes": gpu, "hosted_cents": 0.0},
    }
    return {
        "at": _stamp(offset),
        "actor": json.dumps({"id": "judge@d1:d1-2B", "kind": "core", "via": "judge"}),
        "type": "judge.verdict",
        "subject": json.dumps({"entity_kind": "judgment"}),
        "payload": json.dumps(payload),
    }


def _violation(agent: str, offset: float, rule: str = "no_grief") -> dict:
    return {
        "at": _stamp(offset),
        "actor": json.dumps({"id": agent, "kind": "character", "via": "bot"}),
        "type": "drift.rule_violation",
        "subject": json.dumps({"rule": rule}),
        "payload": json.dumps({"agent": agent, "rule": rule, "detail": "mined a human block"}),
    }


def _write(path: Path, rows: list[dict]) -> Path:
    connection = sqlite3.connect(path)
    connection.execute(
        """create table audit (
            seq integer primary key autoincrement,
            id text not null unique,
            at text not null,
            actor text not null,
            type text not null,
            subject text not null,
            payload text not null,
            artifact text
        )"""
    )
    for index, row in enumerate(rows):
        connection.execute(
            "insert into audit (id, at, actor, type, subject, payload) "
            "values (?, ?, ?, ?, ?, ?)",
            (
                f"id-{index}",
                row["at"],
                row["actor"],
                row["type"],
                row["subject"],
                row["payload"],
            ),
        )
    connection.commit()
    connection.close()
    return path


@pytest.fixture()
def steady_ledger(tmp_path: Path) -> Path:
    """Two agents playing steadily, and a judge that answers."""
    rows: list[dict] = []
    for step in range(60):
        offset = step * 10.0
        rows.append(_play("Kite", offset))
        rows.append(_play("Pebble", offset + 1.0, result="lose"))
        rows.append(_verdict("Kite", offset + 0.5))
        rows.append(_verdict("Pebble", offset + 0.6))
    return _write(tmp_path / "steady.sqlite3", rows)


@pytest.fixture()
def stalled_ledger(tmp_path: Path) -> Path:
    """An agent that plays, stops for ten minutes, then plays again."""
    rows: list[dict] = []
    for step in range(20):
        offset = step * 10.0
        rows.append(_play("Kite", offset))
        rows.append(_verdict("Kite", offset + 0.5))
    # Twenty minutes of nothing: the gaps keep growing.
    for step in range(140, 160):
        offset = step * 10.0
        rows.append(_play("Kite", offset))
        rows.append(_verdict("Kite", offset + 0.5))
    return _write(tmp_path / "stalled.sqlite3", rows)


@pytest.fixture()
def declining_ledger(tmp_path: Path) -> Path:
    """An agent that wins for five windows and then stops winning.

    Ten windows of five minutes, thirty plays each: the first five
    windows win, the last five lose. Long enough that the success
    signal's trailing window can be all losses.
    """
    rows: list[dict] = []
    for step in range(300):
        offset = step * 10.0
        result = "win" if step < 150 else "lose"
        rows.append(_play("Kite", offset, result=result))
        rows.append(_verdict("Kite", offset + 0.5))
    return _write(tmp_path / "declining.sqlite3", rows)


@pytest.fixture()
def refusing_ledger(tmp_path: Path) -> Path:
    """A judge that answers for a while and then starts refusing.

    The first half answers, the second half refuses: a rate gate can
    only see a **change**, so a world that was broken from its first
    window has nothing to trigger on.
    """
    rows: list[dict] = []
    for step in range(60):
        offset = step * 10.0
        refusing = step >= 30
        rows.append(
            _verdict(
                "Kite",
                offset + 0.5,
                refused=refusing,
                error="transport_error" if refusing else None,
            )
        )
    return _write(tmp_path / "refusing.sqlite3", rows)


@pytest.fixture()
def violating_ledger(tmp_path: Path) -> Path:
    """A world with one rule violation in it."""
    rows: list[dict] = []
    for step in range(20):
        offset = step * 10.0
        rows.append(_play("Kite", offset))
        rows.append(_verdict("Kite", offset + 0.5))
    rows.append(_violation("Kite", 100.0))
    return _write(tmp_path / "violating.sqlite3", rows)


def _yield(
    bots: list[str],
    offset: float,
    reason: str = "the box has 3 GB free; the rule is 25 GB",
) -> dict:
    """One ``drift.yield`` event: the world stood aside, naming who."""
    return {
        "at": _stamp(offset),
        "actor": json.dumps({"id": "reflex", "kind": "core", "via": "admission"}),
        "type": "drift.yield",
        "subject": json.dumps({"yield": "box-busy"}),
        "payload": json.dumps({"reason": reason, "bots": bots, "count": len(bots)}),
    }


@pytest.fixture()
def yielding_ledger(tmp_path: Path) -> Path:
    """An agent that waits twice: once because the box is busy, once
    for no reason the ledger can name.

    Kite plays every 10 s, then stands aside for ten minutes with a
    yield every minute (the box busy — the negative control), then
    plays again, then goes silent for seven minutes with **no** yield
    (a real stall), then plays again. Pebble plays steadily
    throughout, so the windows exist and the silence is Kite's alone.

    The two waits are the same silence; only the yield events tell
    them apart, and only one of them is drift.
    """
    rows: list[dict] = []
    for step in range(20):  # offsets 0..190: steady play
        rows.append(_play("Kite", step * 10.0))
    for step in range(20, 159):  # Pebble keeps the world alive
        rows.append(_play("Pebble", step * 10.0, result="lose"))
    # the busy box: a yield every minute across the ten-minute wait
    for offset in range(240, 800, 60):
        rows.append(_yield(["Kite"], float(offset)))
    for step in range(80, 99):  # offsets 800..980: play resumes
        rows.append(_play("Kite", step * 10.0))
    # the unexplained silence: offsets 990..1390, no yield at all
    for step in range(140, 159):  # offsets 1400..1580: play resumes
        rows.append(_play("Kite", step * 10.0))
    return _write(tmp_path / "yielding.sqlite3", rows)
