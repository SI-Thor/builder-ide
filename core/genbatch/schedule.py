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

The plan is what the core's night runner is handed: a list of tasks, in
order, and the iteration policy that says how many seeds each one tries.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from pydantic import BaseModel, Field

from core.night.models import Rail
from core.records import IterationPolicy, Task

from core.genbatch.models import PropRequest, StageKind

__all__ = ["NightPlan", "ScheduleRule", "Stage"]

#: The model the image stage needs.
IMAGE_MODEL = "sd_xl_base_1.0"

#: The model the mesh stage needs.
MESH_MODEL = "trellis2"

#: What a prop costs to make, before anybody has measured it. The GPU lane
#: is the sampling only — the mesh tail is the CPU lane's — and the wall
#: clock is the whole prompt.
_IMAGE_GPU_MINUTES = 0.5
_IMAGE_WALL_MINUTES = 0.7
_MESH_GPU_MINUTES = 0.5
_MESH_WALL_MINUTES = 2.2

#: The per-attempt rail: past this, the work is stopped rather than
#: trusted.
_IMAGE_ATTEMPT_RAIL = 6.0
_MESH_ATTEMPT_RAIL = 10.0


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
        ]

    # -- the tasks ---------------------------------------------------------

    def _image_task(self, request: PropRequest) -> Task:
        count = len(self._seeds[request.id])
        return Task(
            id=f"img:{request.id}",
            intention=f"picture {request.prompt or request.id}",
            owner_character="prop-maker",
            cost_estimate=Rail(
                gpu_minutes=_IMAGE_GPU_MINUTES * count,
                wall_minutes=_IMAGE_WALL_MINUTES * count,
            ),
            rail=Rail(
                gpu_minutes=_IMAGE_GPU_MINUTES * count,
                wall_minutes=_IMAGE_ATTEMPT_RAIL * count,
            ),
        )

    def _mesh_task(self, request: PropRequest) -> Task:
        count = len(self._seeds[request.id])
        return Task(
            id=f"prop:{request.id}",
            intention=f"prop {request.prompt or request.id}",
            owner_character="prop-maker",
            cost_estimate=Rail(
                gpu_minutes=_MESH_GPU_MINUTES * count,
                wall_minutes=_MESH_WALL_MINUTES * count,
            ),
            rail=Rail(
                gpu_minutes=_MESH_GPU_MINUTES * count,
                wall_minutes=_MESH_ATTEMPT_RAIL * count,
            ),
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
