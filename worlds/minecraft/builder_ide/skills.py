"""The world's skills as builder-ide's capabilities.

The world's library is on disk: one JSON file per skill, under
``reflex/skills/seed`` (and, at run time, under ``runtime/skills``). Each
file carries the script, its family, its role, its preconditions, its
prediction and its author — but not its id and not its version, because
the library assigns those when the skill is admitted.

This module is the loader: it reads those files through the world's own
door (so a script that reaches for a word the world does not have is
refused, exactly as it is everywhere else in the world), and hands back
:class:`core.tiles.models.Tile` records — the same records builder-ide's
tile library folds out of the log.

```python
from worlds.minecraft.builder_ide.skills import load_tiles, tile_library

tiles = load_tiles("worlds/minecraft/reflex/skills/seed")
library = tile_library(tiles)
library.require(tiles[0].id).words      # the world's vocabulary words
```

The mapping itself is in :mod:`agent_world_reflex.tiles` — it belongs
beside the world's own records, because it is a statement about what a
skill *is*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.tiles.library import TileLibrary, fold_library
from core.tiles.models import Tile

from agent_world_reflex.library import build_skill
from agent_world_reflex.models import Skill, SkillAuthor
from agent_world_reflex.tiles import WorldVocabulary, skill_to_tile

__all__ = [
    "load_skills",
    "load_tiles",
    "tile_library",
    "fold_world_library",
    "SEED_DIR",
    "SKILL_SUFFIX",
]

#: Where the starting skills live, relative to the world's own root.
SEED_DIR = Path("reflex") / "skills" / "seed"

#: The world's skill files end in ``.json``.
SKILL_SUFFIX = ".json"


def world_root() -> Path:
    """The world's own root — the directory that holds ``reflex`` and ``gym``.

    It is computed from this file's own location, so it is right wherever
    the package is checked out: inside builder-ide the world sits at
    ``worlds/minecraft``, and the same code found it at the root of its
    own repository before.
    """
    return Path(__file__).resolve().parents[1]


def load_skills(root: Path | str | None = None) -> list[Skill]:
    """The world's skills, read from disk through the world's own door.

    A file that the door refuses is **not** a skill, and it is skipped
    with its reason said out loud — the same rule the world's own
    ``seed`` command follows. The reason is returned in
    :func:`load_skills_report` for the callers that want it.
    """
    return [skill for skill, _reason in load_skills_report(root)]


def load_skills_report(root: Path | str | None = None) -> list[tuple[Skill, str]]:
    """The skills and, for each file, the reason it was refused (or ``""``)."""
    directory = Path(root) if root is not None else world_root() / SEED_DIR
    if not directory.is_dir():
        return []
    out: list[tuple[Skill, str]] = []
    for path in sorted(directory.glob(f"*{SKILL_SUFFIX}")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append((None, f"{path.name}: unreadable ({exc})"))  # type: ignore[arg-type]
            continue
        try:
            skill = _skill_from_raw(raw)
        except Exception as exc:
            reason = getattr(exc, "reason", type(exc).__name__)
            out.append((None, f"{path.name}: {reason} ({getattr(exc, 'detail', exc)})"))  # type: ignore[arg-type]
            continue
        out.append((skill, ""))
    return out


def _skill_from_raw(raw: dict[str, Any]) -> Skill:
    """Build a skill from one of the world's JSON files.

    The file carries no id and no version: the library assigns them when
    the skill is admitted, and the id is the hash of the body — so the
    skill is built through :func:`build_skill`, which is the world's only
    way in and holds the script to the door.
    """
    author = SkillAuthor(**(raw.get("author") or {}))
    return build_skill(
        family=raw["family"],
        role=raw["role"],
        title=raw["title"],
        body=raw["body"],
        author=author,
        kind=raw.get("kind", "behaviour"),
        preconditions=raw.get("preconditions", []),
        predict=raw.get("predict", {"kind": "none"}),
        provenance=raw.get("provenance", {}),
    )


def load_tiles(root: Path | str | None = None) -> list[Tile]:
    """The world's skills as builder-ide's tiles."""
    return [skill_to_tile(skill) for skill in load_skills(root)]


def tile_library(
    tiles: Iterable[Tile] = (),
    *,
    ledger: Any | None = None,
    registry: Any | None = None,
) -> TileLibrary:
    """A builder-ide tile library holding the world's tiles.

    The registry is the world's own vocabulary
    (:class:`agent_world_reflex.tiles.WorldVocabulary`), so the tile
    door is the world's door: a tile that names a word the world does
    not have is refused, not repaired.
    """
    return TileLibrary(
        registry=registry if registry is not None else WorldVocabulary(),
        ledger=ledger,
        tiles=tiles,
    )


def fold_world_library(events: Sequence[Any]) -> TileLibrary:
    """The world's tiles, folded back out of a log.

    This is the round trip that says the world's skills and builder-ide's
    capabilities are one record: the rows the world writes are read by
    builder-ide's own fold, and the library that comes back holds the
    same tiles.
    """
    return fold_library(events, registry=WorldVocabulary())
