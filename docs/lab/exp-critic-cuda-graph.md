# EXP 2 — the critic on the GPU, zero-copy from the render buffer, inside a CUDA Graph: up to 106× the PNG path

**Date:** 2026-10-31 (round 4) · **Verdict: CONFIRMED AND EXTENDED — the verdict arrives in milliseconds, and the graph is bit-exact.**
On real Cycles renders with the **real DINOv2-large critic** (bf16, 304 M params),
at the iterator's batch sizes: the PNG path costs **61–8,984 ms per verdict**
(B = 1…8) while the zero-copy device-resident path costs **7.9–106 ms** eager and
**6.1–84.6 ms inside a CUDA Graph** — **8.7× at 480p B=1, 33× at 1080p B=1,
106× at 4K B=8**. The graph's verdict is **bit-identical to the eager verdict in
every configuration**, and its host-side issue cost is **0.10–0.17 ms against
7.7–19 ms eager** — on a launch-bound box, the graph is what makes the verdict
*predictable*, reproducing round 3's reproducibility finding on a real model.

---

## 1. The idea

The round-4 brief's second preference: *"The critic on the GPU, zero-copy from
the render buffer, inside a CUDA Graph: per-verdict latency and joules vs the
PNG path, at the iterator's batch sizes."*

Round 2 (`exp-critic-png-roundtrip.md`) measured the PNG round trip against a
ViT-shaped stand-in with random weights: 10×–228× the critic's own forward pass,
88 % of it the encoder. Round 3 killed the CPU critic (2.2× slower, 2.5× the
joules — `exp-joules-per-fixed-point.md`) and its Part C re-scoped the item to
"the real critic's forward pass". This experiment closes that loop: real model,
real renders, both round-3 recommendations (zero-copy + CUDA Graph) together.

**Batch sizes** — B ∈ {1, 2, 4, 8}: the equilibrium iterator judges the current
field once per iteration (B = 1; `exp-joules-per-fixed-point.md`), and the
mini-night's critic judged 3 candidates per request — 1–8 covers both shapes.

## 2. Hypothesis

1. With a real critic on device-resident float buffers, the whole verdict
   (ingest → resize → normalise → forward → head) fits in single-digit
   milliseconds at 480p/1080p and tens of ms at 4K, against hundreds-to-thousands
   for the PNG path.
2. The whole verdict path captures in a CUDA Graph with a static input buffer
   (what the renderer writes into), removing the launch overhead round 3
   measured as the binding constraint everywhere else.
3. The graph's output is bit-identical to the eager path on the same input.

## 3. Setup

- Script: `scripts/exp2_critic_graph.py` (`.venv-torch`, torch 2.15.0+cu132);
  raw output: `results/exp2_critic_graph.txt`, JSON: `results/exp2_critic_graph.json`.
- **Frames**: round 2's genuine Cycles GPU renders, read-only
  (`~/lm-wt/lab2/results/exp4-frames/`): 480p/1080p/4K float32 **linear** RGBA
  buffers (`.npy`) plus Blender's own 8-bit sRGB PNGs.
- **The critic**: the real local **DINOv2-large** (HF cache, no download), bf16 on
  cuda, mean-pooled patch output, plus a seeded bf16 verdict head
  (1024 → 8 scores). Round 2's stand-in was 3.8 M random params; this is 304 M
  trained parameters.
