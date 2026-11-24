#!/usr/bin/env python3
"""The state facts: one encoder, shared by both sources.

The world has one context object (``bots/src/agent.js`` ``context()``) and
the gym encodes it once, so a student cloned from the community's ledger
reads the live world the same way.

Run on the Thor, from the repo root:

    .venv/bin/python gym/tests/test_gym_facts.py

Needs nothing but numpy: no world, no server, no ledger. Takes under a
second.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))

from agent_world_gym.facts import (  # noqa: E402
    BLOCK_VOCAB,
    FACT_NAMES,
    encode_block_grid,
    encode_facts,
)

FAILS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILS
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def test_the_vector_is_the_named_facts() -> None:
    print("the fact vector")
    facts = {
        "bot": "Pebble",
        "role": "gatherer",
        "phase": "day",
        "time_of_day": 0.5,
        "health": 20,
        "food": 15,
        "has_material": True,
        "humans": 2,
        "human_present": True,
        "confidence": 0.75,
    }
    vector = encode_facts(facts)
    check("the vector is one number per named fact", vector.shape == (len(FACT_NAMES),),
          f"{vector.shape} against {len(FACT_NAMES)} names")
    check("the vector is float32", vector.dtype == np.float32, str(vector.dtype))
    at = {name: float(vector[index]) for index, name in enumerate(FACT_NAMES)}
    check("daytime reads as day", at["phase_day"] == 1.0, str(at["phase_day"]))
    check("health is on the 0..1 scale", at["health"] == 1.0, str(at["health"]))
    check("food is on the 0..1 scale", abs(at["food"] - 0.75) < 1e-6, str(at["food"]))
    check("the role is a one-hot", at["role_gatherer"] == 1.0 and at["role_builder"] == 0.0)
    check("the confidence is carried", abs(at["confidence"] - 0.75) < 1e-6, str(at["confidence"]))
    check("humans are scaled", abs(at["humans"] - 0.25) < 1e-6, str(at["humans"]))


def test_missing_confidence_is_not_zero() -> None:
    print("a missing confidence")
    at = {name: float(value) for name, value in zip(FACT_NAMES, encode_facts({"role": "scout"}))}
    check("a confidence nobody reported reads as -1", at["confidence"] == -1.0, str(at["confidence"]))
    zero = {name: float(value) for name, value in zip(FACT_NAMES, encode_facts({"role": "scout", "confidence": 0.0}))}
    check("a confidence of zero is not the same thing", zero["confidence"] == 0.0, str(zero["confidence"]))


def test_an_old_play_still_encodes() -> None:
    print("an old play from the ledger")
    at = {name: float(value) for name, value in zip(FACT_NAMES, encode_facts({"bot": "Kite", "phase": "night"}))}
    check("a play without a role still encodes", at["phase_day"] == 0.0)
    check("no field raises", at["health"] == 0.0 and at["food"] == 0.0)


def test_the_grid_vocabulary() -> None:
    print("the local block grid")
    shape = (3, 3, 3)
    names = ["air"] * 27
    names[13] = "stone"
    names[0] = "not_a_block_the_world_names"
    grid = encode_block_grid(names, shape)
    check("the grid has the shape asked for", grid.shape == shape, str(grid.shape))
    check("air is zero", grid.reshape(-1)[1] == 0)
    check("a named block is its own index", grid.reshape(-1)[13] == BLOCK_VOCAB.index("stone"))
    check("an unnamed block is unknown, never air", grid.reshape(-1)[0] == BLOCK_VOCAB.index("unknown"))
    check("unknown is not air", BLOCK_VOCAB.index("unknown") != 0)


def test_the_grid_reshape_order() -> None:
    print("the grid's order")
    # The bridge sends dy (bottom to top), then dz, then dx. The Python
    # side reshapes as (height, width, width), so the last axis is dx.
    names = list(BLOCK_VOCAB[:27])
    grid = encode_block_grid(names, (3, 3, 3))
    check("the flat list is kept in order", np.array_equal(grid.reshape(-1), np.arange(27)),
          str(grid.reshape(-1)[:5]))
    check("the last axis is dx", grid[0, 0, 0] == 0 and grid[0, 0, 2] == 2, str(grid[0, 0]))
    check("the middle axis is dz", grid[0, 1, 0] == 3 and grid[0, 2, 0] == 6, str(grid[0, :, 0]))
    check("the first axis is dy", grid[0, 0, 0] == 0 and grid[1, 0, 0] == 9 and grid[2, 0, 0] == 18)


def test_a_grid_of_the_wrong_size_is_refused() -> None:
    print("a grid that does not fit")
    try:
        encode_block_grid(["air"] * 5, (3, 3, 3))
    except ValueError:
        check("a short grid is refused, not guessed", True)
    else:
        check("a short grid is refused, not guessed", False, "no error raised")


if __name__ == "__main__":
    test_the_vector_is_the_named_facts()
    test_missing_confidence_is_not_zero()
    test_an_old_play_still_encodes()
    test_the_grid_vocabulary()
    test_the_grid_reshape_order()
    test_a_grid_of_the_wrong_size_is_refused()
    print(f"\n{'all checks passed' if FAILS == 0 else f'{FAILS} check(s) FAILED'}")
    sys.exit(1 if FAILS else 0)
