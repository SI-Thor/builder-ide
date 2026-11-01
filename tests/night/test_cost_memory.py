"""The cost model's memory column: the peaks the admission daemon measured.

The model already knows what a job kind costs in GPU-minutes and joules.
These tests check the **memory** axis: that the daemon's JSON lines are
read the way the daemon writes them, that the band is the same percentile
convention the model already uses, and that the numbers in the repo's
recorded data are the numbers the box measured.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.night.cost.memory import (
    MemoryColumn,
    PeakRecord,
    default_memory_column,
    live_history_path,
    load_peaks,
    snapshot_path,
)

DATA = Path(__file__).resolve().parents[2] / "core" / "night" / "cost" / "data"


def test_the_snapshot_is_json_lines() -> None:
    text = (DATA / "peaks.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "the snapshot has no measurements in it"
    for line in lines:
        payload = json.loads(line)  # every line is a whole JSON object
        assert isinstance(payload, dict)


def test_every_record_says_where_it_came_from() -> None:
    records = load_peaks(DATA / "peaks.jsonl")
    assert records
    for record in records:
        assert record.basis == "measured", "a memory number must be measured"
        assert record.source == "thor-admit"
        assert record.peak_source in {"rusage", "sample", "none"}
        assert record.host == "thor"
        assert record.mem_total_bytes > 100 * 1024**3
        assert record.floor_bytes == 25 * 1024**3


def _percentile(values: list[float], q: float) -> float:
    """The percentile, computed here — deliberately not the model's function."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[int(position)])
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def test_the_band_is_the_model_percentile_convention() -> None:
    column = MemoryColumn.load(DATA / "peaks.jsonl")
    peak = column.peak_for("hog.4g")
    assert peak is not None
    assert peak.samples == 3
    # The three runs measured 4296847360, 4296847360 and 4296912896 bytes.
    measured = [4296847360.0, 4296847360.0, 4296912896.0]
    assert peak.p50_bytes == int(round(_percentile(measured, 0.50)))
    assert peak.p95_bytes == int(round(_percentile(measured, 0.95)))
    assert peak.p50_bytes == 4296847360
    assert peak.p95_bytes == 4296906342


def test_the_measured_peak_matches_what_the_hog_took() -> None:
    column = MemoryColumn.load(DATA / "peaks.jsonl")
    peak = column.peak_for("hog.8g")
    assert peak is not None
    # The hog was asked for 8 GiB and the kernel says it reached 8.0017 GiB.
    assert peak.p95_bytes / 1024**3 == pytest.approx(8.0017, abs=0.001)


def test_an_unknown_kind_has_no_band() -> None:
    column = MemoryColumn.load(DATA / "peaks.jsonl")
    assert column.peak_for("nothing-was-measured-here") is None


def test_a_torn_line_does_not_take_the_history_with_it(tmp_path: Path) -> None:
    path = tmp_path / "peaks.jsonl"
    path.write_text(
        json.dumps(
            {
                "at": "2026-10-31T21:56:39Z",
                "kind": "x",
                "label": "x",
                "peak_rss_bytes": 10,
                "basis": "measured",
                "source": "thor-admit",
            }
        )
        + "\n"
        + '{"at": "2026-10-31T21:56:40Z", "kind": "x", "peak_rs',
        encoding="utf-8",
    )
    records = load_peaks(path)
    assert len(records) == 1
    assert records[0].peak_rss_bytes == 10


def test_the_column_falls_back_to_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The live history is wherever the daemon writes it; the snapshot is
    # what the repo carries. The default column must have a source either way.
    # The box's own daemon may be recording, so the live path is pointed at a
    # file that is not there: the test is of the fallback, not of the box.
    monkeypatch.setenv("THOR_ADMIT_PEAKS", str(tmp_path / "absent.jsonl"))
    column = default_memory_column()
    assert column.records, "the memory column has no source at all"
    assert "hog.4g" in column.kinds()


def test_the_paths_are_where_the_daemon_writes() -> None:
    assert live_history_path().name == "peaks.jsonl"
    assert snapshot_path().parent == DATA


def test_a_record_reads_the_fields_the_daemon_writes() -> None:
    record = PeakRecord.from_mapping(
        {
            "at": "2026-10-31T21:49:27Z",
            "kind": "trellis",
            "label": "trellis",
            "host": "thor",
            "peak_rss_bytes": 3276800,
            "peak_gpu_bytes": None,
            "gpu_visible": True,
            "duration_s": 1.06,
            "mem_total_bytes": 131856928768,
            "floor_bytes": 26843545600,
            "basis": "measured",
            "source": "thor-admit",
            "peak_source": "sample",
        }
    )
    assert record.kind == "trellis"
    assert record.peak_gpu_bytes is None
    assert record.gpu_visible is True
    assert record.peak_source == "sample"


def test_an_empty_live_history_is_no_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a daemon that has started but not measured yet leaves an empty file;
    # the snapshot must still stand in
    empty = tmp_path / "peaks.jsonl"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("THOR_ADMIT_PEAKS", str(empty))
    assert "hog.4g" in default_memory_column().kinds()
