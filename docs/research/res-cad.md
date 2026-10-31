# REPORT: CAD, asset tooling and the generative pipeline on Jetson AGX Thor

Research for **builder-ide** (see `~/src/builder-ide/docs/vision.md`, "The engineer also
makes things"). Read-only: repos cloned to `/tmp`, wheels checked with PyPI JSON and
`pip download` into `/tmp`. Nothing was installed into a shared environment and no
candidate's code was run. Research date: 2026-10-30.

**Field advantage:** the research box itself is the target — L4T R39.2 (JetPack 7),
`nvidia-smi` reports `NVIDIA Thor`, driver 595.78, CUDA 13.2, Python 3.12. Every
aarch64 wheel claim below was checked against this machine's platform.

---

## TL;DR — verdicts

| Candidate | Role | Verdict | One-line reason |
|---|---|---|---|
| **build123d** | CAD parts as code | **Adopt (primary)** | Typed algebraic API made for agents, Apache-2.0, explicit aarch64 support, verified wheels, exports STEP+GLB with materials |
| **CadQuery** | CAD parts as code | **Adopt (secondary)** | Same OCCT base and wheels; more LLM training data but string-selector API is validation-hostile |
| **modly** | Image-to-3D prop-maker front-end | **Spike first** | MIT, headless FastAPI backend already proven on a Jetson; textures and rembg need work on Thor |
| **StableMaterials + SDXL** | Textures/PBR | **Spike first** | OpenRAIL weights (commercial-OK), tileable SVBRDF in ~4 steps; MatForger (the nicer one) is gated |
| **MoMask** | Text-to-motion | **Spike first (licence-flagged)** | MIT code, fastest of the family, seeded; but HumanML3D/AMASS data provenance restricts shipped use |
| **MDM** | Text-to-motion | **Skip (MoMask covers it)** | MIT and fine, but slower; same data licence problem |
| **MotionGPT** | Text-to-motion + captioning | **Skip for now** | flan-t5 stack adds weight for no t2m gain; weights licence reads only "cc" (ambiguous) |
| **ACE-Step** | Music/ambience | **Adopt** | Apache-2.0 code *and* weights, ~8 GB VRAM class, 4-minute track in ~20 s (A100) |
| **Stable Audio Open Small / 1.0** | Sound effects | **Spike first** | Best SFX quality, Arm-CPU-friendly Small variant; weights gated + community licence (<$1M revenue free) |
| **MusicGen / AudioCraft** | Music | **Skip for shipped assets** | Weights are CC-BY-NC 4.0 — the non-commercial flag the vision warned about |
| **OpenUSD (`usd-core`)** | Scene format & assembly | **Adopt** | Pixar ships aarch64 wheels (verified download); TOST-1.0 ≈ Apache-2.0; layers from Python |
| **SimReady (Foundation repo)** | Physics/material metadata reference | **Adopt as schema** | Apache-2.0 sample content; use its profiles as the schema, not as the asset library |

And the headline hardware finding: **stock PyPI `torch` 2.15.0 now ships an aarch64
CUDA wheel built against CUDA 13.2 with `sm_110` (Blackwell) kernels inside
`libtorch_cuda.so`** (verified by downloading the 462 MB wheel and scanning the
fatbin arch strings; deps pin `cuda-toolkit==13.2.2`, matching this box exactly).
The whole "Jetson needs a special PyTorch index" problem that bit AGX Orin is gone
for Thor: `pip install torch` should just work. Remaining Thor risks are therefore
narrowed to the *compiled CUDA extensions* some projects insist on (texture
rasterizers, PyTorch3D for rendering, xformers) — listed per candidate below.

---

## 1. CadQuery vs build123d — parametric CAD for an agent engineer

Both are thin Python layers over the same OCCT kernel via the same binding family
(`cadquery-ocp` / `cadquery-ocp-novtk`), both **Apache-2.0**, both pure-CPU, both
actively maintained (CadQuery commit 2026-10-24; build123d commit 2026-10-30), and
shapes interop in both directions via the shared `.wrapped` TopoDS handle
(build123d documents this in its tips). The choice is about the API the agent writes.

| Axis | CadQuery 2.8.0 | build123d 0.13.0 |
|---|---|---|
| Style | Fluent chains: `cq.Workplane("XY").box(...).faces(">Z").workplane().hole(3)` | Algebra: `part = extrude(sketch, 2) - Pos(0,0,5) * Cylinder(3,10)`; optional Builder-mode contexts |
| Selectors | String selectors (`">Z"`, `"|X"`) — opaque to static analysis, silent-miss prone | Property-based: `part.faces().group_by(Face.area).sort_by(Axis.X)`, filter by `GeomType.CYLINDER`, lambdas |
| Typing | Partial; the chain API resists checkers | mypy/pylint clean by policy, full type hints, Python 3.11–3.14 |
| aarch64 | All binary deps have aarch64 wheels (see below) | **Explicitly supported**: `pyproject.toml` swaps `lib3mf`→`py-lib3mf` on `linux/aarch64` |
| VTK | drags `trame`/VTK for viz (master) | `cadquery-ocp-novtk` — no VTK at all, ideal headless |
| Exports | STL, STEP, AMF, SVG, three.js, DXF, VRML, VTP, 3MF, BREP; assemblies add GLTF/GLB/VTKJS | STEP, STL, BREP, OBJ, **glTF with material UVs** (`exporters3d.py`) |
| Docs/community | Larger; more LLM training data; CQ-editor | Newer, strong docs/cheatsheet, active Discord |

Sources: [CadQuery repo](https://github.com/CadQuery/cadquery) (README: "output …
STEP and DXF in addition to STL, VRML, AMF and 3MF"; LICENSE = Apache-2.0;
[`ExportTypes`](https://github.com/CadQuery/cadquery/blob/master/cadquery/occ_impl/exporters/__init__.py)
and [`Assembly.export`](https://github.com/CadQuery/cadquery/blob/master/cadquery/assembly.py)
in code), [build123d repo](https://github.com/gumyr/build123d) (README API samples,
[`pyproject.toml`](https://github.com/gumyr/build123d/blob/dev/pyproject.toml) aarch64
markers, [`exporters3d.py`](https://github.com/gumyr/build123d/blob/dev/src/build123d/exporters3d.py)).

**Licences:** code Apache-2.0 both; OCCT itself is LGPL-2.1 with exception (headers),
the OCP wheels are Apache-2.0 (wheel METADATA). No model weights involved.

**Thor feasibility — verified, no source builds:**

- `cadquery_ocp` / `cadquery_ocp_novtk` 7.9.3.0 → 8.0.1.1.0 all publish
  `manylinux_2_28_aarch64` wheels for cp310–cp314 (PyPI file lists); the released
  CadQuery pin `cadquery-ocp>=7.9.3.1,<8.0` resolves, and build123d's `>=8.0,<8.1`
  resolves. I downloaded
  `cadquery_ocp_novtk-8.0.1.1.0-cp312-cp312-manylinux_2_28_aarch64.whl` (59 MB) to
  /tmp successfully.
- The rest: `nlopt`, `casadi`, `ezdxf` have aarch64 manylinux wheels; `multimethod`,
  `trame*`, `runtype`, `ocpsvg`, `ocp_gordon` are pure-Python; `py-lib3mf` 2.5.0 has
  aarch64 wheels. glibc needed is ≤ 2.35 — Ubuntu 24.04 (2.39) is fine.

**Speed/memory/determinism:** CPU-bound OCCT; a typical part is milliseconds to a
few seconds. No GPU/CUDA anywhere in the dependency tree (verified from
`install_requires`/`pyproject`) — CAD batches are effectively free alongside GPU
jobs. Determinism is total for our purposes: no RNG in the kernel; same script +
pinned wheel version → byte-identical geometry. That is why CAD parts are
"recipe-native": the *script is the asset*, meshes are caches.

**Fit & verdicts.** Role: CAD-precise parts (hinges, gears, machinery) written by
the engineer as code, exported as STEP (master, for re-editing) + GLB (for the
scene/USD assembly). **Adopt build123d as the primary authoring API** — its typed,
property-based, operator style is far easier for an agent to write *and for the
review pipeline to statically check*, and it officially supports this exact
platform. **Keep CadQuery as a readable secondary** (it shares every binary
dependency, costs nothing extra, and its larger corpus of public examples makes it
a useful few-shot source for the engineer agent). Both verdicts: **adopt**.

---

## 2. modly — local image-to-3D with an agent-friendly headless backend

[github.com/lightningpixel/modly](https://github.com/lightningpixel/modly), **MIT**
(attribution clause for forks), very active (merge 2026-10-20, tags to v0.4.3).

1. **What it does.** Electron desktop app for local, open-model **image-to-3D**;
   the valuable part for us is that the Python **FastAPI backend is fully
   standalone and HTTP-driven** — run `uvicorn main:app` headless and drive it with
   curl or its stdlib CLI (`tools/modly-cli/agent.py`: `health`, `model`,
   `workflow-run`, `generate` → JSON on stdout; there is also an MCP server,
   `api/mcp_server.py`). Model backends are installable **extensions**: Hunyuan3D 2
   Mini / Mini Turbo / Mini Fast, TripoSG, Trellis2-GGUF. Output: **GLB meshes**
   (+ in-app smoothing/decimation via trimesh/pymeshlab); a `scene` artifact kind
   (`modly.scene-manifest.v1`) exists as a first-class input. Quality notes from
   its own docs: single-image 3D infers unseen sides; outputs "typically not
   watertight".
2. **Licences.** Code MIT. Weights depend on the chosen extension: Hunyuan3D-2mini
   is under the **Tencent Hunyuan 3D 2.0 Community License** — permissive-ish but
   *expressly not applicable in the EU, UK and South Korea*, with an Acceptable Use
   Policy; **TripoSG (VAST-AI) weights are MIT**; **TRELLIS (Microsoft) weights are
   MIT**. For a shipped game, prefer TripoSG/TRELLIS; keep Hunyuan as an internal
   option and record the licence per asset.
3. **Thor feasibility.** The repo ships
   [`docs/running-on-jetson.md`](https://github.com/lightningpixel/modly/blob/main/docs/running-on-jetson.md)
   — a first-party guide verified on an **AGX Orin 64 GB, JetPack 6.2, CUDA 12.6,
   sm_87**, running the **Hunyuan3D-2 Mini** extension mesh-only, "~6 GB
   VRAM-class", `50 steps / 512 octree` "comfortable on a 64 GB Orin". Its three
   Orin problems map to Thor like this:
   - *wrong torch wheels (no sm_87)*: **solved upstream** — PyPI `torch` 2.15.0
     aarch64 is a CUDA 13.2 build containing `sm_110` kernels (verified in
     `/tmp`; deps: `cuda-toolkit==13.2.2`, `nvidia-cudnn-cu13==9.26.0.51`),
     matching Thor exactly.
   - *NumPy 1.x pin*: modern Jetson wheels are NumPy-2-clean; retest, likely gone.
   - *`rembg`/ONNX Runtime aborting on Tegra CPU*: **still a real risk** — PyPI
     `onnxruntime` aarch64 wheels exist (1.31.1, verified) but the Tegra-CPU abort
     was a native crash; plan the guide's NumPy/SciPy background-removal patch or
     pre-cut alpha on the GPU side.
   - *textures*: the texture path needs `custom_rasterizer` +
     `differentiable_renderer` **CUDA C++ extensions built from source** for
     aarch64/CUDA 13 — the one genuinely heavy item. Mesh-only needs no builds.
   Backend deps are all aarch64-clean: `pymeshlab` (aarch64 wheels verified),
   `trimesh` (pure-py), FastAPI stack (pure-py).
4. **Speed/memory/determinism.** From its own Jetson guide: ~6 GB VRAM-class
   model; steps 10/30/50 and octree 256/380/512 selectable; a 64 GB Orin is
   comfortable at the top setting, so 122 GB Thor is ample. **`seed` is a first-class
   param** (`"seed":42` in the documented curl example) → seeded, replayable
   provenance.
5. **Fit.** Role: the **prop-maker** image-to-3D station behind the model
   scheduler, driven over HTTP by the engineer/builder; candidate meshes get scored
   by the critic. Plug-in: scheduler POSTs the image+params+seed, polls, pulls the
   GLB, records provenance (model extension id + weights repo/revision + seed).
   **Verdict: spike first** — the headless backend pattern is exactly right and
   Orin-proven, but budget a few days for the rembg workaround and (later) the
   texture CUDA extensions; use the MIT-weighted TripoSG extension first.

---

## 3. Textures and PBR materials

The vision wants "image generation, then the PBR maps the renderer needs", plus the
curated recipe library. Candidates for the generative gap-filler:

- **StableMaterials** ([gvecchio/StableMaterials](https://huggingface.co/gvecchio/StableMaterials),
  paper [arXiv:2406.09293](https://arxiv.org/abs/2406.09293)): diffusion
  **text→PBR/SVBRDF maps**, trained on MatSynth with an SDXL prior, a tileability
  technique for seamless tiles, and a distilled **latent-consistency path that
  generates in ~4 steps**. Weights licence on the HF card: **OpenRAIL**
  (commercial use permitted under the RAIL use restrictions — the same family as
  SDXL itself). Runs as a diffusers pipeline (pure PyTorch; no compiled kernels).
  *This is the adopt-track candidate.*
- **MatForger** (same author's successor; [ComfyUI_PBR_Maker](https://github.com/smthemex/ComfyUI_PBR_Maker)
  MIT nodes, [material-crafter](https://github.com/rensortino/material-crafter) MIT
  Blender add-on): nicer controllability story, but the weights repo
  (`gvecchio/MatForger`) currently returns **401/gated** — cannot be a dependency
  today. Watch it.
- **Dream Textures** ([carson-katri/dream-textures](https://github.com/carson-katri/dream-textures),
  **GPL-3.0**, 8.2k ★, active 2026-09): Stable Diffusion *inside Blender*,
  including seamless texture generation. Fits the infinigen-thor host naturally
  (it's an add-on, GPL is fine unmodified); useful as an interactive fallback, not
  as a library.
- **Base image models** (the albedo generator, if not using StableMaterials
  end-to-end): SDXL weights = CreativeML **OpenRAIL++-M** (commercial-OK with
  restrictions); SD 3.5 = **Stability Community Licence** (free commercial under
  $1M revenue); **FLUX.1-dev weights are non-commercial — skip for shipped
  assets**; FLUX.1-schnell is Apache-2.0.
- **Curated fallback (adopt now):** [Poly Haven](https://polyhaven.com/) and
  [ambientCG](https://ambientcg.com/) are CC0 — they slot straight into the recipe
  library with zero licence bookkeeping, and Infinigen's own procedural materials
  (BSD-3) remain the default in-engine path.

Determinism: seeded samplers everywhere (diffusers takes `generator`), so a
material is `(prompt, weights-revision, seed, resolution)`. VRAM: SDXL-class fp16
≈ 7–10 GB — trivial next to 122 GB.

**Verdict: spike first** on StableMaterials-in-diffusers + SDXL, with CC0
libraries as the curated baseline. Skip MatForger (gated) and FLUX-dev
(non-commercial) for shipped content.

---

## 4. Character motion — MDM, MoMask, MotionGPT

All three: text → skeletal motion clips on the **HumanML3D 22-joint representation**
(derived from AMASS mocap), seeded sampling (deterministic per seed), pure-PyTorch
inference (no compiled CUDA kernels; PyTorch3D/SMPL appear only in *rendering/eval*
paths). Retargeting onto the avatar rig and export to glTF/FBX animation happens
host-side in Blender — real but bounded spike work.

| | MDM | MoMask | MotionGPT |
|---|---|---|---|
| Code licence | **MIT** (4.1k ★) | **MIT** (1.3k ★) | **MIT** (2.0k ★) |
| Weights | Google Drive checkpoints, **no stated weights licence** | same (repo checkpoints) | HF `OpenMotionLab/MotionGPT-base`, card says only `license: cc` (**ambiguous — flag**) |
| Method | diffusion, ~0.4 s/sample with the 50-step model + cached CLIP | masked RVQ transformer, 10 iterations; **FID 0.045 vs T2M-GPT 0.141 on HumanML3D** (paper) | motion tokens in a flan-t5-base LLM (Apache weights); unified motion↔text |
| Deps beyond torch | CLIP (MIT), plain | CLIP, einops; `smplx/chumpy` only for rendering | transformers, pytorch-lightning |
| Data caveat | HumanML3D/AMASS | HumanML3D/AMASS | HumanML3D/AMASS |

Sources: [motion-diffusion-model](https://github.com/GuyTevet/motion-diffusion-model)
("40X faster (~0.4 sec/sample)" with the 50-step model),
[momask-codes](https://github.com/EricGuo5513/momask-codes) (licence section
explicitly warns: "our code depends on … SMPL, SMPL-X, PyTorch3D, and uses datasets
which each have their own respective licenses that must also be followed"),
[MoMask paper](https://arxiv.org/abs/2312.00063),
[MotionGPT](https://github.com/OpenMotionLab/MotionGPT) (configs: `flan-t5-base`).

**The licence story is the finding:** code is MIT everywhere, but the training data
(HumanML3D ← AMASS) carries research-use restrictions that flow into any shipped
output. For an in-development world this is manageable with per-asset provenance
(the scheduler stamps every clip with model+seed+data licence); for a *shipped
commercial* game it is the one corner of the pipeline that likely needs either a
licence review or replacement with mocap/proc-animated clips.

**Verdict:** **spike MoMask first** (fastest, best published FID of the three, MIT
code, small enough to keep warm all night); MDM **skip** (covered by MoMask);
MotionGPT **skip for now** (heavier LLM stack, no t2m gain, ambiguous weight
licence) — revisit only if the builders need motion *captioning/understanding*.

---

## 5. Music and sound

| | Code | Weights | Notes |
|---|---|---|---|
| **ACE-Step v1 3.5B** | **Apache-2.0** (5k ★) | **Apache-2.0** (HF card) | Music foundation model; **up to 4 min of music in ~20 s on an A100**; RTF 27× (2.2 s per 1 min of audio, 27 steps); max VRAM trimmed to **~8 GB**; diffusion + Sana DCAE + linear transformer, diffusers-style stack |
| **Stable Audio Open 1.0** (stable-audio-tools, MIT, active 2026-10) | MIT | **Stability AI Community License** — free incl. commercial under **$1M annual revenue**, enterprise above; gated on HF | 1.2B; **up to 47 s, 44.1 kHz stereo**; the quality SFX/ambience workhorse |
| **Stable Audio Open Small** (with Arm, 2025-05) | MIT | same community licence, gated | 341M, distilled; **~11 s clips @ 44.1 kHz**, SFX-focused, marketed as real-time **on Arm CPUs** — i.e. it can run on the Thor's CPU lane without touching the GPU |
| **MusicGen / AudioCraft** | audiocraft MIT, but PyPI sdist pins `torch==2.1.0` + `xformers<0.0.23` (dead on CUDA 13; use `transformers`' MusicGen instead) | **CC-BY-NC 4.0** (facebook/musicgen-*) | The non-commercial flag the vision predicted. Fine for throwaway prototyping, **not for shipped assets** |

Sources: [ACE-Step repo](https://github.com/ace-step/ACE-Step) (speed table: RTF
27.27×/A100, 34.48×/4090; "Reduced Max VRAM to 8GB"),
[ACE-Step HF](https://huggingface.co/ACE-Step/ACE-Step-v1-3.5B) (apache-2.0 tag),
[stable-audio-tools](https://github.com/Stability-AI/stable-audio-tools) (MIT),
[Stable Audio Open 1.0](https://huggingface.co/stabilityai/stable-audio-open-1.0)
(licence: free commercial <$1M revenue per the
[Stability licence page](https://stability.ai/license)),
[Stable Audio Open Small announcement](https://stability.ai/news-updates/stability-ai-and-arm-release-stable-audio-open-small-enabling-real-world-deployment-for-on-device-audio-control)
(341M, ~11 s, on-device Arm),
[facebook/musicgen-small](https://huggingface.co/facebook/musicgen-small)
(`license: cc-by-nc-4.0`), [audiocraft PyPI](https://pypi.org/project/audiocraft/)
(pinned torch 2.1.0 / xformers).

Determinism: all seeded. Memory: everything here fits in a warm tier with room to
spare; SAOS can even live on the CPU.

**Verdict: adopt ACE-Step** for ambience/music (the only fully Apache music model
of its class), **spike Stable Audio Open Small** for SFX (gated weights — accept
the licence once, then it's local), **skip MusicGen** for anything that ships.

---

## 6. NVIDIA OpenUSD + SimReady — the scene format and assembly layer

- **OpenUSD** ([PixarAnimationStudios/OpenUSD](https://github.com/PixarAnimationStudios/OpenUSD),
  7.6k ★): licence is the **Tomorrow Open Source Technology License 1.0 (TOST-1.0)**
  — per the repo's own LICENSE.txt, "differs from the original Apache License 2.0
  … Section 6 (Trademarks) is different", i.e. Apache-class permissive. The
  **`usd-core` PyPI wheels are published by Pixar themselves** (author field:
  "Pixar Animation Studios"), and **aarch64 manylinux_2_28 wheels exist for
  cp311–cp314** — I downloaded `usd_core-26.11-cp312-...aarch64.whl` (27 MB) to
  /tmp successfully. From Python you get the full composition engine: layers,
  sublayers, variants, payload, references — exactly the machinery for
  world/physics/material layers assembled per project.
- **SimReady**: [NVIDIA/simready-foundation](https://github.com/NVIDIA/simready-foundation)
  is **Apache-2.0** (NVIDIA-authored content; third-party robot models keep their
  own MIT/BSD notices). Its value to us is the **schema/profiles**: USD assets with
  physics (rigid-body, joints, collision), material and semantic taxonomy baked in
  — a ready-made pattern for how builder-ide assets should carry their physics and
  semantics layers. The *full* SimReady library via Omniverse is governed by the
  [Omniverse terms](https://www.nvidia.com/en-us/omniverse/terms-of-service/)
  (check per asset). There is also an Apache-2.0
  [Blender add-on](https://github.com/NVIDIA/simready-blender-add-on).
- **Interchange:** Blender (infinigen-thor's host) has built-in USD import/export
  with MaterialX in the 4.x line
  ([Blender 4.2 USD docs](https://docs.blender.org/manual/en/4.2/files/import_export/usd.html));
  Infinigen is BSD-3-Clause; the ProArt thin client already expects streamed
  glTF/USD. So: world engine (Blender) ⇄ USD ⇄ viewer/Isaac/SimReady all have
  stock bridges. `usd-core` writes USDA/USDC/USDZ.

**Verdict: adopt** — USD as the *assembly and interchange* layer, exactly as the
addendum proposes. Notable honest caveat: `usd-core` (the Pixar build) has no
Hydra/GPU rendering; that's fine, rendering stays in Blender/Cycles and the ProArt.

---

## 7. Claims checked (from the other agent)

1. **"The Thor has dedicated hardware pipelines that read and stream OpenUSD
   scenes" — FALSE (as stated).** No NVIDIA publication documents a dedicated USD
   hardware unit. Thor's actual hardware accelerators are video/vision oriented;
   its [product page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor)
   sells Blackwell GPU compute (2,070 FP4 TFLOPS, 128 GB, MIG) and a
   video-streaming accelerator suite. OpenUSD is a CPU software library; NVIDIA's
   USD ecosystem (Omniverse, Isaac Sim, Newton physics) runs as software on the
   GPU/CUDA. "Streaming OpenUSD scenes to Thor" demos (XGRIDS/Isaac) are software
   pipelines. *If the claim is softened to "Thor can run USD-based stacks well and
   has hardware video encode for streaming rendered output", that part is true.*
2. **"CadQuery/build123d run on high-frequency CPU/GPU layers with zero VRAM" —
   PARTLY TRUE, packaging is nonsense.**
   - *Zero VRAM: TRUE.* Verified from the dependency trees: no CUDA, no GPU, no
     torch anywhere; OCCT is pure CPU. CAD batches cost zero GPU memory.
   - *"high-frequency CPU/GPU layers": FALSE/unverified.* There is no GPU
     involvement. The accurate statement: OCCT workloads are CPU-bound and often
     effectively single-threaded per boolean/fillet, so they *like high clock
     speeds* on a few fast cores — nice on Thor's 14 Arm cores, but "GPU layers"
     is fiction.

---

## 8. Should the recipe be USD layers, our own format, or both?

**Both — with one direction of truth: the recipe (our own typed format) is the
source of truth; USD is a compiled output and assembly cache.** Reasons:

- The vision already commits to "a project is its recipe … diffable, branchable,
  replayable; a night's work is kilobytes", and builders edit only through a closed
  typed vocabulary. USD's composition semantics (opinions, LIVRPS strength
  ordering, arcs) are powerful but hostile to diffing, typing and
  branch-by-character workflows — a recipe *edit* should read like a parameter
  change, not a USDA opinion reshuffle.
- Interchange is where USD is unbeatable: SimReady physics/material profiles,
  Isaac/Omniverse, Blender, USDZ to the ProArt. So every recipe compiles
  deterministically to a **layered USD stage**: one layer per concern (geometry
  references, materials, physics, semantics), asset provenance in `customData`
  (prompt, model, weights revision, seed, licence), payloads for heavy meshes.
  Deterministic emission (sorted prims, no timestamps) keeps USD diffs meaningful
  as a review artifact.
- One-way flow: recipe → USD, never USD → recipe, except for *importing* external
  assets (SimReady, marketplace), which enter as USD payloads wrapped by a recipe
  entry carrying their licence.

---

## 9. The model scheduler: batching a night on one 122 GB box

The constraint on Thor is not VRAM capacity (122 GB unified; nothing here needs
more than ~10 GB) — it is **GPU compute-time and weight-swap thrash**, plus the
temptation to serialize CPU work behind the GPU.

**Memory tiers (as in the vision):**
- **Hot (always resident):** companion/planner LLM + the critic (vision model).
  Small, latency-sensitive, used between every batch.
- **Warm (loaded once per night-segment, then drained):** one generative model at
  a time — image-to-3D, then the texture stack, then MoMask, then ACE-Step.
  Batching by model is the whole game: hundreds of prompts through one loaded
  model, not one load per prompt.
- **Cold:** everything else, on disk, with pinned weights revisions.

**Lane layout for a night:**
1. **Plan → task queue** (the builders' work orders, each with budget + acceptance
   check).
2. **CPU lane runs continuously:** build123d parts (zero GPU), SAOS sound effects
   (CPU-capable), mesh cleanup/decimation, USD assembly. These never wait on the
   GPU.
3. **GPU lane, ordered to feed dependencies:** image-to-3D props (modly backend,
   TripoSG/Hunyuan-mini) → texture batches for those props and the scene
   (SDXL/StableMaterials) → motion clips (MoMask, seeded) → music/ambience
   (ACE-Step). Critic checks interleave after each batch; failed candidates
   regenerate within budget or park for the morning.
4. **Assembly:** recipe entries updated; USD layers re-emitted; morning report
   with keep/revert branches.

**Provenance is the scheduler's job, not the job's:** it stamps every artifact
`(prompt, model id, weights repo+revision, seed, library versions, wall-time,
licence)` — which is also what makes a night replayable and swappable when a better
Thor-native model lands.

---

## 10. Recommended first pipeline

1. **Backbone first:** `usd-core` (adopt) + own recipe format → deterministic USD
   layer compiler. Nothing else lands without provenance + licence fields.
2. **CAD:** build123d (primary) + CadQuery (secondary) — both pure-CPU, verified
   aarch64 wheels, zero GPU; STEP as master, GLB into the USD assembly.
3. **Props:** modly's headless FastAPI backend with the **TripoSG extension**
   (MIT weights) first, mesh-only; textures deferred past the spike. PyPI `torch`
   (aarch64 CUDA 13.2, sm_110 — verified) is the stack's base; plan the rembg
   workaround.
4. **Textures/PBR:** SDXL + StableMaterials diffusers pipeline (OpenRAIL),
   seeded; Poly Haven/ambientCG CC0 into the curated library now, Infinigen
   procedural materials as the default.
5. **Audio:** ACE-Step (Apache) for ambience/music; spike Stable Audio Open Small
   for SFX. MusicGen excluded from shipped assets (CC-BY-NC).
6. **Motion (last, flagged):** MoMask spike + Blender retarget to glTF clips;
   every clip carries the AMASS/HumanML3D data-provenance flag until a licence
   decision is made.
7. **Scheduler discipline:** hot/warm/cold tiers, batch-by-model, CPU lane always
   busy, everything seeded and stamped.

---

## Appendix: wheel evidence (checked 2026-10-30 on this aarch64 box)

| Package | aarch64 status | Evidence |
|---|---|---|
| `torch` 2.15.0 | ✅ manylinux_2_28 CUDA wheel, cp311–315; **sm_110 strings present** in `libtorch_cuda.so`; deps `cuda-toolkit==13.2.2` | downloaded to /tmp, inspected |
| `cadquery-ocp` / `-novtk` 7.9.3.0–8.0.1.1.0 | ✅ manylinux_2_28 wheels cp310–314 | PyPI file lists + `pip download` (59 MB, cp312) |
| `cadquery` 2.8.0 / `build123d` 0.13.0 | ✅ pure-Python wheels | PyPI |
| `nlopt`, `casadi`, `ezdxf`, `py-lib3mf`, `pymeshlab`, `onnxruntime` | ✅ aarch64 manylinux wheels | PyPI file lists |
| `usd-core` 26.11 | ✅ manylinux_2_28 aarch64, cp311–314 (published by Pixar) | `pip download` (27 MB, cp312) |
| `transformers`, `diffusers`, `accelerate`, `stable-audio-tools`, `trimesh`, `einops` | ✅ pure-Python | PyPI |
| `audiocraft` 1.3.0 | ⚠️ sdist only; pins `torch==2.1.0`, `xformers<0.0.23` — unusable on CUDA 13 as-is (use `transformers`' MusicGen instead) | PyPI metadata |

Would-need-source-builds on Thor: modly's texture path
(`custom_rasterizer`, `differentiable_renderer`), PyTorch3D (motion rendering
only — avoidable), anything flash-attn/xformers-shaped (none of the adopted stack
requires them).

## Sources

- Repos: [CadQuery](https://github.com/CadQuery/cadquery) · [build123d](https://github.com/gumyr/build123d) · [modly](https://github.com/lightningpixel/modly) · [modly Jetson guide](https://github.com/lightningpixel/modly/blob/main/docs/running-on-jetson.md) · [modly-hunyuan3d-mini-extension](https://github.com/lightningpixel/modly-hunyuan3d-mini-extension) · [MDM](https://github.com/GuyTevet/motion-diffusion-model) · [MoMask](https://github.com/EricGuo5513/momask-codes) · [MotionGPT](https://github.com/OpenMotionLab/MotionGPT) · [ACE-Step](https://github.com/ace-step/ACE-Step) · [stable-audio-tools](https://github.com/Stability-AI/stable-audio-tools) · [OpenUSD](https://github.com/PixarAnimationStudios/OpenUSD) · [simready-foundation](https://github.com/NVIDIA/simready-foundation) · [simready-blender-add-on](https://github.com/NVIDIA/simready-blender-add-on) · [dream-textures](https://github.com/carson-katri/dream-textures) · [material-crafter](https://github.com/rensortino/material-crafter) · [ComfyUI_PBR_Maker](https://github.com/smthemex/ComfyUI_PBR_Maker) · [infinigen (BSD-3)](https://github.com/princeton-vl/infinigen)
- Models/cards: [StableMaterials](https://huggingface.co/gvecchio/StableMaterials) · [arXiv:2406.09293](https://arxiv.org/abs/2406.09293) · [arXiv:2312.00063 (MoMask)](https://arxiv.org/abs/2312.00063) · [MotionGPT-base](https://huggingface.co/OpenMotionLab/MotionGPT-base) · [Hunyuan3D-2mini licence](https://huggingface.co/tencent/Hunyuan3D-2mini) · [TripoSG](https://huggingface.co/VAST-AI/TripoSG) · [TRELLIS-image-large](https://huggingface.co/microsoft/TRELLIS-image-large) · [musicgen-small (CC-BY-NC)](https://huggingface.co/facebook/musicgen-small) · [Stable Audio Open 1.0](https://huggingface.co/stabilityai/stable-audio-open-1.0) · [ACE-Step HF](https://huggingface.co/ACE-Step/ACE-Step-v1-3.5B)
- Vendor/docs: [Jetson AGX Thor page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor) · [Stability licence page](https://stability.ai/license) · [Stable Audio Open Small announcement](https://stability.ai/news-updates/stability-ai-and-arm-release-stable-audio-open-small-enabling-real-world-deployment-for-on-device-audio-control) · [Omniverse ToS](https://www.nvidia.com/en-us/omniverse/terms-of-service/) · [Blender 4.2 USD docs](https://docs.blender.org/manual/en/4.2/files/import_export/usd.html) · [Poly Haven](https://polyhaven.com/) · [ambientCG](https://ambientcg.com/) · PyPI JSON APIs for every wheel claim above.
