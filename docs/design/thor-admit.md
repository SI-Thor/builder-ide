# DESIGN — thor-admit: admission before spend

Status: **implemented** (2026-10-31). This is the design of the memory
admission daemon for the Thor (`tools/thor-admit`), the first Rust component
in builder-ide. It does not supersede `docs/design/core-spec.md` (v2): it is
the *box's* admission controller, where the core spec's §1.9 per-model load
cap is the same idea one level up.

**Citation shorthand**

- **S** = `docs/design/core-spec.md` (v2) — §1.9 (the model registry, the
  per-model load cap, enforced at batch admission), §5.5 (the night's rails).
- **L** = `docs/lab/*` — the box's own measurements.
- **B** = the box, measured here and now.

---

## 0. The problem, measured

At 13:22 on 2026-10-31 the Thor hit a **global OOM** and rebooted. The
work that was running at the time:

| Work | Peak |
|---|---|
| TRELLIS.2 | 55–68 GB |
| FP4 GEMM sweeps | GPU-bound, large host memory |
| d1 llama-servers | several GB each |
| motion training | several GB |
| Infinigen sweep workers | several GB each |

122 GiB of **unified** memory, **no swap**, and no shared view of who had
committed what. The OOM killer took the small services first
(`oom_score_adj=200`: `thor-index`, `gpu-queue`) — the services that were
*not* the problem — because that is what `oom_score_adj` asks for.

The stopgap is `flock ~/lm-wt/heavy.lock` plus "keep 25 GB free". It works
until two things happen at once: the lock is coarse (one heavy thing at a
time, whatever it is), and it is **advisory** — it knows nothing about how
much memory the lock holder actually wants.

**The diagnosis is not a leak.** It is co-scheduling with no shared view of
memory.

## 1. What this is

A small resident daemon that owns the box's memory decisions, and a CLI (and
a Python shim) that takes a **lease** on memory before a heavy thing runs.

```
   seat A ─┐                        ┌─ lease 1: trellis  peak 40 GiB
   seat B ─┼─ thor-admit run … ─────┤
   seat C ─┘                        └─ lease 2: critic   peak  2 GiB
                    │
                    ▼
          thor-admit daemon (user-level, ~2 MiB RSS)
            · one picture of the box (MemAvailable + every lease)
            · one queue (FIFO, with priorities)
            · one watchdog (the box ran short → the biggest lease stops)
```

**The one sentence.** *A heavy thing may not start until the box has room
for it, and the box's memory is the only thing that counts.*

## 2. The rules

### 2.1 Admission

A lease **reserves** the peak it was given.

```
available = MemAvailable            (from /proc/meminfo, every 250 ms)
projected = available - Σ (reserved_i - current_i)
admit     ⟺ projected - peak >= floor
```

`current_i` is what lease *i* is using right now (measured from `/proc`);
`reserved_i` is what it promised. The difference is what the lease may
**still** take: a lease that reserved 40 GiB and has used 2 GiB so far still
owes 38 GiB, and the box only has room for what is left after every
running lease reaches its promise.

With no other lease this is exactly the plain rule the brief states,
`available - peak >= floor`. With several, it is the plain rule plus the
running leases' promises.

**Default floor: 25 GiB** — the stopgap's "keep 25 GB free", carried
forward. The floor is a *reservation* floor, not a "free memory" floor: it
is what the box keeps for everything that is not a lease (the desktop, the
seat's own tooling, the kernel's own pages).

**A second budget, with its own floor: the GPU's allocation pool.**
`MemAvailable` is the kernel's estimate of reclaimable memory, and it
cannot say how full or fragmented the *non-reclaimable* part is — the
`cudaMalloc` blocks and pinned host memory that stay put. A lease can fit
the memory rule and still fail its first `cudaMalloc` while the daemon
says there was room (Hy4's third failure mode). `tegrastats`' `lfb` — the
free blocks of the allocation pool, e.g. `lfb 7x4MB` — is the one number
on this box that can see it, so the rule applies it the same shape as the
memory rule, one floor deeper:

```
gpu_free = tegrastats' lfb             (None when nothing can see it)
admit    ⟺ gpu_free - label_gpu_peak >= gpu_floor      (--gpu-floor, default 2 GiB)
```

`label_gpu_peak` is the label's own learned device-memory promise (the
larger of the p95 and the last run of its `peak_gpu_bytes` history; zero
for a label that has never touched the GPU). With no view of the pool
there is no GPU rule — the memory rule is all the daemon has, and it stays
out of the way. The pool is logged beside the memory (`daemon.sample`,
`status`) and a waiter held by it alone is named once
(`lease.waiting_for_gpu_memory`) instead of sitting silently in a queue
that looks like a memory shortage. What the daemon still cannot see is
the *split* between device and pinned host bytes — `nvidia-smi
--query-gpu=memory.used` answers `N/A` on this box — so the pool rule
rides on `lfb` alone.

### 2.2 The queue

First in, first out; a **higher priority goes in front** of everything
waiting, and waiters of the same priority keep their arrival order. There is
head-of-line blocking: the head of the queue must fit before anything
behind it is considered. A box that is nearly full should not be filling
its last hole with the least important thing that happened to ask.

### 2.3 The watchdog

The daemon samples the box every **250 ms**. If `MemAvailable` falls below
the **emergency floor** (8 GiB by default), the watchdog acts on the
**largest admitted lease** — the one using the most memory right now:

1. **SIGTERM** its process group. On this box there is no swap, so a
   `SIGSTOP`ed victim keeps every page it took: `MemAvailable` would not
   move while it sat stopped, and the emergency would get worse during the
   very grace period that was supposed to help. Memory comes back only
   when the process is *gone* — so the stop-then-kill ladder became
   terminate-then-kill, and the memory is booked back when the client has
   reaped its child and released the lease, not before (Hy4's first
   failure mode; folded in on 2026-10-31).
2. If the box is still short after the grace period
   (`--stop-grace-samples`, 8 samples = 2 s) and the process is somehow
   still there, the watchdog escalates to **SIGKILL**.

The events are `watchdog.terminated` and (for the escalation)
`watchdog.killed`, and the first carries the reservation beside the RSS,
so an under-reserved victim is visible in the event itself.

**Two guards, both deliberate:**

* The box's own services (`thor-index`, `gpu-queue`, the desktop) are
  **not leases**. The watchdog's candidate set is exactly the admitted
  leases, so a service can never be a victim.
* A lease using less than **2 GiB** (`--min-victim-rss`) is not a
  candidate either: if the pressure is not coming from the leases, the
  daemon logs `watchdog.pressure_outside_leases` and does nothing. Killing
  an innocent small lease would not free the memory anyway.

The watchdog never signals the daemon's own process or process group.

### 2.4 Learned peaks

Every finished lease writes one JSON line to the history
(`~/.local/state/thor-admit/peaks.jsonl`):

```json
{"at":"2026-10-31T21:56:42Z","kind":"hog.8g","label":"hog.8g","host":"thor",
 "peak_rss_bytes":8591884288,"peak_gpu_bytes":null,"gpu_visible":true,
 "duration_s":1.19,"mem_total_bytes":131856928768,"floor_bytes":26843545600,
 "basis":"measured","source":"thor-admit","peak_source":"rusage"}
```

**But not every finished run teaches** (round 9). A record teaches a
future reservation only if the run **exited 0** — the client reports the
command's exit status on release — and **lasted at least 5 s**
(`history::MIN_LEARNED_DURATION_S`). The rule is applied twice, on write
and on read: a run that fails it is not written (`history.not_learned`
names it in the log, with the reason), and a record like it in an old file
is ignored however many there are. The one exception runs the safe way: an
**over-run** record (§ the over-run watch below) always teaches, because
it is written only past a gross over-reservation and can only raise a
reserve.

