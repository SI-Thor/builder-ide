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

1. **SIGSTOP** its process group. The work stops where it is; nothing is
   lost.
2. If the box is still short after the grace period (8 samples = 2 s), the
   watchdog sends **SIGTERM**, and then **SIGCONT** — because a stopped
   process never sees its SIGTERM until it runs again.

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

`--peak auto` asks the daemon for the **p95 of that label's history**, in
the same percentile convention `core/night/cost/model.py` uses (linear
interpolation, NumPy's convention). A label with no history is refused with
a clear reason rather than guessed at.

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

**One subtlety, measured.** A forked child inherits the descriptor until it
reaches its `exec`, and `O_CLOEXEC` only closes it there. So a lease can
outlive its client by about a millisecond if a fork happens at that
moment. The daemon polls every 250 ms, so it never notices; a test that
probes once can lose that race, so it waits.

**And the orphan.** A client that dies takes its command with it: the daemon
sends `SIGTERM` (then `SIGCONT`) to the lease's target, because an unwatched
30 GiB hog is exactly the thing this daemon exists to prevent.
`--no-stop-on-client-gone` turns that off.

## 4. The protocol

JSON, one object per line, over a Unix socket (`$XDG_RUNTIME_DIR/thor-admit.sock`,
or `/tmp/thor-admit-<uid>.sock`). Small enough for a Python shim with no
dependency, and readable with `nc -U`.

**Client → daemon**

| Request | Meaning |
|---|---|
| `{"op":"acquire","label":"trellis","peak":42949672960,"priority":0,"target":{"group":{"pgid":1234}}}` | take a lease (`peak` may be `"auto"`) |
| `{"op":"held","lease":7}` | the client holds the lock now: the lease is real |
| `{"op":"release","lease":7,"peak_rss_bytes":123456}` | the lease is over |
| `{"op":"status"}` / `{"op":"ping"}` | what is going on / is the daemon alive |

**Daemon → client**

| Event | Meaning |
|---|---|
| `{"event":"queued","position":1,"waiting":1,...}` | in the queue, waiting for room |
| `{"event":"granted","lease":7,"peak_bytes":...,"lock_path":"...","floor_bytes":...}` | the lease is granted; lock the file |
| `{"event":"rejected","reason":"..."}` | no lease (e.g. no history for `--peak auto`) |
| `{"event":"status", ...}` | the status report |
| `{"event":"ok"}` / `{"event":"error","message":"..."}` | answers to `held`/`release`/`ping` |

The `target` says what the lease covers: a **process group** (what the CLI
leases — the command it spawns) or a **single process** (what the Python
shim leases — the calling process, so the watchdog cannot stop a seat's
other work by accident).

## 5. The knobs

Every knob is a parameter with a default; nothing is hard-coded.

| Knob | Default | What it does |
|---|---|---|
| `--floor` | 25 GiB | the floor a lease must clear |
| `--emergency-floor` | 8 GiB | below this, the watchdog acts |
| `--sample-interval-ms` | 250 | how often the box is sampled |
| `--stop-grace-samples` | 8 | samples a stopped lease is given before it is killed (2 s) |
| `--min-victim-rss` | 2 GiB | the smallest lease the watchdog will touch |
| `--socket` | `$XDG_RUNTIME_DIR/thor-admit.sock` | where clients connect |
| `--state-dir` | `~/.local/state/thor-admit` | the lease files, the log, the history |
| `--history` | `<state-dir>/peaks.jsonl` | where the learned peaks are written |
| `--meminfo` | `/proc/meminfo` | where the box's memory accounting is read — **a test seam, not an operating knob** (see §7.3.3) |
| `--gpu-probe` | `auto` | `auto`, `nvidia`, `tegrastats`, `off` |
| `--idle-exit` | 900 s | leave after this long with nothing to do (0 = never) |
| `--no-stop-on-client-gone` | off | leave a dead client's command running |
| `--priority` | 0 | the client's priority in the queue |
| `--peak` | — | a size, or `auto` for the learned p95 |

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

The GPU's per-process figure *is* used: the daemon samples
`nvidia-smi --query-compute-apps` every 8 ticks (2 s) and attributes the
bytes to the lease that owns the pid. That is the `peak_gpu_bytes` in the
history — the only GPU number that can honestly be called a per-lease peak.

## 7. The measured numbers

Everything below was measured on this box, with the box's state beside it.

### 7.1 The daemon's own cost

| Measure | Value | How |
|---|---|---|
| Resident memory | **2 MiB** | `/proc/<pid>/status` `VmRSS`, after 2 s warm-up |
| CPU, doing nothing | **0.30% of one core** | `Δ(utime+stime)` over 10 s of wall clock |
| Samples | 4/s | 250 ms interval |
| Socket | `0600` | only its owner may open it |

The cost of the `/proc` scan (reading every process's `stat` to find the
leases' resident sets) is part of that 0.30%.

### 7.2 The learned peaks (the cost model's memory column)

Measured with the daemon on this box, the kernel's own `rusage`:

| Label | Asked for | Peak reached | Runs |
|---|---|---|---|
| `hog.4g` | 4 GiB | 4 296 847 360 B (4.0016 GiB) | 3 |
| `hog.8g` | 8 GiB | 8 591 884 288 B (8.0017 GiB) | 1 |
| `seat.py` | — | 9 830 400 B (9.4 MiB) | 1 |

The hog over-reaches its request by 0.04% — the allocator's own overhead and
the pages the binary itself occupies.

### 7.3 The integration run

`tools/thor-admit/tests/integration.rs`, on the real box:

| Test | Result |
|---|---|
| `a_dead_client_cannot_leak_a_lease` | **passed** — the kernel drops the client's lock, the daemon gives the memory back |
| `the_queue_is_ordered_by_priority` | **passed** — a priority 5 request overtook a priority 0 one that arrived first |
| `a_learned_peak_is_used_by_the_next_run` | **passed** — `--peak auto` used the p95 of the label's history |
| `the_daemon_costs_almost_nothing` | **passed** — 2 MiB, 0.30% of a core |
| `the_watchdog_leaves_small_leases_alone` | **passed** — a 1 GiB lease was not stopped even with the emergency floor armed |
| `the_stop_command_stops_the_daemon` | **passed** |
| `three_thirty_gigabyte_hogs_are_serialised` | **passed at 12 GiB** — see §7.3.1; the 30 GiB run waits for the box's own lock |
| `the_watchdog_stops_a_runaway_before_the_kernel_oom_does` | **passed at 12 GiB** — see §7.3.2 |

#### 7.3.1 The serialisation (12 GiB hogs, 2026-10-31 22:08)

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

The grants are strictly sequential, and the box never fell below
**82 761 MiB** free. The second hog was **refused by the reservation rule**,
not by running out of memory: it was never admitted because the first still
owed its 12 GiB.

#### 7.3.2 The watchdog (12 GiB runaway, 2026-10-31 22:08)
The emergency floor was `available - 8 GiB` (86 764 MiB):

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

So the ordering the brief asks for is a fact about the rule, not a hope:
the watchdog acts when the box crosses the emergency floor, and the
emergency floor is above the 2 GB line.

### 7.4 The rule, checked

| Case | `available` | Leases | New peak | Admitted? |
|---|---|---|---|---|
| alone | 100 GiB | — | 40 GiB | yes (60 GiB left, floor 25) |
| alone | 100 GiB | — | 80 GiB | no (20 GiB left, floor 25) |
| with a lease that has not grown | 100 GiB | 40 GiB reserved, 2 GiB used | 38 GiB | no (the running lease owes 38) |
| with a lease that overshot | 100 GiB | 10 GiB reserved, 30 GiB used | 65 GiB | yes (it owes nothing more) |

## 8. The daemon as a service

**No systemd unit is installed or enabled.** The daemon is a user-level
process; the crate's README says how to start it. For the operator who wants
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

## 9. What it does not do

* **It does not install anything** — no unit, no packages, no root.
* **It does not touch the box's services.** They are not leases.
* **It does not know about swap.** There is none; the floor is the whole
  story.
* **It does not preempt.** A lease that is running is not interrupted for
  anything but the emergency floor; the queue's priorities decide what waits,
  not what dies.
* **It does not model the kernel's reclaim.** The floor is a number; how
  much of it the kernel would actually give back is the kernel's business.
* **It does not replace the core's per-model load cap** (S §1.9). That is
  the *model* axis, enforced at batch admission; this is the *box* axis,
  enforced at lease time. They compose: the night asks the core what fits
  the rails, the core asks the daemon what fits the memory.

## 10. Open questions

1. **What is the right floor?** 25 GiB is the stopgap's number, carried
   forward. The box's own use (the desktop, the seats' tooling, the
   kernel) is not measured by anything here yet.
2. **Should the emergency floor be lower than 8 GiB?** The kernel's OOM
   killer fires at zero. 8 GiB is a guess with a margin; the honest
   measurement is what the watchdog test showed.
3. **Should a lease be preemptible?** Today a lease runs to the end. The
   night runner might rather stop a batch and resume it than wait.
4. **Does the GPU's per-process figure deserve more than the peak?** The
   driver answers it every 2 s, and it is the only per-lease GPU number
   there is.
5. **Should the history be a table and not a log?** A log is easy to
   append and easy to replay; a table would answer "what did this label
   cost on Tuesday" faster.
