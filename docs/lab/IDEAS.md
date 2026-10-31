# IDEAS — Thor-native breakthroughs for builder-ide

**Date:** 2026-10-30 (round 1) · 2026-10-31 (rounds 2, 3) · **2026-10-31 (round 4 — this
rewrite).** **Author:** the lab seat (`~/lm-wt/lab1`, `lab2`, `lab3`, `lab4`).
**Sources:** `~/src/builder-ide/CLAUDE.md`, `docs/vision.md`, the research file
(`split.md`, `rev-tech.md`, `ig2-procfunc.md`, `trellis-spike.md`,
`v2-thor-experiment.md`, `spike-phase1.md`, `warm-scene.md`, …), and **seventeen
measured experiments** across the four rounds:

| round | files |
|---|---|
| 1 | `exp-unified-memory.md`, `exp-warp-terrain.md`, `exp-fp8-tensorcores.md` |
| 2 | `exp-nvme-bandwidth.md`, `exp-critic-png-roundtrip.md`, `exp-solver-scoring.md`, `exp-warp-terrain-port.md` |
| 3 | `exp-engines.md`, `exp-batched-shared-model.md`, `exp-adapters.md`, `exp-joules-per-fixed-point.md`, `exp-cuda-graphs-nvenc.md`, `exp-nvenc-roundtrip.md` |
| 4 | `exp-warp-mesher-sdf.md`, `exp-critic-cuda-graph.md`, `exp-skill-switch.md` (this round, in `~/lm-wt/lab4/`) |

This file is the *index*: what four rounds have settled (with numbers), what was
killed by fact (with reasons), the rules every future experiment must follow, and
a fresh ranked list of the next candidates — each with the Thor feature it leans
on, the payoff the user feels, and the smallest experiment that would prove or
kill it. The evidence lives in the `exp-*.md` files.

---

## Part 0 — what is settled (the measured foundation)

Load-bearing numbers, by theme. Every one was measured on the Thor itself; the
box's state is recorded beside each in its source file.

### The machine

| fact | number | source |
|---|---|---|
| Host `malloc` memory is device-addressable; kernels read/write NumPy pages in place; torch↔cupy share one buffer via DLPack | `devicePointer == hostPointer`, verified at 4 GB incl. the last element | R1 unified-memory |
| Zero-copy costs nothing in bandwidth; the copy is the cost | 100.87 vs 100.93 GB/s; copy+read = 2.15× | R1 |
| `.cpu()` into pageable memory | **0.34 GB/s** — 11.9 s for 4 GB (258× the pinned path) | R1 |
| The GPU idles at 315 MHz and ramps to 1575 MHz over ~1.4 s | a cold measurement is **2.6× slow** | R3 |
| `nvidia-smi` cannot see GPU memory (fourth confirmation) | `memory.used = [N/A]` | R1–R4 |
| Achievable bandwidth: **166 GB/s** eager, ~220 GB/s graphed | 0.61–0.81× the 273 GB/s datasheet | R3 |
| The engine roster: Blackwell GPU (FP8 ✓, FP4 ✗), PVA v3 (9 ctx, no input), NVENC+NVDEC (own clock domain), 14 cores. **No NVDLA, no OFA, no cameras** | `/dev` + device tree + DTB strings | R3 engines |
| Cold NVMe → unified memory **1.15–1.68 GB/s**; after any read the file is 100 % in the page cache — *the warm tier already exists*; the external shelf (FUSE) stalled and took I/O down with it | 7.45 GiB checkpoint: 6.5 s cold / 1.7–4.3 s warm | R2 nvme |
| The 14-core ceiling is ~4.4× (not 14×), measured under load | numba prange | R1 |

### The procedural world (Infinigen)

