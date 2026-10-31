"""The workflows the night sends to ComfyUI, and the lane their time is in.

Two things are tested here that never touch the network: that the workflow
builder patches the right nodes of the TRELLIS.2 environment's own templates,
and that the per-node timings are split into the GPU lane and the CPU lane
the way the spike found them.

The lane rule is the spike's own (§4.4): *the GPU's own stage is KSampler;
everything else is either model loading or the CPU-bound mesh tail.* A node
this seat has never heard of is left **unknown** rather than guessed into a
lane, so the report can say what it does not know.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from core.genbatch.timing import lane_for, split_lanes
from core.genbatch.workflow import (
    WorkflowError,
    build_image_workflow,
    build_trellis_workflow,
    load_template,
    trellis_seeds,
)

TEMPLATE = {
    "10": {
        "class_type": "LoadImage",
        "inputs": {"image": "viking_wolf_rune_axe.png"},
    },
    "20": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "dino.safetensors"}},
    "30": {"class_type": "UNETLoader", "inputs": {"unet_name": "trellis_2_bf16.safetensors"}},
    "51": {
        "class_type": "KSampler",
        "inputs": {"seed": 56, "steps": 12, "cfg": 7.5, "sampler_name": "euler"},
    },
    "52": {
        "class_type": "VaeDecodeStructureTrellis2",
        "inputs": {"samples": ["51", 0], "resolution": 32},
    },
    "54": {
        "class_type": "KSampler",
        "inputs": {"seed": 42, "steps": 20, "cfg": 7.5, "sampler_name": "euler"},
    },
    "62": {
        "class_type": "KSampler",
        "inputs": {"seed": 43, "steps": 12, "cfg": 1.0, "sampler_name": "euler"},
    },
    "71": {"class_type": "RemeshMesh", "inputs": {"resolution": 768}},
    "72": {"class_type": "DecimateMesh", "inputs": {"target_face_count": 700000}},
    "90": {"class_type": "SaveGLB", "inputs": {"filename_prefix": "trellis2/axe_512"}},
}

IMAGE_TEMPLATE = {
    "10": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl.safetensors"}},
    "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "a placeholder"}},
    "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality"}},
    "13": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
    "14": {
        "class_type": "KSampler",
        "inputs": {"seed": 1234, "steps": 30, "cfg": 7.0, "sampler_name": "dpmpp_2m"},
    },
    "15": {"class_type": "VAEDecode", "inputs": {}},
    "16": {"class_type": "SaveImage", "inputs": {"filename_prefix": "trellis2/text2image"}},
}


def _write_template(tmp_path, name, body) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(body))
    return str(path)


def test_a_template_is_read_and_its_digest_recorded(tmp_path):
    path = _write_template(tmp_path, "trellis2_512.api.json", TEMPLATE)

    template = load_template(path)

    assert template.digest == hashlib.sha256(
        (tmp_path / "trellis2_512.api.json").read_bytes()
    ).hexdigest()
    assert "51" in template.workflow


def test_a_template_that_is_not_there_is_an_error(tmp_path):
    with pytest.raises(WorkflowError):
        load_template(str(tmp_path / "missing.api.json"))


def test_the_image_workflow_carries_the_prompt_and_the_seed(tmp_path):
    template = load_template(_write_template(tmp_path, "t2i.api.json", IMAGE_TEMPLATE))

    workflow = build_image_workflow(
        template,
        prompt="a weathered wooden crate",
        negative="blurry, low quality",
        seed=4242,
        size=1024,
        steps=30,
        cfg=7.0,
        sampler="dpmpp_2m",
        scheduler="karras",
        filename_prefix="genbatch/crate_s4242",
    )

    assert workflow["11"]["inputs"]["text"] == "a weathered wooden crate"
    assert workflow["12"]["inputs"]["text"] == "blurry, low quality"
    assert workflow["14"]["inputs"]["seed"] == 4242
    assert workflow["14"]["inputs"]["steps"] == 30
    assert workflow["13"]["inputs"]["width"] == 1024
    assert workflow["16"]["inputs"]["filename_prefix"] == "genbatch/crate_s4242"


def test_the_template_is_not_modified_by_the_builder(tmp_path):
    template = load_template(_write_template(tmp_path, "t2i.api.json", IMAGE_TEMPLATE))
    before = json.dumps(template.workflow, sort_keys=True)

    build_image_workflow(
        template,
        prompt="a weathered wooden crate",
        negative="",
        seed=1,
        size=512,
        steps=10,
        cfg=7.0,
        sampler="dpmpp_2m",
        scheduler="karras",
        filename_prefix="genbatch/x",
    )

    assert json.dumps(template.workflow, sort_keys=True) == before


def test_the_mesh_workflow_carries_the_image_and_the_three_seeds(tmp_path):
    template = load_template(_write_template(tmp_path, "trellis2.api.json", TEMPLATE))
    seeds = trellis_seeds(4242)

    workflow = build_trellis_workflow(
        template,
        image_name="crate_s4242.png",
        seeds=seeds,
        steps=(12, 20, 12),
        cfg=7.5,
        sampler="euler",
        scheduler="normal",
        filename_prefix="genbatch/crate_s4242",
    )

    assert workflow["10"]["inputs"]["image"] == "crate_s4242.png"
    assert workflow["51"]["inputs"]["seed"] == seeds[0]
    assert workflow["54"]["inputs"]["seed"] == seeds[1]
    assert workflow["62"]["inputs"]["seed"] == seeds[2]
    assert workflow["90"]["inputs"]["filename_prefix"] == "genbatch/crate_s4242"


def test_the_mesh_workflow_carries_the_resolution(tmp_path):
    template = load_template(_write_template(tmp_path, "trellis2.api.json", TEMPLATE))

    workflow = build_trellis_workflow(
        template,
        image_name="crate.png",
        seeds=(1, 2, 3),
        steps=(12, 20, 12),
        cfg=7.5,
        sampler="euler",
        scheduler="normal",
        filename_prefix="genbatch/crate",
        resolution=32,
    )

    assert workflow["52"]["inputs"]["resolution"] == 32


def test_a_template_without_the_nodes_we_need_is_an_error(tmp_path):
    template = load_template(
        _write_template(tmp_path, "broken.api.json", {"1": {"class_type": "Nothing"}})
    )

    with pytest.raises(WorkflowError):
        build_trellis_workflow(
            template,
            image_name="crate.png",
            seeds=(1, 2, 3),
            steps=(12, 20, 12),
            cfg=7.5,
            sampler="euler",
            scheduler="normal",
            filename_prefix="genbatch/crate",
        )


def test_the_three_seeds_are_different_and_repeatable():
    seeds = trellis_seeds(4242)

    assert len(set(seeds)) == 3
    assert seeds == trellis_seeds(4242)
    assert seeds != trellis_seeds(4243)


def test_the_sampler_is_the_gpu_lane():
    assert lane_for("KSampler") == "gpu"
    assert lane_for("VaeDecodeShapeTrellis") == "gpu"


def test_the_mesh_tail_is_the_cpu_lane():
    assert lane_for("RemeshMesh") == "cpu"
    assert lane_for("UnwrapMesh") == "cpu"
    assert lane_for("BakeAmbientOcclusion") == "cpu"
    assert lane_for("SaveGLB") == "cpu"


def test_a_node_we_do_not_know_is_left_unknown():
    assert lane_for("SomeNodeFromNextYear") == "unknown"


def test_the_split_adds_up_the_lanes():
    split = split_lanes(
        [
            ("51", "KSampler", 16.0),
            ("71", "RemeshMesh", 4.0),
            ("74", "UnwrapMesh", 21.0),
            ("99", "SomeNodeFromNextYear", 3.0),
        ]
    )

    assert split.gpu_seconds == pytest.approx(16.0)
    assert split.cpu_seconds == pytest.approx(25.0)
    assert split.unknown_seconds == pytest.approx(3.0)
    assert split.total_seconds == pytest.approx(44.0)
    assert split.cpu_fraction == pytest.approx(25.0 / 44.0)


def test_an_empty_split_is_all_zeroes():
    split = split_lanes([])

    assert split.total_seconds == 0.0
    assert split.cpu_fraction == 0.0
