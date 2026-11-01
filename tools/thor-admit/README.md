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
* A **presence queue**: work that is registered and runs when the box has
  room for it, and gives way when live work arrives.
* A **time ledger**: where the box's time went, by tier, and why it was
  idle.
* A **model-server registry** (`thor-admit serve`): a model loaded once
  per box, not once per seat.

## Using it

```bash
# the daemon (run it under your own supervisor, or in a terminal)
cargo run --release -- daemon

# take a lease and run something under it
thor-admit run --peak 40G --label trellis -- python3 my_generator.py

# a shared model server: the first ask starts it under a lease, the second
# gets the same port back and runs nothing
thor-admit serve d1-2B --port 8100 -- llama-server -m d1-2B --port 8100 ...

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

with lease("8G", "sweep", tier="study"):   # booked to the study tier
    ...the box's own background work...
```

## The presence queue: the box's own useful work

The box is not idle because nobody asked it to be busy. It is idle because
the useful work was never registered. The presence queue is that
registration:

```bash
# register work that runs when the box has room for it
thor-admit presence add --tier study --peak 8G --label infinigen-sweep \
    --resumable -- python3 sweep.py

# what is registered, and what it is doing
thor-admit presence list

# take it out again
thor-admit presence remove 1
```

A presence job is a **command**, a **tier**, an **estimated peak** and a
**resumability flag**. The rules:

* It runs only when **no live request is waiting** — the live queue has
  head-of-line blocking, and background work must not make a live request's
  wait longer.
* Its memory is **charged like any lease**, so a job that promised 30 GiB
  and used 2 GiB so far still owes 28 GiB. That is what makes the
  pre-emption exact.
* It is **pre-empted** by live work, in two different ways, because memory
  and GPU time are different things:

| | the trigger | the signal | what it costs |
|---|---|---|---|
| **memory** | a live lease is waiting and does not fit | `SIGTERM` | the work stops and is started again later |
| **GPU** | a live lease is running and the GPU is busier than `--gpu-busy-threshold` | `SIGSTOP` | the work pauses and is continued when the live work is done |

A pre-empted job that is marked `--resumable` goes back in the queue and
runs again when there is room; one that is not stays put.

The queue is a file (`~/.local/state/thor-admit/presence.json`), so it
survives the daemon and can be edited by hand. The daemon re-reads it when
it changes.

## The tiers

Every lease says what kind of work it is. The tier is the accounting band
the ledger books the seconds to, and it is the permission to pre-empt:
only **live** work may take the box back from the presence queue.

| Tier | What it is |
|---|---|
| **live** | nights, previews, first-mile requests |
| **preparation** | pre-generating likely-needed assets, refreshing keyframes |
| **practice** | retraining choosers, recalibrating confidence, replaying proposed changes |
| **study** | the Infinigen sweep, hardware experiment batches, parity suites |

A lease that does not say is **live**, so every client that predates the
tiers keeps working unchanged.

## The ledger: where the box's time went

```bash
thor-admit ledger            # the hours, by tier
thor-admit ledger --json
```

One JSON line per hour in `~/.local/state/thor-admit/ledger.jsonl`: the
seconds each tier ran, the GPU's power and busy share, the CPU's busy share
per core, and the idle time broken into **causes**:

| Cause | What it means |
|---|---|
| `no_work_registered` | nothing was registered to do, and nothing was asked for |
| `waiting_for_memory` | work was ready, but the box had no room for it |
| `waiting_for_gpu` | work was ready, but the GPU was busy with higher-priority work |
| `preempted_for_live_work` | work was stopped so live work could run |
| `granted_not_run` | a lease was granted — the memory committed — but the client never held it, so no work ran |
| `unattributed` | the ledger cannot say — this is the number that should be zero |

`no_work_registered` is a *cause* but not a good one: it is the presence
gap. It is reported on its own, so that "the ledger explains everything"
and "the box had nothing to do" stay two different sentences.

## The rules, in one paragraph

