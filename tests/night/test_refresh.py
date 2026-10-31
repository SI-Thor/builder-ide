"""The refresh path: the model's data follows the recordings it is built on.

The model is only worth something if every number in it can be traced back to
a file. The refresh keeps that true when the box records something new: it
re-pins the snapshot, records the file's md5 and row count, and says whether
the recording has moved on since.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.night.cost.refresh import check, refresh_night, refresh_sweep

SWEEP = "scene\tseed\tstage\tstatus\tseconds\n"
ROWS = [
    "desert\t1\tcoarse\tok\t1023\n",
    "desert\t2\tcoarse\tok\t990\n",
    "forest\t1\tfine\tok\t36\n",
]


def _index(data_dir: Path, *, origin: Path) -> None:
    """A model index that points at a sweep snapshot."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "recorded.json").write_text(
        json.dumps(
            {
                "version": 1,
                "recorded_at": "2026-01-01",
                "sources": {
                    "sweep": {
                        "file": "infinigen_sweep.tsv",
                        "origin": str(origin),
                        "doc": "docs/research/spike-phase1.md",
                        "rows": 0,
                        "md5": "",
                        "note": "old",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _sweep(tmp_path: Path, rows: list[str] | None = None) -> Path:
    path = tmp_path / "sweep.tsv"
    path.write_text(SWEEP + "".join(rows if rows is not None else ROWS), encoding="utf-8")
    return path


def test_the_refresh_re_pins_the_sweep_snapshot(tmp_path):
    """The model reads a copy that does not move under it."""
    data_dir = tmp_path / "data"
    source = _sweep(tmp_path)
    _index(data_dir, origin=source)

    result = refresh_sweep(source, data_dir=data_dir)

    snapshot = data_dir / "infinigen_sweep.tsv"
    assert snapshot.exists()
    assert snapshot.read_text() == source.read_text()
    assert result["rows"] == 3
    assert len(result["md5"]) == 32
    assert result["changed"] is True


def test_the_refresh_records_the_md5_and_the_rows(tmp_path):
    """The pin is the fingerprint: the file the numbers came from."""
    data_dir = tmp_path / "data"
    source = _sweep(tmp_path)
    _index(data_dir, origin=source)

    refresh_sweep(source, data_dir=data_dir)

    index = json.loads((data_dir / "recorded.json").read_text())
    sweep = index["sources"]["sweep"]
    assert sweep["rows"] == 3
    assert sweep["md5"] == result_md5(source)
    assert index["recorded_at"] != "2026-01-01"


def result_md5(path: Path) -> str:
    import hashlib

    return hashlib.md5(path.read_bytes()).hexdigest()


def test_the_refresh_says_whether_anything_changed(tmp_path):
    data_dir = tmp_path / "data"
    source = _sweep(tmp_path)
    _index(data_dir, origin=source)

    first = refresh_sweep(source, data_dir=data_dir)
    assert first["changed"] is True

    second = refresh_sweep(source, data_dir=data_dir)
    assert second["changed"] is False


def test_the_check_says_when_the_recording_has_moved_on(tmp_path):
    """The quiet question: is the model still true of the box?"""
    data_dir = tmp_path / "data"
    source = _sweep(tmp_path)
    _index(data_dir, origin=source)
    refresh_sweep(source, data_dir=data_dir)

    assert check(data_dir=data_dir)["stale"] is False

    # the sweep keeps running: one more row lands
    source.write_text(SWEEP + "".join(ROWS) + "desert\t3\tcoarse\tok\t1010\n",
                      encoding="utf-8")

    after = check(data_dir=data_dir)
    assert after["stale"] is True
    assert after["moved_on"] is True
    assert after["origin_rows"] == 4
    assert after["rows"] == 3, "the model still describes the snapshot it pinned"


def test_the_check_knows_the_snapshot_is_what_the_index_says(tmp_path):
    data_dir = tmp_path / "data"
    source = _sweep(tmp_path)
    _index(data_dir, origin=source)
    refresh_sweep(source, data_dir=data_dir)

    result = check(data_dir=data_dir)

    assert result["pinned"] is True
    assert result["snapshot_rows"] == 3
    assert result["origin_rows"] == 3


def _ledger(path: Path) -> Path:
    """A ledger with two job.done events: an image and a prop."""
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " id TEXT, at TEXT, actor TEXT, type TEXT, subject TEXT, payload TEXT,"
        " artifact TEXT)"
    )
    rows = [
        {"cost": {"gpu_minutes": 0.2, "wall_minutes": 0.3},
         "artifact": "/out/crate_0001_.png"},
        {"cost": {"gpu_minutes": 1.0, "wall_minutes": 2.0},
         "artifact": "/out/crate_0002_.glb"},
    ]
    for index, row in enumerate(rows):
        db.execute(
            "INSERT INTO audit (id, at, actor, type, subject, payload)"
            " VALUES (?,?,?,?,?,?)",
            (f"e{index}", "2026-01-01T00:00:00Z", "core", "job.done", "job",
             json.dumps(row)),
        )
    db.commit()
    db.close()
    return path


def test_the_refresh_extracts_a_night(tmp_path):
    """A night's lane splits come out of its own ledger."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "recorded.json").write_text(
        json.dumps({"sources": {"mini_night": {"file": "mini_night.json",
                                               "doc": "docs/lab/mini-night.md"}}},
                   indent=2),
        encoding="utf-8",
    )
    ledger = _ledger(tmp_path / "ledger.db")

    result = refresh_night(ledger, data_dir=data_dir)

    document = json.loads((data_dir / "mini_night.json").read_text())
    assert result["jobs"] == 2
    assert document["jobs"] == 2
    assert document["samples"][0]["kind"] == "image"
    assert document["samples"][1]["kind"] == "prop"
    assert document["samples"][1]["gpu_seconds"] == pytest.approx(60.0)
    assert document["samples"][1]["cpu_seconds"] == pytest.approx(60.0)


def test_the_refresh_records_where_the_night_came_from(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "recorded.json").write_text(
        json.dumps({"sources": {"mini_night": {"file": "mini_night.json"}}}, indent=2),
        encoding="utf-8",
    )
    ledger = _ledger(tmp_path / "ledger.db")

    refresh_night(ledger, data_dir=data_dir)

    index = json.loads((data_dir / "recorded.json").read_text())
    assert index["sources"]["mini_night"]["origin"] == str(ledger)
    assert index["sources"]["mini_night"]["jobs"] == 2
