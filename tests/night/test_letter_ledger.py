"""The letter's decision numbers equal the ledger's.

The night-v5 letter said "1 of 5 decisions answered locally (4 went to the
cloud)" while the same run's ledger held 251 ``judge.verdict`` rows, 245 of
them on the local d1-3B. Both counts were honestly derived; they counted
different things (the morning's in-memory seat list against the ledger's
one-row-per-attempt receipt), and the letter read the wrong one. These
tests pin the letter to the ledger: whatever the morning's ``decisions``
block claims, the letter speaks the ledger's split — the same split
``measure.py`` prints — and the facts transcriber produces the same
numbers from the same rows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "docs" / "lab" / "night-v6-scripts"
sys.path.insert(0, str(SCRIPTS))

from decision_counts import count_ledger  # noqa: E402
import write_letter  # noqa: E402

from core.night.ledger import SQLiteLedger
from core.records import Actor

JUDGE = Actor(kind="critic", id="test")
NIGHT_V5 = Path.home() / "lm-wt" / "night-v5" / "artifacts" / "night-v5"


def _verdict(author: str | None, gate: str = "surfaced") -> dict:
    payload = {
        "task": "sea-state.v1",
        "backend": "d1" if author and author.startswith("judge@d1") else "jev",
        "model": "d1-3B" if author and author.startswith("judge@d1") else "jev-latest",
        "author": author,
        "judgments": [{"qid": "sea", "gate": gate}],
        "latency_seconds": 0.05,
    }
    return payload


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    """The night-v5 shape, in miniature: 251 rows, 245 local, 4 cloud,
    2 refusals."""
    book = SQLiteLedger(tmp_path / "ledger.db")
    for _ in range(245):
        book.append(type="judge.verdict", actor=JUDGE,
                    subject={"entity_kind": "night", "entity_id": "t"},
                    payload=_verdict("judge@d1:d1-3B"))
    for _ in range(4):
        book.append(type="judge.verdict", actor=JUDGE,
                    subject={"entity_kind": "night", "entity_id": "t"},
                    payload=_verdict("judge@jev:jev-latest", gate="escalate"))
    for _ in range(2):
        book.append(type="judge.verdict", actor=JUDGE,
                    subject={"entity_kind": "night", "entity_id": "t"},
                    payload=_verdict(None))
    book.close()
    return tmp_path / "ledger.db"


def _morning() -> dict:
    """A morning whose decisions block still tells the old, wrong story."""
    return {
        "night_id": "night-v6",
        "wall_minutes": 288.57,
        "props": {"kept": 3, "winners": [
            {"request": "crate"}, {"request": "lantern"},
            {"request": "anvil"}]},
        "decisions": {"count": 5, "local": 1, "escalated": 4, "surfaced": 0},
        "judge": {"model": "d1-3B", "route_probe": {"accuracy": 0.5208}},
        "critic": {
            "prior": {"groups": 2, "largest_group": 38, "smallest_group": 10,
                      "ghost_threshold": 0.05, "gate_live": True},
            "library": {"approved": 10},
            "signals": [{"stage": "mesh", "ghost": False} for _ in range(18)],
        },
        "memory": {"lease_wait_s": 0.2},
    }


def test_count_ledger_splits_by_author(ledger: Path) -> None:
    counted = count_ledger(ledger)
    assert counted["count"] == 251
    assert counted["local"] == 245
    assert counted["escalated"] == 4
    assert counted["unattributed"] == 2
    assert counted["rungs"] == {"judge@d1:d1-3B": 245,
                                "judge@jev:jev-latest": 4, "?": 2}


def test_letter_speaks_the_ledger_not_the_morning(ledger: Path) -> None:
    letter = write_letter.the_letter(_morning(), ledger=ledger)
    assert "245 of 251 judgments answered locally (4 went to the cloud, 2 were refusals)" in letter
    assert "1 of 5" not in letter
    assert len(letter.split()) <= 150


def test_letter_prefers_the_morning_s_ledger_block(ledger: Path) -> None:
    morning = _morning()
    counted = count_ledger(ledger)
    morning["decisions"]["ledger"] = counted
    letter = write_letter.the_letter(morning, ledger=None)
    assert "245 of 251 judgments answered locally" in letter


def test_letter_falls_back_to_the_morning_without_a_ledger() -> None:
    letter = write_letter.the_letter(_morning(), ledger=None)
    assert "1 of 5" in letter  # the pre-night letter, honestly labelled


def test_facts_transcriber_agrees_with_the_letter(ledger: Path) -> None:
    """The transcriber writes what the shared counter says (its main() is a
    thin wrapper around the same call), and the letter's facts come from
    the same call on the same rows — the three cannot disagree."""
    counted = count_ledger(ledger)
    letter_facts = write_letter.facts(_morning(), ledger=ledger)
    for key in ("count", "local", "escalated", "unattributed", "surfaced"):
        assert letter_facts[key] == counted[key], key


@pytest.mark.skipif(not (NIGHT_V5 / "ledger.db").exists()
                    or not (NIGHT_V5 / "morning.json").exists(),
                    reason="the night-v5 artifacts are not on this box")
def test_the_real_night_v5_letter_now_speaks_its_ledger() -> None:
    morning = json.loads((NIGHT_V5 / "morning.json").read_text())
    letter = write_letter.the_letter(morning, ledger=NIGHT_V5 / "ledger.db")
    assert "245 of 251 judgments answered locally (4 went to the cloud, 2 were refusals)" in letter
    assert "1 of 5" not in letter
    assert len(letter.split()) <= 150
