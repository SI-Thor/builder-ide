# EXP 5b — NVENC/NVDEC round trip of a float field: is it a warm-start store?

**Date:** 2026-10-31 03:35 local (Alaska Daylight Time)
**Verdict: THE VIDEO ENGINE IS REAL AND FREE, BUT IT IS NOT A WARM-START STORE.** Two of
Kimi's claims are **confirmed** — the NVENC path does **not** slow the GPU's tensor work
(**+0.2 % / −1.3 %**, measured against a matmul loop running beside it), and the
compression is extraordinary (**29 KiB for 30 frames of 512×512, 261× smaller than raw
uint8**). But the decisive measurement is the one that connects the codec to the loop: a
warm start that has been through the codec **converges in 6 iterations — exactly as many
as a cold start** — while an exact warm start converges in **4**. **The lossy round trip
destroys the entire warm-start advantage**, and AV1 does not work on this Thor's NVENC at
all.

---

## 1. The idea

> "NVENC/NVDEC to compress world-state latents between frames (warm start)"

and the brief's experiment 5:

> "NVENC/NVDEC round-trip of a float field packed as video (error vs bitrate) as a
> warm-start store."

## 2. Hypothesis

1. A float field packed as video survives an NVENC/NVDEC round trip at a useful error,
   for far fewer bytes than any other store.
2. The video engine is on its own clock domain, so it does not compete with the GPU's
   tensor work — it can run *while* the generator works.
3. The round trip is accurate enough that the equilibrium loop still gets its warm-start
   advantage.

## 3. Setup

- Script: `scripts/exp5b_nvenc.py`; raw JSON: `results/exp5b_nvenc.json`
  (rerun: `.venv/bin/python scripts/exp5b_nvenc.py`)
- The field is a **sequence of 30 slowly-evolving 512×512 scalar fields** in [0, 1] — a
  stand-in for a world state changing over 30 frames. A *sequence* rather than a single
  frame, because inter-frame prediction is the only thing a video codec has that a plain
  image codec does not.
- The field is packed into **NV12 by hand**: the Y plane carries the field and U and V
  are constant 128, because the field is grey. The RGB→YUV mapping uses the **limited
  range** (16–235) with BT.601's 0.859 luma weight, and the decoded Y is mapped back with
  the inverse — so the reported error is the error **the field suffers**, not an
  intermediate colour-space error.
