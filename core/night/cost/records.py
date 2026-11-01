"""The recorded data behind the cost model, and where each number came from.

Every number the night runner spends is a **measurement** with a source, and
this module is where the source is kept. Nothing here computes a cost — it
only reads what was recorded, so that the model's arithmetic has nothing to
hide behind.

Four files carry the measurements, all under ``core/night/cost/data/``:

``infinigen_sweep.tsv``
    the Infinigen seed sweep, verbatim: scene type x seed x stage x seconds.
    A snapshot — the sweep was still running when it was taken — so the
    checksum is recorded with it.

``mini_night.json``
    the mini-night's 18 jobs, with the GPU lane and the CPU lane measured
    separately. Extracted by ``core/night/cost/extract_mini_night.py``.

``mini_night_2.json``
    the second mini-night's 18 jobs and its 9 repair measurements, in the
    same shape. It is the night that ran the whole pipeline — the generator,
    the repair and the measuring — so it is what the mesh stage is priced
    from.

``critic_verdict.json``
    the critic's verdict and the mesh measurement, timed on the box by
    ``core/night/cost/measure_critic.py``.

``recorded.json``
    the index: the power rails, the sources, and the job kinds that are read
    straight out of the documents (the TRELLIS spike, the warm scene, the
    spike's Hello Room render).

**The unit of every sample is the second.** The Rail speaks minutes, so the
model converts once, in one place, and never mixes the two.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "DATA_DIR",
    "JobRecord",
    "PowerRails",
    "RecordedData",
    "Sample",
    "load_recorded",
]

#: Where the measurements live.
DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Sample:
    """One measurement: what a job kind cost, once, on the box.

    ``other_seconds`` is the time the job spent neither on the GPU lane nor
    on the CPU lane — loading a model, writing a file. It is wall time the
    job still owns, so it stays in the wall figure.
    """

    name: str
    gpu_seconds: float
    cpu_seconds: float
    wall_seconds: float
    other_seconds: float = 0.0

    @property
    def lanes(self) -> float:
        """The seconds the job spent on a lane (GPU + CPU)."""
        return self.gpu_seconds + self.cpu_seconds


@dataclass(frozen=True)
class JobRecord:
    """One job kind's recorded samples, and where they came from."""

    kind: str
    label: str
    lane: str
    basis: str
    source: str
    note: str = ""
    samples: tuple[Sample, ...] = ()
    #: Samples grouped by scene type, for the Infinigen stages.
    groups: Mapping[str, tuple[Sample, ...]] = field(default_factory=dict)

    def samples_for(self, scene: str | None = None) -> tuple[Sample, ...]:
        """The samples for one scene type, or all of them."""
        if not self.groups:
            return self.samples
        if scene is None:
            merged: list[Sample] = []
            for group in self.groups.values():
                merged.extend(group)
            return tuple(merged)
        try:
            return self.groups[scene]
        except KeyError:
            raise KeyError(
                f"{self.kind!r} has no recorded sample for scene {scene!r}; "
                f"it has {sorted(self.groups)}"
            ) from None


@dataclass(frozen=True)
class PowerRails:
    """The board's power rails, measured (``docs/lab/exp-engines.md`` §4.4).

    ``vin_w`` is the whole-box input — what the night actually costs the
    electricity. ``idle_vin_w`` is the box's floor with the GPU idle, which is
    the baseline the lab's own rule asks to subtract before calling a number
    "joules above baseline" (``docs/lab/IDEAS.md`` #17).
    """

    vin_w: float
    vdd_gpu_w: float
    vdd_cpu_soc_mss_w: float
    vin_sys_5v0_w: float
    idle_vin_w: float

    @property
    def marginal_vin_w(self) -> float:
        """The whole-box draw above the idle floor."""
        return self.vin_w - self.idle_vin_w


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _sweep_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _sample_from_dict(payload: Mapping[str, Any]) -> Sample:
    return Sample(
        name=str(payload.get("name", "")),
        gpu_seconds=float(payload.get("gpu_seconds", 0.0)),
        cpu_seconds=float(payload.get("cpu_seconds", 0.0)),
        wall_seconds=float(payload.get("wall_seconds", 0.0)),
        other_seconds=float(payload.get("other_seconds", 0.0)),
    )


def _samples_from_critic(document: Mapping[str, Any], series: str) -> tuple[Sample, ...]:
    """The critic file's samples: one per repeat, per asset."""
    samples: list[Sample] = []
    for asset in document.get("assets", []):
        seconds = asset.get(series) or []
        for index, value in enumerate(seconds):
            samples.append(
                Sample(
                    name=f"{asset.get('asset', '?')}#{index}",
                    gpu_seconds=0.0,
                    cpu_seconds=float(value),
                    wall_seconds=float(value),
                )
            )
    return tuple(samples)


def _samples_from_mini_night(document: Mapping[str, Any], kind: str) -> tuple[Sample, ...]:
    samples: list[Sample] = []
    for payload in document.get("samples", []):
        if payload.get("kind") != kind:
            continue
        samples.append(
            Sample(
                name=str(payload.get("name", "")),
                gpu_seconds=float(payload.get("gpu_seconds", 0.0)),
                cpu_seconds=float(payload.get("cpu_seconds", 0.0)),
                wall_seconds=float(payload.get("wall_seconds", 0.0)),
            )
        )
    return tuple(samples)


