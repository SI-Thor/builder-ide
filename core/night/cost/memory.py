"""The cost model's **memory column**: how much memory a job kind takes.

The cost model already knows what a job kind costs in GPU-minutes, wall
minutes and joules. What it did not know was the axis the box actually
runs out of: **memory**. The admission daemon
(``tools/thor-admit``) measures it — every lease records the peak resident
set it reached — and writes it as JSON lines.

One line per finished lease::

    {"at": "2026-10-31T21:49:27Z", "kind": "trellis", "label": "trellis",
     "host": "thor", "peak_rss_bytes": 3276800, "peak_gpu_bytes": null,
     "gpu_visible": true, "duration_s": 1.06, "mem_total_bytes": 131856928768,
     "floor_bytes": 26843545600, "basis": "measured", "source": "thor-admit",
     "peak_source": "sample"}

This module reads those lines and turns them into the same kind of band the
model already speaks: a **p50** and a **p95**, with the number of samples
and the source beside them. The percentile convention is
:func:`core.night.cost.model.percentile`, so a number here and a number in
the model mean the same thing.

**Where the lines come from.** The daemon writes the live history to
``~/.local/state/thor-admit/peaks.jsonl`` (or wherever ``THOR_ADMIT_PEAKS``
points). The copy kept in this package's ``data/`` directory is the
snapshot: what the box measured, recorded next to the rest of the model's
recorded data, so the model's numbers all have a source in the repo.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterable, Mapping

from core.night.cost.model import percentile
from core.night.cost.records import DATA_DIR

__all__ = [
    "MemoryColumn",
    "MemoryPeak",
    "PeakRecord",
    "default_memory_column",
    "live_history_path",
    "load_peaks",
    "snapshot_path",
]


def live_history_path() -> Path:
    """Where the daemon writes the history right now."""
    override = os.environ.get("THOR_ADMIT_PEAKS")
    if override:
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "thor-admit" / "peaks.jsonl"


def snapshot_path() -> Path:
    """The copy of the history kept with the model's recorded data."""
    return DATA_DIR / "peaks.jsonl"


