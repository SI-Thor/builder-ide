"""The night's staging plan — the scheduling lessons, written as rules.

The night is not a queue of props. It is **stages, grouped by model**:
every image the night needs, then every mesh. That is the rule the
TRELLIS.2 spike earned (docs/research/trellis-spike.md §9): the weights are
loaded once for the night, not once per prop, and the box cannot hide a
weight read of ten gigabytes.

The other two rules come from §4.3, where the spike measured the mesh tail
to be most of a prop's cost and CPU-bound, and a seven-fold swing when two
props ran at once and their tails fought over the same cores. So:

* the mesh tail is charged to the **CPU lane**, not to the GPU's bar; and
* the night is **serial** — one prompt at a time, never two.

**What each stage costs comes from the cost model** (``core/night/cost``),
not from numbers typed in here: the image stage is priced as ``prop.image``
(one 1024² picture) and the mesh stage as the TRELLIS.2 prop at the
request's resolution (``prop.mesh.512`` / ``prop.mesh.1024`` — the generator,
the decode, the mesh tail, the repair and the measuring, which is what the
night's mesh stage actually *is*). The ask is the model's p50 and the rail
its p95, so the number the night plans against is the one the box was
measured at, and it moves when the measurement moves.

**The mesh stage used to be priced at the bare generator** (``prop.512`` —
the three KSamplers and the tail, from the spike's two runs). That was 3.4x
under what the night actually spends: the generator is only the sampling,
while the night's mesh stage also carries the decode stages, the repair and
the measuring. ``prop.mesh.512`` is the second mini-night's own measurement of
the whole stage, so the ask is now the night's own cost. The regression test
in ``tests/genbatch/test_schedule.py`` holds that line.

The plan is what the core's night runner is handed: a list of tasks, in
order, and the iteration policy that says how many seeds each one tries.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from pydantic import BaseModel, Field

from core.night.cost.pricing import PricedAsk, price_job
from core.records import IterationPolicy, Task

from core.genbatch.models import PropRequest, StageKind

__all__ = ["NightPlan", "ScheduleRule", "Stage"]

#: The model the image stage needs.
IMAGE_MODEL = "sd_xl_base_1.0"

#: The model the mesh stage needs.
MESH_MODEL = "trellis2"

#: The cost model's job kinds for the two stages: one 1024² picture, and one
#: TRELLIS.2 prop at the resolution the request asks for.
#:
#: The mesh kinds are the *stage*, not the generator: the prompt window the
#: second mini-night measured, plus the repair and the measuring. The
#: generator's own bands (``prop.512`` / ``prop.1024``) are what the spike
#: measured, and they are the input to the 1024³ band, not the price.
IMAGE_KIND = "prop.image"
MESH_KIND = "prop.mesh.512"
MESH_KIND_1024 = "prop.mesh.1024"

#: The resolution the mesh stage falls back to when the model has no measured
#: price for the one the request asks for (512³ — the default, and the one
#: the spike measured).
DEFAULT_MESH_RESOLUTION = 512


def _mesh_kind(resolution: int) -> str:
    """The cost model's kind for a TRELLIS.2 prop at this resolution."""
    if resolution == 1024:
        return MESH_KIND_1024
    return MESH_KIND


class ScheduleRule(BaseModel):
    """One rule, and where it came from."""

    name: str
    rule: str
    evidence: str = ""


class Stage(BaseModel):
    """One model's work for the night."""

    model: str
    kind: StageKind
    task_ids: list[str] = Field(default_factory=list)


