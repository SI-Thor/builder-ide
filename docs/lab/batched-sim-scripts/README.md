# `docs/lab/batched-sim-scripts/` — the measurement scripts

The scripts that produced the numbers in
[`docs/lab/exp-batched-sim.md`](../exp-batched-sim.md).

| script | what it does | how to run | how long |
|---|---|---|---|
| `bench_env.py` | env steps/s at a batch size, on one of three devices, with the box state beside the number | `.venv/bin/python docs/lab/batched-sim-scripts/bench_env.py --batches 128 1024 4096 --steps 2000 --reps 7 --device cuda` | minutes per configuration on the GPU; seconds on the CPU; minutes on the Python reference |
| `results/` | the raw JSON each run wrote, beside the log of the run | — | — |

**The three devices.** `--device cuda` is the GPU backend (the same
`rules.cuh`, compiled by nvcc for sm_110); `--device cpu` is the CPU backend
(the same header, compiled by g++, 14 threads over the worlds); `--device
python` is the reference itself, one world at a time in pure Python, which is
the baseline the two are compared with.

**What it needs.** The repo's venv (`.venv`) and the built module
(`core/sim/build.sh`). A GPU run needs the box's GPU pool to have room:
the script reads the pool's largest free block and **refuses to start** if
the batch does not fit, because on the Thor a CUDA allocation that does not
fit blocks in the kernel rather than failing.

**The two variants.** `step` times the environment alone (`apply_actions`);
`step+obs` adds the observation planes, which is what a policy actually
consumes. `--obs-steps` sets how many steps the observation variant runs
(the rate is the number, and a rate does not need a long run). The
observation is skipped where it is too big to measure — above
`MAX_CPU_OBS_CELLS` on the CPU and above `MAX_PYTHON_OBS_CELLS` on the
Python reference — and the JSON says which, rather than leaving it blank.

**The numbers.** The median of `--reps` repetitions of `--steps` steps. The
first repetition is a warm-up and is not counted: it pays for the first
touch of every buffer.

**The box state.** Every run records the load average, the free memory and
the GPU pool's largest free block before and after, in the JSON beside the
numbers. A timing number on this box without the box beside it is not a
measurement: the GPU memory is the system memory, and the box is shared.

**The file names.** `bench_<device>_<batch>_w<world>.json`, one
configuration per file, next to the `.log` of the same run.