A lease **reserves** the peak it was given. The daemon admits a lease only
if `available - peak >= floor` (the floor is 25 GiB by default), where
`available` is `MemAvailable` from `/proc/meminfo` *minus* what the running
leases still owe — a lease that reserved 40 GiB and has used 2 GiB so far
still owes 38 GiB — and only if the GPU's own allocation pool
(`tegrastats`' `lfb`) has room above its own floor (2 GiB by default) for
what this label has historically held on the device. The queue is first
in, first out, with priorities in front. If the box ever falls below the
emergency floor (8 GiB), the watchdog **terminates** the largest admitted
lease's process group — it never merely stops it, because with no swap a
stopped process keeps every page it took; `SIGKILL` follows a grace
period if the process somehow survives. On top of that, the **presence
queue** runs registered work when no live request is waiting, and gives
it back the moment live work needs the memory or the GPU. While a client
holds a lease it heartbeats every 5 s; a client that goes silent past
`--heartbeat-grace-secs` (default 60 s) is asked to leave, and a lease
whose lock outlives its client is taken back.

## Running the tests

The integration suite is **serial by default**: every test holds a
one-at-a-time gate, which is also the fair way to treat a box other seats
are using (measured: 7 of 14 failed in parallel at load ~38 before round
8; see `docs/design/thor-admit.md` §12.2). `THOR_ADMIT_PARALLEL_TESTS=1`
opens the gate for a deliberate parallel run.

```bash
# the unit tests (fast, no memory)
cargo test --lib

# the integration run: synthetic hogs on the CPU only
cargo test --test integration

# the presence queue and the ledger
cargo test --test integration -- --nocapture \
    a_presence_job_runs_when_the_box_has_room \
    a_live_lease_preempts_a_presence_job \
    the_ledger_books_the_time_by_tier \
    the_ledger_names_the_idleness

# a smoke test of the CLI, end to end (light: it allocates nothing)
python3 smoke-cli.py

# the measurements in the lab record
python3 measure-presence.py

# the low-water mark: the watchdog terminates a hog before the box is in
# trouble (the memory curve is scripted, the watchdog is real)
cargo test --test integration -- --nocapture \
    the_watchdog_stops_a_runaway_before_the_memory_runs_out

# the two heavy tests, which take the box's own heavy lock first.
# They skip themselves when another seat holds it; set the wait to join
# the queue instead of skipping.
THOR_ADMIT_HEAVY_WAIT_SECS=1800 cargo test --release --test integration -- \
    --nocapture three_thirty_gigabyte_hogs_are_serialised \
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
  between the watchdog's `SIGTERM` and the `SIGKILL` escalation, the
  `SIGTERM` stands: the client reaps its child, releases the lease and
  exits on its own. What the daemon cannot finish is a client that
  ignores both signals — that lease waits until the daemon is back. The
  daemon logs every termination and every kill, and `thor-admit status`
  shows the lease.
* **`--peak auto` will not guess.** A label needs three runs of history
  before `auto` is allowed: a p95 of one or two runs under-reserves a
  shifted workload, and on a box with no swap that arrives at the
  emergency floor with the watchdog already late. Give an explicit
  `--peak` until the daemon says otherwise; once the history is there,
  `auto` reserves the larger of the p95 and the last run.
* **The GPU's view is partial.** The Thor's memory is unified: there is no
  separate VRAM pool. `nvidia-smi`'s per-process accounting works and is
  used for the GPU peak; `nvidia-smi --query-gpu=memory.used` answers
  `N/A`, so the device/pinned *split* of the non-swappable pool cannot be
  seen. `tegrastats` gives the Tegra's own RAM figure and the largest
  free block — and that `lfb` is what the `--gpu-floor` rule is applied
  to. See `docs/design/thor-admit.md` §"What the GPU exposes".
* **The heartbeat is a lease-scope promise, not a health check.** The
  daemon learns only that the client's process is alive; it cannot tell a
  client that is computing from one that is spinning. The grace period
  (`--heartbeat-grace-secs`, default 60 s) is set for a client heartbeat
  every 5 s on a loaded box, not for a slow application.
* **The presence queue does not know what a job is.** It runs a command and
  holds a lease to its peak; it does not know whether the command can pick
  up where it left off. That is what the `--resumable` flag is for: it is a
  promise by whoever registered the job, and the daemon believes it.
* **A pre-empted presence job starts again from the beginning.** The daemon
  re-runs the same command; the command's own checkpoint is what makes the
  run a *resume* rather than a restart.
* **The ledger's GPU busy share comes from the driver, not from
  `tegrastats`.** This Thor's `tegrastats` prints no 3D busy percentage, so
  the busy share is `nvidia-smi --query-gpu=utilization.gpu`; the *power*
  figure is `tegrastats`' own `VDD_GPU` rail. The ledger records which
  source each figure came from.

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

Measured on this box with the release build, 30 s windows. The box was busy
with a seat's work when the presence scheduler and the ledger were on
(`MemAvailable` 48.5 GiB, load 16.25 / 16.33 / 16.17, 21:43 AKDT on
2026-10-31):

| | idle | one lease and one presence job |
|---|---|---|
| Resident memory | **2 304 KiB** (2.25 MiB) | **2 560 KiB** (2.50 MiB) |
| CPU, its own | **0.20 % of one core** | **0.80 % of one core** |

Before the presence scheduler and the ledger were added, on the same box
but earlier in the evening (`MemAvailable` 105.9 GiB, load 6.04 / 6.58 /
7.67, 16:26 AKDT): **2 MiB** and **0.03 %** of a core idle, **1.1 %** with
a lease. The extra is the ledger: a sample every 250 ms, the CPU's
counters once a second, and the GPU's children read every tick instead of
every eighth one — the ledger wants the GPU's power and busy share even
when the box is doing nothing, and it cannot be read after the fact.

The two measurements are not directly comparable (the box's load was
twice as high in the second one), so the honest reading is: the ledger
costs a few hundred KiB and a fraction of a core, and the box's own noise
is bigger than that.

Samples: 4.00 a second (the daemon's own counters).

## How it fits with the rest

| Piece | Relationship |
|---|---|
| `core/night/cost` | reads this crate's peak history as the cost model's **memory column** (`core/night/cost/memory.py`) |
| the seats | take a lease with the CLI or the Python shim instead of `flock ~/lm-wt/heavy.lock` |
| the night runner | the per-model load cap (core-spec §1.9) is the same idea one level up: admission before spend |
| the presence queue | the box's own work: it fills the hours the live leases leave, and the ledger says where they went |

The daemon's own state lives in `~/.local/state/thor-admit/` (override with
`--state-dir`): `peaks.jsonl` (the learned peaks), `daemon.log` (its own
JSON-lines log), `ledger.jsonl` (the hours, by tier), `presence.json` (the
registered work), `servers.json` (the shared model servers), and `leases/`
(the lock files).
