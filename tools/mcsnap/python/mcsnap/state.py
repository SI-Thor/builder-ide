"""What a world's state actually holds — read out of the files.

A restore's question is "what came back, and what did not?". That is only
answerable by *looking* at the world, not by trusting the manifest: the
manifest says the files are the ones that were copied, and the server then
does what a server does — it runs, and it writes.

Three things are read here:

* the world's own clock (``level.dat``: the tick, the time of day, the
  seed);
* the **entities** — how many there are, read out of the ``entities``
  region files. A region file is a sparse array of 4 KB sectors; each
  chunk it holds is a length, a compression byte and an NBT compound with
  the chunk's ``Entities`` list in it;
* the **players** — each player's position, dimension, health and
  inventory, read out of the player NBT files.

The comparison that matters is the one a restore makes: the same three
things, before and after, side by side.
"""

from __future__ import annotations

import gzip
import struct
import zlib
from pathlib import Path
from typing import Any

from .nbt import level_facts, parse_nbt, read_nbt

__all__ = ["world_state", "level_state", "entity_counts", "player_states"]


#: The compression types a region file may use. 4 is LZ4, which this
#: reader does not do; a chunk in that form is counted as unread.
_COMPRESSION = {1: "gzip", 2: "zlib", 3: "none"}


def _read_chunk(data: bytes, offset: int) -> dict[str, Any] | None:
    """One chunk of a region file, as its NBT compound."""
    if offset <= 0 or offset + 5 > len(data):
        return None
    (length,) = struct.unpack_from(">i", data, offset)
    compression = data[offset + 4]
    payload = data[offset + 5 : offset + 4 + length]
    try:
        if compression == 1:
            payload = gzip.decompress(payload)
        elif compression == 2:
            payload = zlib.decompress(payload)
        elif compression != 3:
            return None
    except (OSError, zlib.error):
        return None
    try:
        return parse_nbt(payload)
    except Exception:
        return None


def _region_chunks(path: Path) -> list[dict[str, Any]]:
    """Every chunk of a region file, read out."""
    data = path.read_bytes()
    if len(data) < 8196:
        return []
    chunks: list[dict[str, Any]] = []
    for index in range(1024):
        (offset,) = struct.unpack_from(">i", data, index * 4)
        if offset == 0:
            continue
        chunk = _read_chunk(data, offset)
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def level_state(world_dir: str | Path) -> dict[str, Any]:
    """The world's own clock: the tick, the time of day, the seed."""
    level = Path(world_dir) / "level.dat"
    if not level.is_file():
        return {}
    try:
        # level.dat is gzipped NBT: read_nbt knows that, parse_nbt does not.
        return level_facts(read_nbt(level))
    except Exception:
        return {}


def entity_counts(world_dir: str | Path) -> dict[str, int]:
    """How many entities each dimension holds.

    The count is the number of entities in the region files' chunks. It is
    the world's *saved* entities: a mob that is standing somewhere right
    now, and has not been written to disk yet, is not in here.
    """
    root = Path(world_dir) / "dimensions"
    counts: dict[str, int] = {}
    if not root.is_dir():
        return counts
    for entities_dir in sorted(root.glob("*/*/entities")):
        total = 0
        for region in sorted(entities_dir.glob("r.*.mca")):
            for chunk in _region_chunks(region):
                entities = chunk.get("Entities")
                if isinstance(entities, list):
                    total += len(entities)
        key = "/".join(entities_dir.parts[-3:-1])
        counts[key] = total
    return counts


def player_states(world_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Every player's own data: where it is, and what it holds.

    The key is the player's UUID, which in **offline mode** is derived
    from the player's name — so a bot that reconnects after a restore is
    the same player file, and its inventory comes back with the world.
    """
    root = Path(world_dir) / "players" / "data"
    players: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return players
    for path in sorted(root.glob("*.dat")):
        try:
            data = read_nbt(path)
        except Exception:
            continue
        inventory = data.get("Inventory")
        items: list[dict[str, Any]] = []
        if isinstance(inventory, list):
            for entry in inventory:
                if not isinstance(entry, dict):
                    continue
                items.append(
                    {
                        "slot": entry.get("Slot"),
                        "id": entry.get("id"),
                        "count": entry.get("Count"),
                    }
                )
        players[path.stem] = {
            "position": data.get("Pos"),
            "dimension": data.get("Dimension"),
            "health": data.get("Health"),
            "food": data.get("foodLevel"),
            "inventory": items,
            "inventory_size": sum(int(item.get("count") or 0) for item in items),
        }
    return players


def world_state(world_dir: str | Path) -> dict[str, Any]:
    """Everything a restore can be asked about, in one read."""
    return {
        "level": level_state(world_dir),
        "entities": entity_counts(world_dir),
        "players": player_states(world_dir),
    }