Why 5 s and exit 0, measured: on 2026-11-01 the history of
`infinigen.mountain.coarse` held 25 records, every one under 30 ms and
under 4 MB — wrapper invocations with nothing to do — and the next
`--peak auto` reserved **3.6 MB** for a job that was using 1.3 GiB at that
moment (the incident is a test,
`a_no_op_run_cannot_teach_the_reserve`). A run that dies mid-work has
half a peak, not the next run's cost; a run that lasts no time did no
work. A model server that never exits cleanly (a seat stops it with a
signal) keeps its explicit `--peak` — over-reserving is the safe
direction — until one of its runs finishes on its own.

`--peak auto` asks the daemon for the **larger of the p95 and the last
run** of that label's history, in the same percentile convention
`core/night/cost/model.py` uses (linear interpolation, NumPy's
convention). The p95 says what the label *usually* costs; the last run
says what it cost the last time the work looked like this one — and a
label whose last run overran its history is exactly the label a p95-only
reservation would under-reserve (Hy4's second failure mode).

A label with **no history is refused** with a clear reason rather than
guessed at, and so is a label with fewer than **three runs**: a p95 of one
or two runs is still a guess, and on a box with no swap an under-reserved
lease arrives at the emergency floor with the watchdog already late.

**The daemon's memory is not the file.** The history is loaded once; an
edit made by hand — the operator removed the 25 no-op records at 00:50
while the daemon kept them in memory — reaches a running daemon through
`thor-admit reload` or `SIGHUP`, both of which re-read the history and the
presence queue and touch nothing that is running. Before round 9 the only
way was a restart, and a restart waits for a box with no leases.

**The over-run watch.** While a lease runs, the daemon watches for it
passing its reservation. The first scan past `reserved + tolerance`
(2 % of the reservation, at least 128 MiB — a lease that reserved exactly
what it meant still measures a little over, its own runtime, and that is
not what the watch is about) logs `lease.underreserved` with the reserved
and the measured numbers, and writes the measured peak to the history *at
once*, so the next `auto` reserves it even if the run takes the daemon
with it. Each further 512 MiB of growth writes again.

The peak is the larger of two measurements: the kernel's own `rusage`
`ru_maxrss` for the command (exact) and the daemon's 250 ms samples (which
catch a lease that forks). The record says which one won (`peak_source`).

**This is the cost model's memory column.** `core/night/cost/memory.py`
reads these lines and turns them into the same band the model already
speaks — a p50 and a p95, with the sample count and the source beside them.

## 3. Why a client holds the lock

The daemon cannot tell a client that crashed from one that is still
working, unless the kernel tells it. So:

* The **client** takes an exclusive `flock(2)` on a per-lease file and
  keeps the descriptor open for as long as the lease lasts.
* The **daemon** watches by *trying* to take the same lock. If it gets it,
  nobody is holding it, the client is gone, and the lease is released.

Whatever killed the client — `SIGKILL`, a panic, the OOM killer — the
kernel drops the lock. **A dead client cannot leak a lease.**

Two tests hold that promise down: `a_lock_held_by_a_dead_process_is_free`
(the unit test: a process is killed outright, and the lock is free) and
`a_dead_client_cannot_leak_a_lease` (the integration test: a client is
`SIGKILL`ed without saying goodbye, and the daemon gives the memory back
on its own).

**One subtlety, measured.** A forked child inherits the descriptor until it
reaches its `exec`, and `O_CLOEXEC` only closes it there. So a lease can
outlive its client by about a millisecond if a fork happens at that
moment. The daemon polls every 250 ms, so it never notices; a test that
probes once can lose that race, so it waits.

**And the orphan.** A client that dies takes its command with it: the daemon
sends `SIGTERM` (then `SIGCONT`) to the lease's target, because an unwatched
30 GiB hog is exactly the thing this daemon exists to prevent.
`--no-stop-on-client-gone` turns that off.

