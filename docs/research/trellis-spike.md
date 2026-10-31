# TRELLIS.2 on the Thor — spike report

**Plan item 7 (Week 2, Nov 7–13), `~/src/builder-ide/docs/plan.md`**:
TRELLIS.2 spike on ComfyUI with stock PyPI torch 2.15 (E2 env) — RT spike 2:
CUDA true, capability (11,0), a GLB with PBR out, wall-clock at 512³ and
1024³ recorded, peak `MemAvailable` dip recorded, no compiled extensions.

---

## 0. Verdict

**The generator works on the Thor, with no compiled extensions, and the
licence is clean.** The stock PyPI `torch` 2.15.0 cp312 aarch64 wheel is
enough: ComfyUI's *native* TRELLIS.2 implementation runs on the Thor's
`sm_110` cores, and produces a GLB with a full PBR material set and an
embedded provenance record.

**The numbers:** 512³ in **98–115 s**, 1024³ in **166–179 s**, peak RAM
~62 GB of 125.7 GB, `MemAvailable` dipping to 78.8–85.6 GB, on a box whose
14 CPU cores are shared with other seats.

Four findings that change something:

1. **The FP8 lever was unreachable, for a reason that was one line of
   ComfyUI's code.** `UNETLoader.weight_dtype=fp8_e4m3fn` crashes while
   *constructing* the TRELLIS.2 model, because the model's rotary
   coordinate grid is built with `torch.arange(..., dtype=weight_dtype)` and
   torch has no `arange` kernel for FP8. Patched (numerically provably
   neutral for BF16/FP16), the lever becomes measurable. And measured, it
   **does not pay off**: FP8 weights are **50–88% slower** than BF16 on
   the diffusion stages — never faster, in any configuration — and their
   effect on the shipped asset is below the pipeline's own run-to-run
   noise floor. That is the lab's C4b reproduced on the real workload.

2. **The mesh tail is a CPU-lane consumer, and the box's 14 cores are
   contended.** The unwrap stage took **21.4 s on a quiet box and 154.6 s
   while another seat was compiling** — a 7× swing with the GPU untouched.
   And the mesh tail costs the **same at 512³ and 1024³** (~76–96 s),
   while sampling scales **4.0×**. So a 512³ prop is 80% mesh tail. Any
   scheduler that batches generative jobs on this box has to treat the CPU
   lane, not the GPU, as the scarce resource.

3. **The output is not byte-reproducible, and does not need to be.** Same
   seed, same recipe, two independent runs: different GLBs, different
   vertex counts (484,611 vs 485,564). But the *material structure* and the
   *provenance record* are identical, which is the part a prop catalogue
   actually needs.

4. **The text path is text→image→3D, not text→3D**, and it costs ~180 s
   for a 512³ prop — of which only 27.6 s is the image stage.

Full numbers, with the box's state beside every one of them, are in §4.

---

## 1. The box

| | |
|---|---|
| Machine | NVIDIA Thor, aarch64, JetPack 3 |
| Kernel | 6.8.12-1021-tegra |
| GPU | NVIDIA Thor, driver 595.78, **compute capability 11.0** (`sm_110`) |
| SMs | 20 |
| Memory | 128,766,528 kB total (122.8 GiB as CUDA sees it) — **unified** |
| CPU | 14 cores |
| CUDA | 13.2 (nvcc V13.2.86) |
| Python | 3.12.3 |
| Power mode | `NV Power Mode: MAXN 0` |

The box is **shared**. At least one other seat (`ig-spike`) was running a
CPU-bound Infinigen sweep and, for part of the session, compiling
OpenImageIO across ten cores. Every measurement in this report therefore
carries the load average beside it, and the load moves the wall-clock by
up to 7× (§4.3).

Recorded verbatim in `results/box_state.txt`.

---

## 2. What was built

Everything lives inside `~/lm-wt/trellis`. No system package was touched,
no other venv was modified, `~/src/infinigen-thor` was not touched, and no
service was started or stopped — the only process is a ComfyUI server on
`127.0.0.1:8188`, started and stopped by `scripts/serve.sh`.

| Piece | Choice | Why |
|---|---|---|
| torch | **stock PyPI 2.15.0+cu132, cp312 aarch64** | the whole point of the spike. The PyPI aarch64 wheel carries `libtorch_cuda.so` with **535 `sm_110` SASS images**. The 2.6.0 wheel does not — that is the CPU-only trap rev-tech R2 warns about. |
| ComfyUI | `7c4390a` (v0.43.0), native TRELLIS.2 | `comfy/ldm/trellis2/`. No custom nodes, no Pixal3D, no PixArt. |
| Attention | `--use-pytorch-cross-attention` (SDPA) | the only path with sm_110 kernels that exists without a source build (rev-tech R9) |
| Cache | `--cache-none` | with the cache on, the second run of a workflow reuses the first run's sampler output — the wall-clock measures only the mesh tail and the determinism test is vacuous |
| Weights | `Comfy-Org/TRELLIS.2` @ `430a9d0` | MIT, ungated (§6) |
| Workflow | `scripts/build_workflow.py` | the official template is 66 nodes and runs **Pixal3D** by default, dragging in a second model family this spike has not approved |

