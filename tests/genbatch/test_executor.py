"""The executor: the generative job, behind the core's scheduler.

The executor is what the core's night runner asks to do the work. It runs
one image prompt or one mesh prompt, measures what came out, and reports
what it cost — and it reports the cost in the right lane: the sampling is
the GPU's time, the mesh tail is the CPU's.

The ComfyUI client is injected, so these tests never touch a GPU.
"""

from __future__ import annotations

import json

import pytest

from core.genbatch.comfy import PromptResult
from core.genbatch.executor import PropExecutor, Templates
from core.genbatch.models import LaneSplit, NodeTiming, PropRequest
from core.genbatch.schedule import NightPlan
from core.genbatch.store import PropStore
from core.genbatch.workflow import load_template
from core.night.iterate import Variant
from core.records import Task
from tests.genbatch.glb_fixtures import build_glb, cube_mesh

TEMPLATE = {
    "10": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
    "51": {"class_type": "KSampler", "inputs": {"seed": 56, "steps": 12}},
    "52": {"class_type": "VaeDecodeStructureTrellis2", "inputs": {"resolution": 32}},
    "54": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20}},
    "62": {"class_type": "KSampler", "inputs": {"seed": 43, "steps": 12}},
    "71": {"class_type": "RemeshMesh", "inputs": {}},
    "90": {"class_type": "SaveGLB", "inputs": {"filename_prefix": "t"}},
}

IMAGE_TEMPLATE = {
    "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "a"}},
    "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "b"}},
    "13": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
    "14": {"class_type": "KSampler", "inputs": {"seed": 1234, "steps": 30}},
    "16": {"class_type": "SaveImage", "inputs": {"filename_prefix": "i"}},
}

def _png(width: int = 1, height: int = 1) -> bytes:
    """A real PNG, small enough to keep in the test."""
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeComfy:
    """A ComfyUI that writes files instead of generating them."""

    def __init__(self, output_root, *, fail_mesh: bool = False):
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.fail_mesh = fail_mesh
        self.prompts: list[dict] = []
        self.uploads: list[tuple[bytes, str]] = []
        self._counter = 0

    async def run_prompt(self, workflow, *, client_id, class_types=None):
        self.prompts.append(workflow)
        self._counter += 1
        kinds = {node.get("class_type") for node in workflow.values()}
        split = LaneSplit(
            gpu_seconds=16.0,
            cpu_seconds=84.0,
            total_seconds=100.0,
            nodes=[NodeTiming(node="51", class_type="KSampler", lane="gpu", seconds=16.0)],
        )
        if "SaveGLB" in kinds:
            if self.fail_mesh:
                return PromptResult(prompt_id="p", history={}, error="the prompt failed")
            name = f"prop_{self._counter}.glb"
            path = self.output_root / name
            positions, indices = cube_mesh()
            path.write_bytes(build_glb(positions, indices))
            return PromptResult(
                prompt_id="p",
                history={},
                outputs={"90": [path]},
                split=split,
                wall_seconds=100.0,
            )
        name = f"image_{self._counter}.png"
        path = self.output_root / name
        path.write_bytes(_png())
        return PromptResult(
            prompt_id="p",
            history={},
            outputs={"16": [path]},
            split=LaneSplit(gpu_seconds=28.0, total_seconds=28.0),
            wall_seconds=28.0,
        )

    async def upload_image(self, data, filename, *, overwrite=True):
        self.uploads.append((data, filename))
        return filename


def _templates(tmp_path) -> Templates:
    trellis = tmp_path / "trellis2_512.api.json"
    trellis.write_text(json.dumps(TEMPLATE))
    image = tmp_path / "text2image.api.json"
    image.write_text(json.dumps(IMAGE_TEMPLATE))
    return Templates(
        image=load_template(image),
        trellis=load_template(trellis),
    )


def _executor(tmp_path, requests, **kwargs):
    plan = NightPlan(requests)
    store = PropStore()
    client = FakeComfy(tmp_path / "out", **kwargs)
    executor = PropExecutor(
        client=client,
        plan=plan,
        store=store,
        templates=_templates(tmp_path),
    )
    return executor, plan, store, client


def _request() -> PropRequest:
    return PropRequest(
        id="crate",
        prompt="a weathered wooden crate",
        expected_aspect=(1.0, 1.0, 1.0),
        seeds=1,
    )


