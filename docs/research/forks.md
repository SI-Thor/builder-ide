# REPORT: scouting the Infinigen fork network for nuggets of gold

**Date:** 2026-10-30 · **Author:** the lab seat (`~/lm-wt/forks`)
**Scope:** read-only survey of [princeton-vl/infinigen](https://github.com/princeton-vl/infinigen) and its fork
network, for the Thor-native Infinigen plan (`SI-Thor/infinigen-thor`, branch `thor-spike`).
**Method:** GitHub REST API (`gh api`) for the fork list and upstream PRs; `git ls-remote` for every
fork's branch heads; blobless shallow clones into `/tmp/inf-forks/clones` to measure exact
ahead/behind commit counts and read the diffs. **Nothing was forked, starred, commented on, or
otherwise written to GitHub.** No sub-agents.

---

## 0. Headline

**There is exactly one fork in this network that matters to the plan, and it is not the one you
would guess.** It is not the ARM fork and it is not the GPU fork — because there are none.

1. **[tangos302/infinigen](https://github.com/tangos302/infinigen) — the "maquette" branch already
   contains a working prototype of our builders layer** (vision.md §3–§5): an LLM that writes
   Blender build scripts against a closed catalog of factories, a **work-order queue** for
   factories it does not have, a **subprocess implementer** that writes the missing factory, a
   **phase-checkpoint** mechanism for live scene evolution, and a **production-grade LOD /
   instancing / Draco bake** for a browser client. It is ~58k LOC and it is not production-hardened,
   but the *architecture* is the thing we spent the plan designing, and someone already built it.
2. **[vlordier/infinigen](https://github.com/vlordier/infinigen)** gives us the **compute-platform
   preset pattern** — the exact gin slot our Thor needs — plus the first **ARM-class** port work
   (Apple Silicon M4), an **arm64 Docker** path, and a **Blender 4.5 LTS** port.
3. A handful of **cheap, real bug fixes** upstream has not merged, one of which (the Blender
   Boolean solver) can silently hang a night.

**The most important negative finding: there is no GPU-acceleration nugget in this network.**
No fork anywhere uses NVIDIA Warp; no fork rewrites Infinigen's terrain, scattering or node
evaluation for the GPU; no fork targets aarch64-Linux or Jetson. Our IDEAS.md #2 (port one terrain
element to Warp) and #4 (live camera-aware re-meshing) have **no prior art to harvest** — we
would be writing them from scratch. That is worth knowing before we spend days looking.

---

## 1. The landscape, measured

| | count |
|---|---|
| Forks returned by the API | **730** (the repo's own counter says 622 — the API list includes forks-of-forks and stale entries) |
| Forks whose every branch is an exact upstream ref → **untouched** | **199** |
| Forks with ≥1 branch whose tip is unknown to upstream | **531** |
| Forks with **≥2** divergent branches | **43** |
| Forks cloned and measured exactly (ahead/behind per branch) | **68** |
| Forks with measurable divergence | 61 |
| Forks with any star | 41 (max **3**; 689 have none) |
| Forks with a non-default description | 0 (all inherit upstream's) |

**Social signal in this network is nil.** A fork with two or three stars and upstream's description
is indistinguishable from an untouched fork by metadata alone. Everything below was found by reading
code, not by reading popularity. `SI-Thor/infinigen-thor` is itself the most recently pushed fork
in the network (2026-10-31).

### Ranking by commits ahead of `upstream/main`

Measured per branch with `git rev-list --count upstream/main..<branch>`; best branch per fork shown.
"behind" = commits upstream has that the fork lacks (i.e. how stale the fork's base is).

| # | Fork | ahead | behind | best branch | what it is |
|---|---|---|---|---|---|
| 1 | [Debangan-MishraIIIT/infinigen](https://github.com/Debangan-MishraIIIT/infinigen) | 1666 | 1927 | `dataset_gen` | mass indoor dataset generation |
| 2 | [vlordier/infinigen](https://github.com/vlordier/infinigen) | **430** | 220 | `main` | urban/city generator family |
| 3 | [tangos302/infinigen](https://github.com/tangos302/infinigen) | **168** | 220 | `maquette-eroded-terrain` | **LLM-driven scene pipeline** |
| 4 | [chang-xinhai/infinigen](https://github.com/chang-xinhai/infinigen) | 61 | 220 | `nsl` | neural RGB-D benchmark + PLY export |
| 5 | [divisonofficer/infinigen](https://github.com/divisonofficer/infinigen) | 56 | 219 | `robomituba/datagen` | material/weathering quality pass |
| 6 | [JiazheZhang/infinigen](https://github.com/JiazheZhang/infinigen) | 52 | **3434** | `windows_readme` | stale (2023) |
| 7 | [curioushi/infinigen](https://github.com/curioushi/infinigen) | 42 | 1741 | `truck` | robot pick/place, stale |
| 8 | [hh74/infinigen](https://github.com/hh74/infinigen) | 33 | 3434 | `gt_visualization_and_summary` | stale |
| 9 | [BabyBlue26/infinigen-3d-worlds](https://github.com/BabyBlue26/infinigen-3d-worlds) | 28 | 3434 | `main` | stale |
| 10 | [clingto7/infinigen](https://github.com/clingto7/infinigen) | 26 | **1** | `main` | **agent workflow + generator UI** |
| 11 | [Nolicx/infinigen](https://github.com/Nolicx/infinigen) | 23 | 220 | `export-to-gate` | operating-room scene generator |
| 12 | [KaliberAI/infinigen](https://github.com/KaliberAI/infinigen) | 19 | 355 | `aug4_stable` | local scheduling + fast-solve presets |
| 13 | [crypticsymmetry/infinigen](https://github.com/crypticsymmetry/infinigen) | 16 | 220 | `main` | VFX matting + rigged humans |
| 14 | [m-and-m-lab/infinigen](https://github.com/m-and-m-lab/infinigen) | 16 | 221 | `main` | USD articulated export |
| 15 | [dyslexai-cardnl/syntrain-infinigen](https://github.com/dyslexai-cardnl/syntrain-infinigen) | 11 | 220 | `autosave/wip` | MEP asset factories |
| 16 | [hdoi5324/infinigen](https://github.com/hdoi5324/infinigen) | 10 | 704 | `main` | water shader, flat shading |
| 17 | [neulbit/infinigen](https://github.com/neulbit/infinigen) | 8 | 166 | `sirem` | Docker / GHCR publish |
| 18 | [samsartor/infinigen](https://github.com/samsartor/infinigen) | 7 | 656 | `auto-aovs` | automatic AO V |
| 19 | [jose-loci/infinigen](https://github.com/jose-loci/infinigen) | 6 | 656 | `jose/infinigen-blender-plugin` | Blender add-on |
| 20 | [ysysimon/infinigen](https://github.com/ysysimon/infinigen) | 6 | 220 | `ysy` | USD prim path export |
| 21 | [DiegoGomesDG/infinigen](https://github.com/DiegoGomesDG/infinigen) | 4 | 219 | `stable` | **CUDA terrain + compile fixes** |
| 22 | [mathisdhaene/infinigen-fork](https://github.com/mathisdhaene/infinigen-fork) | 3 | 219 | `main` | BEDLAM360 agent planning freeze |
| 23 | [folouiseAWS/infinigen](https://github.com/folouiseAWS/infinigen) | 2 | 219 | `fix/populate-cutter-visibility-guard` | **Boolean solver hang fix** |
| 24 | [preimage-ai/infinigen](https://github.com/preimage-ai/infinigen) | 2 | 656 | `darshan/struct-lang` | structured room language |
| 25 | [ebajemon-tw3/infinigen](https://github.com/ebajemon-tw3/infinigen) | 1 | 166 | `macos-arm64-fixes` | **ARM terrain build fix** |

Also divergent but not worth a clone: [frankclong/infinigen](https://github.com/frankclong/infinigen)
(warehouse generator, 2024), [zloop1982/infinigen_work](https://github.com/zloop1982/infinigen_work)
(Windows, 2023), [shuhanmomo/infinigen](https://github.com/shuhanmomo/infinigen) (facades),
[neulbit/infinigen](https://github.com/neulbit/infinigen) (SIREM integration), [hapham258/infinigen](https://github.com/hapham258/infinigen)
(IMU trajectories), [krishi-saripalli/infinigen](https://github.com/krishi-saripalli/infinigen)
(generator parameter abstraction), [Roboticc-Apps/infinigen](https://github.com/Roboticc-Apps/infinigen)
(scene-from-parameter-dict), [ATphobia22/infinigen](https://github.com/ATphobia22/infinigen)
(docs images), [SkyGao2005/infinigen](https://github.com/SkyGao2005/infinigen) (grafiq custom).

**Staleness rule of thumb:** anything `behind ≥ 700` predates upstream's `src/` layout move and
the Infinigen2 rewrite; treat it as inspiration, not as a cherry-pick source.

---

## 2. The nuggets, ranked

### N1 — tangos302: the builders layer, already built ⭐ highest value

**Fork:** [tangos302/infinigen](https://github.com/tangos302/infinigen) ·
**branch:** [`maquette-eroded-terrain`](https://github.com/tangos302/infinigen/tree/maquette-eroded-terrain)
(168 commits ahead) · **package:** `infinigen/maquette/`, 157 Python files, ~58,400 LOC,
102 factory modules (66 "native" low-poly + 36 "realistic") + `runtime/` + `pipeline/`.

This is a working implementation of exactly the three-layer architecture in vision.md §"The
architecture": an LLM in the middle, a closed typed vocabulary of generators, and a chief-engineer
path that extends the vocabulary.

| Piece | File | What it does |
|---|---|---|
| **The vocabulary** | [`infinigen/maquette/pipeline/factories_guide.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/pipeline/factories_guide.py) | Auto-generates `FACTORIES_GUIDE.md` by **AST-walking** the factory modules (never importing them — keeps it Blender-free), extracting each factory's docstring "pitch", its `_<X>_ARCHETYPES` tuple, `_ARCHETYPE_DEFAULTS` and constructor knobs. **Prompt-aware filtering**: tokenizes the user's prompt, ranks factories by keyword overlap, gives full signatures to hits and one-liners to the rest — "typically halves the catalog token weight". |
| **The work-order queue** | [`infinigen/maquette/pipeline/gap_tracker.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/pipeline/gap_tracker.py) | When the builder hits a missing factory it appends a `REQUESTED_ASSET:` row to a project-level `requested_assets.md` (factory, first seen, last seen, count, spec). Deduplicated across runs. |
| **The engineer** | [`infinigen/maquette/pipeline/implementer.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/pipeline/implementer.py) | Spawns `claude -p` with full tool access to implement the missing factory: read 2–3 sibling factories for conventions, write the new module, register it in both `__init__.py` files, write and run a smoke test. |
| **The entry point** | [`infinigen/maquette/pipeline/cli.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/pipeline/cli.py) | `python -m infinigen.maquette.pipeline.cli "small medieval village by a stream"` → Claude writes a Blender build script → run → render. `--no-render`, `--model`, `--local`. |
| **Live evolution** | [`infinigen/maquette/runtime/checkpoint.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/runtime/checkpoint.py) | `checkpoint('terrain')` exports the current scene to `map.obj` and writes a phase marker; the frontend cache-busts on the marker, so the user watches terrain → foliage → buildings → final. No-op when the env var is unset. |
| **The thin-client wire** | [`infinigen/maquette/runtime/lod_bake.py`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/runtime/lod_bake.py) | 4-level LOD chain, instance batching, `KHR_mesh_quantization`, Draco, KTX2, and a `scatter.json` manifest listing InstancedMesh templates. Shells out to canonical tools (Blender's glTF exporter, `gltf-transform`, `toktx`) rather than reimplementing them; degrades gracefully if `gltf-transform` is missing. Has **measured numbers** (terrain GLB ≈ 5.7 MB after compression; simplify 12k→4k verts). |
| **CPU terrain path** | `infinigen/maquette/terrain/{sdf,marching,features,composition}.py`, `runtime/eroded_terrain.py` | SDF → marching-cubes → Blender, in Python/scipy. A CPU sibling to the CUDA terrain path. |
| **Settlement** | `infinigen/maquette/runtime/village_wfc.py`, `village_tile_wfc.py` | Wave-function-collapse house settlement. |
| **The gap spec** | [`infinigen/maquette/SCENE_PROMPTS.md`](https://github.com/tangos302/infinigen/blob/maquette-eroded-terrain/infinigen/maquette/SCENE_PROMPTS.md) | A running prompt→gap analysis: "prompts that were ACTUALLY built via MCP", which factories exist, which are missing, and the parametric spec for each missing one. |

**How it fits our plan.** This *is* vision.md §4 (the builders) + §5 (the overnight loop) + §"the
engineer's work order" — already built, by someone else, for the same reason we designed it.
Concretely:

- `factories_guide.py` is a **drop-in answer to "the closed, typed vocabulary"** — and the AST
  approach is what makes it viable for a *small local LLM on the Thor*: the catalog is generated,
  not hand-written, and prompt-filtered so the context stays small. This is the piece that most
  directly de-risks our hot tier.
- `gap_tracker.py` + `implementer.py` are the **work-order loop** ("a character that hits a limit
  files a work order; the engineer takes it, builds and tests it in the background, and promotes
  it into the vocabulary"). The `requested_assets.md` table is the queue; the implementer is the
  engineer.
- `lod_bake.py` is **split.md §2.3-4's "LOD/impostor ghost pass for the day view"**, already
  written and already measured — the single hardest *external* piece of our ProArt wire.
- `checkpoint.py` is a cheap, working answer to "the scene should evolve in front of you".

**Licence.** BSD-3-Clause (same as upstream; verified) for all code. **But** `infinigen/maquette/runtime/textures/`
is **35 MB of 47 third-party texture files** — those are *not* covered by the repo's BSD licence and
must be re-licensed or dropped before anything ships. Per our own rule ("licences are a checked
list"), treat the textures as **not** harvested.

**Effort.** Two different answers depending on what we take:

- *Take the four pipeline files* (`factories_guide.py`, `gap_tracker.py`, `implementer.py`, `cli.py`
  ≈ 1.5k LOC): **1–3 days** to port, re-path and re-target at our local model. This is the
  recommended move.
- *Take the whole package* (58k LOC, 102 factories): **weeks**, and it would drag their repo layout,
  their `songe-core` host assumptions, and 35 MB of unlicensed textures in with it. Not recommended.

**Quality / risk — read this before you plan around it.**

- **No tests.** The maquette package ships none; the repo's `tests/` are upstream's.
- **The implementer's wiring is incomplete.** `cli.py --local` is documented in its own docstring as
  "NOT YET IMPLEMENTED in phase 1". The machinery exists; the loop is not closed.
- **It is coupled to `claude -p`** by design (their runner says so explicitly: "lets us swap in any
  Claude Code-compatible backend without rewiring the pipeline"). We want a local model on the Thor —
  that seam is exactly the one we would replace.
- **Hardcoded paths**: `FORK_ROOT` is computed relative to the file, but the implementer's prompt
  template hardcodes `/home/tang/songe/_artifacts/maquette/infinigen-fork`, and `checkpoint.py`
  expects a `MAQUETTE_OUT_DIR` with a `songe-core` layout.
- It targets the pre-`src/` layout (base commit 2026-04-28, 220 commits behind upstream main).
- Quality signal is mixed: real engineering in the pipeline files, but the commit history contains
  "fix(WFC settlement): hoist settlement_archetype_runtime above make_proto loop (every house
  prototype failed with unbound free variable → 0 houses → market/town scenes always failed)"
  ([5268c1c10a1d](https://github.com/tangos302/infinigen/commit/5268c1c10a1d83818bcfc66551ce0108818591ec)) — i.e. the *scene
  output* was broken for a while and the fix is recent.

**Verdict: harvest the pattern and the four pipeline files. Treat the 58k LOC as a catalogue, not
as a dependency.**

---

### N2 — vlordier: the compute-platform preset (our Thor's `.gin`) + the first ARM-class port

**Fork:** [vlordier/infinigen](https://github.com/vlordier/infinigen) — 11 divergent branches, 430
commits ahead on `main`.

#### N2a — the compute-platform slot (highest practical value, minutes of work)

Upstream already has the right shape:
[`src/infinigen/datagen/configs/compute_platform/`](https://github.com/princeton-vl/infinigen/tree/main/src/infinigen/datagen/configs/compute_platform)
contains `local_16GB.gin`, `local_64GB.gin`, `local_128GB.gin`, `local_256GB.gin`, plus `slurm*.gin`.
**vlordier adds the first non-memory-tiered one**, keyed on *compute architecture* rather than RAM:

[`local_apple_silicon.gin`](https://github.com/vlordier/infinigen/blob/apple-silicon-m4-optimizations/infinigen/datagen/configs/compute_platform/local_apple_silicon.gin)
— 17 lines:

```gin
include 'infinigen/datagen/configs/compute_platform/local_64GB.gin'

manage_datagen_jobs.num_concurrent = 4
LocalScheduleHandler.jobs_per_gpu = 2
LocalScheduleHandler.use_gpu = True

queue_combined.cpus = 6
queue_combined.mem_gb = 10

queue_render.cpus = 8
queue_render.gpus = 1
```

Plus [`performance/apple_silicon.gin`](https://github.com/vlordier/infinigen/blob/apple-silicon-m4-optimizations/infinigen_examples/configs_nature/performance/apple_silicon.gin)
(10 lines) for render settings.

**How it fits.** This is *exactly* the file our Thor needs and the upstream schema is already
built for it. A `local_thor.gin` is a 15-line file: `num_concurrent` tuned to the 14 Neoverse
cores and the unified 122 GB pool, `jobs_per_gpu = 1` (one GPU, shared with the hot models),
`queue_combined.mem_gb` set generously because memory is unified, and `LocalScheduleHandler.use_gpu
= True`. It is the concrete artifact that turns "the Thor runs the night" into a config.
**Licence:** BSD-3. **Effort:** under an hour. **Risk:** none — it is a new file, not a patch.

#### N2b — ARM-class port work

| Commit / branch | What | Portable to Thor? |
|---|---|---|
| [`bc2e76155444`](https://github.com/vlordier/infinigen/commit/bc2e761554445fe158f7bf36d7889e9e0745ccee) "Add linux/arm64 Docker support" (branch [`copilot/update-docker-linux-arm64`](https://github.com/vlordier/infinigen/tree/copilot/update-docker-linux-arm64), open [PR #485](https://github.com/princeton-vl/infinigen/pull/485)) | `Dockerfile` + `Makefile` + `docs/Installation.md`, `TARGETARCH` fallback, pinned Miniforge, uv-based Dockerfile | **Yes** — buildx `linux/arm64` is aarch64 |
| [`1dbcd52d3a8f`](https://github.com/vlordier/infinigen/commit/1dbcd52d3a8f670e4586b6b1423eb04384c391e5) "Add Apple Silicon M4 performance optimizations" | `core/init.py` denoiser fallback OPTIX→OPENIMAGEDENOISE; `compile_terrain.sh` `-mcpu=native -ffast-math`; `setup.py` Cython `extra_compile_args`; `customgt/CMakeLists.txt` arm64 flags; `submitit_emulator.py` local-GPU modelling without `nvidia-smi` | **Partly** — the *shape* yes, the flags are Darwin-specific |
| [`167e947440fd`](https://github.com/vlordier/infinigen/commit/167e947440fd61b5a916cb783caf19a5ba830e46) | `core/init.py`: **denoiser fallback chain** `OPTIX → OPENIMAGEDENOISE` | **Yes — take it.** split.md records that on Thor there is no aarch64 OptiX SDK, and that indoors disables denoising outright and the spike's bpy build has OIDN off. Upstream's `try: denoiser="OPTIX" except: warn` leaves the denoiser unset on failure; this makes it explicit and logs which one won. |
| [`1fa945f6dd65`](https://github.com/vlordier/infinigen/commit/1fa945f6dd65c68c133140ceea1ae6385759376f) | Dockerfile `TARGETARCH` fallback, Miniforge pin | Yes |
| [`6498b82f216f`](https://github.com/vlordier/infinigen/commit/6498b82f216fee432dc24a252db3112ce279300b) "Fallback to bundled snow when real_snow is unavailable" | `assets/scatters/snow_layer.py` | Yes — a robustness fallback |
| [`09e3790a3cc4`](https://github.com/vlordier/infinigen/commit/09e3790a3cc44c796398da79a3a696289a7332e7) "chore: upgrade Blender/bpy from 4.2.0 to 4.5.0 LTS" (branch [`copilot/upgrade-blender-to-4-5-lts`](https://github.com/vlordier/infinigen/tree/copilot/upgrade-blender-to-4-5-lts)) | bpy 4.2→4.5, plus **607 lines of non-regression tests** (`tests/test_blender_version_compatibility.py`) and 354 lines of benchmarks | **Defer** — we target 4.2. But the *test file* is worth mining: it is a ready-made bpy-version compatibility harness, which we will need if we ever move off 4.2. |

**Caveat on `-ffast-math`.** The ARM compile flags add `-ffast-math`, which changes floating-point
results. IDEAS.md Rule 1 requires a GPU/CPU port to produce **identical meshes for the same seed**;
`-ffast-math` in the CPU terrain build would break bit-exactness against a reference. If we adopt
the flag, it must be applied to the *reference* build too, or not at all.

**Also in `core/init.py`:** a genuine upstream bug — `require_blender_addon()` is missing a
`return False` after `report_fail(...)`, so a failed addon install falls through and continues.

#### N2c — the urban generator family (`main`, 430 commits)

[`infinigen/assets/urban/`](https://github.com/vlordier/infinigen/tree/main/infinigen/assets/urban) —
32 modules: OSMnx real road networks from OpenStreetMap
([`3e22cdc50b69`](https://github.com/vlordier/infinigen/commit/3e22cdc50b69b0a0a019c9b8590c5665b540e704)), DCEL planar topology,
RoadMesher / IntersectionMesher, block subdivision, building lots, city style presets
(MedievalOrganic / SovietBlock / SuburbanCulDeSac / GardenPlots / SparseOrganic), real DEM terrain
from `.npz` heightmaps (Monaco, Narwa, Warsaw, St-Paul —
[`fbb657a5dc2c`](https://github.com/vlordier/infinigen/commit/fbb657a5dc2c3b7a6e8caf3991f0b576b5a24fb5)), cars, streetlights,
road markings, landmarks, and an **OpenDRIVE exporter**
([`bade5d593654`](https://github.com/vlordier/infinigen/commit/bade5d59365423e5060be4b7103db4eb35cbe2e2), the ASAM standard used
by driving simulators).

Also note vlordier's own working method: [`docs/superpowers/specs/` and
`docs/superpowers/plans/`](https://github.com/vlordier/infinigen/tree/main/docs/superpowers) — a
design-spec-then-plan-then-implement loop.

**How it fits.** Parked. It is a large, self-contained new generator family and a real
game-engine/sim exporter, but our plan is Indoors + terrain + the builders — not cities. **Effort:**
high. **Licence:** BSD-3 for code; the four `.npz` DEM assets need their own provenance check, and
`osmnx` is a new dependency.

---

### N3 — folouiseAWS: the Boolean solver that can hang a night

**Fork:** [folouiseAWS/infinigen](https://github.com/folouiseAWS/infinigen) ·
**commit:** [`d52fac4963af`](https://github.com/folouiseAWS/infinigen/commit/d52fac4963afb2bd9b718cfb2a04a2aaa6aee16d)
"populate: use EXACT solver for cutter booleans to avoid silent infinite hang" ·
**open upstream [PR #498](https://github.com/princeton-vl/infinigen/pull/498)**

One line in `infinigen/core/constraints/example_solver/populate.py` (`apply_cutter`), plus a
CHANGELOG entry. The reasoning, quoted from the commit message:

> The Blender Boolean modifier's FAST solver (legacy BMesh CSG) can enter an infinite loop in C++
> when given degenerate or near-degenerate geometry. No Python exception is raised; the worker just
> hangs forever.
>
> We hit this consistently in `apply_cutter` (called per-asset during `populate`) when a cutter or
> parent surface has sub-microsquare faces. Multi-floor predefined floor plans where solidified
> walls have cross-floor intersections at staircase-room boundaries are an easy trigger; in our
> debugging, an Apollo-cloud Generate stage hung silently for hours during populate before we
> noticed.
>
> The EXACT solver is slower but the slowdown vs FAST is bounded — no infinite loop on degenerate
> input. … roughly +20% wallclock for typical scenes.

A companion branch adds a visibility guard around the Boolean
([`fix/populate-cutter-visibility-guard`](https://github.com/folouiseAWS/infinigen/tree/fix/populate-cutter-visibility-guard)).

**How it fits.** This is the worst failure mode in our overnight loop: not a crash, not a slow
render — a worker that hangs silently and burns a night. `populate` is also the stage we are
already worried about (split.md: "full-scene asset realization" is interactive-killing #3).
**Licence:** BSD-3. **Effort:** ~1 hour plus a degenerate-geometry regression test. **Cost:** ~+20%
populate wallclock — worth it to convert an unbounded silent hang into a bounded slowdown.

---

### N4 — ebajemon-tw3: two lines that unblock the aarch64 terrain build

**Fork:** [ebajemon-tw3/infinigen](https://github.com/ebajemon-tw3/infinigen) ·
**branch:** [`macos-arm64-fixes`](https://github.com/ebajemon-tw3/infinigen/tree/macos-arm64-fixes) ·
**commit:** [`0eb315a047a7`](https://github.com/ebajemon-tw3/infinigen/commit/0eb315a047a711be81e28e077cb167bf4d584b12)
"Fix terrain build on macOS arm64 with llvm 21 (missing cstddef/cassert includes)"

Two added includes in `src/infinigen/terrain/source/common/utils/FastNoiseLite.h`:

```diff
 #include <cmath>
+#include <cstddef>
+#include <cassert>
```

**Verified not upstream.** `upstream/main`'s copy of that file still has only `#include <cmath>`.

**Verified in our own fork.** `~/src/infinigen-thor/src/infinigen/terrain/source/common/utils/FastNoiseLite.h`
is at upstream `224598d4` and also has only `<cmath>` — as does the second copy under
`source/cpu/soil_machine/include/`. Our spike reports the CPU terrain extensions already compiling,
so we are not currently broken; this is a latent portability fix that also protects the
`soil_machine` copy and any future switch to a newer GCC/libstdc++.

**Licence:** BSD-3. **Effort:** minutes. **Risk:** none.

---

### N5 — KaliberAI: run the whole pipeline on one local box (our night loop)

**Fork:** [KaliberAI/infinigen](https://github.com/KaliberAI/infinigen) ·
**branch:** [`aug4_stable`](https://github.com/KaliberAI/infinigen/tree/aug4_stable) ·
**commit:** [`b71c9b5ad777`](https://github.com/KaliberAI/infinigen/commit/b71c9b5ad777ab9201546612743bf547ec97477c)

Two files, both documented, both directly useful:

[`local_64GB_kaliber.gin`](https://github.com/KaliberAI/infinigen/blob/aug4_stable/infinigen/datagen/configs/compute_platform/local_64GB_kaliber.gin)
— a **whole-pipeline local scheduler**: `manage_datagen_jobs.num_concurrent = 2`,
`get_cmd.process_niceness = 2` ("let UI processes etc take precedence, to make the smooth and UI
usable"), `LocalScheduleHandler.jobs_per_gpu = 1`, `jobs_to_launch_next.max_queued_total = 2`,
`max_stuck_at_task = 2`, every queue (`coarse`, `fine_terrain`, `populate`, `render`, `export`)
switched from SLURM to `local_submit_cmd`, `queue_combined.mem_gb = 12`, `queue_combined.hours = 48`,
`queue_export.hours = 24`.

[`fast_solve_kaliber.gin`](https://github.com/KaliberAI/infinigen/blob/aug4_stable/infinigen_examples/configs_indoor/fast_solve_kaliber.gin)
— `FloorPlanSolver.n_divide_trials = 25`, `iters_mult = 25`, `compose_indoors.solve_steps_large = 100`,
`medium = 40`, `small = 5` (upstream defaults are 300/200/50), `terrain_enabled = False`,
`topview = True`, `populate_doors.all_open = True`,
`compose_indoors.invisible_room_ceilings_enabled = True`.

**How it fits.** `local_64GB_kaliber.gin` is a documented example of "everything runs on one
machine overnight" — the shape of split.md §2.2 and of our Phase 4. Copy it as the starting point
for `local_thor.gin` (N2a), and tune: 14 cores not 8, `mem_gb` far above 12 because memory is
unified, `num_concurrent` bounded by what the GPU can actually serve.

**Honest framing on the solver.** `solve_steps_large = 100` is a **quality/time trade, not a
speed-up of the same result** — you get a different, less-optimised scene. IDEAS.md #3's kill
criterion ("extract one stage's scoring function; time Python vs numba vs Warp") is *not* answered
by this. But the three free knobs — `topview`, `all_open`, `invisible_room_ceilings_enabled` — are
genuinely free and are exactly what a fast preview wants.

**Bonus:** `invisible_room_ceilings_enabled` was implemented **independently** by
[m-and-m-lab](https://github.com/m-and-m-lab/infinigen) ("[Fix] Make room ceilings invisible to
cameras after render"). Two independent forks solving the same problem is a strong signal it is a
real need.

**Licence:** BSD-3. **Effort:** hours.

---

### N6 — m-and-m-lab: USD articulated export (the thin-client wire, USD half)

**Fork:** [m-and-m-lab/infinigen](https://github.com/m-and-m-lab/infinigen) ·
**branch:** `main` (16 commits ahead) ·
**commit:** [`f0dcb5f48916`](https://github.com/m-and-m-lab/infinigen/commit/f0dcb5f48916cd60bedd72310e76b0f5d0dddbb5)
"Add changes to generate an articulated door in .usd format for each door in the scene during
scene generation" · later consolidated in
[`a5ce7fc50d8c`](https://github.com/m-and-m-lab/infinigen/commit/a5ce7fc50d8cb03ba77a7098bfe0278707d43ada) (marked `[WIP]`).

Files: `scripts/usd_articulated_asset_exporter.py`,
`scripts/usd_articulated_scene_composer.py`, `scripts/repair_per_asset_usd_topology.py`,
`infinigen/core/sim/exporters/usd_exporter.py`, `docs/simulation/ExportingToSimulators.md`,
plus `export_isaacsim_multi.sh`.

The design, from the composer's own docstring: the scene exporter writes the whole-house USD and
drops an `articulated_assets.json` beside it listing every articulated object (doors, then
cabinets, fridges) with its world pose and the absolute path to a standalone articulated USD twin
(joints, drives, axes). The composer opens the scene USD and, for each entry, creates an `Xform`
prim under `/World/Articulated/<kind>_<idx>` with a USD `references` arc to the per-asset USD,
**bundling** each per-asset USD and its baked textures into the scene directory so the scene is
self-contained and portable (copy the directory to an IsaacSim container without losing
references). Static geometry of those objects is removed from the scene USD so the reference is the
sole source of appearance and articulation.

**How it fits.** vision.md §8 ("the thin client… streamed glTF/USD") and split.md §3(a)
("glTF/USD deltas: structure, transforms, instances, tags"). The `references`-arc + bundling
pattern is the USD-native way to get incremental, asset-level updates without re-exporting the
scene — which is exactly what our recipe-delta stream needs. **Licence:** BSD-3 (the files carry
the BSD header). **Effort:** medium. **Caveats:** Isaac Sim-oriented; the branch is explicitly
WIP; `[Infra] Update OcMesher module to use lab fork` means it wants a different OcMesher pointer,
which conflicts with our upstream pin.

---

### N7 — divisonofficer: staged re-generation with frozen inputs (split.md §2.3-2)

**Fork:** [divisonofficer/infinigen](https://github.com/divisonofficer/infinigen) ·
**branch:** [`robomituba/datagen`](https://github.com/divisonofficer/infinigen/tree/robomituba/datagen)
(56 commits ahead, pushed 2026-10-18)

`datagen/loop/*.sh` implements an **ablation harness**: copy the base layout (`scene.blend` +
`solve_state.json`), replace one stage's spec, re-run that stage only, keep everything else frozen.
The pipeline it drives is rematerial → architecture → room planning → activity → kit lighting →
probe views → render. Two details worth stealing:

- `flock $O/gpu${RENDER_GPU}.lock` — a **GPU lock** so parallel renders don't fight for the device.
- `CUDA_VISIBLE_DEVICES=` (emptied) for the CPU-only stages — deliberate GPU avoidance, which on
  our unified-memory Thor is the equivalent of not waking the GPU.

**How it fits.** split.md §2.3-2 asks for "partial regeneration of only what an edit touched" with
"the rest of the state frozen". This is a working shell-level implementation of that pattern. The
*pattern* is worth more than the code, and the code is worth ~reading*, not adopting* — it is hard-
pathed (`/jarvis/project/robomituba`, `/tmp/claude-0/objreal`) and shell rather than Python.

**The real value in this fork is elsewhere**, in its material work:
[`fcba3649bc38`](https://github.com/divisonofficer/infinigen/commit/fcba3649bc386ff81e312f23ac694e82fc8e359e)
"walls and floors: texturecan scanned PBR (catalogue of approved sets; luminance-tinted plaster
walls, venue-matched floors) in place of Infinigen 2.0's flat paint group; light wear (30%) on
large surfaces" and
[`27a9a5784476`](https://github.com/divisonofficer/infinigen/commit/27a9a578447658d4ea058aff12f67bede154ba42)
"weathering reaches shader node groups; ground-truth channel renderer for review (albedo/normal/
roughness/metallic per view)". A **ground-truth channel renderer** is directly useful to our
**critic** — it renders albedo/normal/roughness/metallic per view, which is a cheap, deterministic
signal the vision critic could use to judge material work without a full render. Worth a look.
**Caveat:** the scanned PBR texture sets are third-party assets with their own licences — check
before shipping.

---

### N8 — clingto7: an in-repo agent workflow + a generator HTTP service

**Fork:** [clingto7/infinigen](https://github.com/clingto7/infinigen) — **1 commit behind upstream
main**, the cleanest cherry-pick base in the entire network.

[`81877b1d57f3`](https://github.com/clingto7/infinigen/commit/81877b1d57f38be54feee7baf71aff7f9225ea1d)
"feat: add interactive generator UI and target reasons" adds
`scripts/spraybot_generator_ui_server.py`: a **stdlib-only** `http.server` with
`/api/generators` returning the catalog, an HTML UI at `/`, and a worker subprocess doing the
actual generation. No Flask, no FastAPI, no dependencies. Plus `AGENTS.md` and
`docs/agents/{domain,issue-tracker,triage-labels}.md` — a domain glossary, an issue-tracker
pointer and five triage labels, i.e. an agent operating model living *in the repo*.

**How it fits.** Two things. (a) vision.md §7 — "the builders are agent sessions behind a protocol.
Front ends attach to them" — a thin HTTP seam over generator invocation is the right shape for that
boundary, and this is a 200-line dependency-free example of it. (b) Our `AGENTS.md` bootstrap is
one of the skills in this catalogue; this fork is a worked example of one.

**Note:** their `AGENTS.md` is a *pointer* — the actual agent skills live in that author's own
harness, not in the repo. We get the shape, not the content.

**Licence:** BSD-3. **Effort:** low. **Bonus:** because this fork is 1 behind upstream, cherry-picks
from it are conflict-free.

---

### N9 — cheap, real bug fixes upstream has not merged

All open upstream, all BSD-3, all small. These are the "free" end of the list.

| PR | Fork | Commit | What it fixes | Fit |
|---|---|---|---|---|
| [#498](https://github.com/princeton-vl/infinigen/pull/498) | [folouiseAWS](https://github.com/folouiseAWS/infinigen) | [`d52fac4963af`](https://github.com/folouiseAWS/infinigen/commit/d52fac4963afb2bd9b718cfb2a04a2aaa6aee16d) | Boolean FAST→EXACT, silent hang | **N3, take it** |
| [#504](https://github.com/princeton-vl/infinigen/pull/504) | [DiegoGomesDG](https://github.com/DiegoGomesDG/infinigen) | [`3aa7b1a6fbab`](https://github.com/DiegoGomesDG/infinigen/commit/3aa7b1a6fbab8782aa394baf00d2b1927d362206) | `sdf_from_mesh` KeyError on **empty meshes on the GPU** | **Directly in the CUDA terrain path we are porting** — take it |
| [#508](https://github.com/princeton-vl/infinigen/pull/508) | [DiegoGomesDG](https://github.com/DiegoGomesDG/infinigen) | [`b6ee4853a1b6`](https://github.com/DiegoGomesDG/infinigen/commit/b6ee4853a1b63a0982585c14b47a0a97f6cb9dae) | `NULL` → `nullptr` compile failure in FastNoiseLite | Same file as N4 — take together |
| [#507](https://github.com/princeton-vl/infinigen/pull/507) | [SAY-5](https://github.com/SAY-5/infinigen) | [`008901ba8503`](https://github.com/SAY-5/infinigen/commit/008901ba8503b01c86250c18723d420bab8928c0) | `room_walls` TypeError for wall materials without `**kwargs` | Cheap; our Indoors path uses room walls |
| [#506](https://github.com/princeton-vl/infinigen/pull/506) | [saschabuehrle](https://github.com/saschabuehrle/infinigen) | [`57924144364a`](https://github.com/saschabuehrle/infinigen/commit/57924144364ac3871893c215f8b1c98e1fb79749) | filter wall-material kwargs by `generate()` signature | Same area as #507 — take the better one |
| [#512](https://github.com/princeton-vl/infinigen/pull/512) | [koraykunal](https://github.com/koraykunal/infinigen) | [`f233a5b46e2c`](https://github.com/koraykunal/infinigen/commit/f233a5b46e2cb5a8e06ed3ba8245d0322f5df3fc) | `scripts/export_v2_asset.py` + `docs/source/ExportingInfinigen2Assets.md` — export V2 assets to Unity | Fits "exporters" + the thin client |
| [#493](https://github.com/princeton-vl/infinigen/pull/493) | [adamadam3d](https://github.com/adamadam3d/infinigen) | [`3607b4aaaef2`](https://github.com/adamadam3d/infinigen/commit/3607b4aaaef2a3dc9e09df9e1afb8a50d4fac05e) | clear ghost shape keys — jellyfish asset generation | Niche |
| [#482](https://github.com/princeton-vl/infinigen/pull/482) | [ysysimon](https://github.com/ysysimon/infinigen) | [`5bb48ecd4f68`](https://github.com/ysysimon/infinigen/commit/5bb48ecd4f6857641d62233b13c43700cc39a475) | assert when Blender exposes int32 (Windows) | Windows-only |
| [#485](https://github.com/princeton-vl/infinigen/pull/485) / [#486](https://github.com/princeton-vl/infinigen/pull/486) | [vlordier](https://github.com/vlordier/infinigen) | [`6498b82f216f`](https://github.com/vlordier/infinigen/commit/6498b82f216fee432dc24a252db3112ce279300b) / [`8fdfb5458868`](https://github.com/vlordier/infinigen/commit/8fdfb54588682f318e8652f9045218b23c32300a) | Apple Silicon M4 perf; OcMesher submodule pointer | **N2b** — but watch the OcMesher pointer (PR #486 is a draft follow-up and would move us off upstream's OcMesher pin) |
| [#342](https://github.com/princeton-vl/infinigen/pull/342) | [RaiaN](https://github.com/RaiaN/infinigen) | [`05b48a9175e6`](https://github.com/RaiaN/infinigen/commit/05b48a9175e6a9ffc85c1d6a01f8218a936a0a84) | GPU support in WSL | Only if we develop on the ProArt's WSL |
| [#497](https://github.com/princeton-vl/infinigen/pull/497) | [neulbit](https://github.com/neulbit/infinigen) | [`01c3f9d89c55`](https://github.com/neulbit/infinigen/commit/01c3f9d89c554c457e24634ad84e7b0fe015d9ea) | CI workflow publishing the Docker image to GHCR | Infra convenience; see N10 |
| [#118](https://github.com/princeton-vl/infinigen/pull/118) | upstream's own `amd_support` | [`4fa02935e004`](https://github.com/princeton-vl/infinigen/commit/4fa02935e004f8e6da3fb0c3573a1e08d2931119) | AMD/HIP support (2 commits, 1915 behind) | Historical only |

### N10 — neulbit: containerised datagen

**Fork:** [neulbit/infinigen](https://github.com/neulbit/infinigen) ·
**branch:** [`sirem`](https://github.com/neulbit/infinigen/tree/sirem) ·
**commits:** [`01c3f9d89c55`](https://github.com/neulbit/infinigen/commit/01c3f9d89c554c457e24634ad84e7b0fe015d9ea) (GHCR publish,
PR #497), [`53a351339928`](https://github.com/neulbit/infinigen/commit/53a351339928a211301d5938831fa74c47d6740a) (symlink
`infinigen` python3.11 as system python), plus GCS install and `src`-layout handling.

A container image for the whole datagen stack is a reasonable answer to "headless / service
wrapper". For us it is **optional**: our `thor-spike` builds bpy from source against the local
wheel, and a container would fight that. Take the `.dockerignore` and the GCS-in-install ideas;
skip the image.

---

## 3. What is *not* there — the negative findings

These matter as much as the nuggets, because each one closes off a search.

1. **No GPU acceleration anywhere.** No fork uses NVIDIA Warp; no fork rewrites terrain, scattering
   or node evaluation for the GPU. The only "warp" hits across all 68 cloned forks are *image warp*
   and *domain warp* in terrain code (verified: `docs/GroundTruthAnnotations.md`,
   `runtime/eroded_terrain.py` "Domain warp is applied via `scipy.ndimage.map_coordinates`"). The
   nearest GPU-adjacent work is
   [`399cc1986ee7`](https://github.com/vlordier/infinigen/commit/399cc1986ee781295d98aeb740b60563c2240014) "Add torch-accelerated
   PR code paths: torch.cdist for SDF batch, torch.matmul for projection, torch ops for colour
   sampling and smooth attribute (GPU)" — but it is on a **copilot branch in a different project
   (`syndata`)**, is 147 commits of unrelated work, and is not a port of Infinigen's stages.
   **Conclusion: IDEAS.md #2 (Warp terrain port) and #4 (live re-meshing) have no prior art here.**
2. **No aarch64-Linux port of anything.** Every ARM thing in the network is **Apple Silicon macOS**
   (Metal) or macOS arm64. The genuinely portable pieces are three: the compute-platform gin
   pattern (N2a), the Docker `TARGETARCH` scaffolding (N2b), and two `#include` lines (N4).
3. **No Jetson or Thor work.** Zero hits.
4. **No warm scene server, no resident `bpy`.** Nothing implements split.md §2.3-1. The nearest
   neighbours are tangos302's *file-marker* checkpoint (not a resident scene) and divisonofficer's
   *staged shell* harness (not in-process). **We build this ourselves.**
5. **No content-addressed stage cache.** Nothing implements split.md §2.3-3's
   `hash(recipe ⊕ gin ⊕ stage ⊕ deps)` cache. Zero prior art.
6. **No solver GPU batching.** Nothing touches IDEAS.md #3 except KaliberAI's config-level step
   reduction (a quality trade, not a speed-up).
7. **No thin-client export pipeline** except tangos302's glTF/Draco LOD bake. No USD LOD pipeline,
   no glTF delta streaming, no "recipe edit → delta" wire. N6's USD `references`-arc work is the
   closest to a delta wire.
8. **No fork is a service.** One stdlib HTTP server (clingto7, N8) for one generator. No API, no
   daemon, no MCP server for Infinigen itself.
9. **The Blender 4.5 port is the only "newer Blender" work in the network** (vlordier,
   N2b). It predates upstream's 4.5 support, so it is now behind.

---

## 4. Upstream's own state (context for the cherry-picks)

- `upstream/main` = [`224598d4a2ff`](https://github.com/princeton-vl/infinigen/commit/224598d4a2ff95b4fc928e72c222598b7122c698) (2026-10-14), 7371 stars, 622 forks.
- **23 open PRs** — listed in N9.
- Branches: `develop` is **702 behind main and 0 ahead** → dead. `amd_support` is 2 ahead / 1915
  behind (2023) → dead. `f_creature_parser` is 1 ahead (2024) → dead. **Only `main` is alive.**
- Upstream main already contains a **3× speed-up for large scenes**:
  [`69d73ca0724c`](https://github.com/princeton-vl/infinigen/commit/69d73ca0724ca0713996bf2f81d262426f0a8898)
  "Update procfunc to 0.37.0, make all operators respect immutable computegraphs and cached nodegroup
  impls, 3x speedup for large scenes". **Make sure our port carries this** — it is free and it
  lands squarely on the populate/asset-realization stage.
- Upstream also has [`407959bb` "Normalize Infinigen2 asset credits"](https://github.com/princeton-vl/infinigen/commit/407959bb931d8ef62f3fd7c6cb1d310a76a15277)
  — asset credit tracking is upstream behaviour now, which supports our "licences are a checked
  list" rule.
- Upstream ships `cuda_terrain.gin` and a CUDA terrain path (`source/cuda/elements/*.cu`). That is
  the thing we must port to sm_110 — and **no fork has done it**.

### Our base

`SI-Thor/infinigen-thor` `main` is **exactly `upstream/main` (224598d4)**, and `thor-spike` is
**+5 commits**:

```
f5a5af1b  thor/install.sh: infinigen venv against the local bpy wheel
b5dead9b  thor/build-bpy.sh: finish the bpy 4.2 aarch64 build end to end
67f3e673  thor/: reproducible bpy build, install and timing scripts
3668454a  terrain: target the build GPU's CUDA arch when compiling terrain kernels
2a7317f3  gitignore: local Thor spike artifacts
```

Consequences for harvesting:

- Cherry-picking from forks based on recent upstream (clingto7, folouiseAWS, DiegoGomesDG,
  ebajemon-tw3, tangos302, vlordier) is **clean** — our main is at upstream main.
- Cherry-picking from forks based **before 2026-01-29** additionally needs the upstream `src/`
  layout move reconciled (paths were `infinigen/...`, now `src/infinigen/...`).
- Our `3668454a` already does the sm_110 arch targeting that the `-arch=native` trick
  (IDEAS.md trap #5) needs, so N2b's `-mcpu=native` work is complementary, not duplicate.

---

## 5. Forks of forks

**The network is flat, and there is nothing to chase here.** The `/forks` API endpoint returned
empty `parent` and `source` for all 730 rows (the fields are not populated in this API version),
so I probed directly with `GET /repos/{fork}` on the ten most divergent forks: **all returned
`parent = princeton-vl/infinigen`**.

I also looked for shared ancestry by grouping all 48 non-upstream commit SHAs that appear in more
than one fork. Every cluster resolved to a **common upstream ancestor** (e.g. `892947be71c4`, a
2026-01-29 upstream commit shared by 17 forks) — i.e. forks that happen to sit at the same
upstream commit, not forks of each other. No fork-of-fork with independent work was found.

**Conclusion: all the interesting work is in direct forks of upstream.** No additional hop needed.

---

## 6. Licence summary

| Source | Licence | Verdict |
|---|---|---|
| Upstream `princeton-vl/infinigen` | BSD 3-Clause | — |
| **Every fork checked** (21 top forks explicitly; all 68 clones inspected for a `LICENSE` file) | **BSD 3-Clause, unchanged from upstream** | **Compatible.** No relicensing anywhere in the network. |
| `tangos302` maquette **textures** (35 MB, 47 files, `runtime/textures/`) | **Not covered by BSD** | ❌ **Do not harvest** without a per-file licence check |
| `vlordier` urban **DEM `.npz`** assets (Monaco/Narwa/Warsaw/St-Paul) | Not covered by BSD | ⚠️ check provenance before use |
| `divisonofficer` scanned PBR texture sets | Not covered by BSD | ⚠️ check provenance before use |

Our own rule — "licences are a checked list" — applies to the *assets*, not the code. All the
**code** nuggets in this report are BSD-3 and safe to take.

---

## 7. Recommended order of work

Ordered by (value × ease) ÷ risk, against our own phases.

**Do now — hours, near-zero risk (Phase 1 / the port):**

1. **N4** — add `<cstddef>` and `<cassert>` to `FastNoiseLite.h` (both copies) and take
   [`b6ee4853a1b6`](https://github.com/DiegoGomesDG/infinigen/commit/b6ee4853a1b63a0982585c14b47a0a97f6cb9dae)
   (the `NULL`→`nullptr` compile fix) at the same time. Two files, one sitting in our own tree.
2. **N3** — take [`d52fac4963af`](https://github.com/folouiseAWS/infinigen/commit/d52fac4963afb2bd9b718cfb2a04a2aaa6aee16d)
   (Boolean EXACT solver) and add a degenerate-geometry regression test. A silent hang is the one
   failure mode that can ruin a whole night.
3. **N9 rows for `#504`** — take the `sdf_from_mesh` empty-mesh GPU fix
   ([`3aa7b1a6fbab`](https://github.com/DiegoGomesDG/infinigen/commit/3aa7b1a6fbab8782aa394baf00d2b1927d362206))
   before we touch the CUDA terrain build. It is in the code path we are about to port to sm_110.
4. **N2a's `local_apple_silicon.gin`** as the template → write **`local_thor.gin`** (14 cores,
   unified 122 GB, `jobs_per_gpu = 1`). Fold in N5's `local_64GB_kaliber.gin` structure
   (all-local queues, `process_niceness`, `max_stuck_at_task`) and N5's free preview knobs
   (`topview`, `all_open`, `invisible_room_ceilings_enabled`).

**Do next — days, the real prizes:**

5. **N1's four pipeline files** — port `factories_guide.py`, `gap_tracker.py`, `implementer.py`,
   `cli.py` (≈1.5k LOC) onto our tree, re-target at a **local model on the Thor** rather than
   `claude -p`, and re-path away from `songe-core`. This is the seed of vision.md §4's builders
   and of the work-order loop. **Do not** take the 58k LOC factory bank or the textures.
6. **N1's `lod_bake.py`** — this is split.md §2.3-4's day-view wire, already written and measured.
   Check that `gltf-transform` (JS, portable) and `toktx` (KTX2 — verify an aarch64 Linux build
   exists) run on the Thor; the module degrades gracefully if `gltf-transform` is absent.
7. **N2b's denoiser fallback** — port the OPTIX→OPENIMAGEDENOISE chain into our `core/init.py`.
   We have no aarch64 OptiX SDK (split.md), so this makes the failure explicit instead of silent.
8. **N2b's Docker `TARGETARCH`** — only if we containerize the night. Optional; our from-source
   bpy build argues against it.

**Park, but read once:**

9. **N7's ground-truth channel renderer** (albedo/normal/roughness/metallic per view) — a cheap
   deterministic signal for the **critic**.
10. **N6's USD articulated `references`-arc + bundling** — the USD half of the thin-client wire,
    when we get there.
11. **N8's `spraybot_generator_ui_server.py`** — a 200-line dependency-free HTTP seam over
    generator invocation, to model our agent-protocol boundary on.
12. **N2c's urban family** — a large, clean, self-contained new generator family with an
    OpenDRIVE exporter. Wrong for our near-term plan; a strong "if we ever do cities" asset.

**Do not spend time on:** the GPU/Warp question (no prior art exists — plan it from scratch),
the aarch64 port (no prior art exists beyond N2a/N2b/N4), the warm scene server and the stage
cache (no prior art exists), and the solver GPU batching (no prior art exists). Four of our
biggest ideas are genuinely unclaimed.

---

## 8. Reproduction

All artefacts are in `/tmp/inf-forks/` (temporary, not checked in):

| File | What |
|---|---|
| `forks.tsv` | all 730 forks with `full_name, pushed_at, created_at, stars, size, default_branch, issues, archived, fork` |
| `heads/*.txt` | `git ls-remote --heads` for every fork (730 files) |
| `upstream_all_refs.txt` | all upstream refs incl. 116 PR heads |
| `divergent_summary.txt` | per-fork divergent branch summary |
| `shortlist.txt` | the 68 forks cloned for exact measurement |
| `batch_summary.txt` | per-branch ahead/behind + commit subjects + key files (2216 lines) |
| `negraw.txt` | the GPU/ARM/Warp/agent negative-finding scan |
| `clones/` | 68 blobless clones |
| `classify.py`, `filter.py`, `shortlist.py`, `analyse.py`, `batch.py`, `rank.py`, `negcheck.py`, `fof.py`, `shas.py` | the analysis scripts |

`gh api rate_limit` showed the unauthenticated core limit at **60 requests/hour** (GraphQL is
**0** unauthenticated), so the bulk scan was deliberately done with `git ls-remote` and shallow
clones — which are not API-rate-limited — and API calls were spent only on the fork list, the
upstream PR list, fork metadata and PR bodies.

---

### One-paragraph version

Scouted 730 forks: 199 untouched, 531 with some divergence, 43 with two or more divergent
branches, 68 measured exactly. **One fork matters:**
[tangos302/infinigen](https://github.com/tangos302/infinigen)'s maquette branch already implements
our builders layer (LLM-driven generation against an AST-derived factory catalog, a work-order
queue, a subprocess implementer, phase checkpoints, and a measured LOD/Draco bake for a browser
client) — take its four pipeline files, not its 58k LOC, and not its textures.
[vlordier/infinigen](https://github.com/vlordier/infinigen) gives us the compute-platform `.gin`
pattern our Thor needs, the first ARM-class port, an arm64 Docker path and a Blender 4.5 port.
Then take three cheap real fixes: the `FastNoiseLite` includes + `nullptr` compile fix
([ebajemon-tw3](https://github.com/ebajemon-tw3/infinigen),
[DiegoGomesDG](https://github.com/DiegoGomesDG/infinigen)), the Boolean EXACT-solver hang fix
([folouiseAWS](https://github.com/folouiseAWS/infinigen)), and the empty-mesh GPU `sdf_from_mesh`
fix ([DiegoGomesDG](https://github.com/DiegoGomesDG/infinigen)). **And note what is missing: no
fork has any GPU acceleration (no Warp, no CUDA rewrite), no aarch64-Linux port, no Jetson work, no
warm scene server and no stage cache.** Four of our biggest ideas are unclaimed, and the social
signal in this network is worthless — 41 forks have any star at all, max three. The licence is
uniformly BSD-3-Clause, so code is safe; the assets (35 MB of maquette textures, urban DEMs,
scanned PBR) are not and must be checked separately.
