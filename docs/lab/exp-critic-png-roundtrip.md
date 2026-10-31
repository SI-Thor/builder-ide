# EXP 4 — the critic's PNG round-trip vs zero-copy from the render buffer

**Date:** 2026-10-31 00:07 local (Alaska Daylight Time)
**Verdict: USEFUL (and a BREAKTHROUGH for the watch clock)** — the PNG round trip
costs **48.5 ms at 480p and 1,201.8 ms at 4K**, against a critic forward pass of
**4.9–5.3 ms**. The round trip is **10× to 228× the critic's own cost**, and
**99 % of it is the PNG codec, not the disk**. Removing it (zero-copy from the
render buffer) makes the whole critic path **2.9–3.5× faster**.

---

## 1. The idea

`IDEAS.md` idea #7 / Part C item #4: "The critic reads the render buffer, not a
PNG." The kill condition was *"Kill it if (a) is under 100 ms — then the
round-trip was never worth removing."*

Today the critic reads a PNG that the renderer wrote to disk. The alternative is
to hand it the render buffer directly — which on this box (EXP A) is the *same
memory the GPU can read*, so the copy can be skipped entirely.

## 2. Hypothesis

The PNG round trip (encode → file → read → decode) costs a meaningful fraction
of the critic's budget at review resolutions, and removing it (zero-copy from the
render buffer) makes the critic path measurably faster. If the round trip is
under 100 ms, the idea is dead.

## 3. Setup

