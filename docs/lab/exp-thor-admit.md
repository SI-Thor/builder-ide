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

---

# Round 7 — the presence scheduler (2026-10-31, 21:26–21:29 AKDT)

The second half of the brief. Round 6 answered "may this heavy thing
start?"; round 7 answers "what should the box be doing with the time
nobody is using?" — and measures the answer.

**The question.** At 20:38 the GPU sat at idle power (VDD_GPU 3.1 W), 12 of
14 cores were near 0 %, and about 80 GB were free, while the seats waited
on cloud LLMs. The box was mostly waiting, and nothing in the system said
so, because nothing in the system knew what the box could have been doing.

**What was built.** A **presence queue** of registered work (a command, a
tier, an estimated peak, a resumability flag), and a **ledger** that books
the box's time by tier and names the cause of every idle second.

**Verdict: useful — the queue runs the box's own work, live work takes it
back in 0.28 s, and the ledger explains 100 % of the idle time it saw.**

## 10. The setup

| | |
|---|---|
| Box | Thor, Linux 6.8.12-1021-tegra, aarch64, 122.8 GiB unified, no swap |
| Load during the run | 16.25 / 16.33 / 16.17 (the box was busy with a seat's work) |
| `MemAvailable` | 48.5 GiB at 21:43, 47.7 GiB at 21:45 |
| Build | release (`cargo build --release`) |
| Memory used by the test | **none**: the presence job was a `sleep`, the leases were `sleep`s |

The script is `tools/thor-admit/measure-presence.py`; it starts a daemon
in a temporary state directory, registers work, takes a lease, reads the
ledger and prints the daemon's own log.

## 11. The daemon's cost, with the ledger on

30 s windows, the release build:

| | idle | one lease and one presence job |
|---|---|---|
| Resident memory | 2 304 KiB (2.25 MiB) | 2 560 KiB (2.50 MiB) |
| CPU, its own | 0.20 % of one core | 0.80 % of one core |

Round 6 measured 2 MiB and 0.03 % of a core idle on the same box. The
extra is the ledger: a sample every 250 ms, `/proc/stat` once a second,
and the GPU's children read every tick instead of every eighth one. The
ledger wants the GPU's power and busy share **when the box is doing
nothing** — "the GPU was idle at 3.2 W" is one of the numbers it exists to
keep, and it cannot be read after the fact.

## 12. The ledger, two windows

**21:44–21:45 AKDT** — the seat's work was on the GPU that minute (51.0 s,
204 samples):

| | |
|---|---|
| live tier | 44.5 s running |
| study tier | 1.0 s running, **44.25 s stopped** by the GPU pre-emption (1 pre-emption) |
| idle | 5.75 s — all `no_work_registered` |
| **unattributed** | **0.0 s (0 %)** |
| GPU power | 39 388 mW mean, 47 548 mW max (`tegrastats`, 204 samples) |
| GPU busy share | 90.0 % (204 samples, `nvidia-smi`) |
| CPU busy share | 0.993 of the box; 14 cores |
| Free memory | 47.7 GiB lowest, 48.4 GiB highest |

**21:27–21:28 AKDT** — the GPU was idle and the seat's work was on the
CPU side (51.5 s, 206 samples):

| | |
|---|---|
| live tier | 44.75 s running |
| study tier | 45.5 s running, 1 run |
| idle | 6.0 s — all `no_work_registered` |
| **unattributed** | **0.0 s (0 %)** |
| GPU power | 3 201.6 mW mean, 5 116 mW max (`tegrastats`, 206 samples) |
| GPU busy share | 0 % (206 samples, `nvidia-smi`) |
| CPU busy share | 0.667 of the box; 14 cores |

Three things worth keeping:

* The GPU's **3.2 W** in the second window is the same reading as the
  20:38 note (3.1 W), two hours and a half later, and now it is in a
  record rather than in somebody's memory. The GPU was idle while the CPU
  was busy: the box's work was not GPU work.
* The first window is the **GPU pre-emption** doing its job: the seat's
  work wanted the GPU, and the presence job gave its streams up for 44
  seconds and ran again afterwards.
* Both windows had **nothing unattributed**. The idle time was the few
  seconds before the work was registered, and the ledger said so.