`setup.sh` is the single source of truth and is idempotent. It **fails the
build** rather than letting a bad install through:

```
torch.version.cuda.startswith("13")      -> True
torch.cuda.is_available()                -> True
torch.cuda.get_device_capability()       -> (11, 0)
"sm_110" in torch.cuda.get_arch_list()   -> True
sm_110-family ELF images in libtorch_cuda.so -> 535
```

A too-old torch does not error; it runs 10–50× slower and still "succeeds".
The assertion turns that into a build failure.

### 2.1 The workflow

The official ComfyUI template
(`3d_pixal3d_trellis2_image_to_model.json`) is a 66-node graph that runs
Pixal3D by default and reaches a TRELLIS.2 branch through a `switch`-like
routing node. `scripts/build_workflow.py` produces the same graph with
those branches removed, TRELLIS.2 made explicit, and a resolution switch
the template does not expose:

| mode | structure resolution | shape | path |
|---|---|---|---|
| `512` | 32 | 512³ | pure-512, no cascade upsample |
| `1024` | 64 | 1024³ | pure-1024, non-cascade |
| `cascade` | 32 → 1536 | 1024³ | the template's own cascade |

38 nodes. Seeds are the published template's, fixed: structure 56, shape 42,
texture 43.

### 2.2 The API-format traps (two real bugs)

Both cost a run each; both are recorded here because the next seat will hit
them.

**`COMFY_DYNAMICCOMBO_V3` widgets.** `RemeshMesh.sign_mode` and
`DecimateMesh.placement_mode` are dynamic-combo widgets. In API format the
combo is a plain string and each per-option sub-widget is a **flat input
whose name is the option id prefixed by the combo id**:

```json
"sign_mode": "solid",
"sign_mode.fill": 20.0,
"sign_mode.qef": false
```

Passing a nested dict instead (`{"sign_mode": "solid", "fill": 20.0, ...}`)
makes the node's `execute()` miss its `sign_mode` argument entirely:
`TypeError: RemeshMesh.execute() missing 1 required positional argument:
'sign_mode'`. ComfyUI rebuilds the nested dict from the dotted keys at
execution time (`comfy_api/latest/_io.py: build_nested_inputs`).

**`validate_workflow.py` cannot see dynamic sub-widgets**, so it reports
them as warnings. Those two warnings are expected and benign; everything
else in the schema check is enforced.

---

## 3. GPU proof

`results/gpu_proof.txt`, produced by `scripts/gpu_proof.py`:

```
torch version      : 2.15.0+cu132
torch.version.cuda : 13.2
cuda available     : True
device name        : NVIDIA Thor
compute capability : (11, 0)  -> sm_110
arch list          : ['sm_80', 'sm_90', 'sm_100', 'sm_110', 'sm_120']
device total mem   : 122.80 GiB
multiprocessors    : 20
```

and the shipped SASS:

```
sm_80    476      sm_90    476      sm_100  476
sm_110   476      sm_110a  59       sm_120  476
sm_110 family total: 535
```

> The "a" suffix matters. `sm_110a` is the architecture-specific variant;
> a `grep -o 'sm_[0-9]*'` counts 535 and a `\bsm_\d+\b` regex counts 476,
> because the regex misses the suffixed ones. **535** is the right number,
> and it matches rev-tech's measurement exactly.

No CPU fallback anywhere: ComfyUI logs `Device: cuda:0 NVIDIA Thor`, the
GPU rail draws 76–85 W during generation, and `nvidia-smi` reports 97–98 %
utilisation during the sampling stages.

### 3.1 No compiled extensions

`results/no_compiled_extensions.txt`, from `scripts/check_extensions.py`:

```
[absent] flash-attn    [absent] nvdiffrast   [absent] nvdiffrec
[absent] xformers      [absent] cumesh       [absent] flexgemm
[absent] o-voxel       [present] triton 3.9.0 (not required by ComfyUI;
                                             arrives as a torch dependency)
```

and the whole import surface of the TRELLIS.2 module:

```python
from typing import Optional, Tuple
import torch
import comfy.model_management
```

**Triton deserves the nuance.** res-3d says ComfyUI's requirements contain
none of flash-attn, nvdiffrast, nvdiffrec, triton, xformers, cumesh,
flexgemm or o-voxel. Triton *is* installed — because **torch 2.15.0 depends
on it**, as a pure-Python wheel from PyPI. No source build, and nothing on
this path calls it. res-3d's claim is that ComfyUI does not *require* it,
and that is what the check verifies. Every package that *would* need a
source build on aarch64/CUDA 13 — kaolin, spconv, pytorch3d, xatlas,
torchmcubes, pymcubes, custom_rasterizer, differentiable_renderer,
nvdiffrec, nvdiffrast, flash-attn, xformers — is **absent**.

This is also why the licence question (§6) comes out clean: the upstream
reference pipeline's renderer dependencies (`nvdiffrast`, `nvdiffrec`) are
exactly the ones this path does not have.

---

## 4. The measurement

Every number below carries the box's state beside it, because on this box
the state moves the number.

**How to read these.** The run label's `_a`/`_b` suffix is a **cold** run
(the server was just restarted, so the 13 GB of weights are read from
disk inside the wall-clock) and a **warm** run (weights already resident in
unified memory). ComfyUI's node cache is **off** for every one of them
(`--cache-none`); with the cache on, run `_b` would reuse run `_a`'s
sampler output and the wall-clock would measure only the mesh tail.

