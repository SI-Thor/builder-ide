# REVIEW — round 2 cross-review: the technology reports against each other and against the Thor

Cross-review of the round-1 technology reports, their mutual contradictions, and a
consolidated ledger/licence register/environment plan for the port.

Reviewed: `~/src/builder-ide/docs/vision.md` (the north star), `res-3d.md` (3D generators),
`res-cad.md` (CAD, OpenUSD, textures, motion, audio, the scheduler), plus the in-flight
Infinigen-on-Thor spike (`~/src/infinigen-thor`) as partial substitute evidence.

Read-only throughout. Nothing was installed into any shared environment; wheels were
downloaded into `/tmp` with `pip download --only-binary=:all:` and inspected. No
sub-agents (per BRIEF.md).

---

## 0. Availability of the sources named in the brief

| Document named in BRIEF.md | Actual path | Status |
|---|---|---|
| `~/src/builder-ide/docs/vision.md` | as stated | **available**, read in full |
| `docs/research/res-3d.md` | `~/src/builder-ide/docs/research/res-3d.md` | **available**, read in full (byte-identical to `~/lm-wt/res-3d/REPORT.md`, md5 `5e0a7854…`) |
| `docs/research/res-cad.md` | `~/src/builder-ide/docs/research/res-cad.md` | **available**, read in full (byte-identical to `~/lm-wt/res-cad/REPORT.md`, md5 `266d613b…`) |
| `~/src/infinigen-thor/thor/SPIKE.md` | **does not exist** | **NOT AVAILABLE** — the spike is still running (see below) |
| `~/lm-wt/split/REPORT.md` | **does not exist** | **NOT AVAILABLE** — only `BRIEF.md` and `casey-ideas-fromgoogle5.md` are present |

The brief's relative path `docs/research/res-3d.md` resolves inside `builder-ide`, not
inside the working directory; the working directory `~/lm-wt/rev-tech` contained only
`BRIEF.md` at the start of this review.

### 0.1 What was used instead of the two missing reports

**In place of `thor/SPIKE.md`** (the Infinigen-on-Thor spike), the spike's own artefacts
in `~/src/infinigen-thor` were read directly — `thor/build-bpy.sh`, `thor/install.sh`,
`thor/run-timed.sh`, `thor/patches/`, `pyproject.toml`, `.python-version`, the branch
`thor-spike` commit log, and the build logs on the external SSD
(`/media/caseydigennaro/TOSHIBA EXT/thor-spike/logs/`). This is *stronger* evidence than a
prose summary would have been for the questions this review asks, because it is the
build tree itself. It is, however, **mid-flight**: at the time of writing the bpy wheel
had not been produced (`wheels/` empty), the ninja build was running (stage 5), and
`SPIKE.md` has not been written. **No Hello Room / Hello World timing, no CPU-vs-GPU
Cycles render comparison, and no phase-2 recommendation exists yet.**

