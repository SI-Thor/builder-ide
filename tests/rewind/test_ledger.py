"""The ledger readers: the world's ledger, the core's ledger, a round log."""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.rewind import (
    LedgerRow,
    read_bevy_dump,
    read_bevy_header,
    read_core_ledger,
    read_world_ledger,
)
from core.rewind.ledger import EPOCH, TICK


def _audit_table(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE audit ("
        "seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, at TEXT, actor TEXT, "
        "type TEXT, subject TEXT, payload TEXT, artifact TEXT)"
    )
    connection.commit()
    connection.close()


def _row(path, *, at, actor, kind, subject, payload) -> None:
    connection = sqlite3.connect(path)
    cursor = connection.execute(
        "INSERT INTO audit (id, at, actor, type, subject, payload, artifact) "
        "VALUES ('', ?, ?, ?, ?, ?, NULL)",
        (at, json.dumps(actor), kind, json.dumps(subject), json.dumps(payload)),
    )
    seq = cursor.lastrowid
    connection.execute("UPDATE audit SET id = ? WHERE seq = ?", (f"aud_{seq:04d}", seq))
    connection.commit()
    connection.close()


def test_the_world_ledger_is_read_with_its_own_attribution(tmp_path):
    path = tmp_path / "world-ledger.sqlite3"
    _audit_table(path)
    _row(
        path,
        at="2026-11-01T06:25:14Z",
        actor={"agent": None, "id": "Pebble", "kind": "character", "via": "reflex"},
        kind="tile.played",
        subject={"family": "", "skill": "skill_14fd7774a036"},
        payload={
            "skill_id": "skill_14fd7774a036",
            "context": {"bot": "Pebble"},
            "outcome": {"result": "lose", "score": 0.0},
        },
    )
    _row(
        path,
        at="2026-11-01T05:40:58Z",
        actor={"agent": None, "id": "judge@d1:d1-2B", "kind": "core", "via": "judge"},
        kind="judge.verdict",
        subject={"entity_id": "sha256:abc", "entity_kind": "judgment"},
        payload={
            "refused": False,
            "judgments": [{"qid": "Pebble", "distribution": {"skill_a": 0.2, "skill_b": 0.8}}],
        },
    )

    ledger = read_world_ledger(path)
    assert ledger.time_unit == EPOCH
    assert len(ledger.rows) == 2

    play = ledger.rows[0]
    assert play.actor == "Pebble"
    assert play.agent == "Pebble"
    assert play.entity_id == "skill_14fd7774a036"
    assert play.verdict == "lose"
    assert play.at == pytest.approx(1793514314.0)  # 2026-11-01T06:25:14Z

    verdict = ledger.rows[1]
    assert verdict.actor == "judge@d1:d1-2B"
    assert verdict.agent == "Pebble"
    assert verdict.verdict == "skill_b"


def test_the_world_ledger_is_opened_read_only(tmp_path):
    path = tmp_path / "world-ledger.sqlite3"
    _audit_table(path)
    _row(
        path,
        at="2026-11-01T06:25:14Z",
        actor={"id": "Kite"},
        kind="tile.played",
        subject={"skill": "skill_1"},
        payload={"context": {"bot": "Kite"}, "outcome": {"result": "win"}},
    )
    ledger = read_world_ledger(path)
    assert ledger.rows[0].kind == "tile.played"


def test_the_core_ledger_is_read_with_its_own_attribution(tmp_path):
    path = tmp_path / "core-ledger.sqlite3"
    _audit_table(path)
    _row(
        path,
        at="2026-11-01T06:25:14Z",
        actor={"kind": "owner", "id": "casey", "agent": None},
        kind="edit.proposed",
        subject={"entity_kind": "edit", "entity_id": "ed_0002"},
        payload={"edit": "ed_0002", "ops": [], "result": "accepted"},
    )
    ledger = read_core_ledger(path)
    row = ledger.rows[0]
    assert row.actor == "casey"
    assert row.agent == "casey"
    assert row.entity_id == "ed_0002"
    assert row.verdict == "accepted"


def test_a_round_log_is_read_in_ticks():
    dump = "\n".join(
        [
            json.dumps(
                {
                    "seed": 7,
                    "start_tick": 0,
                    "last_tick": 300,
                    "ruleset": "beacons",
                    "roster": [{"agent": 0, "squad": 0, "role": "Leader"}],
                }
            ),
            json.dumps(
                {
                    "arrived": 120,
                    "decision": {
                        "apply_tick": 120,
                        "source": {"Agent": 0},
                        "seq": 1,
                        "kind": {"ActionOn": {"GoTo": {"x": 3, "y": 4}}},
                        "provenance": "Test",
                    },
                }
            ),
            json.dumps(
                {
                    "arrived": 200,
                    "decision": {
                        "apply_tick": 150,
                        "source": {"Agent": 3},
                        "seq": 1,
                        "kind": {"ActionOn": "Hold"},
                        "provenance": "Test",
                    },
                }
            ),
        ]
    )
    header = read_bevy_header(dump)
    assert header["seed"] == 7
    assert header["last_tick"] == 300

    ledger = read_bevy_dump(dump)
    assert ledger.time_unit == TICK
    assert len(ledger.rows) == 2

    first = ledger.rows[0]
    assert first.actor == "agent:0"
    assert first.agent == "agent:0"
    assert first.kind == "ActionOn"
    assert first.entity_id == "GoTo"
    assert first.at == 120.0

    # A decision that arrived late is applied on its arrival tick: the
    # sequencer's rule, read the same way here.
    late = ledger.rows[1]
    assert late.actor == "agent:3"
    assert late.entity_id == "Hold"
    assert late.at == 200.0
    assert late.payload["apply_tick"] == 150
