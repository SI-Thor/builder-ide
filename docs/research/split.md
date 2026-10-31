# REPORT: how do we cleverly shift the processing burden? (Thor, ProArt, cloud, Orin)

Research for **builder-ide** against the brief in this directory. Everything here is
read-only: I ran no installs, started/stopped no services, and did not modify
`~/src/infinigen-thor` (the other seat is mid-build there). All Thor measurements were
taken on this box (the research machine *is* the Thor) on **2026-10-30, ~22:20 local**,
with the GNOME desktop and my SSH session as the only load. Every hardware claim below
carries either a command output or a source link; code claims carry `file:line`.

**Input status note.** The brief points at `~/src/builder-ide/docs/research/ux-day.md`
and `res-cad.md`; those files do not exist yet — the sibling sessions' outputs live at
`~/lm-wt/ux-day/REPORT.md` and `~/lm-wt/res-cad/REPORT.md`, and I read those (they are
the "three clocks" doctrine and the scheduler/USD/recipe research the brief means).
`~/src/builder-ide/docs/vision.md` was read as-is. `thor/SPIKE.md` did **not** exist
when I finished (checked 22:30; the bpy-from-source build is still in progress on the
external drive — CPython, OpenImageIO and the CPU terrain extensions are compiled, the
wheel is not). §7 lists exactly what in this plan depends on its numbers.

---

## 0. The machines, verified

### The Thor (measured here)