The "load avg" column is the box's CPU-lane load during the run, on 14
cores. It is the single most important column here.

### 4.1 The headline

| run | wall (s) | peak RAM used (MB) | total RAM (MB) | min `MemAvailable` (MB) | peak GPU rail (mW) | load avg (14 cpu) |
|---|---:|---:|---:|---:|---:|---|
| `512_bf16_a` (cold) | 114.77 | 60,649 | 125,749 | 85,621 | 61,694 | 17.97–20.26 (mean 18.82) |
| `512_bf16_b` (warm) | 98.35 | 61,368 | 125,749 | 85,228 | 89,521 | 17.61–19.29 (mean 18.26) |
| `1024_bf16_a` (cold) | 165.53 | 62,269 | 125,749 | 78,848 | 67,589 | 18.73–27.29 (mean 21.56) |
| `1024_bf16_b` (warm) | 178.62 | 62,340 | 125,749 | 81,680 | 82,914 | 19.11–27.69 (mean 24.28) |
| `512_fp8_a` (cold) | 151.16 | 62,496 | 125,749 | 89,521 | 56,170 | 24.78–38.02 (mean 28.04) |
| `512_fp8_b` (warm) | 214.98 | 64,756 | 125,749 | 82,525 | 75,841 | 27.12–52.31 (mean 32.48) |
| `512_fp8fast_a` (cold) | 291.69 | 70,836 | 125,749 | 61,897 | 78,560 | 46.08–113.88 (mean 92.73) |
| `512_fp8fast_b` (warm) | 287.39 | 50,499 | 125,749 | 84,618 | 86,023 | 22.99–44.24 (mean 31.10) |

**The answers the brief asks for:**

| | 512³ | 1024³ |
|---|---:|---:|
| wall-clock | **98–115 s** | **166–179 s** |
| peak RAM used | ~61 GB | ~62 GB |
| `MemAvailable` dip | 125,749 → 85,228 MB | 125,749 → 78,848 MB |
| peak GPU rail draw | 62–90 W | 68–83 W |

> **Read the FP8 rows with their load column.** The FP8 runs were taken
> later in the session, while other seats were using the box, and the
> harness only started recording *GPU* contention afterwards (§4.5). Their
> wall-clocks are therefore not comparable with the BF16 rows. What *is*
> comparable is the sampler time, because the samplers are the GPU stage
> and the GPU was exclusively ours during the 512³ runs (§7.2).

The `MemAvailable` dip is **40–47 GB** — but note what it is *not*: the
voxel grid. Going from 512³ to 1024³ moves peak RAM by only ~1.6 GB. The
memory is the **weights** (13 GB) plus the texture bake's working set
(4096² atlases, three of them), and the 1024³ shape latent is not the
dominant term. A prop catalogue that only ever ran 512³ would not need a
bigger machine.

### 4.2 What scales with resolution, and what does not

The graph splits into the **sampling** stages (the three KSamplers) and the
**mesh tail** (remesh, decimate, unwrap, the texture/AO/normal bakes, and
the GLB write):

| run | sampling (3× KSampler) | mesh tail | other | wall |
|---|---:|---:|---:|---:|
| `512_bf16_a` | **16.02 s** | 91.83 s | 5.96 s | 114.77 s |
| `512_bf16_b` | **16.13 s** | 75.93 s | 5.32 s | 98.35 s |
| `1024_bf16_a` | **64.49 s** | 86.48 s | 13.76 s | 165.53 s |
| `1024_bf16_b` | **67.22 s** | 96.09 s | 14.19 s | 178.62 s |
| `512_fp8_a` | **25.12 s** | 114.76 s | 10.33 s | 151.16 s |
| `512_fp8_b` | **23.22 s** | 180.59 s | 10.12 s | 214.98 s |
| `512_fp8fast_a` | **39.90 s** | 209.58 s | 42.21 s | 291.69 s |
| `512_fp8fast_b` | **20.57 s** | 255.55 s | 11.27 s | 287.39 s |

**This is the number a scheduler needs.** Sampling goes 16.0 s → 64.5 s,
a **4.0×** cost for 8× the linear resolution. The mesh tail costs
**the same at both resolutions** (~76–96 s) — it is a function of the
decoded mesh, not of the sampling grid.

So the cost model for a night of props is:

```
time  ≈  constant  (~80-95 s of mesh tail)
       + 16 s      for 512³
       + 64 s      for 1024³
```

and the *mesh tail is 80% of a 512³ job*. That is the part to optimise,
and it is the part that is CPU-bound.

### 4.3 The mesh tail is a CPU-lane consumer, and the box is shared

The unwrap stage, on the same recipe, at the same resolution:

| box state | unwrap |
|---|---:|
| quiet | **21.4 s** |
| quiet | 24.0 s |
| quiet | 24.45 s |
| another seat compiling OpenImageIO across 10 cores | **154.6 s** |

A **7.2× swing**, with the GPU untouched. The unwrap is chart packing —
CPU work — and the Thor's 14 cores are shared with other seats' Infinigen
sweeps and compiles. (During this session the box's load average went
from ~18 to over 100 when another seat started a soak test.)