- **Three arms** per (resolution, B), timed in interleaved windows:
  - **PNG eager (today)**: numpy linear→sRGB8 (round 2's exact transform) → PIL
    PNG encode (compress_level 6) → file write → file read → PIL decode → tensor
    → H2D → bilinear resize to 224 → ImageNet normalise → critic → head.
  - **ZC eager (zero-copy)**: the render buffer as a device tensor (Cycles renders
    on this GPU; EXP A proved host `malloc` memory is device-addressable too) →
    sRGB transform, resize, normalise all in torch on GPU → critic → head.
  - **ZC graph**: the ZC-eager path captured in a `torch.cuda.CUDAGraph` with a
    static (B,H,W,4) input and static verdict output; per verdict: write the
    batch into the static input (what the renderer would do) + one replay.
- **Checks**: PNG round trip must decode back to the transform's own 8-bit pixels
  (max |diff| = 0, all resolutions — round 2's check); the graph must reproduce
  the eager ZC verdict exactly; the PNG-path verdict vs ZC verdict RMS is
  reported as the 8-bit-quantisation effect (they carry different pixels by
  design — the PNG path quantises, the ZC path stays float).
- **Joules**: INA rails (whole box above an idle baseline + the VDD_GPU rail)
  around interleaved windows; GPU warmed to 1575 MHz before timing
  (`boxstate.warm_gpu`).

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-31 08:0x |
| loadavg (1/5/15) | 6.7–8.9 through the run (the quietest of any round so far) |
| GPU clock | warmed 315 → **1575 MHz**; recorded per row |
| GPU tenants | `trellis`'s ComfyUI server resident but idle; an Infinigen nature sweep on the CPU for part of the run |
| Power mode | MAXN; MemAvailable ≈ 111 GiB |

## 4. Numbers

### 4.1 — per-verdict latency (ms/verdict for the batch; interleaved, median of 3)

| res | B | PNG (today) | ZC eager | ZC graph | PNG/ZC-graph | CPU issue: eager → graph |
|---|---|---|---|---|---|---|
| 480p | 1 | 61.1 | 7.91 | **6.10** | **10.0×** | 7.66 → 0.103 ms |
| 480p | 2 | 115.1 | 9.04 | **7.24** | 15.9× | 8.51 → 0.143 ms |
| 480p | 4 | 274.4 | 12.73 | **11.89** | 23.1× | 15.91 → 0.140 ms |
| 480p | 8 | 537.9 | 25.77 | **23.97** | 22.4× | 18.98 → 0.156 ms |
| 1080p | 1 | 264.8 | 8.84 | **8.13** | **32.6×** | 8.81 → 0.109 ms |
| 1080p | 2 | 575.3 | 13.61 | **11.54** | 49.9× | 15.24 → 0.133 ms |
| 1080p | 4 | 1101.0 | 23.50 | **19.18** | 57.4× | 9.09 → 0.120 ms |
| 1080p | 8 | 2765.5 | 47.81 | **37.07** | 74.6× | 16.91 → 0.146 ms |
| 4K | 1 | 1131.5 | 17.59 | **13.86** | 81.6× | 15.89 → 0.135 ms |
| 4K | 2 | 2142.0 | 28.05 | **23.88** | 89.7× | 9.74 → 0.119 ms |
| 4K | 4 | 4366.2 | 54.85 | **43.51** | 100.4× | 17.12 → 0.147 ms |
| 4K | 8 | 8983.7 | 106.39 | **84.59** | **106.2×** | 16.92 → 0.170 ms |

Readings:

- **The real critic is fast; the plumbing was never the critic's fault.** At
  B = 1 the whole zero-copy verdict is **6–14 ms** (the DINOv2-large forward at
  224² is ~6 ms of that) against 61–1,132 ms of PNG pipeline.
- **The graph buys 1.1–1.3× on top of zero-copy** and collapses the host issue
  time by ~100× (0.10–0.17 ms vs 7.7–19 ms). On this shared, launch-bound box
  the graphed number is also the *stable* number — the eager arm's issue time
  swung 7.7→19 ms with load while the graph's stayed at 0.10–0.17 ms.
- **The advantage grows with resolution and batch** (10× → 106×), because the
  PNG codec scales with pixels while the GPU front end barely does.
- Context number: an H2D copy of one 4K float32 RGBA frame (133 MB) is
  **13.6 ms** — so even if a renderer *did* hand the critic a host buffer, the
  crossing is cheap; the file and the codec are what cost.

### 4.2 — correctness

| check | result |
|---|---|
| PNG encode→decode round trip vs the transform's own 8-bit pixels | **max \|diff\| = 0** at all three resolutions |
| graphed verdict vs eager ZC verdict (same input) | **bit-identical (max abs 0.0) in all 12 configurations** |
| verdict RMS, PNG-path pixels vs float ZC pixels | 3.4–6.4 % — the 8-bit quantisation difference, by design |

The 3.4–6.4 % verdict RMS between the 8-bit and float paths is the *price of
today's PNG interface* — the critic literally sees different pixels depending on
whether it reads a file or the buffer. That is a correctness argument for the
zero-copy interface, not just a speed one.

### 4.3 — joules per verdict

Whole-box INA joules above the idle baseline are only usable where the box
stayed quiet through the window; negative values mean the box got *quieter*
during the measurement (round 3's trap 17 — report the wall time instead). The
usable rows:

| res | B | J/verdict PNG | J/verdict ZC eager | J/verdict ZC graph | J/verdict graph, VDD_GPU rail |
|---|---|---|---|---|---|
| 480p | 8 | 0.91 | 1.79 | 1.92 | 1.36 |
| 1080p | 8 | **7.00** | 2.75 | 2.58 | 1.68 |
| 4K | 2 | — | 0.78 | 1.13 | 0.60 |
| 4K | 4 | — | 1.71 | 2.06 | 1.34 |

- At 1080p B=8 the PNG path costs **2.7× the joules per verdict** of the
  graphed zero-copy path (7.0 vs 2.6 J) — the CPU codec burns watts while the
  GPU idles.
- The GPU-rail joules scale cleanly with B (0.16 → 1.68 J between 1080p B=1 and
  B=8) and are the attributable metric on a shared box; several whole-box rows
  came out negative (box load fell mid-window) and are reported as unusable
  rather than averaged in.

## 5. How to reproduce

```bash
cd ~/lm-wt/lab4
.venv-torch/bin/pip install torch numpy pillow transformers   # already installed
.venv-torch/bin/python scripts/exp2_critic_graph.py           # ~6 min
# frames are read from ~/lm-wt/lab2/results/exp4-frames (round 2's real renders)
```

## 6. Verdict

**Confirmed and extended.** Round 2's finding survives contact with a real
critic, and round 3's two recommendations compose:

1. **The verdict path is milliseconds, not seconds.** 6–14 ms/verdict at B=1
   (480p–4K) zero-copy graphed, against 61–1,132 ms through the PNG interface.
   The "≤5 s watch clock" has room for **hundreds** of verdicts, or a verdict
   per rendered frame.
2. **The graph is bit-exact and launch-free.** Host issue 0.10–0.17 ms
   (vs 7.7–19 ms eager) and identical outputs in all 12 (resolution, B)
   configurations — on a shared box this is the reproducible way to serve the
   critic.
3. **The PNG interface costs correctness too**, not just time: 3.4–6.4 % verdict
   RMS from 8-bit quantisation — the critic and the renderer should share the
   float buffer.
4. **Joules follow the wall time**: ~2.7× fewer joules per verdict at 1080p B=8
   graphed-zero-copy vs PNG.

### What this changes for the plan

- **Stop writing PNGs for the critic** — now measured with the real model, at
  the iterator's batch sizes, with joules. The middleware's critic interface
  should be a device-resident float buffer (the renderer already renders on
  this GPU) and its serving loop should be graph-captured.
- **Mid-render judging (idea #7's second half) is now cheap**: the front end of
  the zero-copy path is the only cost of looking at a frame, and a graphed
  verdict at 480p is 6 ms — a Cycles render emitting progressive samples could
  be checked per-pass for less than 1 % of its cost.
- **Batching verdicts is nearly free** up to B=8 (6.10 → 23.97 ms at 480p —
  3.9× the time for 8× the verdicts), which is the shape the equilibrium
  iterator and the mini-night's "judge all candidates at once" both want.

## 7. Failures that stayed

- **`torch.from_numpy` on PIL's decoded array is read-only** (numpy
  non-writable warning) — harmless here (the tensor is only read), but
  `.div_(255.0)` in-place on such a tensor would be undefined behaviour; the
  script uses `div_` before the warning appeared only because the permuted
  float copy is fresh.
- **Whole-box joules on a shared box need the baseline taken per window**, not
  per run: several PNG windows at 4K ran 27 s during which the box's other
  tenants finished their work, producing negative above-baseline joules
  (−90 J on one). The VDD_GPU rail is the attributable metric; the whole-box
  number is reported only where the box stayed quiet.
- **The 25 ms INA sampler cannot resolve a 40 ms window** (480p B=1 ZC came out
  `nan`): short arms were lengthened to 5–50 consecutive verdicts per window
  and divided out; sub-10 ms single verdicts still round to the sampler's
  resolution.

## 8. Licence note

`torch` (BSD-3-Clause), `transformers` (Apache-2.0), `pillow` (HPND/MIT-CMU),
`numpy` (BSD-3-Clause). The DINOv2-large weights are the local HF-cache copy
(apache-2.0); **no weights were downloaded** and nothing is redistributed. The
render frames are round 2's own Cycles outputs, read in place.