## 13. The pre-emption, on the real box

The presence job was registered with a 4 GiB peak and held none of it; the
live lease asked for 2 GiB; the floor was 62.5 GiB — the number that makes
the presence job's reservation exactly what stands between the live lease
and the room.

```
21:45:50  presence.started    measure.preempt  peak 4 GiB   mem_available 51 238 248 448
21:45:50  presence.preempted  measure.preempt  live_label measure.live2
21:45:51  presence.finished   measure.preempt  exit 143 (SIGTERM)  state preempted
21:45:51  lease.granted       measure.live2    peak 2 GiB
21:45:56  presence.started    measure.preempt  peak 4 GiB      ← it resumed
```

| | |
|---|---|
| The live lease was admitted after | **0.279 s** (the client's own measurement) |
| The pre-emption was logged | in the same second as the request |
| The job's exit | 143 — 128 + SIGTERM, the signal the daemon sent |
| The job's state afterwards | `preempted`, and resumable, so it was not lost |
| The kernel's OOM killer | 0 times |

**And it resumed five seconds later, and the arithmetic says why.** While
the live lease ran, the presence job's 4 GiB did not fit beside the live
lease's 2 GiB promise:

```
available          51 238 240 256   (47.73 GiB)
- live lease owes    2 145 700 000   (2 GiB promised, 1.8 MB used)
- presence job peak  4 294 967 296   (4 GiB)
= headroom          44 797 572 960   (41.73 GiB)   <  floor 42.9 GiB  → no
```

When the live lease ended, its 2 GiB came back, the headroom became
43.7 GiB, and the job started again. That is the rule working, not the
rule being slow.

## 14. A bug the measurements found

The first ledger had **no GPU busy share** (`busy_samples: 0`) even though
the daemon was reading the driver's own line every tick. The reason: the
daemon's query asks for `nounits`, so the line is `0, 3.15`, and the
parser was looking for the `%` and `W` suffixes that `nounits` removes. The
parser now reads a unit-less line positionally, in the order the query
asked for, and the unit test says so.

It is worth recording because the number was *missing*, not *wrong*: a
ledger that quietly drops a column looks exactly like a ledger whose column
is zero.

## 15. A second bug: a lease booked from the wrong moment

The integration run for the ledger failed **five times in six** — and it
passed when it was run on its own, which is what made it interesting.

The failing bucket said:

```
"idle":{"by_reason":{"no_work_registered":1.0,"unattributed":0.25},"total_s":1.25}
"tiers":{"live":{"running_s":4.25},"study":{"running_s":0.5,"preempted_s":4.0}}
```

A quarter of a second of idle time that the ledger could not name. The
daemon's own log said why:

```
lease.granted      live.test
presence.started   presence.test
presence.gpu_stopped  (the GPU was at 95 % — the seat's work)
```

**The cause.** The daemon answers `granted`, and the client answers
`held` — but the `held` is handled in the *next* tick of the inbox, so for
a whole sample interval the lease was committed while the ledger did not
count it. In that window the presence queue had not started (the client
queue was not empty when the tick ran), so the box looked idle, and the
idle classifier had no cause for it.

The fix is one line and it is the right one: **a lease is booked from the
grant, not from the confirmation**, because the memory is committed at the
grant — that is exactly what the admission rule charges.

After the fix: eight runs in eight pass. The test now prints the daemon's
log when it fails, which is how the window was found in the first place.

It is worth keeping in the record because the number that moved was
`unattributed` — the one the brief says should be zero — and it moved
because of a **one-tick** window. A ledger that is wrong by one tick is
still wrong.

## 16. How to reproduce

```bash
cd tools/thor-admit
cargo build --release
python3 measure-presence.py          # about four minutes
```

The heavy tests still take the box's own lock; these do not need it,
because they allocate nothing.

## 17. What this did not settle

* **What should be in the presence queue.** The queue is a file, and the
  file is empty until somebody puts something in it. The ledger can say
  how much time went to `no_work_registered`; it cannot say what *should*
  have been there. That is a question for the night runner and the seats.
* **Whether `SIGSTOP` is the right way to give the GPU back.** It stops the
  whole process group, so the job's CPU work stops too. The driver's CUDA
  stream priorities would be finer; they were not measured here.
* **A full hour.** The ledger's unit is the hour and the run above is 51
  seconds of one. The hour rollover is unit-tested; a real hour of the
  box's own time is §19 now (measured 2026-11-01, round 9's item 5).

