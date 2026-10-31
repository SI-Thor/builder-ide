# IDEAS — Thor-native breakthroughs for builder-ide

**Date:** 2026-10-30 (round 1) · 2026-10-31 (round 2) · **2026-10-31 (round 3 — this
update)** · **Author:** the lab seat (`~/lm-wt/lab1`, `~/lm-wt/lab3`)
**Sources read:** `~/src/builder-ide/CLAUDE.md`, `docs/vision.md`, `docs/research/split.md`,
`docs/research/rev-tech.md`. **Measured:** ten experiments in this directory —
`exp-unified-memory.md`, `exp-warp-terrain.md`, `exp-fp8-tensorcores.md`,
`exp-nvme-bandwidth.md`, `exp-critic-png-roundtrip.md`, `exp-solver-scoring.md`,
`exp-warp-terrain-port.md`, and from **round 3**: `exp-engines.md`,
`exp-batched-shared-model.md`, `exp-adapters.md`, `exp-joules-per-fixed-point.md`,
`exp-cuda-graphs-nvenc.md`, `exp-nvenc-roundtrip.md`.

CLAUDE.md: *"Thor-native rewrites are welcome, and breakthroughs are the point… Mine ideas
for breakthroughs by running small experiments: an idea becomes a measured result (or a
measured no) within days, not a debate."*

So every idea below carries a **smallest experiment that would prove or kill it**, sized to
fit in a day. Three of them are already partly answered by this round's experiments — those
are marked **measured**, with the numbers attached.

---

## The measured foundation (from this round)

These are the facts the ideas are built on. Full detail in the three `exp-*.md` files.

| Finding | Number | Source |
|---|---|---|
| Host `malloc` memory is **device-addressable** on the Thor | `devicePointer == hostPointer`, `type=cudaMemoryTypeUnregistered` | EXP A |
| A CUDA kernel can **mutate a NumPy buffer in place** | verified at 10 probe indices across 4 GB, incl. the last element | EXP A |
| PyTorch ↔ CuPy share **one buffer** via DLPack | identical pointers both directions | EXP A |
| Zero-copy costs **nothing in bandwidth** | 100.87 GB/s vs 100.93 GB/s for a device-resident read | EXP A |
| …but copy-then-read costs **2.15×** more | 85.20 ms vs 39.66 ms for 4 GB | EXP A |
| **`.cpu()` into pageable memory is 0.34 GB/s** | 11.9 s for 4 GB — 258× slower than pinned | EXP A |
| **Warp 1.18.0 runs on aarch64 + sm_110** | compiles natively; 0.65 s cold, 1.16 ms cached | EXP B |
| Warp's cubin is **native sm_110 SASS, no embedded PTX** | `cuobjdump --list-elf` → `sm_110.sm_110.cubin`; `--list-ptx` → none | EXP B |
| Warp beats an **optimised 14-core CPU** on terrain kernels | 10.2–14.2× (2D fBm 4096²), 7.9–10.5× (3D SDF, identical work) | EXP B |
| …but a **restructured CPU matches the GPU** | separable noise field: 0.91×–1.53× across runs — level within noise | EXP B |
| **FP8 tensor cores work**: 1.6–1.7× FP16 | 177–186 vs 106–113 TFLOPS (8192³) | EXP C |
| FP8 **halves weight residency** | 4 B params: 7.45 GB → 3.73 GB | EXP C |
| **FP4 is a measured no** on this stack | 13.69 TFLOPS = 1.75× the cost of dequantise+BF16 | EXP C |
| FP8 weights **alone** buy nothing on a realistic chain | 0.95× vs FP16 — the activation cast eats it | EXP C |
| **The GPU clock is the first-order measurement trap** | 315 MHz idle → 1575 MHz under load, ~1.4 s to ramp; a cold measurement is **2.6× slow** | **R3** |
| **FP8 weights *with* FP8 activations are the real multiplier** | **3.00×** on a realistic 8-GEMM chain (weights alone: 1.29×) | **R3** |
| …but only **1.29× end-to-end**, because the stack is **launch-bound** | CPU issue time 9.35 ms ≈ the whole step; **1.66–2.42×** once graphed | **R3** |
| FP8 costs **15–22 % output error** on a 16-layer stack | e4m3 has a 3-bit mantissa and the error compounds | **R3** |
| The box's **weight-stream bandwidth is 166 GB/s eager, ~220 GB/s graphed** | **0.61× the 273 GB/s datasheet** | **R3** |
| **Batching is free only in the weights-only regime** | step flat N=1…8; **13.6 → 53.7 ms** from N=1 to N=128 at S=1024 (the KV cache is per-agent) | **R3** |
| **A CUDA Graph removes 99.7 % of the host work** | CPU enqueue 2.38 ms → 0.008 ms; the graphed time varies **6 %** across runs, the eager time **3.4×** | **R3** |
| **A skill adapter is 15.7 M params / 60 MiB and costs ~14 ms** | PEFT keeps adapters in **FP32** even on a BF16 base; 32 adapters = 1860 MiB | **R3** |
| **PEFT's `set_adapter` costs 75–120 ms per switch** | O(layers × adapters) in Python — larger than the request it precedes | **R3** |
| **Warm-starting an equilibrium loop saves 1.4–1.5× the iterations** | 2–3 iterations warm vs 6 cold; joules/fixed-point = 1.39 J × iterations | **R3** |
| **A lossy video store destroys the warm-start advantage** | an NVENC round trip warms the loop in **6** iterations — the same as a cold start | **R3** |
| **NVENC does not compete with the tensor cores** | +0.2 % / −1.3 % on a matmul loop running beside the encode | **R3** |
| **AV1 does not exist on this Thor's NVENC** | `av1_nvenc` fails at every bitrate | **R3** |

Two rules follow, and they shape every idea below:

> **Rule 1 — restructure before you port.** EXP B found that against the *current* CPU
> code the GPU is 7.9–10.5× faster, but against a *restructured* CPU implementation
> (exploiting the separability of the SDF's displacement field) the two are level within
> noise (0.91×–1.53× across runs). **The GPU's advantage is over a faithful port, not
> over a better algorithm.** A GPU rewrite that ships without the algorithmic work
> alongside it is not guaranteed to be a win.
>
> **Rule 2 — zero-copy is a *design constraint*, not an optimisation.** EXP A showed the
> bandwidth is identical either way; what zero-copy buys is the **absence of the copy and
> the second allocation**. Every idea below that crosses a buffer boundary should ask
> "why does this copy exist at all?" before it asks "how fast is the copy?".

**A note on measurement noise.** The box is shared (another seat's build held load ≈ 4–5
during these runs), and several figures move between runs. Where a result was unstable,
the range across four runs is given rather than the single best number. Two published
claims were corrected after a clean re-run — see the note at the end of this file.

---

## Part A — live candidates

### 1. The scene is a pointer, not a file

- **Thor feature:** 122 GB unified memory shared by CPU and GPU with no copies.
- **The idea.** One addressable buffer holds the world state. Blender/bpy, the generators
  (PyTorch) and the critic read and write *that* buffer. No `scene.blend` round-trip, no
  PNG round-trip. split.md's "warm scene server" is normally a hard architectural project
  (kill the per-task Blender relaunch, replace the file boundary). On this box it is
  nearly free: the scene never has to leave memory, so there is nothing to serialise.
- **What it unlocks for the user.** An edit becomes a kernel launch rather than a
  re-serialise → the ≤60 s workshop clock is comfortable instead of aspirational. The
  critic looks at the *live* buffer, not a rendered file, so a verdict can arrive while
  the world is still being edited. The morning "before/after" is a pointer diff, not a
  re-render.
- **Smallest experiment.** Build a 4096 × 4096 float32 buffer; a fake "generator" (CuPy or
  Warp) writes into it; a fake "critic" (torch) reads it. Measure end-to-end latency
  against the same data travelling through a `.npy` file and a `.png` file. **Kill it if
  the file round-trip is under 2× the pointer version** — that would mean the I/O was
  never the bottleneck and the real cost is elsewhere.
- **Status: measured (partly).** The zero-copy mechanism is proven in EXP A. What is not
  yet proven is that a *real* bpy scene can live in one of these buffers — bpy owns its
  own allocator, and Blender 4.2 is still being built for aarch64.

### 2. Infinigen's stage executor on the GPU (Warp)

- **Thor feature:** Blackwell GPU (sm_110) + Warp's Python→CUDA path + unified memory.
- **The idea.** Rewrite Infinigen's heaviest procedural stages — terrain SDF elements,
  scattering density evaluation, geometry-node evaluation — as Warp kernels instead of
  Python/Blender ops. Warp keeps the code in Python (which is what the builders' closed
  vocabulary speaks) and compiles to CUDA at runtime.
- **What it unlocks for the user.** The CPU lane goes back to the solver. Coarse terrain
  goes from minutes to milliseconds, so "re-cut this valley" becomes a day-clock action
  rather than a night job.
- **Smallest experiment.** Port **one** Infinigen terrain element (a mountain SDF from
  `source/cuda/elements/*.cu`) to Warp, keep the existing CPU path as the reference, and
  require the two to produce **identical meshes for the same seed**. Time both.
  **Kill it if the outputs differ, or if the existing CPU path is already under 1 s.**
- **Status: measured (the substrate).** Warp works on aarch64/sm_110 and beats an
  optimised 14-core CPU by 10.2–14.2× (2D) and 7.9–10.5× (3D) on equivalent kernels.
  Its cubin is **native sm_110 SASS with no embedded PTX**, so it sidesteps the
  `nvcc`-defaults-to-sm_75 trap that every hand-written CUDA extension on this box must
  work around (rev-tech §C6) — an argument for Warp over a hand-written extension here.
  The port itself is unproven, and per **Rule 1** it must ship alongside the algorithmic
  work.
- **Status: MEASURED (round 2, `exp-warp-terrain-port.md`) — BREAKTHROUGH.** The
  `mountains` terrain element was ported to Warp and is **bit-identical** to Infinigen's
  own CPU *and* CUDA libraries (max |diff| = 0.0 over 16 M points) while running
  **44–56× faster than the CPU path** and **6× faster than Infinigen's own hand-written
  CUDA kernel** — which `cudaMalloc`s and copies its buffers on *every call*, pure waste on
  a unified-memory box. The outputs-differ kill condition is not triggered. The reusable
  artefact is the **oracle**: compile Infinigen's own headers into a tiny program and diff
  the intermediates, instead of transcribing the C by hand (which was wrong twice — Part D
  trap 8).

### 3. The solver's inner loop is a GPU batch — the Architect becomes a daytime character

- **Thor feature:** Blackwell GPU + the 14 cores as a heterogeneous pair.
- **The idea.** Infinigen Indoors' greedy simulated annealing (~38 min for 5k solver steps
  on the authors' x86 hardware, single-threaded Python) spends its time *evaluating
  candidate placements*. The annealing decision must stay sequential, but the **scoring of
  a batch of candidates does not**. Move the scoring to the GPU; keep the decision on the
  CPU. This is the one place where the GPU attacks the stage split.md names as
  "interactive-killing" (the solver).
- **What it unlocks for the user.** Re-solving one room in seconds instead of tens of
  minutes. That is the difference between the Architect being a night job and being a
  character you can talk to while you work — and it is the single biggest UX unlock in
  the whole plan.
- **Smallest experiment.** Take one stage from `core/constraints/example_solver/`, extract
  its candidate-scoring function into a pure function, and time it as (a) the current
  Python, (b) numba across 14 cores, (c) one Warp batch. **Kill it if (c) is not ≥5×
  faster than (a), or if that stage is not ≥30 s of the ~38 min.**
- **Status: unproven, and this is the highest-value untested idea in the list.**
- **Status: MEASURED (round 2, `exp-solver-scoring.md`) — USEFUL, with a condition.** The
  scoring function extracted was `cl.angle_alignment_cost` → `angle_alignment_cost_base`
  (a real score term, evaluated on every proposal). The GPU port scores **47.95 M
  candidates/s** — **3,394× the current shapely path** (14,127 cand/s) and **97× the best
  restructured CPU** — so the ≥5× kill condition is cleared by a factor of 680. **But the
  solver scores ONE candidate per annealing step**, and at that size the *restructured CPU*
  (numpy-vectorised, 0.04 ms) is **7.5× faster than the GPU** (0.30 ms) and **23× faster
  than today**. The crossover is between 64 and 256 candidates. **The GPU is the right engine
  only if the proposal step is restructured to batch candidates** — and that restructuring
  is the real finding, not the kernel.
- **A second, separate finding:** the scoring function's argmin is **ambiguous for ~17 % of
  candidates** (at a polygon corner the two adjacent edges are exactly equidistant), so a
  port that breaks ties differently changes the solver's *decisions*, not just its speed.
  Any GPU port must break ties the same way, or the generated scene changes.
- **Still open:** this stage's share of the ~38 min solve. `thor/run-timed.sh` exists but
  `outputs/logs/` does not, so there is no per-stage breakdown to check "≥30 s" against.
  What is measured is a *rate*: 14,127 candidates/s today.
- **Caution:** the 14 cores are worth ~4.4×, not 14× (EXP B, measured under load). A
  CPU-only fallback is capped around 4–5×.

### 4. Live, camera-aware re-meshing

- **Thor feature:** unified memory + Blackwell GPU.
- **The idea.** Infinigen's fine terrain is *already* camera-aware (OcMesher meshes only
  what the cameras see, at view-dependent resolution) — but today the mesh is a cache
  produced once and written to disk. If the SDF field stays resident in unified memory and
  the camera set is editable, the mesh can be **re-derived live**: the world re-cuts itself
  as the camera moves, and the ProArt's LOD stream updates continuously.
- **What it unlocks for the user.** The world stops being a downloaded artefact and starts
  being a place you can look around in. The thin client stops receiving a pre-baked LOD
  set and starts receiving a *stream*. This is the difference between "a scene" and "a
  world".
- **Smallest experiment.** One day: port OcMesher's octree traversal + SDF evaluation to
  Warp for a single tile set, and compare against the C++ OcMesher for the same camera set
  and seed — vertex count, triangle count, and a sampled surface-distance comparison —
  plus both wall times. **Kill it if the C++ cost is dominated by octree bookkeeping
  rather than SDF evaluation**, since then the GPU has nothing to accelerate.
- **Status: unproven.** Depends on the bpy 4.2 aarch64 build landing.

### 5. FP8 is the scheduler's unit of residency

- **Thor feature:** Blackwell FP8 tensor cores.
- **The idea.** Make FP8 e4m3 the default precision for *warm* generative models. The
  constraint on this box is not capacity but **weight-swap thrash** (rev-tech §C4), and
  thrash scales with bytes moved. FP8 halves the bytes.
- **What it unlocks for the user.** The hot tier becomes three models instead of one:
  companion + critic + a generator, all resident at once. The critic's ≤5 s watch clock
  stops competing with a generator's weight load — which today it does, and which is why
  the scheduler has a "downgrade the critic" row at all.
- **Smallest experiment.** One day: load one real model twice — once fp16, once with
  ComfyUI's `--fp8_e4m3fn-unet` — and record (a) the peak `MemAvailable` dip measured from
  `/proc/meminfo` (not `nvidia-smi`, which cannot see GPU memory on this box),
  (b) time per image, (c) a visual/numeric diff of the output. **Kill it if memory does
  not drop ~2× or the output visibly degrades.**
- **Status: measured (the hardware half).** FP8 works, 1.6–1.7× FP16, half the weight
  bytes. The end-to-end generator path is untested — rev-tech R9 flags ComfyUI's fp8 flag
  as unvalidated on sm_110.
- **Status: MEASURED (round 3, `exp-batched-shared-model.md`) — the residency half holds, the
  speed half needs a graph.** FP8 halves the weights (1.946 GB → 0.973 GB for a 973 M-parameter
  stack) and the *GEMM chain* runs **3.00×** faster. But end-to-end the step is
  **1.29×**, because the FP8 path is **launch-bound** (the host spends 9.35 ms issuing the
  step — as long as the step itself). Capturing the step in a CUDA Graph takes it to
  **1.66–2.42×**. **And FP8 costs 15–22 % output error** on a 16-layer stack, so the
  residency unit may be FP8 while the *output* of the thing that checks the work stays BF16.

### 6. FP8 activations, not just FP8 weights