The practical consequence: **the GPU is not the scarce resource on this
box, the CPU lane is.** `nvidia-smi` showed 0% utilisation while a
TRELLIS.2 job sat in the unwrap. A scheduler that batches generative jobs
here has to budget CPU lanes, and a run whose wall-clock is quoted without
the load average beside it is not comparable with any other run.

### 4.4 Per-node breakdown
**`512_bf16_a`** — wall 114.77 s

| node | seconds |
|---|---:|
| BakeAmbientOcclusion | 30.60 |
| UnwrapMesh | 21.56 |
| KSampler (all three stages) | 16.02 |
| BakeTextureFromVoxel | 15.24 |
| BakeNormalMapFromMesh | 9.87 |
| RemeshMesh | 4.16 |
| SaveImage | 3.94 |
| SaveGLB | 3.71 |
| Trellis2Conditioning | 1.69 |
| MeshSmoothNormals | 1.67 |
| VAELoader | 1.14 |
| VaeDecodeShapeTrellis | 1.10 |
| VaeDecodeTextureTrellis | 1.09 |
| DecimateMesh | 0.96 |
| UNETLoader | 0.45 |
| VaeDecodeStructureTrellis2 | 0.27 |
| ApplyTextureToMesh | 0.13 |
| ImageCropToMask | 0.08 |
| LoadImage | 0.06 |
| Trellis2ShapeStage | 0.04 |
| CLIPVisionLoader | 0.01 |
| CFGOverride | 0.01 |
| Trellis2TextureStage | 0.01 |

**`1024_bf16_a`** — wall 165.53 s

| node | seconds |
|---|---:|
| KSampler (all three stages) | 64.49 |
| BakeTextureFromVoxel | 23.14 |
| BakeAmbientOcclusion | 22.10 |
| UnwrapMesh | 17.60 |
| BakeNormalMapFromMesh | 7.56 |
| RemeshMesh | 5.57 |
| VaeDecodeShapeTrellis | 5.30 |
| VaeDecodeTextureTrellis | 4.82 |
| SaveImage | 4.02 |
| SaveGLB | 3.86 |
| Trellis2Conditioning | 1.71 |
| MeshSmoothNormals | 1.47 |
| DecimateMesh | 1.05 |
| VAELoader | 1.03 |
| UNETLoader | 0.42 |
| VaeDecodeStructureTrellis2 | 0.30 |
| ApplyTextureToMesh | 0.11 |
| ImageCropToMask | 0.07 |
| LoadImage | 0.05 |
| Trellis2ShapeStage | 0.04 |

The GPU's own stage is `KSampler`; everything else is either model loading
or the CPU-bound mesh tail.

Full records, with the box state before *and* after every run, are in
`results/run_*.json`.

### 4.5 The GPU is shared too

Part-way through the session, while reading the FP8-fast timings, this
turned up:

```
$ nvidia-smi --query-compute-apps=pid,used_memory --format=csv
pid,process_name,used_gpu_memory
2145779, .../trellis/.venv-e2/bin/python, 5717 MiB     <- us
2157520, .venv/bin/python, 7134 MiB                    <- another seat
```

Another seat's job — a "warm scene" experiment — was on the Thor at the
same time. The CPU lane was never the only contended resource.

So the harness now samples, during every run:

* the number of GPU compute processes that are **not** ours,
* the GPU's mean and peak utilisation,
* the GPU's mean power draw.

The rows in §4.1 predate that instrumentation and show `—` in that column;
the rows after it carry the numbers. The important consequence for reading
this report: **the 512³ BF16 rows and the 512³ FP8 rows were both taken
while the GPU was exclusively ours** (the other seat's GPU job started at
03:12, after the 512³ FP8 runs), so the sampler-time comparison in §7.2 is
sound even though the wall-clocks are not directly comparable.

---

## 5. Determinism

**The output is not byte-reproducible.** Same seed, same recipe, same
workflow, two independent executions with ComfyUI's cache off:

| | run A | run B |
|---|---|---|
| GLB sha256 | `78465d5e54d68e4b…` | `365fb68b7312b845…` |
| GLB bytes | 58,509,380 | 58,587,568 |
| vertices | 484,611 | 485,564 |
| triangles | 699,894 | 699,906 |
| material set | identical | identical |
| image set | identical | identical |
| accessors | **differ** | **differ** |

Reproduced with `scripts/inspect_glb.py`.

**Why.** res-3d §5 says it outright: *"Rasterization with atomics, attention
kernels that select different strategies at runtime, and non-deterministic
CUDA reductions mean byte-for-byte reproduction is not something we should
promise."* What we actually see is that the *sampling* is not reproducible:
the structure and shape stages pick different values on each run, so the
mesh that comes out is a different mesh. The unwrap chart count swings with
it — 4,449 / 6,945 / 8,106 / 8,162 / 13,890 charts observed across runs of
the same recipe.

**What *is* stable is the part that matters downstream:**

- the material set — one PBR material with `baseColorTexture`,
  `metallicRoughnessTex`, `normalTexture`, `occlusionTexture`,
  `doubleSided`;
- the image set — three embedded PNGs (albedo, metallic-roughness packed,
  normal);
