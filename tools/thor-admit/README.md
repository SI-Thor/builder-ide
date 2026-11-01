# thor-admit

A memory-admission daemon for the Thor: the first Rust component in
builder-ide.

The box has **122 GiB of unified memory and no swap**. Several seats can run
heavy work at once, and until this crate existed nobody but the operator
knew how much was already committed. At 13:22 on 2026-10-31 (the box's
own clock, AKDT) the box hit a global OOM: TRELLIS at 55–68 GB, FP4 GEMM
sweeps, llama-servers, motion training and Infinigen sweep workers, all
at once. The OOM killer took the small services first
(`oom_score_adj=200`), not the hogs.

This is the admission controller that replaces the `flock ~/lm-wt/heavy.lock`
stopgap.

## What it is

* A small resident **daemon** (user-level; no systemd unit is installed or
  enabled — one is *documented* in `docs/design/thor-admit.md`).
* A **CLI** that takes a lease, runs a command under it, and gives the lease
  back — including when the command is killed, or when the client itself
  dies.
* A **Python shim** (`thor_admit.lease`) for work that is already a Python
  process.
* A **learned-peak history**: every lease records the peak it reached, so a
  later `--peak auto` uses the p95 of what that label really costs.

## Using it

```bash
# the daemon (run it under your own supervisor, or in a terminal)
cargo run --release -- daemon

# take a lease and run something under it
thor-admit run --peak 40G --label trellis -- python3 my_generator.py

# what is running, what is waiting, and how much memory is free
thor-admit status

# what the daemon has learned about each label
thor-admit peaks
```

From Python:

```python
from thor_admit import lease

with lease("40G", "trellis"):
    ...the heavy work...

with lease("auto", "trellis"):     # the p95 of this label's own history
    ...the same work...
```

## The rules, in one paragraph

A lease **reserves** the peak it was given. The daemon admits a lease only
if `available - peak >= floor` (the floor is 25 GiB by default), where
`available` is `MemAvailable` from `/proc/meminfo` *minus* what the running
leases still owe — a lease that reserved 40 GiB and has used 2 GiB so far
still owes 38 GiB. The queue is first in, first out, with priorities in
front. If the box ever falls below the emergency floor (8 GiB), the
watchdog stops the **largest admitted lease's** process group — never the
box's own services, and never a lease too small to be the cause.

## Running the tests

```bash
# the unit tests (fast, no memory)
cargo test --lib

# the integration run: synthetic hogs on the CPU only
cargo test --test integration -- --test-threads=1

# the low-water mark: the watchdog stops a hog before the box is in
# trouble (the memory curve is scripted, the watchdog is real)
cargo test --test integration -- --test-threads=1 --nocapture \
    the_watchdog_stops_a_runaway_before_the_memory_runs_out

# the two heavy tests, which take the box's own heavy lock first.
# They skip themselves when another seat holds it; set the wait to join
# the queue instead of skipping.
THOR_ADMIT_HEAVY_WAIT_SECS=1800 cargo test --release --test integration -- \
    --test-threads=1 --nocapture three_thirty_gigabyte_hogs_are_serialised \
    the_watchdog_stops_a_runaway_before_the_kernel_oom_does
```

The Python shim's tests live with the repo's suite:

```bash
.venv/bin/python -m pytest tests/thor_admit -q
```

**The GPU's peak column**, with a real GPU context (the test hogs are CPU
only, so the driver says nothing about them):

```bash
nvcc -O2 -o /tmp/cuda_probe tests/cuda_probe.cu
/tmp/cuda_probe --mib 512 --hold 12 &          # a real context, 512 MiB
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits
# 163916, 614
```

Run the same probe under a lease and the daemon writes the driver's own
number for it: `peak_gpu_bytes: 643825664` (614 MiB).

## What it stubs, and what it does not do

* **It does not install anything.** No systemd unit, no system packages.
  The daemon is a user-level process; `docs/design/thor-admit.md` carries a
  unit for the operator who wants one.
* **It does not replace the box's services.** `thor-index`, `gpu-queue` and
  the desktop are not leases and are never signalled by the watchdog.
* **It does not reserve memory for the kernel's reclaim.** The floor is a
  number the operator sets; the default (25 GiB) is the stopgap's "keep
  25 GB free", carried forward.
* **It does not know about swap.** There is none.
* **`--meminfo` is a test seam, not an operating knob.** It says where the
  daemon reads the box's memory accounting from; it is `/proc/meminfo` in
  production and it should stay that way. Point the daemon at anything
  else and the watchdog is watching a number the kernel is not using. The
  daemon logs the path it is reading in `daemon.started`, so a stale file
  cannot hide.
* **It cannot finish a kill it never started.** If the daemon is killed
  between the watchdog's `SIGSTOP` and the `SIGTERM` two seconds later,
  the stopped process stays stopped — a stopped process holds its memory
  and never sees its `SIGTERM`. The daemon logs every stop and every
  kill, and `thor-admit status` shows the lease. A lease that ends
  *normally* while stopped is handled: the release path sends `SIGTERM`
  and then `SIGCONT`.
* **The GPU's view is partial.** The Thor's memory is unified: there is no
  separate VRAM pool. `nvidia-smi`'s per-process accounting works and is
  used for the GPU peak; `nvidia-smi --query-gpu=memory.used` answers `N/A`.
  `tegrastats` gives the Tegra's own RAM figure and the largest free block.
  See `docs/design/thor-admit.md` §"What the GPU exposes".

## Licences

This crate is MIT, like the repo. Its dependencies are all MIT OR
Apache-2.0, from crates.io:

| Crate | Version | Licence | Why |
|---|---|---|---|
| `libc` | 0.2 | MIT OR Apache-2.0 | `flock(2)`, `fork`/`execvp`/`wait4`, `kill(2)`, `signal(2)` |
| `serde` | 1 | MIT OR Apache-2.0 | the socket protocol's types |
| `serde_json` | 1 | MIT OR Apache-2.0 | the socket protocol's JSON |

No model weights, no data licences, nothing installed system-wide.

## What it costs

Measured on this box with the release build, 30 s windows, the box busy
with a seat's work (`MemAvailable` 105.9 GiB, load 6.0):

| | |
|---|---|
| Resident memory | **2 MiB** |
| CPU, doing nothing | **0.03% of one core** |
| CPU, one lease running | **1.1% of one core** |
| Samples | 4.00 a second (the daemon's own counters) |

## How it fits with the rest

| Piece | Relationship |
|---|---|
| `core/night/cost` | reads this crate's peak history as the cost model's **memory column** (`core/night/cost/memory.py`) |
| the seats | take a lease with the CLI or the Python shim instead of `flock ~/lm-wt/heavy.lock` |
| the night runner | the per-model load cap (core-spec §1.9) is the same idea one level up: admission before spend |

The daemon's own state lives in `~/.local/state/thor-admit/` (override with
`--state-dir`): `peaks.jsonl` (the learned peaks), `daemon.log` (its own
JSON-lines log), and `leases/` (the lock files).
