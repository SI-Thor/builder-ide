# IDEAS — Thor-native breakthroughs for builder-ide

**Date:** 2026-10-30 · **Author:** the lab seat (`~/lm-wt/lab1`)
**Sources read:** `~/src/builder-ide/CLAUDE.md`, `docs/vision.md`, `docs/research/split.md`,
`docs/research/rev-tech.md`. **Measured:** three experiments in this directory —
`exp-unified-memory.md`, `exp-warp-terrain.md`, `exp-fp8-tensorcores.md`.

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