- **the provenance record**: the GLB's `asset.extras.prompt` carries the
  full workflow JSON (5,059 bytes), so the mesh knows how it was made.

**The honest summary for the plan:** *do not promise bit-identical
reproducibility; do promise that every asset carries its recipe.* The
provenance hook is already there and it is the thing worth standardising on.

---

## 6. The weights' licence

Checked against the Hugging Face registry and the upstream repositories
directly, not against res-3d's summary.

| Component | Source | Licence | Gated | Commercial use |
|---|---|---|---|---|
| TRELLIS.2 code | `github.com/microsoft/TRELLIS.2` | **MIT** (Microsoft Corporation) | — | yes |
| TRELLIS.2 weights (original) | `huggingface.co/microsoft/TRELLIS.2-4B` | **mit** | `gated: False` | yes |
| TRELLIS.2 weights (ours) | `huggingface.co/Comfy-Org/TRELLIS.2` | **mit** | `gated: False` | yes |
| DINOv3 encoder | inside the above, `clip_vision/dino_v3_vit_l.safetensors` | Meta `dinov3-license` | `gated: manual` (upstream) | yes, with attribution and end-use limits |
| ComfyUI (the host) | `github.com/comfyanonymous/ComfyUI` | **GPL-3.0** | — | **as a separate service only** |
| `nvdiffrast` / `nvdiffrec` | NVIDIA | their own | — | **not on this path** |
| SDXL base 1.0 (text path's image stage only) | Stability AI | OpenRAIL++-M | — | yes, with use restrictions |

### What it permits

**The weights are MIT and ungated.** The registry returns
`license: mit, gated: False` for both `microsoft/TRELLIS.2-4B` and
`Comfy-Org/TRELLIS.2`, and neither carries `extra_gated_eu_disallowed` or
any region flag. Commercial use, redistribution and modification are all
fine, with the MIT notice retained.

The revision actually loaded is pinned and recorded in
`models/TRELLIS2_WEIGHTS_REVISION.txt`:

```
repo   = Comfy-Org/TRELLIS.2
sha    = 430a9d09b2416687018c8fe8edced2ad4858a439
license= MIT (code + weights), ungated
```

and that sha matches the registry's current `sha` for the repo, so the
weights on disk are the ones the registry describes.

### The three things that are *not* clean

1. **ComfyUI is GPL-3.0.** It is the *host*, not the generator. Running it
   as a separate service and talking to it over HTTP is the arrangement
   that keeps the licence question on the right side of the line. Linking
   it into a proprietary product is not.
2. **The DINOv3 encoder's terms travel with the pipeline.** Meta's
   `dinov3-license` is `license: other` with `gated: manual` and carries
   end-use conditions (attribution; no weapons or espionage; no reverse
   engineering). `Comfy-Org/TRELLIS.2` republishes the encoder inside its
   MIT repo, so *the file we load is MIT-licensed*; the upstream Meta repo
   it was derived from is separately gated. The obligations to carry are
   the DINOv3 attribution and its end-use limits, and the full text needs
   a signed agreement with Meta, which this spike did not obtain.
3. **`nvdiffrast` and `nvdiffrec` are the reason the reference pipeline is
   not MIT in practice** — `nvdiffrec`'s licence is not commercial. The
   upstream README lists them as separate-licence dependencies. **They are
   not on this path at all** (§3.1), so their terms do not attach to the
   native ComfyUI route. This is the licence payoff of choosing the native
   implementation over the upstream repo, and it is the single strongest
   argument for the native path.

### Verdict on the licence

**Clean for commercial use as a separate service, with two obligations to
carry**: the MIT notices for TRELLIS.2 and ComfyUI, and the DINOv3
attribution and end-use limits. No region restriction, no gating, no
non-commercial clause on the path actually used.

---

## 7. FP8: the lever, and a bug in it

The lab's proposition (`docs/lab/exp-fp8-tensorcores.md`) is that the Thor's
Blackwell tensor cores give **1.6–1.7× FP16 on large GEMMs**, and that a
generator which keeps activations in FP8 would see it. But the lab also
measured C4b: *"quantizing weights alone buys nothing unless the
activations are quantized too (0.95×)."*

ComfyUI exposes two knobs, and they are different mechanisms:

| knob | mechanism | what happens |
|---|---|---|
| `UNETLoader.weight_dtype = "fp8_e4m3fn"` | `manual_cast` ops | weights stored FP8, **cast to the compute dtype at every use** |
| `UNETLoader.weight_dtype = "fp8_e4m3fn_fast"` | `fp8_ops` | the fused path: the matmul itself runs in FP8 |
| `--fast fp8_matrix_mult` (server-wide) | `fp8_ops` | the same, applied to every model |

`comfy/ops.py: pick_operations` chooses `fp8_ops` only when
`supports_fp8_compute(load_device)` is true — which needs compute
capability ≥ 9. The Thor is 11.0, so it is.

### 7.1 The bug: the lever did not exist

The first FP8 run failed in **3.1 seconds**, at model load:

```
File 'comfy/ldm/trellis2/model.py', line 674, in __init__
  coords = torch.meshgrid(*[torch.arange(res, device=self.device,
                                         dtype=dtype) for res in [resolution] * 3],
                          indexing='ij')
NotImplementedError: "arange_cpu" not implemented for 'Float8_e4m3fn'
```

`dtype` there is the model's **weight** dtype. `torch.arange` has no CPU
kernel for FP8, so the model cannot be *constructed*. The lever was not
slow — it was unreachable, for any model that builds a coordinate grid in
its weight dtype.

**The fix** (`scripts/patches/trellis2-fp8-rope.patch`, one line): build
the grid in float32. The grid is a *positional* tensor, not a weight — the
sparse rotary path already casts its coords to float32, and the dense
path's own frequencies are float32.

**And it is numerically neutral for everything else.**
`scripts/verify_patch_neutral.py` checks it directly, for every resolution
the graph uses (16, 32, 64) and both bf16 and fp16: the coordinates and
the resulting `rope_phases` buffer are **bit-identical**, because
bf16/fp16 represent every integer up to 256 exactly and the float32
frequencies promoted the outer product to float32 anyway. Only the FP8 path
changes behaviour.

`setup.sh` applies the patch and re-runs the neutrality check, so the tree
is reproducible from the setup script alone.

### 7.2 What the lever actually buys

**Speed.** The sampler stages are the measurement that matters here — the
samplers are the GPU stage, and during the 512³ runs the GPU was
exclusively ours (the other seat's GPU job started at 03:12, after those
runs; §4.5).

| 512³ — time in the 3× KSampler | run `_a` | run `_b` | mean | vs BF16 |
|---|---:|---:|---:|---:|
| **BF16** | 16.02 s | 16.13 s | **16.08 s** | — |
| **FP8 weights** (`fp8_e4m3fn`) | 25.12 s | 23.22 s | **24.17 s** | **+50% slower** |
| **FP8 fused** (`fp8_e4m3fn_fast`) | 39.90 s | 20.57 s | **30.24 s** | **+88% slower** |

**Neither FP8 form is faster than BF16. Not one configuration, not one run.**

At 1024³ the FP8 rows are contaminated — both runs were taken with five
other GPU processes on the Thor — so the only honest statement there is
*at best equal, at worst much slower* (one run's samplers took 180.6 s
against BF16's 64.5 s, the other took 69.7 s against 67.2 s). **Never
faster.**

The reason is exactly the one the lab identified as C4b. `fp8_e4m3fn`
selects ComfyUI's `manual_cast` ops: the weights are *stored* in FP8 (half
the memory) but are cast back to the compute dtype at every matmul, so the
run pays the cast on every layer and saves nothing on the arithmetic.
`fp8_e4m3fn_fast` selects the fused `fp8_ops`, which is the mechanism the
lab's 1.6× figure is about — and it is *more* variable (20.6 s to 39.9 s
across two runs), tracking the box's CPU load closely, which points at
per-layer scale computation being the new bottleneck.