**And the stuck client.** The lock says a client is not *dead*; it cannot
say the client is not *stuck* — a hung client's lock never drops, and its
reservation would be charged forever (Hy4's fourth failure mode). So the
lock has a partner: while the lease is held, the client **heartbeats**
(every 5 s, from its own thread and its own connection — the CLI's `run`
and the Python shim both do this), and the daemon holds a silent client to
`--heartbeat-grace-secs` (default 60 s: six missed beats plus slack for a
loaded box). The client's pid comes from the socket's own credentials
(`SO_PEERCRED` — the kernel's word, not the client's), which tells the two
failures apart:

* the client is **gone** but the lock is still held (an inherited
  descriptor): the lease is taken back at once (`lease.force_released`),
  and the lock file goes with it;
* the client is **there but stuck**: it is asked to leave (`SIGTERM`,
  logged as `lease.stale_client_signalled`), which drops the lock and
  releases the lease the honest way; if it is still stuck a grace period
  later, the lease is taken back anyway.

## 4. The protocol

JSON, one object per line, over a Unix socket (`$XDG_RUNTIME_DIR/thor-admit.sock`,
or `/tmp/thor-admit-<uid>.sock`). Small enough for a Python shim with no
dependency, and readable with `nc -U`.

**Client → daemon**

| Request | Meaning |
|---|---|
| `{"op":"acquire","label":"trellis","peak":42949672960,"priority":0,"tier":"live","target":{"group":{"pgid":1234}}}` | take a lease (`peak` may be `"auto"`, `tier` may be absent — it is `live`) |
| `{"op":"held","lease":7}` | the client holds the lock now: the lease is real |
| `{"op":"heartbeat","lease":7}` | the client is still alive and still holding (`held` counts as the first) |
| `{"op":"release","lease":7,"peak_rss_bytes":123456,"exit_code":0}` | the lease is over, and how the run finished (`exit_code` 0 is what lets the peak teach) |
| `{"op":"presence_add","label":"sweep","tier":"study","peak":8589934592,"resumable":true,"enabled":true,"command":["python3","sweep.py"]}` | register work in the presence queue (`enabled: false` registers it without running it) |
| `{"op":"presence_remove","id":3}` | take a job out of the presence queue |
| `{"op":"presence_list"}` | what is registered, and what it is doing |
| `{"op":"reload"}` | re-read the history and the presence queue (SIGHUP does the same) |
| `{"op":"ledger"}` | the hours, and the hour being kept now |
| `{"op":"status"}` / `{"op":"ping"}` | what is going on / is the daemon alive |

**Daemon → client**

| Event | Meaning |
|---|---|
| `{"event":"queued","position":1,"waiting":1,...}` | in the queue, waiting for room |
| `{"event":"granted","lease":7,"peak_bytes":...,"lock_path":"...","floor_bytes":...}` | the lease is granted; lock the file |
| `{"event":"presence_added","id":3,"label":"sweep","tier":"study"}` | the job is registered |
| `{"event":"presence","jobs":[...]}` | the presence queue |
| `{"event":"ledger","buckets":[...],"current":{...}}` | the closed hours and the hour being kept |
| `{"event":"rejected","reason":"..."}` | no lease (e.g. no history for `--peak auto`) |
| `{"event":"status", ...}` | the status report |
| `{"event":"ok"}` / `{"event":"error","message":"..."}` | answers to `held`/`release`/`ping` |

**One command does not use the socket.** `thor-admit peaks` reads the
history file (`<state-dir>/peaks.jsonl`, or `--history`) directly and
reports each label's p50 and p95 — the daemon writes that file as leases
end, so the history is there without asking the daemon anything.

The `target` says what the lease covers: a **process group** (what the CLI
leases — the command it spawns) or a **single process** (what the Python
shim leases — the calling process, so the watchdog cannot stop a seat'sother work by accident).

## 5. The knobs

Every knob is a parameter with a default; nothing is hard-coded.

| Knob | Default | What it does |
|---|---|---|
| `--floor` | 25 GiB | the floor a lease must clear |
| `--emergency-floor` | 8 GiB | below this, the watchdog acts |
| `--gpu-floor` | 2 GiB | the least the GPU's own allocation pool (`lfb`) must keep free; applied only when something can see the pool |
| `--sample-interval-ms` | 250 | how often the box is sampled |
| `--stop-grace-samples` | 8 | samples a watchdog-terminated lease is given before the escalation to `SIGKILL` (2 s) |
| `--heartbeat-grace-secs` | 60 | how long a silent client keeps its lease (clients heartbeat every 5 s) |
| `--grant-grace-secs` | 30 | how long a grant waits for its client to take the lock |
| `--min-victim-rss` | 2 GiB | the smallest lease the watchdog will touch |
| `--socket` | `$XDG_RUNTIME_DIR/thor-admit.sock` | where clients connect |
| `--state-dir` | `~/.local/state/thor-admit` | the lease files, the log, the history |
| `--history` | `<state-dir>/peaks.jsonl` | where the learned peaks are written |
| `--meminfo` | `/proc/meminfo` | where the box's memory accounting is read — **a test seam, not an operating knob** (see §7.3.3) |
| `--gpu-probe` | `auto` | `auto`, `nvidia`, `tegrastats`, `off` |
| `--tegrastats-command` | `tegrastats` | **a test seam**, like `--meminfo`: run this instead, so the GPU pool rule can be driven without touching the GPU |
| `--idle-exit` | 900 s | leave after this long with nothing to do (0 = never) |
| `--no-stop-on-client-gone` | off | leave a dead client's command running |
| `--priority` | 0 | the client's priority in the queue |
| `--peak` | — | a size, or `auto` for the learned p95 |
| `--tier` | `live` | the tier of work a lease is (see §8.1) |
| `--no-presence` | off | do not run the presence queue |
| `--presence-file` | `<state-dir>/presence.json` | where the presence queue is kept |
| `--flow-file` | `<state-dir>/flow.json` | where the flow signal is published, if anyone publishes one; the daemon records it and computes nothing |
| `--ledger` | `<state-dir>/ledger.jsonl` | where the ledger's hours are written |
| `--ledger-interval-ms` | 1000 | how often the CPU's counters are read |
| `--gpu-busy-threshold` | 50 | the GPU's busy share (per cent) at which live work takes the GPU from the presence queue |
| `--no-gpu-preempt` | off | never stop the presence work for the GPU |

## 6. What the GPU exposes (measured on this box)

The Thor's memory is **unified**: there is no separate VRAM pool, so there
is no second memory budget to watch. What the box does expose:

| Probe | Result on this box | Used for |
|---|---|---|
| `nvidia-smi --query-gpu=memory.used` | `[N/A], [N/A]` | nothing — the pool does not exist |
| `nvidia-smi --query-compute-apps=pid,used_memory` | **works**: `9961, 2570 MiB` | the per-lease GPU peak |
| `tegrastats` | `RAM 19777/125749MB (lfb 7x4MB)` | the Tegra's own RAM figure and the largest free block |
| `/sys/class/misc/nvmap` | a device node, no counters a user can read | nothing |
| `/proc/meminfo` | the kernel's own accounting | **the number the rule uses** |

**The tegrastats figure is the second opinion, not a second pool.** Measured
side by side on this box (13:58, box local; the meminfo column is
`MemTotal - MemAvailable`, in MB):

| Moment | `tegrastats` RAM used | `MemTotal - MemAvailable` | The gap |
|---|---|---|---|
| 13:58:04 | 19 777 | 14 513 | 5 264 |
| 13:58:05 | 19 774 | 14 509 | 5 265 |
| 13:58:06 | 19 758 | 14 494 | 5 264 |

The two numbers disagree by about 5.1 GiB and move together only loosely:
`tegrastats` counts the Tegra's own idea of used RAM (including what the
carveouts hold), while `MemAvailable` is the kernel's estimate of what a new
allocation could get. **`MemAvailable` is the number the rule uses**, because
it is the conservative one and it is the same number the OOM killer acts on.
`tegrastats` is kept as a second reading in the status and in the log.

The GPU's per-process figure *is* used: one `nvidia-smi` child keeps
printing `--query-compute-apps` every 2 s, the daemon reads its lines,
and it attributes the bytes to the lease that owns the pid. That is the
`peak_gpu_bytes` in the history — the only GPU number that can honestly
be called a per-lease peak.

## 7. The measured numbers

Everything below was measured on this box, with the box's state beside it.

### 7.1 The daemon's own cost

Measured on this box with the **release** build (the one that runs as a
daemon), 30 s windows, the box busy with a seat's work:

| Measure | Value | How |
|---|---|---|
| Resident memory | **2 MiB** | `/proc/<pid>/status` `VmRSS` |
| CPU, doing nothing | **0.03% of one core** (1 clock tick in 30 s) | `Δ(utime+stime)` over 30 s |
| CPU, one lease running | **1.1% of one core** | the same, over 30 s |
| CPU, the children it reaped | **0.00%** | the GPU watcher is one long-lived child, not a fork every sample |
| Minor faults | **0** | `/proc/<pid>/stat` `minflt` |
| Samples | **4.00 a second** | the daemon's own counters: 121 samples in 30.2 s |
| Socket | `0600` | only its owner may open it |

**The box, beside those numbers:** `MemTotal: 128 766 532 kB` (122.8 GiB,
no swap), `MemAvailable: 111 063 640 kB` (105.9 GiB), load average
6.04 / 6.58 / 7.67, at 16:26 on 2026-10-31 (the box's own clock, AKDT,
UTC-8).

**What changed, and why it was worth it.** The daemon used to ask
`nvidia-smi` for the GPU's per-process numbers every two seconds, forking
a fresh process each time whether anything was running or not, and walk
`/proc` for every process on the box every 250 ms. Measured, before and
after, same box, same windows:

| | before | after |
|---|---|---|
| idle, own CPU | 0.133% of a core | 0.133% of a core |
| idle, children reaped | 0.500% of a core | **0.000%** |
| idle, minor faults | 16 678 | **0** |
| one lease, own CPU | 2.133% of a core | **1.100%** |
| one lease, children reaped | 0.500% of a core | **0.000%** |
| one lease, minor faults | 15 650 | **0** |

The fork storm is gone: one `nvidia-smi` child keeps printing the
driver's view and the daemon reads its lines, so the daemon pays for one
fork, ever. The `/proc` scan has its own, slower clock
(`--scan-interval-ms`, default 1 s) instead of running on every 250 ms
sample — and it still runs on *every* sample when the box is below the
emergency floor, because that is when the watchdog needs a fresh ranking.
The GPU's view is only asked for when there is something to attribute it
to.

### 7.2 The learned peaks (the cost model's memory column)

Measured with the daemon on this box, the kernel's own `rusage`:

| Label | Asked for | Peak reached | Runs |
|---|---|---|---|
| `hog.4g` | 4 GiB | 4 296 847 360 B (4.0016 GiB) | 3 |
| `hog.8g` | 8 GiB | 8 591 884 288 B (8.0017 GiB) | 1 |
| `seat.py` | — | 9 830 400 B (9.4 MiB) | 1 |

The hog over-reaches its request by 0.04% — the allocator's own overhead and
the pages the binary itself occupies.

**The GPU's column, with a real GPU context.** The hogs above are CPU
only, so they have no GPU context and the driver says nothing about
them (`peak_gpu_bytes: null`). To show the column working, a small CUDA
program was run under a lease: it takes a real 512 MiB allocation on the
GPU and holds it for 12 s.

```
$ nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits
163916, 614
```

and the line the daemon wrote for that lease:

```json
{"at":"2026-11-01T00:18:00Z","kind":"cuda.probe","label":"cuda.probe","host":"thor",
 "peak_rss_bytes":71897088,"peak_gpu_bytes":643825664,"gpu_visible":true,
 "duration_s":12.27,"mem_total_bytes":131856928768,"floor_bytes":26843545600,
 "basis":"measured","source":"thor-admit","peak_source":"rusage"}
```

643 825 664 B is **614 MiB** — the same number the driver reported for
that pid (the 512 MiB the program asked for, plus the context). So the
GPU peak is a real per-lease measurement, not a guess: it is the
driver's own accounting, attributed to the processes of the lease.

### 7.3 The integration run

`tools/thor-admit/tests/integration.rs`, on the real box:

| Test | Result |
|---|---|
| `a_dead_client_cannot_leak_a_lease` | **passed** — the kernel drops the client's lock, the daemon gives the memory back |
| `the_queue_is_ordered_by_priority` | **passed** — a priority 5 request overtook a priority 0 one that arrived first |
| `a_learned_peak_is_used_by_the_next_run` | **passed** — `--peak auto` used the p95 of the label's history |
| `a_refused_lease_does_not_run_the_command` | **passed** — a refused lease never runs its command |
| `the_daemon_costs_almost_nothing` | **passed** — 2 MiB, 0.10% of a core idle, 2.20% with a lease (the **debug** build; the release build is §7.1) |
| `the_watchdog_leaves_small_leases_alone` | **passed** — a 1 GiB lease was not stopped even with the emergency floor armed |
| `the_stop_command_stops_the_daemon` | **passed** |
| `the_watchdog_stops_a_runaway_before_the_memory_runs_out` | **passed** — the low-water mark, §7.3.3 |
| `three_thirty_gigabyte_hogs_are_serialised` | **passed at 12 GiB** — see §7.3.1; the 30 GiB run waits for the box's own lock |
| `the_watchdog_stops_a_runaway_before_the_kernel_oom_does` | **passed at 12 GiB** — see §7.3.2 |

The unit tests cover the parts that are pure logic: the admission rule's
arithmetic (`admission.rs`), the queue's order (`queue.rs`), the lease
lock and the kernel dropping it when a client dies (`lease.rs`), the
percentiles the learned peaks use (`history.rs`), the meminfo and
`/proc` parsers, and the protocol's round trip.

#### 7.3.1 The serialisation (12 GiB hogs, 2026-10-31 22:08 UTC — 14:08 on the box)

Three hogs, one at a time. The floor was computed from the box's real
headroom (`available - hog - 8 GiB` = 72.9 GiB), so the test does not depend
on the exact gigabytes free at that moment:

```
22:08:13  lease.granted   hog1   mem_available 99 776 745 472
22:08:18  lease.released  hog1   peak_rss 12 886 786 048 (12.002 GiB)
22:08:18  lease.granted   hog0   mem_available 99 358 363 648
22:08:22  lease.released  hog0   peak_rss 12 886 654 976
22:08:22  lease.granted   hog2   mem_available 99 678 412 800
22:08:27  lease.released  hog2   peak_rss 12 886 847 488
```

The grants are strictly sequential: each hog was released before the next
one was granted, and the box never fell below **82 761 MiB** free. The
second and third hogs were **not admitted while the first was running** —
they waited in the queue, because the first still owed its 12 GiB and the
rule charges a running lease's promise against the headroom. They were
not *refused* (nothing was rejected): the queue is where a request waits
for room.

#### 7.3.2 The watchdog (12 GiB runaway, 2026-10-31 22:08 UTC — 14:08 on the box)

> Measured on the **stop-then-kill ladder that round 8 replaced** (§2.3).
> The numbers below are the old build's; they are kept because they are
> the honest record of that build. On the terminate-then-kill build, the
> same scripted-curve test (4 GiB hog, floor 8 GiB), measured 2026-11-01
> 08:34 UTC — 00:34 on the box, load 11.5/13.0/13.0, `MemAvailable`
> 104.2 GiB of `MemTotal` 125.8 GiB: the hog was **terminated with
> 7 168 MiB free**, the daemon acted within **172 ms** of the floor being
> crossed, the curve went on down to 0 MiB, the hog died and its lease
> was released, and the kernel's OOM killer fired **0 times**.

The daemon's emergency floor is a fixed **8 GiB** (§2.3). The *test*
lowers it to `available - 8 GiB` (86 764 MiB), because driving the real
box to 8 GiB free would need 110 GiB of allocation — more than the
brief allows a test to use, and more than the box can afford while a
seat is working. The rule that fires is the same rule; only the number
it fires at is different.

**The box, beside the numbers:** `MemTotal: 128 766 532 kB` (122.8 GiB,
no swap), and `MemAvailable` 99 776 745 472 B (92.9 GiB) when the first
lease was granted — the daemon's own log line. (The load average for
that run was not recorded; the log lines are.)

