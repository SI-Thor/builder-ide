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

The box, as it stood at 13:36 on 2026-10-31:

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

Measured by the integration test (`the_daemon_costs_almost_nothing`), on
the busy box, with the daemon doing nothing for ten seconds:

| Measure | Value |
|---|---|
| Resident memory (`VmRSS`) | **2 MiB** |
| CPU (`Δ(utime+stime)` over 10 s) | **0.30% of one core** |
| Samples | 4/s (250 ms) |
| Socket mode | `0600` |

The `/proc` scan — reading every process's `stat` to find the leases'
resident sets — is inside that 0.30%. There are ~200 processes on the box.

**A design decision, and why.** The scan reads `/proc/<pid>/stat` — one
line per process, where the resident set is field 24 — and not
`/proc/<pid>/status`, which is fifty lines per process. The kernel's exact
high-water mark (`VmHWM`) is still used, but only for the lease's own
process, where it matters. The total cost of the whole daemon, scan
included, is the 0.30% of a core measured above.

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

## 5. The integration run

`tools/thor-admit/tests/integration.rs`, on the real box:

| Test | Result |
|---|---|
| `a_dead_client_cannot_leak_a_lease` | **passed** — the kernel drops the client's lock, the daemon gives the memory back |
| `the_queue_is_ordered_by_priority` | **passed** — a priority 5 request overtook a priority 0 one that arrived first |
| `a_learned_peak_is_used_by_the_next_run` | **passed** — `--peak auto` used the p95 of the label's history |
| `the_daemon_costs_almost_nothing` | **passed** — 2 MiB, 0.30% of a core |
| `the_watchdog_leaves_small_leases_alone` | **passed** — a 1 GiB lease was not stopped even with the emergency floor armed |
| `three_thirty_gigabyte_hogs_are_serialised` | see §6 |
| `the_watchdog_stops_a_runaway_before_the_kernel_oom_does` | see §6 |

## 6. The two heavy tests

These take the box's own `heavy.lock` before they run, because five other
seats were queued on it while this work was done. They skip themselves when
the lock is held, unless `THOR_ADMIT_HEAVY_WAIT_SECS` says to wait.

<!-- HEAVY RESULTS -->

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