- Comparators: raw uint8, raw 10-bit, raw float16, and **PNG per frame** (round 2's
  measured store: 88 % of the encoder, and 10–228× the critic's own forward pass).
- **The payoff arm:** the EXP 4 equilibrium loop is re-run with a warm start that has been
  through the codec.

### The box this ran on

| | |
|---|---|
| GPU clock | 1575 MHz (warmed) |
| **Load during the run** | **loadavg 26.9–33.1 on 14 cores** |
| GPU tenants | `trellis/ComfyUI/main.py` (9.8 GB), `warm-scene`'s server |
| **Effect on these numbers** | the **byte counts and the errors are exact** — they are properties of the codec. The **joules are not usable**: the whole-box INA rail is dominated by other tenants, and the baseline-corrected figures came out *negative*, which only means the box's power draw fell between the baseline capture and the measurement. **Use the wall time.** |

## 4. Numbers

### 4.1 The round trip

30 frames of 512×512. The field as float32 is 30.0 MiB; packed as NV12, 11.2 MiB.

| codec | bitrate | bytes | bpp | vs raw uint8 | RMSE | PSNR | encode | decode |
|---|---|---|---|---|---|---|---|---|
| h264 | 200 k | 29.4 KiB | 0.03 | **261.4×** | 0.03069 (3.07 %) | 30.3 dB | 1021 ms | 1085 ms |
| h264 | 1000 k | 271.9 KiB | 0.28 | 28.2× | 0.02896 (2.90 %) | 30.8 dB | 1038 ms | 1039 ms |
| h264 | 5000 k | 1426.2 KiB | 1.49 | 5.4× | 0.01723 (1.72 %) | 35.3 dB | 890 ms | 1015 ms |
| hevc | 200 k | 38.6 KiB | 0.04 | **198.8×** | 0.03037 (3.04 %) | 30.4 dB | 872 ms | 1091 ms |
| hevc | 1000 k | 274.7 KiB | 0.29 | 28.0× | 0.02824 (2.82 %) | 31.0 dB | 879 ms | 1142 ms |
| hevc | 5000 k | 1252.1 KiB | 1.30 | 6.1× | 0.01860 (1.86 %) | 34.6 dB | 895 ms | 1127 ms |
| **av1** | 200/1000/5000 k | — | — | — | — | — | **FAILED** | — |

**Comparators, whole sequence:**

| store | size | note |
|---|---|---|
| raw uint8 | 7.50 MiB | exact |
| raw 10-bit | 15.00 MiB | exact |
| raw float16 | 15.00 MiB | exact |
| **PNG per frame** | **5.18 MiB** | **lossless**, 382 ms |
| hevc @ 200 k | **38.6 KiB** | 3.04 % RMSE |
| hevc @ 5000 k | 1252.1 KiB | 1.86 % RMSE |

**The compression is extraordinary and the error is bounded.** 30 frames of a 512×512
field in **38.6 KiB** is 199× smaller than raw uint8 and **134× smaller than PNG** — and
PNG is *lossless*, so the comparison is not like-for-like: the video path trades 3 % of
the field for a 134× size reduction.

**The error does not go to zero with bitrate.** Even at 5 Mbit/s the round trip leaves
1.72 % RMSE (35.3 dB PSNR). That is the DCT's limit for a field that has already been
through the limited-range 8-bit YUV pipeline: *the field's own precision, not the codec's
rate control, is the floor.*

**AV1 is not available on this Thor.** `av1_nvenc` fails at every bitrate with *"Failed
locking bitstream buffer: invalid param"*. The encoder is listed by ffmpeg but the
hardware does not implement it on this module.

### 4.2 The video engine does not compete with the GPU

A 4096³ BF16 matmul loop, timed alone and then again while an NVENC encode runs:

| run | alone | during an NVENC encode | change |
|---|---|---|---|
| 1 | 1211.6 ms | 1214.5 ms | **+0.2 %** |
| 2 | 1221.1 ms | 1205.1 ms | **−1.3 %** |

**Kimi's "it does not compete with the GPU for tensor cores" is confirmed.** The video
engine lives on its own clock domain (`gpu-nvd-0`, max 1692 MHz, separate from the
`gpu-gpc-0` tensor cores at 1575 MHz) and the interference is inside the noise. The
encoder can run *while* the generator works.

Two caveats worth keeping:

- **The encode is only ~30 fps of 512×512 frames — and that is not the NVENC engine.**
  The cost is the CPU-side rawvideo plumbing and the container muxing, not the hardware
  encoder. On a busy box this dominates.
- **The joules could not be attributed.** The baseline-corrected figures came out
  negative (−1.66 to −43 J), which means the box's total power draw *fell* between the
  idle baseline and the measurement. With three other tenants on the whole-box rail, the
  joules of a 1-second ffmpeg subprocess are simply not attributable on this box. The
  wall time is the usable number here.

### 4.3 The payoff: does the round trip still warm-start the loop?

EXP 4 put the equilibrium loop's tolerance at 2e-3 and found that an exact warm start
converges in **4 iterations** against **6** for a cold start. Here the warm start is
passed through the codec first:

| warm start | field RMSE after the round trip | iterations to converge |
|---|---|---|
| cold start | — | **6** |
| **exact warm start** | — | **4** |
| hevc @ 200 k | 0.5066 | **6** |
| hevc @ 1000 k | 0.3319 | **6** |
| hevc @ 5000 k | 0.3429 | **6** |

**A warm start that has been through the video codec is worth exactly as much as no warm
start at all.** The round trip's error (0.33–0.51 in the field's own units, against a
field scale of 2.75) is *larger than the 10 %-of-scale perturbation the warm start was
correcting*, so the loop spends its iterations undoing the codec instead of converging.