| | |
|---|---|
| Stopped with | **82 633 MiB free** — 40× the 2 GiB the brief asks for |
| The runaway's resident set when stopped | 10.1 GiB |
| Stopped → killed | 2 042 ms (8 samples at 250 ms) |
| The kernel's OOM killer | **0 times** (`/proc/vmstat`'s `oom_kill` was 0 before and after) |

The daemon reacted within one sample of the floor being crossed, with the
whole box still free. The kernel's OOM killer fires at zero free; the
watchdog fired at 80 GiB free.

#### 7.3.3 The low-water mark (the "before 2 GB" line)

The brief asks for the watchdog to stop a runaway hog **before
`MemAvailable` reaches 2 GB**. On this box that line is about 100 GiB of
allocation away: the box has 122 GiB and no swap, and the brief caps a
test's memory at 60 GiB. So the memory **curve** is scripted and
everything else is real.

The daemon can read its accounting from a file (`--meminfo`, default
`/proc/meminfo`; it is a test seam, and the daemon logs the path it is
reading in `daemon.started`, so a stale file cannot hide). The test
writes that file: first the box loses 88 GiB at once — the shape of the
13:22 OOM — and then it slides down a quarter of a gibibyte a step,
through the emergency floor and on past the 2 GiB line.

Measured (`the_watchdog_stops_a_runaway_before_the_memory_runs_out`):

| | |
|---|---|
| Stopped with | **7 168 MiB free** — the emergency floor was 8 192 MiB |
| The curve went on down to | **0 MiB** — the danger zone was reached *after* the stop |
| The daemon acted | **211 ms** after the floor was crossed (the log is polled every 20 ms, so this is an upper bound) |
| The kernel's OOM killer | **0 times** |
| The hog | really stopped (state `T`), then killed after the grace period |

The daemon's own log for that run — the number it acted on, and the
ranking it used:

```json
{"event":"watchdog.stopped","label":"runaway","lease":1,"mem_available_bytes":7516192768,"rss_bytes":4296790016,"signalled":true}
{"event":"watchdog.killed","label":"runaway","lease":1,"mem_available_bytes":0,"rss_bytes":4296790016,"signalled":true,"waited_ms":2241}
```

