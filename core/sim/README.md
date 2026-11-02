# `core/sim` — the batched simulator: one interface, many rule systems

A **batch** is a set of independent worlds of one rule system, stepped
together on the GPU. This package is the interface the design names
([`docs/design/batched-sim.md`](../../docs/design/batched-sim.md) §1): a
fixed-size POD state per world, a legal-action mask written by the rules
engine, and observation planes from the acting player's point of view.

The point of the interface is that **the rule system is a directory, not a
branch**: a new system brings its state, its rules, its two backends, its
plane manifest and a Python reference, and nothing upstream changes shape.

```python
from core.sim import make_batch

batch = make_batch("beacons", num_envs=1024, rows=1, device="cuda", seed=7)
mask = batch.legal_action_mask()     # (num_envs, A) bool
obs = batch.obs()                     # (num_envs, C, H, W) float32
batch.apply_actions(actions)          # actions: int32 (num_envs,)
```

## What it owns

| file | what it owns |
|---|---|
| `state.h` | `template <class Traits> struct Batch` — the container |
| `kernels.h` | the kernel contract, the `Backend` vtable, the registry |
| `bindings.cc` | the pybind11 module `_pysim` |
| `registry.cc` | the registry itself |
| `systems/<name>/` | one rule system: state, rules, backends, manifest, reference |

## The rules that are not negotiable

They come from the Stratego port
([`docs/lab/exp-stratego.md`](../../docs/lab/exp-stratego.md) §4) and they are
the reason this interface is shaped the way it is:

- **Fixed-size state, no per-world allocation.** `sizeof(State)` is known at
  compile time; the batch is `rows × num_envs` states, row-major, the row
  stride is `num_envs`.
- **The mask is `num_envs × A` bools and it is written by the rules engine.**
  The policy gathers on it; it never re-derives legality.
- **Point of view is the caller's problem.** The observation is written from
  the acting player's point of view, so the plane list does not depend on who
  is acting.
- **Tensor lifetime is short and documented.** The backend reuses its
  buffers, so **every array the binding returns is a fresh copy**.
- **No float ever enters the state.** The state is integers, so the GPU and
  the CPU can be compared byte for byte.

## The kernel contract

Each system supplies five launches, over the same rules:

| kernel | parallelism | what it does |
|---|---|---|
| reset | one thread per world | the initial state, from the seed |
| step | one thread per world | one ply |
| mask | one thread per world | the legal-action mask |
| obs | one thread per (world, cell) | the observation planes |
| terminate | one thread per world | the reward and the terminated flag |

The CPU and the CUDA backend are two implementations of the **same** rules
header. That is the point: "the GPU agrees with the CPU" is then a property
of the backend, not of a second implementation that might drift.

## Building it

```bash
core/sim/build.sh
```

Needs the repo's venv (pybind11) and the CUDA toolkit at
`/usr/local/cuda-13.2`. The build has **no** `CMAKE_BUILD_TYPE` on purpose:
no `-DNDEBUG`, so the device-side asserts stay in and a bad kernel says so
instead of quietly corrupting a number.

The module is built next to the package, so `from core.sim import _pysim`
finds it. It is not committed (see `.gitignore`).

## Running its tests

```bash
.venv/bin/python -m pytest tests/sim -q
```

The equality gate (`tests/sim/test_beacons_equivalence.py`) runs the same
seed and the same actions through the Python reference, the CPU backend and
the CUDA backend, and compares the canonical byte encoding of every state
after every step.

## What it does not own

- **torch.** The arrays are numpy; `core.sim.to_torch` converts them with
  `torch.from_numpy` when a caller has torch. The shape contract is what
  the callers need, and torch is not installed on the Thor.
- **The observation history.** The container supports it
  (`Traits::kObsHistory`), and the Beacons system declares it off: 200 rows
  of a 128×128×6-plane observation is 322 GB at batch 4096.
- **The belief model and the search.** They are §2 and §3 of the design, and
  they need this simulator, not the other way round.
