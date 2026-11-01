# exp-ct-thor — the crew's constraint code, measured on the AGX Thor (2026-10-31)

Casey's brief: the SuperInstance constraint repos were built against an RTX 4050
laptop GPU (6 GB, PCIe), AVX-512 CPUs, and a 4-thread Jetson. We rebuilt the five
ranked ideas for this box and measured. Harnesses: `probe.cu`, `exp1_ce_resident.cu`,
`exp2_flux_exact.cu`, `exp3_crossover.cu`, `exp4_hdc.cu`, `exp_diag.cu`,
`crdt-bench/` (Rust), `exp5b_judge_bench.py`. All builds local, all runs under
`flock ~/lm-wt/heavy.lock` with ≥ 25 GB free (`free -g` checked before each run;
peak use ~9 GB of the 60 GB cap).

**The box, measured at run time** (probe.cu, driver 595.78, CUDA 13.2):
NVIDIA Thor, compute capability **sm_110** (Blackwell), **20 SMs**, **32 MB L2**,
**122.8 GB unified LPDDR5X**, 256-bit bus, measured triad **239.7 GB/s**.
`cudaMallocManaged` returns one pointer used by both sides (device pointer ==
host pointer, verified by writing from host and reading in-kernel);
`hostNativeAtomicSupported = 1`, `concurrentManagedAccess = 1`. CPU: **14
Neoverse (V3AE) cores**, aarch64, 128-bit NEON; gcc also emits SVE2 where it
auto-vectorizes plain loops. No AVX-512 exists on this machine.

Every number below was taken while the box's other heavy jobs waited on the same
lock; each figure is best-of-N (N ≥ 3, more for sub-10 µs work). Where a
measurement was run twice (the exp_diag table in §1 and the float/host-read
rows in §2), both runs are shown as a range: absolute times on this shared box
swing up to ~2× with the GPU's clock state between runs, while within-run
ratios — which carry the mechanism — repeat closely.

---

## 1. cuda-constraint-engine, resident at 20× scale

**Hardware fact.** sm_110 with the LPDDR5X pool shared by CPU and GPU at one
pointer. 10⁸ int32 constraints are 1.20 GB of values-plus-bounds and a 12.5 MB
violation mask — 1.2 % of the box's memory, permanently resident, visible to
both sides at the same address.

**What limited it before.** The README benchmarks "from actual RTX 4050 Laptop
GPU (sm_89)": 10⁷ constraints in 8.5 ms = 1.17 B checks/s, with the note "The
system is memory-bound, not compute-bound." The engine's `ce_check_i32` path
`cudaMemcpyAsync`s the values in and copies the mask back on **every call**,
and the pool is `cudaMalloc` device memory — the PCIe-coupled shape.

**The Thor path.** Built for sm_110. Part A runs the stock engine at its
published size. Part B holds values, bounds, and mask in unified memory
(device pointer == host pointer) and calls the repo's own
`launch_bounds_check_i32` + `launch_violation_count` kernels 100 times with
zero copies; between calls the host rewrites 1000 bounds **in place**, and the
GPU sees them on the next launch (verified: post-mutation mask words match a
CPU recount, 0/32 mismatches; GPU violation count 95,076,017 of 10⁸).

**Numbers.**

| path | size | time/call | throughput |
|---|---|---|---|
| README, RTX 4050 (published) | 10⁷ | 8.5 ms | 1.17 B/s |
| [A] stock `ce_check_i32` on Thor, first call (incl. copies) | 10⁷ | 3.83 ms | 2.61 B/s |
| [A] stock, steady state (best of 20) | 10⁷ | 3.03 ms | **3.30 B/s** |
| [B] resident unified, repo kernel, 100 calls | 10⁸ | 4,897 ms | 0.02 B/s |
| diag D2: same kernel, `cudaMalloc` pool, 10⁸ | 10⁸ | 26–54 ms | 1.9–3.9 B/s |
| diag D3: resident unified, **non-atomic** byte mask | 10⁸ | **6.7–10.1 ms** | **9.9–14.9 B/s** |
| diag D6: pure stream (int32 read + byte write), memory floor | 2×10⁸ | 6.1–10.3 ms | 98–165 GB/s |