## 18. Round 9: the no-op that taught a 3.6 MB reserve

The director's overnight watch (2026-11-01, ~01:35 AKST) caught the
daemon's learned peaks trusting runs that did no work. This section is
the incident, the rule that closes it, and what the round's own testing
found on the way.

**The incident, from the box's own records.** At 00:47 the sweep
wrapper's no-op invocations wrote 25 records into `peaks.jsonl`, one per
biome — every one `duration_s` under 0.03 and `peak_rss_bytes` 3 801 088
(the wrapper binary's own footprint, 3.6 MB). The director removed them
at 00:50 (`peaks.jsonl.bak-0048` keeps them), but the daemon had loaded
them at 00:45 and kept them in memory. At ~01:12 a lease for
`infinigen.mountain.coarse` was **granted with `peak_bytes` 3 801 088**
— the p95 of 25 no-ops — and by 10:12 UTC it was using
1 173 307 392 B (1.09 GiB), 308× its reserve, with the over-run watch
writing the real peaks into the history while it ran:

```
{"event":"lease.underreserved","label":"infinigen.mountain.coarse","lease":39,
 "reserved_bytes":3801088,"peak_rss_bytes":1173307392,
 "over_by_bytes":1169506304,...}
```

The over-run watch (round 8) kept the box safe — the lease was visible,
logged and corrected while it ran — but the *reserve* was nonsense, and
a nonsense reserve is what the history is for.

**The rule.** A run teaches the history only if it **exited 0** (the
client now reports its exit status on release) **and lasted at least
5 s** — applied when the record is written *and* when the file is read,
so no-ops already in a file are ignored however many of them there are.
The one exception is the over-run record, which always teaches: it is
written only past a gross over-reservation and can only raise a
reserve. A model server that never exits cleanly (a seat stops it with
a signal) keeps its explicit `--peak` — over-reserving is the safe
direction.

**The reload.** The history and the presence queue are loaded once, so
the director's 00:50 edit never reached the running daemon, and the
only cure was a restart — which waits for a box with no leases.
`thor-admit reload` (and `SIGHUP`) re-read both files and touch nothing
that is running. The incident is a test:
`a_no_op_run_cannot_teach_the_reserve` seeds the daemon's history with
the exact 25 records, watches a live no-op fail to teach, hand-teaches
the label with three real records, reloads, and takes the learned peak.

**Two bugs the round's own tests found.**

*The daemon that idled out but did not exit.* A test daemon idled out
under a waiter the GPU's floor was holding, and hung the suite for half
an hour. The cause: the CLI's signal watcher waited for a signal, and
only a signal — after an idle exit the daemon's clock had left, the
process stayed alive in `watcher.join()`, and it kept the socket's
flock, so every later daemon on that socket was refused with "another
thor-admit daemon is already running" while the log said `idle_exit`.
Fixed twice over: the watcher takes the daemon's own `is_stopped` word,
and a non-empty queue counts as activity — a daemon with a client
waiting for room has something to do.

*The tests read the box's real GPU pool.* With other seats' CUDA work
holding `lfb` at 0.15–0.4 GiB — under the 2 GiB `--gpu-floor` — every
CPU-only test lease waited on the GPU's rule, because `gpu_admits`
applies the pool's floor to every lease including one that promises no
device memory. On the live box that is the designed rule doing its job
(below); in a test it is another seat's CUDA allocations deciding a
CPU-only test's admission. Test daemons now start `--gpu-probe off`.

**`serve`, keyed on the model** (the 01:19 incident). Three d1-2B
servers ran as `d1-2B`, `d1-2B-baseline` and `d1-2B-batch` because the
registry deduped by the name a seat typed. The registry now keys on the
model file (resolved path + a streamed FNV-1a content hash) plus the
config tuple (the command minus the model file and the port). At 02:10
the box was still paying for the old keying: a second d1-2B server was
admitted under the name `d1-2B-baseline` while `serve.d1-2B` (8 GiB
reserved, 830 MiB used) was already answering. Entries from the
name-keyed build keep their old key until their servers go.

**The tests, on this box, 2026-11-01 ~02:45 AKST (load ~11, `lfb`
swinging 0.15–2 GiB, other seats' work running):**

| Suite | Result | Time |
|---|---|---|
| unit (`cargo test --lib`) | 116/116 | 0.03 s |
| integration (serial, the default) | 30/30 | 146.6 s |
| the Python shim | 10/10 | 24.7 s |

The teaching runs in the learned-peak tests now outlast the five-second
line, because that is what a teaching run is; the suite grew by four
tests (the no-op, the SIGHUP reload, the two-names serve, the by-label
ledger with the flow signal).

## 19. The one-hour measurement, on the real load (item 5)

Round 9's item 5: measure one hour of the box under the daemon with the
real load, and read the ledger's tier split, the minimum `MemAvailable`,
the refusals and the pre-emptions.

**What ran.** The daemon in tmux `last-mile:admitd` since 00:45 AKST
(the round-8 binary — the round-9 binary was shipped to
`~/lm-tools/thor-admit` at 02:50, and the swap waits for a moment with
no leases, which two model-server leases 3.8 h and 2.3 h long never
offered; `reload`, once the new daemon is in, is how cleanups reach it
without a restart at all). The hour is **12:00–13:00 UTC on 2026-11-01
(03:00–04:00 AKST)**, the ledger's own closed bucket `T12`, with a
per-minute status sampler alongside (56 samples in the window).

**The box, beside every number:** `MemTotal` 122.8 GiB, no swap; free
memory 89.3–100.6 GiB for the whole hour; load 4.8–7.0 falling from a
~24 peak earlier; 10 tmux windows of seats' work plus the sweep;
`oom_kill` 0 before, during and after.

| What item 5 asked for | The hour's answer |
|---|---|
| tier split | **live 3 723.5 s of 3 724 s (100 %)**; preparation, practice, study: 0 s; idle 0.0 s, `unattributed` 0.0 % |
| minimum `MemAvailable` | **89.3 GiB** (of 122.8 GiB; never within 81 GiB of the 8 GiB emergency floor) |
| refusals | **0 refused, 0 granted** — 3 new arrivals were queued (positions 19–21) and none admitted in the hour |
| pre-emptions | **0** (no `presence.preempted`, no `watchdog.*`, no OOM kills) |
| GPU | 8.0 W mean / 44.0 W max (`tegrastats`), busy share 10.1 % mean |
| CPU | 14 cores, mean busy share 0.217 (one core at 0.64, the rest under 0.2) |

**The finding the hour actually carries.** The box was safe — two
model-server leases held 16 GiB reserved against ~1.5 GiB used all
hour, the watchdog had nothing to do — and simultaneously **not at full
presence**: 18–21 ready requests sat in the queue for the entire hour
while 89–100 GiB stood free and the GPU idled at 8 W and 10 %. Nothing
was refused; nothing fit either. The reason is the GPU's own allocation
pool: `lfb` stayed between 0.14 and 1.5 GiB, under the 2 GiB
`--gpu-floor`, and the pool rule (round 8, Hy4's third failure mode)
holds every lease — including CPU-only work — while the pool is thin.
The daemon's own log names it precisely, once per waiter:

```
{"event":"lease.waiting_for_gpu_memory","label":"d1-2B-batched",
 "label_gpu_peak_bytes":0,"gpu_free_bytes":511705088,
 "gpu_floor_bytes":2147483648,...}
{"event":"lease.waiting_for_gpu_memory","label":"syzygy-keyframes.d1kf-cpu",
 "label_gpu_peak_bytes":8984199168,"gpu_free_bytes":3573547008,...}
```

The second line is the pool rule working as designed: that label has
*learned* a 8.98 GiB device-memory promise (a llama-server with
`-ngl 99`, whatever "cpu" is doing in its name), and admitting it into
a 3.5 GiB pool would have been the exact `cudaMalloc` failure the rule
exists to prevent. The first line is the open question: a lease that
promises **zero** device memory, held by a floor protecting a pool it
will never touch. The last time the pool recovered above the floor
(10:43 UTC), a burst of three leases was admitted within the same
second — the queue drains the moment the rule lets it.

So the honest split of the hour: **the memory rule and the watchdog did
their jobs** (no incident, no kill, no unexplained second), and **the
presence scheduler had nothing to say** — no background tier ran a
second, because live requests were waiting and the pool never opened.
"The Thor is always at full presence" is measured false tonight for a
reason no lease caused: ~40–70 GiB of other seats' CUDA allocations
(the physag, cad and coldshelf work, outside the daemon's leases) held
the non-reclaimable pool shut. That is the design record's open
question §11.8 with an hour of evidence behind it.

**Two smaller observations, kept for the record.**

*Zombie waiters.* A client that dies while queued leaves its waiter in
the queue: the daemon only discovers the dead reply channel when it
tries to grant, and a queue that never fits never tries. Two of the 21
waiters in this hour were the round's own killed hog probes
(`hog.4g`, 12:06 UTC). Harmless while blocked and self-healing on the
next grant, but a queue depth of 21 overstates the live demand by at
least two — a waiter whose client pid is gone could be reaped on the
same liveness pass the leases get.

*The disabled examples.* The round ships the three cheapest
PRESENCE-JOBS.md proposals as disabled examples in
`presence.default.json`, but they could not be registered on the live
daemon: it predates `presence add --disabled`, and registering them
enabled would have run the placeholder `echo` and called it a night's
work. They register at the daemon swap; the hour's presence queue held
one real job (`syzygy-keyframes.d1kf`, pending — correctly, behind
waiting live work and a pool it has learned to need 8.98 GiB of).

**Reproduce:** the ledger is the daemon's own
(`thor-admit ledger --hours 2`), the per-minute sampler is 60 calls to
`thor-admit status --json`, and the window's events are grepped from
`~/.local/state/thor-admit/daemon.log` between the two UTC stamps.

## 20. Round 10: the hour above, answered (2026-11-01, ~04:30 AKDT)

Section 19's hour left §11.8 open with 21 waiters held by a 2 GiB floor on
`tegrastats`' `lfb` while `MemAvailable` sat near 100 GiB. The director's
watch overnight added the decisive number — those 21 requests were held
**for over an hour** — and moved the live daemon to `--gpu-floor 0` by
hand. Round 10 put the code where the operator already was, and the
hardware fact underneath it is in `docs/design/thor-admit.md` §14.1:
`lfb` (`7x4MB`) counts the allocation pool's *contiguous* free blocks, a
fragmentation signal, while the GPU's real budget on unified memory is
`MemAvailable` — already governed by the memory rule. A default floor on
`lfb` therefore double-governs the same bytes and bites exactly when the
pool is fragmented and the box is otherwise empty, which is what the hour
measured.

Two changes, each with its test in the integration suite:

* the default `--gpu-floor` is **0** (the rule is still there for an
  operator who asks for it);
* a lease whose label has never held device memory **skips the pool
  rule** (`a_cpu_only_lease_is_not_held_by_the_gpus_pool`: the same 8 MiB
  scripted pool and 1 GiB floor that holds a GPU-holding lease in
  `a_lease_waits_when_the_gpus_own_pool_is_thin` lets a fresh CPU-only
  label straight through). The promise is learned, so the risk — a first
  run touching CUDA unmeasured — stays; if it takes device memory, its
  own history makes the next run wait for the pool.

The same round fixed the 04:15 wedged startup (bind before the lifetime
lock, plus a 15 s `--startup-timeout-secs`; reproduced with a test seam
that hangs the daemon where the old order left the box wedged) and made a
queued client ride out a daemon restart by asking again instead of dying
(`a_queued_client_rides_out_a_daemon_restart`).

**The suite after the changes:** 34/34 serial, 203 s, load 5.7–7.5 (other
seats: a `serve` d1-2B on 8094, a `d1-2B-baseline` lease, the coldshelf
paint chain), `MemAvailable` 86 GiB — the heavy tests ran for real, under
the box's stopgap lock, and left nothing running behind them.

**Reproduce:** `cargo test --test integration` (serial is the default);
the two pool tests bring their own scripted `tegrastats` via
`--tegrastats-command`, so they touch no GPU.
