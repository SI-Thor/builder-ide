#!/usr/bin/env python3
"""Smoke test for the ported stratego extension on the Thor.

Checks the things a port can break that a compile cannot: that the module
loads, that the constants are the expected ones, that a batch of games can be
created, stepped and observed on the GPU, and that the observation planes are
the shape the policy expects.

Usage (from the stratego checkout, with its .venv on PATH):
    python smoke_test.py
"""

import sys

import torch

from pyengine.utils.load_pystratego import get_pystratego

FAIL = []

# Piece letters per colour (stratego_board.h, PIECE_ENCODING). Case encodes
# visibility, not colour.
RED_PIECES = set("CDEFGHIJKLMB")
BLUE_PIECES = set("OPQRSTUVWXYN")


def check(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAIL.append(name)


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

    # The board must be a legal Stratego position: 40 pieces per side.
    # Case is *visibility*, not colour (stratego.h, "BoardStrs"): the letter
    # gives the colour (C..M, B = red; O..Y, N = blue), the case says whether
    # the piece is visible. 'a' is empty, '_' is a lake.
    board = env.board_strs(4)[0]
    print(f"board:\n{board}")
    red = sum(1 for ch in board if ch.upper() in RED_PIECES)
    blue = sum(1 for ch in board if ch.upper() in BLUE_PIECES)
    print(f"red pieces {red}, blue pieces {blue}")
    if red != 40 or blue != 40:
        FAIL.append(f"board has {red} red / {blue} blue pieces (want 40/40)")

    print("reward_pl0:", env.reward_pl0.tolist())
    print("SMOKE_OK" if not FAIL else f"SMOKE_FAILED: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
