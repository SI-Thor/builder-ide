"""The state facts: the world's own context, as numbers.

The gym's observation is the **reflex's context object** — the dictionary
``bots/src/agent.js`` ``context()`` builds for the d1 reflex every tick —
encoded as a fixed vector. Not more and not less. A student that learns to
read the world's facts is learning the contract the world's own bots run
on, and a student cloned from one source must read the other source the
same way, so there is exactly **one** encoder here: the live env and the
replay of the community's plays both call it.

The names below are the world's own field names, in the world's own order.
``confidence`` is the one field that can be missing: a bot that has never
been asked has no confidence to report, and ``-1.0`` is that state (a
confidence of zero is a real number and means something else).
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

__all__ = [
    "ROLES",
    "FACT_NAMES",
    "BLOCK_VOCAB",
    "encode_facts",
    "encode_block_grid",
]

#: The world's roles. The reflex asks per role, and a skill belongs to one.
ROLES: tuple[str, ...] = ("gatherer", "builder", "scout", "farmer")

#: The state facts, in order. The vector is this tuple, one number each.
FACT_NAMES: tuple[str, ...] = (
    "phase_day",
    "time_of_day",
    "health",
    "food",
    "has_material",
    "humans",
    "human_present",
    "confidence",
    "role_gatherer",
    "role_builder",
    "role_scout",
    "role_farmer",
)

#: The block names the optional local grid can name. Index 0 is air, index 1
#: is "a block this vocabulary does not name" — so a grid never lies about
#: an unknown block by calling it air.
BLOCK_VOCAB: tuple[str, ...] = (
    "air",
    "unknown",
    "stone",
    "dirt",
    "grass_block",
    "coarse_dirt",
    "podzol",
    "cobblestone",
    "oak_log",
    "spruce_log",
    "birch_log",
    "oak_leaves",
    "spruce_leaves",
    "sand",
    "gravel",
    "water",
    "bedrock",
    "crafting_table",
    "chest",
    "farmland",
    "wheat",
    "short_grass",
    "tall_grass",
    "planks",
    "torch",
    "cobblestone_stairs",
    "stone_bricks",
    "glass",
    "oak_sapling",
)

_BLOCK_INDEX = {name: index for index, name in enumerate(BLOCK_VOCAB)}
_UNKNOWN = _BLOCK_INDEX["unknown"]

#: How many humans are "the whole world's worth" for the scale. The world's
#: own context counts humans; the scale only has to stop the number growing
#: without bound, and 8 is the server's own player limit.
_HUMAN_SCALE = 8.0


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def encode_facts(facts: Mapping[str, Any]) -> np.ndarray:
    """The reflex's context as a fixed vector of ``FACT_NAMES``.

    Unknown or missing fields read as their neutral value, never as an
    exception: the world's context has grown fields over time, and an old
    play recorded in the ledger must still encode.
    """
    role = str(facts.get("role", "") or "")
    confidence = facts.get("confidence")
    try:
        time_of_day = float(facts.get("time_of_day") or 0.0)
    except (TypeError, ValueError):
        time_of_day = 0.0
    try:
        health = float(facts.get("health") or 0.0)
    except (TypeError, ValueError):
        health = 0.0
    try:
        food = float(facts.get("food") or 0.0)
    except (TypeError, ValueError):
        food = 0.0
    try:
        humans = float(facts.get("humans") or 0.0)
    except (TypeError, ValueError):
        humans = 0.0
    try:
        confidence_value = -1.0 if confidence is None else float(confidence)
    except (TypeError, ValueError):
        confidence_value = -1.0

    values = [
        1.0 if str(facts.get("phase", "")) == "day" else 0.0,
        _clip(time_of_day, 0.0, 1.0),
        _clip(health / 20.0, 0.0, 1.0),
        _clip(food / 20.0, 0.0, 1.0),
        1.0 if facts.get("has_material") else 0.0,
        _clip(humans / _HUMAN_SCALE, 0.0, 1.0),
        1.0 if facts.get("human_present") else 0.0,
        _clip(confidence_value, -1.0, 1.0),
    ]
    values.extend(1.0 if role == name else 0.0 for name in ROLES)
    return np.asarray(values, dtype=np.float32)


def encode_block_grid(names: Any, shape: tuple[int, ...]) -> np.ndarray:
    """The bridge's block names as the grid's indices.

    The bridge sends names (it is the side that can read the world); the
    vocabulary that turns a name into a number lives here, so the two
    sides cannot drift apart. A name the vocabulary does not know reads as
    ``unknown``, never as air.
    """
    flat = np.asarray(names, dtype=object).reshape(-1)
    out = np.zeros(shape, dtype=np.int32)
    expected = int(np.prod(shape)) if shape else 0
    if flat.size != expected:
        raise ValueError(
            f"the grid has {flat.size} blocks; the shape {shape} wants {expected}"
        )
    for index, name in enumerate(flat):
        out.reshape(-1)[index] = _BLOCK_INDEX.get(str(name), _UNKNOWN)
    return out
