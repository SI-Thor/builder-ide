"""Where a prompt's time went: the GPU lane, the CPU lane, and the rest.

ComfyUI's history keeps only prompt-level timestamps, and ``/object_info``
says nothing about time. The per-node timings come from the websocket, which
streams an ``executing`` message when each node starts.

There is no reliable node-*end* message: ComfyUI sends ``executed`` only for
nodes that produce a UI output, and a KSampler returns a latent, so the
nodes that do the work never get one. What works is the gap to the next
node's start, because a prompt's nodes run in order — the last node runs
until the prompt reports success.

The lane rule is the TRELLIS.2 spike's own (docs/research/trellis-spike.md
§4.4): *the GPU's own stage is KSampler; everything else is either model
loading or the CPU-bound mesh tail.* A node this seat has never heard of is
left **unknown** rather than guessed into a lane, so a report can say what
it does not know.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Iterable, Sequence

from core.genbatch.models import Lane, LaneSplit, NodeTiming

__all__ = [
    "CPU_NODE_TYPES",
    "GPU_NODE_TYPES",
    "PromptTimer",
    "lane_for",
    "split_lanes",
]

#: The nodes that spend their time on the GPU.
GPU_NODE_TYPES = frozenset(
    {
        "KSampler",
        "CLIPTextEncode",
        "VAEDecode",
        "VaeDecodeStructureTrellis2",
        "VaeDecodeShapeTrellis",
        "VaeDecodeTextureTrellis",
        "Trellis2Conditioning",
        "Trellis2ShapeStage",
        "Trellis2TextureStage",
        "Trellis2UpsampleStage",
        "ModelSamplingSD3",
        "CFGOverride",
        "RescaleCFG",
        "EmptyTrellis2LatentStructure",
        "EmptyLatentImage",
    }
)

#: The nodes that spend their time on the CPU: the mesh tail, the model
#: loading, and the image stage's own encoding.
CPU_NODE_TYPES = frozenset(
    {
        "RemeshMesh",
        "DecimateMesh",
        "MeshSmoothNormals",
        "UnwrapMesh",
        "BakeTextureFromVoxel",
        "BakeAmbientOcclusion",
        "BakeNormalMapFromMesh",
        "ApplyTextureToMesh",
        "GetMeshInfo",
        "SaveGLB",
        "SaveImage",
        "LoadImage",
        "MaskPreview",
        "ImageCropToMask",
        "UNETLoader",
        "VAELoader",
        "CLIPVisionLoader",
        "CheckpointLoaderSimple",
    }
)


def lane_for(class_type: str) -> Lane:
    """Which lane a node's time belongs to."""
    if class_type in GPU_NODE_TYPES:
        return "gpu"
    if class_type in CPU_NODE_TYPES:
        return "cpu"
    return "unknown"


def split_lanes(entries: Iterable[tuple[str, str, float]]) -> LaneSplit:
    """Split a list of ``(node, class_type, seconds)`` into the lanes."""
    nodes: list[NodeTiming] = []
    gpu = cpu = unknown = 0.0
    for node_id, class_type, seconds in entries:
        lane = lane_for(class_type)
        nodes.append(
            NodeTiming(node=node_id, class_type=class_type, lane=lane, seconds=seconds)
        )
        if lane == "gpu":
            gpu += seconds
        elif lane == "cpu":
            cpu += seconds
        else:
            unknown += seconds
    return LaneSplit(
        gpu_seconds=gpu,
        cpu_seconds=cpu,
        unknown_seconds=unknown,
        total_seconds=gpu + cpu + unknown,
        nodes=nodes,
    )


