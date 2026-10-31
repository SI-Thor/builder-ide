"""Reading the little that has to be read about an image.

The image stage's output has to be uploaded into ComfyUI before the mesh
stage can load it, and the upload's answer is the name the workflow uses.
Checking that the picture is the size it was asked to be is worth doing:
an image that came back at the wrong size is a picture the mesh stage would
silently mis-condition on.
"""

from __future__ import annotations

import struct
from pathlib import Path

__all__ = ["ImageError", "png_dimensions"]

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ImageError(ValueError):
    """An image we cannot read."""


def png_dimensions(path: str | Path) -> tuple[int, int]:
    """The width and height of a PNG, read from its header."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise ImageError(f"{path}: cannot be read ({exc})") from exc
    if len(header) < 24 or header[:8] != _PNG_MAGIC:
        raise ImageError(f"{path}: not a PNG")
    if header[12:16] != b"IHDR":
        raise ImageError(f"{path}: the PNG has no header chunk")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)
