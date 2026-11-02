# Batched simulator — implementation plan

> **For agentic workers:** execute task-by-task in one session (the desk brief
> forbids sub-agents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** build `core/sim/` — the general batched-simulator interface from
`docs/design/batched-sim.md` §1 (C++/CUDA, Python bindings) — and port one real
game of ours onto it: the **last-mile Beacons** ruleset, with the Python/CPU
reference, the GPU/CPU byte-identical trajectory proof, and env steps/s at batch
128 / 1024 / 4096.

**Architecture:** `core/sim/state.h` is the generic container (one contiguous
array of fixed-size states, `template <class Traits> struct Batch`).
`core/sim/kernels.h` is the kernel contract (a `Backend` vtable: reset / step /
mask / obs / terminate) and the system registry. `core/sim/bindings.cc` is the
single pybind11 module `_pysim`. Each rule system lives in
`core/sim/systems/<name>/` and supplies: the POD state, the rules **written
once** in a header that compiles for both host and device, a CUDA backend, a
host (CPU) backend, the plane manifest, and a Python reference implementation.

The Beacons rules live in `core/sim/systems/beacons/rules.cuh`, compiled by g++
(for the CPU backend) and by nvcc (for the GPU backend). One source of truth for
the rules, so "GPU == CPU" is a property of the *backend*, not of a
re-implementation. The Python reference is a third, independent implementation
of the same semantics, and is the ground truth.

**Tech stack:** C++17 host, CUDA 13.2 (`nvcc` at `/usr/local/cuda-13.2`, target
`sm_110`), pybind11, numpy (the binding's array type), pytest.

## Global constraints

- The Thor is the only machine this runs on. `nvcc` is **not** on PATH; use
  `/usr/local/cuda-13.2/bin/nvcc`. Target `sm_110`.
- The build has **no** `CMAKE_BUILD_TYPE`: no `-DNDEBUG`, so the device-side
  asserts stay in (the rule that caught the Stratego port's defects).
- GPU memory is system memory. The box's **largest free block** was 0.965 GB at
  planning time; size every allocation against that, not against free memory
  (an allocation that does not fit *blocks in the kernel* on this box).
- All GPU work runs under a lease:
  `~/lm-tools/thor-admit run --tier live --peak <size> --label batched-sim.<step> -- <cmd>`.
- Never `python -m venv` + pip copy: use `uv venv` + `uv pip install` (hard
  links from the shared cache). The repo's `.venv/` is already gitignored.
- Do not push. Commit on the `batched-sim` branch with full messages.
- Files are written on the Thor with `scp`; never build heredocs inside
  `ssh "…"`.
- Never start anything that preallocates GPU memory without
  `XLA_PYTHON_CLIENT_PREALLOCATE=false`.
- DOC-RULES: write as you go; `NOTES.md` gets a dated entry per step; every
  number carries the box state; say what was not verified.

---

## File map

| path | what it owns |
|---|---|
| `core/sim/README.md` | what the interface is, how to build it, how to run its tests |
| `core/sim/state.h` | `template <class Traits> struct Batch` — the container |
| `core/sim/kernels.h` | the kernel contract, the `Backend` vtable, the registry |
| `core/sim/bindings.cc` | the pybind11 module `_pysim` |
| `core/sim/CMakeLists.txt` | the build (CUDA + pybind11, no build type) |
| `core/sim/build.sh` | one-command build |
| `core/sim/__init__.py` | the Python wrapper: `make_batch`, tensor-shaped returns |
| `core/sim/systems/beacons/state.h` | the Beacons POD state and its traits |
| `core/sim/systems/beacons/rules.cuh` | the rules: host **and** device |
| `core/sim/systems/beacons/worldgen.cuh` | the seed-grown world (host **and** device) |
| `core/sim/systems/beacons/host.cc` | the CPU backend (the same `rules.cuh`) |
| `core/sim/systems/beacons/kernels.cu` | the CUDA backend (the same `rules.cuh`) |
| `core/sim/systems/beacons/python.cpp` | the system's registration into `pysim` |
| `core/sim/systems/beacons/planes.json` | the plane manifest (the contract) |
| `core/sim/systems/beacons/reference.py` | the Python/CPU reference implementation |
| `core/sim/systems/beacons/README.md` | the ported game: rules, deviations, tests |
| `tests/sim/test_beacons_rules.py` | the Python reference's own rule tests |
| `tests/sim/test_beacons_equivalence.py` | Python == CPU == CUDA, byte-identical |
| `docs/lab/exp-batched-sim.md` | the lab note: mechanism, numbers, box state |
| `docs/lab/batched-sim-scripts/bench_env.py` | the benchmark that produced the numbers |

## The ported game, precisely

Ported from `~/last-mile` (read-only) `crates/lm-core`:
`rules/beacons.rs`, `world/{grid,los,gen}.rs`, `rng.rs`, `hash.rs`, `fixed.rs`,
`agent.rs` (the motor), `params.rs`.

**One env = one round.** `num_envs` rounds, each with its own seed.
One step = one **acting agent's** turn (the design's "one character's turn
inside a shared world"). The acting agent rotates over the roster; when the
rotation wraps, the round's rules tick runs. So a round of 8 agents takes 8
steps per tick.

- **Action space A = 9**: `0` hold, `1..8` the eight neighbour directions
  (N, NE, E, SE, S, SW, W, NW).
- **Mask**: written by the rules engine, `num_envs × 9`. Hold is legal always;
  a move is legal iff the neighbour cell is in bounds and not a `Wall`. A
  stunned agent may only hold (the real motor holds while stunned).
- **Motor**: last-mile's kinematics exactly — a speed budget of `speed_upt`
  (136) units per tick, spent axis-separated (y first when
  `(now / axis_swap_ticks) % 2 == 1`), never entering a non-walkable cell.
  The **routing** (JPS) is not ported: the policy picks the neighbour, so the
  env's action space is the neighbour move. This is the one deliberate
  deviation, and it is documented in the system's README.
- **Rules tick** (when the rotation wraps): respawn → tag (rotating order, a
  tag never comes back in the same tick) → hold (a beacon in two squads is
  held by nobody) → score → end (win score or tick limit).
- **Reward**: the points the acting agent's squad scored this step.
- **Obs** (`num_envs, C, H, W`, float32, the acting agent's eyes):
  `visible`, `terrain`, `beacon_holder`, `self`, `ally`, `enemy` — C = 6.
  Visibility is last-mile's rule: Chebyshev distance ≤ `view_range_cells`
  **and** the Bresenham line of sight is clear.
- **World**: grown from the seed exactly as `world/gen.rs` grows it —
  SplitMix64 streams, wall blocks in the top half, cover, the 180° mirror,
  pinned symmetric spawns and beacons, the 3×3 neighbourhoods floored, and the
  mirrored L-shaped corridor repair.

**Equality**: the state is all integers (no float ever enters it), so the
GPU's state bytes and the CPU's state bytes are compared byte-for-byte.

---

### Task 1 — toolchain and build environment

- [ ] Install `uv`; create `~/lm-wt/batched-sim/.venv` with `uv venv`; install
  `numpy`, `pytest>=8`, `pybind11` with `uv pip install`.
- [ ] Verify `python -c "import pybind11; print(pybind11.get_include())"`.
- [ ] Verify a trivial `nvcc -arch=sm_110` compile of a kernel runs on the GPU.
- [ ] Commit: `build: the venv and a CUDA smoke check`.

### Task 2 — the general interface (`core/sim/`)

- [ ] `state.h`: `template <class Traits> struct Batch` with the fields from
  the design doc (`d_states`, `d_terminated`, `d_reward`, `d_legal_mask`,
  `d_obs`) plus `d_worlds` for the static per-round world; `rows` is the
  rollout depth; the obs buffer's row factor is `Traits::kObsHistory`.
- [ ] `kernels.h`: `SystemTraits`, the `Backend` vtable (reset / step / mask /
  obs / terminate), and the registry (`register_system`, `make_backend`).
- [ ] `bindings.cc`: module `_pysim`; `make_batch(system, num_envs, rows,
  device, seed)` → a `Batch` object with `apply_actions`, `legal_action_mask`,
  `obs`, `reward`, `terminated`, `reset`, `state_bytes`, `world_bytes`.
  Every returned array is **cloned** (the backend reuses its buffers), per the
  design doc's rule.
- [ ] `__init__.py`: `make_batch(...)` wrapper; numpy in, numpy out; a
  `.torch()` helper that converts with `torch.from_numpy` when torch is
  importable (torch is **not** installed on this box — documented).
- [ ] `CMakeLists.txt` + `build.sh`; `README.md`.
- [ ] Commit: `core/sim: the batched-simulator interface`.

### Task 3 — the Beacons rules, written once (`rules.cuh`, `worldgen.cuh`)

- [ ] `rules.cuh`: FNV-1a 64, SplitMix64, the grid, the Bresenham LOS, the
  motor's `axis_step`, the rules tick, the reward, the mask, the obs planes.
  Compiles for host **and** device (`__host__ __device__`).
- [ ] `worldgen.cuh`: the generator, ported from `world/gen.rs`.
- [ ] `state.h`: the POD state + traits.
- [ ] `planes.json`: the manifest (version 1, the six planes, the nine actions).
- [ ] Commit: `core/sim/systems/beacons: the rules, one source for host and device`.

### Task 4 — the Python reference (`reference.py`)

- [ ] Port the semantics to Python: `Fnv64`, `Rng`, `Grid`, `los.clear`,
  `worldgen`, the motor, the rules tick, the mask, the obs.
- [ ] `tests/sim/test_beacons_rules.py`: the reference's own tests — tag stuns
  and respawns, a beacon in two squads is held by nobody, the score and the
  win condition, the LOS symmetry, the generator's determinism.
- [ ] Commit: `core/sim/systems/beacons: the Python reference and its tests`.

### Task 5 — the CPU backend and the bindings

- [ ] `host.cc`: the same `rules.cuh`, called per env.
- [ ] `python.cpp`: registration; `make_batch("beacons", ...)`.
- [ ] Commit: `core/sim/systems/beacons: the CPU backend`.

### Task 6 — the CUDA backend

- [ ] `kernels.cu`: `ResetKernel`, `StepKernel`, `MaskKernel`, `ObsKernel`,
  `TerminateKernel` — one thread per env (the mask and obs are one thread per
  env too: the Beacons mask is 9 bits and the obs is a per-env POV).
- [ ] Commit: `core/sim/systems/beacons: the CUDA backend`.

### Task 7 — the equality gate

- [ ] `tests/sim/test_beacons_equivalence.py`: the same seed and the same
  action sequence on the Python reference, the CPU backend and the CUDA
  backend; the **state bytes** compared byte-for-byte after every step, over
  several seeds and several worlds.
- [ ] Also compare the masks and the obs bytes.
- [ ] Commit: `core/sim: the GPU and the CPU agree byte-for-byte`.

### Task 8 — the measurements

- [ ] `docs/lab/batched-sim-scripts/bench_env.py`: env steps/s at batch 128 /
  1024 / 4096, the `step` variant and the `step + obs` variant, 7 repetitions
  of 2000 steps, median reported; the box state recorded before and after.
- [ ] Run it under `thor-admit run --tier live --peak <size> --label
  batched-sim.bench -- ...`, sized against the largest free block.
- [ ] `docs/lab/exp-batched-sim.md`: the lab note.
- [ ] `NOTES.md` entries; commit with full messages.

---

## What this plan does not decide

- The belief model and the sampled-belief search (§2, §3 of the design doc):
  they need the simulator, and this plan builds the simulator.
- The drift and pre-flight systems: the interface is general, but only one
  game is ported here.
- Whether the observation is stored per row: the container supports it
  (`Traits::kObsHistory`), and the Beacons system declares it off, because
  200 rows of a 128×128×6-plane observation is 322 GB at batch 4096.
