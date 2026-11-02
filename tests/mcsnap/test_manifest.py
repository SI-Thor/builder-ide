"""The manifest, and the verification that checks a restored world."""

from __future__ import annotations

from pathlib import Path

from mcsnap.manifest import (
    FileEntry,
    Manifest,
    manifest_from_dict,
    manifest_to_dict,
    read_manifest,
    sha256_file,
    verify_directory,
    write_manifest,
)


def _manifest(root: Path, *, extra: str = "") -> Manifest:
    entry = FileEntry(
        relpath="level.dat",
        size=10,
        sha256=sha256_file(root / "level.dat"),
        mtime=0.0,
        section="level",
    )
    files: tuple[FileEntry, ...] = (entry,)
    if extra:
        files = files + (
            FileEntry(
                relpath=extra,
                size=3,
                sha256="0" * 64,
                mtime=0.0,
                section="region",
            ),
        )
    return Manifest(
        snapshot_id="snap-test",
        taken_at="2026-11-01T00:00:00.000Z",
        world_dir=str(root),
        server={"paper_version": "1.21.11"},
        world={"tick": 100},
        ledger={"path": "/tmp/ledger.sqlite3", "seq": 42},
        files=files,
    )


def test_the_manifest_survives_a_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"0123456789")
    manifest = _manifest(source)
    path = write_manifest(manifest, tmp_path / "manifest.json")
    read_back = read_manifest(path)
    assert read_back.snapshot_id == manifest.snapshot_id
    assert read_back.ledger_seq == 42
    assert read_back.files == manifest.files
    assert manifest_to_dict(read_back) == manifest_to_dict(manifest)


def test_the_ledger_seq_is_the_join_to_the_story() -> None:
    manifest = Manifest(snapshot_id="s", taken_at="t", world_dir="w", ledger={"seq": 7})
    assert manifest.ledger_seq == 7
    assert Manifest(snapshot_id="s", taken_at="t", world_dir="w").ledger_seq is None


def test_a_verified_directory_has_no_problems(tmp_path: Path) -> None:
    source = tmp_path / "world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"0123456789")
    manifest = _manifest(source)
    assert verify_directory(source, manifest) == []


def test_a_file_the_manifest_names_and_the_world_does_not_have_is_a_problem(
    tmp_path: Path,
) -> None:
    source = tmp_path / "world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"0123456789")
    manifest = _manifest(source, extra="region/r.0.0.mca")
    problems = verify_directory(source, manifest)
    assert problems and "missing" in problems[0]


def test_a_changed_file_is_caught_by_its_hash(tmp_path: Path) -> None:
    """The check is by content: a file of the right size and wrong bytes fails."""
    source = tmp_path / "world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"0123456789")
    manifest = _manifest(source)
    (source / "level.dat").write_bytes(b"9876543210")
    problems = verify_directory(source, manifest)
    assert problems and "hash differs" in problems[0]


def test_a_manifest_from_a_dict_is_the_same_manifest(tmp_path: Path) -> None:
    source = tmp_path / "world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"0123456789")
    manifest = _manifest(source)
    assert manifest_from_dict(manifest_to_dict(manifest)) == manifest