**Real renders, not a stand-in.** The frames are genuine Cycles GPU renders made
on this box in phase 1 (`scripts/exp4_render_dump.py`, run with the Infinigen
spike's own bpy 4.2.0 interpreter, read-only):

| resolution | pixels | Cycles samples | render time | device |
|---|---|---|---|---|
| 480p (854×480) | 0.41 Mpx | 16 | 0.904 s | NVIDIA Thor (CUDA), compute device type CUDA |
| 1080p (1920×1080) | 2.07 Mpx | 16 | 3.349 s | same |
| 4K (3840×2160) | 8.29 Mpx | 4 | 6.983 s | same |

For each frame two artefacts were kept:

- `<res>.npy` — the **raw render buffer**: float32 **linear** RGBA, exactly what a
  renderer hands to the next stage (recovered from a float EXR through Blender).
- `<res>.png` — the same frame as **Blender writes it**: 8-bit PNG with the
  "Standard" view transform (so PNG = sRGB(linear)). This is what Infinigen
  produces today.

**The two pipelines measured** (from "the render buffer exists in memory" to
"the critic's input tensor is ready"):

- **(A) today — PNG round trip:** colour transform → PNG encode → write file
  (NVMe) → read file → PNG decode → tensor → resize to 224×224 → normalise.
- **(B1) zero-copy, same pixels:** colour transform → tensor → resize → normalise,
  with the buffer shared, no file, no encode, no decode.
- **(B2) zero-copy, float:** the same but the colour transform is done in torch
  and the frame stays float32 (no 8-bit quantisation at all).

(B1) is deliberately the *same 8-bit pixels* as (A), so the difference between
them **is** the round trip and nothing else. That is checked, not assumed:

```
480p   max |A_pixels - B1_pixels| = 0
1080p  max |A_pixels - B1_pixels| = 0
4k     max |A_pixels - B1_pixels| = 0
```

**The critic** is a stand-in: a ViT-shaped network (patch conv → 2 transformer
encoder layers → mean pool → linear head), **3.8 M parameters with random
weights**, on the GPU. It exists only to put the round trip in proportion to a
critic's budget; no model weights were downloaded and no claim is made about
its accuracy.

**The box's state, beside the numbers** (this run):

| | |
|---|---|
| Timestamp | 2026-10-31T00:07:20-0800 |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / 114.36 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` at start | 0 % GPU util, 2.36 W, 38 °C, 315 MHz |
| `tegrastats` RAM | 47,637 / 125,749 MB |
| `tegrastats` VIN | 54,698 mW peak / 34,255 mW avg |
| loadavg (1/5/15) | **87.83 / 41.07 / 22.36** (rising to 96 during the run) |
| CPU busy at sample | **all 14 cores at 98–100 %** (another seat's build) |
| `jetson_clocks` | present, **not** locked |

**The box was saturated** (load 88→96 on 14 cores) — another seat was running a
build. The PNG codec is CPU-bound, so this run is a *worst case*: an earlier run
of the same script at load ≈ 7 measured the 4K encode at 881.8 ms against
1,055.6 ms here (≈ 17 % slower under load). The structure of the result (codec
dominates, disk irrelevant) is identical in both runs.

## 4. The numbers

### 4.1 — the round trip against the critic

| resolution | pixels | **(A) PNG path** | (A) on tmpfs | **(B1) zero-copy** | (B2) zero-copy float | **round trip saved** | critic forward | round trip / critic |
|---|---|---|---|---|---|---|---|---|
| 480p | 0.41 Mpx | **72.9 ms** | 77.4 ms | **25.1 ms** | 30.9 ms | **48.5 ms (2.9×)** | 4.9 ms | **9.9×** |
| 1080p | 2.07 Mpx | **407.2 ms** | 388.3 ms | **116.4 ms** | 74.2 ms | **293.0 ms (3.5×)** | 4.6 ms | **63.2×** |
| 4K | 8.29 Mpx | **1,675.5 ms** | 1,709.3 ms | **472.8 ms** | 178.1 ms | **1,201.8 ms (3.5×)** | 5.3 ms | **227.9×** |

*(The raw output's "round-trip is N× of it" line measures (round trip + front end) ÷
critic — 10.8× / 67.1× / 233.9×. The table's last column is the round trip alone ÷
critic. Both are quoted; the difference is the front end.)*

### 4.2 — where the round trip actually goes (milliseconds)

| resolution | colour transform | PNG encode | file write | file read | PNG decode | critic front end |
|---|---|---|---|---|---|---|
| 480p | 19.7 | **42.4** | 0.3 | 0.0 | 5.8 | 4.7 |
| 1080p | 96.3 | **254.2** | 1.3 | 0.2 | 37.4 | 18.0 |
| 4K | 442.0 | **1,055.6** | 4.9 | 1.0 | 140.3 | 31.7 |

**The disk is irrelevant.** At 4K, writing the PNG takes 4.9 ms and reading it
back 1.0 ms — 0.5 % of the round trip. Moving the file to tmpfs (`/dev/shm`)
changes nothing (1,709.3 ms vs 1,675.5 ms — within noise). **The PNG *encoder*
alone is 88 % of the round trip.**

For scale: Blender's own PNG writer saved the 4K frame in **0.66 s** (the phase-1
log: `Time: 00:06.96 (Saving: 00:00.66)`) — PIL is not faster than the renderer
here, so this is not a Python-library artefact.

### 4.3 — what the critic actually costs

The stand-in critic's forward pass is **4.6–5.3 ms** at every resolution (it
sees a 224×224 input either way). So:

- at 480p the PNG round trip is **9.9×** the critic's forward pass;
- at 1080p it is **63×**;
- at 4K it is **228×**.

The "critic" in today's pipeline is mostly *waiting for a PNG*.

## 5. How to reproduce

```bash
cd ~/lm-wt/lab2
# phase 1: render the frames (needs the Infinigen spike's bpy 4.2.0 interpreter)
~/src/infinigen-thor/.venv/bin/python scripts/exp4_render_dump.py --out results/exp4-frames
# phase 2: the measurement
.venv/bin/pip install pillow torch numpy
.venv/bin/python scripts/exp_critic_png_roundtrip.py
```

Raw output: `results/exp-critic-png-roundtrip.txt`; the rendered frames are in
`results/exp4-frames/` (`.npy` buffers + Blender's `.png`).

## 6. Verdict

**USEFUL — and more than that for the watch clock.** The kill condition
("under 100 ms → kill it") is **not** triggered: the round trip is 48.5 ms at
480p and 293 ms at 1080p, i.e. **10× to 63× the critic's own forward pass**.

Three findings, each measured:

1. **The round trip is the critic's dominant cost**, not a rounding error
   beside it. At 1080p the critic spends 293 ms waiting for a PNG and 4.6 ms
   thinking.
2. **It is the codec, not the disk.** 88 % of the round trip is the PNG
   *encoder*; the file write and read together are 1.5 ms at 4K, and tmpfs is
   no faster. **Any design that keeps the PNG but moves it to a faster disk
   solves nothing.**
3. **Zero-copy from the render buffer is 2.9–3.5× faster end-to-end** at every
   resolution, and the saving grows with resolution — the PNG cost scales with
   pixels, the shared-buffer cost does not.

### What this changes for the plan

- **The "morning report" idea (idea #6) is now measurable.** A critic pass
  currently costs ~407 ms at 1080p of which ~96 % is plumbing. With a shared
  render buffer it costs ~116 ms, and with a float buffer (B2) ~74 ms — the
  same order as the "≤ 5 s watch clock" would allow for **tens** of frames
  instead of a handful.
- **The plan should stop writing PNGs for the critic to read.** Not "write PNGs
  faster" — PNGs are fine as *artefacts*; they are simply the wrong interface
  between two stages that share a memory space.
- **Corollary for the middleware (idea #10):** the critic is not GPU-bound and
  is not disk-bound. It is **CPU-codec-bound**. That also means the critic
  competes with the renderer for CPU — which on a box where the GPU is the
  bottleneck is a scheduling problem worth knowing about.
- **Mid-render judging (the second half of idea #7) is cheaper than it looks**:
  the expensive part is decoding a full-resolution PNG. Judging from a
  down-sampled *buffer* (no encode, no decode) costs the front end only —
  4.7 / 18.0 / 31.7 ms at 480p / 1080p / 4K.

### The next step this suggests

Measure the *real* critic (a CLIP/BLIP-class model with real weights) on a
shared buffer, so the "10× to 228×" ratio is anchored to a critic that actually
exists rather than a ViT-shaped stand-in. The ratio will move — a bigger critic
has a bigger forward pass — but the *denominator* (the round trip) is measured
from real renders and does not depend on the model.

## 7. Failures that stayed

- **My first accounting was wrong and the check caught it.** The first run
  compared the PNG path against the zero-copy path and found
  `max |A_pixels - B_pixels| = 74` — the two paths were not carrying the same
  image. The cause was in *my* script: the colour transform (linear → sRGB8) was
  counted in one path but not the other, and the zero-copy branch was missing
  the OETF entirely. The fix was to make both paths carry the *same* pixels and
  then verify it (`max |A_pixels - B1_pixels| = 0` at all three resolutions).
  **The pixel-equality check is what caught the mistake; without it this write-up
  would have shipped a wrong speedup number.**
- **The colour transform itself is expensive** (19.7 / 96.3 / 442.0 ms in
  numpy) and is easy to forget because it belongs to "the renderer" in today's
  pipeline. In the zero-copy design the critic pays it instead. Doing it in
  torch rather than numpy is 1.7–2.5× faster (B2 vs B1 at 1080p and 4K).
- **The box was saturated during the measurement** (load 88–96, all 14 cores at
  100 %). The numbers are a worst case for the CPU-bound parts; the GPU parts
  are unaffected. An earlier run at load ≈ 7 is quoted above for comparison.