- **Thor feature:** Blackwell FP8 tensor cores.
- **The idea.** EXP C measured that a diffusion-shaped GEMM chain with **weights** in FP8
  but activations in FP16 runs at **0.95×** — no faster — because every layer pays a
  cast and a scale allocation. The real prize is a generator that keeps activations in
  FP8 end-to-end (fused QKV/attention/MLP), which is what ComfyUI's fp8 flag is *trying*
  to do.
- **What it unlocks for the user.** The true 1.6–1.7× on every generator — so the night
  fits more work, or the same work in half the time, which means more branches explored
  before you wake up.
- **Smallest experiment.** Half a day: benchmark one fused block (QKV → attention → MLP) on
  this box with weights in FP8 and activations **kept** in FP8 (no per-layer cast), against
  the FP16 version. **Kill it if the fused version is under 1.3×** — then the cast was
  never the bottleneck and something else is eating the gain.
- **Status: unproven, and it is the specific thing that makes idea #5 worth anything.**
- **Status: MEASURED (round 3, `exp-batched-shared-model.md`) — YES, AND THE MULTIPLIER IS
  BIGGER THAN ANYONE ASSUMED.** On a realistic 8-GEMM chain (156 GFLOP, the shapes a
  transformer actually uses): FP8 weights with a cast per layer = **1.29×**; FP8 weights
  with the activations **kept** in FP8 between the GEMMs = **3.00×** (301.7 TFLOPS against
  BF16's 100.9). With **calibrated per-tensor activation scales** it is **2.60×** — and
  the calibrated version is *more accurate* (15.9 % vs 22.0 % output error), because the
  unscaled version drifts into e4m3's limited range. **Round 1's "FP8 weights alone buy
  nothing" (0.95×) was right and is now explained: it measured exactly the cast-per-layer
  path.** The multiplier is real, it is per-shape (1.26× on a skinny GEMM, 2.96× on a fat
  one), and it only reaches the user if the serving loop captures its step in a CUDA Graph.

### 7. The critic reads the render buffer, not a PNG

- **Thor feature:** unified memory.
- **The idea.** Cycles renders into a buffer; the vision critic reads that buffer
  directly — no PNG encode → file → decode → tensor. This is the "critic on the same
  pixels" idea made literal.
- **What it unlocks for the user.** The critic's verdict latency drops by the encode/decode
  step. More interestingly, the critic can read **intermediate** Cycles passes, so it can
  judge a render *while it is rendering* and stop a bad render early instead of after it
  finishes. On a night of hundreds of renders, aborting bad ones early is worth more than
  any throughput gain.
- **Smallest experiment.** Two hours: render one 480p frame, then time (a) PNG write +
  read + decode → tensor, versus (b) the direct buffer → tensor route from EXP A.
  **Kill it if (a) is under 100 ms** — then the round-trip was never worth removing.
- **Status: unproven, cheap to test, and it composes with idea #4's "judge mid-render".**
- **Status: MEASURED (round 2, `exp-critic-png-roundtrip.md`) — USEFUL, and bigger than
  expected.** Measured on **real Cycles renders** (480p / 1080p / 4K) with the pixel
  equality between the two paths *verified* (max |A_pixels − B_pixels| = 0). The PNG round
  trip costs **48.5 ms / 293.0 ms / 1,201.8 ms** against a critic forward pass of
  **4.9 / 4.6 / 5.3 ms** — it is **10× to 228× the critic's own cost**, so the
  "kill it if under 100 ms" condition is not triggered. **88 % of the round trip is the PNG
  *encoder***; the file write and read together are 1.5 ms at 4K, and tmpfs is no faster.
  Zero-copy from the render buffer is **2.9–3.5× faster end-to-end**. Corollary for the
  middleware (idea #10): **the critic is CPU-codec-bound, not GPU-bound and not
  disk-bound** — it competes with the renderer for CPU.

### 8. NVENC: the morning report as a film you actually watch

- **Thor feature:** NVENC (AV1 + H.265 + H.264, verified present in the encoder API;
  `/dev/v4l2-nvenc`).
- **The idea.** The night's renders become a timelapse encoded by a dedicated hardware
  engine that runs **in parallel with everything else** — it does not compete with the
  GPU for tensor cores. "Store recipes, not meshes" extends to "store the morning as a
  video, not a folder of PNGs". The ProArt's RTX 4050 hardware-decodes it (Ada NVDEC
  handles AV1).
- **What it unlocks for the user.** The morning report becomes a 60-second film of the
  night's work instead of a grid of thumbnails. It plays on a phone on the train. It costs
  essentially zero GPU time, so it can be produced *every* night without being budgeted.
- **Smallest experiment.** Half a day: encode 100 frames at 1080p60 in H.265 and AV1,
  measure sustained fps, the `tegrastats` power draw, and confirm `nvidia-smi` GPU
  utilisation stayed near zero (proving it is free). Then transfer one 30 s clip over the
  current 2.4 GHz Wi-Fi and time it. **Kill the "cheap" claim if NVENC pushes the GPU
  above a few percent utilisation or the clip does not fit the wire.**
- **Status: unproven.** Note the wire interaction with idea #13.
- **Status: MEASURED (round 3, `exp-nvenc-roundtrip.md`) — THE FREE CLAIM HOLDS, AND ONE
  DETAIL IS WRONG.** NVENC genuinely does not compete with the tensor cores: a 4096³ BF16
  matmul loop ran **+0.2 % / −1.3 %** slower while an NVENC encode ran beside it. The video
  engine is on its own clock domain (`gpu-nvd-0`, max 1692 MHz, separate from the tensor
  cores' `gpu-gpc-0` at 1575 MHz). The compression is extraordinary: **30 frames of a
  512×512 field in 38.6 KiB** — 199× smaller than raw uint8 and 134× smaller than
  *lossless* PNG. **But AV1 does not work on this Thor**: `av1_nvenc` fails at every bitrate
  with *"Failed locking bitstream buffer: invalid param"*, so the morning report is H.264 or
  H.265 — and the ProArt's "Ada NVDEC handles AV1" advantage in the idea text does not
  apply, because nothing here produces AV1.

### 9. NVDEC: a critic that can see time

- **Thor feature:** NVDEC.
- **The idea.** Today the critic scores frames. If the Thor decodes its own night clips,
  the critic can score *sequences* — camera smoothness, flicker, temporal popping, whether
  a rebuild looks like a rebuild. **No frame-based critic can see flicker**, and flicker is
  exactly what an overnight loop that re-renders between recipe edits produces.
- **What it unlocks for the user.** The builders stop shipping a world that pops and
  flickers between edits — a defect class that only the overnight loop creates, and which
  no still-image critic can catch.
- **Smallest experiment.** One day: encode a short AV1 clip with a deliberately introduced
  flicker, decode it through NVDEC into a torch tensor (checking whether that path is
  zero-copy), and compute a temporal-difference metric. **Kill it if the metric does not
  separate flickering from clean frames**, or if NVDEC→torch forces a copy that costs more
  than re-rendering the frames.
- **Status: unproven.** Pairs with idea #8 (encode) — the two engines face each other.
- **Status: MEASURED in the adjacent direction (round 3, `exp-nvenc-roundtrip.md`) — THE
  DECODER IS NOT THE PROBLEM; THE ENCODER'S FIDELITY IS.** The H.264/H.265 round trip leaves
  **1.72–3.07 % RMSE** on the field (30–35 dB PSNR) even at 5 Mbit/s — the error does
  **not** go to zero with bitrate, because the limited-range 8-bit YUV pipeline is the floor.
  That is fine for a film you watch and fatal for a state you warm-start from: fed a warm
  start that has been through the codec, the equilibrium loop needs **6 iterations —
  exactly as many as a cold start** (an exact warm start needs 4). **A video codec is a good
  store for the morning report and a bad store for the world state.**

### 10. PVA: the only engine that can run while the GPU sleeps

- **Thor feature:** PVA v3 (`/dev/nvhost-ctrl-pva0`).
- **The idea.** PVA is a separate accelerator that can run a small CNN at low power while
  the GPU is saturated with a night batch. Use it for the always-on cheap perception that
  vision.md's context packet needs — "what am I looking at" — so a builder can answer a
  question **without waking the GPU**.
- **What it unlocks for the user.** The talk clock (≤2 s) survives a saturated GPU. Right
  now, a night batch and a question from the human compete for the same device.
- **Smallest experiment.** Half a day: run one PVA-supported task (e.g. a people/face
  detection from the Jetson samples) and record watts and latency; then run it
  concurrently with a saturated GPU and confirm it does not slow the GPU down.
- **Status: PARKED.** There are **no cameras attached** on this box — `ls /dev` shows no
  `/dev/video*` capture nodes — so this needs a USB webcam before it can be measured.
  PVA itself is real and present; the input is missing.

### 11. All 14 cores: the honest ceiling is ~4.4×, and it is still worth taking

- **Thor feature:** 14 Neoverse-V3AE cores.
- **The idea.** Infinigen's CPU stages are single-threaded **today**: the constraint
  solver, the camera-trajectory search (`max_tries=50000`), and the mesh exporter (which
  applies all modifiers and realises instances). Rewrite the top three as numba/C++ with
  the 14 cores, and keep the CPU lane fed while the GPU works.
- **What it unlocks for the user.** The night plan's "CPU lane never idles" assumption
  becomes real. And with the GPU freed from procedural stages, the CPU has actual work.
- **Smallest experiment.** One day: take the Infinigen spike's own `pipeline_coarse.csv`
  (the stage timings are already being recorded) and pick the top 3 CPU stages; measure
  each under a numba/parallel rewrite. **Kill it if the top 3 are under 20 % of total
  wall time** — then give the CPU to the GPU and stop pretending.
- **Status: measured (the ceiling).** numba `prange` gave **4.4×** on a simple kernel
  (10.5 ms → 2.4 ms) and NumPy 14-thread gave only **4.6×** on the fBm (allocation-heavy,
  bandwidth-bound) — both **with another seat's build competing for cores**, which is the
  realistic condition. So "use all 14 cores" is a 4–5× lever, not 14×. Note the GPU
  shares this same memory bandwidth.

### 12. The NVMe's bandwidth decides the shape of the whole scheduler

- **Thor feature:** the internal NVMe (343 GB free) + the 1.9 TB external SSD cold shelf
  + the 122 GB unified pool.
- **The idea.** The scheduler's entire hot/warm/cold tiering rests on one number nobody in
  the plan has measured: **how fast does a 7.45 GB (or 3.73 GB in FP8) weight file move
  from NVMe into unified memory?** If it is ~3 GB/s, a model load is 2.5 s and the tiering
  is over-engineered; if it is 200 MB/s, thrash is real and FP8's halving (idea #5) is
  the fix that matters most.
- **What it unlocks for the user.** Nothing visible directly — but it is the number that
  decides whether the overnight loop spends its time *generating* or *loading*, and that
  difference is the whole morning report.
- **Smallest experiment.** One hour: write an 8 GB file to the internal NVMe and to the
  external SSD, then time reading it back into unified memory (`torch.load` into a CUDA
  tensor). Report GB/s for both devices, with the box's state beside the number.
  Residency must be measured from `/proc/meminfo` + `tegrastats` — **`nvidia-smi` cannot
  report GPU memory on this box** (rev-tech §C9).
- **Status: unproven. This is the cheapest high-value measurement still outstanding.**
- **Status: MEASURED (round 2, `exp-nvme-bandwidth.md`) — USEFUL.** Cold NVMe → unified
  memory runs at **1.15–1.68 GB/s** (verified cold with `posix_fadvise` + **`mincore()`**,
  not assumed), so a 7.45 GiB fp16 checkpoint takes **6.5 s** cold and **1.7–4.3 s** warm;
  `torch.load(map_location='cuda')` of a 3.73 GiB checkpoint takes **1.78 s** cold /
  **0.78 s** warm, and the H2D copy runs at 34.9 GB/s while a zero-copy GPU read of the
  freshly loaded bytes runs at 60.4 GB/s. **So a model load costs seconds, not minutes**,
  and the tiering is over-engineered — but the conclusion is sharper than that: **the warm
  tier already exists for free** (after any read the file is 100 % resident in the page
  cache, which *is* unified memory), so the real design question is **what to pin**, not
  how to move bytes. Cold-tier latency (6.5 s) is longer than the critic's ≤5 s watch
  clock, so a cold model cannot be swapped mid-session.
- **Two corrections from the same round.** The external cold shelf (1.9 TB, `/dev/sda1`,
  **fuseblk**) **stalled mid-write and never recovered** — it took the box's I/O paths
  down with it (every access, and even `os.sync()`, blocked forever) — so the shelf tier is
  **currently unusable and unmeasured**, and it should be planned as an *archive* tier, not
  a cache tier. And "1.2–1.7 GB/s", not the ~3 GB/s this idea guessed: the guess was
  optimistic by ~2×.

### 13. The 5 GbE cable is a prerequisite, not a nice-to-have

- **Thor feature:** the r8126 5 GbE RJ45 port (**currently DOWN — no cable**) and the
  QSFP28 cage (**unpopulated**).
- **The idea.** Two of the ideas above (the NVENC filmstrip #8, the LOD state stream) both
  cross the wire between the Thor and the ProArt. On the current 2.4 GHz Wi-Fi (PHY
  229/207 Mbps measured) a 1080p60 AV1 clip is tight; on 5 GbE it is trivial. The
  hardware breakthrough here is literally one cable.
- **What it unlocks for the user.** The morning filmstop becomes reliable instead of
  conditional; the ProArt's day view stops competing with the night's video for the same
  radio.
- **Smallest experiment.** One hour, and it needs Casey's cooperation to plug the cable:
  `iperf3` in both directions, then transfer one real 1080p60 AV1 clip and time the
  playback. **Kill the "trivial" claim if the sustained rate is below the clip's bitrate.**
- **Status: unproven, and the cheapest experiment on this list** — but it needs a human
  with a cable.
- **Challenge (already answered, don't re-litigate):** the QSFP28 4×25 GbE is real
  silicon — four `tegra264-mgbe` MACs are in the device tree — but **no cage is
  populated** and the ProArt has no matching port. It is a purchase, not a dependency.

### 14. Cycles renders straight into NVENC — the film is a by-product, not a post-process

- **Thor feature:** unified memory + NVENC together.
- **The idea.** If the Cycles output buffer and the NVENC input surface live in the same
  unified pool, then "render then encode" needs no file and no host copy: Cycles writes a
  frame, NVENC consumes it, and the night's film is produced *as a side effect of
  rendering*. The difference is between "the night's renders are files we later encode"
  and "the night produces a film".
- **What it unlocks for the user.** A timelapse of a whole branch flip costs no extra time
  and no extra pass; the morning report's video is free, so it can be produced every
  night without being budgeted.
- **Smallest experiment.** Half a day: feed 50 rendered frames to NVENC through
  GStreamer / jetson-multimedia and measure whether the path is copy-free — compare GPU
  utilisation and wall time against the file round-trip. Use a stand-in renderer first so
  the experiment does not wait on the bpy 4.2 aarch64 build.
- **Status: unproven.** Depends on `bpy` 4.2 landing, but the NVENC half can be tested
  now with a stand-in.

---

### 15. The decode step is a CUDA Graph, not a Python loop

- **Thor feature:** Blackwell tensor cores plus a host that cannot feed them.
- **The idea.** EXP 5a measured the thing every model plan on this box has to account
  for: the FP8 path is **launch-bound**. The host spends **9.35 ms** issuing a decode
  step, and the step takes 9.35 ms — the GPU is idle a third of the time waiting for
  Python. Capturing the step in a CUDA Graph removes **99.7 % of the host work**
  (enqueue **2.38 ms → 0.008 ms**) and turns the FP8 advantage from **1.29×** into
  **1.66–2.42×**.
- **What it unlocks for the user.** The whole FP8 story becomes reachable. Right now the
  plan has to choose between *model quality* (FP8's 15–22 % output error) and *speed*
  (the launch overhead eats the gain). A graph removes the reason for the trade. And on a
  shared box the graph is worth more as a **reproducibility** tool than as a speedup: the
  graphed time varied **6 %** across runs while the eager time varied **3.4×**.
- **Smallest experiment.** Two hours: capture one real generator's decode step
  (`torch.cuda.graph`) and record the step time eager vs graphed, the joules per item
  from the rails, and the CPU issue time. **Kill it if the graph does not change the step
  time** — which would mean the step was already GPU-bound and the launch overhead was
  not the constraint.
- **Status: MEASURED on a synthetic 16-layer stack (round 3, `exp-cuda-graphs-nvenc.md`) —
  CONFIRMED. Untested on the real generator, and it is the cheapest high-value thing left.**

### 16. Batch the agents by their KV cache, not by their count

- **Thor feature:** unified memory; a 128 GB shared heap.
- **The idea.** Kimi's claim is that batching N agents costs the bandwidth of one, because
  the weights stream once. That is true **only while the agents have no context**. EXP 2
  measured it: in the weights-only regime the step time is **flat from N = 1 to N = 8**,
  but with a realistic **1024-token** context it grows **13.6 ms → 53.7 ms** from N = 1 to
  N = 128 — because at N = 128 the per-agent KV cache is **4.3 GB against 1.9 GB of
  weights**. The cache is per-agent and it scales with N.
- **What it unlocks for the user.** A scheduler with a *batch limit that is a function of
  the context length*, not of the model. An agent on a long context should be batched
  with fewer neighbours; a short-context agent can have many. That is a one-line change
  to the scheduler's admission rule and it is worth more than any further weight
  optimisation, because the joules per item fall **186×** between N = 1 and N = 512.
- **Smallest experiment.** Half a day: sweep N against S on the real context lengths the
  builder actually holds, and fit the curve. **Kill it if the KV cache is not what breaks
  the batching** — then the limit is something else and the rule stays simple.
- **Status: MEASURED on a synthetic stack (round 3, `exp-batched-shared-model.md`) — the
  effect is real and large. The real context lengths are not yet known.**

### 17. A skill is a merged resident model, not a switched adapter

- **Thor feature:** 128 GB of unified memory; a 15.7 M-parameter adapter is 60 MiB.
- **The idea.** Kimi's shape is "one shared base, skills as adapters, switch per builder".
  EXP 3 measured both halves: the **adapter** is cheap (15.7 M params, 60 MiB, ~14 ms on
  a 1.64 B-parameter forward), but the **switch** is not — PEFT's `set_adapter` costs
  **75–120 ms of host time** because it is O(layers × adapters) in Python, and it is
  *flat* in the number of resident adapters, so it never gets cheaper as the craft count
  grows. PEFT's mixed-adapter batch is **10× worse at 32 adapters** (5 120 one-row
  GEMMs). The alternative shape is the one the project already believes in for meshes:
  **recipes, not shared state**. A craft is a *merged* model — the adapter folded into a
  resident copy of the base — and the scheduler routes requests to the craft model that
  is already resident, like it routes to a stage.
- **What it unlocks for the user.** Skills that cost **no per-request switch** at all.
  The price is 60 MiB + a 2.2 GiB base per craft, so this only works for a **small number
  of crafts** — which is probably right: a builder has a handful of crafts, not
  hundreds. It also makes the skill *a model*, which the project's asset/licence rules
  can reason about.
- **Smallest experiment.** One day: merge three adapters into three resident copies of a
  real base and measure (a) the merge cost, (b) the per-request cost of serving from a
  merged model against serving from the base with an adapter attached, (c) the resident
  footprint of K merged crafts for K = 4, 8, 16. **Kill it if the merge cost dominates** —
  then the adapter has to stay attached and the switch has to be optimised instead.
- **Status: MEASURED on the cost side (round 3, `exp-adapters.md`) — the switch is the
  problem, and merging is the obvious alternative. Unmeasured on the resident side.**

---

## Part B — killed by fact (recorded so nobody re-proposes them)

- **OFA as a real-time mesh deformer.** There is **no OFA device node** on this box:
  `ls /dev` shows `nvhost-ctrl-pva0` (PVA), the two ISP channels, `/dev/v4l2-nvenc` and
  `/dev/v4l2-nvdec` — no OFA. Casey's idea #5 is wrong *as framed*; the surviving kernel
  (camera/hand input as a sculpt brush) is ordinary software.
- **Camera injection ports / C-PHY / D-PHY.** No cameras are attached and there are no
  `/dev/video*` capture nodes. "20 feeds" and "10× 4K60 decode" describe Thor automotive
  configurations, not this devkit. (This is what parks idea #10.)
- **4× 25 GbE / 100 Gbps to the laptop.** Real silicon, no cage, no matching port on the
  ProArt. See idea #13 for what *is* cheap.
- **Sizing work against 2,070 TFLOPS FP4.** EXP C measured FP4 at **13.69 TFLOPS** on
  this stack, and *slower than dequantising to BF16 and multiplying*. That figure is a
  dataclass NN-inference number and is not available here.
- **"122 GB makes VRAM a non-issue."** Right about capacity, wrong about contention, and
  **unobservable**: `nvidia-smi` reports `memory.total`/`memory.used` as `[N/A]` on this
  box. Eviction must be driven by `/proc/meminfo` + `tegrastats`. (Note: this also means
  the Infinigen spike's `run-timed.sh` records `maxGPUmem=0MiB` on every run — worth
  fixing before SPIKE.md publishes numbers.)

### Killed in round 3 (see the end of this file for the numbers)

- **NVENC/NVDEC as the warm-start store for world-state latents.** The compression is
  superb (199×) and the engine is free (it does not touch the tensor cores) — but the
  round trip leaves **1.7–3.1 % RMSE** on the field, and that error is *larger than the
  perturbation a warm start corrects*. A warm start that has been through the codec
  converges in **6 iterations — the same as a cold start**, against 4 for an exact one.
  A lossless 8-bit store keeps the full warm-start advantage at no cost. **Use the codec
  for the film; use 8 bits for the state.**
- **"Switch the active adapter per request" (PEFT's multi-LoRA server shape).**
  `set_adapter` costs **75–120 ms of host time per call** — O(layers × adapters) in
  Python — which is *more than the request it precedes*, and it is flat in the number of
  resident adapters, so it does not get cheaper as the skill count grows. The naive
  "copy the 60 MiB of weights into the active slot" is **faster** (45 ms).
- **PEFT's mixed-adapter batch as the way to serve many builders at once.** Break-even at
  N ≤ 8 and **10× worse at N = 32** (1161 ms/request against 109 ms), because it
  degenerates into 160 layers × 32 one-row GEMMs plus 5 120 index-scatters.
- **The critic on the CPU.** With the GPU busy, the same 6 iterations take **2.2× longer**
  and cost **2.5× the joules**. Combined with round 1's finding that there is no spare
  accelerator on this box, the critic has to share the GPU and the *schedule* has to
  arbitrate.
- **Sizing the scheduler against 273 GB/s.** This box delivers **166 GB/s** eager and
  **~220 GB/s** graphed. Any `T_pass` computed from the datasheet is a `T_pass` that cannot
  be achieved.
- **Batching N agents costs the bandwidth of one.** True only while the agents have no
  context. With a 1024-token context the step time grows **13.6 → 53.7 ms** from N = 1 to
  N = 128, because each agent's KV cache is its own: at N = 128 the cache is **4.3 GB
  against 1.9 GB of weights**.
- **AV1 on this Thor's NVENC.** `av1_nvenc` fails at every bitrate.

---

## Part C — what I would run next, in order

Each is a day or less and each unlocks a decision the plan depends on.

| # | Experiment | Time | What it decides |
|---|---|---|---|
| 1 | **NVMe → unified-memory load bandwidth** (idea #12) | 1 h | The shape of the whole hot/warm/cold scheduler |
| 2 | **The `ls /dev` and `nvidia-smi` fact-check is already done** — instead: fix `run-timed.sh` to sample `tegrastats` for memory | 15 min | The spike's published numbers stop reading `maxGPUmem=0MiB` |
| 3 | **ComfyUI `--fp8_e4m3fn-unet` on a real model** (ideas #5, #6) | 1 day | Whether the scheduler's residency unit is FP8 |
| 4 | **The critic's PNG round-trip vs zero-copy** (idea #7) | 2 h | Whether the critic's ≤5 s clock is I/O-bound |
| 5 | **Extract one solver stage's scoring function; time Python vs numba vs Warp** (idea #3) | 4 h | Whether the Architect can ever work in daylight |
| 6 | **Plug the 5 GbE cable and iperf3** (idea #13) | 1 h + a human | Whether the filmstrip channel is real |
| 7 | **Port one Infinigen terrain element to Warp** (idea #2) | 1 day | Whether the procedural stage rewrite is worth it |
| 8 | **OcMesher: is the cost SDF evaluation or octree bookkeeping?** (idea #4) | 1 day | Whether live re-meshing is possible |

Items 1, 4 and 6 are the cheapest and each answers a question the plan is currently
guessing at.

### Round 2 ran items 1, 4, 5 and 7 — here is what they decided

| # | Result | Verdict | File |
|---|---|---|---|
| 1 | Cold NVMe → unified memory is **1.15–1.68 GB/s**; a 7.45 GiB checkpoint loads in **6.5 s** cold, **1.7–4.3 s** warm; the page cache *is* the warm tier. The external cold shelf **stalled and is unusable**. | useful | `exp-nvme-bandwidth.md` |
| 4 | The PNG round trip is **48.5 / 293 / 1,202 ms** at 480p / 1080p / 4K against a **4.6–5.3 ms** critic — **10× to 228×** the critic's cost, and **88 % of it is the encoder, not the disk**. Zero-copy is **2.9–3.5×** faster end-to-end. | useful | `exp-critic-png-roundtrip.md` |
| 5 | The GPU scores **47.95 M candidates/s** (**3,394×** the current shapely path) — but at the solver's real pattern (one candidate per step) the **restructured CPU wins by 7.5×**. The GPU needs the proposal step batched. | useful, with a condition | `exp-solver-scoring.md` |
| 7 | A Warp port of Infinigen's `mountains` element is **bit-identical** to Infinigen's own CPU *and* CUDA libraries over 16 M points, and is **44–56× the CPU path** and **6× Infinigen's own CUDA kernel**. | **breakthrough** | `exp-warp-terrain-port.md` |

**Still open after round 2:** items 2, 3, 6 and 8. Item 6 needs a human and a cable.
Item 8 is now the natural next experiment, because item 7 answered its sibling
("the procedural rewrite is worth it") and left the other half ("is the cost SDF
evaluation or octree bookkeeping?") untouched.

### Round 3 ran Kimi's six claims, and five of them moved

| # | Kimi's claim | Measured | Verdict | File |
|---|---|---|---|---|
| 1 | NVLA / PVA / NVDLA as critic, scheduler or mesh-deformer engines | **No NVDLA device node exists** (`ls /dev`: PVA, two ISP channels, `/dev/v4l2-nvenc`, `/dev/v4l2-nvdec` — no OFA, no NVDLA). PVA is not schedulable from userspace. **AV1 has no NVENC encoder on this Thor.** | **killed** | `exp-engines.md` |
| 2 | One shared model, N agents batched; weights stream once per pass | Step flat N=1…8, then grows; **13.6 → 53.7 ms** from N=1 to N=128 once the agents have a 1024-token context | **half right** | `exp-batched-shared-model.md` |
| 3 | FP8 as the multiplier; re-derive it | **3.00×** on the GEMM chain, **1.29×** end-to-end (launch-bound), **1.66–2.42×** graphed, at **15–22 %** output error | **re-derived** | `exp-batched-shared-model.md`, `exp-cuda-graphs-nvenc.md` |
| 4 | Skills as LoRA adapters on one shared base, switched per builder | Adapter is **15.7 M params / 60 MiB** and costs **~14 ms**; but **switching costs 75–120 ms** and the mixed batch is **10× worse** at 32 adapters | **half right** | `exp-adapters.md` |
| 5 | Warm-started equilibrium loops, 2–3 iterations; joules per fixed point as the governing metric | **2–3 iterations warm, 6 cold**; joules = **1.39 J × iterations**; a **lossless 8-bit store is free** | **confirmed** | `exp-joules-per-fixed-point.md` |
| 6 | NVENC/NVDEC for world-state latents between frames (warm start) | The engine is **free** (+0.2 %) and **199×** compressive — but the round trip leaves **1.7–3.1 % RMSE** and **destroys the warm-start advantage** | **killed as a store, confirmed as an engine** | `exp-nvenc-roundtrip.md` |

### What round 3 says to run next, in order

| # | Experiment | Time | What it decides |
|---|---|---|---|
| 1 | **Capture the real generator's decode step in a CUDA Graph** | 2 h | Whether the 1.66–2.42× graphed FP8 gain is reachable in the real pipeline, or whether the real model's shapes differ. **This is the highest-value cheap thing in the list.** |
| 2 | **Re-measure the whole round on a quiet box** (load < 8) | 1 h | The box ran at load 15–113 during round 3. The *ratios* held; the absolutes did not. A clean re-run turns every range in round 3 into a number. |
| 3 | **Graph-capture PEFT's mixed-adapter batch** | 4 h | The mixed path is 160 layers × N one-row GEMMs — exactly the launch-bound case a graph removes. If it captures, the 10× penalty at N = 32 may vanish. |
| 4 | **Skill adapters as *merged* resident models**, not switched ones | 1 day | 60 MiB + a 2.2 GiB base per craft group, versus 75–120 ms per switch. Which is cheaper depends on how many crafts and how many requests per second. |
| 5 | **The real critic's forward pass in FP8 vs BF16** (items 3 and 8 of round 2, re-scoped) | 1 day | Whether the critic can afford FP8's 15–22 % error at all — round 1 says keep it in BF16, and round 3 has the number to argue with. |
| 6 | **The KV-cache-aware batch limit** | 4 h | Round 3 measured the *shape* of the effect (batching stops being free at N ≈ 2 with a 1024-token context). The scheduler needs the actual curve for the real context length. |
| 7 | **Part C items 2, 6 and 8 from round 2 are still open** | — | Item 6 needs a human and a cable; item 8 is still the natural next *kernel* experiment. |

---

## Part D — cross-cutting traps found in this round

These are not ideas; they are the things that will silently cost hours if nobody writes
them down.

1. **Never call `.cpu()` on a large tensor into pageable memory.** Measured at
   **0.34 GB/s** — 11.9 s for 4 GB, 258× slower than the pinned path, and it never
   errors. It just takes eleven seconds.
2. **`wp.from_numpy()` copies.** It returns a *device* array. Use
   `wp.array(ptr=host_ptr, dtype=..., shape=..., copy=False)` to actually share a buffer.
   CuPy's equivalent is `cupy.cuda.UnownedMemory` + `MemoryPointer`.
3. **Warm a numba JIT with a C-contiguous array of the same rank**, or the timed call
   silently recompiles a second layout specialisation *inside the timed region* — this
   reported 513 ms for work that takes 3.8 ms.
4. **A GPU port must beat a *restructured* CPU, not the current one.** Against the
   current CPU code the GPU is 7.9–10.5× faster; against a restructured CPU
   implementation the two are level (0.91×–1.53× across runs). The algorithm and the
   port are one job, not two.
5. **`nvcc` defaults to sm_75 on this box** (PTX-JIT tax; SASS-only builds fail outright).
   Warp sidesteps this by compiling natively for sm_110 — verified: its cached cubin is
   `sm_110.sm_110.cubin` with **no PTX embedded**. But any *hand-written* CUDA extension
   must pass `-arch=native` and be verified with `cuobjdump --list-elf`.
6. **`nvidia-smi` cannot see GPU memory here.** Use `/proc/meminfo` `MemAvailable` and
   `tegrastats` RAM. Any future report asserting a GPU memory figure must say how it was
   measured.
7. **The box is shared.** During these experiments another seat's `cmake` build held load
   at ≈ 4–5, and the 14-core scaling figure (4.4×) was measured *under that load* —
   which is the realistic condition. Every measurement in this directory records the
   load beside the number.
8. **Do not transcribe C into another language — compile it into an oracle.** Round 2's
   Warp port of Infinigen's `mountains` was wrong *twice* in the same 12-line hash chain:
   Blender's `hash_bit_final` ends with `c -= hash_bit_rotate(b, 24)` (it rotates **b**,
   not c) and its middle step is `b -= hash_bit_rotate(a, 25)` (rotates **a**, not b).
   Both misreadings produced a plausible-looking 7 % output error. **Compile the original
   headers into a tiny program and diff the intermediates** (`vendor/infinigen-terrain/oracle.cpp`
   does this) — it turned a day of guesswork into ten minutes and is the single most
   reusable thing in this round.
9. **Warp's mutable variables inside `if` blocks are a trap.** A probe kernel that assigned
   a variable inside an `if/elif` chain returned a corrupted value (`0xdeafa148` instead of
   `0xdeafd03c`) and sent the hunt for a bug in the hash that did not exist. Use
   `wp.where(...)` selects instead of branches for anything that is read after the branch.
10. **`posix_fadvise(DONTNEED)` silently does nothing to a file with dirty pages.** The
    first "cold" disk numbers in round 2 were optimistic by up to 2× because the files had
    just been written. `fsync` the file first, and **verify with `mincore()`** — do not
    trust the eviction.
11. **Never call `os.sync()` on this box.** It syncs *every* filesystem, including the
    external FUSE mount, and blocks forever if that mount is wedged. `fsync` the one file.
12. **An argmin over a set with duplicates is not a function.** The solver's
    `closest_edge_to_point_edge_list` is ambiguous for **~17 % of candidates** (at a
    polygon corner, two adjacent edges are exactly equidistant). Two correct
    implementations can return different scores, and a port that breaks ties differently
    changes the *solver's decisions*, not just its speed. Measure the ambiguity rather than
    calling the difference a bug (`scripts/exp5_tie_diagnostic.py`).
13. **An external FUSE mount can take the box's I/O down with it.** The cold shelf stalled
    mid-write and every later access — including `os.sync()` — blocked indefinitely; two
    processes are still in `D` state on it and cannot be signalled. Bound every device
    operation with a timeout and plan the shelf as an archive tier, not a cache tier.
14. **The GPU clock ramps, and the first measurement of a session is 2.6× slow.** The Thor
    idles at **315 MHz** and ramps to **1575 MHz** under `nvhost_podgov`, taking ~1.4 s of
    *sustained* load. Measured: a cold 8-GEMM chain is **3.51 ms**, the same chain after
    1.4 s of warm-up is **1.40 ms**, and 5 s of idling puts it back to 1.84 ms. **Warm the
    GPU before timing anything and record the clock beside the number** — this applies to
    every GPU figure in rounds 1 and 2 as well.
15. **Time the variants you are comparing in *interleaved* rounds.** On a shared box the
    absolute time of anything drifts 2–3× with the other seats' load. Two blocks
    measured back to back are not comparable; two variants measured in the same rounds are.
    This is what turned exp 5a's 2.8× disagreement between runs into a ratio.
16. **A CUDA Graph's replay time is the pure GPU cost, so it moves with the box's *GPU*
    tenants, not with the CPU load.** With another seat's ComfyUI server rendering, the
    graphed BF16 step measured 8.83 ms on a quiet GPU and 20.29 ms with the tenant
    rendering. **Every absolute GPU number on this box is a range; only ratios are
    numbers.**
17. **The whole-box INA rail needs an idle baseline, and even then it is only good for
    work that dominates the box.** With three other tenants, the raw whole-box joules for
    a one-second ffmpeg subprocess came out *below* the idle baseline (negative
    "joules above baseline"). **Subtract the baseline, and if the result comes out
    negative, report the wall time instead.**
18. **PEFT's `set_adapter` is O(layers × adapters) in Python, and it makes the adapter
    *trainable* while it does it** (`inference_mode=False` is the default). 160 LoRA layers
    × 32 adapters = 10 240 `requires_grad` rewrites per switch.
19. **The PEFT adapter is FP32 even when the base model is BF16.** A "15.7 M-parameter
    skill" is 60 MiB on the device, not 30 MiB. Size the skill budget in *bytes*, not in
    parameters.
20. **`torch._scaled_mm`'s scale tensors must be allocated once, outside the timed loop.**
    Creating them inside is a synchronous H2D copy per GEMM, which costs more than the
    GEMM.
21. **A tensor with outliers needs an RMS difference, not a max-abs one.** DINOv2's output
    has elements up to 15.9 against an RMS of 1.40; a max-abs comparison reported two
    adapters as "13 apart" when their RMS difference was 1.3 % and the truth was ~10 %.
22. **Grouped-query attention must not materialise a `repeat_interleave` copy of the KV
    cache.** The copy is 4× the cache and it turns a bandwidth measurement into a
    measurement of the attention implementation (234 ms/step against 54 ms).
23. **This ffmpeg has no `scale` filter.** It cannot convert `rgb24` → `yuv420p`
    (*"scale filter not present"*); the pixel format has to be produced in Python. NV12 is
    accepted directly by `*_nvenc`.

## Licence note for everything in this directory

Code only, no model weights were downloaded: `torch` (BSD-3-Clause), `cupy` (MIT),
`numpy` (BSD-3-Clause), `warp-lang` (Apache-2.0), `numba` (BSD-2-Clause),
`llvmlite` (Apache-2.0), `torchao` (BSD-3-Clause). No shipped-asset licence implications
from this round's work.

---

## Corrections after a clean re-run

All three scripts were re-run from scratch (empty Warp cache) after these files were
written, to confirm they reproduce. Two published claims did not survive, and both are
corrected above and in the `exp-*.md` files:

1. **"A restructured CPU beat the GPU port by 1.53×"** (EXP B, idea #2, Rule 1). The
   clean re-run measured the opposite direction (GPU ahead by 1.10×). The honest result
   is that the two are **level within run-to-run noise (0.91×–1.53×)**. The claim was
   drawn from a single run on a shared box and was over-read; it is now stated as a
   range, and the conclusion — that a GPU rewrite must ship with the algorithmic work —
   is unchanged but weaker than first written.
2. **A numba figure of 513 ms** in an earlier EXP B run was **JIT compile time leaking
   into the timed region** (a non-contiguous warm-up forced a second layout
   specialisation). The real figure is 3.8–7.9 ms. The published tables use the
   corrected run.

Everything else reproduced within the ranges stated: zero-copy match and chain `True`
(EXP A), 2.13× vs 2.15× copy+read, FP8 185.95 vs 176.96–182.57 TFLOPS, NVFP4 ratio
1.77 vs 1.75, FP8-weights-only chain 0.94× vs 0.95×.

**The lesson for the lab, worth carrying into the next round: on a shared box, publish
ranges and re-run before publishing a conclusion.**

---

## Round 2 — what changed

Four experiments, in the order the brief asked for them: Part C items **1**, **4**, **5**
and **7**. One file each, with the numbers, the box's state beside every number, and the
failures that stayed.

| file | what it measured | verdict |
|---|---|---|
| `exp-nvme-bandwidth.md` | NVMe → unified-memory load bandwidth, cold and warm, 64 MiB → 16 GiB | useful |
| `exp-critic-png-roundtrip.md` | the critic's PNG round trip vs zero-copy from the render buffer, on real Cycles renders | useful |
| `exp-solver-scoring.md` | one Infinigen solver score term: Python vs numba vs Warp vs a restructured CPU | useful, with a condition |
| `exp-warp-terrain-port.md` | one Infinigen terrain element ported to Warp | **breakthrough** |

### The four things that changed

1. **The procedural-stage rewrite is worth it, and the proof is bit-exactness.** A Warp
   port of Infinigen's `mountains` element reproduces the existing CPU *and* CUDA libraries
   **exactly** (max |diff| = 0.0 over 16 M points) at **44–56× the CPU path** and **6× the
   spike's own hand-written CUDA kernel** — because that kernel copies its buffers through
   `cudaMalloc`/`cudaMemcpy` on every call, which is pure waste on a unified-memory box.
   *(`exp-warp-terrain-port.md`)* — and the reusable artefact is the **oracle**: compile
   Infinigen's own headers into a tiny program and diff the intermediates, rather than
   transcribing C by hand (which was wrong twice).
2. **The Architect's speed-up is a *solver* change, not a kernel change.** The GPU scores
   47.95 M candidates/s (3,394× the current path) but the solver scores **one** candidate
   per annealing step, where a restructured CPU is 7.5× faster than the GPU. The crossover
   is between 64 and 256 candidates, so the proposal step has to batch. *(`exp-solver-scoring.md`)*
   — and the scoring function's argmin is ambiguous for ~17 % of candidates, so a port must
   break ties the same way or the generated scene changes.
3. **The critic is CPU-codec-bound.** Its PNG round trip is 10× to 228× the critic's own
   forward pass, and 88 % of that is the PNG *encoder* — the disk is 0.5 % of it. Moving
   the PNG to a faster disk solves nothing; handing the critic the render buffer is
   2.9–3.5× faster end to end. *(`exp-critic-png-roundtrip.md`)*
4. **The residency tiers are a pinning policy, not a transfer system.** Cold NVMe → unified
   memory is 1.15–1.68 GB/s (so a 7.45 GiB checkpoint loads in 6.5 s cold, 1.7–4.3 s
   warm), and the page cache — which *is* unified memory — already provides the warm tier
   for free. Meanwhile the external cold shelf **stalled mid-write and never recovered**,
   taking the box's I/O paths down with it; plan it as an archive tier, not a cache tier.
   *(`exp-nvme-bandwidth.md`)*

### What this round did not settle

- **The solver stage's share of the ~38 min solve.** `thor/run-timed.sh` exists but
  `outputs/logs/` does not, so there is still no per-stage breakdown. What is measured is
  a *rate* (14,127 candidates/s today; 47.95 M/s on the GPU if batched).
- **The external shelf's read bandwidth** — it never recovered long enough to be measured.
- **The real critic.** The PNG-round-trip numbers are anchored to a ViT-shaped stand-in with
  random weights; the round trip itself was measured from real Cycles renders and does not
  depend on the model.
- **Part C items 2, 3, 6 and 8** were not run (item 6 needs a human and a cable).

### The correction this round makes to round 1

Round 1's Part D trap 5 says *"`nvcc` defaults to sm_75 on this box"* and that a
hand-written CUDA extension must pass `-arch=native`. That is still true of the *default*,
but the Infinigen spike's **current build does pass an explicit arch flag**: the built
`mountains_cuda.so` contains **native sm_110 SASS and no PTX**
(`cuobjdump --list-elf` → `mountains_cuda.1.sm_110.cubin`; `--list-ptx` → none). The
"PTX-JIT tax" is therefore a property of the default, not a wall — but it is still a
trap for anyone who writes a new `.cu` file without checking, and Warp's native sm_110
cubin remains the reason to prefer Warp for new work.

---

## Round 3 — what changed

Six experiments, against the six claims in the round-3 brief. One file each, with the
numbers, the box's state beside every number, and the failures that stayed. The scripts
are in `docs/lab/lab3-scripts/`.

| file | what it measured | verdict |
|---|---|---|
| `exp-engines.md` | the fact-check: does NVLA / PVA / NVDLA / AV1 exist on this Thor? | **kills four claims** |
| `exp-batched-shared-model.md` | one shared model, N agents batched; the FP8 multiplier; the bandwidth | **half right, and the multiplier is 3×** |
| `exp-adapters.md` | N LoRA skills on one shared base; switching vs mixing; memory per adapter | **half right — switching is the wrong mechanism** |
| `exp-joules-per-fixed-point.md` | a toy equilibrium loop, warm vs cold; joules per fixed point | **confirmed** |
| `exp-cuda-graphs-nvenc.md` | CUDA Graphs against launch overhead | **confirmed, and worth more as reproducibility** |
| `exp-nvenc-roundtrip.md` | a float field through NVENC/NVDEC, as a warm-start store | **kills the store, confirms the engine** |

### The five things that changed

1. **The GPU clock was silently corrupting every measurement, and now it is a rule.**
   The Thor idles at 315 MHz and ramps to 1575 MHz over ~1.4 s of sustained load. A cold
   measurement is **2.6× slow**, and it is the *first* measurement of every session.
   Every script in `lab3-scripts/` now warms the GPU before timing and records the clock
   beside the number. *(`exp-batched-shared-model.md` §5.1)*
2. **The FP8 multiplier is 3×, not 1.6–1.7× — and the reason round 1 measured
   0.95× is now understood.** Round 1 measured FP8 *weights* with a cast at every layer.
   Keep the activations in FP8 and the same chain is **3.00×** (301.7 TFLOPS against
   BF16's 100.9); with calibrated per-tensor activation scales, **2.60×** and *more
   accurate*. But end-to-end the gain is **1.29×**, because the FP8 path is
   **launch-bound** — the host spends 9.35 ms issuing the step and the step takes 9.35 ms.
   **A CUDA Graph takes it to 1.66–2.42×.** And FP8 costs **15–22 % output error**,
   so the critic and the provenance path stay in BF16.
   *(`exp-batched-shared-model.md`, `exp-cuda-graphs-nvenc.md`)*
3. **Batching is free only while the agents have no context.** The step time is flat from
   N = 1 to N = 8 in the weights-only regime, and then grows; with a realistic 1024-token
   context it grows **13.6 → 53.7 ms** from N = 1 to N = 128, because each agent's KV cache
   is its own (4.3 GB of cache against 1.9 GB of weights at N = 128). The scheduler's batch
   limit has to be a function of the *context length*, not of the model.
   *(`exp-batched-shared-model.md`)*
4. **Skills are cheap; switching them is not.** A 15.7 M-parameter adapter is 60 MiB
   (PEFT keeps it FP32) and costs ~14 ms on a 1.64 B-parameter forward. But PEFT's
   `set_adapter` costs **75–120 ms per switch** — O(layers × adapters) in Python,
   larger than the request, and flat in the number of resident adapters — and PEFT's
   mixed-adapter batch is **10× worse at N = 32** because it degenerates into 5 120
   one-row GEMMs. **The builder-scheduling layer must not be built on "switch the active
   adapter".** *(`exp-adapters.md`)*
5. **The equilibrium loop's governing metric works, and a lossy store destroys it.** Warm
   starts converge in **2–3 iterations** against 6 for a cold start; joules per fixed point
   = **1.39 J × iterations**; a **lossless 8-bit warm-start store is free**. But an NVENC
   round trip leaves **1.7–3.1 % RMSE**, which is larger than the perturbation the warm
   start was correcting, and the loop then needs **6 iterations — exactly as many as a
   cold start**. The video engine itself is free (it does not touch the tensor cores) and
   199× compressive, so it is excellent for the morning report and useless for the world
   state. *(`exp-joules-per-fixed-point.md`, `exp-nvenc-roundtrip.md`)*

### What this round did not settle

- **The absolute numbers are ranges, not numbers.** The box ran at load 15–113 with two or
  three other seats resident on the GPU. The *ratios* reproduced; the absolutes moved by up
  to 3.4×. Every figure in these files is quoted with its range and its load, and
  round 2's lesson holds: **publish ranges and re-run before publishing a conclusion.**
  A clean re-run at load < 8 is the first thing to do.
- **The real generator.** The 16-layer stack is synthetic (seeded weights), which is what
  makes the byte accounting exact. Whether ComfyUI's own fp8 path reaches 3× is
  untested — and rev-tech R9 flags ComfyUI's fp8 flag as unvalidated on sm_110.
- **The real critic.** The adapter experiment used the real DINOv2-giant weights; the
  equilibrium loop used a synthetic critic. The *engine* results (FP8 multiplier, graph
  speedup, adapter switching cost) do not depend on which model is in the loop; the
  joules-per-fixed-point figures do.
- **Part C items 2, 6 and 8 from round 2** are still open (item 6 needs a human and a
  cable).

### The corrections this round makes to rounds 1 and 2

1. **"FP8 weights alone buy nothing" (round 1) was right but is easy to misread.** It
   measured the cast-per-layer path: 0.95× there, 1.29× on a clean rebuild, and
   **3.00×** with the activations kept in FP8. Both numbers are true; the multiplier
   depends on which path you mean. **Round 3's version of the claim: the prize is real and
   large, and it is *not* the thing that makes the serving loop fast — the launch
   overhead is.**
2. **The 273 GB/s in the bandwidth formula is not achievable here.** Measured: **166 GB/s**
   eager, **~220 GB/s** graphed. Any `T_pass` computed from 273 GB/s is a `T_pass` that
   cannot be achieved.
3. **Round 1's and round 2's GPU figures need the clock rule.** Trap 14 above applies to
   every GPU number in this directory. Nothing measured in rounds 1–2 was re-run under it,
   so those numbers should be read as "at whatever clock the GPU happened to be at".
4. **Round 2's PNG finding now has its contrast.** PNG is lossless at 5.18 MiB for 30
   frames; the video path is 38.6 KiB at 3 % error. **The critic wants the PNG (or the
   render buffer); the world state wants the 8-bit store; the film wants the codec.**
