"""The executor: the generative job, behind the core's scheduler.

One image prompt or one mesh prompt, one attempt. The executor runs it,
measures what came out, records it as an asset with its provenance and its
licence row, and reports what it cost.

The cost is reported **by lane**. The GPU lane's time is the sampling; the
CPU lane's time is the mesh tail. That split is what the core's rails are
built on — the spike found the tail is most of a prop's cost and it is
CPU-bound — so charging the whole prompt to the GPU's bar would be a lie
about where the night went.

The model is declared to the core only when it is actually loaded. The
core's load cap is one load a night, and the ComfyUI service keeps the
weights resident across prompts, so the second prop of the night reuses the
model the first one loaded. Declaring it once is what makes the night line
say "one load" and mean it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.night.executor import ExecutionPlan
from core.night.iterate import Variant
from core.records import Task

from core.genbatch.assets import build_asset
from core.genbatch.comfy import PromptResult
from core.genbatch.glb import GlbError, read_glb
from core.genbatch.images import ImageError, png_dimensions
from core.genbatch.licences import licence_for
from core.genbatch.mesh import measure_mesh
from core.genbatch.models import ImageResult, PropRequest, PromptRecord, StageKind
from core.genbatch.repair import RepairResult, repair_mesh
from core.genbatch.schedule import MESH_MODEL, NightPlan
from core.genbatch.store import PropStore
from core.genbatch.workflow import (
    WorkflowError,
    WorkflowTemplate,
    build_image_workflow,
    build_trellis_workflow,
    nodes_of_type,
    trellis_seeds,
)

__all__ = ["PropExecutor", "Templates"]


@dataclass(frozen=True)
class Templates:
    """The two workflow templates, read from the TRELLIS.2 environment."""

    image: WorkflowTemplate
    trellis: WorkflowTemplate


class ComfyRunner(Protocol):
    """The part of the ComfyUI client the executor uses."""

    async def run_prompt(
        self,
        workflow: dict,
        *,
        client_id: str,
        class_types: dict[str, str] | None = None,
    ) -> PromptResult: ...

    async def upload_image(self, data: bytes, filename: str) -> str: ...


class PropExecutor:
    """The generative job."""

    def __init__(
        self,
        *,
        client: ComfyRunner,
        plan: NightPlan,
        store: PropStore,
        templates: Templates,
    ) -> None:
        self._client = client
        self._plan = plan
        self._store = store
        self._templates = templates
        self._resident: set[str] = set()

    # -- the cost, before the spend ---------------------------------------

    def plan(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        """What this task will cost, and which model it needs."""
        request = self._plan.request(task.id)
        if request is None:
            return ExecutionPlan(outcome="failed", reason=f"no request for {task.id!r}")
        model = self._plan.model_for(task.id)
        count = 1 if variant is not None else len(self._plan.seeds(request.id))
        gpu, wall = self._per_variant_cost(task.id)
        return ExecutionPlan(
            model=model if model not in self._resident else None,
            gpu_minutes=gpu * count,
            wall_minutes=wall * count,
        )

    def _per_variant_cost(self, task_id: str) -> tuple[float, float]:
        """The GPU minutes and the wall minutes of one attempt."""
        if self._plan.stage_kind(task_id) == StageKind.IMAGE:
            return (0.5, 0.7)
        return (0.5, 2.2)

    # -- the work ----------------------------------------------------------

    def run(self, task: Task, variant: Variant | None = None) -> ExecutionPlan:
        """Do the work; report what it actually cost and what it produced."""
        request = self._plan.request(task.id)
        if request is None:
            return ExecutionPlan(outcome="failed", reason=f"no request for {task.id!r}")
        seed = variant.seed if variant is not None else None
        if seed is None:
            seeds = self._plan.seeds(request.id)
            seed = seeds[0] if seeds else 0
        if self._plan.stage_kind(task.id) == StageKind.IMAGE:
            return self._run_image(task, request, seed, variant)
        return self._run_mesh(task, request, seed, variant)

    def _run_image(
        self,
        task: Task,
        request: PropRequest,
        seed: int,
        variant: Variant | None,
    ) -> ExecutionPlan:
        """The image stage: a concept, and a picture of it."""
        workflow = build_image_workflow(
            self._templates.image,
            prompt=request.prompt,
            negative=request.negative,
            seed=seed,
            size=request.image_size,
            steps=request.image_steps,
            cfg=request.image_cfg,
            sampler=request.image_sampler,
            scheduler=request.image_scheduler,
            filename_prefix=f"genbatch/{request.id}_s{seed}",
        )
        result = self._run(workflow, request.id, seed, "image")
        self._record_prompt(task, request, seed, result, "image")
        if not result.ok:
            return ExecutionPlan(outcome="failed", reason=result.error)
        node_id = self._node_of(workflow, "SaveImage")
        picture = result.output(node_id) if node_id else None
        if picture is None:
            return ExecutionPlan(
                outcome="failed", reason="the image stage wrote no picture"
            )
        try:
            width, height = png_dimensions(picture)
        except ImageError as exc:
            return ExecutionPlan(outcome="failed", reason=str(exc))
        name = asyncio.run(self._client.upload_image(picture.read_bytes(), picture.name))
        self._store.record_images(
            request.id,
            [
                ImageResult(
                    seed=seed,
                    path=name,
                    width=width,
                    height=height,
                    seconds=result.wall_seconds,
                    prompt=request.prompt,
                )
            ],
        )
        self._resident.add("sd_xl_base_1.0")
        return ExecutionPlan(
            gpu_minutes=result.split.gpu_seconds / 60.0,
            wall_minutes=result.wall_seconds / 60.0,
            artifact=str(picture),
        )

    def _run_mesh(
        self,
        task: Task,
        request: PropRequest,
        seed: int,
        variant: Variant | None,
    ) -> ExecutionPlan:
        """The mesh stage: a picture, and a mesh of it."""
        image = self._store.image(request.id, seed)
        if image is None:
            return ExecutionPlan(
                outcome="failed",
                reason=f"there is no image for {request.id!r} at seed {seed}",
            )
        seeds = trellis_seeds(seed)
        try:
            workflow = build_trellis_workflow(
                self._templates.trellis,
                image_name=image.path,
                seeds=seeds,
                steps=request.trellis_steps,
                cfg=request.trellis_cfg,
                sampler=request.trellis_sampler,
                scheduler=request.trellis_scheduler,
                filename_prefix=f"genbatch/{request.id}_s{seed}",
                resolution=32 if request.resolution <= 512 else 64,
            )
        except WorkflowError as exc:
            return ExecutionPlan(outcome="failed", reason=str(exc))
        result = self._run(workflow, request.id, seed, "mesh")
        self._record_prompt(task, request, seed, result, "mesh")
        if not result.ok:
            return ExecutionPlan(outcome="failed", reason=result.error)
        node_id = self._node_of(workflow, "SaveGLB")
        glb = result.output(node_id) if node_id else None
        if glb is None:
            return ExecutionPlan(
                outcome="failed", reason="the mesh stage wrote no GLB"
            )
        try:
            mesh = read_glb(glb).mesh
        except GlbError as exc:
            return ExecutionPlan(outcome="failed", reason=str(exc))
        # The repair stage: between the generator and the critic. TRELLIS.2
        # hands over a mesh whose vertices are split at the UV seams, and the
        # critic's watertightness check cannot tell a closed solid from an
        # open one until those seams are welded (docs/lab/exp-mesh-repair.md).
        repair = repair_mesh(mesh, request.repair)
        report = repair.report.after or measure_mesh(repair.mesh)
        variant_id = variant.id if variant is not None else f"{task.id}_s{seed}"
        asset = build_asset(
            request=request,
            variant_id=variant_id,
            glb_path=glb,
            generator=self._recipe(request, seed, seeds, repair),
            licence=licence_for(MESH_MODEL).licence,
            source_image=None,
            critic=None,
        )
        self._store.record_mesh(
            task.id,
            variant_id,
            report,
            asset=asset,
            split=result.split,
            seconds=result.wall_seconds,
            seed=seed,
        )
        self._store.record_repair(task.id, variant_id, repair.report)
        self._resident.add(MESH_MODEL)
        return ExecutionPlan(
            gpu_minutes=result.split.gpu_seconds / 60.0,
            wall_minutes=result.wall_seconds / 60.0,
            artifact=str(glb),
        )

    def _record_prompt(
        self,
        task: Task,
        request: PropRequest,
        seed: int,
        result: PromptResult,
        stage: str,
    ) -> None:
        """Record the window one prompt held the box for.

        The window is what the night's overlap rule is checked against: the
        mesh tail of one prop must never run inside the sampling of the next.
        """
        self._store.record_prompt(
            PromptRecord(
                task_id=task.id,
                variant_id=f"{task.id}_s{seed}",
                stage=stage,
                model=self._plan.model_for(task.id),
                prompt_id=result.prompt_id,
                started_at=result.started_at,
                ended_at=result.ended_at,
                gpu_seconds=result.split.gpu_seconds,
                cpu_seconds=result.split.cpu_seconds,
                unknown_seconds=result.split.unknown_seconds,
            )
        )

    # -- the recipe --------------------------------------------------------

    def _recipe(
        self,
        request: PropRequest,
        seed: int,
        seeds: tuple[int, int, int],
        repair: RepairResult | None = None,
    ) -> dict[str, Any]:
        """The whole recipe, as the asset's provenance."""
        recipe: dict[str, Any] = {
            "prompt": request.prompt,
            "negative": request.negative,
            "model": MESH_MODEL,
            "weights_revision": licence_for(MESH_MODEL).revision,
            "seed": seed,
            "resolution": request.resolution,
            "structure_seed": seeds[0],
            "shape_seed": seeds[1],
            "texture_seed": seeds[2],
            "steps": list(request.trellis_steps),
            "cfg": request.trellis_cfg,
            "sampler": request.trellis_sampler,
            "scheduler": request.trellis_scheduler,
            "workflow_sha256": self._templates.trellis.digest,
            "image_model": "sd_xl_base_1.0",
            "image_seed": seed,
            "image_steps": request.image_steps,
            "image_cfg": request.image_cfg,
            "image_workflow_sha256": self._templates.image.digest,
        }
        if repair is not None:
            # The repair is part of the recipe: what was done to the mesh
            # between the generator and the critic, and what it measured.
            recipe["repair"] = {
                "method": request.repair.method,
                "tolerance": request.repair.tolerance,
                "split_non_manifold": request.repair.split_non_manifold,
                "min_fidelity": request.repair.min_fidelity,
                "seconds": round(repair.report.seconds, 3),
                "welded_vertices": repair.report.welded_vertices,
                "boundary_edges_closed": repair.report.boundary_edges_closed,
                "nonmanifold_edges_split": repair.report.nonmanifold_edges_split,
                "fidelity": round(repair.report.fidelity, 6),
                "ok": repair.report.ok,
                "reason": repair.report.reason,
            }
        return recipe

    # -- the plumbing ------------------------------------------------------

    def _run(
        self, workflow: dict, request_id: str, seed: int, stage: str
    ) -> PromptResult:
        class_types = {
            node_id: str(node.get("class_type", ""))
            for node_id, node in workflow.items()
            if isinstance(node, dict)
        }
        client_id = f"genbatch-{stage}-{request_id}-{seed}"
        return asyncio.run(
            self._client.run_prompt(
                workflow, client_id=client_id, class_types=class_types
            )
        )

    @staticmethod
    def _node_of(workflow: dict, class_type: str) -> str | None:
        found = nodes_of_type(workflow, class_type)
        return found[0][0] if found else None
