"""What the night produced, and where it put it.

The executor writes into the store; the critic reads out of it. The two
never talk to each other directly, which keeps the seam the core already
has — the runner asks the executor to do the work and then asks the critic
to judge it — and it means the critic can be tested against a store that
was filled in by hand.
"""

from __future__ import annotations

from core.models import Asset

from core.genbatch.models import ImageResult, LaneSplit
from core.genbatch.mesh import MeshReport

__all__ = ["PropStore"]


class PropStore:
    """The night's output: one entry per attempt."""

    def __init__(self) -> None:
        self._meshes: dict[tuple[str, str], MeshReport] = {}
        self._assets: dict[tuple[str, str], Asset] = {}
        self._splits: dict[tuple[str, str], LaneSplit] = {}
        self._seconds: dict[tuple[str, str], float] = {}
        self._images: dict[str, dict[int, ImageResult]] = {}

    # -- the meshes --------------------------------------------------------

    def record_mesh(
        self,
        task_id: str,
        variant_id: str,
        report: MeshReport,
        *,
        asset: Asset | None = None,
        split: LaneSplit | None = None,
        seconds: float = 0.0,
    ) -> None:
        """Record what one attempt produced."""
        key = (task_id, variant_id)
        self._meshes[key] = report
        if asset is not None:
            self._assets[key] = asset
        if split is not None:
            self._splits[key] = split
        self._seconds[key] = seconds

    def mesh(self, task_id: str, variant_id: str) -> MeshReport | None:
        return self._meshes.get((task_id, variant_id))

    def asset(self, task_id: str, variant_id: str) -> Asset | None:
        return self._assets.get((task_id, variant_id))

    def split(self, task_id: str, variant_id: str) -> LaneSplit | None:
        return self._splits.get((task_id, variant_id))

    def seconds(self, task_id: str, variant_id: str) -> float:
        return self._seconds.get((task_id, variant_id), 0.0)

    def attempts(self, task_id: str) -> list[str]:
        """The variant ids recorded for a task, in the order they arrived."""
        return [key[1] for key in self._meshes if key[0] == task_id]

    # -- the images --------------------------------------------------------

    def record_images(self, request_id: str, images: list[ImageResult]) -> None:
        """Record the image stage's output for a request."""
        held = self._images.setdefault(request_id, {})
        for image in images:
            held[image.seed] = image

    def image(self, request_id: str, seed: int) -> ImageResult | None:
        return self._images.get(request_id, {}).get(seed)

    def images(self, request_id: str) -> list[ImageResult]:
        return list(self._images.get(request_id, {}).values())