@dataclass(frozen=True)
class PeakRecord:
    """One measured peak: what one lease of one label reached."""

    at: str
    kind: str
    label: str
    host: str
    #: The peak resident set, in bytes. The memory column's number.
    peak_rss_bytes: int
    #: The peak GPU bytes, when the driver could be asked.
    peak_gpu_bytes: int | None
    #: Whether the GPU's view was available at all.
    gpu_visible: bool
    duration_s: float
    mem_total_bytes: int
    floor_bytes: int
    #: ``measured`` — the model's word for where a number comes from.
    basis: str
    #: Who measured it.
    source: str
    #: Which measurement the peak came from (``rusage`` or ``sample``).
    peak_source: str
    #: The run's exit status: 0 is a clean finish. ``None`` is a record
    #: from before exit statuses were written (round 9), where the
    #: duration is all the record can say about whether the work happened.
    exit_code: int | None = None

    #: How long a run must last before it may teach, in seconds — the same
    #: line the daemon's ``history::MIN_LEARNED_DURATION_S`` draws, kept in
    #: step so a number here and a number there mean the same thing.
    MIN_TEACHING_DURATION_S: ClassVar[float] = 5.0

    def teaches(self) -> bool:
        """May this record teach a reservation?

        The daemon's own rule, mirrored: a run teaches only if it finished
        cleanly and lasted — a no-op run (exit 0 in milliseconds, a few MB)
        is not what the next run costs. An over-run record always teaches:
        it is written only past a gross under-reservation and can only
        raise the number.
        """
        if self.peak_source == "overrun":
            return True
        return (self.exit_code in (None, 0)) and (
            self.duration_s >= self.MIN_TEACHING_DURATION_S
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "PeakRecord":
        label = str(payload.get("label", "") or "")
        kind = str(payload.get("kind", label) or label)
        gpu = payload.get("peak_gpu_bytes")
        exit_code = payload.get("exit_code")
        return cls(
            at=str(payload.get("at", "")),
            kind=kind,
            label=label,
            host=str(payload.get("host", "")),
            peak_rss_bytes=int(payload.get("peak_rss_bytes", 0) or 0),
            peak_gpu_bytes=int(gpu) if gpu is not None else None,
            gpu_visible=bool(payload.get("gpu_visible", False)),
            duration_s=float(payload.get("duration_s", 0.0) or 0.0),
            mem_total_bytes=int(payload.get("mem_total_bytes", 0) or 0),
            floor_bytes=int(payload.get("floor_bytes", 0) or 0),
            basis=str(payload.get("basis", "measured")),
            source=str(payload.get("source", "thor-admit")),
            peak_source=str(payload.get("peak_source", "sample")),
            exit_code=int(exit_code) if exit_code is not None else None,
        )


@dataclass(frozen=True)
class MemoryPeak:
    """One job kind's memory band: the p50 and the p95, with their source."""

    kind: str
    samples: int
    p50_bytes: int
    p95_bytes: int
    last_peak_bytes: int
    source: str

    @property
    def p50_gib(self) -> float:
        return self.p50_bytes / (1024**3)

    @property
    def p95_gib(self) -> float:
        return self.p95_bytes / (1024**3)


def load_peaks(path: Path | str) -> list[PeakRecord]:
    """Read a JSON-lines peak history.

    A line that cannot be read is skipped: the daemon appends, so a writer
    that died mid-line must not take the history with it.
    """
    path = Path(path)
    records: list[PeakRecord] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            records.append(PeakRecord.from_mapping(payload))
        except (TypeError, ValueError):
            continue
    return records


class MemoryColumn:
    """The cost model's memory column, read from the daemon's history."""

    def __init__(self, records: Iterable[PeakRecord] = ()):
        self._records = list(records)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "MemoryColumn":
        """Read a history file (the live one by default)."""
        if path is None:
            return default_memory_column()
        return cls(load_peaks(path))

    @property
    def records(self) -> list[PeakRecord]:
        return list(self._records)

    def kinds(self) -> list[str]:
        """Every label the history knows about, in the order first seen."""
        kinds: list[str] = []
        for record in self._records:
            if record.kind not in kinds:
                kinds.append(record.kind)
        return kinds

    def records_for(self, kind: str) -> list[PeakRecord]:
        """The records that may speak for one kind.

        Only the runs that teach (see :meth:`PeakRecord.teaches`): a
        no-op's megabytes are in the file's past, not in the kind's future.
        The raw list stays on :attr:`records`.
        """
        return [
            record for record in self._records if record.kind == kind and record.teaches()
        ]

    def peak_for(self, kind: str) -> MemoryPeak | None:
        """The band for one kind, or ``None`` when nothing was measured."""
        records = self.records_for(kind)
        if not records:
            return None
        peaks = [float(record.peak_rss_bytes) for record in records]
        return MemoryPeak(
            kind=kind,
            samples=len(records),
            p50_bytes=int(round(percentile(peaks, 0.50))),
            p95_bytes=int(round(percentile(peaks, 0.95))),
            last_peak_bytes=records[-1].peak_rss_bytes,
            source=records[-1].source,
        )


def default_memory_column() -> MemoryColumn:
    """The column as the box stands now: the live history, or the snapshot.

    The live history is the daemon's own file; when it is not there or empty (a
    fresh checkout, or the daemon has never run) the snapshot kept with
    the model's recorded data is used instead, so the column always has a
    source in the repo.
    """
    live = live_history_path()
    if live.exists():
        records = load_peaks(live)
        if records:
            return MemoryColumn(records)
    # an absent or empty live file (a daemon that has not measured yet)
    # is no source: the snapshot stands in
    return MemoryColumn(load_peaks(snapshot_path()))
