"""The asset: what was made, where it came from, and what licence it carries.

The core's :class:`core.models.Asset` is the record the world keeps. A
generated prop is recorded like any other asset — with its file, its
provenance and its licence row — so a prop made in a night can be found
later, replayed, or shipped without anyone having to remember how it was
made.

The provenance is the whole recipe: the prompt, the model, the weights'
revision, the seed, the resolution and the knobs. The GLB itself carries its
own recipe too (``asset.extras.prompt``), but the asset record is what the
core indexes, so the recipe is written here as well.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.models import Asset, FileRef, Licence, Provenance

from core.genbatch.models import PropRequest

__all__ = ["build_asset", "file_ref"]


def file_ref(role: str, path: str | Path) -> FileRef:
    """A reference to a file, with its size and its digest."""
    path = Path(path)
    data = path.read_bytes()
    return FileRef(
        role=role,
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
    )


def build_asset(
    *,
    request: PropRequest,
    variant_id: str,
    glb_path: str | Path,
    generator: dict[str, Any],
    licence: Licence,
    source_image: str | Path | None = None,
    critic: dict[str, Any] | None = None,
) -> Asset:
    """Record a generated prop as an asset.

    ``generator`` is the recipe — the prompt, the model, the weights'
    revision, the seed, the resolution. It is copied into the provenance
    as given, so the caller decides what the recipe says.
    """
    files = [file_ref("glb", glb_path)]
    if source_image is not None:
        files.append(file_ref("source_image", source_image))
    return Asset(
        id=f"asset_{variant_id}",
        kind="mesh",
        files=files,
        provenance=Provenance(source="generated", generator=dict(generator)),
        licence=licence,
        critic=critic,
    )
