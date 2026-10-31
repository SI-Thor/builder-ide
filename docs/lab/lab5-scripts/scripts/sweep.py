#!/usr/bin/env python3
# lab5 — the round-5 sweep: baseline + batched arms, interleaved by seed
# (round rule 4: on a shared box, interleave the variants).
#
# One subprocess per solve (fresh headless Blender session per run); arms are
# cycled inside each seed so any load drift spreads across arms evenly.
# Box state is snapshotted (scripts/box_state.sh) before/after the whole
# sweep and beside every run's log.

import json
import subprocess
import sys
import time
from pathlib import Path

LAB5 = Path(__file__).resolve().parent.parent
PY = Path.home() / "lm-wt/v2-thor/.venv/bin/python"
RESULTS = LAB5 / "results"
RUNS = LAB5 / "runs"

# The arms. The distribution gate runs on the *quarter schedule*
# (25/10/5 steps — small enough that N=512 same-steps fits the day on the
# CPU); the full fast_solve baseline is anchored separately in results_full/.
#
# budget=same-steps is the natural upstream change: the annealing schedule
# and decision count are untouched, each step just scores N candidates and
# shows the annealer the best (or a sampled) one. That is also what a free
# GPU scorer buys. budget=equal (steps/N steps) is kept as a datapoint only.
#
# (tag, arm, N, mode, budget, seeds, stages, steps_override)
#
# Seeds: the upstream floor-plan solver crashes on some seeds (degenerate
# shapely polygon; 2,3,4,13 probed) — every arm uses the same five seeds
# that survive it (probe_seeds.sh finds them).
#
# The GATE arms run the **large object stages only** at a 15-step schedule:
# the full solve makes ~46 solve_objects calls (side_obj ×14,
# obj_on_support ×14 …), and at N×64 candidates per step the batched arms
# cost ~1 h/seed on this CPU — the gate needs identical schedules across
# arms, not maximal stages. The large stages are the dominant real
# placement work (the full-solve baseline spends its biggest single block
# there). The today-anchor (results_full/) keeps the whole default
# fast_solve solve for the wall story.
GATE = "15,0,0"
GATE_STAGES = "large"
SEEDS5 = [0, 1, 5, 6, 7]
ARMS = [
    ("baseg", "baseline", 1, "best", "same-steps", SEEDS5, GATE_STAGES, GATE),
    ("b8bestg", "batch", 8, "best", "same-steps", SEEDS5, GATE_STAGES, GATE),
    ("b8unifg", "batch", 8, "uniform", "same-steps", SEEDS5, GATE_STAGES, GATE),
    ("b8sampleg", "batch", 8, "sample", "same-steps", SEEDS5, GATE_STAGES, GATE),
    ("b64bestg", "batch", 64, "best", "same-steps", SEEDS5, GATE_STAGES, GATE),
    ("b64sampleg", "batch", 64, "sample", "same-steps", [0, 1, 5], GATE_STAGES, GATE),
    ("b512bestg", "batch", 512, "best", "same-steps", [0, 1], GATE_STAGES, GATE),
]
# the today-anchor: the unmodified fast_solve schedule (100/40/5 steps),
# all solve stages
ARMS_FULL = [
    ("basefull", "baseline", 1, "best", "same-steps", SEEDS5, "large,medium,small", None),
]


def box(tag: str) -> None:
    out = subprocess.run([str(LAB5 / "scripts/box_state.sh")], capture_output=True, text=True)
    (RUNS / f"box_{tag}.txt").write_text(out.stdout)


def run_one(tag, arm, N, mode, budget, seed, stages, steps_override, results_dir) -> None:
    out_json = results_dir / f"{tag}_seed{seed}.json"
    if out_json.exists():
        print(f"[skip] {out_json.name} exists", flush=True)
        return
    log = RUNS / f"{tag}_seed{seed}.log"
    cmd = [
        str(PY), str(LAB5 / "scripts/run_solve.py"),
        "--seed", str(seed), "--arm", arm, "--N", str(N),
        "--mode", mode, "--budget", budget, "--stages", stages,
        "--out", str(out_json),
    ]
    if steps_override:
        cmd += ["--steps-override", steps_override]
    t1 = time.time()
    with open(log, "w") as fh:
        proc = subprocess.run(cmd, env={"PYTHONPATH": "pylibs", "PATH": "/usr/bin:/bin"},
                              cwd=LAB5, stdout=fh, stderr=subprocess.STDOUT)
    dt = time.time() - t1
    ok = proc.returncode == 0 and out_json.exists()
    line = f"[{'ok ' if ok else 'FAIL'}] {tag} seed{seed} {dt/60:.1f}min"
    print(line, flush=True)
    with open(RUNS / "sweep_progress.txt", "a") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {line}\n")


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)
    (LAB5 / "results_full").mkdir(exist_ok=True)
    only = set(sys.argv[1:])  # optional: restrict to these tags

    box("sweep_start")
    t0 = time.time()

    # the full-schedule baseline first (one run already exists from the smoke)
    for tag, arm, N, mode, budget, seeds, stages, steps in ARMS_FULL:
        if only and tag not in only:
            continue
        for seed in seeds:
            run_one(tag, arm, N, mode, budget, seed, stages, steps, LAB5 / "results_full")

    # then the gate arms, interleaved by seed (rule 4)
    max_seed = max(s for *_, seeds, _st, _t in ARMS for s in seeds)
    for seed in range(max_seed + 1):
        for tag, arm, N, mode, budget, seeds, stages, steps in ARMS:
            if seed not in seeds:
                continue
            if only and tag not in only:
                continue
            run_one(tag, arm, N, mode, budget, seed, stages, steps, RESULTS)

    box("sweep_end")
    print(f"sweep done in {(time.time()-t0)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
