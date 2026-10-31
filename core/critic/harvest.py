"""The harvest: the sweep's real renders, found without touching them.

The overnight sweep (``thor/seed-sweep.sh`` in the infinigen-thor tree)
renders Infinigen nature scenes on the Thor and keeps the frames under
``outputs/sweep/<scene>-s<seed>/frames/``. Those frames are this seat's
reference material: the calibration set is built from **real renders**, not
from stand-ins, so the scripted checks are measured against the images the
critic will really be handed.

The sweep belongs to another night's work, so the harvest is strictly
read-only: it lists directories, reads the PNG's bytes to hash them, and
writes nothing inside the sweep. (The mesh probe in :mod:`core.critic.mesh`
is the one thing that needs the scene's ``scene.blend``, and the sweep
deletes those when a scene finishes — see that module for the window.)

What a base is:

    <sweep>/<scene>-s<seed>/frames/Image/camera_0/Image_0_0_0001_0.png

What the harvest returns is a tuple of :class:`~core.critic.models.BaseRender`
sorted by ``(scene, seed)`` — so the reference set is built in a stable
order and the same sweep always yields the same members.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.canon import sha256_hex

from .models import BaseRender

__all__ = [
    "DEFAULT_SWEEP_ROOT",
    "FRAME_GLOB",
    "harvest",
    "base_id",
    "parse_base_id",
    "png_size",
    "sha256_file",
]

#: Where the sweep writes, on the Thor. Overridable — the harvest takes a
#: root, so a test (or another box) can point it anywhere.
DEFAULT_SWEEP_ROOT = Path.home() / "src" / "infinigen-thor" / "outputs" / "sweep"

#: The rendered frame of one camera, inside one scene's ``frames/`` folder.
FRAME_GLOB = "frames/Image/camera_0/*.png"

_SCENE_DIR = re.compile(r"^(?P<scene>.+)-s(?P<seed>\d+)$")


def base_id(scene: str, seed: int) -> str:
    """The sweep's name for a scene: ``desert-s4``."""
    return f"{scene}-s{seed}"


def sha256_file(path: str | Path) -> str:
    """The sha256 of a file's bytes, read in chunks (the frames are ~1 MB)."""
    import hashlib

    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def png_size(path: str | Path) -> tuple[int, int]:
    """A PNG's ``(width, height)`` read from its header.

    The harvest stays dependency-free on purpose: it must be able to run on a
    box with no numpy and no Pillow, because it is the one piece that talks
    to the sweep.
    """
    with open(path, "rb") as fh:
        header = fh.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return width, height


def parse_base_id(name: str) -> tuple[str, int] | None:
    """``"desert-s4"`` → ``("desert", 4)``; ``None`` when the name is not one."""
    match = _SCENE_DIR.match(name)
    if not match:
        return None
    return match.group("scene"), int(match.group("seed"))


def harvest(
    sweep_root: str | Path | None = None,
    *,
    require_done: bool = False,
) -> tuple[BaseRender, ...]:
    """The sweep's finished renders, read-only.

    ``require_done=True`` keeps only the scenes the sweep has marked
    finished; the default keeps every scene that has produced a frame,
    because a scene still in flight has already rendered — and is the only
    chance a mesh-level member has.
    """
    root = Path(sweep_root) if sweep_root is not None else DEFAULT_SWEEP_ROOT
    if not root.is_dir():
        return ()

    bases: list[BaseRender] = []
    for scene_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        parsed = parse_base_id(scene_dir.name)
        if parsed is None:
            continue
        scene, seed = parsed
        frames = sorted(scene_dir.glob(FRAME_GLOB))
        if not frames:
            continue
        done = (scene_dir / "DONE").exists()
        if require_done and not done:
            continue
        frame = frames[0]
        mesh = _live_mesh(scene_dir)
        width, height = png_size(frame)
        bases.append(
            BaseRender(
                id=scene_dir.name,
                scene=scene,
                seed=seed,
                image_path=str(frame),
                image_sha256=sha256_file(frame),
                width=width,
                height=height,
                mesh_path=str(mesh) if mesh is not None else None,
                mesh_sha256=sha256_file(mesh) if mesh is not None else None,
                done=done,
            )
        )
    return tuple(bases)


def _live_mesh(scene_dir: Path) -> Path | None:
    """The scene's ``scene.blend`` if the sweep has not deleted it yet.

    The fine stage's blend is the render-ready one (it carries the assets);
    the coarse stage's is the pre-populate scene. The sweep deletes both
    when the scene finishes, so this is a window, not a store.
    """
    for candidate in (scene_dir / "fine" / "scene.blend", scene_dir / "coarse" / "scene.blend"):
        if candidate.is_file():
            return candidate
    return None