class PromptTimer:
    """The per-node timings of one prompt.

    The socket has to be open **before** the prompt is posted: ComfyUI
    publishes the per-node messages to the client id that owns the prompt,
    and a message published to a client id that is not connected yet is
    dropped rather than queued. Open late and the breakdown loses its early
    nodes — which is exactly the part that matters.
    """

    def __init__(self, base_url: str, client_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self._session = None
        self._ws = None
        self._task = None
        self._starts: dict[str, float] = {}
        self._ends: dict[str, float] = {}
        self._order: list[str] = []
        self._finished_at: float | None = None
        self._error: str | None = None
        self._messages: list[tuple[float, str, str | None, str | None]] = []

    # -- the socket --------------------------------------------------------

    async def open(self) -> "PromptTimer":
        """Connect, and start reading."""
        try:
            import aiohttp
        except ImportError as exc:  # pragma: no cover - the extra is optional
            raise RuntimeError(
                "the per-node timings need aiohttp: "
                "pip install 'builder-ide-core[propgen]'"
            ) from exc
        self._aiohttp = aiohttp
        self._session = aiohttp.ClientSession()
        url = f"{self.base_url}/ws?clientId={self.client_id}"
        self._ws = await self._session.ws_connect(url, heartbeat=30)
        self._task = asyncio.get_running_loop().create_task(self._read())
        return self

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
        if self._session is not None:
            await self._session.close()
        self._ws = None
        self._task = None
        self._session = None

    async def __aenter__(self) -> "PromptTimer":
        return await self.open()

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def _read(self) -> None:
        """Read the socket until it closes.

        Nothing in here may block: a blocking call freezes the reader for
        long stretches, the messages then arrive in one burst, and every
        per-node timestamp becomes the same instant.
        """
        assert self._ws is not None
        try:
            async for message in self._ws:
                if message.type != self._aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(message.data)
                except (TypeError, ValueError):
                    continue
                kind = data.get("type")
                payload = data.get("data")
                if not isinstance(payload, dict):
                    continue
                node = payload.get("node")
                node_id = str(node) if node is not None else None
                prompt_id = payload.get("prompt_id")
                if kind not in ("executing", "executed", "execution_success", "execution_error"):
                    continue
                now = time.monotonic()
                self._messages.append((now, str(kind), node_id, prompt_id))
                if kind == "executing" and node_id is not None:
                    if node_id not in self._starts:
                        self._order.append(node_id)
                    self._starts[node_id] = now
                elif kind == "executed" and node_id is not None:
                    self._ends[node_id] = now
                elif kind in ("execution_success", "execution_error"):
                    self._finished_at = now
        except Exception as exc:  # noqa: BLE001 - the socket dies, the prompt does not
            self._error = repr(exc)

    # -- the reading -------------------------------------------------------

    async def capture(self, prompt_id: str, *, timeout: float = 3600.0) -> LaneSplit:
        """Wait for the prompt to finish, and split its time by lane."""
        deadline = time.monotonic() + timeout
        while self._finished_at is None and time.monotonic() < deadline:
            await self._asyncio_sleep(0.2)
        if self._finished_at is None:
            raise TimeoutError(
                f"prompt {prompt_id} did not finish within {timeout:.0f}s"
            )
        return self.split(prompt_id)

    async def _asyncio_sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def split(self, prompt_id: str, class_types: dict[str, str] | None = None) -> LaneSplit:
        """The lane split for one prompt, from what the socket heard."""
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        order: list[str] = []
        finished: float | None = None
        for when, kind, node_id, message_prompt in self._messages:
            if message_prompt != prompt_id:
                continue
            if kind == "executing" and node_id is not None:
                if node_id not in starts:
                    order.append(node_id)
                starts[node_id] = when
            elif kind == "executed" and node_id is not None:
                ends[node_id] = when
            elif kind in ("execution_success", "execution_error"):
                finished = when
        if finished is None:
            finished = self._finished_at or time.monotonic()

        entries: list[tuple[str, str, float]] = []
        for index, node_id in enumerate(order):
            start = starts.get(node_id)
            if start is None:
                continue
            if node_id in ends:
                end = ends[node_id]
            elif index + 1 < len(order) and order[index + 1] in starts:
                end = starts[order[index + 1]]
            else:
                end = finished
            seconds = max(0.0, end - start)
            class_type = (class_types or {}).get(node_id, "")
            entries.append((node_id, class_type, seconds))
        return split_lanes(entries)