**Quality.** This one needs care, because the obvious measurement is
invalid. The pipeline is not reproducible (§5), so two runs produce
different meshes with differently-laid-out atlases, and a pixel-for-pixel
comparison of two atlases mostly measures *"the mesh is different"*. The
control is therefore the **BF16-vs-BF16 pair**: the PSNR you get from
changing nothing but the run.

At 512³, with two BF16 runs and two FP8 runs (`results/precision_study_512.json`):

| map | NOISE — same dtype, two runs | SIGNAL — BF16 vs FP8 |
|---|---|---|
| base colour | 12.02 – 15.82 dB (mean 13.92) | 12.31 – 12.52 dB (mean 12.43) |
| metallic | 7.28 – 8.44 dB (mean 7.86) | 7.42 – 7.58 dB (mean 7.48) |
| roughness | 9.73 – 14.18 dB (mean 11.95) | 11.07 – 11.13 dB (mean 11.10) |
| normal | 24.57 – 26.84 dB (mean 25.70) | 25.42 – 25.68 dB (mean 25.55) |
| AO | 12.78 – 13.49 dB (mean 13.14) | 12.96 – 13.14 dB (mean 13.05) |

**Every signal value lies inside the noise range, for every map.** And two
FP8 runs differ from each other *more* than a BF16 run differs from an FP8
run (base colour 12.02 vs 12.43 dB, roughness 9.73 vs 11.10, normal 24.57
vs 25.55): the dtype's effect on the shipped asset is not detectable
against the pipeline's own run-to-run variation.

> **How far this measure reaches, honestly.** A PSNR between atlases of
> *different* meshes is a blunt instrument — the floor is low (7–15 dB on
> the colour maps), so the test is strong enough to say *"the dtype effect
> is not detectable"* and **not** strong enough to bound the error
> tightly. The normal map is the most sensitive of the five (25.7 dB
> floor), because it is derived from the mesh geometry, which is more
> similar between runs than the atlas layout is; even there the signal
> (25.55 dB) sits inside the noise (24.57–26.84). A sharper test would
> compare the *latents* of the samplers, which the graph does not expose
> for saving.

**Memory — the one thing FP8 does buy.** At 1024³ the FP8 path's
`MemAvailable` dip is much shallower and its peak RAM is much lower:

| 1024³ | peak RAM used (MB) | min `MemAvailable` (MB) |
|---|---:|---:|
| BF16 | 62,269 / 62,340 | 78,848 / 81,680 |
| FP8 weights | **49,457 / 47,686** | **90,022 / 86,928** |

