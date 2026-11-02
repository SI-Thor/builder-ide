"""A fake world, for the tests that must not need a server.

The tests build a world directory that looks like Paper's — the same
paths, the same section names — with small files in it. Nothing here
starts a server: the snapshot's own machinery (the copy, the hashing, the
manifest, the restore) is what is under test.
"""

from __future__ import annotations

import gzip
import struct
from pathlib import Path

import pytest


def _tag(out: bytearray, name: str, tag: int, value: object) -> None:
    """One named tag."""
    out.append(tag)
    encoded = name.encode("utf-8")
    out += struct.pack(">H", len(encoded)) + encoded
    if tag == 1:
        out += struct.pack(">b", int(value))
    elif tag == 3:
        out += struct.pack(">i", int(value))
    elif tag == 4:
        out += struct.pack(">q", int(value))
    elif tag == 8:
        text = str(value).encode("utf-8")
        out += struct.pack(">H", len(text)) + text
    elif tag == 10:
        for sub_name, sub_tag, sub_value in value:  # type: ignore[union-attr]
            _tag(out, sub_name, sub_tag, sub_value)
        out.append(0)
    else:
        raise ValueError(f"the test writer does not write tag {tag}")


def encode_nbt(pairs: list[tuple[str, int, object]]) -> bytes:
    """A gzipped NBT compound: ``[(name, tag type, value), ...]``."""
    out = bytearray()
    out.append(10)                      # TAG_Compound
    out += struct.pack(">H", 0)         # the root's name is empty
    for name, tag, value in pairs:
        _tag(out, name, tag, value)
    out.append(0)                      # TAG_End
    return gzip.compress(bytes(out))


def write_level_dat(
    path: Path, *, seed: int = 4242, tick: int = 1000, day_time: int = 6000
) -> None:
    """A ``level.dat`` with the fields a snapshot reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        encode_nbt(
            [
                ("DataVersion", 3, 3955),
                ("Time", 4, tick),
                ("DayTime", 4, day_time),
                ("LevelName", 8, "world"),
                (
                    "WorldGenSettings",
                    10,
                    [("seed", 4, seed), ("generate_features", 1, 0)],
                ),
            ]
        )
    )


@pytest.fixture
def fake_world(tmp_path: Path) -> Path:
    """A small world directory with one of everything."""
    world = tmp_path / "world"
    write_level_dat(world / "level.dat")
    (world / "level.dat_old").write_bytes(b"old")
    (world / "session.lock").write_text("1")
    overworld = world / "dimensions" / "minecraft" / "overworld"
    (overworld / "region").mkdir(parents=True)
    (overworld / "region" / "r.0.0.mca").write_bytes(b"region-blocks" * 100)
    (overworld / "entities").mkdir(parents=True)
    (overworld / "entities" / "r.0.0.mca").write_bytes(b"entities" * 100)
    (overworld / "poi").mkdir(parents=True)
    (overworld / "poi" / "r.0.0.mca").write_bytes(b"poi" * 50)
    (overworld / "data").mkdir(parents=True)
    (overworld / "data" / "raids.dat").write_bytes(b"raids")
    (overworld / "paper-world.yml").write_text("keep-inventory: false\n")
    (world / "data" / "minecraft").mkdir(parents=True)
    (world / "data" / "minecraft" / "scoreboard.dat").write_bytes(b"scoreboard")
    (world / "data" / "minecraft" / "world_clocks.dat").write_bytes(b"clocks")
    (world / "datapacks" / "bukkit").mkdir(parents=True)
    (world / "datapacks" / "bukkit" / "pack.mcmeta").write_text("{}")
    (world / "players" / "data").mkdir(parents=True)
    (world / "players" / "data" / "player.dat").write_bytes(b"player")
    (world / "players" / "advancements").mkdir(parents=True)
    (world / "players" / "advancements" / "player.json").write_text("{}")
    (world / "players" / "stats").mkdir(parents=True)
    (world / "players" / "stats" / "player.json").write_text("{}")
    return world
