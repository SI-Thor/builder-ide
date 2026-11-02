#!/usr/bin/env python3
"""Count the pieces on the board at reset and after each step.

The smoke test asserts 40 red / 40 blue pieces on the board *after* five
steps, and it failed with 39/39 on the Thor. This asks the only question
that matters: is a piece missing because the port mis-placed it, or because
it was captured during the five steps?

The board string is 100 cells, each cell followed by one movement flag
('.', has moved, or '@', has not) - `StrategoBoard::BoardString`
(src/env/stratego_board.cu:62). So the cells are the first 100 characters
and the flags are the last 100.

Piece letters, from PIECE_ENCODING (src/env/stratego_board.h:37):
  red   C=SPY D=SCOUT E=MINER F=SERGEANT G=LIEUTENANT H=CAPTAIN
        I=MAJOR J=COLONEL K=GENERAL L=MARSHAL M=FLAG B=BOMB
  blue  O=SPY P=SCOUT Q=MINER R=SERGEANT S=LIEUTENANT T=CAPTAIN
        U=MAJOR V=COLONEL W=GENERAL X=MARSHAL Y=FLAG N=BOMB
Expected counts (COUNTERS["classic"], pyengine/utils/init_helpers.py:66):
  SPY 1, SCOUT 8, MINER 5, SERGEANT 4, LIEUTENANT 4, CAPTAIN 4,
  MAJOR 3, COLONEL 2, GENERAL 1, MARSHAL 1, FLAG 1, BOMB 6  = 40 per side.

Usage: python piece_audit.py
"""

import collections
import sys

import torch

from pyengine.utils.load_pystratego import get_pystratego

pystratego = get_pystratego()

RED = set("CDEFGHIJKLMB")
BLUE = set("OPQRSTUVWXYN")
EXPECTED = {
    "C": 1, "D": 8, "E": 5, "F": 4, "G": 4, "H": 4,
    "I": 3, "J": 2, "K": 1, "L": 1, "M": 1, "B": 6,
}
EXPECTED_BLUE = {
    "O": 1, "P": 8, "Q": 5, "R": 4, "S": 4, "T": 4,
    "U": 3, "V": 2, "W": 1, "X": 1, "Y": 1, "N": 6,
}


def tally(board: str):
    cells = board[:100]
    flags = board[100:]
    red = collections.Counter(c for c in cells if c.upper() in RED)
    blue = collections.Counter(c for c in cells if c.upper() in BLUE)
    return red, blue, len(cells), flags.count(".")


def main() -> int:
    num_envs = 8
    env = pystratego.StrategoRolloutBuffer(
        256, num_envs,
        reset_behavior=pystratego.ResetBehavior.RANDOM_JB_CLASSIC_BOARD,
        move_memory=16, two_square_rule=True, quiet=2,
    )
    actions = torch.zeros(num_envs, dtype=torch.int32, device="cuda")
    env.reset()
    boards = env.board_strs(0)
    print(f"after reset: {len(boards)} boards")
    bad = 0
    for i, b in enumerate(boards):
        red, blue, ncells, nmoved = tally(b)
        rt, bt = sum(red.values()), sum(blue.values())
        ok = (rt == 40 and bt == 40 and ncells == 100)
        if not ok:
            bad += 1
        print(f"  board {i}: red={rt} blue={bt} cells={ncells} moved_flags={nmoved} "
              f"{'OK' if ok else 'MISMATCH'}")
        if not ok:
            print(f"      red  {dict(sorted(red.items()))}")
            print(f"      blue {dict(sorted(blue.items()))}")
    print(f"\nreset: {len(boards) - bad}/{len(boards)} boards at 40/40")

    # Now step and watch the counts.
    print("\nafter each step (board 0):")
    for step in range(1, 11):
        env.sample_random_legal_action(actions)
        env.apply_actions(actions)
        b = env.board_strs(step)[0]
        red, blue, ncells, nmoved = tally(b)
        print(f"  step {step:>2}: red={sum(red.values())} blue={sum(blue.values())} "
              f"moved_flags={nmoved} reward_pl0={env.reward_pl0[0].item():+.1f}")
        if sum(red.values()) != 40:
            print(f"      red  {dict(sorted(red.items()))}")
        if sum(blue.values()) != 40:
            print(f"      blue {dict(sorted(blue.items()))}")

    print("\nexpected per side:", EXPECTED)
    print("expected per side (blue):", EXPECTED_BLUE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
