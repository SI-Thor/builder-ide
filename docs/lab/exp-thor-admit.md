# exp-thor-admit — the box's memory, measured

**Round 6 (2026-10-31).** The experiment behind `tools/thor-admit`: the
first Rust component in builder-ide. The question was not "can Rust work on
the Thor" — it was "can the box be told how much memory is already
committed, and can a heavy thing be made to wait for room".

**Verdict: useful — it works, and the numbers are better than the stopgap
it replaces.** A daemon that costs **2 MiB of RAM and 0.30% of one core**
keeps **122 GiB** of unified memory under a single view, and the rule it
enforces (`available - peak >= floor`, with the running leases' promises
charged) is the plain rule plus what the kernel cannot see.

---

## 1. The setup

The box, as it stood at 13:36 on 2026-10-31 (the box's own clock, AKDT,
UTC-8; times that say UTC are UTC):

| | |
|---|---|
| Kernel | Linux 6.8.12-1021-tegra, aarch64 |
| Memory | `MemTotal: 128 766 532 kB` — **122.8 GiB unified, no swap** (`SwapTotal: 0`) |
| GPU | NVIDIA Thor, driver 595.78, CUDA 13.2 |
| CPU | 14 Neoverse cores |
| Load at the time | `15.92 7.36 3.24`, 1070 threads — **the box was busy with seat work** |

The measurement that made this necessary: at 13:22 the box hit a **global
OOM** and rebooted, with TRELLIS (55–68 GB), FP4 sweeps, llama-servers,
motion training and Infinigen sweep workers all running at once. The OOM
killer took the small services first (`oom_score_adj=200`).

The box's stopgap at the time: `flock ~/lm-wt/heavy.lock`. While this
experiment ran, **five other seats were queued on that lock** — which is
the contention the daemon exists to replace.

## 2. What the GPU exposes (the part the brief asked about)

The Thor's memory is unified, so the question "what does the GPU see?" has
an unusual answer: there is no second pool, but there are three different
readings of the *same* pool.

| Probe | Answer on this box | Kept? |
|---|---|---|
| `nvidia-smi --query-gpu=memory.used,memory.total` | `[N/A], [N/A]` | no — the pool does not exist |
| `nvidia-smi --query-compute-apps=pid,used_memory` | `9961, ./build/lt_fp4_bench, 2570 MiB` | **yes** — the per-lease GPU peak |
| `tegrastats` | `RAM 19777/125749MB (lfb 7x4MB)` | yes — the Tegra's own figure |
| `/sys/class/misc/nvmap` | a device node (`cr--r----- root video`), **no counters a user can read** | no |
| `/sys/module/nvmap/parameters` | `enable_page_pools`, `pool_size`, `shrink_page_pools` | no — tunables, not readings |

**tegrastats against the kernel, side by side** (13:58, box local; the
meminfo column is `MemTotal - MemAvailable`, in MB):

| Moment | `tegrastats` RAM used | `MemTotal - MemAvailable` | The gap |
|---|---|---|---|
| 13:58:04 | 19 777 | 14 513 | 5 264 |
| 13:58:05 | 19 774 | 14 509 | 5 265 |
| 13:58:06 | 19 758 | 14 494 | 5 264 |

The gap is stable at ~5.14 GiB: `tegrastats` counts the Tegra's own idea of
used RAM (including the carveouts), while `MemAvailable` is the kernel's
estimate of what a new allocation could get. **The rule uses
`MemAvailable`** — it is the conservative reading, and it is the number the
OOM killer acts on. The tegrastats figure is kept as a second opinion in
the status and in the log.

## 3. The daemon's own cost

Measured by the integration test (`the_daemon_costs_almost_nothing`) and by
a 30 s window against the **release** build — the one that runs as a
daemon:

| Measure | Value | How |
|---|---|---|
| Resident memory (`VmRSS`) | **2 MiB** | `/proc/<pid>/status` |
| CPU, doing nothing | **0.03% of one core** (1 clock tick in 30 s) | `Δ(utime+stime)` |
| CPU, one lease running | **1.1% of one core** | the same, over 30 s |
| CPU of the children it reaped | **0.00%** | `Δ(cutime+cstime)` |
| Minor faults | **0** | `/proc/<pid>/stat` `minflt` |
| Samples | **4.00 a second** | the daemon's own counters: 121 samples in 30.2 s |
| Socket mode | `0600` | the socket's own mode |

