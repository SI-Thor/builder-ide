"""The ComfyUI client: the TRELLIS.2 environment, over HTTP.

ComfyUI is GPL-3.0 and it stays a separate service for exactly that reason
(docs/research/trellis-spike.md §6) — this seat talks to it over HTTP and
never links it.

Two things are worth knowing about the API:

* an image has to be **uploaded** before a workflow can load it, so the
  image stage's output goes through ``/upload/image`` rather than being
  written into the environment's input directory by hand;
* the socket has to be open **before** the prompt is posted, or ComfyUI
  drops the per-node messages and the lane breakdown collapses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.genbatch.models import LaneSplit
from core.genbatch.timing import PromptTimer

__all__ = ["ComfyClient", "ComfyError", "PromptResult"]

#: The node classes that write a file. If a prompt that has one of them
#: produces no file, the prompt was refused.
OUTPUT_NODE_TYPES = frozenset(
    {"SaveGLB", "SaveImage", "SaveImageAdvanced", "PreviewImage", "Save3DAdvanced"}
)


class ComfyError(RuntimeError):
    """ComfyUI said no, or said something we cannot read."""


@dataclass
class PromptResult:
    """What one prompt produced, and what it cost."""

    prompt_id: str
    history: dict
    #: The files the prompt wrote, by the node that wrote them.
    outputs: dict[str, list[Path]] = field(default_factory=dict)
    #: The lane split of the prompt's time.
    split: LaneSplit = field(default_factory=LaneSplit)
    wall_seconds: float = 0.0
    #: When the prompt started and ended, on the monotonic clock.
    started_at: float = 0.0
    ended_at: float = 0.0
    #: The error, when the prompt failed.
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def output(self, node_id: str) -> Path | None:
        """The first file a node wrote."""
        files = self.outputs.get(node_id) or []
        return files[0] if files else None


class ComfyClient:
    """A client for one ComfyUI server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        *,
        output_root: str | Path = "~/lm-wt/trellis/out",
        timeout: float = 3600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.output_root = Path(output_root).expanduser()
        self.timeout = timeout

    # -- the plain calls ----------------------------------------------------

    def _session(self):
        """A fresh session. The client is used once per call, so the
        session is too."""
        try:
            import aiohttp
        except ImportError as exc:  # pragma: no cover - the extra is optional
            raise ComfyError(
                "talking to ComfyUI needs aiohttp: "
                "pip install 'builder-ide-core[propgen]'"
            ) from exc
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

    async def get_json(self, path: str) -> Any:
        import aiohttp

        async with self._session() as session:
            async with session.get(f"{self.base_url}{path}") as response:
                if response.status != 200:
                    raise ComfyError(f"GET {path} answered {response.status}")
                return await response.json()

    async def system_stats(self) -> dict:
        """The server's own account of the box."""
        return await self.get_json("/system_stats")

    async def upload_image(
        self, data: bytes, filename: str, *, overwrite: bool = True
    ) -> str:
        """Put an image where ComfyUI can load it, and return its name."""
        import aiohttp

        form = aiohttp.FormData()
        form.add_field(
            "image",
            data,
            filename=filename,
            content_type="image/png",
        )
        form.add_field("type", "input")
        form.add_field("overwrite", "true" if overwrite else "false")
        async with self._session() as session:
            async with session.post(f"{self.base_url}/upload/image", data=form) as response:
                if response.status != 200:
                    raise ComfyError(
                        f"the image upload answered {response.status}: "
                        f"{await response.text()}"
                    )
                body = await response.json()
        name = body.get("name")
        if not name:
            raise ComfyError(f"the image upload returned no name: {body!r}")
        subfolder = body.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else str(name)

    async def queue_prompt(self, workflow: dict, *, client_id: str) -> str:
        """Put a prompt in the queue, and return its id."""
        import aiohttp

        payload = {"prompt": workflow, "client_id": client_id}
        async with self._session() as session:
            async with session.post(
                f"{self.base_url}/prompt", json=payload
            ) as response:
                if response.status != 200:
                    raise ComfyError(
                        f"the prompt was refused ({response.status}): "
                        f"{await response.text()}"
                    )
                body = await response.json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"the queue returned no prompt id: {body!r}")
        return str(prompt_id)

    async def history(self, prompt_id: str) -> dict | None:
        """The history entry for a prompt, once it is there."""
        body = await self.get_json(f"/history/{prompt_id}")
        return body.get(prompt_id) if isinstance(body, dict) else None

    async def wait_for(self, prompt_id: str) -> dict:
        """Wait for a prompt to finish, and return its history entry."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            entry = await self.history(prompt_id)
            if entry is not None:
                return entry
            import asyncio

            await asyncio.sleep(1.0)
        raise ComfyError(f"prompt {prompt_id} did not finish within {self.timeout:.0f}s")

    # -- the whole round trip ----------------------------------------------

    async def run_prompt(
        self,
        workflow: dict,
        *,
        client_id: str,
        class_types: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> PromptResult:
        """Run one prompt, and collect its outputs and its lane split.

        The socket opens first, on purpose: ComfyUI drops the per-node
        messages for a client that is not connected when they are published.
        """
        timeout = self.timeout if timeout is None else timeout
        started = time.monotonic()
        timer = await PromptTimer(self.base_url, client_id).open()
        try:
            prompt_id = await self.queue_prompt(workflow, client_id=client_id)
            entry = await self.wait_for(prompt_id)
            try:
                split = await timer.capture(prompt_id, timeout=timeout)
            except TimeoutError:
                split = LaneSplit()
            if class_types is not None:
                split = timer.split(prompt_id, class_types)
            result = PromptResult(
                prompt_id=prompt_id,
                history=entry,
                outputs=self._outputs(entry),
                split=split,
                wall_seconds=time.monotonic() - started,
                started_at=started,
                ended_at=time.monotonic(),
            )
            status = (entry.get("status") or {}).get("status_str")
            if status == "error":
                result.error = self._error_text(entry)
            if result.error is None:
                result.error = self._missing_output_text(workflow, result)
            return result
        finally:
            await timer.close()

    def _outputs(self, entry: dict) -> dict[str, list[Path]]:
        """The files the prompt wrote, by the node that wrote them."""
        found: dict[str, list[Path]] = {}
        for node_id, output in (entry.get("outputs") or {}).items():
            if not isinstance(output, dict):
                continue
            paths: list[Path] = []
            for key in ("3d", "images", "gltf"):
                for item in output.get(key) or []:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    if not filename:
                        continue
                    subfolder = item.get("subfolder") or ""
                    path = self.output_root / subfolder / filename
                    if path.exists():
                        paths.append(path)
            if paths:
                found[str(node_id)] = paths
        return found

    def _missing_output_text(self, workflow: dict, result: PromptResult) -> str | None:
        """Name the outputs a refused prompt did not write.

        ComfyUI refuses a workflow it cannot validate — a combo given the
        wrong type of value, say — by ignoring the output nodes and
        reporting **success** in its history. The refusal is only in its
        log. A prompt that was supposed to write a file and wrote none was
        refused, and the morning has to be able to say so.
        """
        missing = [
            node_id
            for node_id, node in workflow.items()
            if isinstance(node, dict)
            and node.get("class_type") in OUTPUT_NODE_TYPES
            and not result.outputs.get(node_id)
        ]
        if not missing:
            return None
        return (
            "the prompt wrote no output for node(s) "
            f"{', '.join(sorted(missing))} — ComfyUI refused the workflow"
        )

    def _error_text(self, entry: dict) -> str:
        for message in (entry.get("status") or {}).get("messages") or []:
            if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
                payload = message[1] or {}
                return str(payload.get("exception_message") or payload.get("exception_type") or "the prompt failed")
        return "the prompt failed"