7 516 192 768 B is the value the daemon read (the scripted curve, at that
moment) — the free memory it had when it stopped the hog. The box's
*real* `MemAvailable` was about 105 GiB throughout: the hog's own 4 GiB
were real memory, and the curve was the pressure on top of it.

So the ordering the brief asks for is a fact about the rule, not a hope:
the watchdog acts when the box crosses the emergency floor, and the
emergency floor is above the 2 GB line.

**What this is and is not.** The *curve* is scripted; the daemon, the
hog, the `SIGSTOP`, the `SIGTERM` and the timing are real. The box's
real `MemAvailable` was never driven to 2 GB — that would have taken
about 100 GiB of allocation, more than the brief allows a test to use
(60 GiB) and more than the box can afford while a seat is working. So
the claim is split in two, and both halves are checked:

1. *The daemon acts before the box is in trouble.* Proved on the curve:
   the stop happened at 7 168 MiB, and the curve then went on down to
   0 MiB — the danger zone was reached **after** the stop.
2. *The 2 GiB line is below where the daemon acts.* Proved by
   arithmetic: the emergency floor is 8 GiB by default, the watchdog
   acts when `MemAvailable` falls below it, so it acts 6 GiB above the
   2 GiB line. §7.3.2 is the same rule against the kernel's own
   numbers, on the real box.

### 7.4 The rule, checked

The rule is `projected = available - Σ (reserved_i - current_i)`, and a
lease is admitted when `projected - peak >= floor`. Worked through:

| Case | `available` | Leases | New peak | Projected | Admitted? |
|---|---|---|---|---|---|
| alone | 100 GiB | — | 40 GiB | 100 GiB | **yes** — 60 GiB left, floor 25 |
| alone | 100 GiB | — | 80 GiB | 100 GiB | **no** — 20 GiB left, floor 25 |
| with a lease that has not grown | 100 GiB | 40 GiB reserved, 2 GiB used | 38 GiB | 62 GiB | **no** — 24 GiB left, one short of the floor |
| with a lease that overshot | 100 GiB | 10 GiB reserved, 30 GiB used | 65 GiB | 120 GiB | **yes** — 55 GiB left; the lease owes nothing more, so the memory it took past its promise is given back |

## 8. The presence scheduler: the box's own useful work

The admission controller answers "may this heavy thing start?". It does not
answer "what should the box be doing with the hours nobody is using?".

Measured at 20:38 on 2026-10-31: the GPU at idle power (VDD_GPU 3.1 W),
12 of 14 cores near 0 %, about 80 GB free, while the seats waited on cloud
LLMs. The box was mostly waiting — and nothing in the system said so,
because nothing in the system *knew* what the box could have been doing.

This section is the answer: a queue of the box's own work, and a ledger that
says where the box's time went.

### 8.1 The tiers

Every lease says what kind of work it is. The tier does two things: it is
the accounting band the ledger books the seconds to, and it is the
permission to pre-empt. Only **live** work may take the box back from the
presence queue.

| Tier | What it is | May pre-empt? |
|---|---|---|
| **live** | nights, previews, first-mile requests | **yes** |
| **preparation** | pre-generating likely-needed assets, refreshing keyframes | no |
| **practice** | retraining choosers, recalibrating confidence, FP4-aware training, replaying proposed changes against recorded inputs | no |
| **study** | the Infinigen sweep, hardware experiment batches, parity and benchmark suites | no |

A lease that does not say is **live**. That is the safe default — an
unlabelled request is somebody's work happening now — and it keeps every
client that predates the tiers working unchanged.

### 8.2 The presence queue

Registered work: **a command, a tier, an estimated peak and a resumability
flag**. It is a file (`<state-dir>/presence.json`), so it survives the
daemon and can be edited by hand; the daemon re-reads it when the file
changes.

The rules are three, and each one is a consequence of the others:

1. **A presence job runs only when no live request is waiting.** The live
   queue has head-of-line blocking: a live request that does not fit blocks
   everything behind it. The presence queue is behind everything, so
   background work can never make a live request's wait longer.
2. **Its memory is charged like any lease.** A job that promised 30 GiB
   and has used 2 GiB so far still owes 28 GiB. The headroom is
   `available - Σ (reserved - current)`, and the presence jobs are in that
   sum.
3. **It gives way when live work arrives** — in two different ways, because
   memory and GPU time are different things.

| | the trigger | the signal | what it costs the job |
|---|---|---|---|
| **memory** | a live lease is waiting and does not fit, and it *would* fit if the presence jobs were not charged | `SIGTERM` | the job stops; a resumable one goes back in the queue and runs again |
| **GPU** | a live lease is running and the GPU's busy share is at or above `--gpu-busy-threshold` (50 %) | `SIGSTOP` | the job pauses, keeping its memory and giving up the GPU's streams; it is continued when the live work is done |

The two are different on purpose. **A stopped process still holds its
memory**, so `SIGSTOP` cannot answer a memory shortage — only `SIGTERM`
can, because the process has to be gone. And a `SIGSTOP` is free of
consequence: the work resumes exactly where it left off, which is why the
GPU pre-emption is the gentler of the two.

### 8.3 The rule that decides the pre-emption

The memory pre-emption is not a guess. It fires only when all three of
these hold:

1. a **live** lease is at the head of the queue, and
2. it does **not** fit under the rule, and
3. it **would** fit if the presence jobs were not charged.

Condition 3 is what makes the pre-emption exact rather than brutal: if the
clients themselves are using the room, the presence queue is not what is in
the way, and the daemon does nothing (that case is the watchdog's
business). If the presence queue *is* what is in the way, the least urgent
running job is asked to stop — the *least* urgent, so the most useful
presence work keeps running as long as it can.

### 8.4 The ledger

One JSON line per hour, in `<state-dir>/ledger.jsonl`:

```json
{"hour":"2026-11-01T05","window_s":51.0,"samples":204,
 "tiers":{"live":{"running_s":44.5,"runs":0,"preemptions":0,"preempted_s":0.0},
          "study":{"running_s":1.0,"runs":1,"preemptions":1,"preempted_s":44.25}},
 "by_label":{"d1-critic":{"running_s":44.5,"preempted_s":0.0},
             "sweep.w7":{"running_s":1.0,"preempted_s":44.25}},
 "gpu":{"power_mw_mean":39388.0,"power_mw_max":47548,"power_samples":204,
        "busy_pct_mean":90.01,"busy_samples":204,"source":"tegrastats"},
 "cpu":{"cores":14,"busy_share_mean":0.993,"per_core_busy_share":[...],"samples":49},
 "idle":{"total_s":5.75,"by_reason":{"no_work_registered":5.75},
         "unattributed_s":0.0,"no_work_s":5.75},
 "memory":{"available_min":51245244416,"available_max":51990007808,
           "available_sum":10520264331264,"samples":204},
 "flow":{"confidence_mean":null,"confidence_min":null,"rate_mean":null,
         "sign":null,"samples":0}}
```

**The by-label bookkeeping** (round 9, from the three-minds gap analysis:
"a d1 per character, the critic… each in its own groove"). The tiers say
where the box's time went; `by_label` says what each *player* got — every
held lease's label and every running presence job's label, with the
pre-empted seconds beside the running ones. The tier totals and the label
totals are two views of the same samples, so an hour can be checked
against itself.