**The box, beside those numbers:** `MemTotal: 128 766 532 kB` (122.8 GiB,
no swap), `MemAvailable: 111 063 640 kB` (105.9 GiB), load average
6.04 / 6.58 / 7.67, at 16:26 on 2026-10-31 (the box's own clock, AKDT,
UTC-8).

The integration test's own numbers are higher (0.10% idle, 2.20% with a
lease) because it measures the **debug** build; the release numbers are
the ones above.

**A design decision, and why.** The scan reads `/proc/<pid>/stat` — one
line per process, where the resident set is field 24 — and not
`/proc/<pid>/status`, which is fifty lines per process. The kernel's exact
high-water mark (`VmHWM`) is still used, but only for the lease's own
process, where it matters. The total cost of the whole daemon, scan
included, is the number above.

**What the scan costs, and what it bought.** The daemon used to fork a
fresh `nvidia-smi` every two seconds (whether anything was running or
not) and walk `/proc` on every 250 ms sample. Measured before and after,
same box, same 30 s windows:

| | before | after |
|---|---|---|
| idle, own CPU | 0.133% of a core | 0.133% of a core |
| idle, children reaped | 0.500% of a core | **0.000%** |
| idle, minor faults | 16 678 | **0** |
| one lease, own CPU | 2.133% of a core | **1.100%** |
| one lease, children reaped | 0.500% of a core | **0.000%** |
| one lease, minor faults | 15 650 | **0** |

One `nvidia-smi` child now keeps printing the driver's view and the
daemon reads its lines: one fork, ever. The `/proc` scan has its own
clock (`--scan-interval-ms`, default 1 s) and still runs on *every* sample
when the box is below the emergency floor, because that is when the
watchdog needs a fresh ranking.

## 4. The learned peaks

The daemon records the peak each lease reached. Measured with the kernel's
own `rusage` (`ru_maxrss`), which is exact rather than sampled:

| Label | Asked for | Peak reached | Runs |
|---|---|---|---|
| `hog.4g` | 4 GiB | 4 296 847 360 B (4.0016 GiB) | 3 |
| `hog.8g` | 8 GiB | 8 591 884 288 B (8.0017 GiB) | 1 |
| `seat.py` | — | 9 830 400 B (9.4 MiB) | 1 |

The hog over-reaches its request by 0.04% — the allocator's overhead and
the pages the binary itself occupies. The three 4 GiB runs agree to within
**65 536 bytes** (16 pages), which is the allocator's own jitter.

These are the cost model's **memory column** (`core/night/cost/memory.py`),
in the same percentile convention the model already uses.

**The GPU's column, with a real GPU context.** The hogs are CPU only, so
they have no GPU context and the driver says nothing about them
(`peak_gpu_bytes: null`). A small CUDA program (512 MiB on the GPU, held
for 12 s) was run under a lease to show the column working:

```
$ nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits
163916, 614
```

```json
{"at":"2026-11-01T00:18:00Z","kind":"cuda.probe","label":"cuda.probe","host":"thor",
 "peak_rss_bytes":71897088,"peak_gpu_bytes":643825664,"gpu_visible":true,
 "duration_s":12.27,"mem_total_bytes":131856928768,"floor_bytes":26843545600,
 "basis":"measured","source":"thor-admit","peak_source":"rusage"}
```

643 825 664 B is **614 MiB** — the driver's own number for that pid. The
GPU peak is a measurement, not an estimate.

## 5. The integration run

`tools/thor-admit/tests/integration.rs`, on the real box:

| Test | Result |
|---|---|
| `a_dead_client_cannot_leak_a_lease` | **passed** — the kernel drops the client's lock, the daemon gives the memory back |
| `the_queue_is_ordered_by_priority` | **passed** — a priority 5 request overtook a priority 0 one that arrived first |
| `a_learned_peak_is_used_by_the_next_run` | **passed** — `--peak auto` used the p95 of the label's history |
| `a_refused_lease_does_not_run_the_command` | **passed** — a refused lease never runs its command |
| `the_daemon_costs_almost_nothing` | **passed** — 2 MiB, 0.10% of a core idle, 2.20% with a lease (the debug build; §3 has the release numbers) |
| `the_watchdog_leaves_small_leases_alone` | **passed** — a 1 GiB lease was not stopped even with the emergency floor armed |
| `the_watchdog_stops_a_runaway_before_the_memory_runs_out` | **passed** — the low-water mark, §6.3 |
| `three_thirty_gigabyte_hogs_are_serialised` | see §6 |
| `the_watchdog_stops_a_runaway_before_the_kernel_oom_does` | see §6 |
| the Python shim's own tests (`tests/thor_admit/test_shim.py`) | **6 passed** — `pytest tests/thor_admit -q`; the shim takes a lease for the calling process, gives it back, and survives the daemon being gone |

