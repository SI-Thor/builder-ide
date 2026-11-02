"""The join between the world's state and the world's story.

A rewind point on the ledger is a row; a snapshot is a state; the two meet
at the ledger's ``seq``. These tests are the join, on rows and manifests
made by hand — no server, no world, no database.
"""

from __future__ import annotations

from core.rewind.ledger import LedgerRow, ledger_from_rows
from core.rewind.snapshot import (
    Placement,
    classify_event,
    nearest_snapshot_at_or_before,
    rewind_plan,
)
from mcsnap.manifest import Manifest


def _manifest(snapshot_id: str, seq: int | None) -> Manifest:
    return Manifest(
        snapshot_id=snapshot_id,
        taken_at="2026-11-01T12:00:00.000Z",
        world_dir=f"/tmp/{snapshot_id}/world",
        ledger={"path": "/tmp/ledger.sqlite3", "seq": seq},
    )


def _row(seq: int, kind: str, actor: str = "Timber", at: float = 1000.0) -> LedgerRow:
    return LedgerRow(
        seq=seq,
        at=at,
        actor=actor,
        agent=actor,
        kind=kind,
        entity_id="skill_1",
        verdict="",
        payload={},
    )


def _ledger():
    return ledger_from_rows(
        [
            _row(1, "tile.played", at=1000.0),
            _row(2, "judge.verdict", at=1001.0),
            _row(3, "tile.played", "Kite", at=1002.0),
            _row(4, "tile.played", at=1003.0),
        ]
    )


# -- the nearest snapshot ----------------------------------------------------


def test_the_nearest_snapshot_at_or_before_is_chosen() -> None:
    snapshots = [_manifest("a", 10), _manifest("b", 20), _manifest("c", 30)]
    assert nearest_snapshot_at_or_before(snapshots, 25).snapshot_id == "b"
    assert nearest_snapshot_at_or_before(snapshots, 20).snapshot_id == "b"
    assert nearest_snapshot_at_or_before(snapshots, 5) is None


def test_a_snapshot_with_no_ledger_row_cannot_be_placed_in_the_story() -> None:
    snapshots = [_manifest("a", None), _manifest("b", 20)]
    assert nearest_snapshot_at_or_before(snapshots, 25).snapshot_id == "b"


# -- what a row means for a restore -----------------------------------------


def test_a_judges_verdict_is_a_record_not_world_state() -> None:
    verdict, reason, placement = classify_event(_row(2, "judge.verdict"), [])
    assert verdict == "recorded"
    assert "record" in reason
    assert placement is None


def test_a_block_placement_can_be_put_back() -> None:
    row = _row(1, "tile.played", at=1000.0)
    journal = [
        Placement(at=1000.2, bot="Timber", op="place", block="stone", x=1, y=2, z=3)
    ]
    verdict, reason, placement = classify_event(row, journal)
    assert verdict == "reappliable"
    assert placement is not None
    assert (placement.x, placement.y, placement.z) == (1, 2, 3)


def test_a_mined_block_cannot_be_put_back() -> None:
    row = _row(1, "tile.played", at=1000.0)
    journal = [
        Placement(at=1000.2, bot="Timber", op="mine", block="stone", x=1, y=2, z=3)
    ]
    verdict, reason, _ = classify_event(row, journal)
    assert verdict == "lost"
    assert "mined" in reason


def test_a_play_with_no_journal_entry_is_lost() -> None:
    verdict, reason, placement = classify_event(_row(1, "tile.played"), [])
    assert verdict == "lost"
    assert "does not say what this play did" in reason
    assert placement is None


def test_the_journal_is_joined_by_the_bots_own_name() -> None:
    row = _row(1, "tile.played", actor="Timber", at=1000.0)
    journal = [
        Placement(at=1000.1, bot="Kite", op="place", block="stone", x=1, y=2, z=3)
    ]
    verdict, _, _ = classify_event(row, journal)
    assert verdict == "lost"


# -- the plan ----------------------------------------------------------------


def test_the_plan_keeps_the_work_between_the_snapshot_and_the_point() -> None:
    snapshots = [_manifest("a", 1)]
    journal = [
        Placement(at=1002.1, bot="Kite", op="place", block="stone", x=1, y=2, z=3)
    ]
    plan = rewind_plan(3, snapshots, _ledger(), placements=journal)
    assert plan.snapshot_id == "a"
    assert plan.snapshot_seq == 1
    assert [row.seq for row in plan.kept] == [2, 3]
    assert len(plan.reappliable) == 1
    assert plan.reappliable[0].actor == "Kite"
    assert plan.after_point == 1


def test_the_selection_drops_the_work_the_human_struck_out() -> None:
    from core.rewind.selection import parse

    snapshots = [_manifest("a", 1)]
    plan = rewind_plan(
        3, snapshots, _ledger(), selection=parse("actor = Kite"), placements=[]
    )
    assert [row.seq for row in plan.kept] == [3]
    assert [row.seq for row, _ in plan.dropped] == [2]
    assert plan.dropped[0][1]


def test_a_point_before_every_snapshot_says_so() -> None:
    plan = rewind_plan(5, [_manifest("a", 10)], _ledger())
    assert plan.snapshot_id is None
    assert "no snapshot at or before" in plan.note


def test_the_plan_is_plain_data_for_the_report() -> None:
    plan = rewind_plan(3, [_manifest("a", 1)], _ledger(), placements=[])
    payload = plan.to_dict()
    assert payload["point_seq"] == 3
    assert payload["snapshot_id"] == "a"
    assert "kept" in payload and "lost" in payload