| fact | number | source |
|---|---|---|
| Warp 1.18 runs on aarch64/sm_110, native SASS, no PTX-JIT tax | cold compile 0.65 s, cached 1.16 ms | R1 |
| The `mountains` element in Warp: **bit-identical** to Infinigen's CPU *and* CUDA libraries | 44–56× CPU, 6× their CUDA (16 M pts) | R2 |
| **The real OcMesher is 69 % SDF-evaluation-bound** (13.6/19.7 s, 3 reps, ~50 M SDF points, 122 batches) | bookkeeping is 31 % | R4 mesher |
| The two-element mesher SDF (`mountains`+`warped_rocks`) in Warp: **bit-identical on the mesher's own octree batches**, 75–85× the CPU libs, 5.8× Infinigen's CUDA lib | projected whole-mesh **3.16×** (19.9 → 6.3 s), after which the mesher is bookkeeping-bound | R4 mesher |
| The solver's scoring: GPU scores 47.95 M candidates/s (3,394× today) **but** the solver proposes one at a time, where a restructured CPU is 7.5× faster than the GPU; crossover 64–256 candidates; ~17 % of candidates have a tied closest edge | the win is a solver change, not a kernel | R2 solver |
| Infinigen 2.0 runs end-to-end on the Thor (Cycles CUDA); its tracer covers objects (80/88) but **not** the scene generators; a warm process saves only ~2.4 s/scene | 435 s cold room render | v2-thor |
| Infinigen v1's scattering is Blender geometry nodes — not Warp-portable with an oracle (needs a live bpy scene) | — | R4 mesher §1 |

### Serving models

| fact | number | source |
|---|---|---|
| FP8 tensor cores: 1.57–1.75× FP16 on big GEMMs; FP4 a measured no (13.7 TFLOPS, worse than dequant+BF16) | 177–186 vs 106–113 TFLOPS | R1 fp8 |
| FP8 **with fused activations** is **3.00×** on a realistic chain (2.60× calibrated, and *more* accurate than unscaled); weights-only is 1.29×; round 1's 0.95× was the cast-per-layer path | 301.7 TFLOPS vs BF16's 100.9 | R3 batched |
| …but the stack is **launch-bound**: end-to-end 1.29× until graphed (1.66–2.42×); a graph removes 99.7 % of host enqueue (2.38 ms → 0.008 ms) and makes timing reproducible (6 % spread vs 3.4×) | — | R3 graphs |
| FP8 costs 15–22 % output error → **the critic and provenance stay BF16** | — | R3 |
| Batching is free only without context: with S=1024 the step grows 13.6 → 53.7 ms from N=1 to N=128 (KV cache per-agent); joules/item still fall 186× from N=1 to N=512 | — | R3 batched |
| On the *real* generator (TRELLIS.2 via ComfyUI) FP8 is **50–88 % slower, never faster**; the fused path's CPU-side scale work is the bottleneck; its one real benefit is ~13 GB peak RAM at 1024³, which 128 GB does not need | patch to make it reachable at all: one line (`arange` in fp8) | trellis-spike |
| Skills: a 15.7 M LoRA is 60 MiB (PEFT keeps FP32) and ~14 ms on a 1.64 B forward; **`set_adapter` costs 73–119 ms of host time** (O(layers×adapters) in Python); PEFT's mixed batch 10× worse at 32 adapters | round 4 measured the fixes — see Part 0 "skills" below | R3 adapters |
| Warm-started equilibrium loops: 2–3 iterations vs 6 cold; joules = 1.39 J × iterations; a lossless 8-bit store is free; **the critic cannot live on the CPU** (2.2× slower, 2.5× joules) | — | R3 joules |
| Model loads cost seconds, not minutes (cold 6.5 s for 7.45 GiB) — **no cold model can be swapped inside the critic's ≤5 s clock** | — | R2 nvme |

### The critic