| What | Verified value | How |
|---|---|---|
| Board | NVIDIA Jetson AGX Thor Developer Kit, module P4071-0000 + carrier P3834-0008, SoC `nvidia,tegra264` | `/proc/device-tree/model`, `compatible` |
| OS | L4T **R39.2.1** (JetPack 7 line), Ubuntu 24.04, kernel 6.8.12-1021-tegra | `/etc/nv_tegra_release` |
| CPU | **14× ARM Neoverse class, 1 cluster, max 2,601 MHz, min 54 MHz**, no SMT | `nproc`, `lscpu` |
| Caches (sysfs) | L1d/L1i 64 KiB/core, L2 1 MiB/core (14 MiB total). **No L3 exposed in sysfs**; NVIDIA's spec sheet says 16 MB shared L3 — real per docs, invisible to `lscpu`/`cpu/cache` | `/sys/devices/system/cpu/cpu0/cache/index*` |
| RAM | 128 GB physical, **125.7 GB visible to tegrastats / 122.8 GiB in `/proc/meminfo`**, unified CPU+GPU, LPDDR5X 256-bit, ~273 GB/s (vendor figure) | `/proc/meminfo`, tegrastats, [NVIDIA Thor page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor) |
| GPU | "NVIDIA Thor", driver **595.78**, CUDA **13.2**; compute capability **11.0 (sm_110, Blackwell)**; CUDA toolkit at `/usr/local/cuda-13.2`; idle 2 W / 32 °C | `nvidia-smi`; cc 11.0 verified by the spike's `nvcc -arch=native` sanity check (`thor/build-bpy.sh`) |
| Power modes | **0 = MAXN, 1 = 120 W, 2 = 90 W, 3 = 70 W**; currently MAXN. Idle draw with desktop: **~25–28 W** at the `VIN` rail, GPU rail 0 mW | `nvpmodel -q`, `/etc/nvpmodel.conf -> nvpmodel_p3834_0008.conf`, tegrastats |
| Clock locking | `jetson_clocks` available (not currently locked; CPU scaling at 78% when sampled) | `which jetson_clocks`, `lscpu` |
| Video engines | `/dev/v4l2-nvenc`, `/dev/v4l2-nvdec` (device nodes); **AV1 encode controls present** (AV1 tiles, AV1 RDO/SSIM metadata) alongside H.264/H.265 in the encoder API → NVENC does H.264, HEVC and AV1 | `ls /dev`, `NvVideoEncoder.h`, `01_video_encode` sample in `/usr/src/jetson_multimedia_api` |
| Other engines | PVA v3 (`/dev/nvhost-ctrl-pva0`), 2 ISP channels (`nvhost-ctrl-isp{,1}`). **No OFA device node.** **No camera `/dev/video*` capture nodes** — no sensors attached | `ls /dev` |
| Network | 4× `tegra264-mgbe` MACs (the 4× 25 GbE behind the devkit's **QSFP28 cage** — silicon real per [NVIDIA docs](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor), **all four DOWN, no cage populated**), 1× `eqos` (GbE class), 1× **Realtek r8126 = the RJ45 5 GbE port, also DOWN (no cable)**. Current link: **Wi-Fi only, 2.4 GHz (ch. 11), WiFi-6 2×2, PHY 229/207 Mbps, −64 dBm, RTT to gateway 1.6–7.6 ms** | `ip -br link`, device tree `ethernet@*` compatibles, `ethtool -i`, `iw dev wlP1p1s0 link`, `ping` |
| Storage | Internal NVMe (system, 343 GB free per the spike brief); 1.9 TB USB SSD at `/media/caseydigennaro/TOSHIBA EXT` for big caches | spike BRIEF, `ls` |

### The other seats (not measurable from here — facts from the brief)

- **ProArt** (the human's seat): Ryzen AI 9 HX 370, Radeon 890M iGPU, **RTX 4050 6 GB**,
  31 GB RAM, Windows 11 + WSL. The 4050 (Ada) has its own NVENC/NVDEC incl. AV1, so it
  is a *hardware decoder* for anything the Thor encodes — that half of the wire is real.
- **Cloud**: planner/engineer API calls on a budget. **Orin**: 8 GB, idle, spare.

---

## 1. Stage map of Infinigen's pipeline (from the code + published timings)

Infinigen is a *batch* system today: one Blender (`bpy`) process per task, state handed
through `scene.blend` on disk between tasks — `execute_tasks.py:217-221` reopens the
blend for every non-coarse task; tasks are `coarse → populate → fine_terrain → render /
ground_truth / mesh_save / export` (`generate_indoors.py:557-566`). Within `coarse`,
stages run under `RandomStageExecutor`, which already (a) times and counts
objects/instances per stage into `pipeline_coarse.csv`
(`core/util/pipeline.py:96-99`) and (b) makes each stage **deterministic** via
`FixedSeed(int_hash((scene_seed, stage_name)))` (`pipeline.py:41,84`) — the single most
important existing hook for the caching plan in §2.

| Stage (code path) | Cost profile | Parallelism | Evidence |
|---|---|---|---|
| **Constraint solving / scene composition** (`core/constraints/example_solver/`, `generate_indoors.py:188-307`) | Greedy simulated-annealing over discrete + continuous moves; pure Python driving Blender ops. Defaults 300/200/50 steps per stage *per room assignment* (`configs_indoor/base_indoors.gin:4-6`). Published: **≈2,281 s wall (~38 min) for 5k solver steps per scene** on the authors' hardware; ~100-min budgets scored higher ([Infinigen Indoors, arXiv:2406.11824, Table 3](https://arxiv.org/abs/2406.11824)). On 2.6 GHz ARM expect *worse*, not better (see §7) | Single process; internal caches (eval cache, plane hashing, BVH cache — the paper's ablations show 2–3× from them) bound the damage but it stays single-threaded | `solve.py:193-197` (the `for j in range(n_steps): optim.step(...)` loop) |
| **Room solving + solidifying** (`example_solver/room/{graph,floor_plan,solidifier}.py`) | Included above; produces the room meshes the rest decorates | Single-threaded | `generate_indoors.py:190-193` |
| **Asset generation** (`example_solver/populate.py`, `assets/**`) | Each placeholder realizes a factory → node graph → mesh (often boolean-cut against walls: `populate.py:23-43`). Cost scales with object count (paper: ~29–50 solved objects/scene *before* meshes); memory grows monotonically (`pipeline.py` records RSS per stage) | Per-object sequential; Blender mesh ops mostly single-thread; **shader/geometry-node evaluation is deferred to render/depsgraph time** | `populate_state_placeholders` |
| **Terrain coarse** (`terrain/`, `source/cuda/elements/*.cu`) | SDF kernels; a **CUDA path exists** (mountains, water, landtiles…) and a CPU path (`source/cpu/` — already compiled on this box by the spike) | GPU-parallel or multi-threaded CPU | `terrain/core.py:141+`; spike log "compiled lib/cpu/..." |
| **Terrain fine** (`fine_terrain`, OcMesher) | **Camera-aware octree SDF mesher** (C++): meshes only what cameras see, at view-dependent resolution; emits per-tile `glb` + displacement `.npy` (`execute_tasks.py:281-286` symlinks them forward). Heavy but *already view-dependent* — the natural LOD/impostor hook | Native, mostly single-process but compute-dense | `terrain/core.py:107-135`, `OcMesher/` |
| **Scattering / instancing** (`assets/scatters/*`, ~25 generators) | Density-driven particle/geometry-node scatters (grass, ferns, leaves…). Placement cost is CPU; the instances are evaluated **at render time** (memory-bandwidth bound in Cycles, cheap to store) | Placement partly parallel; evaluation in renderer | `generate_nature.py:481-617` stage list |
| **Materials / node evaluation** (`core/nodes/node_wrangler.py`) | Node graphs are cheap to *build*; evaluation happens inside Cycles on CPU/GPU. `resample_scene` can re-noise every material/scatter seed in place (`rendering/resample.py:27-52`) — the existing partial-variation mechanism | Renderer-dependent | `resample.py` |
| **Camera trajectories** (`placement/camera_trajectories.py`) | Search-based pose finding (`max_tries=50000` config) — CPU, minutes-class indoors | Single-threaded | `base_indoors.gin` (`max_tries=50000`) |
| **Mesh export** (`tools/export.py`, `execute_tasks.py:337-344`) | `export_scene` **applies all modifiers and realizes instances** (`export.py:39-70`) — the expensive step — then writes fbx/obj/**usdc/usda**/stl/ply; `save_meshes` writes per-frame OBJ+instances+camera JSON (datagen ground truth for training) | Single-threaded, memory-heavy | `export.py:29,55` |
| **Rendering** (`core/rendering/render.py`) | Cycles; device preference **OPTIX > CUDA > CPU** (`core/init.py:29-33`) — on Thor this is **CUDA-only** (no aarch64 OptiX SDK; spike builds sm_110 kernels). Defaults: 1280×720, up to 8192 samples adaptive (`configs_nature/base.gin:26-27,62`); indoors disables denoising (`base_indoors.gin` `denoise = False`) — and the spike's bpy build has OIDN **off** anyway | GPU-parallel (or CPU-parallel, slower) | code refs above; `thor/build-bpy.sh` header |
| **Ground-truth passes** (`datagen/customgt/`) | A **separate C++/GLSL OpenGL rasterizer** (own `main.cpp`, CMake) for depth/normals/optical-flow/segmentation — not Cycles; plus compositor passes in `render.py` | GPU (GL) + CPU compositing; headless on Jetson needs EGL — untested (§7) | `datagen/customgt/{main.cpp,CMakeLists.txt,glsl/}` |

**What the map says.** The interactive-killing costs are (1) the ~40–100-minute
Python solver, (2) per-task Blender relaunch + `scene.blend` serialize/deserialize,
(3) full-scene asset realization. The GPU is busy only in fine terrain, rendering and
the GT rasterizer. The solver and populate are *why* batch Infinigen can't be
interactive unmodified — everything else is cacheable or movable.

---

## 2. Placement: every stage and every new job, and the Infinigen changes that make it possible

The ux-day doctrine fixes the clocks: **talk ≤ 2 s, watch ≤ 5 s per card, workshop ≤ 60 s
with progress/cancel** (`~/lm-wt/ux-day/REPORT.md` §"three clocks"). Nothing that can't
hold a clock goes on it — it moves to the night queue. That single rule does most of
the placement work:

### 2.1 The day (interactive) — what runs where

| Job | Where | Clock | Why / what it needs |
|---|---|---|---|
| Companion/planner LLM (talk, plan chips, one-line confirms) | **Thor GPU, hot tier** | talk ≤ 2 s | Small local model resident (res-cad verified the aarch64 CUDA-13.2 torch stack). Cloud only for *engineer* calls, never on the talk clock |
| Critic (vision, verdicts) | **Thor GPU, hot tier** (downgrade-able, per ux-day's OOM recovery row) | watch ≤ 5 s | Reads renders the Thor itself produces — keep it next to the pixels |
| In-world day view | **ProArt RTX 4050 renders** a LOD/ghost scene; Thor only streams state | watch/workshop | See §3; needs the ghost/LOD export below |
| Preview renders (a recipe edit's before/after) | **Thor, Cycles-CUDA, low-spp, queued one-at-a-time** | workshop ≤ 60 s w/ progress + cancel | Needs the warm scene server; a 16-spp 480p flat render is already a config knob (`flat/render_image.override_num_samples = 16`) |
| Recipe edits / solver runs ( Architect re-arranging a room) | **Thor CPU, background**; small edits only | workshop (60 s) if one room; otherwise night | Needs incremental solving (below); the full solver is a night job, full stop |
| CAD parts, mesh cleanup, decimation, USD assembly, SFX audio | **Thor CPU lane** (Orin can take the night overflow) | night | Zero GPU (res-cad §1, §9) |
| Generative batches (image-to-3D props, textures, motion, music) | **Thor GPU, warm tier, batched by model** | night (workshop for single items) | The model scheduler of res-cad §9 |
| Human's IDE/terminal, dashboards, night feed, morning report | **ProArt CPU/browser** (static over the ledger) | watch | ux-day screens 5.2–5.6 are all "now" and need no 3D |

### 2.2 The night — what runs where

The vision's overnight loop (plan → sealed bets → keep/revert) with the GPU lane ordered
to feed dependencies (image-to-3D → textures → motion → audio, critic interleaved) and
the CPU lane never idle — exactly res-cad §9, no changes needed to that plan. **Orin
(8 GB, idle)** gets the CPU-lane overflow that doesn't need the Thor's memory or the
recipe store's latency: mesh cleanup/decimation of accepted assets, USD layer emission,
audio SFX batches, and the "watchtower" (budget/queue monitoring + the OOM/verdict
fallback judgments). Nothing GPU-model-shaped belongs on an 8 GB Orin.

### 2.3 The Infinigen modifications that make this placement possible

1. **Warm scene server (the big one).** Replace the per-task `bpy` relaunch +
   `scene.blend` round-trip (`execute_tasks.py:217-221`) with a resident process owning
   the open scene; other stages call into it. Infinigen's stage functions already take
   `(output_folder, scene_seed)` and mostly touch `bpy.data` — they are callable
   in-place once the file I/O boundary is gone. This is the difference between the
   workshop clock (seconds for an in-place edit) and batch latency (a fresh Blender
   launch per edit).
2. **Partial regeneration of only what an edit touched.** Two hooks already exist:
   `resample_scene` re-noises materials/scatters and re-realizes specific factories in
   place (`resample.py:27-52`), and the solver writes/reads a serializable
   `solve_state.json` (`generate_indoors.py:421`). Build: (a) room-scoped re-solve —
   re-run `solve_objects` for one room assignment (the greedy stages are already
   enumerated per assignment, `generate_indoors.py:195-208`) with the rest of the state
   frozen; (b) placeholder-scoped asset swap (delete + re-realize one placeholder's
   object, cutters re-applied via `populate.apply_cutter`).
3. **Stage caching keyed by recipe hash.** `RandomStageExecutor` is *one function away*
   from a content-addressed cache: it already hashes `(scene_seed, stage_name)` into the
   RNG (`pipeline.py:41,84`) and already writes per-stage timings. Add: key =
   `hash(recipe ⊕ gin config ⊕ stage_name ⊕ deps' keys)`, value = the stage's side
   effects (objects via a lightweight per-stage `.blend` library or USD layer + the CSV
   row). The existing `assets/` folder symlink between runs
   (`execute_tasks.py:198-211`) is this pattern's ancestor — same idea, formalized.
4. **LOD/impostor "ghost" pass for the day view.** The scene *already contains* the
   ghost layer: the `placeholders` collection of low-res markers is exactly the
   bounding-box world Casey's ideas file wants, and fine terrain is *already
   camera-dependent* (OcMesher meshes what the cameras see). Add an exporter that
   walks `placeholders` + room solids + scatter densities → glTF/USD with baked LODs;
   the recipe edit stream then updates transforms/tags as deltas. Blender's USD export
   exists in 4.2 but the spike's bpy build has `WITH_USD=OFF` (`thor/build-bpy.sh`
   apt-stage note) — glTF/OBJ/Ply paths are the near-term wire, USD needs the flag
   re-enabled in the build.
5. **GPU node evaluation.** Not really ours to build: shader/geometry-node evaluation
   rides Cycles/the depsgraph, so "GPU node evaluation" in practice = (a) keep
   evaluation where it already lands (render time), (b) keep *previews* on the ProArt's
   GPU via the LOD export, and (c) accept that headless EEVEE on Jetson (EGL) is
   unproven — treat as speculative until the spike or a follow-up proves it.

---

## 3. The wire between Thor and ProArt

The physical wire **today** is 2.4 GHz Wi-Fi: PHY 229/207 Mbps (measured), so realistic
TCP ≈ 90–140 Mbps, RTT ~3 ms. One cable into the r8126 RJ45 gives a 5 GbE path (driver
verified; port currently has no link). The QSFP28 4×25 GbE exists in silicon
(4 `tegra264-mgbe` MACs in the device tree) but has no cage populated and the ProArt has
no matching port — it is a future adapter + NIC purchase, not a plan dependency.

| | (a) Thor streams compact world state; ProArt renders | (b) Thor renders, streams video (NVENC) | (c) Hybrid — state by day, encoded pixels by night |
|---|---|---|---|
| **What crosses** | glTF/USD deltas: structure, transforms, instances, tags. Initial LOD scene ~10–100 MB (baked LODs + impostor textures); edits ≈ KB; renders pulled as PNG/WebP on view (~0.2–3 MB each) | H.265/AV1 video: 1080p60 ≈ 15–30 Mbps, 4K60 ≈ 50–80 Mbps (encoder-side choice) | (a)'s deltas by day + (b)'s clips/images on demand |
| **Fits today's Wi-Fi?** | Yes, trivially | 1080p60 yes (tight); 4K60 no | Yes |
| **Latency** | Initial world ~8 s warm (ux-day spec), then per-edit < 100 ms network; frame latency = the 4050's render (60 fps class) | Live nav: ~50–100 ms glass-to-glass *if* a real-time renderer exists on Thor — Cycles cannot, EEVEE-headless unproven. For **served** clips: zero (local playback) | Both properties where each applies |
| **Quality** | As good as the LOD bake — good for building, not photoreal | **Photoreal** (Cycles offline → NVENC) — the best possible image | Photoreal where pre-rendered, interactive everywhere |
| **Keeps ProArt free?** | No — the 4050 does the day-view rendering (it's the human's seat *and* the viewport; 6 GB VRAM means LOD discipline) | Yes — 4050 only hardware-decodes (Ada NVDEC incl. AV1) | Mostly |
| **Makes possible** | Free navigation; point-and-say chips; the camera-ray context packet; ghost work-order previews; provenance inspection; branch flip *if* each branch's LOD is pre-baked | Morning filmstrip at 60 fps anywhere (even phone/IDE panel); timelapses; cinematic walkthroughs; the night feed's video moments | The whole ux-day story: day = build (a), morning = gifts (b) |
| **Infinigen work needed** | The §2.3-4 LOD/ghost exporter + a thin render client on the ProArt | NVENC pipeline (GStreamer/jetson-multimedia, no service installs during research) + pre-rendered clip emission; live variant blocked on EEVEE-headless | Both, but each half is small |

**Recommendation: (c), weighted heavily toward (a).** The state stream is the
interactive backbone (every talk/watch/workshop interaction needs local pixels on the
ProArt), and NVENC is not a "live view" technology here — its honest job is the
*playback channel for pre-rendered truth*: the filmstrip, the timelapse, the branch
comparison clips. Almost everything the night produces is **images, not streams**, which
is even cheaper. Casey's "Thor renders, laptop is a television" framing is right for
the morning and wrong for the day: you cannot navigate a Cycles render, and an
unproven headless EEVEE should not be a dependency of the core loop. Also: **plug the
5 GbE RJ45** — a single cable makes every option comfortable and stops the 2.4 GHz
band being the system bus.

---

## 4. Casey's ideas, triaged

Verdicts: **practical now / practical later / speculative / wrong (with the killing
fact)**. Good kernels kept even where the framing dies. (Idea numbers follow the file's
own structure.)

| # | Idea (as filed) | Verdict | The facts |
|---|---|---|---|
| 1 | "Ghost preview pass": voxel/bounding-box layout streamed to the laptop; photoreal work queued to night | **Practical now** — with one substitution | The `placeholders` collection *is* the ghost layer and fine terrain is already camera-dependent (§2.3-4). Drop "voxelized": glTF/USD LODs are strictly better than voxels for this. This is move #3 in §6 |
| 2 | Kinematic solvers / physics-aware avatar micro-decisions on the 14 cores; cloud handles speech, Thor handles interaction | **Practical later** (and right in spirit) | Nothing in Infinigen does this; it's a sim layer to be chosen (and the vision deliberately keeps characters *out* of physics-writing). The talk-local / cloud-planner split matches vision.md exactly |
| 3 | Overnight metamorphosis + morning reveal | **Practical now** | This *is* the overnight loop (vision §5, ux-day §2–3); no hardware claim involved |
| 4 | "Zero-lag" WebRTC/NDI streaming of the internal 3D state window | **Practical later** for pre-rendered content; **speculative** for live nav | NVENC exists (verified incl. AV1), but live nav needs a real-time renderer on Thor that we don't have headless-verified (§3). Use NVENC for filmstrips/timelapses now-class |
| 5 | **OFA as a real-time mesh deformer** ("hardwired, without a single CUDA thread"; hands → force-field sculpting at 60 FPS) | **Wrong as framed** on this box | **No OFA device node exists** (`ls /dev` — isp/pva/nvenc/nvdec only). Also Jetson optical-flow paths run through the GPU/ISP stack, not a free-standing fixed-function OFA you can bind as a uniform buffer. *Kept kernel:* camera/hand input as a sculpt brush is a fine *software* feature — it just costs ordinary GPU/CPU like any other input |
| 6 | **Camera lanes as injection ports** (C-PHY/D-PHY, "20 feeds", "10× 4K60 decode without touching the GPU"; desk objects ingested from 3 angles → spawned as assets) | **Wrong as framed; kernel practical later** | **No cameras and no `/dev/video*` capture nodes exist** on this box; the "20 camera" figure is Thor's automotive *configurations*, not this devkit. *Kept kernel:* "put a mug on the desk → it appears in the world" is a great work-order UX — served by one ordinary USB webcam + the local vision model, no sensor-lane magic |
| 7 | **4× 25 GbE** ("100 Gbps", push video "straight to the laptop over one of the ports") | **Partly true, practically wrong today** | The 4× 25 GbE is real *silicon* (4 `tegra264-mgbe` MACs in DT; NVIDIA docs: one QSFP28 cage) — but nothing is populated, the ProArt has no such port, and the box is on 2.4 GHz Wi-Fi. And the loads don't need it: state ≈ KB/s, 1080p60 H.265 ≈ ≤30 Mbps (§3) |
| 8 | NVENC zero-copy frame delivery; laptop "decodes like a television" | **Practical now-class** (engineering, not research) | `/dev/v4l2-nvenc` + AV1/H.265/H.264 encode API verified locally; 4050 hardware-decodes all of it. Needs the GL/EGL→NVENC path for *live* viewports — for pre-rendered clips it's a plain GStreamer/ffmpeg script. Live nav still blocked by §3's renderer point |
| 9 | **"130 W max"** night power envelope | **True in spirit, verified** | Real modes: MAXN / 120 W / 90 W / 70 W (`nvpmodel.conf`); NVIDIA markets 40–130 W for the kit. Idle measured 25–28 W. See §5 |
| 10 | **"2,070 TFLOPS FP4"** sized for the world engine | **Misleading for this workload** | That's the sparse-FP4 *NN inference* figure. Cycles and the procedural pipeline are FP32/FP16; the Thor GPU is a capable but *mid* rasterizer next to a 4050-class dGPU. Size renders by the spike's measured tiles/s, never by this number |
| 11 | 273 GB/s unified LPDDR5X, zero-copy between agent tensors and mesh vertices, no PCIe bottleneck | **True and already how Jetson works** | Vendor-spec bandwidth; unified memory is the platform's default. The zero-copy *claim* is correct but costs nothing — it's not a differentiator to engineer for |
| 12 | 16 MB shared L3, "server-class" Neoverse single-thread | **Half-true** | 16 MB L3 is in NVIDIA's spec (not in sysfs); but 2.6 GHz ARM single-thread ≠ desktop x86 — the Python solver will run *slower* than the paper's x86 timings (Table 3 ≈ 38 min @ 5k steps). Do not size day-clock solver work on "server-class" |
| 13 | `.xyz`/graph text streams from laptop; "purely mathematical text, zero overhead" | **Practical now** (it's just the recipe protocol) | This is the recipe-as-source-of-truth from res-cad §8 — the one good idea in that whole "spatial database" section. The "RTX 4050 runs only custom shaders / 3D ASCII" dressing is noise; the real client is a small glTF renderer |
| 14 | UDP raw-input daemon on the laptop, worker pinned to Thor core 0, packets into L3 | **Over-engineered; harmless kernel** | A keyboard hook + TCP is microseconds against a 2 s talk clock — the machinery is unjustified. *Kept kernel:* input stays cheap on the laptop, all state lives on the Thor — that part is exactly right |
| 15 | Real-world room geometry as generation constraints ("Constraint Engine" from camera capture of the office) | **Speculative — park it** | No cameras (fact above); room capture is solvable later with one webcam or a tape measure if the idea ever earns priority; privacy rules in ideation B would govern it anyway |
| 16 | **OptiX on Thor** (client-server section) | **Wrong** | No aarch64 OptiX SDK; spike builds Cycles **CUDA-only** at sm_110 (`thor/build-bpy.sh` header). Nothing OptiX-shaped will load |
| 17 | "Cloud dreams, ProArt edits light structures, Thor compiles at night" | **Practical now** — it's the architecture | Matches vision.md's three layers and §2's placement table almost exactly. The best-formed idea in the file |

**Pattern.** The file's *architecture* instincts (thin client, day/night split, night
bake, recipe-not-meshes over the wire) are sound and match the vision. The *hardware*
storytelling (OFA deformer, camera injection ports, 4×25 GbE as a plug-in port, 2,070
TFLOPS sizing) is automotive-marketing material that mostly dies on contact with this
devkit — every surviving piece of it is cheaper as ordinary software on the GPU/CPU we
verified.

---

## 5. The day/night power plan (mapped to the real modes)

Measured baseline: idle with desktop ≈ **25–28 W** (`VIN` rail), GPU rail at 0 mW,
CPU+SoC rail ~10–12 W. Real modes from `/etc/nvpmodel.conf`: **0 = MAXN (unconstrained),
1 = 120 W, 2 = 90 W, 3 = 70 W**. Sustained draw under real GPU+CPU load is *not yet
measured* — the spike's `run-timed.sh` already wraps every stage with tegrastats at
1 Hz, so those numbers arrive with its first timings (§7).

**Day (interactive), mode 2 (90 W), DVFS left alone:**
- Must stay responsive: the talk-clock LLM + critic (hot tier, ~single-digit GB),
  the preview queue (**one** Cycles-CUDA preview job at a time, low-spp), NVENC for
  any peek clip. That fits comfortably in 90 W with boost headroom, because none of it
  is sustained-all-core.
- Do **not** run `jetson_clocks` by day: it pins max clocks and max fan; interactive
  latency needs *burst* headroom, not pinned heat.
- Reserve rule: if the budget bar (ux-day) would push a > 60 s job onto the screen
  clock, it goes to the night queue instead — the power plan and the clock plan are the
  same plan.
- Mode 3 (70 W) is the "quiet afternoon / Magnus is watching" fallback: same
  architecture, longer workshop queue.

**Night (unthrottled), mode 0 (MAXN) + `jetson_clocks` (locked clocks, max fan):**
- The batch window owns the box after the client detaches (ux-day: "the scheduler waits
  for the client to detach before the big batches"). GPU lane drains model-by-model
  (res-cad §9), CPU lane runs CAD/cleanup/USD/audio continuously, Orin takes CPU-lane
  overflow. MAXN lets the SoC use its full ~130 W class envelope; if sustained
  throttling shows up in tegrastats under MAXN, drop to mode 1 (120 W) — a measured
  decision, not a guess.
- The 2 a.m. peek costs nothing: the feed is ledger reads (ux-day §2) — no GPU
  contention, no mode change.

**Morning burst:** stay MAXN until the human detaches — branch flips are USD/recipe
pointers plus pre-baked LODs (≤ 2 s flip, ≤ 15 s re-stream per ux-day #8), then the
first day-mode budget resumes. Mode switches are one `nvpmodel -m` call each; the
core service should own them as part of the night queue's begin/end (and log the mode
beside every timing, per the carried-over rule "measure with the box's load beside the
number").

---

## 6. The top 5 burden-shifting moves, ranked by (user-felt benefit) / (effort)

1. **Warm resident scene server** — kill the per-task Blender relaunch and the
   `scene.blend` round-trip (`execute_tasks.py:217-221`); keep the solved scene open in
   a service the builders call into. *Benefit:* every workshop-clock interaction
   (edits, previews, partial re-solves) drops by the whole launch+I/O tax; the day UX
   becomes possible at all. *Effort:* moderate — the stage functions are already
   in-place-callable once the file boundary is gone. *Measure:* p50/p95 edit→preview
   latency batch-vs-warm on the same recipe edit; Blender process starts per night
   (target: 1–2, vs ~1 per task today).
2. **Recipe-hash stage cache + partial regeneration** — key on
   `hash(recipe, gin, stage, dep-keys)`; re-solve only the touched room; re-realize
   only the touched placeholders (`resample.py`, per-assignment greedy stages, and
   `solve_state.json` are the existing hooks). *Benefit:* night throughput multiplies
   (untouched stages never re-run), morning branch flips are ≤ 2 s pointers, and a
   builder's "change one room" bet costs minutes, not the ~40-min full solve
   (paper Table 3). *Effort:* moderate. *Measure:* wall time of "edit one room"
   end-to-end vs full regeneration; stage-cache hit rate per night.
3. **Ghost/LOD glTF export for the day view (the ProArt renders)** — walk
   `placeholders` + room solids + scatter densities into baked-LOD glTF; stream deltas.
   *Benefit:* the entire day half of ux-day (walk, point-and-say, ghost work orders,
   provenance) with the Thor's GPU left for models and previews. *Effort:* moderate
   (exporter path exists; USD needs a build flag, glTF doesn't). *Measure:* export time
   and bytes per scene; ProArt fps and VRAM on the 4050; initial world-load ≤ 8 s warm.
4. **Plug the 5 GbE RJ45 + stand up the NVENC clip channel** — one cable (driver
   verified) replaces 2.4 GHz Wi-Fi as the system bus; a small encode script turns the
   night's renders into filmstrip/timelapse clips the ProArt hardware-decodes. *Benefit:*
   every video-class moment (peek clips, morning filmstrip at 60 fps) stops competing
   with Wi-Fi; zero risk to the core loop. *Effort:* trivial + small. *Measure:* iperf
   TCP Thor↔ProArt (needs a minute of the human's cooperation); glass-to-glass latency
   and dropped frames over a 10-min 1080p60 playback.
5. **Night scheduler lanes: GPU batched-by-model, CPU lane always busy, Orin overflow**
   — res-cad §9 as written, plus Orin as the CPU-lane spare and watchtower. *Benefit:*
   roughly doubles usable night GPU-hours for free (weight-swap thrash is the real
   constraint on a 122 GB box), and CPU work never queues behind GPU work. *Effort:*
   moderate. *Measure:* model-load count per night (target: 1 per model); GPU-hours
   consumed vs the budget bar; CPU-lane utilization; morning report's "5.3 of 5.5 GPU-h"
   line becoming trustworthy.

(Honorable mention, not top-5 only because it *is* #2's prerequisite: the recipe as
source of truth compiling deterministically to USD layers — res-cad §8 already argued
it and nothing here contradicts it.)

---

## 7. What in this plan depends on the spike's numbers

`thor/SPIKE.md` **did not exist** when this report finished (checked 22:30, 2026-10-30);
the build is mid-flight on the external drive (CPython 3.11 ✅, OpenImageIO ✅, terrain
CPU extensions ✅, bpy wheel ⏳). My plan's dependencies, ranked by how much they move:

1. **Cycles-CUDA throughput at sm_110** — decides whether Thor-side *preview* renders
   can hold the 60 s workshop clock (move #1's payoff), or whether previews must
   render on the ProArt through the LOD path (move #3) with the Thor CPU-only for
   geometry. Everything in §2.1's preview row scales on this number.
2. **Hello Room / Hello World stage timings on aarch64** — my solver cost cites the
   paper's x86 ≈ 38 min @ 5k steps; if Thor is 2–4× slower there, room-scoped
   re-solving (§2.3-2) goes from "nice" to "the only way the Architect ever works at
   day," and the night budget bar needs re-anchoring.
3. **Peak RSS per warm scene** — decides how many worlds/branches stay resident in
   122 GB (move #1's memory ceiling, and how many pre-baked branches the morning can
   hold).
4. **bpy 4.2 on aarch64 at all** — the whole §2 placement assumes it lands; every
   alternative (Blender 4.0.2 from apt + API shims, or x86 emulation) changes the plan
   materially.
5. **EEVEE-headless (EGL) viability** — only affects §3's live-video *variant*; the
   recommendation (state-stream + pre-rendered clips) deliberately does not depend on
   it.
6. **Sustained power draw under GPU load** (tegrastats, already collected by
   `run-timed.sh`) — decides MAXN vs 120 W for the night window in §5.

---

## Sources

- Local code: `~/src/infinigen-thor` @ `thor-spike` (read-only) —
  `src/infinigen/core/execute_tasks.py`, `core/util/pipeline.py`,
  `core/constraints/example_solver/{solve,populate}.py`, `core/rendering/resample.py`,
  `core/init.py`, `terrain/core.py`, `tools/export.py`, `datagen/customgt/`,
  `src/infinigen_examples/generate_indoors.py`, `configs_indoor/base_indoors.gin`,
  `configs_nature/base.gin`, `thor/{BRIEF.md,build-bpy.sh,run-timed.sh}`.
- Local research: `~/src/builder-ide/docs/vision.md`; `~/lm-wt/ux-day/REPORT.md`
  (three clocks, night feed, moments table); `~/lm-wt/res-cad/REPORT.md` (model
  scheduler, USD/recipe, verified torch/CAD wheels); `~/lm-wt/split/casey-ideas-fromgoogle5.md`.
- Measurements: all commands quoted in §0–§5, run on this Thor 2026-10-30 ~22:20
  (`nproc`, `lscpu`, `/proc/meminfo`, `nvidia-smi`, `nvpmodel -q`, `tegrastats`,
  `ip -br link/addr`, `ethtool -i`, `iw … link`, `ping`, `ls /dev`, device tree,
  `/etc/nvpmodel.conf`, `/usr/src/jetson_multimedia_api` headers).
- External: [Infinigen Indoors (arXiv:2406.11824)](https://arxiv.org/abs/2406.11824)
  (solver timings, Table 3; UE5/Isaac export rates), [Infinigen (arXiv:2306.09310)](https://arxiv.org/abs/2306.09310),
  [NVIDIA Jetson AGX Thor product page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-thor)
  (2070 FP4 TFLOPS, 128 GB/273 GB/s, PVA v3, 40–130 W, QSFP28 4×25 GbE + 5 GbE RJ45,
  dual NVENC/NVDEC, 16 MB L3), NVIDIA Jetson Thor Features Guide (developer.nvidia.com).
