"""Putting a snapshot back, by swap."""

from __future__ import annotations

from pathlib import Path

from mcsnap.restore import restore
from mcsnap.snapshot import take_snapshot


def _server(tmp_path: Path) -> Path:
    """A server directory holding a world of its own."""
    server = tmp_path / "server"
    server.mkdir()
    (server / "world").mkdir()
    return server


def test_a_restore_puts_the_files_back(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    server = _server(tmp_path)
    live = server / "world"
    (live / "level.dat").write_bytes(b"a different world")

    restored = restore(server, result.directory)
    assert restored.verified
    assert restored.problems == []
    assert (live / "level.dat").read_bytes() == (fake_world / "level.dat").read_bytes()


def test_a_restore_keeps_the_world_it_replaced(fake_world: Path, tmp_path: Path) -> None:
    """The world that was there is kept beside the one that came back."""
    result = take_snapshot(fake_world, tmp_path / "store")
    server = _server(tmp_path)
    live = server / "world"
    (live / "level.dat").write_bytes(b"the world that was there")

    restored = restore(server, result.directory)
    assert restored.previous_world is not None
    assert restored.previous_world.exists()
    assert (restored.previous_world / "level.dat").read_bytes() == b"the world that was there"


def test_a_restore_that_does_not_verify_says_so(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    server = _server(tmp_path)

    # A snapshot whose file was changed after it was taken must not verify.
    (result.directory / "world" / "level.dat").write_bytes(b"changed")
    restored = restore(server, result.directory)
    assert restored.verified is False
    assert restored.problems


def test_the_restore_timings_are_measured(fake_world: Path, tmp_path: Path) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    server = _server(tmp_path)
    restored = restore(server, result.directory)
    for step in ("move_aside", "copy", "verify"):
        assert step in restored.timings


def test_the_server_is_stopped_and_started_around_the_swap(
    fake_world: Path, tmp_path: Path
) -> None:
    result = take_snapshot(fake_world, tmp_path / "store")
    server = _server(tmp_path)
    calls: list[str] = []
    restored = restore(
        server,
        result.directory,
        stop=lambda: calls.append("stop"),
        start=lambda: calls.append("start"),
    )
    assert calls == ["stop", "start"]
    assert restored.stopped is True
    assert restored.started is True