**The flow signal** (round 9): whoever runs the work may publish
`{"confidence": 0.87, "rate_of_change": 0.02}` to `<state-dir>/flow.json`;
the daemon reads it when the file changes and keeps it in the hour — the
confidence's mean and minimum, the rate's mean, the sample count, and the
sign at the end (`steady` / `faded`, a recording convention, not a
trigger). The daemon computes none of it and decides nothing from it; an
hour in which nobody published has `flow.samples: 0`, so "nobody is
publishing" and "the signal faded" stay two different sentences. This is
the honest slice of the three-minds "autopilot window": the daemon can
*record* the window's sign, but whether the window is the moment for a
keyframe or a mediator call is the mediator's decision, made where the
confidence came from (§13.2).

**The idle time is broken into causes**, because "the box was idle" is not
a measurement — it is a shrug:

| Cause | What it means |
|---|---|
| `no_work_registered` | nothing was registered to do, and nothing was asked for |
| `waiting_for_memory` | work was ready, but the box had no room for it |
| `waiting_for_gpu` | work was ready, but the GPU was busy with higher-priority work |
| `preempted_for_live_work` | work was stopped so live work could run |
| `granted_not_run` | a lease was granted — the memory committed — but the client never held it, so no work ran |
| `unattributed` | the ledger cannot say — **this is the number that should be zero** |

`no_work_registered` is a cause but not a good one: it is the presence gap
itself. It is reported on its own, so that "the ledger explains
everything" and "the box had nothing to do" stay two different sentences.
The brief's target — the share of time idle **without a reason** — is the
`unattributed` share, and the classifier is total: every idle sample gets
exactly one cause, and the last case (`unattributed`) is reachable only
when registered work fits, is not running, and is not stopped.

**A lease is booked from the `held`, not from the grant.** The daemon
answers `granted` and the client answers `held`, and only the `held` means
work can exist: booking from the grant invented running time for leases
whose command never started — `live.running_s > 0` with `runs: 0` (Hy4's
fifth failure mode). But the grant's window is not thrown away, because
the box was not doing *nothing* in it either — the memory was committed,
which is exactly why nothing else ran. The window is booked to
`granted_not_run`, its own attributed cause, and the release path names
the same fact once in the log (`lease.granted_not_run`): a phantom lease
is neither work nor a mystery, and `unattributed` stays at zero.

**Where the figures come from.** The GPU's **power** is `tegrastats`' own
`VDD_GPU` rail — the Tegra's number for the GPU's rail — read by the child
that was already printing the box's memory view. The GPU's **busy share**
is `nvidia-smi --query-gpu=utilization.gpu`: this Thor's `tegrastats`
prints no 3D busy percentage, so the driver answers that one. The
**CPU**'s share per core comes from `/proc/stat`'s per-core lines: the busy
share of each core is Δ(busy) / Δ(total) over the window. The ledger
records the source of the GPU figures, so a reader never has to guess
which tool answered what.

### 8.5 What it measured, on this box

**The box, beside the numbers:** `MemTotal: 128 766 532 kB` (122.8 GiB, no
swap), `MemAvailable` 48.5 GiB, load average 16.25 / 16.33 / 16.17, at
21:43 AKDT on 2026-10-31 (the box's own clock, UTC-8). The box was busy
with a seat's work; the daemon's own cost was measured in that state, not
on an idle box.

**The daemon's cost, with the presence scheduler and the ledger on** (the
release build, 30 s windows):

| | idle | one lease and one presence job |
|---|---|---|
| Resident memory | **2 304 KiB** (2.25 MiB) | **2 560 KiB** (2.50 MiB) |
| CPU, its own | **0.20 % of one core** | **0.80 % of one core** |

The extra work over §7.1 is the ledger: a sample every 250 ms, the CPU's
counters once a second, and the GPU's children read every tick instead of
every eighth one (the ledger wants the GPU's power and busy share even
when the box is doing nothing — "the GPU was idle at 3.2 W" is one of the
numbers the ledger exists to keep).

**The ledger, one window** (51.0 s, 204 samples, 21:44–21:45 AKDT). The
seat's work was on the GPU that minute, so the GPU pre-emption fired and
the presence job gave the GPU up:

| | |
|---|---|
| live tier | **44.5 s** running |
| study tier | **1.0 s** running, **44.25 s stopped** by the GPU pre-emption, 1 run, 1 pre-emption |
| idle | **5.75 s**, all of it `no_work_registered` |
| **unattributed** | **0.0 s — 0 %** |
| GPU power | **39 388 mW mean**, 47 548 mW max (`tegrastats`) |
| GPU busy share | **90.0 %** mean (204 samples) |
| CPU busy share | **0.993** of the box, 14 cores (per-core shares in the record) |
| Free memory | 47.7 GiB at the lowest, 48.4 GiB at the highest |

**And the same ledger, twenty minutes earlier**, when the GPU was idle and
the seat's work was on the CPU side (21:27–21:28 AKDT, 51.5 s, 206
samples):

| | |
|---|---|
| live tier | 44.75 s running |
| study tier | 45.5 s running, 1 run |
| idle | 6.0 s — all `no_work_registered` |
| **unattributed** | **0.0 s — 0 %** |
| GPU power | **3 201.6 mW mean**, 5 116 mW max (`tegrastats`) |
| GPU busy share | **0 %** (206 samples) |
| CPU busy share | 0.667 of the box, 14 cores |

Two windows, two states of the box, and the ledger reads both: the GPU at
**3.2 W** and idle while the CPU was busy, and the GPU at **39 W** and 90 %
busy while the presence work had given its streams up. The 3.2 W is the
same reading as the 20:38 note in the brief (3.1 W), two hours and a half
later — now in a record rather than in somebody's memory.

**The memory pre-emption, on the real box** (21:45 AKDT). The presence job
was registered with a 4 GiB peak and was holding none of it; the live
lease asked for 2 GiB; the floor was 42.9 GiB, which is
`available - 4 GiB - 2 GiB + 1 GiB` — the number that makes the presence
job's reservation exactly what stands between the live lease and the room.

```
21:45:50  presence.started    measure.preempt  peak 4 GiB   mem_available 51 238 248 448
21:45:50  presence.preempted  measure.preempt  live_label measure.live2
21:45:51  presence.finished   measure.preempt  exit 143 (SIGTERM)  state preempted
21:45:51  lease.granted       measure.live2    peak 2 GiB
21:45:56  presence.started    measure.preempt  peak 4 GiB     ← it resumed
```

