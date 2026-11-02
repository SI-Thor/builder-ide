"""The Bevy proof: rewind a round, keep one actor's work, drop another's.

The Bevy world is the one where byte-identical replay holds, so it is where
the rewind is proved rather than asserted. Two mechanisms build the same
world — the round's own ``lm branch --drop`` and this package's replay of the
kept decisions — and the diff between their logs is the proof.

These tests need the ``lm`` tool; they are skipped where it is not.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.rewind import BevyWorld, keep_from_round, parse
from core.rewind.ledger import read_bevy_header

LM = shutil.which("lm")

pytestmark = pytest.mark.skipif(
    LM is None, reason="the lm tool is not on this box"
)


def _decision(agent: int, tick: int, seq: int, x: int, y: int) -> str:
    return json.dumps(
        {
            "arrived": tick,
            "decision": {
                "apply_tick": tick,
                "source": {"Agent": agent},
                "seq": seq,
                "kind": {"ActionOn": {"GoTo": {"x": x, "y": y}}},
                "provenance": "Test",
            },
        }
    )


def _ledger() -> str:
    """Two actors, each with work before and after the rewind point."""
    return "\n".join(
        [
            _decision(0, 100, 1, 12, 9),
            _decision(3, 100, 1, 30, 30),
            _decision(0, 200, 2, 40, 12),
            _decision(3, 200, 2, 18, 44),
        ]
    ) + "\n"


@pytest.fixture()
def world() -> BevyWorld:
    return BevyWorld(LM)


def test_a_round_replays_byte_identically(world: BevyWorld, tmp_path):
    """The property the Bevy world has and the Minecraft world does not."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(_ledger(), encoding="utf-8")
    log = tmp_path / "parent.lml"

    world.run(seed=5, ticks=300, out=log, inject=ledger)
    replay = world.replay(log)
    assert replay.ok, replay.output
    assert replay.hashes > 0


def test_the_fork_and_the_reference_are_the_same_world(world: BevyWorld, tmp_path):
    """Rewind to a tick, keep one actor's later work, drop another's.

    The fork is ``lm branch --at 150 --drop agent:3``: the round's own
    machinery. The reference is ``lm run --inject`` with the decisions the
    selection kept. They share nothing but the ledger they read.
    """
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(_ledger(), encoding="utf-8")
    parent = tmp_path / "parent.lml"
    world.run(seed=5, ticks=300, out=parent, inject=ledger)

    keep = keep_from_round(
        world,
        parent=parent,
        at=150,
        selection=parse("actor = agent:0"),
        out_dir=tmp_path / "out",
    )

    # One actor's later work was kept, the other's was dropped.
    assert keep.dropped_sources == ("agent:3",)
    assert keep.partial_sources == ()
    assert keep.identical is True, keep.diff.output if keep.diff else ""

    # The fork says what it did: a lineage at the rewind tick.
    header = read_bevy_header(world.dump(keep.fork, header=True))
    assert header["lineage"]["at"] == 150
    assert header["lineage"]["changes"] == 1

    # And the fork is a round in its own right: it replays to its hashes.
    assert world.replay(keep.fork).ok
    assert world.replay(keep.reference).ok


def test_the_drop_changes_the_world(world: BevyWorld, tmp_path):
    """The fork is not the parent: the dropped actor's work is gone."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(_ledger(), encoding="utf-8")
    parent = tmp_path / "parent.lml"
    world.run(seed=5, ticks=300, out=parent, inject=ledger)

    keep = keep_from_round(
        world,
        parent=parent,
        at=150,
        selection=parse("actor = agent:0"),
        out_dir=tmp_path / "out",
    )

    difference = world.diff(parent, keep.fork)
    assert not difference.identical, difference.output
    assert difference.tick is not None and difference.tick >= 150


def test_the_selection_keeps_what_it_names(world: BevyWorld, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(_ledger(), encoding="utf-8")
    parent = tmp_path / "parent.lml"
    world.run(seed=5, ticks=300, out=parent, inject=ledger)

    keep = keep_from_round(
        world,
        parent=parent,
        at=150,
        selection=parse("actor = agent:3"),
        out_dir=tmp_path / "out",
    )

    assert keep.dropped_sources == ("agent:0",)
    assert keep.identical is True
