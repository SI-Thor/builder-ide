"""The night driver: the whole thing, end to end, on a fake box.

A mini-night with a fake ComfyUI, so the wiring is tested without a GPU:
the plan becomes a queue, the queue becomes attempts, the attempts are
scored, and the morning says who won and what it beat.
"""

from __future__ import annotations

import json

import pytest

from core.genbatch.comfy import PromptResult
from core.genbatch.executor import Templates
from core.genbatch.models import LaneSplit, NodeTiming, PropRequest
from core.genbatch.night import MeasuredClock, run_prop_night
from core.genbatch.workflow import load_template
from core.night.ledger import InMemoryLedger
from core.night.models import Rail
from tests.genbatch.glb_fixtures import build_glb, cube_mesh, quad_mesh

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


class FakeComfy:
    """Makes a closed cube for even seeds and an open sheet for odd ones."""

    def __init__(self, output_root):
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.prompts: list[dict] = []
        self._counter = 0
        self._clock = 0.0

    async def run_prompt(self, workflow, *, client_id, class_types=None):
        self.prompts.append(workflow)
        self._counter += 1
        started = self._clock
        kinds = {node.get("class_type") for node in workflow.values()}
        split = LaneSplit(
            gpu_seconds=16.0,
            cpu_seconds=84.0,
            total_seconds=100.0,
            nodes=[NodeTiming(node="51", class_type="KSampler", lane="gpu", seconds=16.0)],
        )
        if "SaveGLB" in kinds:
            seed = workflow["51"]["inputs"]["seed"]
            positions, indices = cube_mesh() if seed % 2 == 0 else quad_mesh()
            path = self.output_root / f"prop_{self._counter}.glb"
            path.write_bytes(build_glb(positions, indices))
            self._clock = started + 100.0
            return PromptResult(
                prompt_id=f"p{self._counter}",
                history={},
                outputs={"90": [path]},
                split=split,
                wall_seconds=100.0,
                started_at=started,
                ended_at=self._clock,
            )
        path = self.output_root / f"image_{self._counter}.png"
        path.write_bytes(_png())
        self._clock = started + 28.0
        return PromptResult(
            prompt_id=f"p{self._counter}",
            history={},
            outputs={"16": [path]},
            split=LaneSplit(gpu_seconds=28.0, total_seconds=28.0),
            wall_seconds=28.0,
            started_at=started,
            ended_at=self._clock,
        )

    async def upload_image(self, data, filename, *, overwrite=True):
        return filename


def _png(width: int = 1024, height: int = 1024) -> bytes:
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


def _templates(tmp_path) -> Templates:
    trellis = tmp_path / "trellis2_512.api.json"
    trellis.write_text(json.dumps(TEMPLATE))
    image = tmp_path / "text2image.api.json"
    image.write_text(json.dumps(IMAGE_TEMPLATE))
    return Templates(image=load_template(image), trellis=load_template(trellis))


def _requests() -> list[PropRequest]:
    return [
        PropRequest(
            id="crate",
            prompt="a weathered wooden crate",
            expected_aspect=(1.0, 1.0, 1.0),
            seeds=3,
        ),
        PropRequest(id="lantern", prompt="a dented brass lantern", seeds=3),
    ]


def _run(tmp_path, requests=None):
    requests = requests if requests is not None else _requests()
    client = FakeComfy(tmp_path / "out")
    report = run_prop_night(
        requests=requests,
        client=client,
        templates=_templates(tmp_path),
        ledger=InMemoryLedger(),
        night_id="night-test",
        clock=MeasuredClock(),
    )
    return report, client


def test_the_night_makes_a_prop_for_every_request(tmp_path):
    report, client = _run(tmp_path)

    assert {winner.request_id for winner in report.winners} == {"crate", "lantern"}


def test_the_night_tries_every_seed(tmp_path):
    report, client = _run(tmp_path)

    # Two requests of three seeds: six mesh prompts, six image prompts.
    assert len(client.prompts) == 12


def test_the_winner_is_the_one_that_passed_the_checks(tmp_path):
    report, client = _run(tmp_path)

    for winner in report.winners:
        assert winner.watertight is True
        assert winner.triangles == 12


def test_the_morning_says_what_the_winner_beat(tmp_path):
    report, client = _run(tmp_path)

    card = next(
        iteration
        for iteration in report.night.iterations
        if iteration.task_id.startswith("prop:")
    )
    assert card.runner_ups, "the morning did not say what the winner beat"
    assert card.winner.score > 0


def test_the_model_is_loaded_once_a_night(tmp_path):
    report, client = _run(tmp_path)

    assert report.night.numbers.model_loads == {"sd_xl_base_1.0": 1, "trellis2": 1}


def test_the_lane_split_shows_the_cpu_tail(tmp_path):
    report, client = _run(tmp_path)

    assert report.lanes.prompts == 12
    assert report.lanes.cpu_seconds > report.lanes.gpu_seconds
    assert report.lanes.cpu_fraction > 0.5


def test_nothing_ran_at_the_same_time(tmp_path):
    report, client = _run(tmp_path)

    assert report.lanes.overlaps == 0


def test_the_rules_are_in_the_report(tmp_path):
    report, client = _run(tmp_path)

    assert [rule.name for rule in report.rules] == [
        "batch_by_model",
        "cpu_mesh_tail",
        "no_overlap",
        "costs_from_the_model",
    ]


def test_the_assets_are_in_the_report(tmp_path):
    report, client = _run(tmp_path)

    assert report.assets
    for asset in report.assets:
        assert asset.licence.spdx == "MIT"
        assert asset.provenance.generator["model"] == "trellis2"


def test_the_report_renders_as_text(tmp_path):
    report, client = _run(tmp_path)

    text = report.render_text()

    assert "crate" in text
    assert "batch_by_model" in text