@dataclass
class NightPlan:
    """What the night will make, and in what order."""

    requests: list[PropRequest]
    with_image_stage: bool = True

    def __post_init__(self) -> None:
        self._by_id = {request.id: request for request in self.requests}
        self._seeds: dict[str, list[int]] = {
            request.id: self._derive_seeds(request) for request in self.requests
        }

    # -- the queue ---------------------------------------------------------

    @property
    def tasks(self) -> list[Task]:
        """The night's queue: every image stage, then every mesh stage.

        The order is the rule. All the work that needs the image model
        comes first, so that model is loaded once and stays loaded; then
        all the work that needs TRELLIS.2, likewise.
        """
        tasks: list[Task] = []
        if self.with_image_stage:
            for request in self.requests:
                if request.starts_from_an_image:
                    continue
                tasks.append(self._image_task(request))
        for request in self.requests:
            tasks.append(self._mesh_task(request))
        return tasks

    def stage_kind(self, task_id: str) -> StageKind:
        """Whether a task is the image stage or the mesh stage."""
        return StageKind.IMAGE if task_id.startswith("img:") else StageKind.MESH

    def model_for(self, task_id: str) -> str:
        """The model a task needs."""
        return IMAGE_MODEL if self.stage_kind(task_id) == StageKind.IMAGE else MESH_MODEL

    def request(self, task_id: str) -> PropRequest | None:
        """The request a task is about."""
        request_id = task_id.split(":", 1)[-1]
        return self._by_id.get(request_id)

    def priced(self, task_id: str) -> PricedAsk:
        """What the cost model says one job of this stage costs.

        The image stage is a picture (``prop.image``); the mesh stage is the
        TRELLIS.2 prop at the resolution the request asked for.
        """
        request = self.request(task_id)
        if self.stage_kind(task_id) == StageKind.IMAGE:
            return price_job(IMAGE_KIND)
        resolution = request.resolution if request else DEFAULT_MESH_RESOLUTION
        return price_job(_mesh_kind(resolution))

    def per_variant_cost(self, task_id: str) -> tuple[float, float]:
        """The GPU minutes and the wall minutes of one attempt of this stage.

        One attempt is one job of the stage's kind, so this is the model's
        p50 for that kind — the same number the task's ask is made of.
        """
        priced = self.priced(task_id)
        return (priced.ask.gpu_minutes, priced.ask.wall_minutes)

    def seeds(self, request_id: str) -> list[int]:
        """The seeds a request's variants use."""
        return list(self._seeds.get(request_id, []))

    def seed_for(self, request_id: str, index: int) -> int | None:
        seeds = self._seeds.get(request_id, [])
        return seeds[index] if 0 <= index < len(seeds) else None

    # -- the rules ---------------------------------------------------------

    @property
    def stages(self) -> list[Stage]:
        """The night's work, grouped by model."""
        stages: list[Stage] = []
        for task in self.tasks:
            model = self.model_for(task.id)
            if not stages or stages[-1].model != model:
                stages.append(
                    Stage(model=model, kind=self.stage_kind(task.id), task_ids=[])
                )
            stages[-1].task_ids.append(task.id)
        return stages

    @property
    def parallelism(self) -> int:
        """How many prompts run at once. One: the mesh tails must not fight.

        The spike measured a seven-fold swing when two props ran together
        and their mesh tails contended for the same cores, so the night
        runs its prompts one after another.
        """
        return 1

    @property
    def iteration_policy(self) -> IterationPolicy:
        """How deep the night goes on one goal: N seeds, one round.

        One round is the point: the brief asks for N seeds per prop, and
        the best of them kept. A second round would be the loop refining
        its winner, which is a different night.
        """
        widest = max((len(self.seeds(r.id)) for r in self.requests), default=1)
        return IterationPolicy(variants_per_round=max(1, widest), max_rounds=1)

    @property
    def rules(self) -> list[ScheduleRule]:
        """The rules this plan runs by, and where they came from."""
        stages = self.stages
        by_model = ", ".join(
            f"{stage.model} ({len(stage.task_ids)} task{'s' if len(stage.task_ids) != 1 else ''})"
            for stage in stages
        )
        return [
            ScheduleRule(
                name="batch_by_model",
                rule=(
                    "the GPU stages are batched by model: the night's work is "
                    f"ordered {by_model}, so each model is loaded once"
                ),
                evidence=(
                    "docs/research/trellis-spike.md §9 — the weights are loaded "
                    "once for the night, not once per prop"
                ),
            ),
            ScheduleRule(
                name="cpu_mesh_tail",
                rule=(
                    "the mesh tail is charged to the CPU lane, not to the "
                    "GPU's bar; the GPU lane's time is the sampling alone"
                ),
                evidence=(
                    "docs/research/trellis-spike.md §4.3, §4.4 — the tail is "
                    "~80% of a 512³ prop and it is CPU-bound"
                ),
            ),
            ScheduleRule(
                name="no_overlap",
                rule=(
                    "one prompt at a time: the mesh tail of one prop never "
                    "runs alongside the sampling of the next"
                ),
                evidence=(
                    "docs/research/trellis-spike.md §4.3 — two props at once "
                    "measured a seven-fold swing under contention"
                ),
            ),
            ScheduleRule(
                name="costs_from_the_model",
                rule=(
                    "each stage's ask is the cost model's measured p50 and its "
                    "rail the measured p95 — the picture as prop.image, the "
                    "prop as the TRELLIS.2 kind for its resolution"
                ),
                evidence=(
                    "core/night/cost — the sweep and the mini-night's ledger; "
                    "the model's own README says what each kind measured"
                ),
            ),
        ]

    # -- the tasks ---------------------------------------------------------

    def _image_task(self, request: PropRequest) -> Task:
        """The image stage: one 1024² picture, priced by the cost model.

        The ask is the measured p50 and the rail the measured p95 — the
        picture's own bad case, so the night stops work that has run past
        what the box was seen to do.
        """
        count = len(self._seeds[request.id])
        priced = price_job(IMAGE_KIND, count=count)
        return self._task(
            task_id=f"img:{request.id}",
            intention=f"picture {request.prompt or request.id}",
            priced=priced,
        )

    def _mesh_task(self, request: PropRequest) -> Task:
        """The mesh stage: one TRELLIS.2 prop, priced by the cost model.

        The GPU lane is the sampling alone; the mesh tail is the CPU lane's
        — which is why the tail is not charged to the GPU's bar.
        """
        count = len(self._seeds[request.id])
        kind = _mesh_kind(request.resolution)
        priced = price_job(kind, count=count)
        return self._task(
            task_id=f"prop:{request.id}",
            intention=f"prop {request.prompt or request.id}",
            priced=priced,
        )

    @staticmethod
    def _task(task_id: str, intention: str, priced: PricedAsk) -> Task:
        """A stage's task: the model's ask, and the model's rail."""
        return Task(
            id=task_id,
            intention=intention,
            owner_character="prop-maker",
            cost_estimate=priced.ask,
            rail=priced.rail,
            kind=priced.kind,
            ask_source="model",
            ask_basis=priced.basis,
        )

    @staticmethod
    def _derive_seeds(request: PropRequest) -> list[int]:
        """A request's seeds, derived so the night's work replays."""
        seeds: list[int] = []
        for index in range(request.seeds):
            digest = hashlib.blake2b(
                f"{request.id}:{request.base_seed}:{index}".encode("utf-8"),
                digest_size=8,
            ).digest()
            seeds.append(int.from_bytes(digest, "big") % (2**31 - 1))
        return seeds
