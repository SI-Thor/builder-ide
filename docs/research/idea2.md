# idea2: enhancement and mod ideas, sorted (2026-10-31)

Casey shared `idea2.md`, a chat with another agent about enhancement and mod ideas. The DeepSeek library lane extracted it ($0.02). This note is the director's sorting of that extraction against what we have. The raw extraction is in the seed bank's working directory.

## The ideas that fit, and where

| Idea | What we already have | Seed for |
|---|---|---|
| **Feed the renderer a perfect G-buffer instead of estimating motion.** We own the camera, so no optical flow is needed. | Infinigen already writes ground-truth depth, optical-flow and object-index passes (the MiniMax harness read them: `depth_`, `optical-flow_`, `object_`) | A **neural upscaler or denoiser for the viewer and the filmstrip** fed by exact motion vectors and instance IDs, not estimates. Exact inputs are something only a procedural world can give. |
| **Instance-ID temporal rejection:** use segmentation IDs to kill ghosting at object edges | Object-index passes; world-stream's instance IDs | The same upscaler; the open question is what replaces the rejected history (see Q2) |
| **A draft track and a generative track:** physics and layout instantly at 480p flat-shaded, rich shading arriving asynchronously | The ProArt renders fast previews and the Thor does final renders (vision §8); world-stream's LOD swap | **The day view:** the builders' edits appear instantly as draft geometry, and the Thor's baked colour and lighting slide in after. Pairs with world-stream round 2 (colour) |
| **Procedural noise from world coordinates on the GPU:** store no textures | Infinigen's shader graphs; our Warp terrain kernels | Some materials could ship to the browser as **noise parameters, not textures**: tiny deltas, infinite detail. A seed for world-stream round 3 |
| **Per-layer precision:** FP8 for visual layers, INT4/INT8 for latent structural layers | lab-cascade E1 (precision changed no d1 decision); lab-fp4; fp8-real | A per-layer precision policy as a parameter, measured by the critic |
| **Calibrate quantisation on our own clean data** | fp8-real, lab-fp4 Part 2 | Our sim is an unlimited calibration set: a strength only we have |
| **Kernel fusion and barrier-free dispatch chaining** (claimed 72 ms → 2.7 ms) | CUDA Graphs on the Thor (lab rounds 3–4) | The same idea for the browser's WebGPU path, if the viewer runs a network |
| **Zero-copy unified-memory handoff** | Measured on the Thor (round 1, a breakthrough) | Already ours, within the Thor. Not across machines |
| **Front desk / back office:** a fast UI model up front, heavy work scheduled into the human's downtime | **The first mile** (ProArt) and **the night** | Already the architecture; a good name for it |
| **Repo as room:** a codebase as navigable space | The ship's computer and work orders | Metaphor as written (the mapping rule is never given), but a seed: **engineer work shown in-world**, a branch as a room you can walk into |

**Metaphor only:** "semantic spatial layouts over raw pixels", "intent-driven rendering", "a living, breathing digital canvas", "the human-machine rhythm".

## Experiments, under a day each (from the extraction, adapted)

1. **G-buffer vs optical flow, same network,** on a 200-frame Infinigen clip. Pass: the exact-motion path has ≥ 2× lower per-frame error and no ghosting on a fast pan.
2. **The draft/generative split at 60 fps in the viewer.** Pass: p99 frame time under 16.6 ms on the split path while full resolution misses it, and a blind A/B on 20 frames cannot tell them apart.
3. **Fusion measured:** naive per-block dispatch against chained dispatch, on the same weights. Pass: ≥ 5× at p50, with bit-identical output.

## Three checkable questions for the author

1. "72 ms → 2.7 ms" compares a WebGPU browser port with a native Vulkan port. **Same GPU, same block count?** Otherwise the gain may be the platform, not the chaining.
2. Instance-ID rejection "rejects old pixel history". **Does the shader zero the history (flicker at every occlusion) or reproject it (which needs a fallback)?**
3. In the draft/generative split, textures arrive "milliseconds later". **What bounds that lag, and what happens when the generative pass takes longer than a frame:** does the draft track keep advancing and desync?