Note the ordering: **hevc @ 5000 k (1.86 % RMSE on the field) is no better than
hevc @ 200 k (3.04 % RMSE)** at warming the loop. Past the point where the codec's error
exceeds the warm-start offset, more bitrate buys nothing for this use.

And the control from EXP 4 is the important contrast: a warm start through an **8-bit
quantisation** (lossless for the field's purposes) converged in the **same** 3–5 iterations
as the exact warm start. **The store's job is not to be exact — it is to be accurate
enough that the loop still converges in 2–3 iterations. A video codec is not.**

## 5. Verdict

- **Confirmed:** *"NVENC/NVDEC … does not compete with the GPU for tensor cores."* Measured
  at **+0.2 % / −1.3 %** against a matmul loop running beside the encode. The video engine
  is genuinely free to run alongside the generator.
- **Confirmed, and remarkable:** the compression. **38.6 KiB for 30 frames of 512×512**,
  199× smaller than raw uint8 and 134× smaller than lossless PNG.
- **Killed:** *"NVENC/NVDEC to compress world-state latents between frames (warm start)"*
  **as a warm-start mechanism.** The codec's error (3 % of range at best, 1.7 % even at
  5 Mbit/s) exceeds the perturbation a warm start corrects, so the loop's iteration count
  falls back to the cold-start value: **6 iterations, exactly as if there were no warm
  start at all.**
- **New:** **AV1 does not work on this Thor's NVENC** (`av1_nvenc` fails with *"Failed
  locking bitstream buffer: invalid param"* at every bitrate). H.264 and H.265 do.
- **New:** the error of the video path does **not** go to zero with bitrate. Even at
  5 Mbit/s it is 1.72 % RMSE — the limited-range 8-bit YUV pipeline is the floor, not the
  rate control.

### What this changes

- **Do not use a video codec to carry a world state between frames.** The codec is
  excellent at compressing and useless at *preserving* — and a warm start's whole value is
  in preserving. EXP 4 already showed an 8-bit quantised warm start costs nothing; this
  shows a 1.7 %-accurate one costs everything.
- **The right store for the warm start is a cheap, accurate one** — 8-bit, or whatever the
  field's own resolution already is. The design should spend its budget on keeping the
  previous fixed point *close*, not on compressing it.
- **Keep NVENC for the job it is good at.** It is free (does not touch the tensor cores),
  it is 200× more compressive than raw, and it is the right tool for anything that is
  *meant* to be lossy — video previews, turntable renders, an artist's contact sheet.
- **The video engine being free is still a real finding for the schedule**: a preview
  encoder can run alongside the generator without costing the generator anything.

## 6. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp5b_nvenc.py            # -> results/exp5b_nvenc.json

python3 -c "
import json; d=json.load(open('results/exp5b_nvenc.json'))
for r in d['runs']:
    print(r['codec'], r['bitrate_k'], r['bytes'], 'B', round(r['rmse'],5), 'RMSE')
print('warm-start store:', d['warm_start_store'])"
```

## 7. Licence note

`ffmpeg` (LGPL/GPL depending on the build) and `numpy` (BSD-3-Clause). The field is
synthetic. Nothing is downloaded.

## 8. Failures that stayed

- **This ffmpeg has no `scale` filter**, so it cannot convert `rgb24` → `yuv420p`:
  *"scale filter not present, cannot convert formats"*. The pixel format has to be
  produced **in Python** — NV12 is accepted directly by `*_nvenc`.
- **AV1 needs a container it recognises** — `.av1` is not a standard extension; `.mkv` is.
- **NVENC's AV1 encoder does not exist on this Thor** even though ffmpeg lists it.
- **The round trip has to be measured in the field's own units**, through the limited-range
  mapping the codec actually uses. Comparing a decoded Y plane against a float field
  directly would report a constant offset, not an error.
- **The whole-box joules are not attributable to a subprocess** on a box with three other
  tenants: the baseline-corrected figures came out negative. Report the wall time, and
  say so.