| fact | number | source |
|---|---|---|
| The PNG round trip is 10×–228× a stand-in critic's forward pass; 88 % is the *encoder*; disk is 0.5 %; tmpfs no faster | 48.5 / 293 / 1,202 ms at 480p/1080p/4K | R2 critic |
| **With the real DINOv2-large critic, zero-copy + CUDA Graph: 6.1–84.6 ms per verdict** (B=1…8, 480p→4K) vs 61–8,984 ms through PNG — **10×–106×**; the graph is **bit-exact** vs eager in all 12 configurations; host issue 0.10–0.17 ms (vs 7.7–19 eager); ~2.7× fewer joules/verdict at 1080p B=8 | verdict RMS between the PNG (8-bit) and buffer (float) paths: 3.4–6.4 % — the PNG interface costs correctness too | R4 critic |

### Skills, after round 4 (from `exp-skill-switch.md`)

| fact | number | source |
|---|---|---|
| PEFT's `set_adapter` reproduced at low load | **72.5–129.5 ms** host per switch | R4 skills |
| Copy-slot is not inherently slow — round 3's 45 ms was CPU starvation | **2.4 ms** (60 MiB d2d, 160 modules) | R4 skills |
| `delta_swap` (in-place `W += Δ_new − Δ_old`) | 36.7 ms | R4 skills |
| **Merged-resident `pointer_swap`** — re-point 160 weight tensors | **0.40 ms** (180× PEFT) | R4 skills |
| Merged serving is *faster* than adapter serving (adapter arithmetic gone) | 18.6 vs 47.0 ms/request at N=32 | R4 skills |
| Batched multi-LoRA (grouped bmm, graphed): mixed skills, no switch | **11–14 ms/request at N≥4; 9.0× PEFT's switching server at N=32; 0.43 J/req on the GPU rail (4.1× less)** | R4 skills |
| All four serving paths numerically exact vs single-adapter forwards | rel RMS 0.0000 % (merging included) | R4 skills |
| The byte bill: hold a skill = 60 MiB (fp32 adapter); serve it merged = 720 MiB (bf16 q/k/v/o set) | 12× | R4 skills |

### The video engines

| fact | number | source |
|---|---|---|
| NVENC does not compete with the tensor cores (+0.2 %/−1.3 % on a matmul beside it) and is 199× compressive (38.6 KiB / 30 frames 512²) | own clock domain `gpu-nvd-0` | R3 nvenc |
| **But it is not a warm-start store**: 1.7–3.1 % RMSE round trip → the loop needs 6 iterations (same as cold). Use the codec for film, 8-bit for state | AV1 does not exist on this NVENC | R3 nvenc |

---

## Part B — killed by fact (nobody should re-propose these)