**~13 GB less peak RAM** — the 9.7 GB UNet stored in half the bits is
4.85 GB, and the rest is the BF16 copies the cast path makes. On a box
with 128 GB this is not a constraint that needs solving: even the BF16
path leaves 78–81 GB available.

### 7.2.1 The verdict on the lever

**FP8 weights for the heavy blocks: measured, and rejected.**

| | result |
|---|---|
| Reachable at all? | **Only after a one-line fix** to ComfyUI's TRELLIS.2 model (§7.1) |
| Speed on the diffusion stages | **50–88% slower** than BF16, never faster, in every configuration |
| Peak RAM | ~13 GB less at 1024³ — and this box does not need it |
| Quality | **Not distinguishable from BF16** — the dtype's effect is below the run-to-run noise floor |
| Verdict | **Do not take it.** Slower, no quality difference, no useful memory difference. |

This is the lab's C4b result reproduced on the real workload: *"quantizing
weights alone buys nothing unless the activations are quantized too
(0.95×)."* The lever is now *reachable and measurable*; the measurement
says it is not worth taking. That is a more useful answer than "FP8 might
help".

### 7.3 The other lever this opened up

`fp8_e4m3fn_fast` selects ComfyUI's `fp8_ops` — the *fused* path, where
the matmul itself runs in FP8 rather than the weights merely being stored
in FP8. That is the mechanism the lab's 1.6× figure is actually about,
and it **was** measured here (§7.2): 20.57 s and 39.90 s against BF16's
16.0 s.

It was slower, not faster, and it was the *most variable* of the three
(20.6 s to 39.9 s across two runs, tracking the box's CPU load almost
one-for-one: the 39.9 s run was at a mean load of 92.7, the 20.6 s run at
31.1). That pattern points at the fused path's per-layer scale computation
being the new bottleneck — CPU work, on a box whose CPU lane is shared.

So the lab's 1.6× does not transfer to this workload, in either form.
**What would be worth a follow-up:** the fused path's CPU overhead is the
thing to attack, not the precision. A Thor-native rewrite that keeps the
per-tensor scales on the GPU (or precomputes them per layer) is the
experiment the lab's number actually points at — and it is a rewrite of
ComfyUI's ops, not a flag.

The server-wide equivalent of the same ops is `--fast fp8_matrix_mult`,
which applies them to every model in the process. It is a one-flag
experiment for whoever picks this up.

---

## 8. The text path

**The native ComfyUI TRELLIS.2 path is image-conditioned only.** Neither
`Trellis2Conditioning` (which takes `CLIP_VISION` + `IMAGE`) nor
`Trellis2TextureStage` (which takes `CONDITIONING` + `LATENT`) has a text
input, and `comfy_extras/nodes_trellis2.py` contains no text encoder at
all. There is no text→3D on this path.

**Text→image→3D works**, and is the composition a prop catalogue wants:
`scripts/build_text2image.py` builds an SDXL stage
(`sd_xl_base_1.0.safetensors`, 30 steps, CFG 7.0, fixed seed 1234) whose
output is then fed to the TRELLIS.2 stage. The SDXL weights are symlinked
from `~/image-studio/ComfyUI/models/checkpoints/` — a read-only dependency
on an existing tree, not a copy, and a licence to track separately
(OpenRAIL++-M, §6).

**Measured end to end** (`scripts/run_text_path.sh 512`, records in
`results/run_text2image.json` and `results/run_textprop_512.json`):

| stage | wall | peak RAM | result |
|---|---:|---:|---|
| text → image (SDXL base 1.0, 30 steps, 1024²) | **27.6 s** | 46.9 GB | a 1024² PNG |
| image → 3D (TRELLIS.2, 512³) | **152.3 s** | 46.0 GB | `textprop_512_00001_.glb`, 53.7 MB |

The resulting GLB is a complete PBR asset: 436,860 vertices, 699,674
triangles, one material with `baseColorTexture`, `metallicRoughnessTex`,
`normalTexture` and `occlusionTexture`, three embedded PNGs, and the
provenance record (5,038 bytes of workflow JSON) in `asset.extras.prompt`.

**So a prop from text costs ~180 s** at 512³ on this box — of which only
27.6 s is the image stage. The text stage is cheap; the 3D stage is the
same cost as any other 512³ prop (§4.1).

One real bug found in that script and fixed: the negative prompt was
serialised **character by character** (`"b, l, u, r, r, y, ,, ..."`), because
a string was passed where a tuple of prompts was intended and then joined.

---

## 9. Verdict for the prop-maker role

**TRELLIS.2 is the strongest PBR generator on the shortlist, and it is
usable as-is on the Thor.** The reasons, in order of how much they matter:

1. **It is the only one that produces a complete PBR set** — albedo,
   metallic-roughness, normal, AO, baked onto a UV-unwrapped atlas, in a
   GLB with a real material. Nothing else on the shortlist ships a
   material.
2. **It needs no compiled extension.** No source build, no sm_110 kernel
   hunting, no third-party renderer with a non-commercial licence.
3. **It is MIT and ungated**, with the caveat that ComfyUI itself is
   GPL-3.0 and must stay a separate service, and the DINOv3 terms travel
   with the encoder.