| | |
|---|---|
| The live lease was admitted after | **0.279 s** (the client's own measurement) |
| The pre-emption was logged | in the **same second** as the request |
| The job's exit | **143** — 128 + SIGTERM, the signal the daemon sent |
| The job's state afterwards | `preempted` — and it was **resumable**, so it was not lost |
| The kernel's OOM killer | **0 times** |

**And it resumed five seconds later, not sooner** — and the arithmetic
says why. While the live lease was running, the presence job's 4 GiB did
not fit beside the live lease's 2 GiB promise:

```
available          51 238 240 256   (47.73 GiB)
- live lease owes    2 145 700 000   (2 GiB promised, 1.8 MB used)
- presence job peak  4 294 967 296   (4 GiB)
= headroom          44 797 572 960   (41.73 GiB)   <  floor 42.9 GiB  → no
```

When the live lease ended, its 2 GiB came back and the headroom became
43.7 GiB — above the floor — and the job started again at 21:45:56. That
is the rule working, not the rule being slow: the presence work waits
until the box really has the room for it.

## 9. The daemon as a service

**No systemd unit is installed or enabled.** The daemon is a user-level
process; the crate's README says how to start it. Checked on this box
(2026-10-31, 16:19 AKDT):

```
$ systemctl --user list-unit-files | grep thor-admit
(no output)
$ ls ~/.config/systemd/user/
thor-desk-novnc.service  thor-desk-x11vnc.service  thor-index.service
$ ls /etc/systemd/system/ | grep thor
(no output)
```

The box's own units (`thor-index`, the desktop) are there; nothing of
this crate's is. For the operator who wants
one, this is the unit — it is *documented*, not installed:

```ini
# ~/.config/systemd/user/thor-admit.service
[Unit]
Description=thor-admit: memory admission for the Thor
After=default.target

[Service]
Type=simple
ExecStart=%h/src/builder-ide/tools/thor-admit/target/release/thor-admit daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now thor-admit.service
```

It is a *user* unit on purpose: the daemon runs as the user whose seats run
under, it needs no root, and it cannot outlive the session.

## 10. What it does not do

* **It does not install anything** — no unit, no packages, no root.
* **It does not touch the box's services.** They are not leases.
* **It does not know about swap.** There is none; the floor is the whole
  story.
* **It does not preempt a lease.** A lease that is running is not
  interrupted for anything but the emergency floor; the queue's priorities
  decide what waits, not what dies. What the daemon *does* pre-empt is its
  own presence queue (§8.2) — the work it started itself, for which it
  holds the lease.
* **It does not model the kernel's reclaim.** The floor is a number; how
  much of it the kernel would actually give back is the kernel's business.
* **It does not replace the core's per-model load cap** (S §1.9). That is
  the *model* axis, enforced at batch admission; this is the *box* axis,
  enforced at lease time. They compose: the night asks the core what fits
  the rails, the core asks the daemon what fits the memory.
* **It does not survive its own death in the middle of a kill.** If the
  daemon is killed between the watchdog's `SIGTERM` and the `SIGKILL`
  escalation, the `SIGTERM` stands on its own: the client reaps its child,
  releases the lease and exits, so the normal cleanup paths finish the
  job. What the daemon still cannot finish is the client's side — a client
  that ignores both signals keeps its lease until the daemon is back. The
  daemon logs every termination and every kill, and `thor-admit status`
  shows the lease, so the operator can see it and act.
* **It cannot see the split of the GPU's non-reclaimable pool.** The
  `--gpu-floor` rule rides on `tegrastats`' `lfb` alone (§2.1): how much of
  that pool is device memory and how much is pinned host memory is not
  answered by anything a user can read on this box (`nvidia-smi
  --query-gpu=memory.used` says `N/A`).

## 11. Open questions

1. **What is the right floor?** 25 GiB is the stopgap's number, carried
   forward. The box's own use (the desktop, the seats' tooling, the
   kernel) is not measured by anything here yet.
2. **Should the emergency floor be lower than 8 GiB?** The kernel's OOM
   killer fires at zero. 8 GiB is a guess with a margin; the honest
   measurement is what the watchdog test showed.
3. **Should a lease be preemptible?** Today a lease runs to the end. The
   night runner might rather stop a batch and resume it than wait. The
   presence queue's pre-emption (§8.2) is the same question asked of the
   daemon's *own* work, and it has an answer for that case: `SIGSTOP` for
   the GPU, `SIGTERM` for the memory. A client-held lease is different,
   because the client would have to agree to be stopped.
4. **Does the GPU's per-process figure deserve more than the peak?** The
   driver answers it every 2 s, and it is the only per-lease GPU number
   there is.
5. **Should the history be a table and not a log?** A log is easy to
   append and easy to replay; a table would answer "what did this label
   cost on Tuesday" faster.
