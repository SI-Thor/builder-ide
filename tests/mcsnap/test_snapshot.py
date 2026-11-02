"""Taking a snapshot of a world, and what the manifest says about it."""

from __future__ import annotations

from pathlib import Path

import mcsnap.snapshot as snapshot_module
from mcsnap.manifest import MANIFEST_NAME, read_manifest
from mcsnap.snapshot import take_snapshot


def test_the_snapshot_says_what_it_copied(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    manifest = result.manifest
    assert manifest.snapshot_id
    assert manifest.totals["files"] == len(manifest.files)
    assert manifest.totals["bytes"] > 0
    assert manifest.world["seed"] == 4242
    assert manifest.world["tick"] == 1000
    assert manifest.world["day_time"] == 6000
    assert manifest.world["data_version"] == 3955
    assert (result.directory / MANIFEST_NAME).is_file()
    assert (result.directory / "world" / "level.dat").is_file()


def test_the_servers_own_console_is_used_in_the_right_order(
    fake_world: Path, tmp_path: Path
) -> None:
    """save-off, then the flush, then save-on, and the version at the end."""
    commands: list[str] = []
    take_snapshot(
        fake_world,
        tmp_path / "store",
        command=lambda command: commands.append(command) or "",
    )
    assert commands == ["save-off", "save-all flush", "save-on", "version"]


def test_the_manifest_carries_the_ledger_row_it_sits_behind(
    fake_world: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        snapshot_module,
        "ledger_head",
        lambda path: {"path": str(path), "seq": 5, "at": "2026-11-01T12:00:00Z"},
    )
    result = take_snapshot(
        fake_world, tmp_path / "store", ledger_path=tmp_path / "ledger.sqlite3"
    )
    assert result.manifest.ledger_seq == 5
    assert result.manifest.ledger["path"].endswith("ledger.sqlite3")


def test_the_snapshot_is_a_separate_tree_from_the_world(
    fake_world: Path, tmp_path: Path
) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    level = result.directory / "world" / "level.dat"
    before = level.read_bytes()
    (fake_world / "level.dat").write_bytes(b"a different world")
    assert level.read_bytes() == before


def test_the_manifest_lists_what_was_left_behind(
    fake_world: Path, tmp_path: Path
) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    skipped = {item["path"] for item in result.manifest.skipped}
    assert "session.lock" in skipped
    assert "level.dat_old" in skipped


def test_the_manifest_can_be_read_back(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    read_back = read_manifest(result.directory / MANIFEST_NAME)
    assert read_back.files == result.manifest.files
    assert read_back.snapshot_id == result.manifest.snapshot_id


def test_the_timings_are_measured(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    for step in ("save_off", "save_flush", "copy", "hash", "manifest"):
        assert step in result.timings
        assert result.timings[step] >= 0