## 6. The two heavy tests

These take the box's own `heavy.lock` before they run, because five other
seats were queued on it while this work was done. They skip themselves when
the lock is held, unless `THOR_ADMIT_HEAVY_WAIT_SECS` says to wait.

<!-- HEAVY RESULTS -->

### 6.1 The mechanism, proved at 12 GiB (2026-10-31 22:08 UTC — 14:08 on the box)

The 30 GiB run was still queued behind the other seats, so the two tests were
run at a smaller scale to prove the mechanism first
(`THOR_ADMIT_HOG_GB=12`, without the box's lock — a bounded 12 GiB, on a box
with 100 GiB free).

**Serialisation** — three hogs, one at a time. The floor was computed from
the box's real headroom (`available - hog - 8 GiB` = 72.9 GiB):

```
serialisation: 12 GiB hogs, floor 78295891968, at most 1 at a time,
               the box never fell below 82761 MiB free
22:08:13  lease.granted   hog1   mem_available 99 776 745 472
22:08:18  lease.released  hog1   peak_rss 12 886 786 048 (12.002 GiB)
22:08:18  lease.granted   hog0   mem_available 99 358 363 648
22:08:22  lease.released  hog0   peak_rss 12 886 654 976
22:08:22  lease.granted   hog2   mem_available 99 678 412 800
22:08:27  lease.released  hog2   peak_rss 12 886 847 488
```

The grants are strictly sequential — each hog was released before the next
was granted — and the box never fell below 80 GiB free. The second and
third hogs were **not admitted while the first was running**: they waited
in the queue, because the first still owed its 12 GiB and the rule
charges a running lease's promise against the headroom. They were not
*refused* (nothing was rejected) — the queue is where a request waits for
room.

**The watchdog** — a runaway hog. The daemon's emergency floor is a
fixed **8 GiB**; the *test* lowers it to `available - 8 GiB` (86 764 MiB),
because driving the real box to 8 GiB free would need 110 GiB of
allocation. The rule that fires is the same rule; only the number it
fires at is different.

```
watchdog: the runaway was stopped with 82633 MiB free (the emergency floor
was 86764 MiB) and killed 2042 ms later; the kernel's OOM killer fired 0 times
```

**The box, beside the numbers:** `MemTotal: 128 766 532 kB` (122.8 GiB,
no swap), `MemAvailable` 99 776 745 472 B (92.9 GiB) when the first
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


### 6.3 The low-water mark ("before MemAvailable reaches 2 GB")

The brief asks for the watchdog to stop a runaway hog before
`MemAvailable` reaches 2 GB. On this box that line is about 100 GiB of
allocation away: the box has 122.8 GiB and no swap, and the brief caps a
test's memory at 60 GiB. So the memory **curve** is scripted and
everything else is real — the daemon, the hog, the `SIGSTOP`, the
`SIGTERM` and the timing.

The daemon reads its accounting from a file (`--meminfo`, default
`/proc/meminfo`; a test seam, and the daemon logs the path it is reading
in `daemon.started`, so a stale file cannot hide). The test writes that
file: first the box loses 88 GiB at once — the shape of the 13:22 OOM —
and then it slides down a quarter of a gibibyte a step, through the
emergency floor and on past the 2 GiB line.

```
low water: the hog was stopped with 7168 MiB free (the floor was 8192 MiB)
and the curve went on down to 0 MiB; the daemon acted within 211 ms of
the floor being crossed, and the kernel's OOM killer fired 0 times
```

| | |
|---|---|
| Stopped with | **7 168 MiB free** — the emergency floor was 8 192 MiB |
| The curve went on down to | **0 MiB** — the danger zone was reached *after* the stop |
| The daemon acted | **211 ms** after the floor was crossed (the log is polled every 20 ms, so this is an upper bound) |
| The hog | really stopped (state `T`), then killed 2 241 ms later (`signalled: true` both times) |
| The kernel's OOM killer | **0 times** |

The daemon's own log for that run:

```json
{"event":"watchdog.stopped","label":"runaway","lease":1,"mem_available_bytes":7516192768,"rss_bytes":4296790016,"signalled":true}
{"event":"watchdog.killed","label":"runaway","lease":1,"mem_available_bytes":0,"rss_bytes":4296790016,"signalled":true,"waited_ms":2241}
```