**In place of `~/lm-wt/split/REPORT.md`** (how to shift the processing burden), only its
brief was available. That brief is informative for this review because it defines the
seam this review must not duplicate: it asks for a per-stage cost map of Infinigen, a
placement table across Thor/ProArt/cloud/Orin, a Thor→ProArt wire comparison, a triage of
`casey-ideas-fromgoogle5.md`, a day/night power plan, and the top 5 burden-shifting moves.
None of that is answered here. What this review contributes to it is §4 (the environment
plan and the scheduler's residency model) and §6 (risks R1, R4, R7), all of which the
split report will need. The split brief also states it will read `thor/SPIKE.md` "if it
exists when you finish" — so the two missing documents are mutually dependent and both
were in flight at review time.

---

## 1. Agreements and contradictions

### 1.0 Verdict summary

| # | Topic | Nature | Which is right |
|---|---|---|---|
| C1 | PyPI `torch` on aarch64: CPU-only vs CUDA-13.2-with-sm_110 | **Direct contradiction** | **Both, version-scoped.** res-3d is right about torch 2.6.0; res-cad is right about torch 2.15.0. res-3d's *generalisation* is the error |
| C2 | Python version | **Contradiction + a shared premise error** | **Neither.** Both briefs asserted "Python 3.12"; the world engine needs **3.11**. Three interpreters are required |
| C3 | ComfyUI vs modly as the host for generative models | **Apparent contradiction** | **Both, and they compose.** res-3d picked the right *engine*, res-cad the right *interface* |
| C4 | Scheduler design (hot/warm/cold, batch-by-model, provenance ownership) | **Agreement** | Both right; both share one blind spot (§C4) |
| C5 | Licences: non-commercial weights as the gating item | **Agreement**, with one gap | Both right; the gap is modly's texture path and its GGUF repack (see C5) |
| C6 | sm_110 kernel coverage | **Agreement in direction**, one measured fact missing from both | res-3d's framing is right; the box's *default* nvcc arch is a third, unstated risk (R1) |
| C7 | Published speed/memory figures are datacenter numbers | **Agreement** | Both right, and both correctly refuse to schedule against them |
| C8 | The recipe, not USD, is the source of truth | **Agreement** | res-cad right; consistent with vision.md §8 |
| C9 | "122 GB makes VRAM a non-issue" | **Agreement, overstated** | Right for capacity, wrong for *contention* and wrong about *observability* (§C9) |

---

### C1 — PyPI `torch` on aarch64: "CPU-only" vs "CUDA 13.2 with sm_110"

**The claims.**
- res-3d §1: *"The aarch64 torch wheels published on PyPI are CPU-only builds — the 2.6.0 aarch64 wheel declares no `nvidia-*` runtime dependencies whatsoever — so a working Thor install must point at NVIDIA's own indexes."*
- res-cad, TL;DR: *"stock PyPI `torch` 2.15.0 now ships an aarch64 CUDA wheel built against CUDA 13.2 with `sm_110` (Blackwell) kernels inside `libtorch_cuda.so` … The whole 'Jetson needs a special PyTorch index' problem that bit AGX Orin is gone for Thor: `pip install torch` should just work."*

**Both are literally true. The disagreement is entirely about which torch version.**
Both reports verified the same thing; they read different files.

**Evidence (measured on the Thor, 2026-10-30).**

| | torch 2.6.0 cp312 aarch64 | torch 2.15.0 cp312 aarch64 |
|---|---|---|
| Wheel size | 95.6 MB | 483.7 MB |
| `libtorch_cuda.so` in the wheel | **absent** | present, 513.5 MB |
| `nvidia-*` / cuda deps in per-wheel METADATA | 13 lines, **every one** gated `platform_machine == "x86_64"` | 6 lines, gated only on `platform_system == "Linux"` |
| → installed on aarch64 | **zero** CUDA libs → CPU-only | `cuda-toolkit[cublas,cudart,cufft,cufile,cupti,cusolver,cusparse,nvjitlink,nvrtc,nvtx]==13.2.2`, `nvidia-cudnn-cu13==9.26.0.51`, `nvidia-nccl-cu13==2.30.7`, `triton~=3.9.0` |
| sm_110 kernels | n/a | **535 sm_110 ELF images** in `libtorch_cuda.so` (`cuobjdump --list-elf`), plus sm_100/103/120/121/90/80. No sm_87. |

`cuda-toolkit==13.2.2` matches this box exactly (`/usr/local/cuda-13.2`, nvcc 13.2.86).

**Verdict.** res-cad is right about the present. res-3d is right about the version
TRELLIS.2 actually pins — and that is the one thing that makes the question non-trivial:
`microsoft/TRELLIS.2`'s `setup.sh` (fetched first-party) contains

```
conda create -n trellis2 python=3.10
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
```

so TRELLIS.2's *reference* path does take a CPU-only-on-aarch64 torch 2.6.0 and a CUDA
**12.4** runtime — exactly res-3d's world. But that path is the one res-3d itself rejects
(§4.1). The **ComfyUI native path pins no torch at all** — the local ComfyUI tree's
`requirements.txt` lists bare `torch`, `torchvision`, `torchsde` — so it takes PyPI
2.15.0 and lands on sm_110 for free.

**Resolution.** Retire res-3d's general rule ("a working Thor install *must* point at
NVIDIA's own indexes"). It is true only for stacks pinning torch < 2.15. The rule that
survives is narrower and must be enforced per-environment: *pin torch ≥ 2.15 in every
generative environment, and assert at build time that it is the CUDA aarch64 build* —
because the failure mode is a silent CPU fallback, not an error.

Keep res-3d's refs [3][4] (Jetson AI Lab SBSA cu130/cu132 indexes) as the fallback for
any stack that must pin an older torch; the index carries torch 2.9–2.11 for cp312
aarch64 and cu132 carries 2.9.1 for cp310–cp314.

*Minor discrepancy:* res-cad says "462 MB wheel"; the actual cp312 aarch64 wheel is
483.7 MB (483.6 MB for cp311). Immaterial to the conclusion, worth correcting if the
number is quoted again.

---

### C2 — Python version: a shared premise error in both briefs

**The claims.** Both round-1 briefs state the Thor is *"aarch64, Ubuntu 24.04, **Python
3.12**, CUDA 13.2, Blackwell GPU sm_110, 122 GB unified memory"*. res-3d §1 then says
*"Python 3.12 collides with several upstream pins, and the fix is a per-model environment
rather than a per-model patch. TRELLIS.2's own setup script answers this the way we should
— a conda environment on **Python 3.10**."* res-cad is written throughout against 3.12
(cp312 wheels).

**The premise is wrong for the world engine.** Measured on this box:

| Source | Statement |
|---|---|
| `src/infinigen-thor/pyproject.toml` | `requires-python = "==3.11.*"` |
| `src/infinigen-thor/.python-version` | `3.11.13` |
| PyPI `procfunc` 0.37.0 (an Infinigen dependency) | `requires-python = ">=3.11,<3.12"` → **hard block on 3.12** |
| `thor/build-bpy.sh` (spike's own finding) | *"Blender 4.2 embeds exactly Python 3.11 (build_files/cmake/Modules/FindPythonLibsUnix.cmake: `_PYTHON_VERSION_SUPPORTED 3.11`); Ubuntu 24.04 ships 3.12 only, so we build 3.11.13 with `--enable-shared`"* |
| Box system Python | 3.12.3 (`/usr/bin/python3.12` only) |
| PyPI `scipy` 1.18.1 | `requires-python = ">=3.12"` → 3.11 needs an older scipy |

**Verdict.** Neither report is wrong about its own scope, but **both inherited a false
shared premise**, and it matters because the two reports' Python advice is mutually
incompatible:

- res-3d's **3.10** is correct *for TRELLIS.2's reference pipeline only* — and that
  pipeline is rejected. It cannot host Infinigen (needs 3.11) or bpy 4.2 (needs 3.11).
- res-cad's **3.12** is correct *for everything it recommends* — CAD/OCCT, `usd-core`,
  diffusers/SDXL, MoMask, ACE-Step all ship cp312 aarch64 wheels — but it cannot host
  Infinigen or bpy 4.2.
- The world engine needs **3.11**, which neither report mentions.

**Resolution:** three interpreters, not one — see §4. This is the single most
load-bearing correction in this review, because it invalidates the shared premise of both
reports and because "one env per model family" (res-3d §6) becomes "one env per
*interpreter + ABI* class".

---

### C3 — ComfyUI vs modly as the host for generative models

**The claims.**
- res-3d §4.1/§8: the prop-maker path is **TRELLIS.2 via ComfyUI's native implementation**
  — *"the only path on the list that requires no compiled CUDA extension."*
- res-cad §2/§10: the prop-maker station is **modly's headless FastAPI backend**
  (Orin-proven), *"spike first"*, with the TripoSG extension, mesh-only.

**Verdict: they are not actually in conflict, and they compose.** Verified from the
local clones and manifests:

*ComfyUI (engine side) — local clone `~/image-studio/ComfyUI`, **v0.42.0**, commit
`fb3befd`, 2026-10-23:*
- `comfy/ldm/trellis2/` exists with `flexgemm.py`, `model.py`, `vae.py`.
- `comfy/ldm/trellis2/flexgemm.py` imports **only** `torch` (+ `comfy.model_management`) —
  res-3d's §4.1 claim [11] is **confirmed from source**.
- `requirements.txt` contains **none** of flash-attn, nvdiffrast, nvdiffrec, triton,
  xformers, cumesh, flexgemm, o-voxel — res-3d's claim is **confirmed**.
- **Pixal3D is native too**, in the same module directory (`comfy/model_detection.py`
  detects it by a `proj_linear` projection head absent from TRELLIS.2) — so res-3d's
  "evaluate Pixal3D inside the same ComfyUI environment" is **confirmed** and costs one
  weights download, not a second environment.
- ComfyUI's attention backends are `--use-split-cross-attention`,
  `--use-quad-cross-attention`, `--use-pytorch-cross-attention` (PyTorch 2.0 SDPA) and
  `--use-sage-attention`. With no xformers in requirements, the **SDPA path is the
  sm_110-safe default** — this is the real content of res-3d's "escape hatch".
- Caveat nobody states: `pyproject.toml` in the ComfyUI tree pins
  `master.py-version = "3.10"`.

*modly (interface side) — its own README and extension manifests:*
- Extensions available: `modly-triposg-extension` (`VAST-AI/TripoSG`, ~8 GB VRAM),
  `modly-trellis2-gguf-extension` (`Aero-Ex/Trellis2-GGUF`, 1–3 B params, ~6–10 GB),
  and three Hunyuan3D-2-mini variants.
- The README describes `experimental comfy-image` / `experimental generate-from-workflow`
  as *"external ComfyUI orchestration helpers"* — i.e. modly can already *drive* ComfyUI.

**Resolution.** res-3d is right that ComfyUI-native is the right **engine** (it is the
only shortlisted PBR path with zero compiled CUDA extensions and a seeded pipeline).
res-cad is right that an HTTP-driven headless service is the right **interface** for the
scheduler (and that its `seed` parameter is first-class). The composed design is a
FastAPI/CLI service in front — modly's shape, or our own thin service over ComfyUI's
`/prompt` API — with ComfyUI as the engine behind it. **Neither report says this**, and
each would have had the reader implement only half of it.

One genuine disagreement remains open: **res-cad does not mention ComfyUI at all**, and
**res-3d does not mention modly**. Both are one-hop-from-a-better-answer.

---

### C4 — The scheduler's design: a real agreement

res-3d §6 and res-cad §9 agree on every load-bearing point, which is worth recording
because it means the scheduler needs no adjudication:

| Principle | res-3d §6 | res-cad §9 | Verdict |
|---|---|---|---|
| Batch by model, not by prompt | "the night's jobs are batched by model so the scheduler is not thrashing environments" | "hundreds of prompts through one loaded model, not one load per prompt" | agree |
| Hot / warm / cold tiers | "a model is hot when its environment is resident on the GPU" | "Hot: companion/planner LLM + critic; Warm: one generative model at a time; Cold: everything else on disk, with pinned weights revisions" | agree |
| One warm model at a time | "each model family wants its own environment" | "Warm: one generative model at a time — image-to-3D, then the texture stack, then MoMask, then ACE-Step" | agree |
| CPU work runs concurrently | (implicit) | "CPU lane runs continuously… These never wait on the GPU" | agree |
| Provenance is the scheduler's job | "The licence field should be written by the model registry rather than by the job that happens to call it" | "Provenance is the scheduler's job, not the job's" | agree, same wording independently |
| Seeding is mandatory | "TripoSR, SF3D, SPAR3D and Hunyuan3D expose no seed argument at all, so the scheduler would have to seed torch externally" | "all seeded"; "seeded" for MoMask, SDXL, ACE-Step | agree |

**The shared blind spot (see also §C9 and R4):** both treat "hot/warm/cold" as if it
were a GPU-memory problem. On this box **GPU memory is not separately observable** — see
C9.

---

### C5 — Licences: agreement, and one gap

**Agreement, verified against the Hugging Face registry** (the authoritative source for
weights terms), not against the reports' own restatements:

| Asset | Report claim | HF card (verified) | Verdict |
|---|---|---|---|
| `facebook/musicgen-small` | CC-BY-NC 4.0 (res-cad §5) | `cc-by-nc-4.0` | ✓ |
| `OpenMotionLab/MotionGPT-base` | licence reads only "cc", ambiguous (res-cad §4) | `cc` | ✓ |
| `stabilityai/stable-audio-open-1.0` / `-small` | Stability Community Licence, gated (res-cad §5) | `other`, gated `auto` | ✓ |
| `stabilityai/stable-fast-3d` | gated, licence "other" (res-3d §3) | `other`, gated `auto` | ✓ |
| `ACE-Step/ACE-Step-v1-3.5B` | Apache-2.0 code *and* weights (res-cad §5) | `apache-2.0`, ungated | ✓ |
| `microsoft/TRELLIS.2-4B`, `Comfy-Org/TRELLIS.2` | MIT, ungated (res-3d §3) | `mit`, ungated | ✓ |
| `stabilityai/TripoSR` | MIT, ungated (res-3d §3) | `mit`, ungated | ✓ |
| `VAST-AI/TripoSG` | MIT (res-cad §2) | `mit`, ungated | ✓ |
| `3DTopia/3DTopia-XL` | Apache-2.0 (res-3d §3) | `apache-2.0` | ✓ |
| `TencentARC/Pixal3D` | MIT, HF flags EU-disallowed (res-3d §3) | `license: mit` + **`extra_gated_eu_disallowed: true`** in the README frontmatter | ✓ |
| `xanderhuang/material_estimator` | Apache-2.0 (res-3d §3) | `apache-2.0` | ✓ |
| `gvecchio/StableMaterials` | OpenRAIL (res-cad §3) | `openrail` | ✓ |
| `tencent/Hunyuan3D-2mini` | Tencent Community, **not applicable in EU/UK/SK** (res-cad §2) | `other` + `extra_gated_eu_disallowed: true` | ✓ |
| `facebook/dinov3-vitb16-pretrain-lvd1689m` | Meta licence travels with TRELLIS.2's encoder (res-3d §3) | `other`, gated `manual` | ✓ |

**The gap: modly's texture path is a licence trap that neither report prices.**
`modly-hunyuan3d-mini-extension`'s own `manifest.json` says, verbatim:
*"For textures, chain the separate Hunyuan3D Paint extension."* The Hunyuan3D-2-mini
weights are the Tencent Community Licence with `extra_gated_eu_disallowed: true`
(verified above), and res-cad §2 itself notes the texture path needs `custom_rasterizer`
+ `differentiable_renderer` **CUDA C++ extensions built from source** for aarch64/CUDA
13. So "enable modly's textures later" = *territory restriction* + *two CUDA source
builds* — not the "a day of work" that res-cad §4.5's tone implies for the neighbouring
Stability option. res-cad §10 does route textures to SDXL + StableMaterials instead,
which is the correct call; the gap is that the modly texture path is never explicitly
*closed*, and res-cad §2's bullet list presents it as merely "budget a few days".

**Second gap, in the same family.** The modly extension `modly-trellis2-gguf-extension`
pulls its weights from **`Aero-Ex/Trellis2-GGUF`**, a third-party quantised repack of
TRELLIS.2. That HF repo declares **no licence at all** (`license: None` on the card).
This is exactly the situation res-3d §4.8 flags for TexGaussian (*"no LICENSE file in the
repository … ambiguous; treat as unusable until pinned"*) — but applied to a package the
team is actively being pointed at. The GGUF path is a real convenience (~6–10 GB VRAM,
1–3 B params, `vram_gb: 8`) and a licence unknown. **Record it as unlicensed until the
original MIT terms are pinned in writing.**

---

### C6 — sm_110 kernel coverage: right direction, one measured fact missing from both

Both reports are right that sm_110 is the crux. res-3d §1 is the sharper statement:
*"flash-attn publishes no wheels on PyPI at all, only an sdist, and the prebuilt binaries
that do exist carry no sm_110 SASS, which is precisely the 'no kernel image for device'
failure reported against a Thor."* Verified on PyPI: `flash-attn` 2.8.3.post2 has exactly
**one file, an sdist**; `xformers` 0.0.35 has 2 wheels, **neither aarch64**.

**The fact neither report states: the box's own `nvcc` defaults to the wrong
architecture.** Measured on `/usr/local/cuda/bin/nvcc` 13.2.86:

| Build | Embedded SASS | Embedded PTX | Result on the Thor (cc 11.0) |
|---|---|---|---|
| no `-arch` (toolkit default) | **sm_75** | compute_75 | **works** — driver JIT-compiles the PTX to sm_110 |
| `-arch=native` | **sm_110** | — | works, native SASS |
| `-arch=sm_75` | sm_75 | compute_75 | works (PTX JIT) |
| `-gencode arch=compute_75,code=sm_75` (SASS only) | sm_75 | **none** | **`no kernel image is available for execution on the device`** |

So the default is *not* a hard failure but it is a **silent sm_75-shaped binary with a
PTX-JIT tax**, and any build that emits SASS without PTX is a hard failure. This is not
hypothetical: the Infinigen spike hit it and committed the fix —
`src/infinigen-thor` commit `3668454a` *"terrain: target the build GPU's CUDA arch when
compiling terrain kernels"*, whose message says the default target on this box *"is
sm_75, whose cubins fail to load on the GPU ('no kernel image available')"* — and
`thor/patches/blender-v4.2.0-cycles-config-sm110.patch` adds the sm_90/100/110 launch
bounds to Cycles' `config.h`, which upstream 4.2 only served via compute_75 PTX + JIT.

**This generalises to every from-source CUDA extension in the ledger** (§2): xatlas,
torchmcubes/PyMCubes, nvdiffrast, PyTorch3D, flash-attn, Kaolin, spconv,
`custom_rasterizer`, `differentiable_renderer`. **One build rule, applied everywhere:**
every source build on this box passes `-arch=native` (or
`-gencode arch=compute_110,code=sm_110`), and every produced `.so` is verified with
`cuobjdump --list-elf` before it is trusted. Neither report states this rule.

---

### C7 — Published speed and memory figures are datacenter numbers

res-3d §1/§7 and res-cad §1/§4 agree, and both are right. res-3d's §7 table is the
better-formed version: *"TripoSR's 'less than 0.5 seconds' is an NVIDIA A100
measurement… TRELLIS.2's 3 s / 17 s / 60 s ladder is an H100 measurement. No Thor or
Jetson benchmark of any model on this list is published."* res-cad independently reaches
the same conclusion for ACE-Step (*"4-minute track in ~20 s (A100)"*), Stable Audio
(*"free commercial under $1M revenue"*), StableMaterials (*"~4 steps"* latent
consistency), and MoMask (*"fastest of the family"*). Nothing on this box contradicts
either. **Both are right that the scheduler's throughput table must be filled by
measurement.**

---

### C8 — The recipe, not USD, is the source of truth

vision.md's layer 2 ("A project is its recipe… Diffable, branchable, replayable") and
res-cad §8 agree: the recipe is the typed source of truth, USD is a compiled output and
assembly cache, and the flow is one-way (recipe → USD; USD → recipe only for *importing*
external assets, wrapped by a recipe entry carrying the licence). res-cad §8's
reasoning — that USD's LIVRPS/arc semantics are *"hostile to diffing, typing and
branch-by-character workflows"* — is the right reason and is consistent with vision.md's
"Data, never code" rule. **No disagreement; this is settled.**

---

### C9 — "122 GB makes VRAM a non-issue": right about capacity, wrong about contention
and wrong about observability

res-cad §9 opens: *"The constraint on Thor is not VRAM capacity (122 GB unified; nothing
here needs more than ~10 GB) — it is GPU compute-time and weight-swap thrash."* The first
clause is right and the second is right. Two refinements:

**(a) There is no separate GPU memory pool to manage.** Measured: `nvidia-smi
--query-gpu=memory.total,memory.used` returns **`[N/A], [N/A]`** on this Thor, and the
`nvidia-smi` table prints *"Memory-Usage: Not Supported"*. The 122 GB is one unified
pool: `MemTotal: 128766528 kB` (122.8 GiB), and `tegrastats` reports
`RAM 46203/125749MB`. So the scheduler's hot/warm/cold tiers — as designed in *both*
reports — have **no nvidia-smi memory signal to act on**. Eviction must be driven by
`/proc/meminfo` `MemAvailable` plus `tegrastats` RAM, and it must account for the fact
that a model, a Cycles render buffer, the OCCT/CPU lane and the page cache all draw
from the *same* pool. "Nothing here needs more than ~10 GB" is true per model and
misleading in aggregate: the engine plus the model plus render buffers plus page cache
is the real budget.

**(b) The Infinigen spike's own measurement harness has this bug.**
`src/infinigen-thor/thor/run-timed.sh` samples
`nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu` and
parses `MAX_GPU_MEM` from it. Because `memory.used` is `[N/A]` on this box, that awk
expression (`gsub(" MiB","",$2); if ($2+0>m) m=$2+0`) yields **0 for every run** — the
spike's summary lines will report `maxGPUmem=0MiB` regardless of actual usage. Its
CPU/RAM sampling via `tegrastats` is fine. Worth fixing before the SPIKE.md numbers are
published, and worth telling the split report, whose power/placement plan depends on
these counters.

---

## 2. The dependency ledger (single, deduplicated)

One row per library across both reports plus the Infinigen spike. **aarch64** =
Linux aarch64 wheel exists on PyPI? **CUDA 13** = works against this box's CUDA 13.2.86
driver/13.2 toolkit? **sm_110** = kernels/codegen actually target compute 11.0?

**Legend:** ✅ wheel, verified · ⚙️ builds from source (with the rule from §C6) ·
🧱 blocked / not usable as-is · ➖ not applicable (no CUDA involvement)

### 2.1 The runtime and the world engine

| Dependency | Needed by | aarch64 | CUDA 13 | sm_110 | Verdict |
|---|---|---|---|---|---|
| `torch` **2.15.0** (PyPI, cp312) | every generative env | ✅ 483.7 MB | ✅ `cuda-toolkit==13.2.2` | ✅ **535 sm_110 images** | **the base of the whole generative stack** |
| `torch` **2.6.0** (PyPI, cp312) | TRELLIS.2 *reference* path only | ✅ 95.6 MB, **no CUDA lib** | 🧱 CPU-only (deps x86_64-gated) | n/a | 🧱 do not use |
| `torch` 2.9–2.11 (Jetson AI Lab SBSA cu130/cu132) | fallback for torch-pinned stacks | ✅ | ✅ | ✅ (index is CUDA-13-native) | ⚙️ fallback only |
| `torchvision`, `torchaudio` | ComfyUI; ACE-Step | ✅ / ✅ py3-none | ✅ | via torch | ✅ (`torchaudio` 2.11.1 pins `torch>=2.11`) |
| `triton` 3.9.0 | torch 2.15 dep; 3DTopia-XL pins 2.1.0 | ✅ cp311–cp315 | ✅ (3.9 is the cu13 line) | ✅ via torch | ✅ — but **3DTopia-XL's `triton==2.1.0` pin conflicts with CUDA 13** (res-3d §4.6) |
| `numpy` 2.5.4 | everywhere | ✅ cp312–cp315 | ➖ | ➖ | ✅ (Infinigen caps `numpy>=1.25,<2` → needs **numpy 1.x**, a separate env) |
| `scipy` 1.18.1 | Infinigen (`>=1.10`), trimesh collision | ✅ cp312–cp315 | ➖ | ➖ | ✅ for 3.12; **3.11 needs an older scipy** (`scipy>=1.18` requires ≥3.12) |
| `pandas`, `matplotlib`, `shapely`, `pillow`, `OpenEXR`, `rtree` | Infinigen | ✅ cp310–cp314 | ➖ | ➖ | ✅ |
| `opencv-python`, `imageio` | Infinigen | ✅ (abi3) / pure | ➖ | ➖ | ✅ |
| `procfunc` 0.37.0 | Infinigen | ✅ pure | ➖ | ➖ | ⚙️ **`requires-python >=3.11,<3.12`** → forces the 3.11 env |
| `python-fcl` 0.7.0.11 | Infinigen (trimesh) | ✅ cp39–cp314 | ➖ | ➖ | ✅ |
| `cvdpack` 0.7.0 | Infinigen (ground truth) | ✅ pure | ➖ | ➖ | ✅ |
| `landlab` 2.11.0 | Infinigen `[terrain]` | ✅ cp311–cp314 | ➖ | ➖ | ✅ (Infinigen pins `landlab==2.6.0`) |
| `pyrender` | Infinigen `[terrain]` | ✅ pure | ➖ | ➖ | ✅ |
| **`bpy` 4.2.0** | Infinigen, Blender 4.2 | 🧱 **no Linux aarch64 wheel at any version** (PyPI latest 5.2.3 ships only macOS/Windows arm64) | ⚙️ source build, Cycles CUDA `sm_110` | ⚙️ **needs the local `config.h` patch** | 🧱 **must be built from source** — this is the Infinigen spike's whole subject |
| Blender 4.2 cycles CUDA arch | final renders | ➖ | ⚙️ | ⚙️ `CYCLES_CUDA_BINARIES_ARCH=sm_110` + `config.h` patch (sm_90/100/110 launch bounds) | ⚙️ **permanent local fork of Blender** (R10) |
| Infinigen terrain CUDA kernels | terrain | ➖ | ⚙️ | ⚙️ **already solved**: commit `3668454a` → `-arch=native`; 21 CUDA `.so` + 27 CPU `.so` compiled | ⚙️ but rule now applies to every other extension |
| `cpython` 3.11.13 | the world engine | ⚙️ built from source on the box (`--enable-shared`, rpath) | ➖ | ➖ | ⚙️ done by the spike |

### 2.2 3D generation

| Dependency | Needed by | aarch64 | CUDA 13 | sm_110 | Verdict |
|---|---|---|---|---|---|
| `transformers` 5.22.1 | TRELLIS.2 (DINOv3), TripoSR, SDXL, MoMask, ACE-Step | ✅ pure (≥3.11) | ➖ | ➖ | ✅ |
| `diffusers` 0.42.1 | StableMaterials/SDXL, ACE-Step, stable-audio-tools | ✅ pure (≥3.11) | ➖ | ➖ | ✅ |
| `accelerate`, `safetensors` (cp310-abi3 ✅), `huggingface-hub`, `einops`, `timm`, `omegaconf`, `hydra-core`, `protobuf` | diffusers family | ✅ | ➖ | ➖ | ✅ |
| `xatlas` 0.0.11 | TripoSR, Hunyuan3D | 🧱 **no Linux aarch64 wheel** | ➖ | ➖ | ⚙️ C++ build (68 wheels exist, none aarch64) |
| `torchmcubes` / `PyMCubes` 0.1.6 | TripoSR, InstantMesh, 3DTopia-XL | 🧱 no aarch64 | ⚙️ small CUDA build | ⚙️ `-arch=native` | ⚙️ |
| `onnxruntime` 1.31.1 | TripoSR/rembg | ✅ cp311–cp314 | ➖ | ➖ | ✅ wheel exists — but see R6 (native abort on Tegra CPU) |
| `rembg` 2.0.86 | modly | ✅ pure (≥3.11) | ➖ | ➖ | ✅ wheel; crash risk is in the ONNX runtime, not the wheel |
| `trimesh` 5.2.0, `pymeshlab` 2025.7.post1 | mesh cleanup, modly | ✅ / ✅ cp310–cp314 | ➖ | ➖ | ✅ |
| `open3d` 0.20.0 | TripoSR path | ✅ cp310–cp314 | ➖ | ➖ | ✅ (res-3d's "open3d 0.18 has no cp312" is now stale) |
| `pynanoinstantmeshes`, `gpytoolbox` | SF3D/SPAR3D | 🧱 no aarch64 | ⚙️ | ➖ | ⚙️ two source builds (res-3d §4.5) |
| `flash-attn` | TRELLIS v1, InstantMesh | 🧱 **sdist only, 1 file, 0 wheels** | ⚙️ multi-hour | 🧱 prebuilt wheels lack sm_110 SASS | 🧱 **avoid entirely** |
| `xformers` 0.0.35 | TRELLIS v1 | 🧱 no aarch64 wheel | ⚙️ | ⚙️ | 🧱 avoid; use torch SDPA |
| `spconv-cu120`, `kaolin` 0.1 | TRELLIS v1 | 🧱 none / sdist | ⚙️ | ⚙️ | 🧱 avoid |
| `nvdiffrast` | 3DTopia-XL, InstantMesh, TRELLIS.2 *reference* | 🧱 not on PyPI at all (git only) | ⚙️ | ⚙️ | ⚙️ and ⚠️ NVIDIA Source Code Licence, 1-Way Commercial (commercial OK) |
| `nvdiffrec` | TRELLIS.2 *reference* only | 🧱 git only | ⚙️ | ⚙️ | 🧱 **non-commercial licence** → never in the shipped path |
| `pytorch3d` 0.7.4 | Material Anything, motion rendering | 🧱 no aarch64 wheel | ⚙️ | ⚙️ | ⚙️ avoidable (motion rendering only) |
| `cupy-cuda12x` / **`cupy-cuda13x`** 14.2.0 | Hunyuan3D, some 3D paths | ✅ cp310–cp314 **for both** | ✅ **use `cupy-cuda13x`** | ⚙️ verify SASS | ✅ resolves res-3d's "CUDA 12 runtime on a 13 driver" worry |
| `bitsandbytes` 0.50.2 | InstantMesh | ✅ 1 aarch64 py3 wheel | ➖ | ⚙️ sm_110 coverage unverified | ⚙️ |
| `smplx` 0.1.28, `chumpy` 0.70 (sdist), `open-clip-torch`, `blobfile` | MoMask / MDM | ✅ pure except chumpy (sdist) | ➖ | ➖ | ⚙️ **rendering-only** — avoid (avoids PyTorch3D too) |
| `pysdf` 0.1.9, `meshio`, `plyfile`, `mapbox-earcut` | mesh IO | ✅ / ✅ / ✅ / ✅ 18 aarch64 wheels | ➖ | ➖ | ✅ |

### 2.3 Textures, audio, CAD, USD

| Dependency | Needed by | aarch64 | CUDA 13 | sm_110 | Verdict |
|---|---|---|---|---|---|
| `librosa` 1.0.0, `soundfile` 0.14.0 | audio post | ✅ pure / ✅ aarch64 | ➖ | ➖ | ✅ (librosa 1.0.0 requires ≥3.12) |
| `encodec` 0.1.1 (sdist), `x-transformers`, `torchac`, `julius`, `rotary-embedding-torch`, `sentencepiece`, `tokenizers` (cp310-abi3 ✅) | stable-audio-tools | ✅ | ➖ | ➖ | ✅ |
| `cadquery-ocp` / `cadquery-ocp-novtk` 8.0.1.1.0 | CadQuery, build123d | ✅ `manylinux_2_28_aarch64` cp311–cp314 (59 MB, downloaded) | ➖ | ➖ | ✅ |
| `cadquery` 2.8.0, `build123d` 0.13.0 | CAD | ✅ pure wheels | ➖ | ➖ | ✅ (build123d swaps `lib3mf`→`py-lib3mf` on `linux/aarch64`) |
| `nlopt`, `casadi`, `ezdxf`, `py-lib3mf` 2.5.0, `ocpsvg`, `ocp_gordon`, `multimethod`, `runtype` | CAD | ✅ | ➖ | ➖ | ✅ |
| `usd-core` 26.11 (Pixar) | assembly/interchange | ✅ `manylinux_2_28_aarch64` cp311–cp314 (27 MB, downloaded) | ➖ | ➖ | ✅ (TOST-1.0; no Hydra/GPU rendering) |
| `simready-foundation` | schema reference | ✅ (content) | ➖ | ➖ | ✅ (Apache-2.0 schema, not an asset library) |

### 2.4 The ledger's summary

**Nothing in the adopted/spiked set is blocked outright.** The only hard blocks are
`flash-attn`, `xformers`, `spconv-cu120`, `kaolin`, `nvdiffrec` and `bpy` (no wheel) —
and every one of them belongs to a path the reports already reject (TRELLIS v1,
InstantMesh, TRELLIS.2's reference pipeline) **except `bpy`, which is unavoidable and is
exactly what the Infinigen spike is solving.** The remaining "build from source" items
are: `bpy`/Blender-Cycles (huge, in flight), `xatlas`, `torchmcubes`/`PyMCubes`,
`nvdiffrast`, `pytorch3d`, `custom_rasterizer` + `differentiable_renderer`,
`pynanoinstantmeshes` + `gpytoolbox`, and `chumpy`/`pysdf` (both avoidable).

**One rule covers half of them: build with `-arch=native` and verify with `cuobjdump`
(§C6).** One second rule covers the rest: **never let an environment silently fall back
to a CPU-only torch** — assert `torch.cuda.is_available()` and the device's compute
capability at install time, because the failure is a quiet 10× slowdown, not a crash.

---

## 3. The licence register (single, for code and weights)

Scope: what each permits **for shipped assets** (commercial / research-only /
attribution). "Shipped asset" = a mesh, texture, motion clip, audio file or CAD part
that ships in a game or is delivered to a customer.

| Component | Code licence | Weights licence | Commercial use? | Obligations / limits | Status |
|---|---|---|---|---|---|
| **Infinigen** | BSD-3-Clause (`pyproject.toml`) | n/a (procedural) | ✅ yes | retain notice | ✅ **clean**; code in `src/infinigen/infinigen_gpl` is GPL — **don't link it** |
| **Blender 4.2 (bpy)** | GPL-2.0-or-later | n/a | ✅ as a separate process | do not link into a proprietary app; keep the bpy module a separate process | ⚠️ process boundary is mandatory |
| `usd-core` / OpenUSD | TOST-1.0 (Apache-class, §6 differs) | n/a | ✅ yes | retain notice | ✅ |
| `cadquery`, `build123d` | Apache-2.0 | n/a | ✅ yes | NOTICE | ✅ |
| `cadquery-ocp` / OCCT | Apache-2.0 wheels; OCCT LGPL-2.1-with-exception | n/a | ✅ yes | retain notices | ✅ |
| ComfyUI | GPL-3.0 | n/a | ⚠️ as a **separate service** | cannot be linked into a proprietary product | ⚠️ **host it as a service** — another reason for the ComfyUI/modly split |
| TRELLIS.2 (ComfyUI native) | MIT | MIT, ungated (verified) | ✅ yes | DINOv3 encoder terms travel with it | ✅ **cleanest PBR path** |
| DINOv3 encoder | Meta licence | `other`, gated `manual` (verified) | ✅ yes, with **end-use** limits | attribution; no weapons/espionage; no reverse engineering | ✅ non-commercial is **not** the issue here — end-use is |
| Pixal3D | MIT | MIT, **`extra_gated_eu_disallowed: true`** (verified) | ✅ outside the EU | distribution constraint — record per asset | ⚠️ |
| TripoSR | MIT | MIT, ungated (verified `stabilityai/TripoSR`) | ✅ yes | none | ✅ |
| TripoSG | MIT (extension) | MIT, ungated (verified `VAST-AI/TripoSG`) | ✅ yes | none | ✅ |
| **Aero-Ex/Trellis2-GGUF** (modly's TRELLIS.2 path) | — | **none declared on the HF card** | ⚠️ **unknown** | — | 🧱 **pin the MIT terms in writing before use** (same class as res-3d's TexGaussian) |
| 3DTopia-XL | Apache-2.0 | Apache-2.0 (verified) | ✅ yes | Objaverse-derived corpus provenance | ✅ |
| SF3D / SPAR3D | Stability AI Community Licence | `other`, gated `auto` (verified) | ⚠️ **registration required**; >US$1M revenue needs enterprise | keep the "Notice" file; display "Powered by Stability AI"; **outputs remain ours** | ⚠️ register early (lead time) |
| Material Anything | MIT | Apache-2.0 (verified) | ✅ yes | none | ✅ (blocked on PyTorch3D) |
| Hunyuan3D 2.1 / 2-mini / Paint | Tencent Hunyuan 3D Community | `other`, **`extra_gated_eu_disallowed: true`** (verified) | ⚠️ **not applicable in EU/UK/South Korea**; output use restricted to the Territory; >1M MAU needs a separate licence | Notice file on distribution | ⚠️ legal review; keep internal-only |
| `nvdiffrast` | NVIDIA Source Code Licence, **1-Way Commercial** | n/a | ✅ yes | — | ⚙️ build-time only |
| `nvdiffrec` | NVIDIA, *"only may be used or intended for use non-commercially"* | n/a | 🧱 **no** | — | 🧱 never in a shipped path |
| StableMaterials | — | **OpenRAIL** (verified) | ✅ yes, under RAIL restrictions | use restrictions | ✅ |
| SDXL base | OpenRAIL++-M | OpenRAIL++-M | ✅ yes, with restrictions | use restrictions | ✅ |
| FLUX.1-dev | — | **non-commercial** | 🧱 no | — | 🧱 skip |
| FLUX.1-schnell | — | Apache-2.0 | ✅ yes | — | ✅ |
| Poly Haven / ambientCG | — | **CC0** | ✅ yes, zero bookkeeping | none | ✅ **adopt now as the curated baseline** |
| MoMask / MDM | MIT | no stated weights licence | ⚠️ **the weights are fine; the DATA is not** | — | ⚠️ |
| HumanML3D ← **AMASS** data | — | research-use restrictions | ⚠️ **restrictions flow into shipped clips** | — | ⚠️ **the one genuinely unresolved corner** |
| SMPL / SMPL-X | research-only | research-only | 🧱 for shipped use | — | 🧱 avoid (skip PyTorch3D and `smplx` entirely) |
| MotionGPT | MIT | HF card says only `cc` | ⚠️ ambiguous | — | 🧱 skip |
| ACE-Step | Apache-2.0 | Apache-2.0 (verified) | ✅ yes | none | ✅ |
| Stable Audio Open 1.0 / Small | MIT (stable-audio-tools) | Stability Community (`other`, gated, verified) | ⚠️ commercial **< $1M revenue**, enterprise above | register | ⚠️ |
| MusicGen / AudioCraft | audiocraft MIT but PyPI sdist pins `torch==2.1.0`, `xformers<0.0.23` | **CC-BY-NC 4.0** (verified) | 🧱 **no** for shipped assets | — | 🧱 skip; `transformers`' MusicGen is the prototyping path |
| CHORD | Ubisoft ML Licence, **Research-Only Copyleft** | same | 🧱 **no** | copyleft | 🧱 skip |
| TexGaussian | **no LICENSE file** | card says apache-2.0 | ⚠️ ambiguous | — | 🧱 skip until pinned |
| Nova3D / nova3d-mcp | MIT (archived 2026-06-28) | n/a (hosted service) | ⚠️ **output terms not published** | — | 🧱 skip; steal the interface pattern |
| SimReady foundation | Apache-2.0 | third-party robots keep their own notices | ✅ | per-asset check for Omniverse-sourced content | ✅ schema only |

**The register's three rules, restated from vision.md's "Licences are a checked list":**
1. **Weights licences gate shipped assets, not just code.** Four entries above are clean
   code with unusable weights (MusicGen, CHORD, MotionGPT, TexGaussian) and one is the
   reverse (the MIT ComfyUI host carrying a GPL codebase and a licence-unknown GGUF
   repack).
2. **Region flags are real.** `extra_gated_eu_disallowed: true` is present on Pixal3D
   and on Hunyuan3D-2-mini — both verified from the HF README frontmatter, not from the
   reports.
3. **The scheduler stamps the licence** (both reports agree) — so the model registry,
   not the job, must hold this table, and it must be per *weights revision*, since the
   same repo can be re-licensed.

---

## 4. The environment plan

### 4.1 How many environments, and why

**Four environments, plus one optional.** Not "one per model family" (res-3d §6) and not
"one per interpreter" — the real dividing lines are (a) **interpreter version**,
(b) **native ABI** (bpy's Python module, OCCT bindings, CUDA extensions), and
(c) **process isolation** for crash-prone native code. Every generator the reports adopt
shares one torch ABI (2.15 aarch64/CUDA 13.2/sm_110) and one interpreter (3.12), so they
do **not** each need their own environment — they need their own **process**.

| # | Environment | Python | Contents | GPU? | Why it is separate |
|---|---|---|---|---|---|
| **E1** | **world engine** | **3.11** | locally built `bpy` 4.2 wheel, Infinigen editable + terrain CUDA `.so`, `landlab`, `procfunc` | ✅ Cycles CUDA `sm_110` | bpy 4.2 embeds exactly Python 3.11; `procfunc` is `<3.12`; `numpy<2`; a different ABI from everything else. **Nothing else may enter this env.** |
| **E2** | **generative / torch** | 3.12 | `torch` 2.15.0 aarch64 CUDA 13.2, `diffusers`, `transformers`, `accelerate`, ComfyUI (TRELLIS.2 + Pixal3D), MoMask, ACE-Step, stable-audio-tools | ✅ sm_110 | one torch ABI for every generative model; ComfyUI's own tree targets 3.10 but runs on 3.12 |
| **E3** | **prop service** | 3.12 | modly FastAPI backend + TripoSG / Trellis2-GGUF extensions, `rembg`, `onnxruntime`, `trimesh`, `pymeshlab` | ✅ | **isolated because `rembg`/ONNX Runtime aborts natively on Tegra CPU** (res-cad §2) — a native crash in a shared env takes the scheduler's process with it. Also keeps `numpy`/`onnxruntime` version skew out of E2 |
| **E4** | **CAD + USD (pure CPU)** | 3.12 | `build123d`, `CadQuery`, `cadquery-ocp`, `usd-core`, `py-lib3mf`, `ezdxf`, `nlopt`, `casadi` | ➖ **no torch, no CUDA context** | keeps the deterministic CAD lane out of the torch ABI entirely; a CAD batch then costs **zero** GPU memory and cannot perturb the generative lane's residency. Carries Stable Audio Open **Small** (Arm-CPU) as its audio-SFX occupant |
| E5 *(optional)* | CPU audio variant | 3.12 | `stable-audio-tools` + `torchaudio` | ➖ | only if SAOS Small's 44.1 kHz decode interferes with the CAD lane's latency |

**Why not one environment:** E1 is forced (3.11 + bpy ABI + `numpy<2`); E2/E3 differ in
native-extension risk; E4 must be torch-free to keep the CAD lane deterministic and
free.

**Why not one per model family (res-3d §6's rule):** the stated reason — *"torch
versions, compiled extensions and licence conditions differ per family"* — is only true
for the **rejected** families (TRELLIS v1's `kaolin`/`spconv`, Hunyuan3D's pins,
Material Anything's PyTorch3D). For everything the reports actually adopt, torch 2.15 +
pure-Python wheels unify cleanly, and the HF registry shows the licence differences are
a **registry** concern, not an environment concern. The rule that actually matters:

> **Environments are the compatibility unit; residency is the process unit.**
> Hot/warm/cold eviction acts on *processes*, because a single Python process cannot
> unload one model and load another without tearing down its CUDA context.

So: one venv (E2) can serve several models, but the scheduler must run each model in
its **own process** so that "evict" = "exit the process" and the CUDA context and its
memory are genuinely returned.

### 4.2 How the scheduler moves models in and out of the 122 GB

**The pool is unified, so there is one budget, not two.** `MemTotal: 128766528 kB`
(122.8 GiB) serves CPU RAM *and* GPU memory; `nvidia-smi` reports `memory.total` and
`memory.used` as `[N/A]` and the table as "Not Supported" (§C9). The scheduler therefore
cannot ask the GPU how much is left.

**The signals that do work:**
- `/proc/meminfo` → `MemAvailable` (measured 121,653,696 kB idle).
- `/usr/bin/tegrastats --interval 1000` → `RAM 46203/125749MB`, per-core clock/load,
  `VDD_GPU`, `tj@`, and the SoC/GPU power rails. This is also what `thor/run-timed.sh`
  already uses for CPU/RAM — good — and what it should use *instead of* nvidia-smi for
  memory (bad: see §C9).
- `nvidia-smi` remains useful for `utilization.gpu`, `power.draw`, `temperature.gpu`.

**Residency model (adopting both reports' hot/warm/cold, with the arithmetic fixed):**

| Tier | Contents | Budget | Rule |
|---|---|---|---|
| **Hot** | companion/planner LLM + critic (vision model) | measured at build time; expect single-digit GB | never evicted; latency-critical, used between every batch |
| **Warm** | exactly **one** generative model per process | measured peak per model (from the spikes), not the published 6–29 GB figures | loaded once per night-segment, drained after; **batch all of that model's prompts before moving on** |
| **Cold** | pinned weights revisions on the external NVMe SSD (1.9 TB) and/or the 340 GB free on `/` | — | never resident |

**Eviction procedure.** Because the pool is unified, "evicting" a model means freeing
host RAM that the model pinned as GPU-accessible. The scheduler should:
1. Keep a per-model **peak RSS** figure measured on this box (`/usr/bin/time -v` gives
   `Maximum resident set size`; `run-timed.sh` already captures it).
2. Before starting a warm model, require `MemAvailable > (model peak + render reserve +
   page-cache floor)`; if not, drain the current warm model first (exit its process),
   then wait for the kernel to release.
3. **Reserve a render window.** Both reports treat the CPU lane and the GPU lane as
   independent (res-cad §9's lane layout). They are not: a Cycles GPU render and a
   4B diffusion model draw from the same 122 GB. The night's plan needs the final-render
   stage to be scheduled *against* the model lane, not merely alongside it.
4. Batch by model, in dependency order: image-to-3D → textures → motion → music, with
   critic checks interleaved *after* each batch (res-cad §9's lane 3 — agreed by both).
5. Run CAD, USD assembly, mesh cleanup and SAOS Small on the CPU lane continuously; they
   cost no GPU residency and should never be blocked by the GPU lane.

**Storage for cold weights:** `/` has 340 GB free and the 1.9 TB external SSD
(`/media/caseydigennaro/TOSHIBA EXT`) is the established home for large trees (the
Infinigen spike already uses it via the space-free `.ext-thor` symlink). Cold weights
belong on the external SSD; keep a manifest of pinned revisions on `/`.

**One correction to `thor/run-timed.sh`** (it belongs to the Infinigen seat, but the
scheduler inherits it): replace the `nvidia-smi memory.used` sampling with
`tegrastats` RAM, or the spike's published peak-memory numbers will read `maxGPUmem=0MiB`.

---

## 5. Merged spike order — the first 5

Merged from res-3d §8, res-cad §10, vision.md's Phases, and the Infinigen spike already
in flight. Ordered by dependency first (what unblocks what), then by cost of regret.

| # | Spike | Source | What it proves | **Pass / fail check** |
|---|---|---|---|---|
| **1** | **bpy 4.2 on aarch64 + Cycles CUDA on sm_110** (the Infinigen spike) | vision.md Phase 1; `~/src/infinigen-thor` | That the world engine can run and render on the Thor at all | **PASS** if: the `bpy` 4.2 wheel builds and imports; `cuobjdump --list-elf` on the Cycles CUDA binaries shows **sm_110** (not sm_75-only); Hello Room and Hello World both complete; a CPU render and a GPU render of the same frame exist as PNGs with **both timings** and the box's state recorded. **FAIL** if any Cycles kernel lacks sm_110 SASS or the GPU render is slower than CPU |
| **2** | **TRELLIS.2 native on ComfyUI with stock PyPI torch 2.15** | res-3d §8 (spike first) | Whether the whole "PyPI torch just works on sm_110" claim holds end-to-end, and whether the first PBR path is real | **PASS** if: `torch.cuda.is_available()` is true and `torch.cuda.get_device_capability() == (11, 0)`; TRELLIS.2 loads from the ComfyUI native path and emits a GLB with albedo + metallic-roughness (+ normal/AO); wall-clock recorded at 512³ and 1024³; **no** flash-attn/nvdiffrast/nvdiffrec/xformers in the install; peak `MemAvailable` dip recorded. **FAIL** if torch silently resolves to the CPU-only build, or if any compiled extension is needed |
| **3** | **USD backbone: recipe → layered USD + build123d STEP→GLB** | res-cad §10 (backbone first) | The schema every later spike stamps into — "Nothing else lands without provenance + licence fields" | **PASS** if: `usd-core` imports on aarch64; a build123d part exports STEP (master) and GLB (with material UVs) into a layered USD stage with one layer per concern (geometry refs / materials / physics / semantics); provenance (prompt, model, weights revision, seed, licence) round-trips in `customData`; emission is deterministic (re-emit → identical bytes, sorted prims, no timestamps); `build123d`/`CadQuery` use **zero** GPU memory. **FAIL** if USD becomes the source of truth or the emission is non-deterministic |
| **4** | **modly headless FastAPI + TripoSG, mesh-only** | res-cad §2/§10 | That an HTTP-driven prop service with a first-class `seed` works on the Thor, and that the scheduler's provenance record survives a real call | **PASS** if: `POST` an image + params + seed to the backend and get a GLB back with the seed echoed; the provenance record (model id, weights repo + revision, seed, wall-time, licence) is written **by the registry, not the job**; `rembg`/ONNX Runtime does **not** abort on Tegra CPU (or the documented NumPy/SciPy workaround is in place); peak RSS measured. **FAIL** on a native abort, or if the licence is not stamped |
| **5** | **ACE-Step (music) + StableMaterials/SDXL (PBR textures)** | res-cad §3/§5 | Two independent, permissive, extension-free licences that fill the texture and ambience roles | **PASS** if: ACE-Step generates a ≥60 s track on the Thor with a recorded wall-clock (the published ~20 s is an **A100** number, so the Thor number will be far worse — that is the point of measuring it); SDXL + StableMaterials produce a **tileable** SVBRDF set (albedo/normal/roughness/metallic) at 1024² from a seed, with the resolution and sampler settings recorded; both licence strings are stamped into the asset record (Apache-2.0 and OpenRAIL respectively). **FAIL** if the tileability claim does not hold, or if either path turns out to need a compiled extension |

**Deliberately not in the first 5, with reasons:**

- **MoMask** (res-cad §4 "spike first") — **deferred, not skipped.** The code is MIT and
  it is the fastest text-to-motion candidate, but the HumanML3D←AMASS data licence is
  unresolved (res-cad's own §4), so a clip produced in a spike cannot legally ship. Run it
  as a *technical* spike once the CAD/asset-record spine from spike 3 exists, so the
  data-provenance flag has somewhere to live. Resolve the data licence in parallel.
- **TripoSR** (res-3d §8 "adopt in parallel") — res-cad's TripoSG is strictly better
  (MIT weights, ~8 GB, first-class seed, mesh-only, no xatlas/torchmcubes builds) and
  covers the same "cheap licence-clean prop baseline and plumbing exercise" role.
  **Fold TripoSR's purpose into spike 4** rather than running both.
- **SF3D / SPAR3D** (res-3d §8 "spike second") — two source builds plus a Stability
  registration with lead time. Start the **registration now** (it costs no engineering
  time and gates a later option), but do not spend spike time yet.
- **Material Anything** (PyTorch3D port), **3DTopia-XL** (`triton==2.1.0` conflicts with
  CUDA 13), **Hunyuan3D** (licence territory), **Pixal3D** (evaluate *inside* spike 2's
  ComfyUI env — one extra weights download, not a separate spike).

---

## 6. Open technical risks, ranked

| # | Risk | Evidence | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| **R1** | **Every from-source CUDA extension defaults to the wrong architecture on this box.** `nvcc` 13.2.86's default target is **sm_75** SASS + compute_75 PTX: it works only via driver PTX JIT, and a SASS-only build fails outright with *"no kernel image is available for execution on the device"* | measured (§C6); the Infinigen spike already hit it and committed the fix (`3668454a`, `-arch=native`) and a Cycles `config.h` patch for sm_90/100/110 launch bounds | **certain** for every new extension (xatlas, torchmcubes, nvdiffrast, PyTorch3D, `custom_rasterizer`, `differentiable_renderer`, Kaolin, spconv, flash-attn) | **blocker** for the affected model | One build rule for the whole port: every source build passes `-arch=native` (or `-gencode arch=compute_110,code=sm_110`), and every produced `.so` is checked with `cuobjdump --list-elf` before it is trusted. Bake this into the build scripts, not into each developer's memory |
| **R2** | **Silent CPU fallback.** The failure mode of a too-old torch is not an error, it is a 10–50× slowdown | torch 2.6.0 aarch64 wheel contains **no** `libtorch_cuda.so` and its nvidia deps are `platform_machine == "x86_64"`-gated (§C1) | medium — triggered by any upstream `torch==` pin (TRELLIS.2 pins 2.6.0; `audiocraft` pins 2.1.0) | high — a night of jobs would run at CPU speed and still "succeed" | Assert at environment build time: `torch.cuda.is_available()` is true, `torch.cuda.get_device_capability() == (11, 0)`, and `torch.version.cuda` starts with `"13"`. Fail the install loudly, never at run time |
| **R3** | **Unified-memory contention and no memory observability.** `nvidia-smi` reports `memory.total`/`memory.used` as `[N/A]`; GPU memory is the same pool as CPU RAM. The scheduler's hot/warm/cold design in *both* reports has no GPU-memory signal, and `thor/run-timed.sh` will record `maxGPUmem=0MiB` on every run | measured (§C9) | **certain** | high — thrash or OOM with no diagnostic | Drive eviction from `/proc/meminfo` `MemAvailable` + `tegrastats` RAM; fix `run-timed.sh` to sample `tegrastats` for memory; schedule the final-render stage *against* the model lane, not alongside it |
| **R4** | **Three Python versions, one of them forced.** 3.11 (Infinigen/bpy/`procfunc`), 3.12 (everything generative/CAD), 3.10 (TRELLIS.2's rejected reference path) | measured (§C2); `scipy>=1.18` needs ≥3.12, `procfunc` needs <3.12 | **certain** | medium — wasted effort, env drift | Fix the matrix now (§4.1): E1 = 3.11 and nothing else; everything else = 3.12. Record it in the shared brief so round-3 briefs do not repeat "Python 3.12" |
| **R5** | **Licence contamination via the convenient path.** modly's TRELLIS.2 extension pulls `Aero-Ex/Trellis2-GGUF`, which declares **no licence**; modly's texture path requires the Hunyuan3D Paint extension, whose weights are the Tencent Community Licence with `extra_gated_eu_disallowed: true`, plus two CUDA source builds | verified against the HF registry (§C5, §3) | **high** if the fast path is taken | **high** — a shipped-asset licence defect, found late | Keep the GGUF repack out of the registry until its MIT terms are pinned in writing; treat modly's texture path as closed (use StableMaterials/SDXL, already in spike 5); make the registry reject any weights repo with no declared licence |
| **R6** | **`rembg` / ONNX Runtime native abort on Tegra CPU.** `onnxruntime` 1.31.1 *does* have aarch64 cp311–cp314 wheels, so the wheel is present — the crash is in the native code, and a present wheel does not fix it | res-cad §2 (from modly's own Jetson guide, AGX Orin / JetPack 6.2 / sm_87) | **high** on this box (same CPU lane, different Tegra generation) | medium — the prop service (spike 4) is blocked; mesh-only may still work if alpha is pre-cut | Put the rembg call behind the documented NumPy/SciPy patch or pre-cut alpha on the GPU side; if it still aborts, run TripoSG/TRELLIS2-GGUF without rembg |
| **R7** | **Zero Thor performance numbers for every generative model.** Every speed and memory figure in both reports is an A100 / H100 / 4090 / Orin number | res-3d §1, §7; res-cad §1, §4, §5 — and both correctly refuse to schedule against them | **certain** | medium — the entire night-batch plan and the scheduler's throughput table are unvalidated | Spikes 2, 4 and 5 exist to fill this table. Record each measurement **next to** the model's provenance entry, with the box's state beside it, so the next person does not re-derive it |
| **R8** | **Motion data licence blocks shipped character motion.** Code MIT, but HumanML3D←AMASS carries research-use restrictions that flow into shipped clips; SMPL/SMPL-X are research-only | res-cad §4; `smplx`/`chumpy`/`PyTorch3D` all sit in the render path we intend to skip | medium | medium — one role of the pipeline is legally blocked | Either licence-review AMASS, or keep motion on mocap/proc-animated clips. Until then, stamp every clip with the data-provenance flag (and make sure a place exists to stamp it → spike 3) |
| **R9** | **The ComfyUI host has never run on this box.** The local clone (v0.42.0, commit `fb3befd`) is a working tree under `~/image-studio`; `pyproject.toml` pins `master.py-version = "3.10"`; the fp8 (`--fp8_e4m3fn-unet`) and `--use-sage-attention` flags are unvalidated on sm_110 | inspection of `~/image-studio/ComfyUI` | high | medium — spike 2's whole plan depends on it | Spike 2 *is* the test. Start with the SDPA path and stock fp16; treat fp8 and sage attention as opt-in extras until measured |
| **R10** | **The Thor's final renders depend on a locally patched Blender.** Blender 4.2 predates sm_110 and serves 9.x/10.x via compute_75 PTX + JIT; the spike patches `intern/cycles/kernel/device/cuda/config.h` to add the sm_90/100/110 launch bounds and builds with `CYCLES_CUDA_BINARIES_ARCH=sm_110` | `thor/patches/blender-v4.2.0-cycles-config-sm110.patch`; `thor/build-bpy.sh` stages 4–5 | **certain** — the patch is already applied to the build tree | medium — a permanent maintenance fork of an upstream project | Keep the patch set in `thor/patches/` and committed (two of the three are currently **untracked**: `ffmpeg61-anim-movie`, `ffmpeg61-av-input-buffer`); treat the fork as a permanent cost of the port, and re-check it on every Blender bump |
| **R11** | **Infinigen's install matrix has no Linux ARM64 column and its CUDA terrain is Linux-x86-only.** The port is not a wheel install; it is a maintained fork | `~/src/infinigen-thor/BRIEF.md`; commit `3668454a` | **certain** | high — the world engine is the product | Phase 2 of the Infinigen spike (not yet written) should state what is ported, what is rewritten, and where Thor-native changes pay most |
| **R12** | **OpenUSD has no GPU rendering** (`usd-core` is the Pixar CPU build; no Hydra). The "assembly cache" story is therefore CPU-only | res-cad §6 (the report states this caveat itself) | certain | low | None needed — rendering stays in Cycles and on the ProArt. Just do not let a later design assume USD can render |

### 6.1 Risks this review adds that neither report raises

- **R13 — the GGUF repack has no licence** (see R5). Neither report names
  `Aero-Ex/Trellis2-GGUF`, yet it is the easiest TRELLIS.2 path in the recommended
  prop service.
- **R14 — the world engine needs Python 3.11, which no round-1 brief stated**
  (see R4). Both briefs said 3.12; that error is now in two reports' worth of
  downstream reasoning.
- **R15 — `nvidia-smi` cannot measure GPU memory on this box** (see R3). Every future
  report that asserts a memory figure must say *how* it was measured.
- **R16 — the Infinigen spike's own harness under-reports memory** (see R3): its
  `maxGPUmem` metric is structurally 0 on this hardware.

---

## Appendix — what was run, for reproduction

Read-only. No installs into any shared environment; all downloads into `/tmp`.

**Machine state**
```
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv
  → NVIDIA Thor, 595.78, [N/A], 11.0
nvidia-smi --query-gpu=memory.total,memory.used,utilization.gpu --format=csv,noheader
  → [N/A], [N/A], 0 %
python3 --version → Python 3.12.3          nproc → 14
free -g → 122 total      /proc/meminfo → MemTotal: 128766528 kB
/usr/local/cuda/bin/nvcc --version → release 13.2, V13.2.86
tegrastats → RAM 46203/125749MB, VDD_GPU 2360mW
```

**Wheel checks** — `pip download --only-binary=:all: --no-deps` into `/tmp`, plus PyPI
JSON file lists and PEP 658 per-wheel metadata for: torch (2.6.0 and 2.15.0, cp312
aarch64), flash-attn, xformers, spconv-cu120, kaolin, pytorch3d, xatlas, PyMCubes,
torchmcubes, pynanoinstantmeshes, gpytoolbox, triton, bitsandbytes, cupy-cuda12x,
cupy-cuda13x, open3d, onnxruntime, onnxruntime-gpu, pymeshlab, usd-core, cadquery-ocp,
cadquery-ocp-novtk, build123d, cadquery, numpy, scipy, pandas, shapely, pillow, OpenEXR,
landlab, python-fcl, procfunc, cvdpack, torchaudio, soundfile, safetensors, tokenizers,
rembg, transformers, diffusers, accelerate, einops, trimesh, smplx, chumpy, open-clip-torch,
encodec, x-transformers, torchac, julius, librosa, bpy.

**Kernel inspection**
```
cuobjdump --list-elf libtorch_cuda.so   # torch 2.15.0 cp312 aarch64
  → sm_100(535) sm_103(59) sm_110(535) sm_120(477) sm_121(1) sm_80(476) sm_90(480)
nvcc default (no -arch) → sm_75 SASS + compute_75 PTX  → runs on Thor via PTX JIT
nvcc -gencode arch=compute_75,code=sm_75 → "no kernel image is available for execution on the device"
```

**First-party sources consulted** (beyond PyPI/HF/GitHub APIs): `microsoft/TRELLIS.2`
`setup.sh` (conda python 3.10, `torch==2.6.0` cu124, `flash-attn==2.7.3`, and the
optional nvdiffrast/nvdiffrec/cumesh/o-voxel/flexgemm flags), the local ComfyUI tree
(v0.42.0: `comfy/ldm/trellis2/{flexgemm.py,model.py,vae.py}`, `requirements.txt`,
`comfy/model_detection.py`, `comfy/cli_args.py`), the local
`~/src/infinigen-thor` spike tree (`thor/build-bpy.sh`, `thor/install.sh`,
`thor/run-timed.sh`, `thor/patches/`, `pyproject.toml`, `.python-version`, commits
`67f3e673` and `3668454a`), modly's README and the `manifest.json` of its
`triposg`, `trellis2-gguf` and `hunyuan3d-mini` extensions, and the HF README
frontmatter for Pixal3D (`extra_gated_eu_disallowed: true`).

**Not consulted / not available:** `thor/SPIKE.md` (does not exist — spike still
building the bpy wheel), `~/lm-wt/split/REPORT.md` (does not exist — only its brief),
and the GitHub REST API for `Dao-AILab/flash-attention` releases/issues, which was
rate-limited from this host; the flash-attn sm_110 claim therefore rests on the PyPI
file list (1 sdist, 0 wheels) plus res-3d's cited issue, not on a fresh fetch of
that issue.