Ranges cover two full diag runs on the shared box; absolute times swing ≈ 2×
with the GPU's clock state between runs, but the within-run ratios — which is
where the mechanism lives — are stable (D3 sits on the D6 floor at 0.98× and
1.11× in the two runs; the managed-atomic penalty below is 130× and 188×).

**Did the "memory-bound" limit move? Yes — and it was never bandwidth.**
Even on the 4050, 8.5 ms for ~120 MB of traffic is 14 GB/s, an eighth of that
card's bandwidth: the shipped kernel is bound by its own violation mask, which
does one `atomicOr` per violated element, and the crew's benchmark data pattern
violates ~95 % of the time. The diagnostics separate the two things the README
conflated. Atomics on **device** memory run 1.9–3.9 G/s (D2, 26–54 ms).
Atomics on **managed** memory take a slow path — ~70 ns each (D1: 4.88–6.92 s;
D4 with the violation rate cut to ~5 % still 274–566 ms) — so the literal
resident-unified run of the shipped kernel is 130–190× slower than the same
kernel on device memory. Change the mask write from an atomic bit-set to one
byte per value and the resident unified path runs at **9.9–14.9 B checks/s**,
10 ms or less per 10⁸-constraint call, at 98–165 GB/s — exactly the kernel
shape's memory floor (D6), still under the 240 GB/s triad ceiling because of
byte-granular mask stores and one-element-per-thread indexing. The bandwidth
wall itself moved less than the copy-and-residency story: 192 GB/s (4050) →
240 GB/s (Thor) is 1.25×; the engines-level win is 2.6–2.8× on the stock path
from the sm_110 rebuild alone, ~10–15 B/s on the non-atomic path, and a working
set that no longer exists as an "upload" concept at all.

**What it makes possible in builder-ide.** Tiles validation and the night's
rails are the same shape: a whole build's constraint set (per-layer precision
bounds from the flux-lucid idea) checked every tick against values that the
host is actively mutating. On this box that is one resident 1.2 GB set checked
in 10 ms, with the rails rewritten by CPU code between ticks — the demonstrated
host-mutation-visible-to-GPU loop, no staging, no upload API. Per-layer
precision (flux-lucid's stakes tiers) matters doubly here because of the FP64
finding in §2.

---

## 2. flux-gpu, with no copy-back

**Hardware fact.** The error mask (1 byte per value) lives in the same pool as
everything else; the CPU can read it in place after a sync, and the copy engine
moves it at DRAM speed if you ask.

**What limited it before.** The repo's README: "The bottleneck is VRAM
bandwidth (~160 GB/s effective out of ~256 GB/s theoretical)" on the 6 GB 4050,
with a benchmark table that stops at 10⁷ values because the doubles (8 GB at
10⁹) do not fit in 6 GB. Everything at 10⁹ was PCIe-shaped: chunked uploads,
chunked read-backs.

**The Thor path.** The repo's `exact_check_kernel` (pasted verbatim into
`exp2_flux_exact.cu`), 10⁹ values × 8 double-precision range constraints, all
buffers unified, with kernel time and host mask-read time measured separately —
plus an explicit `cudaMemcpy` D2H of the same mask to price the old copy-back,
and a diagnostic sweep of element types to find the real wall (exp_diag D5–D7).

**Numbers** (N=10⁹, M=8, values 8 GB + mask 1 GB, ~78 % violate per the repo's
own constraint pattern; NaN handling verified, 0 mismatches on a 1 M sample):

| step | time | rate |
|---|---|---|
| kernel, double (as shipped) | 453.1 ms | 17.7 G checks/s (≈ 20 GB/s effective) |
| diag: same loop, float | — | **84–166 G checks/s** (9.6–19.0 ms at 2×10⁸; 9.4–10.2× the double rate) |
| host reads mask in place, 1 thread | 48–66 ms | 15–21 GB/s |
| host reads mask in place, 14 threads | 9.6–13.1 ms | 76–104 GB/s |
| `cudaMemcpy` D2H of 1 GB mask | 11.0 ms | 91 GB/s |

