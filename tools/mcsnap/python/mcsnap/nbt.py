"""A small NBT reader — enough to read a world's ``level.dat``.

Paper writes a world's level data as **gzipped NBT**: a root compound tag
whose name is empty, holding the world's own fields. Three of them matter to
a snapshot:

* ``Time`` — the number of ticks the world has been alive. It is the
  world's clock, and it is what makes a snapshot *a moment in a world*
  rather than *a directory of bytes*;
* ``DayTime`` — the tick of the day cycle, which is what a player reads as
  *the time of day*;
* ``WorldGenSettings.seed`` (modern worlds) or ``RandomSeed`` (older ones) —
  the seed the terrain was grown from. A restore has to bring the seed back
  with it, or the world's name is a lie.

``DataVersion`` is the Minecraft data version: what the world's blocks and
entities *mean*. It is the cheapest way to say "these two worlds are not
the same kind of world".

This reader is deliberately small. It decodes the twelve tag types NBT has,
it never writes, and it never touches a file except to read it.
"""

from __future__ import annotations

import gzip
import struct
from pathlib import Path
from typing import Any

__all__ = ["read_nbt", "parse_nbt", "level_facts", "lookup", "NbtError"]


class NbtError(ValueError):
    """The bytes are not NBT this reader can read."""


TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


def _read_string(buffer: bytes, offset: int) -> tuple[str, int]:
    """A length-prefixed UTF-8 string, and the offset after it."""
    (length,) = struct.unpack_from(">H", buffer, offset)
    offset += 2
    raw = buffer[offset : offset + length]
    if len(raw) != length:
        raise NbtError("a string runs past the end of the buffer")
    return raw.decode("utf-8", errors="replace"), offset + length


def _read_payload(buffer: bytes, offset: int, tag: int) -> tuple[Any, int]:
    """One tag's payload, and the offset after it."""
    if tag == TAG_BYTE:
        return struct.unpack_from(">b", buffer, offset)[0], offset + 1
    if tag == TAG_SHORT:
        return struct.unpack_from(">h", buffer, offset)[0], offset + 2
    if tag == TAG_INT:
        return struct.unpack_from(">i", buffer, offset)[0], offset + 4
    if tag == TAG_LONG:
        return struct.unpack_from(">q", buffer, offset)[0], offset + 8
    if tag == TAG_FLOAT:
        return struct.unpack_from(">f", buffer, offset)[0], offset + 4
    if tag == TAG_DOUBLE:
        return struct.unpack_from(">d", buffer, offset)[0], offset + 8
    if tag == TAG_BYTE_ARRAY:
        (length,) = struct.unpack_from(">i", buffer, offset)
        offset += 4
        raw = buffer[offset : offset + length]
        if len(raw) != length:
            raise NbtError("a byte array runs past the end of the buffer")
        return raw, offset + length
    if tag == TAG_STRING:
        return _read_string(buffer, offset)
    if tag == TAG_LIST:
        (item_tag,) = struct.unpack_from(">b", buffer, offset)
        (length,) = struct.unpack_from(">i", buffer, offset + 1)
        offset += 5
        items: list[Any] = []
        for _ in range(length):
            value, offset = _read_payload(buffer, offset, item_tag)
            items.append(value)
        return items, offset
    if tag == TAG_COMPOUND:
        compound: dict[str, Any] = {}
        while True:
            (child_tag,) = struct.unpack_from(">b", buffer, offset)
            offset += 1
            if child_tag == TAG_END:
                return compound, offset
            name, offset = _read_string(buffer, offset)
            value, offset = _read_payload(buffer, offset, child_tag)
            compound[name] = value
    if tag == TAG_INT_ARRAY:
        (length,) = struct.unpack_from(">i", buffer, offset)
        offset += 4
        values = list(struct.unpack_from(f">{length}i", buffer, offset))
        return values, offset + 4 * length
    if tag == TAG_LONG_ARRAY:
        (length,) = struct.unpack_from(">i", buffer, offset)
        offset += 4
        values = list(struct.unpack_from(f">{length}q", buffer, offset))
        return values, offset + 8 * length
    raise NbtError(f"unknown NBT tag type {tag}")


def read_nbt(path: str | Path) -> dict[str, Any]:
    """Read an NBT file (gzipped or not) and return its root compound."""
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return parse_nbt(raw)


def parse_nbt(raw: bytes) -> dict[str, Any]:
    """Parse NBT bytes and return the root compound.

    The bytes are the ones a chunk of a region file holds: a length and a
    compression byte have already been taken off the front by the reader.
    """
    if not raw:
        raise NbtError("the NBT is empty")
    (root_tag,) = struct.unpack_from(">b", raw, 0)
    if root_tag != TAG_COMPOUND:
        raise NbtError(f"the root tag is {root_tag}, not a compound")
    offset = 1
    _, offset = _read_string(raw, offset)  # the root's own name
    value, _ = _read_payload(raw, offset, TAG_COMPOUND)
    if not isinstance(value, dict):
        raise NbtError("the root tag did not decode to a compound")
    return value


def lookup(root: dict[str, Any], *path: str, default: Any = None) -> Any:
    """A nested lookup: ``lookup(root, "WorldGenSettings", "seed")``."""
    current: Any = root
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def level_facts(root: dict[str, Any]) -> dict[str, Any]:
    """The facts a snapshot wants out of a ``level.dat``.

    Every fact is optional: a world that has never been played has no
    spawn, and an old world has no ``WorldGenSettings``. The manifest
    records what was there and nothing more.
    """
    seed = lookup(root, "WorldGenSettings", "seed")
    if seed is None:
        seed = lookup(root, "RandomSeed")
    facts: dict[str, Any] = {
        "seed": int(seed) if isinstance(seed, (int, float)) else None,
        "tick": int(lookup(root, "Time", default=0) or 0),
        "day_time": int(lookup(root, "DayTime", default=0) or 0),
        "data_version": int(lookup(root, "DataVersion", default=0) or 0),
        "last_played": int(lookup(root, "LastPlayed", default=0) or 0),
        "level_name": str(lookup(root, "LevelName", default="") or ""),
    }
    spawn = {}
    for axis in ("X", "Y", "Z"):
        value = lookup(root, f"spawn{axis}")
        if isinstance(value, (int, float)):
            spawn[axis.lower()] = int(value)
    if spawn:
        facts["spawn"] = spawn
    return facts
