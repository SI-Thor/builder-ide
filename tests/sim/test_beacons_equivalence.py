"""The equality gate: the GPU, the CPU and the Python reference agree.

The claim under test is the one the design makes
(`docs/design/batched-sim.md` §6): the CUDA implementation is checked against
the Python one **bit for bit** before anything depends on it.

So this test runs the *same seed* and the *same action sequence* through

  - the Python reference (`core/sim/systems/beacons/reference.py`),
  - the CPU backend (the same `rules.cuh`, compiled by g++),
  - the CUDA backend (the same `rules.cuh`, compiled by nvcc),

and compares the **canonical byte encoding** of every state after every
step. The encoding is little-endian and fixed-width, so "the states agree"
means the bytes agree, not "they are close".

The world bytes are compared too, so the generator is covered: the Python
reference grows its own world from the seed, and it has to match the host
generator byte for byte.

The CUDA half runs in a subprocess with a timeout: on this box a CUDA
allocation that does not fit the GPU pool **blocks in the kernel** rather
than failing, and a test that hangs is worse than a test that skips.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.sim import make_batch  # noqa: E402
from core.sim.systems.beacons import reference as ref  # noqa: E402
from core.sim.systems.beacons.reference import Params, Round  # noqa: E402

DEVICES = ["cpu"]

_CUDA_CHECKED = False
_CUDA_OK = False


# The GPU pool's largest free block has to be at least this big before the
# CUDA half of the gate is attempted.
#
# On the Thor, a CUDA allocation that does not fit the pool **blocks in the
# kernel rather than failing**, and the process ends up in uninterruptible
# sleep -- where a timeout cannot save it. So the room is checked *before*
# the CUDA call, and the CUDA half is skipped rather than attempted.
# The threshold is low on purpose. The simulator allocates with cudaMalloc,
# and the thing that wedged on this box was a *managed* allocation
# (cudaMallocManaged) in a throwaway smoke program: with 184 MB of free
# block the managed allocation blocked in the kernel, while the simulator's
# own allocations run at 125 MB. The guard is here to catch a box with no
# room at all, not to pretend the pool is a clock.
MIN_GPU_FREE_BLOCK_BYTES = 64 * 1024 * 1024


def gpu_free_block_bytes() -> int | None:
    """The GPU pool's largest free block, as the admission daemon sees it."""
    try:
        done = subprocess.run(
            [os.path.expanduser("~/lm-tools/thor-admit"), "status", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if done.returncode == 0:
            return int(json.loads(done.stdout)["gpu_largest_free_block_bytes"])
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        pass
    return None


def cuda_available() -> bool:
    """Whether a CUDA batch can be made on this box, right now."""
    global _CUDA_CHECKED, _CUDA_OK
    if _CUDA_CHECKED:
        return _CUDA_OK
    _CUDA_CHECKED = True
    block = gpu_free_block_bytes()
    if block is None or block < MIN_GPU_FREE_BLOCK_BYTES:
        _CUDA_OK = False
        return False
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from core.sim import make_batch\n"
        "b = make_batch('beacons', num_envs=1, device='cuda')\n"
        "b.apply_actions([0])\n"
        "print('ok')\n" % str(REPO)
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", code], cwd=str(REPO), timeout=180,
            capture_output=True, text=True,
        )
        _CUDA_OK = done.returncode == 0 and "ok" in done.stdout
    except subprocess.TimeoutExpired:
        _CUDA_OK = False
    return _CUDA_OK


if cuda_available():
    DEVICES.append("cuda")


def test_the_backends_that_ran():
    """Which backends the gate actually compared.

    A gate that silently skips the GPU is not a gate, so the report says
    what it compared.
    """
    assert "cpu" in DEVICES
    print(f"the gate compared: {DEVICES}")


def action_sequence(seed: int, steps: int, num_envs: int) -> list[list[int]]:
    """The same actions for every run: legal ones, so nothing is refused early."""
    rng = np.random.default_rng(seed)
    return [
        [int(rng.integers(0, 9)) for _ in range(num_envs)] for _ in range(steps)
    ]


def params_for(world: int) -> Params:
    return Params(world_w=world, world_h=world)


def _greedy_action(round_: Round) -> int:
    """Walk the acting agent towards the nearest beacon it does not hold.

    A random walk does not cover the distance between the two spawns in the
    time a round lasts -- the displacement of a walk is the square root of
    its length -- so the sanity floor needs a policy that wants something.
    """
    world, state = round_.world, round_.state
    index = round_.acting_index()
    cx, cy = ref.cell_of(world, state.pos_x[index], state.pos_y[index])
    squad = state.agent_squad[index]
    # The enemy squad's centre: the beacon nearest it is the one the two
    # squads contest. (Each squad walking to its *own* nearest beacon would
    # send them to opposite corners, and they would never meet.)
    enemy = [i for i in range(state.num_agents) if state.agent_squad[i] != squad]
    if not enemy:
        return 0
    ex = sum(state.pos_x[i] for i in enemy) / len(enemy)
    ey = sum(state.pos_y[i] for i in enemy) / len(enemy)
    ecx, ecy = ref.cell_of(world, int(ex), int(ey))
    target = None
    best = None
    for b, (bx, by) in enumerate(world.beacons):
        if state.holders[b] == squad:
            continue  # ours already
        d = abs(bx - ecx) + abs(by - ecy)
        if best is None or d < best:
            best, target = d, (bx, by)
    if target is None:
        return 0
    mask = round_.mask()
    chosen, chosen_d = 0, None
    for action in range(1, len(ref.DIRECTIONS)):
        if not mask[action]:
            continue
        dx, dy = ref.DIRECTIONS[action]
        d = abs(target[0] - (cx + dx)) + abs(target[1] - (cy + dy))
        if chosen_d is None or d < chosen_d:
            chosen, chosen_d = action, d
    return chosen


def test_the_worlds_agree_byte_for_byte():
    """The generator: the reference's world and the host's world are the same bytes."""
    world = 32
    params = params_for(world)
    rounds = [Round(seed, params) for seed in (1, 2, 3)]
    batch = make_batch(
        "beacons", num_envs=3, rows=1, device="cpu", seed=0,
        params={"world_w": world, "world_h": world},
    )
    # The batch's worlds are grown from the seeds it was given.
    batch.reset(np.array([1, 2, 3], dtype=np.uint64))
    encoded = batch.world_bytes()
    for index, round_ in enumerate(rounds):
        assert encoded[index].tobytes() == round_.world_bytes(), (
            f"the world of seed {index + 1} differs"
        )


def test_the_states_agree_byte_for_byte():
    """The states: Python, CPU and CUDA, after every step."""
    world = 32
    steps = 24
    num_envs = 3
    params = params_for(world)
    actions = action_sequence(99, steps, num_envs)

    for device in DEVICES:
        # A fresh reference for every backend: the pass steps it.
        rounds = [Round(seed, params) for seed in range(1, num_envs + 1)]
        batch = make_batch(
            "beacons", num_envs=num_envs, rows=1, device=device, seed=0,
            params={"world_w": world, "world_h": world},
        )
        batch.reset(np.arange(1, num_envs + 1, dtype=np.uint64))
        for step in range(steps):
            for index, round_ in enumerate(rounds):
                round_.step(actions[step][index])
            batch.apply_actions(np.array(actions[step], dtype=np.int32))
            encoded = batch.state_bytes()
            for index, round_ in enumerate(rounds):
                assert encoded[index].tobytes() == round_.state_bytes(), (
                    f"[{device}] the state of world {index} differs at step {step}"
                )


def test_the_masks_agree():
    """The legal-action mask: the rules engine writes it, on every backend."""
    world = 32
    steps = 12
    num_envs = 3
    params = params_for(world)
    actions = action_sequence(7, steps, num_envs)

    for device in DEVICES:
        rounds = [Round(seed, params) for seed in range(1, num_envs + 1)]
        batch = make_batch(
            "beacons", num_envs=num_envs, rows=1, device=device, seed=0,
            params={"world_w": world, "world_h": world},
        )
        batch.reset(np.arange(1, num_envs + 1, dtype=np.uint64))
        for step in range(steps):
            mask = batch.legal_action_mask()
            for index, round_ in enumerate(rounds):
                assert list(mask[index]) == list(round_.mask()), (
                    f"[{device}] the mask of world {index} differs at step {step}"
                )
            for index, round_ in enumerate(rounds):
                round_.step(actions[step][index])
            batch.apply_actions(np.array(actions[step], dtype=np.int32))


def test_the_observations_agree():
    """The observation planes: the same floats, on every backend."""
    world = 32
    steps = 6
    num_envs = 2
    params = params_for(world)
    actions = action_sequence(13, steps, num_envs)

    for device in DEVICES:
        rounds = [Round(seed, params) for seed in range(1, num_envs + 1)]
        batch = make_batch(
            "beacons", num_envs=num_envs, rows=1, device=device, seed=0,
            params={"world_w": world, "world_h": world},
        )
        batch.reset(np.arange(1, num_envs + 1, dtype=np.uint64))
        for step in range(steps):
            obs = batch.obs()
            for index, round_ in enumerate(rounds):
                want = np.array(round_.obs(), dtype=np.float32).reshape(
                    obs.shape[1:]
                )
                assert np.array_equal(obs[index], want), (
                    f"[{device}] the observation of world {index} differs at step {step}"
                )
            for index, round_ in enumerate(rounds):
                round_.step(actions[step][index])
            batch.apply_actions(np.array(actions[step], dtype=np.int32))


def test_the_rewards_agree():
    """The reward: the points the acting squad scored."""
    world = 32
    steps = 40
    num_envs = 2
    params = params_for(world)
    actions = action_sequence(23, steps, num_envs)

    for device in DEVICES:
        rounds = [Round(seed, params) for seed in range(1, num_envs + 1)]
        batch = make_batch(
            "beacons", num_envs=num_envs, rows=1, device=device, seed=0,
            params={"world_w": world, "world_h": world},
        )
        batch.reset(np.arange(1, num_envs + 1, dtype=np.uint64))
        for step in range(steps):
            for index, round_ in enumerate(rounds):
                round_.step(actions[step][index])
            batch.apply_actions(np.array(actions[step], dtype=np.int32))
            reward = batch.reward()
            for index, round_ in enumerate(rounds):
                assert float(reward[index]) == float(round_.reward()), (
                    f"[{device}] the reward of world {index} differs at step {step}"
                )


def test_the_game_actually_plays():
    """A sanity floor: the port is not a game that stands still.

    Random legal play, on the Python reference: the agents walk, some get
    tagged, and the beacons change hands. Without this the equality gate
    could pass on a simulator that does nothing.

    The horizon is long on purpose. The motor moves `speed_upt` (136) units
    a tick and a cell is 2048 units, so an agent crosses one cell every
    fifteen ticks -- and a round of eight agents is eight steps a tick. The
    squads start twenty-seven cells apart, so they need about four hundred
    ticks, which is three thousand two hundred steps, before they can meet.
    """
    params = params_for(32)
    steps = 4000
    moved = 0
    tagged = 0
    held = 0
    rounds = 6
    for seed in range(1, rounds + 1):
        round_ = Round(seed, params)
        start = [(x, y) for x, y in zip(round_.state.pos_x, round_.state.pos_y)]
        for _ in range(steps):
            round_.step(_greedy_action(round_))
        end = [(x, y) for x, y in zip(round_.state.pos_x, round_.state.pos_y)]
        if start != end:
            moved += 1
        if any(round_.state.stunned):
            tagged += 1
        if any(h >= 0 for h in round_.state.holders):
            held += 1
    assert moved >= rounds - 1, f"only {moved} of {rounds} rounds moved"
    assert tagged >= 1, "no agent was ever tagged"
    assert held >= 1, "no beacon was ever held"
