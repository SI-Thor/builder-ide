"""The records this seat keeps: what was asked, what was measured, what it scored.

Everything here is a pydantic model, so a record can be folded into the
ledger, written into the morning report and read back without a second
translation layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.genbatch.repair import RepairRecipe

__all__ = [
    "CheckResult",
    "ImageResult",
    "LaneSplit",
    "NodeTiming",
    "PromptRecord",
    "PropRequest",
    "PropVerdict",
    "StageKind",
]

#: Which lane a piece of work belongs to. The GPU lane is the sampling; the
#: CPU lane is the mesh tail, which is where the Thor's scarce resource
#: actually is (docs/research/trellis-spike.md §4.3).
Lane = Literal["gpu", "cpu", "unknown"]


class StageKind(str, Enum):
    """The two GPU stages of a prop, in the order the night runs them."""

    IMAGE = "image"
    MESH = "mesh"


class PropRequest(BaseModel):
    """One prop the owner asked for.

    ``prompt`` is the concept — "a weathered wooden crate". If an ``image`` is
    given, the night starts from that image instead of making one; otherwise
    the concept goes through the local image model first.

    ``expected_aspect`` is the shape the requester expects, as ``x:y:z``
    normalised so its largest axis is 1. It is the only part of the shape a
    generated prop can be held to: TRELLIS.2 normalises the prop's size away
    (the largest horizontal extent comes out as one unit), so the absolute
    size is the caller's business and the *proportions* are the generator's.
    """

    id: str
    prompt: str = ""
    negative: str = ""
    #: An image to start from. When it is set, the night does not run the
    #: image stage for this request.
    image: str | None = None
    #: How many seeds to try for this prop.
    seeds: int = Field(default=3, ge=1)
    #: The triangle budget the critic holds the prop to.
    triangle_budget: int = Field(default=700_000, ge=1)
    #: The shape asked for, as ``x:y:z`` normalised to its largest axis.
    expected_aspect: tuple[float, float, float] | None = None
    #: How far the measured aspect may sit from the expected one, relative.
    aspect_tolerance: float = Field(default=0.25, ge=0.0)
    #: The acceptable range for the prop's volume as a fraction of its
    #: bounding box — a prop that fills its box is solid, one that fills a
    #: thousandth of it is a shell. A solid cannot fill *more* than its box.
    fill_ratio: tuple[float, float] = (0.005, 1.0)
    #: The TRELLIS.2 resolution: 512 or 1024.
    resolution: int = Field(default=512, ge=64)
    #: The dtype the TRELLIS.2 weights are loaded in.
    #:
    #: "default" is the model's own dtype — bfloat16 on this box — and it is
    #: the default because fp8 has to earn its place before it is asked for
    #: (docs/lab/exp-fp8-real.md). "fp8_e4m3fn_fast" is the fused fp8 path:
    #: the weights are stored in fp8 and the matmul itself runs in fp8.
    #: "fp8_e4m3fn" stores the weights in fp8 but casts them back to the
    #: compute dtype at every use.
    #:
    #: Asking for fp8 needs two things: this parameter, and a ComfyUI with
    #: the fp8 fix installed (the fused path declines without it — see
    #: docs/lab/trellis-graph-scripts/comfy-base/custom_nodes/fp8_real).
    weight_dtype: Literal[
        "default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"
    ] = "default"
    #: The image stage's knobs (SDXL).
    image_steps: int = Field(default=30, ge=1)
    image_cfg: float = Field(default=7.0, ge=0.0)
    image_sampler: str = "dpmpp_2m"
    image_scheduler: str = "karras"
    image_size: int = Field(default=1024, ge=64)
    #: The TRELLIS.2 stage's knobs: structure, shape and texture steps.
    trellis_steps: tuple[int, int, int] = (12, 20, 12)
    trellis_cfg: float = Field(default=7.5, ge=0.0)
    trellis_sampler: str = "euler"
    trellis_scheduler: str = "normal"
    #: The anchor the request's seeds are derived from, so the night's work
    #: replays.
    base_seed: int = Field(default=0, ge=0)
    #: The repair stage: what the pipeline does to the mesh between the
    #: generator and the critic. It is part of the recipe because it is part
    #: of what the night does — and because a different repair is a different
    #: prop.
    repair: RepairRecipe = Field(default_factory=RepairRecipe)

    @field_validator("expected_aspect")
    @classmethod
    def _normalise_aspect(cls, value: tuple[float, float, float] | None):
        """Normalise the expected aspect so its largest axis is one."""
        if value is None:
            return None
        if any(axis <= 0 for axis in value):
            raise ValueError("the expected aspect needs every axis above zero")
        largest = max(value)
        return tuple(axis / largest for axis in value)

    @property
    def starts_from_an_image(self) -> bool:
        """True when the request carries its own image."""
        return self.image is not None


class NodeTiming(BaseModel):
    """One node's wall time, and the lane it was spent in."""

    node: str
    class_type: str
    lane: Lane = "unknown"
    seconds: float = 0.0


class ImageResult(BaseModel):
    """One image the image stage made, and what it cost."""

    seed: int
    path: str
    width: int = 0
    height: int = 0
    seconds: float = 0.0
    prompt: str = ""


class PromptRecord(BaseModel):
    """One prompt, and the window it held the box for.

    The window is what the night's overlap rule is checked against: the
    mesh tail of one prop must never run inside the sampling of the next.
    """

    task_id: str
    variant_id: str
    stage: str
    model: str
    prompt_id: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    unknown_seconds: float = 0.0

    @property
    def seconds(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    def overlaps(self, other: "PromptRecord") -> bool:
        """True when the two windows share any time at all."""
        return self.started_at < other.ended_at and other.started_at < self.ended_at


class LaneSplit(BaseModel):
    """A prompt's time, split by the lane that spent it.

    This is the number the night's scheduling rests on: the GPU lane's time
    is the sampling, and the CPU lane's time is the mesh tail — the part that
    is fixed per prop and that the box cannot hide.
    """

    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    unknown_seconds: float = 0.0
    total_seconds: float = 0.0
    nodes: list[NodeTiming] = Field(default_factory=list)

    @property
    def cpu_fraction(self) -> float:
        """How much of the prompt the CPU lane took."""
        if self.total_seconds <= 0:
            return 0.0
        return self.cpu_seconds / self.total_seconds


class CheckResult(BaseModel):
    """One check the critic ran, and what it made of the prop."""

    name: str
    #: 0.0 to 1.0 — a graded judgement, not just a verdict.
    score: float = 0.0
    weight: float = 1.0
    passed: bool = False
    detail: str = ""


class PropVerdict(BaseModel):
    """The critic's judgement of one prop."""

    score: float = 0.0
    checks: list[CheckResult] = Field(default_factory=list)
    reason: str = ""
    degraded: bool = False