**The honest mechanisms.** Two of the unlocks doc's predictions invert here.
First, the kernel is *not* memory-bound on the Thor: 9 GB of traffic in 453 ms
is 20 GB/s, a twelfth of DRAM. The wall is the **FP64 pipe** — the Thor iGPU
cuts FP64 hard next to FP32, and the kernel does two double compares per
constraint. The identical loop on `float` runs 9.4–10.2× faster (84–166 G
checks/s across two diag runs); that, not bandwidth, is what the crew should
change. Second, the copy-back this
experiment was designed to eliminate is already gone as a *cost*: on one box,
`cudaMemcpy` of the 1 GB mask (11 ms, 91 GB/s) and a 14-core in-place read
(13.1 ms, 76 GB/s) are the same speed — both are just DRAM traffic. What
unified memory actually removes is the **upload side**: on the 4050, 8 GB of
values could not be resident at all and every byte crossed PCIe; here the
values never move. The copy was never the bottleneck to remove; the precision
was.

**What it makes possible in builder-ide.** The first mile's reflex gating —
every incoming value NaN-checked and range-checked against the constraint set
before anything downstream sees it — becomes a float-path kernel at ~84–166 G
checks/s whose mask the decision loop reads in place. The NaN guard (the
repo's own) is the part that matters: the first mile is where sensor garbage
arrives.

---

## 3. The GPU-vs-AVX-512 crossover

**Hardware fact.** A CUDA Graph turns a kernel launch into a ~4 µs replayable
object. The CPU side has 128-bit NEON (and SVE2 through gcc auto-vectorization)
— half the legacy AVX-512 register width per instruction, no AVX-512 at all.

**What limited it before.** The corpus's own table: "AVX-512 (20 constraints)
35.9B/s | GPU (RTX 4050) 1.02B/s" — the GPU lost because launch overhead
dominated small batches.

**The Thor path.** The 20-constraint AND chain (the `avx512-constraint-checker`
workload: value passes iff it sits in all 20 windows) ported twice: a CUDA
kernel captured in a CUDA Graph, and the same loop in NEON intrinsics under
OpenMP across the 14 cores. Sizes 20 / 10³ / 10⁶ / 10⁸, per-value pass byte
written out on both sides (no early exit on either — the published 35.9B/s
included a bloom pre-filter and early exit, so it is not like-for-like and was
measured on an x86 part this box doesn't have).

**Numbers** (checks/s = values × 20, the corpus's own metric):

| N | GPU graph | GPU checks/s | CPU NEON 1T | CPU NEON 14T | CPU scalar 14T |
|---|---|---|---|---|---|
| 20 | 4.7 µs | — | 0.4 µs | 0.195 ms | 0.151 ms |
| 10³ | 4.9 µs | 4 G/s | 6.4 µs | 0.144 ms | 0.234 ms |
| 10⁶ | 49.4 µs | 405 G/s | 6.16 ms | 1.02 ms | 1.72 ms |
| 10⁸ | 4.46 ms | **448 G/s** | 616 ms | 68.9 ms | 117 ms |

**The crossover.** Against the 14-thread CPU, the graph-launched GPU wins at
**every measured size** — the OpenMP fork alone costs 120–195 µs, more than any
GPU launch here. Against single-threaded CPU the crossover sits between 20 and
10³ values (a few hundred: GPU launch ≈ 4.7 µs flat, CPU at 0.4 µs for 20
values, 6.4 µs at 10³). The corpus's crossover is gone: CUDA Graphs moved it to
batch sizes so small that "should this go to the GPU?" stops being a tuning
question. Two side findings for the ARM notes: explicit NEON intrinsics beat
gcc's auto-vectorized scalar loop by 1.5–1.7× at 10⁶–10⁸ on these cores —
the corpus's "auto-vectorization is faster than explicit SIMD" (measured on
Ampere N1) flips on V3AE; and the honest Thor-CPU equivalents of the 35.9B/s
AVX-512 figure are 3.25 G checks/s single-thread and 29 G/s on 14 threads.

**Which unit does the work.** SIMT integer compare lanes on the GPU; NEON/SVE2
integer pipes on the CPU. No tensor cores anywhere in this experiment — there
is no GEMM shape to give them.

**What it makes possible in builder-ide.** One validation path instead of a
tuned dispatcher: batches below a few hundred values run on one CPU core,
everything else goes through one pre-captured graph. Tiles validation can run
the same compiled check set from the editor (tiny batches) and the night's
rails (10⁸ batches) without a second code path.

---

## 4. flux-hdc on the GPU

**Hardware fact.** A 1024-bit hypervector is 16 × 64-bit words; Hamming
distance is 16 XOR + 16 POPC + 15 adds. `__popcll` is a SIMT instruction on
the CUDA cores' integer pipe. The database of 10⁶ hypervectors is 128 MB —
4× the 32 MB L2, a rounding error in the 122.8 GB pool.

**What limited it before.** The repo's C baseline (5.5B comparisons/s claimed)
is AVX-512 `VPOPCNTDQ` over 128-bit *folded* vectors — an x86-only path — and
the FPGA path folds to 128-bit too. No GPU implementation existed.

**The Thor path.** A tiled SIMT matcher (`exp4_hdc.cu`): 256 db vectors per
shared-memory tile (rows padded to 17 words against bank conflicts), one warp
per query per pass, warp-reduced min, one `atomicMin` per warp. Measured on a
real slice — 4096 queries × the full 10⁶ database = 4.096×10⁹ comparisons —
against the same slice on the 14 cores (full 1024-bit and the repo's folded
128-bit shape), with GPU/CPU best-match distances verified equal on a 2¹⁶
prefix.

**Numbers.**

| implementation | rate | per full-database query (10⁶) |
|---|---|---|
| GPU SIMT kernel, 128 MB db | **11.84 G comparisons/s** | ≈ 84 µs |
| GPU SIMT, db shrunk to 32 MB (all of L2) | 12.14 G comparisons/s | ≈ 82 µs |
| C 14 cores, full 1024-bit | 0.78 G comparisons/s | 1.28 ms |
| C 1 core, full 1024-bit | 0.062 G comparisons/s | 16 ms |
| C 14 cores, folded 128-bit (repo's shape) | 2.36 G comparisons/s | — |

**Mechanisms, honestly.** The GPU wins **15×** over the 14-core CPU on the
full-1024-bit slice, and the win is the SIMT popcount pipe, not memory: the
slice streams only ~46 GB/s, and shrinking the database from 128 MB to an
L2-resident 32 MB buys just 3 % — the kernel is limited by its shared-memory
access pattern and reduction latency, not DRAM. Popcount is exactly the work
tensor cores are bad at and SIMT is good at; NVFP4 (a tensor-core FP4 GEMM
format) has no application to XOR+POPC and none was used. The full 10⁶×10⁶
product is 10¹² comparisons × 128 B = 128 TB of reads; with the kernel's
32-query reuse the unavoidable DRAM traffic is ~4 TB, a **~4.6 h floor** at
240 GB/s on either side of the machine (the CPU's measured streaming, ~100 GB/s,
makes its own full product ~11 h). So: the full cross product is an overnight
job, not an interactive one, on any implementation — what the Thor changes is
that **one query against the whole 10⁶-database is 84 µs**, and the whole
database is resident.

**What it makes possible in builder-ide.** The first mile's reflex matching is
this operation: encode the current situation as a 1024-bit hypervector, match
it against every stored situation, act on the nearest. At 84 µs per lookup that
is a reflex arc, not a retrieval step; the 122.8 GB pool holds ~9×10⁸
hypervectors, so the situation library stopped being a memory question too.

---

## 5. constraint-crdt and snapkit-v2 on 14 cores

**Hardware fact.** 14 Neoverse cores with one shared 122.8 GB pool: per-thread
working sets in the hundreds of MB never leave the socket, and threads are the
only parallelism that touches this memory — the GPU is irrelevant to both of
these workloads (a CRDT merge is hash-map maxima; the governor judge is pure
Python).

**What limited it before.** constraint-crdt published "G-Counter merge 76 ns,
13.1M ops/s" from a Ryzen AI 9 HX 370 laptop. snapkit-v2's judge figure
("12.3 ms p50 at 4 threads on a Jetson") has no harness anywhere in the repo —
which is why the corpus flagged the ARM figure as unsupported.

**The Thor path.** `crdt-bench/` folds 10⁶ `ConstraintGCounter`s (14 fleet
nodes each — the repo's own `Merge` impl, HashMap-of-String state) into one
accumulator at 1 / 4 / 14 threads, chunked semilattice tree reduction, plus a
pairwise micro-bench. `exp5b_judge_bench.py` runs the Harmony Governor judge —
the per-tick `record_observation` pass, i.e. the rolling entropy + Hurst +
autocorrelation friction evaluation, in the repo's own code — over a fleet of
120 agents (the architecture doc's fleet size) at 1 / 4 / 14 threads, p50 of
120 cycles after warm-up.

**Numbers.**

| workload | 1 thread | 4 threads | 14 threads |
|---|---|---|---|
| CRDT fold of 10⁶ G-Counters | 1.278 s (0.78 M merges/s) | 0.336 s (2.97 M/s) | **0.150 s (6.66 M/s)** |
| snapkit judge, 120 agents (p50/cycle) | **34.8 ms (3,447 judgements/s)** | 68.4 ms (1,753/s) | 68.8 ms (1,744/s) |
| CRDT pairwise merge, 14-node counters | 1,315 ns (0.76 M/s) | — | — |

**Mechanisms, honestly.** The CRDT result matches the unlocks doc's prediction:
**8.5× from 14 cores** (61 % parallel efficiency; 3.8× at 4 threads), because
chunked merge is allocation-light and each thread's chunk stays cache-resident.
The pairwise figure (1.3 µs vs the published 76 ns) is not comparable — the
published counter's node count isn't in the repo, and a 14-node
`HashMap<String,u64>` merge pays 14 SipHash-keyed lookups; the algorithm, not
the machine, sets that constant. The snapkit judge went the **other way**:
4 and 14 Python threads are 2× *slower* than one thread (CPython's GIL plus
per-cycle thread handoff). Core count cannot reach interpreted code through
`threading`; the published "4 threads" improvement was never a property of the
ARM hardware. The honest Thor correction for the corpus: **judge ≈ 35 ms p50
per 120-agent cycle single-threaded; threads make it worse; the 14 cores
arrive only via multiprocessing** (near-linear in principle → ~45 k
judgements/s) or by moving the spectral inner loop to C.

**What it makes possible in builder-ide.** The night's rails can keep fleet
budget state as G-Counters and merge the whole night's 10⁶-state history in
150 ms on the CPU — no GPU, no copy, one box holds the entire fleet's CRDT
state with 90 % of the pool to spare. The governor judge is the motion side's
friction monitor: 3.4 k agent-judgements/s per process today, and a known,
cheap path (multiprocessing or a C spectral loop) to use all 14 cores when a
fleet outgrows it.

---

## Which unit did the work, and what didn't move

Every number in §1–§4 was produced by **SIMT integer lanes** (compare, XOR,
POPC) on the Thor's CUDA cores, or by **CPU integer/NEON pipes** in §3/§5.
No tensor core appears anywhere in the five experiments: NVFP4 is a tensor-core
FP4 GEMM path (cuBLASLt), and integer bounds checks and Hamming distances have
no matrix-multiply shape — the unlocks doc's NVFP4 framing for ideas 1, 2 and 3
does not apply and was not used. What actually moved, per idea: §1 — copy
elimination and residency (2.6–9.9× depending on the mask fix), not bandwidth;
§2 — the FP64→FP32 precision choice (10.2×), not the vanished copy-back (which
measures the same as an in-place read on one box); §3 — CUDA Graphs (launch ≈
4.7 µs), which removed the small-batch crossover the corpus measured in 2026-05;
§4 — the SIMT popcount pipe (15×); §5a — core count (8.5×); §5b — nothing yet,
and threads actively hurt. The things the unlocks doc said Thor would not help
— convergence rates, consensus claims, O(log N) snaps — remain unhelped, and
one of its predictions (§2's "5–10× because the copy disappears") was measured
and corrected above.

---

## Notes per repo for the crew

- **cuda-constraint-engine** — Replace the `atomicOr` violation mask with a
  per-element byte mask: 6.7–10.1 ms vs 4.9–6.9 s for the same 10⁸-constraint
  resident call in unified memory across two runs (the atomics, not the memory,
  are the cost; ~70 ns per atomic on managed memory vs ~0.6 ns on device). Add
  `sm_110` to the Makefile's ARCH list. Make `do_check`'s per-call
  `cudaMemcpyAsync`/readback optional — on an iGPU the host pointer already
  *is* the device pointer.
- **flux-gpu** — Instantiate `exact_check_kernel` for `float` and `int32`, not
  only `double`: 84–166 G vs 17.7 G checks/s at 10⁹. Keep the NaN guard. The
  README's "memory-bound" note should say FP64-throughput-bound on Thor-class
  parts.
- **constraint-theory-llvm** — `TTL-ARM-NEON-BENCHMARKS.md` should gain a Thor
  row (measured here: 3.25 G checks/s 1T NEON, 29 G/s 14T on the 20-constraint
  chain, no early exit) and its "auto-vectorization beats explicit SIMD" finding
  needs a V3AE caveat — explicit NEON wins 1.5–1.7× here. The x86 JIT emitter
  cannot run on aarch64; the graph-captured kernel in `exp3_crossover.cu` is the
  portable replacement for the batched check.
- **avx512-constraint-checker** — Keep as the x86 artifact; annotate the 35.9B/s
  figure (rdtsc at an assumed 3 GHz, bloom pre-filter, early exit). The NEON
  port is 30 lines (in exp3) and belongs in this repo as the ARM sibling.
- **flux-hdc** — The natural hybrid is the repo's own folded-128-bit prefilter
  (2.36 G/s on 14 cores) ahead of the GPU full-1024-bit verification
  (`exp4_hdc.cu`, 11.84 G/s, 84 µs per full-database query). Kernel headroom is
  in the shared-memory tile pattern (L2-resident db buys only 3 %), not DRAM.
- **constraint-crdt** — Swap `HashMap<String,u64>` per node for a fixed replica
  slot vector (`u64[16]` + node-id map at the edge): the measured merge cost is
  14 hash lookups (1,315 ns at 14 nodes); a slot vector should cut it ~50× and
  make the published 76 ns claim true again. Thread scaling is already good
  (8.5× at 14 threads).
- **snapkit-v2** — Publish the judge harness (`exp5b_judge_bench.py` runs the
  repo's own governor) so the "12.3 ms p50 at 4 threads" figure finally has a
  source; on the Thor, `threading` makes the judge 2× slower than 1 thread —
  the doc should recommend multiprocessing or a C spectral loop, not threads.
- **Consolidation candidate — lattice snapping, five implementations:**
  constraint-theory-core (Rust: Pythagorean lattice + KD-tree snap), eisenstein
  (Rust, `no_std`), snapkit-v2 `snapkit/eisenstein.py`, snapkit-v2
  `snapkit/eisenstein_voronoi.py` (naive + Voronoi variants), and
  cuda-constraint-engine (`eisenstein_check_kernel` +
  `examples/eisenstein_narrows.cu`). **constraint-substrate** already ships what
  should govern all five: `tests/vectors.json` — shared expected-output vectors
  for lattice, funnel, holonomy, rigidity, and consensus, with matching
  Python/Rust/C implementations behind one header. Crew action: make
  `vectors.json` the conformance suite every snapping implementation must pass
  in CI, keep one Rust core and one CUDA kernel, and retire or explicitly fork
  the other three. Note the substrate's lattice vectors use a group-order-3
  triangular lattice — reconciling that with the A₂ Eisenstein parameterization
  in the other four is the actual consolidation work.
