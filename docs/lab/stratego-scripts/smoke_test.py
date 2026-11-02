#!/usr/bin/env python3
"""Smoke test for the ported stratego extension on the Thor.

Checks the things a port can break that a compile cannot: that the module
loads, that the constants are the expected ones, that a batch of games can be
created, stepped and observed on the GPU, and that the board is a *legal*
Stratego position.

On the piece count, and why it is checked at reset and not after the steps:

The board string is 100 cells, each cell followed by a one-character movement
flag ('.', has moved, or '@', has not) - `StrategoBoard::BoardString`
(src/env/stratego_board.cu:62). So the string is 200 characters and the
cells are the *even* indices.

The piece letters and the expected classic composition come from
PIECE_ENCODING (src/env/stratego_board.h:37) and COUNTERS["classic"]
(pyengine/utils/init_helpers.py:66):

    SPY 1, SCOUT 8, MINER 5, SERGEANT 4, LIEUTENANT 4, CAPTAIN 4,
    MAJOR 3, COLONEL 2, GENERAL 1, MARSHAL 1, FLAG 1, BOMB 6   = 40 per side

    red   C=SPY D=SCOUT E=MINER F=SERGEANT G=LIEUTENANT H=CAPTAIN
          I=MAJOR J=COLONEL K=GENERAL L=MARSHAL M=FLAG B=BOMB
    blue  O=SPY P=SCOUT Q=MINER R=SERGEANT S=LIEUTENANT T=CAPTAIN
          U=MAJOR V=COLONEL W=GENERAL X=MARSHAL Y=FLAG N=BOMB

A previous version of this test asserted 40 red / 40 blue *after five random
steps*. That is flaky: a step can capture a piece, and the piece leaves the
board (it goes to the side's reserve). On the Thor the first run of the
flaky version failed with 39/39 because one red and one blue scout had been
captured in those five steps; a later run passed because nothing was
captured. So the count is now checked where it is deterministic - at reset,
where both sides must have exactly the classic 40 - and after the steps the
test asserts the *upper* bound instead: no side may hold more pieces than it
started with, and no piece type may appear that was not in the initial
composition.

Usage (from the stratego checkout, with its .venv on PATH):
    python smoke_test.py
"""

import collections
import sys

import torch

from pyengine.utils.load_pystratego import get_pystratego

FAIL = []

# Piece letters per colour (stratego_board.h:37, PIECE_ENCODING). Case encodes
# visibility, not colour.
RED_PIECES = set("CDEFGHIJKLMB")
BLUE_PIECES = set("OPQRSTUVWXYN")

# COUNTERS["classic"], pyengine/utils/init_helpers.py:66
EXPECTED_RED = {"C": 1, "D": 8, "E": 5, "F": 4, "G": 4, "H": 4,
                "I": 3, "J": 2, "K": 1, "L": 1, "M": 1, "B": 6}
EXPECTED_BLUE = {"O": 1, "P": 8, "Q": 5, "R": 4, "S": 4, "T": 4,
                 "U": 3, "V": 2, "W": 1, "X": 1, "Y": 1, "N": 6}


def check(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAIL.append(name)


def pieces_on(board: str, side: set) -> collections.Counter:
    """Count the pieces of one side on a board string.

    The string is 100 cells each followed by a movement flag, so the cells are
    the even indices. Counting over the whole string would be equivalent
    (flags are only '@' and '.'), but taking the cells explicitly is what
    makes the count readable.
    """
    cells = board[0::2]
    return collections.Counter(c.upper() for c in cells if c.upper() in side)


def main() -> int:
    ps = get_pystratego()
    print(f"module: {ps.__file__}", flush=True)

    check("NUM_ACTIONS", ps.NUM_ACTIONS, 1800)
    check("NUM_BOARD_STATE_CHANNELS", ps.NUM_BOARD_STATE_CHANNELS, 355)
    check("NUM_PIECE_TYPES", ps.NUM_PIECE_TYPES, 14)

    num_envs = 8
    # The continuous chasing rule needs at least 210 rows of history
    # (stratego.cu: "The buffer size is too small to support the continuous
    # chasing rule").
    env = ps.StrategoRolloutBuffer(
        256,
        num_envs,
        reset_behavior=ps.ResetBehavior.RANDOM_JB_CLASSIC_BOARD,
        move_memory=16,
        two_square_rule=True,
        quiet=2,
    )
    print("ctor ok", flush=True)

    actions = torch.zeros(num_envs, dtype=torch.int32, device="cuda")
    env.reset()
    print("reset ok", flush=True)

    # --- the board at reset: both sides exactly the classic 40 -------------
    boards = env.board_strs(0)
    for i, b in enumerate(boards):
        red = pieces_on(b, RED_PIECES)
        blue = pieces_on(b, BLUE_PIECES)
        if dict(sorted(red.items())) != dict(sorted(EXPECTED_RED.items())):
            FAIL.append(f"board {i} red composition")
            print(f"FAIL board {i} red composition: {dict(sorted(red.items()))}")
        if dict(sorted(blue.items())) != dict(sorted(EXPECTED_BLUE.items())):
            FAIL.append(f"board {i} blue composition")
            print(f"FAIL board {i} blue composition: {dict(sorted(blue.items()))}")
    print(f"ok   reset composition: {len(boards)}/{len(boards)} boards at the "
          f"classic 40 per side")

    for _ in range(5):
        env.sample_random_legal_action(actions)
        env.apply_actions(actions)
    print("5 steps ok", flush=True)

    env.compute_infostate_tensor(4)
    # The mask is computed on request; it is not filled in by a step.
    env.compute_legal_action_mask(4)
    check("infostate shape[0]", env.infostate_tensor.shape[0], num_envs)
    check("infostate is cuda", env.infostate_tensor.is_cuda, True)
    check("infostate dtype float32", env.infostate_tensor.dtype, torch.float32)
    check("mask shape", tuple(env.legal_action_mask.shape), (num_envs, 1800))

    legal = env.legal_action_mask.sum(1).tolist()
    print(f"legal actions per game: {legal}")
    if not all(n > 0 for n in legal):
        FAIL.append("every game has a legal action")

    # --- after the steps: pieces may be captured, but never created -------
    board = env.board_strs(4)[0]
    print(f"board:\n{board}")
    red = pieces_on(board, RED_PIECES)
    blue = pieces_on(board, BLUE_PIECES)
    print(f"red pieces {sum(red.values())}, blue pieces {sum(blue.values())}")
    for label, got, allowed in (("red", red, EXPECTED_RED), ("blue", blue, EXPECTED_BLUE)):
        for piece, n in got.items():
            if n > allowed[piece]:
                FAIL.append(f"{label} has {n} of {piece}, more than the initial {allowed[piece]}")
        for piece, n in allowed.items():
            if got[piece] > n:
                FAIL.append(f"{label} piece {piece} grew past its initial count")
    print("ok   no side gained a piece during the five steps"
          if not any("more than the initial" in f or "grew past" in f for f in FAIL)
          else "FAIL piece count grew")

    print("reward_pl0:", env.reward_pl0.tolist())
    print("SMOKE_OK" if not FAIL else f"SMOKE_FAILED: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
