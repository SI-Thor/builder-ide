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
* A **learned-peak history**: every *clean* lease run records the peak it
  reached, so a later `--peak auto` uses the p95 of what that label really
  costs. A no-op run (exit 0 in milliseconds) or a failed run records
  nothing — see "What it stubs".
* A **presence queue**: work that is registered and runs when the box has
  room for it, and gives way when live work arrives.
* A **time ledger**: where the box's time went, by tier and by label, what
  the flow signal said, and why it was idle.
* A **model-server registry** (`thor-admit serve`): a model loaded once
  per box, not once per seat — keyed on the model file and the serving
  flags, not on the name a seat types.
* A **guard** for work that took **no lease**: the daemon can stop the
  biggest unleased process when the box is in trouble, and `thor-admit exec`
  refuses to start a framework that takes the box's memory by surprise
  (round 12; see below).

## Using it

```bash
# the daemon (run it under your own supervisor, or in a terminal)
cargo run --release -- daemon

# take a lease and run something under it
thor-admit run --peak 40G --label trellis -- python3 my_generator.py

# a shared model server: the first ask starts it under a lease, the second
# gets the same port back and runs nothing. Keyed on the model file
# (path + hash) and the command's other flags, so the same model under any
# name is one server, and a variant only when its flags really differ.
thor-admit serve d1-2B --port 8100 -- llama-server -m /models/d1-2B.gguf --port 8100 ...

# what is running, what is waiting, and how much memory is free
thor-admit status

# what the daemon has learned about each label
thor-admit peaks

# make a running daemon re-read its history and its presence queue
# (after an edit by hand; SIGHUP does the same)
thor-admit reload

# the work changed phase: give the difference back while the lease runs.
# A shrink is always allowed (never below what the run has touched); a grow
# is refused if the box has no room for it.
thor-admit phase trellis --peak 8G

# start something WITHOUT a lease — and refuse to start a framework that
# takes the box's memory by surprise (JAX/XLA, TensorFlow)
thor-admit exec -- python3 train_spike.py --backend mjx --nworld 256
```

`thor-admit run` puts the lease's id in the command's environment as
`THOR_ADMIT_LEASE`, so a workload can phase itself without knowing its
own id:

```bash
thor-admit run --peak 40G --label trellis -- bash -c '
  load_weights                       # the heavy part
  thor-admit phase "$THOR_ADMIT_LEASE" --peak 8G   # give the rest back
  render_scene'
```

From Python:

