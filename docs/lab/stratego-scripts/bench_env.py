#!/usr/bin/env python3
"""Environment throughput on the Thor: env steps/s at batch 128 / 1024 / 4096.

This is the measurement the desk brief asks for: "(c) env steps/s at batch
128/1024/4096". It is the same shape as upstream's
`scripts/profile/profile_env.py` (same buffer size, same move_memory, same
random-legal-action sampling), with the units fixed and the box state recorded
beside the numbers, as DOC-RULES.md asks.

Two variants are timed:

  step  : sample_random_legal_action + apply_actions  (the environment alone)
  obs   : the above + compute_infostate_tensor          (the policy's input)

The second is the number that matters for a policy: the observation planes are
355+ per game, and they are written by nine separate kernel launches.

Usage (from the stratego checkout, with its .venv on PATH):
    python bench_env.py --num-envs 128,1024,4096 --out results/bench_env.json
"""

import argparse
import json
import os
import statistics
import subprocess
import time

import torch

from pyengine.utils.load_pystratego import get_pystratego

pystratego = get_pystratego()


def box_state() -> dict:
    """The box state that the numbers have to be read against."""
    out = {}
    try:
        with open("/proc/loadavg") as f:
            out["loadavg"] = f.read().split()[:3]
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    out["mem_total_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                if line.startswith("MemAvailable:"):
                    out["mem_available_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        out["nvidia_smi"] = smi
    except Exception:
        pass
    out["cuda_visible_devices"] = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    return out


def bench(num_envs: int, num_rows: int = 400, move_memory: int = 32,
          num_reps: int = 7, warmup: int = 20) -> dict:
    env = pystratego.StrategoRolloutBuffer(
        num_rows,
        num_envs,
        reset_behavior=pystratego.ResetBehavior.RANDOM_JB_CLASSIC_BOARD,
        move_memory=move_memory,
        two_square_rule=True,
    )
    action = torch.zeros(num_envs, dtype=torch.int32, device="cuda")

    # Warm up: cuBLAS/kernel autotune and the first-touch allocations.
    env.reset()
    for _ in range(warmup):
        env.sample_random_legal_action(action)
        env.apply_actions(action)
    torch.cuda.synchronize()

    step_times = []
    obs_times = []
    steps = 5 * num_rows

    for _ in range(num_reps):
        env.reset()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(steps):
            env.sample_random_legal_action(action)
            env.apply_actions(action)
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)

        env.reset()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for t in range(steps):
            env.sample_random_legal_action(action)
            env.apply_actions(action)
            env.compute_infostate_tensor(t)
        torch.cuda.synchronize()
        obs_times.append(time.perf_counter() - t0)

    def summarise(times):
        med = statistics.median(times)
        total_env_steps = num_envs * steps
        return {
            "median_s": round(med, 4),
            "min_s": round(min(times), 4),
            "max_s": round(max(times), 4),
            "env_steps_per_s": round(total_env_steps / med, 1),
            "us_per_env_step": round(med / total_env_steps * 1e6, 3),
        }

    result = {
        "num_envs": num_envs,
        "num_rows": num_rows,
        "move_memory": move_memory,
        "steps_per_rep": steps,
        "num_reps": num_reps,
        "step": summarise(step_times),
        "obs": summarise(obs_times),
    }
    del env
    torch.cuda.empty_cache()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-envs", default="128,1024,4096")
    ap.add_argument("--num-rows", type=int, default=400)
    ap.add_argument("--move-memory", type=int, default=32)
    ap.add_argument("--num-reps", type=int, default=7)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    results = []
    for n in [int(x) for x in args.num_envs.split(",")]:
        r = bench(n, num_rows=args.num_rows, move_memory=args.move_memory,
                  num_reps=args.num_reps)
        r["box"] = box_state()
        results.append(r)
        print(
            f"envs={r['num_envs']:>5}  "
            f"step: {r['step']['env_steps_per_s']:>12,.0f} env-steps/s "
            f"({r['step']['us_per_env_step']:>8.3f} us/env-step)  |  "
            f"obs: {r['obs']['env_steps_per_s']:>12,.0f} env-steps/s "
            f"({r['obs']['us_per_env_step']:>8.3f} us/env-step)",
            flush=True,
        )
        print(f"    box: {r['box']}", flush=True)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump({"results": results, "box": box_state()}, f, indent=2)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
