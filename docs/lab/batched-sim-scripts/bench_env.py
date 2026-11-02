"""Env steps/s for the batched simulator, with the box state beside it.

This is the measurement the design asks for
(`docs/design/batched-sim.md` §5, build 1): env steps/s at batch 128 / 1024 /
4096, against the Python/CPU reference.

Two variants are timed, the way the Stratego port's own bench did it:

  - **step**: the environment alone -- `apply_actions`;
  - **step+obs**: the same plus the observation planes, which is what the
    policy actually consumes.

Every number is the median of `--reps` repetitions of `--steps` steps, and
the box state (load average, free memory, the GPU pool's largest free block)
is recorded before and after, because this box's GPU memory is its system
memory and a number without the box beside it is not a measurement.

Usage:

    .venv/bin/python docs/lab/batched-sim-scripts/bench_env.py \\
        --batches 128 1024 4096 --steps 2000 --reps 7 --device cuda

`--device python` measures the pure Python reference instead, which is the
baseline the batched backends are compared with.

The script refuses to run a GPU workload that does not fit: it reads the
GPU pool's largest free block and sizes the batch against it.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.sim import make_batch  # noqa: E402


def load_average() -> list[float]:
    try:
        with open("/proc/loadavg") as handle:
            return [float(x) for x in handle.readline().split()[:3]]
    except OSError:
        return []


def memory_free_bytes() -> int:
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def thor_status() -> dict:
    """The admission daemon's view of the box."""
    try:
        done = subprocess.run(
            [os.path.expanduser("~/lm-tools/thor-admit"), "status", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if done.returncode == 0:
            return json.loads(done.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return {}


def box_state() -> dict:
    status = thor_status()
    return {
        "load_average": load_average(),
        "mem_available_bytes": memory_free_bytes(),
        "gpu_largest_free_block_bytes": status.get("gpu_largest_free_block_bytes"),
        "gpu_box_used_bytes": status.get("gpu_box_used_bytes"),
        "leases": [
            {"label": lease.get("label"), "peak_bytes": lease.get("peak_bytes"),
             "current_rss_bytes": lease.get("current_rss_bytes")}
            for lease in status.get("leases", [])
        ],
    }


def time_steps(batch, actions, steps: int) -> float:
    """The seconds for `steps` steps of the whole batch."""
    start = time.perf_counter()
    for index in range(steps):
        batch.apply_actions(actions[index % len(actions)])
    return time.perf_counter() - start


def time_steps_with_obs(batch, actions, steps: int) -> float:
    start = time.perf_counter()
    for index in range(steps):
        batch.obs()
        batch.apply_actions(actions[index % len(actions)])
    return time.perf_counter() - start


# The observation is the expensive half: every cell of every world gets a
# line-of-sight walk. On the CPU that work does not shrink with the batch, so
# a configuration whose observation is bigger than this is measured for the
# step only, and the report says so.
MAX_CPU_OBS_CELLS = 8_000_000

# The pure Python reference writes the observation one cell at a time, so it
# is measured on the observation only where that fits in the budget.
MAX_PYTHON_OBS_CELLS = 20_000


def bench_one(device: str, batch_size: int, steps: int, reps: int, params: dict,
              variant: str = "auto", obs_steps: int | None = None) -> dict:
    batch = make_batch(
        "beacons", num_envs=batch_size, rows=1, device=device, seed=0, params=params
    )
    rng = np.random.default_rng(1234)
    actions = [
        rng.integers(0, batch.spec["num_actions"], size=batch_size, dtype=np.int32)
        for _ in range(64)
    ]
    # The first repetition pays for the warm-up (the first touch of every
    # buffer), so it is measured separately and not counted in the median.
    time_steps(batch, actions, min(steps, 64))
    step_times = [time_steps(batch, actions, steps) for _ in range(reps)]
    obs_cells = batch_size * params["world_w"] * params["world_h"]
    want_obs = variant in ("step_obs", "both")
    if variant == "auto":
        want_obs = device == "cuda" or obs_cells <= MAX_CPU_OBS_CELLS
    # The observation is the expensive half, so it is timed over fewer
    # steps: the rate is the number, and a rate does not need a long run.
    obs_run_steps = obs_steps if obs_steps is not None else steps
    obs_times = (
        [time_steps_with_obs(batch, actions, obs_run_steps) for _ in range(reps)]
        if want_obs
        else []
    )

    def report(times: list[float], count: int) -> dict:
        median = statistics.median(times)
        return {
            "seconds_median": median,
            "seconds_min": min(times),
            "seconds_max": max(times),
            "env_steps_per_s": batch_size * count / median,
            "us_per_env_step": 1e6 * median / (batch_size * count),
        }

    entry = {
        "device": device,
        "num_envs": batch_size,
        "steps": steps,
        "obs_steps": obs_run_steps if want_obs else 0,
        "reps": reps,
        "params": params,
        "step": report(step_times, steps),
    }
    if obs_times:
        entry["step_obs"] = report(obs_times, obs_run_steps)
    else:
        entry["step_obs"] = {
            "skipped": f"the observation is {obs_cells} cells a step, over the "
                       f"{MAX_CPU_OBS_CELLS} this script measures on the CPU",
        }
    return entry


def bench_python(batch_size: int, steps: int, reps: int, params: dict,
                 variant: str = "auto", obs_steps: int | None = None) -> dict:
    """The same rules, run one env at a time in pure Python.

    This is the reference the GPU and the CPU are checked against, so it is
    also the baseline the throughput is compared with. There is no batch
    here: the reference holds one `Round` per world and the loop walks them
    in turn, which is what the Python/CPU baseline *is*.
    """
    from core.sim.systems.beacons import reference

    ref_params = reference.Params(world_w=params["world_w"], world_h=params["world_h"])
    rounds = [reference.Round(seed=i, params=ref_params) for i in range(batch_size)]
    rng = np.random.default_rng(1234)
    actions = [
        rng.integers(0, reference.NUM_ACTIONS, size=batch_size, dtype=np.int32)
        for _ in range(64)
    ]

    def run(count: int, with_obs: bool) -> float:
        start = time.perf_counter()
        for index in range(count):
            row = actions[index % len(actions)]
            for env, rnd in enumerate(rounds):
                if with_obs:
                    rnd.obs()
                rnd.step(int(row[env]))
        return time.perf_counter() - start

    # The warm-up pays for the first touch of every world; it is not counted.
    run(min(steps, 16), False)
    step_times = [run(steps, False) for _ in range(reps)]
    obs_cells = batch_size * params["world_w"] * params["world_h"]
    want_obs = variant in ("step_obs", "both")
    if variant == "auto":
        # The reference writes the observation one cell at a time, in Python:
        # it is ~10^3 times slower than the same work in C++. It is measured
        # only where it fits in the budget, and the report says which.
        want_obs = obs_cells <= MAX_PYTHON_OBS_CELLS
    obs_run_steps = obs_steps if obs_steps is not None else steps
    obs_times = (
        [run(obs_run_steps, True) for _ in range(reps)] if want_obs else []
    )

    def report(times: list[float], count: int) -> dict:
        median = statistics.median(times)
        return {
            "seconds_median": median,
            "seconds_min": min(times),
            "seconds_max": max(times),
            "env_steps_per_s": batch_size * count / median,
            "us_per_env_step": 1e6 * median / (batch_size * count),
        }

    entry = {
        "device": "python",
        "num_envs": batch_size,
        "steps": steps,
        "obs_steps": obs_run_steps if want_obs else 0,
        "reps": reps,
        "params": params,
        "step": report(step_times, steps),
    }
    if obs_times:
        entry["step_obs"] = report(obs_times, obs_run_steps)
    else:
        entry["step_obs"] = {
            "skipped": f"the observation is {obs_cells} cells a step; the pure "
                       f"Python reference is measured on it only up to "
                       f"{MAX_PYTHON_OBS_CELLS} cells",
        }
    return entry


def require_gpu_room(need_bytes: int) -> None:
    """Refuse to start a GPU workload the box cannot hold.

    On the Thor a CUDA allocation that does not fit the pool **blocks in the
    kernel rather than failing**, and the process ends up in uninterruptible
    sleep. The box's own advice is to size a GPU workload against the pool's
    largest free block, so that is what this checks.
    """
    status = thor_status()
    block = status.get("gpu_largest_free_block_bytes")
    if block is None:
        print("no GPU view from the admission daemon; the run is not started")
        raise SystemExit(2)
    if block < need_bytes:
        print(
            f"the GPU pool's largest free block is {block / 1e6:.1f} MB; "
            f"this run needs {need_bytes / 1e6:.1f} MB. The run is not started."
        )
        raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches", type=int, nargs="+", default=[128, 1024, 4096])
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--reps", type=int, default=7)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--world", type=int, default=128, help="the world's edge in cells")
    parser.add_argument("--obs-steps", type=int, default=200,
                        help="the steps the observation variant runs; the rate is "
                             "the number and does not need a long run")
    parser.add_argument("--variant", default="auto",
                        choices=["auto", "step", "step_obs", "both"],
                        help="which variants to time; auto skips the observation "
                             "on the CPU when it is too big to measure")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    params = {"world_w": args.world, "world_h": args.world}
    if args.device in ("cuda", "gpu"):
        # The batch's own footprint: the state, the world, the mask and the
        # observation planes, at the largest batch asked for.
        largest = max(args.batches)
        need = largest * (6 * args.world * args.world * 4 + 16_448 + 480)
        require_gpu_room(need)
    result = {
        "box_before": box_state(),
        "device": args.device,
        "world": args.world,
        "results": [],
    }
    for batch_size in args.batches:
        print(f"== batch {batch_size} ({args.device}, {args.world}x{args.world}) ==",
              flush=True)
        if args.device == "python":
            entry = bench_python(batch_size, args.steps, args.reps, params,
                                 args.variant, args.obs_steps)
        else:
            entry = bench_one(args.device, batch_size, args.steps, args.reps, params,
                              args.variant, args.obs_steps)
        result["results"].append(entry)
        print(
            f"   step      {entry['step']['env_steps_per_s']:>12,.0f} env-steps/s "
            f"({entry['step']['us_per_env_step']:.3f} us/env-step)",
            flush=True,
        )
        if "env_steps_per_s" in entry["step_obs"]:
            print(
                f"   step+obs  {entry['step_obs']['env_steps_per_s']:>12,.0f} env-steps/s "
                f"({entry['step_obs']['us_per_env_step']:.3f} us/env-step)",
                flush=True,
            )
        else:
            print(f"   step+obs  skipped: {entry['step_obs']['skipped']}", flush=True)
    result["box_after"] = box_state()

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