| claim | killed by | why |
|---|---|---|
| NVDLA as a critic farm | **no NVDLA exists on this SoC** | absent from `/dev`, the device tree and the compiled DTB. Thor moved the work into the GPU's tensor cores |
| OFA as a real-time mesh deformer | no device node | the driver has an OFA counter; the hardware is not reachable on this SKU |
| PVA as the scheduler | wrong capability + no input | PVA v3 is a fixed-program vision accelerator driven through the camera stack; there are no `/dev/video*` nodes. (Parked, not dead: cheap always-on perception if a camera is attached) |
| Camera injection / “20 feeds” / C-PHY | no cameras | automotive Thor configurations, not this devkit |
| 4×25 GbE / 100 Gbps to the laptop | real silicon, no cage | the ProArt has no matching port either; it is a purchase, not a dependency |
| Sizing work against 2,070 TFLOPS FP4 | measured 13.69 TFLOPS via torchao | and *slower* than dequantise-to-BF16-then-multiply; the dtype exists, the path does not |
| Sizing the scheduler against 273 GB/s | measured 166 GB/s eager / ~220 graphed | any `T_pass` from the datasheet cannot be achieved |
| “122 GB makes VRAM a non-issue” | contention is real and unobservable via `nvidia-smi` | drive eviction from `/proc/meminfo` + `tegrastats` |
| FP8 as a drop-in for the critic / provenance | 15–22 % output error | keep BF16 where output is checked |
| FP8 weights-only on the real generator | 50–88 % slower on TRELLIS.2's samplers, never faster | the cast-per-layer path (the lab's own C4b, reproduced on the real workload) |
| NVENC/NVDEC as the world-state warm-start store | 1.7–3.1 % RMSE destroys the warm start (6 iterations = cold) | fine for the morning film, fatal for state |
| AV1 encoding on this box | `av1_nvenc` fails at every bitrate | H.264/H.265 only |
| “Switch the active adapter per request” (PEFT's multi-LoRA server shape) | 73–119 ms host per switch, flat in adapter count | round 4 measured the alternatives — merged swaps and batched serving (Part 0) |
| PEFT's mixed-adapter batch (`adapter_names=`) | 10× worse at N=32 (5,120 one-row GEMMs) | round 4 graphed a punica-shaped replacement — see `exp-skill-switch.md` |
| The critic on the CPU | 2.2× slower, 2.5× joules | there is no spare accelerator to move it to (engines) |
| Die heat as attention / ECC bit-flips as entropy / JTAG puppeteering / a safety-island constitution | read-only scalars / no ECC counters / no port / no island | non-deterministic by construction, which also breaks the recipe premise (`exp-engines.md` §5) |
| “A warm scene process will make batch scenes fast” | saves ~2.4 s of imports per scene | generation, modifier bake and sampling are all per-scene work (v2-thor §5) |
| Blender-codec PNGs as the critic's interface | 10–106× slower than the buffer *and* 3.4–6.4 % verdict drift from quantisation | rounds 2 + 4 |

---

## The rules (each one was paid for)

1. **Restructure before you port.** The GPU beats a faithful port by 8–85×; against a
   restructured CPU it can be level (0.91–1.53×, R1) or the port is pointless
   (solver: crossover 64–256 candidates, R2). The algorithm and the port are one job.
2. **Zero-copy is a design constraint, not an optimisation.** The bandwidth is the
   same; what disappears is the copy, the second allocation, and (round 4) the
   8-bit quantisation the file interface forced on the critic.
3. **Warm the GPU clock before timing anything** (315 → 1575 MHz, ~1.4 s; cold
   readings are 2.6× slow) and record the clock beside the number.
4. **On a shared box, interleave the variants and publish ranges.** Absolute times
   drift 2–3.4× with other seats' load; ratios measured in the same rounds hold.
   A CUDA Graph is the *reproducible* way to measure GPU work (6 % vs 3.4× spread).
5. **Compile the original headers into an oracle; never transcribe C by hand.**
   Round 2's hash-chain was wrong twice; round 4's `log_uniform` was wrong once —
   both caught in minutes by the compiled oracle, not by reading the header again.
6. **Joules: subtract the idle baseline, and if the result is negative, report the
   wall time instead.** The whole-box rail carries every tenant; the VDD_GPU rail
   is the attributable one; the 25 ms sampler cannot resolve 10 ms windows.
7. **Bit-exactness is achievable and worth requiring** for numeric ports (three
   for three now: mountains, warped_rocks, the composed field) — and for graphs
   (bit-exact vs eager in all 12 configurations).

---

## Part A — the live candidates, ranked (round 4)

### 1. Finish the OcMesher: the octree tail is now the whole cost

- **Thor feature:** Blackwell GPU + unified memory + Warp (all proven on this
  exact code path by round 4).
- **The idea.** Round 4 moved the SDF evaluation (69 % of the mesher) to the GPU
  bit-identically at 75–85×; the projected mesh is now **97 % octree bookkeeping
  and marching cubes** (~6.1 s of a projected 6.3 s). The next term is the
  octree build/refine/bisect loop itself (`OcMesher/source/core.cpp`: `run_coarse`
  splits by projected pixel size, `fine_group` batches leaves, 15 bisection
  iterations re-query corners).
- **User payoff.** Live, camera-aware re-meshing — the world re-cuts itself as
  the camera moves and the ProArt's LOD stream becomes continuous. That is the
  difference between “a scene” and “a world” (idea #4's original framing), and
  the measured numbers now say it is one port away, not a research question.
- **Smallest experiment (≤1 day).** Keep the CPU mesher's serial decisions but
  batch its per-leaf work to Warp: port `fine_iteration`'s per-cube sign tests
  and the bisection vertex updates to one Warp kernel per group, with the
  octree arrays resident in unified memory. Require the *same mesh* out
  (vertex and face counts identical; sampled surface distances 0) and time the
  hybrid vs the current mesher. **Kill it** if the canonical-order invariants
  (the mesher's frontier ordering is deliberately serial) cannot be preserved
  on the GPU without changing the output mesh.
- **Status: the substrate is measured** (round 4); the port itself is unproven.

### 2. Wire the zero-copy graphed critic into the middleware

- **Thor feature:** unified memory (the render buffer never leaves the device)
  + CUDA Graphs.
- **The idea.** Round 4 measured the verdict path at **6.1–84.6 ms** with the
  real critic, bit-exact and launch-free. None of it is in the middleware yet —
  the core's critic still reads PNG-shaped inputs, and the renderer still
  writes them.
- **User payoff.** The ≤5 s watch clock becomes ~10 ms of GPU work: verdicts on
  *every* frame the night renders, mid-render aborts of bad branches, and the
  morning report ranked by a critic that actually saw the pixels (not their
  8-bit quantisation — 3.4–6.4 % verdict drift today).
- **Smallest experiment (≤1 day).** One integration slice: a stand-in renderer
  writing into the graph's static input buffer; the core's graded checks
  consuming graphed DINOv2 verdicts for the mini-night's three requests;
  end-to-end timed against the current PNG path *inside the core's own
  pipeline*. **Kill it** if the middleware's process boundary forces a copy
  that eats the gain (EXP A says it need not — the buffer can stay
  device-addressable across processes on this box).

### 3. The scheduler's skill policy: merged residents, not switches

- **Thor feature:** 128 GB unified memory — a merged skill set is 720 MiB (bf16,
  measured round 4) and a hot craft group of 4–8 fits trivially; the batched
  multi-LoRA path (graphed) serves mixed-skills nights without any switch.
- **User payoff.** Builders' skills stop paying 73–119 ms of host time per
  request, and a night mixing crafts batches one graph replay instead of
  switching. The numbers for the policy are in `exp-skill-switch.md`.
- **Smallest experiment (≤½ day).** Not hardware: a scheduling simulation over
  the mini-night's ledger — replay its request pattern under (a) PEFT switching,
  (b) merged residents with an LRU of K, (c) graphed batched multi-LoRA — and
  pick the policy from projected request latency and resident bytes. **Kill**
  nothing; this is a design decision the measurements now make quantitative.

### 4. Batch the solver's proposals (the Architect's day-clock still depends on it)

- **Thor feature:** Blackwell GPU scoring at 47.95 M candidates/s — unused while
  the solver proposes one candidate at a time.
- **User payoff.** Re-solving a room in seconds, not tens of minutes: the
  Architect becomes a character you talk to, the single biggest UX unlock left.
- **Smallest experiment (≤1 day).** Change `propose_continous`/`propose_discrete`
  to emit N candidate poses, score them batched (Warp), accept the best (or
  sample); verify the annealing's output *distribution* is unchanged (KS test
  over placement scores across seeds, with the ~17 % tie-ambiguity from round 2
  respected) and measure the solve wall. **Kill it** if accept-best changes the
  distribution — then the GPU number stays decorative.

### 5. Graph-capture the real generator's decode step (round 3's #1, still open)

- **Thor feature:** CUDA Graphs on the one real serving loop we have (TRELLIS.2
  via ComfyUI).
- **User payoff.** The lab's FP8 3× and the graph's launch-killing have both
  been measured on synthetics; neither has touched the real generator. This is
  the cheapest unmeasured multiplier on the board (a 512³ prop is 98–115 s
  wall, samplers 16 s of it).
- **Smallest experiment (≤½ day).** Capture the KSampler step (or one UNet
  block) in `torch.cuda.graph` inside ComfyUI, record step time eager vs
  graphed and the CPU issue time; then, separately, attack the fused-fp8 path's
  CPU-side per-layer scale work (trellis-spike §7.3's diagnosis — precompute
  scales per layer on the GPU). **Kill** the graph half if ComfyUI's dynamic
  control flow refuses capture (likely for the whole workflow; unlikely for a
  block).

### 6. The KV-cache-aware batch limit (needs the real context lengths first)

- **Thor feature:** unified memory; the KV cache is per-agent and dominated the
  batch at S=1024 (13.6 → 53.7 ms, N=1→128).
- **User payoff.** More builders resident per watt; the scheduler's admission
  rule becomes one measured curve instead of a guess.
- **Smallest experiment.** When the first LLM seat exists, log its real context
  lengths for a night and re-run `exp2_batched.py`'s sweep at those lengths.
  Until then this stays parked-by-missing-dependency, not killed.

### 7. The 5 GbE cable (needs a human) and 8. PVA (needs a camera)

Both unchanged from round 3: the cable is the cheapest experiment on the list
(`iperf3` both ways, one real clip) but needs Casey; PVA is real silicon with
no input attached. **Parked, not killed.**

### Deprioritised by newer facts (not killed — just not next)

- **FP8 for anything whose output is checked** — the critic, provenance, and any
  quality-gating path stay BF16 (15–22 % error, and TRELLIS.2's real workload
  was *slower* in both ComfyUI FP8 modes).
- **The external cold shelf** — plan it as an archive tier; it is a FUSE mount
  that took the box's I/O down with it once already.
- **Warm scene *processes* for batch throughput** — worth ~2.4 s of imports;
  worth much more as the *interactive* loop (edit → re-render in 5–9 s, v2-thor).

---

## Round 4 — what changed

Three experiments, one file each, all in `~/lm-wt/lab4/`:

| file | what it measured | verdict |
|---|---|---|
| `exp-warp-mesher-sdf.md` | the real OcMesher's cost split, and its two-element SDF in Warp on the mesher's own octree batches | **breakthrough on the SDF half** — 69 % SDF-bound, port bit-identical, 75–85× CPU; mesher projects 3.16× |
| `exp-critic-cuda-graph.md` | the real DINOv2-large critic zero-copy + CUDA Graph vs the PNG path at B=1…8 | **10×–106×**, bit-exact graphs, 0.1 ms issue, ~2.7× fewer joules |
| `exp-skill-switch.md` | merged-delta swap, merged-resident pointer swap, punica-shaped batched multi-LoRA (eager + graphed) vs PEFT's switch | **the switch is solved** — pointer swap 0.40 ms (180× PEFT), merged serving faster than adapters, batched mixed-skills 9.0× the switching server |

### The three things round 4 changed

1. **Idea #4's question is answered and its SDF half is ported.** The real
   OcMesher is **69 % SDF-bound**; the two-element SDF is bit-identical in
   Warp on the mesher's own octree batches at 75–85×; the mesh projects
   **3.16×**, and the mesher's remaining cost is now 97 % octree bookkeeping —
   which is what candidate #1 attacks next.
2. **The critic's whole verdict path is measured with the real model** —
   6.1–84.6 ms graphed zero-copy (10×–106× the PNG interface), bit-exact,
   0.10–0.17 ms of host issue, ~2.7× fewer joules — and the PNG interface
   costs *correctness* too (3.4–6.4 % verdict RMS from 8-bit quantisation).
   The middleware integration is candidate #2.
3. **Skill switching stops being a problem**: merged residents switch in
   0.40 ms and serve *faster* than adapters; mixed-skill batches serve at
   11–14 ms/request with no switch at all, in plain-torch grouped bmm that
   captures in a graph. PEFT switching is retired. The design decision that
   remains (how many merged residents to keep hot) is a scheduler simulation,
   not a hardware experiment — candidate #3.

### What round 4 did not settle

- **The octree tail** (candidate #1) — measured as the next blocker, not ported.
- **The real generator's graph/FP8 story** (candidate #5) — untouched; round 4's
  graph work was the critic's.
- **The solver's batched proposals** (candidate #4) — round 2's condition stands.
- **The box is still shared**: round 4 ran at load 7–23 (the quietest round yet,
  and the only one with a warmed-clock rule in every script), but absolutes are
  still ranges; only the interleaved ratios are numbers.

### Corrections round 4 makes to earlier rounds

1. **Idea #4's question is answered** — “is the OcMesher's cost SDF evaluation
   or octree bookkeeping?” was **SDF evaluation (69 %)**. The idea's status
   moves from “unproven, depends on the bpy build” to “the SDF half is measured
   and ported; the tail is next”. (The bpy dependency was also wrong: the
   OcMesher package itself needs no bpy.)
2. **Round 3's adapters file ended by recommending exactly what round 4
   measured** — merging and graph-capturing the mixed batch. The numbers land
   in `exp-skill-switch.md`; idea #17's “a skill is a merged resident model”
   graduates from proposal to design rule with a byte cost attached
   (60 MiB fp32 adapter vs 720 MiB bf16 merged set).
3. **Round 2's critic numbers were anchored to a stand-in; round 4 re-anchored
   them to DINOv2-large** — the ratios *grew* with the real model (the forward
   is a larger share at 4K), and the new finding is that the PNG interface
   costs *correctness* (3.4–6.4 % verdict RMS), not just time.

---

## Part D — cross-cutting traps (rounds 1–4, cumulative)

The things that silently cost hours. Rounds 1–3's 23 are kept verbatim in the
round-3 IDEAS (builder-ide `docs/lab/IDEAS.md`); the lab-4 additions:

24. **Infinigen's element `init()` keeps your parameter *pointers*** (`core.cpp`:
    `d_i_params = i_params`). Pass a numpy temporary and the library evaluates
    through freed memory — a pure function that silently returns different
    values on later calls. Keep every array handed to `init()` alive for the
    process's lifetime.
25. **Infinigen's CUDA element library smashes its aux buffer's neighbours** when
    driven with the CPU library's 1-aux stride — run its timing arm *after* any
    correctness comparison, with padded buffers.
26. **The OcMesher's `bounds` are (xmin, xmax, ymin, ymax, zmin, zmax)** — a
    (min-triple, max-triple) order makes an empty x-range and the mesher
    silently returns a 0-vertex mesh. Its camera argument is cam→world with the
    camera axes as *columns* (the demo's convention). Grid-scan the composed SDF
    before blaming the camera.
27. **`log_uniform(low, high, seed)`'s inner hash is the ONE-argument
    `hash_to_float(seed)`** (blender_noise.h:420). Wrapping it with the 2-arg
    hash produces a plausible field that is wrong by 3–57 units — the compiled
    oracle pins it in minutes.
28. **The punica/S-LoRA shape on a ViT is (skill, token, dim)** — the LoRA layer
    sees 3D hidden states; a 2D-row bmm explodes. punica itself is a CUDA
    source build and does not install on aarch64; the portable form is grouped
    bmm (2 bmms per module), which captures in a CUDA Graph.
29. **PEFT 0.21's `get_peft_model` takes no `torch_dtype`** — the adapters are
    FP32 by default (round 3's 60-MiB finding) regardless of the base dtype.
30. **`torch.from_numpy` on a read-only array warns and the tensor is
    undefined-if-written** — harmless for reads; never `.div_()` in place on it.

## Licence note for this round

Code only, no model weights downloaded: `torch` (BSD-3), `transformers`
(Apache-2.0), `peft` (MIT), `warp-lang` (Apache-2.0), `numpy` (BSD-3), `pillow`,
`trimesh`, `tqdm`, `gin-config`, `psutil` (MIT-family). Infinigen's headers and
the spike's built element libraries are copied unmodified into
`lab4/vendor/infinigen-terrain/` (BSD-3 with Blender dual-licensed bits
attributed). DINOv2 weights are the Thor's local copies, read in place.