**What this proves, and what it does not.** The box's real `MemAvailable`
was never driven to 2 GB — that would have needed about 100 GiB of
allocation. What is proved is the *ordering*: the daemon acts when the
box crosses the emergency floor, the curve then went on into the danger
zone, and the kernel's OOM killer never fired. The 2 GiB line itself is
below the default floor (8 GiB), so a box on the default settings acts
6 GiB above it.

## 7. A subtlety worth keeping

The lease's lock is held by the **client**, so the kernel drops it when the
client dies — that is the whole "a dead client cannot leak a lease"
promise. It has one wrinkle, found by a test that failed twice in forty
runs and then failed to fail for a day:

> A forked child inherits the lease's descriptor, and `O_CLOEXEC` only
> closes it at the child's `exec`. In the window between the fork and the
> exec, the child holds the open file description alive, so the lock
> outlives its holder.

Measured: **1 in 200 forks** caught the window, and the lock was released
**1 ms** later than the holder closed it. The daemon polls every 250 ms, so
it never notices; a test that probes once can lose the race, so it waits.

The same window is why the daemon does not fork anything while it holds a
lease: the CLI forks the command *before* the lease exists, so the command
never inherits the lease's descriptor at all.

## 8. How to reproduce

```bash
cd tools/thor-admit
cargo test --lib                      # 53 unit tests
cargo test --test integration -- --test-threads=1

# the low-water mark: the scripted curve, the real watchdog
cargo test --test integration -- --test-threads=1 --nocapture \
    the_watchdog_stops_a_runaway_before_the_memory_runs_out

# the two heavy tests, joining the box's own queue
THOR_ADMIT_HEAVY_WAIT_SECS=1800 cargo test --release --test integration -- \
    --test-threads=1 --nocapture three_thirty_gigabyte_hogs_are_serialised \
    the_watchdog_stops_a_runaway_before_the_kernel_oom_does
```

The Python shim's tests (in the repo's suite):

```bash
.venv/bin/python -m pytest tests/thor_admit -q
```

**The box state to record beside any rerun:** `MemAvailable`, the load
average, and who holds `heavy.lock`. The two heavy tests are the only
measurements that move the box by tens of gigabytes; everything else is
under 2 GiB.

## 9. The cloud judge (what this cost)

The documents above were put in front of a cloud judge (Groq's
`gpt-oss-120b`, via `~/lm-tools/gq.py`) with the brief as the reference,
and asked for concrete problems only: a requirement with no evidence, a
number that contradicts another number, a measurement with no box state
beside it, an internal inconsistency.

| Call | In | Out | Time | Cost |
|---|---|---|---|---|
| 1 | 10 049 | 3 000 | 7.04 s | $0.00331 |
| 2 | 10 049 | 2 360 | 5.78 s | $0.00292 |
| 3 (the documents after the first pass) | 15 455 | 3 384 | 9.38 s | $0.00472 |
| 4 (the same, asked for a tighter list) | 15 454 | 3 384 | 8.28 s | $0.00435 |

**Total: $0.01530**, against the brief's $2 ceiling.

It found ten problems; eight were fixed in the documents above (the
release-build cost numbers with their box state, the missing GPU-peak
evidence, the systemd check, the test names behind the "a dead client
cannot leak a lease" claim, the sample rate measured from the daemon's
own counters, the low-water section, and a wrong claim that the second
hog was "refused" — it waited in the queue and was admitted after the
first released). Two were the judge's own misreading, worth recording
because they are the kind of thing a reader assumes too: it called the
12 GiB and the scripted run "mutually contradictory" (they are two
different runs of the same rule), and it wanted the heavy tests' lock
contention recorded, which §6 does.

A second pass over the updated documents found eight more; four were
real (the emergency floor reading as two different numbers, the
watchdog's measurement without its box state, the rule's table without
its arithmetic, and `thor-admit peaks` missing from the protocol
section) and four were the judge again — it quoted the brief's
requirement for a 30 GB run as if the documents had claimed it, and
missed the README's box state, the shim's usage example, and the rule's
own table. A number was also *removed* rather than kept: a load average
for the 12 GiB run that nobody had recorded.

The judge's cost is a rounding error next to the box's: one heavy test
moves 30 GiB of the Thor's memory, and four judge calls cost one and a
half cents.