def _sweep_samples(
    rows: Iterable[Mapping[str, Any]], stage: str, scene: str | None = None
) -> tuple[Sample, ...]:
    """The sweep's rows for one stage (and optionally one scene type)."""
    samples: list[Sample] = []
    for row in rows:
        if row.get("stage") != stage:
            continue
        if row.get("status") != "ok":
            continue
        row_scene = str(row.get("scene", ""))
        if scene is not None and row_scene != scene:
            continue
        seconds = float(row.get("seconds", 0.0))
        samples.append(
            Sample(
                name=f"{row_scene}/seed {row.get('seed', '?')}",
                # the sweep records one wall time per stage; the coarse and
                # fine stages are the solver's (CPU) and the render stage is
                # the renderer's (GPU) — see the spike's own box state.
                gpu_seconds=seconds if stage == "render" else 0.0,
                cpu_seconds=0.0 if stage == "render" else seconds,
                wall_seconds=seconds,
            )
        )
    return tuple(samples)


@dataclass(frozen=True)
class RecordedData:
    """Everything the model reads, loaded once."""

    index: Mapping[str, Any]
    sweep_rows: tuple[Mapping[str, Any], ...]
    mini_night: Mapping[str, Any]
    critic: Mapping[str, Any]
    rails: PowerRails
    #: The other whole nights the model can read, by their source key.
    nights: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def night(self, source: str) -> Mapping[str, Any]:
        """One night's recorded document, by its source key."""
        if source == "mini_night":
            return self.mini_night
        try:
            return self.nights[source]
        except KeyError:
            raise KeyError(
                f"no recorded night {source!r}; the model knows "
                f"{sorted(set(self.nights) | {'mini_night'})}"
            ) from None

    def job(self, kind: str) -> JobRecord:
        """The record for one job kind."""
        jobs = self.index.get("jobs") or {}
        try:
            record = jobs[kind]
        except KeyError:
            raise KeyError(
                f"no recorded job kind {kind!r}; the model knows {sorted(jobs)}"
            ) from None

        source = str(record.get("source", ""))
        label = str(record.get("label", kind))
        lane = str(record.get("lane", "mixed"))
        note = str(record.get("note", ""))
        basis = str(record.get("basis", "measured"))

        samples: tuple[Sample, ...] = ()
        groups: dict[str, tuple[Sample, ...]] = {}

        if "samples" in record:
            samples = tuple(_sample_from_dict(item) for item in record["samples"])
        elif source == "sweep":
            stage = str((record.get("from") or {}).get("stage", ""))
            if not stage:
                raise KeyError(f"job {kind!r} reads the sweep but names no stage")
            by_scene = record.get("by") == "scene"
            if by_scene:
                scenes = sorted({str(row.get("scene", "")) for row in self.sweep_rows})
                for scene in scenes:
                    group = _sweep_samples(self.sweep_rows, stage, scene)
                    if group:
                        groups[scene] = group
                samples = tuple(s for group in groups.values() for s in group)
            else:
                samples = _sweep_samples(self.sweep_rows, stage)
        elif source == "mini_night" or source in self.nights:
            wanted = str((record.get("filter") or {}).get("kind", ""))
            samples = _samples_from_mini_night(self.night(source), wanted)
        elif source == "critic":
            series = str(record.get("series", ""))
            samples = _samples_from_critic(self.critic, series)
        else:
            raise KeyError(f"job {kind!r} names an unknown source {source!r}")

        return JobRecord(
            kind=kind,
            label=label,
            lane=lane,
            basis=basis,
            source=source,
            note=note,
            samples=samples,
            groups=groups,
        )

    def joules_per_iteration(self) -> float:
        """The measured cost of one more fixed-point iteration."""
        payload = self.index.get("joules_per_iteration") or {}
        return float(payload.get("value", 0.0))

    def attention_minutes_per_decision(self) -> float:
        """The attention estimate — the number nobody has measured yet."""
        payload = self.index.get("attention_minutes_per_decision") or {}
        return float(payload.get("value", 15.0))


def load_recorded(directory: Path | None = None) -> RecordedData:
    """Load the recorded data from ``directory`` (the package's own by default)."""
    base = Path(directory) if directory is not None else DATA_DIR
    index = _read_json(base / "recorded.json")
    rails = index.get("power_rails") or {}
    # Every night the index names as a source, read once.
    nights: dict[str, Mapping[str, Any]] = {}
    for source in (index.get("sources") or {}):
        if not source.startswith("mini_night"):
            continue
        path = base / f"{source}.json"
        if path.exists():
            nights[source] = _read_json(path)
    return RecordedData(
        index=index,
        sweep_rows=tuple(_sweep_rows(base / "infinigen_sweep.tsv")),
        mini_night=_read_json(base / "mini_night.json"),
        critic=_read_json(base / "critic_verdict.json"),
        rails=PowerRails(
            vin_w=float(rails.get("vin_w", 0.0)),
            vdd_gpu_w=float(rails.get("vdd_gpu_w", 0.0)),
            vdd_cpu_soc_mss_w=float(rails.get("vdd_cpu_soc_mss_w", 0.0)),
            vin_sys_5v0_w=float(rails.get("vin_sys_5v0_w", 0.0)),
            idle_vin_w=float(rails.get("idle_vin_w", 0.0)),
        ),
        nights=nights,
    )