6. **What should be in the presence queue?** The queue is a file, and the
   file is empty until somebody puts something in it. The ledger can now
   say how much of the box's time went to `no_work_registered` — the
   presence gap — but it cannot say what *should* have been there. That is
   a question for the night runner and the seats, not for the daemon
   (§13.2: the crate ships three disabled *examples*, and that is as far
   as the daemon's opinion goes).
7. **Is `SIGSTOP` the right way to give the GPU back?** It stops the
   whole process group, so the job's CPU work stops too. A finer
   mechanism — the CUDA stream priority the driver already exposes — would
   keep the job's CPU work running and only take its GPU streams. It was
   not measured here.
8. **Should a lease that promises no device memory wait for the GPU's
   pool?** The `--gpu-floor` rule applies to every lease, so when the
   box's allocation pool (`lfb`) sits under the floor — other seats'
   CUDA work, which is not the daemon's to move — even a CPU-only lease
   with no GPU history waits. That is the conservative reading and it is
   what ran overnight; the alternative (exempt a lease whose learned GPU
   promise is zero) would let CPU work through a full pool at the risk
   that a first run touches CUDA unmeasured. Measured on this box at
   ~02:00 on 2026-11-01, `lfb` swung between 0.15 GiB and 2 GiB in
   minutes, so the question is live (§13.4).

## 12. Round 8 (2026-10-31 23:00 → 11-01): the Hy4 review folded in, the real workload invited in

Round 7 was merged (9e02958). At 22:09 the box fell to 8 GiB available —
the thing this daemon exists to prevent — under three Infinigen sweep
workers, Hunyuan3D-2 and two seats' d1-2B llama-servers. The director's
round 8 asked for the real workload to be put under the daemon, and Hy4's
adversarial review (REVIEW-HY4.md, 22:45) named five failure modes. All
five are folded in; each is described where it lives above, and named
here with what changed:

1. **A stopped process holds its memory.** The watchdog no longer
   `SIGSTOP`s for memory — it terminates (§2.3), because with no swap a
   stopped victim's pages stay taken and the emergency deepens through the
   grace period. The GPU pre-emption still `SIGSTOP`s (that is the point:
   give up the GPU, keep the memory), and every memory termination of a
   presence job now `SIGCONT`s first, so a frozen job actually receives
   its `SIGTERM`.
2. **A learned peak can be too low.** `--peak auto` reserves
   max(p95, last run), refuses to guess below three runs, and an
   over-running lease is logged and written to the history while it is
   still running (§2.4).
3. **MemAvailable cannot see the non-swappable pool.** The GPU's own
   allocation pool (`lfb`) is a second budget with `--gpu-floor`, applied
   when something can see it, logged beside the memory, and named when it
   is what a waiter is waiting for (§2.1).
4. **A hung client's lock never drops.** Clients heartbeat while they
   hold; the daemon gives silence a grace period, tells a stuck client
   from a dead one by the socket's credentials, and takes the lease back
   either way (§3).
5. **A granted-but-never-held lease was booked as running.** The ledger
   books from the `held`, and the grant's window has its own attributed
   cause, `granted_not_run` (§8.4).

Two daemon-identity holes mcode had already found were finished and
committed first: the daemon holds an exclusive flock on
`<socket>.lock` for its whole life (the kernel drops it whatever kills
the daemon, so "one daemon per socket" is a fact, not a hope; the
acceptor also stops loudly on the first error it cannot survive), and a
daemon started for a socket that is not the box's own keeps its state
beside that socket instead of writing into the box's real record.

### 12.1 `serve`: a model loaded once per box

The 22:09 incident was half sweep workers and half *two* d1-2B
llama-servers, one per seat. `thor-admit serve <model> --port <n> --
<command>` is the registry (§"serve" in the crate README): the second
asker gets the first's port and runs nothing; the first runs the server
under an ordinary live lease (`serve.<model>`), so admission, the
watchdog and the learned peaks all apply to a model server exactly as to
any other work, and killing the seat's `serve` takes the server with it.
The registry is one JSON line per server under the state dir, worth
exactly as much as the port probe behind it.

Round 8 keyed the registry on the *name* the seat typed, and the box paid
for it at 01:19 on 2026-11-01: three d1-2B servers ran at once as `d1-2B`,
`d1-2B-baseline` and `d1-2B-batch`. Round 9 re-keyed it on what actually
costs the memory and what actually changes the serving: the **model
file** (its resolved path plus a content hash, computed per ask) and the
**config tuple** (the command with the model file and the port taken
out). The same file under the same flags is one server under any name; a
variant exists only when its flags really differ, and a variant is its
own server because it is one. Entries written by the round-8 build keep
their name-derived key until their servers go.

### 12.2 The tests, made fair to a busy box

The director measured 7 of 14 integration tests failing in parallel at
load ~38 (14/14 serial). The suite is now **serial by default** (a
one-at-a-time gate; `THOR_ADMIT_PARALLEL_TESTS=1` opens it for a
deliberate parallel run), and the waits no longer assume a quiet box:
arrivals are waited for, not slept past; the deadlines behind slow
daemon starts were doubled; and the GPU-pool test waits for its scripted
pool to be visible before asking for a lease. Measured here, 14 cores,
load 8-9 from other seats' work before the runs:

| Run | Result | Time | Box state |
|---|---|---|---|
| serial (the default) | 26/26 | 79 s | load ~9 |
| parallel, 6 consecutive runs | 26/26 each | 24 s each | load ~9 |
| parallel, 2 more | 26/26 | 24 s | 1-min load 27-35 (28 bounded CPU spinners, nice 5) |
| serial | 26/26 | 79 s | same window |

Before the gate and the fixes, the parallel suite failed roughly one run
in three on this box. The suite is 26 tests now; the new ones are the
three lease-holder tests (silent, orphaned, heartbeating), the
granted-never-run ledger test, the two learned-peak tests, the over-run
watch test, the GPU-pool test and the serve lifecycle test.

### 12.3 What is staged, and what is held

The round's items 1 and 2 — the sweep worker wrapped in study-tier
leases (`~/src/infinigen-thor`, branch `thor-sweep-admit`) and the seats'
memory rule (`~/lm-wt/MEMORY-RULE.md`) — live outside this repository,
and this round ran under the instruction to modify files only inside it.
Both are finished, tested and staged in `tools/thor-admit/round8/`,
with exact apply steps: the patch was verified with `git apply --check`
against the current `thor/sweep-worker.sh`, and its bootstrap-fallback
logic was smoke-tested against a scratch daemon on this box.

Item 5 — the one-hour measurement with the sweep under the daemon — is
held until the director says the MIG quiet window is over
(`~/lm-ops/QUIET-WINDOW.md`, which did not exist when this round
started). No GPU work was started in this round; the tests allocate at
most a few gibibytes of CPU memory, and the load runs above used
bounded CPU spinners only.

## 13. Round 9 (2026-11-01): what a run must do to teach, and what the daemon must not own

Round 8 was merged. Overnight the daemon ran for real (tmux
`last-mile:admitd`, from the binary at `~/lm-tools/thor-admit`), seats
took leases — and the director's watch caught two failures and three
design gaps. The fixes, each where it lives:

### 13.1 A no-op run cannot teach (items a and c)

A lease's reserve showed as **3.6 MB** for `infinigen.mountain.coarse`
while the lease was using **1.3 GiB**. The history held 25 no-op records
(<5 s, <512 MiB — the wrapper's own invocations), the director removed
them from `peaks.jsonl` at 00:50, and the running daemon still held them
in memory. Three changes close all three holes:

* the **learning rule**: a run teaches only if it exited 0 (the client
  reports its exit status on release) and lasted at least 5 s, applied on
  write *and* on read (§2.4) — so no-ops already in a file are ignored
  however many there are;
* the **reload**: `thor-admit reload` and `SIGHUP` re-read the history
  and the presence queue without a restart, so an edit by hand reaches a
  daemon that is mid-flight (§2.4); before this, the only way was a
  restart, and a restart waits for a box with no leases;
* the **over-run watch keeps its authority**: an over-running lease is
  written down while it runs (that is round 8's), and those records
  always teach — the filter is aimed at no-ops, which can only lower a
  reserve, never at the records that raise one.

### 13.2 The three-minds gaps (item d, REVIEW-HY4-GAPS.md)

The gap analysis named four; the smallest two are built, the third is
built as *recording only*, and the fourth is corrected in the design
rather than built, because the daemon should not own it:

* **A by-label ledger** — built (§8.4): every hour keeps each label's
  running and pre-empted seconds beside the tier totals. Labels are
  facts the daemon already holds; booking them is bookkeeping, not
  judgement.
* **A default presence queue** — built as *examples*: the crate ships
  `presence.default.json` with the cheapest three jobs of the
  PRESENCE-JOBS.md proposal, **disabled**, their commands placeholders.
  The daemon does not decide what is worth doing; the night runner owns
  the content, and a disabled example is a starting point that cannot
  run anything by accident. `presence add --disabled` registers the
  same shape at runtime, and a job whose command cannot start is marked
  failed once instead of being retried every tick.
* **A flow signal** — built as recording only (§8.4): the daemon reads
  `<state-dir>/flow.json` when it changes and keeps the hour's
  confidence, rate of change and sign. The autopilot *decision* — "the
  sign is steady, take the keyframe" — stays with the mediator, who can
  register preparation work whenever it decides to; the queue's existing
  rules handle the rest. The daemon records the window; it does not open
  it.
* **A `presence_cue` op** — not built, and the design is corrected
  instead: cues are the room graph's channel, not the admission
  daemon's. The daemon's queue is not a message bus, and a per-job cue
  FIFO inside an admission controller would be a second room graph grown
  by accident. When the room graph exists, a presence job that wants
  cues should subscribe to it directly; nothing in this crate needs to
  change for that.

The gap analysis's other items — the glance that gathers the other
players' state, the "another chorus" reallocation, the human-feedback
channel, the re-entry triggers — are all the same shape: the daemon can
provide the *window* (memory, the queue, the ledger's record of it) but
not the *decision*, and they are left where the decisions live.

### 13.3 `serve`, keyed on the model (item e)

§12.1 above: the registry keys on the model file (path + content hash)
plus the config tuple, so `d1-2B` and `d1-2B-baseline` with the same
command are one server, and a variant only when its flags really differ.

### 13.4 Two bugs the round's own tests found

**A daemon that idled out did not exit.** The CLI's signal watcher waited
for a signal, and only a signal: when the daemon's clock left by idle
exit, the process stayed alive in `watcher.join()`, holding the socket's
flock — so every later daemon on that socket was refused with "another
thor-admit daemon is already running", and a client waiting on a lease
waited on a socket whose daemon had said goodbye in its log and not in
its process table. Found because a test daemon idled out under a waiter
the GPU's floor was holding (below) and hung the suite for half an hour.
The watcher now takes the daemon's own word (`is_stopped`) as well as the
signal's, and a non-empty queue counts as activity: a daemon with a
client waiting for room has something to do.

**The tests read the box's real GPU pool.** With other seats' CUDA work
holding the allocation pool at ~0.3 GiB of `lfb` — under the 2 GiB
`--gpu-floor` — every CPU-only test lease waited on a rule that had
nothing to do with it, because `gpu_admits` applies the pool's floor to
every lease, including one that promises no device memory at all. That is
the designed rule (§2.1), and on the live box it did what it is for: the
01:19 queue of d1-2B variants was waiting for the *pool*, correctly, not
for memory. But a test's admission decisions must not depend on another
seat's CUDA allocations, so every test daemon now starts with
`--gpu-probe off` (the GPU-pool test brings its own scripted view). The
general question — should a lease with no GPU promise be exempt from the
pool's floor? — stays open (§11.8).
