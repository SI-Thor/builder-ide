"""What a snapshot copies, and what it leaves behind.

A Paper world directory is **not** just the region files. The design note
counts four overworld region files and 20 MB, and that is the part a rewind
needs; but a world restored without the rest is not the world that was
snapshotted. So the tool copies all of what Paper writes, and it is explicit
about every file it leaves behind.

The tree, as the live world's own directory shows it:

============================  ==========================================
``level.dat``                the world's own data: time, seed, spawn
``dimensions/<ns>/<dim>/``   one tree per dimension:
``  region/r.*.mca``         the blocks
``  entities/r.*.mca``       the entities (mobs, item drops, boats)
``  poi/r.*.mca``            the points of interest (villagers, beds)
``  data/``                  the dimension's own data (maps, raids)
``data/``                    the world's own data: the scoreboard, the
                             stopwatches, the boss events, the random
                             sequences
``datapacks/``               the datapacks the server ships
``players/``                 the players' own data: their NBT, their
                             advancements, their statistics
``paper-world.yml``          the dimension's Paper settings
============================  ==========================================

Two things are **not** copied:

* ``session.lock`` — the server's own lock on the world while it runs. It
  holds the server's pid, so a restored copy of it would be a lie.
* ``level.dat_old`` — the *previous* ``level.dat``, written by the server
  on each save: a backup of a moment that is already gone.

Everything the tool does not recognise is **copied anyway** and listed in
the manifest under ``unclassified``, so a Paper version that keeps state
somewhere new shows up in the manifest instead of being silently dropped.
That list is the brief's "list what you find": the plugin and server state
that Paper keeps outside the region files.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FilePlan",
    "classify",
    "plan_tree",
    "copy_tree",
    "SECTION_LABELS",
]


@dataclass(frozen=True)
class FilePlan:
    """One file of the world, and what the tool will do with it."""

    relpath: str
    size: int
    section: str
    include: bool
    reason: str = ""


#: A human label for each section, for the report and the README.
SECTION_LABELS = {
    "level": "the world's own data (level.dat)",
    "region": "the blocks, as region files",
    "entities": "the entities, as region files",
    "poi": "the points of interest, as region files",
    "dimension-data": "each dimension's own data",
    "world-data": "the world's data: scoreboard, stopwatches, boss events",
    "datapacks": "the datapacks the server ships",
    "players": "the players' data, advancements and statistics",
    "config": "the dimension's Paper settings",
    "unclassified": "a file this tool did not recognise — copied, and listed",
    "skipped": "left behind on purpose",
}


def classify(relpath: str) -> tuple[str, bool, str]:
    """The section a world-relative path belongs to, and whether to copy it.

    Returns ``(section, include, reason)``. The reason is only set for the
    files that are *not* copied — a skipped file says why it was skipped,
    so the manifest is the list of what the operator should know about.
    """
    parts = relpath.split("/")
    name = parts[-1]

    if name == "session.lock":
        return "skipped", False, "the server's own lock on the world while it runs"
    if name == "level.dat_old":
        return "skipped", False, "the previous level.dat, already superseded"
    if relpath.startswith("logs/"):
        return "skipped", False, "the server's logs, not world state"
    if name.endswith(".lock"):
        return "skipped", False, "a lock file"

    if relpath == "level.dat":
        return "level", True, ""
    if relpath.startswith("datapacks/"):
        return "datapacks", True, ""
    if relpath.startswith("data/"):
        return "world-data", True, ""
    if relpath.startswith("players/"):
        return "players", True, ""
    if relpath.startswith("dimensions/"):
        # dimensions/<namespace>/<dimension>/<what>/...
        if len(parts) >= 4:
            leaf = parts[3]
            if leaf == "region":
                return "region", True, ""
            if leaf == "entities":
                return "entities", True, ""
            if leaf == "poi":
                return "poi", True, ""
            if leaf == "data":
                return "dimension-data", True, ""
            if name.endswith(".yml"):
                return "config", True, ""
    if name.endswith(".yml"):
        return "config", True, ""

    return "unclassified", True, ""


def plan_tree(world_dir: str | Path) -> list[FilePlan]:
    """Every file under the world directory, with its section and decision."""
    root = Path(world_dir)
    plans: list[FilePlan] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = Path(dirpath) / filename
            relpath = absolute.relative_to(root).as_posix()
            section, include, reason = classify(relpath)
            try:
                size = absolute.stat().st_size
            except OSError:
                size = 0
            plans.append(
                FilePlan(
                    relpath=relpath,
                    size=size,
                    section=section,
                    include=include,
                    reason=reason,
                )
            )
    return plans


def copy_tree(
    world_dir: str | Path,
    destination: str | Path,
    *,
    plans: list[FilePlan] | None = None,
) -> tuple[int, int]:
    """Copy the world's files into ``destination``; return ``(files, bytes)``.

    Only the files the plan includes are copied. The copy is a plain file
    copy — not a hard link — because a hard link would let the restored
    world's writes reach back into the snapshot and change it.
    """
    source = Path(world_dir)
    target = Path(destination)
    if plans is None:
        plans = plan_tree(source)
    files = 0
    total = 0
    for plan in plans:
        if not plan.include:
            continue
        absolute = source / plan.relpath
        if not absolute.is_file():
            continue
        out = target / plan.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(absolute, out)
        files += 1
        total += out.stat().st_size
    return files, total
