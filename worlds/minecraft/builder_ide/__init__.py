"""The seam between the Minecraft world and builder-ide.

``worlds/minecraft`` is a world that runs on the Thor: four mineflayer
builders living in a Paper server, a reflex that decides, a canon that
remembers and a mediator that improves the options while the world runs.
It was its own repository; it is now a package of builder-ide, and this
package is where it meets the core.

Three things live here, and each one is a seam rather than a copy:

``ledger``
    :class:`~worlds.minecraft.builder_ide.ledger.CoreStoreLedger` — the
    world's log of record, written through builder-ide's core store, so
    the Minecraft builders' decisions are in the same log the morning
    report and the "why" door read. The rows the world wrote before the
    move are still read; :func:`read_core_store_ledger` reads the core
    store's own schema back.

``skills``
    :func:`~worlds.minecraft.builder_ide.skills.load_tiles` — the world's
    skills as builder-ide's tiles, so a skill and a capability are one
    record. The mapping is in :mod:`agent_world_reflex.tiles`, beside
    the world's own records.

``the vocabulary``
    :class:`agent_world_reflex.tiles.WorldVocabulary` — builder-ide's
    tile door, answered by the world's own closed vocabulary, so the two
    doors are one door.

The paths are the world's own: ``worlds/minecraft`` is the root, and the
world's ``reflex`` package is put on the import path from here, so the
world's modules import exactly as they did before the move.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "WORLD_ROOT",
    "world_root",
    "reflex_on_path",
    "builder_ide_root",
    "builder_ide_on_path",
]


def world_root() -> Path:
    """The world's own root — the directory that holds ``reflex`` and ``gym``."""
    return Path(__file__).resolve().parents[1]


#: The world's root, computed once.
WORLD_ROOT = world_root()


def builder_ide_root() -> Path:
    """Where builder-ide lives.

    The world used to be its own repository and reached builder-ide
    through a path that was configured per box (``~/src/builder-ide``).
    Now the world *is* inside builder-ide, so the root is found by
    walking up from this file until a directory holding ``core/`` appears
    — which is builder-ide, wherever it is checked out.

    ``AW_BUILDER_IDE`` still overrides it, for the case where the world
    runs against a builder-ide other than the one it sits in.
    """
    configured = os.environ.get("AW_BUILDER_IDE")
    if configured:
        return Path(configured).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "core" / "__init__.py").is_file():
            return parent
    return Path.home() / "src" / "builder-ide"


def reflex_on_path() -> None:
    """Put the world's ``reflex`` package on the import path.

    The world's modules import each other as ``agent_world_reflex.*``,
    which is how they were written before the move. The package sits one
    directory below the world's root, so that is what goes on the path.
    """
    path = str(WORLD_ROOT / "reflex")
    if path not in sys.path:
        sys.path.insert(0, path)


def builder_ide_on_path() -> None:
    """Put builder-ide's own packages on the import path.

    The world codes against ``core.*`` — the tiles, the judge, the store —
    so those names have to resolve. Under pytest the repository root is
    already on the path; this makes the same code work when a script is
    run from anywhere.
    """
    path = str(builder_ide_root())
    if path not in sys.path:
        sys.path.insert(0, path)


reflex_on_path()
builder_ide_on_path()