```python
from thor_admit import lease, phase

with lease("40G", "trellis"):
    ...the heavy work...

with lease("auto", "trellis"):     # the p95 of this label's own history
    ...the same work...

with lease("8G", "sweep", tier="study"):   # booked to the study tier
    ...the box's own background work...

with lease("40G", "trellis") as held:
    ...the heavy work...
    phase(held, "8G")                    # the work changed phase: give
                                          # the difference back at once
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

A job registered with `--disabled` stays in the queue and never runs: the
shape an example or a held-over job takes (`presence add --disabled`).

The queue is a file (`~/.local/state/thor-admit/presence.json`), so it
survives the daemon and can be edited by hand. The daemon re-reads it when
it changes. **The daemon does not decide what is worth doing** — the queue
is empty until somebody registers work, and `presence.default.json` beside
this README carries three *examples* (the cheapest three of the
`PRESENCE-JOBS.md` proposal, disabled, with the command a placeholder): a
starting point to copy, not a decision the daemon made. The night runner
owns the content. A job whose command cannot start at all is marked
`failed`, once, rather than retried every tick.

The queue file's format is one JSON object per line: `cp presence.default.json
~/.local/state/thor-admit/presence.json` installs the examples.

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
seconds each tier ran, the seconds each **label** ran (the players, not
just the bands — `by_label`), the GPU's power and busy share, the CPU's
busy share per core, the **flow signal** a publisher wrote (below), and
the idle time broken into **causes**:

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

### The flow signal: recorded, never computed

Whoever runs the box's work — the reflex, the mediator, the night runner —
may publish a small JSON object to `~/.local/state/thor-admit/flow.json`:

```json
{"confidence": 0.87, "rate_of_change": 0.02}
```

The daemon reads it when it changes and keeps it in the hour (the `flow`
section: the confidence's mean and minimum, the rate's mean, the samples,
and the sign at the end — `steady` or `faded`, a recording convention, not
a trigger). **The daemon computes none of it and decides nothing from it.**
An hour in which nobody published has `flow.samples: 0`, so "nobody is
publishing" and "the signal faded" stay two different sentences. Whether
the steady window is the moment for a keyframe or a mediator call is the
mediator's decision, made where the confidence came from.

## The rules, in one paragraph

A lease **reserves** the peak it was given. The daemon admits a lease only
if `available - peak >= floor` (the floor is 25 GiB by default), where
`available` is `MemAvailable` from `/proc/meminfo` *minus* what the running
leases still owe — a lease that reserved 40 GiB and has used 2 GiB so far
still owes 38 GiB. When the label has held device memory before and
something can see the GPU's allocation pool, the pool must also have room
for what the label historically held on the device (`--gpu-floor`, default
0 — `tegrastats`' `lfb` is a contiguous-block figure, not GPU headroom, so
the pool's floor is off unless the operator asks for it; a lease that
promises no device memory never waits for the pool at all). The queue is
first in, first out, with priorities in front — and when the head
**cannot fit at all**, a waiter behind it may pass it, under the rules
below, because a queue that waits for a head that will not fit is a queue
that does nothing. If the box ever falls
below the emergency floor (8 GiB), the watchdog **terminates** the largest
admitted lease's process group — it never merely stops it, because with no
swap a stopped process keeps every page it took; `SIGKILL` follows a grace
period if the process somehow survives. On top of that, the **presence
queue** runs registered work when no live request is waiting, and gives
it back the moment live work needs the memory or the GPU. While a client
holds a lease it heartbeats every 5 s; a client that goes silent past
`--heartbeat-grace-secs` (default 60 s) is asked to leave, and a lease
whose lock outlives its client is taken back. A process that took **no lease** is outside all of that, so the daemon
keeps a second guard for it: the biggest unleased process is stopped when
the box falls below the emergency floor, or when the box loses memory faster
than the leases can explain it (the shape the 2026-11-01 JAX incident had),
and the guard never touches the desktop, the login, the system's own services
or the seat agents. If the daemon goes away
while a client is queued, the client reconnects and asks again rather
than losing its wait — and auto-starts a daemon if nothing answers; a
daemon that never begins serving within `--startup-timeout-secs`
(default 15 s) stops itself so its socket is free for the next start.
When a lease ends, its peak **teaches** the history only if the run
exited 0 and lasted at least 5 s — a no-op's megabytes never lower a
reserve — and an over-running lease is written down while it still runs,
which can only raise one. The history and the presence queue live in
files the operator can edit; `thor-admit reload` (or `SIGHUP`) makes a
running daemon see the edit without a restart.

## When the head cannot fit

On 2026-11-01 the box's queue was not slow, it was stuck: a 58 GiB
request at the head, 35 GiB free above the floor, and nineteen waiters
behind it — none of them admitted, because strict FIFO only ever looks
at the head. Three rules fix that shape.

**Backfill.** A waiter behind a head that does not fit may be admitted
instead, when it *cannot delay the head's earliest possible start*: the
head's start is bounded by when the memory it waits for can exist, and a
smaller request that fits now does not move that moment. The daemon does
not guess — without an estimate of the head's start, nothing passes it.
The head's protection is bounded too (`--backfill-max-head-wait`,
default **1800 s**), after which the queue is plain FIFO again.
`--no-backfill` turns the rule off.

The guarantee: **a backfilling policy never starts the blocking head
later than strict FIFO did.** It is checked in the suite and again by
the replay (§ "the measurements in the lab record").

**Coalescing.** Two asks for the *same model* that are waiting side by
side become **one waiter and one promise**. The key is the model file
and the command's flags — the same key the shared-server registry uses
— so the second ask for a model that is still starting is told which
lease holds it, reads the leader's port from the registry when it
answers, and starts no server of its own. (The registry answers "is
there a server for this model?" once one is *up*; the coalesce key
answers "is another ask for this model *waiting*?", which is the window
before there is one.)

**Phase.** A lease that reserved far above what it uses is holding the
box hostage. `thor-admit phase` changes a running lease's reservation:
a **shrink** is always allowed and is charged back at once (never below
what the run has already touched); a **grow** is refused if the box has
no room for it, and the lease keeps the promise it has.

The daemon does not shrink a lease by itself — the work may spike
later, and only the workload knows. It **names** the lease: a lease
holding at least four times both its label's learned peak and its own
measured peak, with 8 GiB of the promise still owed, for five minutes,
is logged as `lease.overreserved` and marked **over-reserved** in
`thor-admit status`, with the peak it would fit in. The holder then
answers, by id:

```bash
thor-admit phase <label-or-id> --peak auto   # settle at the label's learned peak
```

## The guard: work that is outside any lease

Every rule above reaches work that **took a lease**. On 2026-11-01 a JAX run
started outside `thor-admit` took **94.5 GB of this box's unified memory in
20 seconds** — the desktop died, the Wi-Fi driver died, and the box needed a
power cycle — and the daemon, running at the time, saw nothing: a process
with no lease is in no lease table. It is also worth saying *why* the old
rule could not have helped: the run left **15 GB free**, which is above the
8 GiB emergency floor, so the floor's rule called the box healthy while the
desktop was already gone.

Two halves answer that.

### Before it starts: `thor-admit exec`

It reads the command line and refuses to start a framework that takes the
box's memory by surprise:

```bash
thor-admit exec -- python3 train_spike.py --backend mjx --nworld 256
# thor-admit: refusing to start a JAX/XLA process without a safe allocator.
#   found: the script train_spike.py imports it
#   why:   on this box the GPU's memory is the system's memory, and this framework
#          preallocates 75-90% of it before it computes anything. That is what
#          hung the Thor on 2026-11-01: 94.5 GB in 20 seconds, the desktop died,
#          the Wi-Fi driver died, and the box needed a power cycle.
#   make it safe with one of: XLA_PYTHON_CLIENT_PREALLOCATE=false or
#          XLA_PYTHON_CLIENT_ALLOCATOR=platform or XLA_PYTHON_CLIENT_MEM_FRACTION=0.15
#     or run it under a lease, which is the rule for heavy work:
#       thor-admit run --peak 16G --label jax -- python3 train_spike.py ...
```

JAX/XLA is safe when `XLA_PYTHON_CLIENT_PREALLOCATE=false`, or the platform
allocator, or a memory fraction of at most 0.15; TensorFlow when
`TF_FORCE_GPU_ALLOW_GROWTH=true`. The framework is found by the module it
runs (`python -m jax...`), by the code given to `-c`, or by what the script
on disk imports — the incident's script was called `train_spike.py` and said
nothing; its `import jax` said everything. **`jaxlib` is not `jax`**: the
match is on the import statement, not on the word, and importing the
compiler library allocates nothing. `--allow-preallocation` overrides the
refusal and says so loudly.

### After it starts: the guard

The daemon looks at every process on the box every `--guard-interval-ms`
(2 s) and can stop the biggest one that **no lease owns**:

* a **candidate** is a process that holds at least `--guard-min-rss` (4 GiB)
  of the box — its resident set *plus* the bytes the driver says it holds on
  the GPU — that no lease owns, and that is on neither protection list;
* the **built-in protection list** is by name: the login (`sshd`), the
  desktop (`gnome-*`, `gdm-*`), the session's services (`dbus-*`, `pipewire`,
  `ibus-*`), the system's own services (`systemd-*`, `NetworkManager`, …)
  and the seat agents (`zcode-cli`, `minimax-code`, `MainThread`). An
  interpreter is deliberately **not** protected: on this box a `python` is
  the model server, the incident's runaway, a seat's script or a one-liner,
  and a name cannot tell them apart;
* the **operator's list** is matched against the **command line**
  (`--guard-protected-file`, default `<state-dir>/protected.txt`):

```text
# one pattern per line. A pattern with a * is a glob, without one a substring.
*glide.server*
llama-server
pid 4321
```

  It is the escape hatch for work that is legitimately big and legitimately
  outside a lease: the model server is `python -m glide.server`, and every
  other python on the box is `python` too.

The guard has **two triggers**:

* **the floor** — below the emergency floor (8 GiB) the biggest holder is
  where the memory is, and if that is an unleased process it is stopped;
* **the runaway** — the box loses `--guard-drop` (8 GiB) inside
  `--guard-window-secs` (10 s) and the leases cannot explain it. This is the
  trigger the incident needed: the JAX run left **15 GB free**, above the
  floor, with the desktop already dead.

A candidate is stopped with **SIGTERM**, and with **SIGKILL** after the
grace if it is still there. It is signalled together with the processes it
started, and its group is signalled only when the group is exactly that
family — the operator's shell is never taken with it. `SIGCONT` goes with
the signal: a process the GPU pre-emption froze never sees its `SIGTERM`,
and the memory never comes back.

Everything the guard does is in the log (`guard.terminated`, `guard.killed`,
`guard.gone`, `guard.unexplained_drop`) and in the status:

```bash
thor-admit status --json | jq .guard
```

`--no-guard` turns the whole thing off.

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
    the_ledger_names_each_label_and_keeps_the_published_flow \
    the_ledger_names_the_idleness

# the learning rule: a no-op cannot teach, and a reload sees an edit
cargo test --test integration -- --nocapture \
    a_no_op_run_cannot_teach_the_reserve \
    a_sighup_reload_drops_what_the_operator_removed

# the shared-model registry, keyed on the model file rather than the name
cargo test --test integration -- --nocapture \
    a_model_is_loaded_once_per_box \
    the_same_model_under_two_names_is_loaded_once

# the GPU's pool: a lease with a device-memory promise waits for it, and
# a CPU-only lease does not
cargo test --test integration -- --nocapture \
    a_lease_waits_when_the_gpus_own_pool_is_thin \
    a_cpu_only_lease_is_not_held_by_the_gpus_pool

# the startup order: a daemon that hangs on the way up cannot wedge the
# socket, and one that never serves stops itself
cargo test --test integration -- --nocapture \
    a_daemon_that_hangs_on_the_way_up_does_not_wedge_the_socket \
    a_daemon_that_never_serves_stops_itself \
    a_queued_client_rides_out_a_daemon_restart

# the queue when the head cannot fit: backfill, coalescing, phase
cargo test --test integration -- --nocapture \
    a_small_request_backfills_past_a_blocked_head \
    the_heads_wait_bound_closes_the_backfill_window \
    two_identical_serve_asks_waiting_side_by_side_become_one_waiter \
    a_phase_shrink_frees_the_room_the_queue_is_waiting_for \
    a_phase_grow_that_does_not_fit_is_refused \
    a_lease_that_holds_far_more_than_it_uses_is_named_in_the_status

# the replay: the day's real queue under each policy, and the model's own
# error against what really happened
cargo run --release --example replay -- \
    ~/.local/state/thor-admit/daemon.log ~/lm-tools/thor-admit-daemon.log \
    --history ~/.local/state/thor-admit/peaks.jsonl --pid 956421 --floor 25G

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
* **The guard does not stop work under a lease.** A lease is the lease
  watchdog's business: it knows how to stop that work, how to wait for it and
  how to give the memory back to the accounting. The guard's business is the
  work nobody claimed — and it will not touch the desktop, the login, the
  system's own services, the seat agents, or anything on the operator's
  list, whatever their size.
* **The guard is a last resort, and it can be wrong.** It answers a runaway by
  stopping the biggest process it may touch, and on a busy box that may be a
  seat's unleased job that was doing the right thing. The operator's list is
  the answer to that, and `--no-guard` is the other one.
* **`thor-admit exec` is a refusal, not a sandbox.** It reads the command
  line; a program that preallocates without naming its framework on the
  command line still gets through, and the guard is what is left.
* **It does not reserve memory for the kernel's reclaim.** The floor is a
  number the operator sets; the default (25 GiB) is the stopgap's "keep
  25 GB free", carried forward.
* **It does not know about swap.** The rule is `MemAvailable`, which the
  kernel already accounts for the swap against, so the daemon does not
  reserve for the swap and does not read it. (There **is** swap on the
  box now — 47 GiB, added after the brief was written — so a workload
  that overruns its promise is now paged rather than killed at once.
  The floor still means what it says: `MemAvailable` must stay above it.)
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
* **A no-op run cannot teach.** Measured on this box (2026-11-01): 25
  no-op records — each under 30 ms, under 4 MB — sat in the history of
  `infinigen.mountain.coarse`, and the next `--peak auto` reserved
  **3.6 MB** for a job that was using 1.3 GiB. Now a run teaches only if
  it **exited 0** (the client reports its exit status on release) and
  **lasted at least 5 s**; the filter applies to what is written *and* to
  what is read, so records like that in an old file are ignored however
  many there are. The one exception is the over-run record, which is
  written while a lease is past its reservation and can only raise a
  reserve. A model server that never exits cleanly (a seat stops it with
  a signal) keeps its explicit `--peak` — over-reserving is the safe
  direction — until one run finishes on its own.
* **The daemon's memory is not the file.** The history and the presence
  queue are loaded once; an edit made by hand reaches a running daemon
  only through `thor-admit reload` or `SIGHUP`. Both re-read the files and
  touch nothing that is running.
* **The GPU's view is partial.** The Thor's memory is unified: there is no
  separate VRAM pool. `nvidia-smi`'s per-process accounting works and is
  used for the GPU peak; `nvidia-smi --query-gpu=memory.used` answers
  `N/A`, so the device/pinned *split* of the non-swappable pool cannot be
  seen. `tegrastats` gives the Tegra's own RAM figure and its `lfb` —
  the pool's *contiguous* free blocks, a fragmentation signal rather than
  GPU headroom, which is why `--gpu-floor` defaults to 0 and why a lease
  that promises no device memory skips the pool rule (measured
  2026-11-01: a 2 GiB default on `lfb` held 21 requests for over an hour
  while ~100 GiB was available). See `docs/design/thor-admit.md`
  §"What the GPU exposes" and §14.
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
JSON-lines log), `ledger.jsonl` (the hours, by tier and by label),
`presence.json` (the registered work), `flow.json` (the flow signal, when
a publisher writes one), `servers.json` (the shared model servers), and
`leases/` (the lock files).
