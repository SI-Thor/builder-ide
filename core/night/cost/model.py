"""The night's arithmetic: what a job costs, in every unit the rails speak.

Core-spec v2 §5.5 sets the night's rail in three units — GPU-minutes, hosted
cents and wall-minutes — and says the GPU-minutes come from *measured* costs,
not from the wall clock. This module is that measured cost table, and it is
built the only way the project's rules allow: from numbers somebody measured
on this box, with the source beside each one.

**What a job kind knows.** Every kind is recorded as a set of samples
(:mod:`core.night.cost.records`), and the model turns them into a *band*:

* ``p50`` — the median run: what the job usually costs.
* ``p95`` — the 95th percentile: what the job costs when the box is busy.

Both are in the same units the rail uses, so a night's plan and a night's
spend can be compared without anybody converting anything by hand.

**The units a cost carries**

``gpu_minutes``
    the GPU lane's time — the scarce axis. A cheap CPU-lane hour does not
    eat the GPU bar (§5.5).
``cpu_lane_minutes``
    the CPU lane's time. Free, but not free to *run*: the mesh tail is where
    the CPU lane goes, and it is the reason the scheduler batches by model.
``wall_minutes``
    the wall time the job owns, end to end.
``hosted_cents``
    money spent outside the box. Zero for every local model; the axis exists
    so a hosted engine can be priced honestly.
``joules``
    the energy, from the board's **measured power rails** (§4.4 of
    ``docs/lab/exp-engines.md``): the whole-box ``VIN`` rail over the job's
    wall time, minus the box's idle floor. The raw whole-box figure is kept
    beside it. The lab's own rule: subtract the baseline, and if the result
    comes out negative, report the wall time instead (``docs/lab/IDEAS.md``
    #17).
``iterations``
    how many iterations of this kind one goal costs — the variants the night
    tries before it keeps one.

**Nothing here is a guess that does not say so.** Each band carries its
``basis`` (``measured``, ``derived`` or ``estimate``) and its ``source``; the
one estimate in the whole model — the owner's attention per decision — is
marked as such and stays marked until a morning measures it.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from pydantic import BaseModel

from core.night.cost.records import JobRecord, RecordedData, Sample, load_recorded
from core.night.models import Rail

__all__ = [
    "CostBand",
    "CostEstimate",
    "CostModel",
    "get_model",
    "percentile",
]

#: The basis a band's numbers rest on.
MEASURED = "measured"
DERIVED = "derived"
ESTIMATE = "estimate"


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile of ``values``, linearly interpolated.

    The same convention NumPy uses (``linear``), so a number here can be
    checked against a number in a notebook without argument.
    """
    if not values:
        raise ValueError("a percentile needs at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[int(position)])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


class CostEstimate(BaseModel):
    """One job kind's cost, in every unit the night's rails speak."""

    kind: str
    gpu_minutes: float = 0.0
    cpu_lane_minutes: float = 0.0
    wall_minutes: float = 0.0
    hosted_cents: int = 0
    #: The energy the whole box drew while the job ran: the measured ``VIN``
    #: rail over the job's wall time. The box belongs to this project, so
    #: every joule it drew that night was this night's.
    joules: float = 0.0
    #: The energy above the box's idle floor. ``None`` when the job is too
    #: short to dominate the box and the wall time is the number to read
    #: (``docs/lab/IDEAS.md`` #17).
    joules_above_idle: float | None = None
    #: How many iterations of this kind one goal costs.
    iterations: int = 1
    #: How many recorded samples the figure rests on.
    samples: int = 0

    @property
    def lane_minutes(self) -> float:
        """The GPU lane plus the CPU lane."""
        return self.gpu_minutes + self.cpu_lane_minutes

    @property
    def gpu_seconds(self) -> float:
        """The GPU lane in seconds — the unit the recordings are in."""
        return self.gpu_minutes * 60.0

    @property
    def cpu_seconds(self) -> float:
        """The CPU lane in seconds."""
        return self.cpu_lane_minutes * 60.0

    @property
    def wall_seconds(self) -> float:
        """The wall time in seconds."""
        return self.wall_minutes * 60.0

    def rail(self) -> Rail:
        """This estimate as a :class:`~core.night.models.Rail`.

        The Rail is the night's own unit — the thing the bar, the admission
        check and the ledger all speak.
        """
        return Rail(
            gpu_minutes=self.gpu_minutes,
            hosted_cents=self.hosted_cents,
            wall_minutes=self.wall_minutes,
        )


class CostBand(BaseModel):
    """A job kind's measured range: the median run and the bad one."""

    kind: str
    label: str
    basis: str
    source: str
    note: str = ""
    p50: CostEstimate
    p95: CostEstimate
    #: The scene type the band was measured on, when it is scene-specific.
    scene: str | None = None

    @property
    def worst(self) -> CostEstimate:
        """The p95 — the number the night's plan should be built against."""
        return self.p95


class CostModel:
    """The measured cost table, and the arithmetic over it.

    One instance reads the recorded data once. :func:`get_model` hands out
    the shared one.
    """

    def __init__(self, data: RecordedData | None = None) -> None:
        self.data = data if data is not None else load_recorded()
        self._records: dict[str, JobRecord] = {}

    # -- the recorded job kinds ------------------------------------------

    def record(self, kind: str) -> JobRecord:
        """The recorded record for one job kind."""
        if kind not in self._records:
            self._records[kind] = self.data.job(kind)
        return self._records[kind]

    def kinds(self) -> list[str]:
        """Every recorded job kind."""
        return sorted((self.data.index.get("jobs") or {}))

    # -- the bands --------------------------------------------------------

    def band(self, kind: str, *, scene: str | None = None) -> CostBand:
        """The measured band for one job kind.

        ``scene`` narrows an Infinigen stage to one scene type; without it
        the band is over every scene recorded.
        """
        if kind in self._derived_kinds():
            return self._derived_band(kind, scene=scene)
        record = self.record(kind)
        samples = record.samples_for(scene)
        if not samples:
            raise KeyError(f"{kind!r} has no recorded sample{'' if not scene else f' for {scene!r}'}")
        return self._band_from_samples(record, samples, scene=scene)

    def infinigen_stage(self, scene_type: str, stage: str) -> CostBand:
        """One Infinigen stage, for one scene type."""
        kind = f"infinigen.{stage}"
        return self.band(kind, scene=scene_type)

    def prop(self, resolution: str = "512") -> CostBand:
        """One TRELLIS.2 prop, at one resolution."""
        return self.band(f"prop.{resolution}")

    def rung(self, rung: int) -> CostBand:
        """One rung of the render ladder."""
        if rung not in (1, 2, 3):
            raise ValueError(f"the render ladder has three rungs, not {rung}")
        return self.band(f"rung.{rung}")

    def critic_verdict(self) -> CostBand:
        """The critic's verdict on one variant."""
        return self.band("critic.verdict")

    # -- the derived kinds ------------------------------------------------

    def _derived_kinds(self) -> tuple[str, ...]:
        return ("prop.goal", "scene.goal")

    def _derived_band(self, kind: str, *, scene: str | None = None) -> CostBand:
        """The two kinds that are sums of recorded kinds.

        ``prop.goal`` — one owner's goal, tried ``seeds`` times: a picture,
        then a 3D prop, then the verdict. ``scene.goal`` — one scene, built
        coarse, fine, rendered.
        """
        if kind == "prop.goal":
            seeds = 3
            resolution = "512"
            parts = [self.band("prop.image"), self.band("prop.night")]
            verdict = self.band("critic.verdict")
            label = f"one prop goal, {seeds} variants at {resolution}³"
            note = (
                "a picture, then a prop, then the verdict, per variant; "
                "the mini-night's shape (3 seeds a goal)"
            )
            iterations = seeds
        elif kind == "scene.goal":
            scene_type = scene or "plain"
            parts = [
                self.band("infinigen.coarse", scene=scene_type),
                self.band("infinigen.fine", scene=scene_type),
                self.band("infinigen.render", scene=scene_type),
            ]
            label = f"one scene goal ({scene_type})"
            note = "coarse, fine, render"
            iterations = 1
        else:  # pragma: no cover - guarded by _derived_kinds
            raise KeyError(kind)

        p50 = self._sum([band.p50 for band in parts], iterations=iterations)
        p95 = self._sum([band.p95 for band in parts], iterations=iterations)
        return CostBand(
            kind=kind,
            label=label,
            basis=DERIVED,
            source="+".join(band.source for band in parts),
            note=note,
            p50=p50,
            p95=p95,
            scene=scene,
        )

    def _sum(self, parts: Sequence[CostEstimate], *, iterations: int) -> CostEstimate:
        """Add the parts of a derived kind, then scale by the goal's depth."""
        total = CostEstimate(
            kind="",
            gpu_minutes=sum(part.gpu_minutes for part in parts),
            cpu_lane_minutes=sum(part.cpu_lane_minutes for part in parts),
            wall_minutes=sum(part.wall_minutes for part in parts),
            hosted_cents=sum(part.hosted_cents for part in parts),
            joules=sum(part.joules for part in parts),
            iterations=iterations,
            samples=sum(part.samples for part in parts),
        )
        if iterations != 1:
            total.gpu_minutes *= iterations
            total.cpu_lane_minutes *= iterations
            total.wall_minutes *= iterations
            total.joules *= iterations
        total.joules_above_idle = self._combine_joules(total)
        return total

    def _combine_joules(self, estimate: CostEstimate) -> float | None:
        """The joules above the box's idle floor — ``None`` if it comes out
        negative, which is the lab's rule for work too small to dominate the
        box (``docs/lab/IDEAS.md`` #17)."""
        marginal = self.data.rails.marginal_vin_w * estimate.wall_minutes * 60.0 / 1000.0
        return marginal if marginal > 0 else None

    # -- the arithmetic over samples --------------------------------------

    def _band_from_samples(
        self, record: JobRecord, samples: Sequence[Sample], *, scene: str | None = None
    ) -> CostBand:
        """Turn a set of recorded samples into the band."""
        p50 = self._estimate(record, samples, 0.50, iterations=1)
        p95 = self._estimate(record, samples, 0.95, iterations=1)
        return CostBand(
            kind=record.kind,
            label=record.label,
            basis=record.basis,
            source=record.source,
            note=record.note,
            p50=p50,
            p95=p95,
            scene=scene,
        )

    def _estimate(
        self, record: JobRecord, samples: Sequence[Sample], q: float, *, iterations: int
    ) -> CostEstimate:
        """One end of a band, in minutes and joules."""
        gpu = percentile([sample.gpu_seconds for sample in samples], q)
        cpu = percentile([sample.cpu_seconds for sample in samples], q)
        wall = percentile([sample.wall_seconds for sample in samples], q)
        estimate = CostEstimate(
            kind=record.kind,
            gpu_minutes=gpu / 60.0,
            cpu_lane_minutes=cpu / 60.0,
            wall_minutes=wall / 60.0,
            hosted_cents=0,
            joules=self.data.rails.vin_w * wall / 1000.0,
            iterations=iterations,
            samples=len(samples),
        )
        estimate.joules_above_idle = self._combine_joules(estimate)
        return estimate

    # -- the night's own numbers ------------------------------------------

    def default_night_rails(self) -> Rail:
        """The night's default rail (§5.5): 360 GPU-min, 0 cents, 560 wall-min.

        The spec's number, kept in one place so the code and the document
        cannot drift apart.
        """
        return Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0)

    def attention_minutes_per_decision(self) -> float:
        """The owner's attention per decision — an estimate, and marked as one."""
        return self.data.attention_minutes_per_decision()

    def joules_per_iteration(self) -> float:
        """The measured cost of one more fixed-point iteration (1.39 J)."""
        return self.data.joules_per_iteration()

    def power_rails(self) -> Mapping[str, Any]:
        """The measured power rails, for the record."""
        rails = self.data.rails
        return {
            "vin_w": rails.vin_w,
            "vdd_gpu_w": rails.vdd_gpu_w,
            "vdd_cpu_soc_mss_w": rails.vdd_cpu_soc_mss_w,
            "vin_sys_5v0_w": rails.vin_sys_5v0_w,
            "idle_vin_w": rails.idle_vin_w,
        }


_MODEL: CostModel | None = None


def get_model() -> CostModel:
    """The shared cost model — the recorded data, read once."""
    global _MODEL
    if _MODEL is None:
        _MODEL = CostModel()
    return _MODEL