def test_the_plan_declares_the_model_only_for_the_first_job():
    executor, plan, store, client = _executor(_tmp(), [_request()])
    task = next(t for t in plan.tasks if t.id == "img:crate")

    first = executor.plan(task)
    executor.run(task, Variant(id="v1", seed=1))
    second = executor.plan(task)

    assert first.model == "sd_xl_base_1.0"
    assert second.model is None


def test_the_cost_is_charged_to_the_lane_that_spent_it(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])
    task = next(t for t in plan.tasks if t.id == "prop:crate")
    seed = plan.seeds("crate")[0]

    # The image first, so the mesh has something to work from.
    image_task = next(t for t in plan.tasks if t.id == "img:crate")
    executor.run(image_task, Variant(id="v0", seed=seed))
    result = executor.run(task, Variant(id="v1", seed=seed))

    # 16 s of GPU lane, 100 s of wall.
    assert result.gpu_minutes == pytest.approx(16.0 / 60.0)
    assert result.wall_minutes == pytest.approx(100.0 / 60.0)


def test_the_image_stage_makes_an_image_and_uploads_it(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])
    task = next(t for t in plan.tasks if t.id == "img:crate")
    seed = plan.seeds("crate")[0]

    result = executor.run(task, Variant(id="v0", seed=seed))

    assert result.outcome == "kept"
    assert client.uploads, "the image was not uploaded for the mesh stage to load"
    recorded = store.image("crate", seed)
    assert recorded is not None
    assert recorded.width == 1
    assert recorded.height == 1


def test_the_mesh_stage_makes_a_prop_and_measures_it(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])
    seed = plan.seeds("crate")[0]
    image_task = next(t for t in plan.tasks if t.id == "img:crate")
    executor.run(image_task, Variant(id="v0", seed=seed))
    task = next(t for t in plan.tasks if t.id == "prop:crate")

    result = executor.run(task, Variant(id="prop:crate_r1_v1", seed=seed))

    assert result.outcome == "kept"
    report = store.mesh("prop:crate", "prop:crate_r1_v1")
    assert report is not None
    assert report.triangles == 12
    assert report.watertight is True
    assert result.artifact is not None


def test_the_prop_is_recorded_as_an_asset_with_its_recipe(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])
    seed = plan.seeds("crate")[0]
    image_task = next(t for t in plan.tasks if t.id == "img:crate")
    executor.run(image_task, Variant(id="v0", seed=seed))
    task = next(t for t in plan.tasks if t.id == "prop:crate")

    executor.run(task, Variant(id="prop:crate_r1_v1", seed=seed))

    asset = store.asset("prop:crate", "prop:crate_r1_v1")
    assert asset is not None
    recipe = asset.provenance.generator
    assert recipe["prompt"] == "a weathered wooden crate"
    assert recipe["model"] == "trellis2"
    assert recipe["seed"] == seed
    assert recipe["resolution"] == 512
    assert recipe["weights_revision"].startswith("430a9d0")
    assert recipe["workflow_sha256"]
    assert asset.licence.spdx == "MIT"


def test_a_mesh_prompt_that_fails_is_a_failed_prop(tmp_path):
    executor, plan, store, client = _executor(
        tmp_path, [_request()], fail_mesh=True
    )
    seed = plan.seeds("crate")[0]
    image_task = next(t for t in plan.tasks if t.id == "img:crate")
    executor.run(image_task, Variant(id="v0", seed=seed))
    task = next(t for t in plan.tasks if t.id == "prop:crate")

    result = executor.run(task, Variant(id="prop:crate_r1_v1", seed=seed))

    assert result.outcome == "failed"
    assert "failed" in (result.reason or "")


def test_a_mesh_without_an_image_fails_rather_than_guessing(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])
    task = next(t for t in plan.tasks if t.id == "prop:crate")

    result = executor.run(task, Variant(id="prop:crate_r1_v1", seed=plan.seeds("crate")[0]))

    assert result.outcome == "failed"
    assert "image" in (result.reason or "")


def test_a_task_with_no_request_is_refused(tmp_path):
    executor, plan, store, client = _executor(tmp_path, [_request()])

    result = executor.run(Task(id="prop:nothing", intention="?"))

    assert result.outcome == "failed"


def _tmp():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