4. **It carries its own provenance.** The GLB's `asset.extras.prompt` holds
   the workflow JSON that produced it.

The costs, honestly:

- **~100 s per 512³ prop and ~170 s per 1024³ prop** on this box, of which
  the mesh tail is ~80% and ~50% respectively — and the mesh tail is
  **CPU-bound and contended** (§4.3).
- **Not bit-reproducible**, though it is recipe-reproducible (§5).
- **The text path needs a second model** (SDXL) in front of it (§8), which
  is another licence to carry and another stage to schedule.

---

## 10. What this changes for the plan

1. **Rev-tech spike 2's pass/fail conditions all pass**: CUDA true,
   capability (11,0), a GLB with PBR out, wall-clock at 512³ and 1024³
   recorded, peak `MemAvailable` dip recorded, no compiled extensions. The
   stock PyPI torch 2.15.0 cp312 aarch64 wheel is sufficient — the
   "compile it yourself" branch of rev-tech's plan is **not** needed for
   this generator.
2. **The FP8 lever should be recorded as measured-and-rejected** for both
   forms ComfyUI exposes, with the patch that made it measurable, and with
   the `--fast fp8_matrix_mult` fused path left open (§7.3). Its one
   benefit — ~13 GB of peak RAM at 1024³ — is not a constraint on a 128 GB
   box.
3. **The scheduler needs to know the CPU lane is the scarce resource**
   (§4.3), and that the mesh tail is a **fixed** ~80 s per prop
   independent of resolution, while sampling is the only part that scales
   (§4.2).
4. **Provenance is solved by the asset itself** — the GLB carries its
   recipe. That is the hook the plan's provenance section should standardise
   on, instead of asking the generator to be deterministic (§5).
5. **The text path is text→image→3D, not text→3D**, and needs SDXL in the
   picture (§8).

---

## 11. Walls hit

Things that cost time, in the order they cost it, so the next seat does not
pay them again.

**Measurement harness (the biggest wall).** Getting a trustworthy
per-node breakdown took four attempts, and every failure was silent:

1. ComfyUI has **no reliable per-node *end* message**. It sends
   `"executed"`, but only for nodes that produce UI output —
   `execution.py` guards it with `if len(output_ui) > 0:`. A KSampler
   returns a LATENT, so it never gets one. Measured here: **23 nodes
   started, 2 produced `"executed"`**. Timing against `"executed"` reports
   0.00 s for precisely the nodes that do the work. The usable signal is
   the gap to the *next* node's start, because ComfyUI executes a prompt's
   nodes in order.
2. **The socket must be open before `POST /prompt`.** ComfyUI publishes
   the per-node messages to the client id that owns the prompt and
   **drops** them if that client is not connected yet. A socket opened
   afterwards loses the early nodes and collapses the breakdown to one
   bogus entry.
3. **Nothing in the capture path may block the event loop.** `urllib`'s
   blocking `urlopen`, and a blocking `time.sleep(1.0)` inside the async
   polling loop, both froze the reader for long stretches; the messages
   then arrived in one burst and every per-node timestamp became the same
   instant. The capture came back with **zero** messages before this was
   found. `post_prompt` and `get_history` are now `aiohttp` calls.
4. **Filter on `prompt_id`.** ComfyUI broadcasts to the client id that
   owns a prompt, so a previous prompt's messages can land in a new
   capture, and the one message that carries no prompt id is a reconnect
   notice belonging to whichever prompt was running when the socket opened.

**ComfyUI API format.** Dynamic-combo widgets want flat dotted input
names, not nested dicts (§2.2). The error message points at the wrong
place.

**The FP8 construction bug** (§7.1) — one line, but it is the difference
between "the lever is slow" and "the lever does not exist".

**The box's contention.** Two of this session's exploratory measurements
are not in the final table because the box was too busy for them to mean
anything. The load average is recorded beside every number so that a
future reader can tell which is which.

**And the GPU is shared too.** This one only turned up while reading the
FP8-fast numbers: `nvidia-smi --query-compute-apps` showed a second
process on the Thor, another seat's "warm scene" experiment, with 7 GB of
GPU memory. The CPU lane was never the only contended resource, and a
GPU-stage timing without that checked is not comparable either. The
harness now samples the number of foreign GPU processes, the GPU's
utilisation and its power draw, during every run (§4.5).

The honest consequence: the 1024³ FP8 rows are contaminated (five other
GPU processes during both runs) and are reported with that caveat rather
than quietly averaged in. The 512³ rows are not — the other seat's GPU
job started after they finished.

---

## 12. Where everything is

| | |
|---|---|
| This report | `SPIKE.md` |
| The map, and how to run it | `README.md` |
| The environment | `setup.sh` (idempotent, fails loudly) |
| The Thor patch | `scripts/patches/trellis2-fp8-rope.patch` |
| The measurement records | `results/run_*.json` — the evidence |
| The box's state | `results/box_state.txt` |
| The GPU proof | `results/gpu_proof.txt` |
| The extension check | `results/no_compiled_extensions.txt` |
| The patch-neutrality proof | `results/patch_neutrality.txt` |
| Raw websocket evidence | `results/ws_dump_512.jsonl` |
| The generated GLBs | `out/trellis2/` (not in git — large) |
