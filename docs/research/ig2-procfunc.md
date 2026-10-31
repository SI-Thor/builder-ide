# Infinigen 2.0 and procfunc — what the engine should be built on

**Date:** 2026-10-31 · **For:** Casey Digennaro / builder-ide engine decision
**Sources:** `~/src/builder-ide/docs/{vision.md,understanding.md,research/split.md,research/forks.md,lab/exp-warp-terrain-port.md}`;
`princeton-vl/infinigen` @ `224598d` (upstream `main` = Infinigen 2.0, `2.0.0a3`);
`princeton-vl/procfunc` @ `80e9c1a` (release `0.37.0`); arXiv 2604.26943v1.
All source claims below were read directly from the clones at `/tmp/infinigen-main` and `/tmp/procfunc`.

---

## Recommendation in one paragraph

**Build on 2.0 + procfunc (option b), and treat our Warp terrain port as a v2-native stage, not as "a v1 feature we're replacing later."** The reason is not that 2.0 is more capable — it is strictly less capable than 1.x today — but that 2.0's *architecture* is the one our recipe/stage-cache/warm-scene design needs, and that procfunc's tracer gives us something neither 1.x nor our current design has: a machine-readable dependency graph of a generation, which is the missing half of our stage cache. The recommendation carries one hard precondition: we must own the terrain, because v2 has no terrain of its own and the v1 terrain pipeline we already Warp-ported is the single most expensive thing we would otherwise have to rebuild. Concretely, that means **(c), entered through (b)** — v2 + procfunc as the substrate, our Warp terrain re-expressed as v2/procfunc primitives. The first experiment is in the last section.

---

## 1. Infinigen 1.x vs 2.0

### Two architectures, not two versions

The most important thing to understand about the upstream repo is that `main` contains **both** generations simultaneously. `src/infinigen/` is 1.x (v1.19.x) and `src/infinigen2/` is 2.0 (`2.0.0a3`), in one tree, with one `pyproject.toml`. The v1 code has not been deleted — it is still the "legacy" path, gated behind an extra:

```toml
# Legacy 1.0 gen; not "v1" ("v1" is a PEP 440 version, breaks pip<25 extra markers)
infinigen1 = [
    "infinigen[vis]",
    "scikit-image<0.20.0", "geomdl", "coacd", "networkx", "psutil",
    "scikit-learn<1.4.0", "shapely<=2.0.5", "tqdm", "submitit",
]
```

That listing is itself a summary of the gap. Everything 2.0 dropped from the default install — the constraint solver (`gin_config`, `networkx`, `scikit-learn`), the terrain build (`landlab`, submodules, native `marching_cubes`), the v1 exporter (`shapely<=2.0.5`), and the v1 SLURM job system (`submitit`) — moved into `infinigen1`. Upstream's own installation docs call v1 "Legacy (1.0) generation" and instruct you to install it with `INFINIGEN_MINIMAL_INSTALL=False INFINIGEN_INSTALL_TERRAIN=True pip install -e ".[infinigen1]"` [7].

Upstream describes 2.0 as "a top-to-bottom refactor of the system which aims to create simple and controllable APIs for all asset generators while also improving efficiency, detail, and diversity. It is built on top of `procfunc`" — and is explicit about its limits: "However, Infinigen 2.0 is in preview. It does not yet contain all asset types — currently it only has new high quality indoor materials, a limited subset of indoor objects, and simple indoor room arrangements." [1]

That "does not yet contain all asset types" is the maturity line to hold onto. v2 is at `2.0.0a3`, an alpha, three months old, with the upstream docs themselves advising: "we recommend fixing a specific version of the alpha, as some interfaces may change gradually until we reach the 2.0 full release." [1] The release history confirms the trajectory: the `v2.0.0a1` tag is dated 2026-07-08 (published on GitHub 15 Jul 2026), and `2.0.0a3`'s release commit `a0d1a0d` is dated 2026-10-08, adding room types, assets, and house tours [2][3].

### What each can generate

v1 is a two-product repo. **Infinigen Nature** generates outdoor terrain: procedural heightfields via CUDA and CPU element kernels (`terrain/source/cuda/elements/*.cu` — atmosphere, core, ground, landtiles, mountains, upsidedown_mountains, voronoi_rocks, warped_rocks, waterbody), with fine terrain produced by a camera-aware octree SDF mesher (`OcMesher`) emitting per-tile `glb` plus `.npy` displacement. **Infinigen Indoors** generates rooms by constraint solving. Both are wrapped in a batch system (`datagen/`: `manage_jobs.py`, `job_funcs.py`, `states.py`) with `.gin` configs, plus articulated-object/simulation support under `core/sim/`.

v2 is a single-product repo, currently indoor-only. Its `manifest.json` registers **253 generators**: Object 94, Material 66, Scene 46, Mask 18, Exporter 10, Cameras 6, Environment 5, Displacement 4, MaterialOverlay 4. The scene layer is the interesting part, and it is where v2 diverges most sharply from v1.

### The architectural break: v1 solves, v2 composes

This is the finding that most directly determines our decision, so it is worth being precise about.

v1's Indoors pipeline is a **constraint-solving architecture**. `core/constraints/` contains a constraint language (`constraint_language/`), an evaluator (`evaluator/`), a `reasoning/` module, and `example_solver/` — a greedy simulated-annealing solver that repeatedly proposes placements and evaluates them against the constraint set. The published cost of this is brutal: **2280.68 s (~38 min)** for the "Full System" configuration at 5k solver steps, averaged over 20 random scenes, and **6080.84 s (~101 min)** for the 100-minute budget — which scored *better* (avg. score 114.72 vs 80.84), not worse [4]. An independent 2025 measurement by a third party puts the solver at "an average 50.85 minutes per indoor scene on 4 Xeon Gold 5320 CPUs" [15], so the figure is not a one-off. The solver's state is serialisable (`solve_state.json`), and v1 already has per-stage deterministic seeding: `RandomStageExecutor` in `core/util/pipeline.py` derives each stage's seed as `int_hash((scene_seed, name))` and runs the stage body inside `FixedSeed(seed)`.

v2 has **no constraint solver at all**. I searched the whole `src/infinigen2/` tree: zero files matching `*constraint*` or `*solver*`, and the only occurrences of the word "constraint" are unrelated geometry parameters (`constraint_axis` in placement/snap code). The v2 house generator does have a function named `room_solve`, but it is a different thing entirely — a shapely polygon-partitioning routine that divides an outline into rooms and merges cells back down to a target count, retrying up to 100 times (`scenes/house/floor_plan.py:281-315`). Object arrangement is then handled by `pf.control.choice` plus a `CollisionSet` (`scenes/placement/collision.py`, trimesh + python-fcl) that checks for overlaps. The published v2 API docs list room generators by signature — `room_solve(rng, boundary_rings, room_count, …)`, `room_connect_rand(rng, walls, room_count)` [8] — with no constraint vocabulary anywhere in the surface.

So the practical difference: **v1 spends 38 minutes of CPU annealing to find a good layout; v2 spends milliseconds picking a good-enough layout and then places furniture around walls.** For a warm, interactive scene server where the user wants to see a room *now* and adjust one thing, v2's model is far closer to what we want — the expensive thing in v1 is exactly the thing our design cannot afford, and it is expensive in the most boring possible way (a Python loop calling Blender operators).

But the cost is that v2 has traded away **declarative control**. v1's constraint language was a first-class, user-facing artifact: you could write "a sofa against the longest wall, a coffee table 0.5 m in front of it, no object blocking the door." v2 replaces that with generator function signatures and `choice` calls. For a product whose core promise is *"the crew changes the world, not the code"* — where an architect says "make this room feel more open" — declarative control is the substance, not the garnish. v2's `room_livingroom_rand` is a sampler with explicit typed arguments; that is controllable, but it is control *by parameter*, not control *by constraint*.

### What 2.0 dropped or moved

| Capability | v1 location | v2 status | Consequence for us |
|---|---|---|---|
| Constraint solver | `core/constraints/` (language + evaluator + `example_solver/`) | **Gone.** Replaced by procedural composition + collision checks | We lose declarative layout control. Would have to rebuild a constraint layer. |
| Terrain pipeline | `terrain/source/{cuda,cpu}/`, `land_process/` (landlab), `mesh_to_sdf/`, `OcMesher` | **Gone from v2.** `pyproject`: `"terrain" = ["infinigen[infinigen1]"]  # terrain is a v1 feature`. v2 ships only a thin **ANT Landscape** binding (`objects/ant_landscape.py`) that wraps the third-party `bl_ext.blender_org.antlandscape` Blender extension and needs an **online addon install** | v2 has *no* terrain of its own. But our Warp port of v1's `mountains` element is exactly the raw material to write one. |
| GPU path | v1 CUDA terrain kernels + Cycles GPU render | v2 keeps Cycles GPU rendering; drops the CUDA terrain path | Our Warp port already beats v1's CUDA kernel 6×. No loss. |
| Ground truth | **Separate C++/GLSL OpenGL rasterizer** (`datagen/customgt/`, own CMake) | **Now Cycles-based**: `render_cycles_ground_truth` with `override_shading_for_gt()` that disconnects Surface/Volume links | **A real win for us.** v1's GT rasterizer needs headless EGL on the Thor — untested. v2 has no separate GL context. |
| Mesh/asset export | `tools/export.py`: fbx, obj, usdc, usda, stl, ply | **Gone.** v2's `ExportType` has `MESH` and `OBJECTS_FILE` but I found **no producer** for either — no `bpy.ops.export_scene.*` call anywhere in `src/infinigen2/`. The only exports are renders, `.blend`, `.npz` object data, camera pose, IMU trajectories, point tracks | **A real loss.** USD export matters to us — the vision doc treats USD as the compiled output. We would write the exporter. |
| Denoiser | `denoise = False` in both base configs (`configs_indoor/base_indoors.gin:43`, `configs_nature/base.gin:29`) — denoising simply off | New `DenoiseMode` enum (NONE / BEST / OPTIX / OPENIMAGEDENOISE) with `_DENOISER_PREFERENCE = (OPTIX, OPENIMAGEDENOISE)`. `_configure_denoising` **raises `RuntimeError("No usable denoiser")`** if a denoised pass is requested and no engine is available | **A trap for us.** Our Thor bpy build has OIDN off and the T5000 has no RT cores (so no OptiX). v1 never asked. v2 will hard-fail unless we set `denoise_mode=NONE` or build OIDN. Manageable, but it is a new failure mode. |
| Simulation / articulated objects | `core/sim/` (exporters, physics, kinematic compiler) | Not present in v2 | Not in our near-term scope, but it is gone. |
| Asset library | v1 `assets/` (large; 1.19.0-era) | v2 writes **new** materials and objects; the v1 asset library is not ported | v2's materials are described upstream as high quality and are a genuine improvement. Its object coverage is explicitly "a limited subset". |

Two consequences deserve emphasis because they cut in opposite directions. **v2's GT pipeline is a significant de-risking for the Thor**: the v1 OpenGL rasterizer would have needed EGL on aarch64 with no RT cores and a headless GPU stack — a thing nobody has ever run. v2 removes that entire risk class. And **v2's terrain gap is a gift, given what we already built**: our Warp port is bit-identical to v1's `mountains` and 6× faster than v1's own CUDA kernel, so re-expressing it as a v2 generator is a matter of wrapping, not of reimplementing physics we would otherwise have to port from scratch.

### Mapping onto our recipe / stage-cache / warm-scene design

Our design, from `vision.md` and `research/split.md`, wants:

- **Recipe as source of truth**, diffable, branchable, replayable. Meshes and renders are caches.
- **A stage cache** keyed by `hash(recipe ⊕ gin config ⊕ stage_name ⊕ deps' keys)`.
- **A warm scene server**: one resident `bpy` process, no per-task relaunch, no `.blend` round-trip.
- **Partial regeneration**: room-scoped re-solve, placeholder-scoped asset swap, material re-noise.

Against those four:

**Recipe-as-source-of-truth.** v1 fights this. v1's scene state is a `.blend` file plus a `.gin` config plus the solver's `solve_state.json`; `execute_tasks.py` reopens the `.blend` for every non-coarse task (`bpy.ops.wm.open_mainfile(...)` at line 219), and the batch system hands state between subprocesses. The recipe is implicit in Blender's object database, not in a diffable document. v2 fits far better: `generate.py` runs a list of named generator functions and chains their outputs by keyword (`--list` shows the 253; `uv run infinigen room_livingroom_rand render_cycles --seed 0`). The generation is a **callable program**, which is diffable and branchable. But note the caveat: a procfunc program is *code*, whereas our vision says the recipe is the source of truth and the code is fixed. This tension is addressed in §2.

**Stage cache.** v1 gets us halfway for free. `RandomStageExecutor` already gives per-stage determinism — `int_hash((scene_seed, name))` — and per-stage timings/object counts in a `pipeline_coarse.csv`. That is a stage-keyed cache skeleton, but it is keyed by *seed*, not by *content*, and it caches nothing: `run_stage` always re-executes. Nothing in v1 hashes upstream outputs. v2 gives us nothing here directly (no stage executor at all) but supplies the raw material — see §2.

**Warm scene server.** v1's batch architecture is the direct obstacle; our own `split.md` already lists "batch → warm scene server" as a required modification. v2's `generate.py` is *already* a single-process, in-memory pipeline: `execute_generators` threads `objects`, `cameras`, `lights` through a dict and calls generators in sequence, with no `.blend` round-trip in the middle. This is a materially better starting point for a resident server, and it is the single strongest argument for 2.0.

**Partial regeneration.** v1 has exactly one mechanism, `resample_scene` (`core/rendering/resample.py`), which re-noises materials and re-rolls scatters in place — no layout change. v2's answer is different in kind: because the generator graph is explicit, you can re-run *one* generator with a different parameter or a different `chosen_idx` and swap its outputs. That is the "placeholder-scoped asset swap" we want, and it is only reachable because of the graph structure discussed next. Upstream's own example projects already exploit the separation this enables, splitting a scene seed from a `--trajectory_seed` that re-randomises the camera path without touching the built scene [9].

### The catch that shapes everything: our fork is already on 2.0

`~/src/infinigen-thor` is at `224598d` — the same commit as upstream `main` — with 12 commits on top, and its `pyproject.toml` declares:

```toml
[project.scripts]
infinigen = "infinigen2.generate:main"
infinigen2 = "infinigen2.generate:main"
```

The plain `infinigen` command in our fork **already runs 2.0**. The v1 code is still in the tree and still runnable (`src/infinigen_examples/generate_indoors.py`, `generate_nature.py`), but it is no longer the default entry point. Anyone reading the fork today and typing `infinigen` gets v2. This is worth stating plainly because it means "build on 1.x" is not a free choice we can make by *not* moving — it is a choice to deliberately re-pin the entry point back to a path upstream is actively deprecating, and to keep a Python 3.11 `gin`-config pipeline alive that upstream now labels legacy.

Our fork's Thor work so far — the bpy 4.2.0 aarch64 build, the sm_110 Cycles kernels, the OIDN/OptiX-off configuration, the terrain CUDA arch fix — is all in `thor/` and `terrain/` (v1 paths). It is not thrown away under option (b): the bpy wheel and the venv tooling carry over unchanged, because both generations pin `bpy==4.2.0` and `requires-python = "==3.11.*"`.

---

## 2. procfunc

procfunc is a small, sharp, well-scoped library: BSD-3-Clause, PrincetonVL, released 2026, 5,353 stars. Its README is explicit about scope: "This repository contains only the Primitives API, Transpiler and Tracer from our research paper" [5]. The paper is arXiv 2604.26943v1, "ProcFunc: Function-Oriented Abstractions for Procedural 3D Generation in Python" (Raistrick, Kayan, Nugent, Yan, Mei, Parakh, Wen, Li, Zuo, Liang, Deng), AISTATS 2026 [6].

Its size is the first useful fact: `src/procfunc/` is roughly 21,000 lines total, of which `nodes/` (12,325) and `ops/` (3,926) are the primitive surface, and `compute_graph/` (969), `tracer/` (999), `transpiler/` (2,290), `codegen/` (1,681) are the machinery. The paper claims 497 primitives; I counted **725 public functions** across `nodes/` and `ops/` in the 0.37.0 tree (186 in `geo.py`, 91 in `compositor.py`, 79 in `math.py`, 59 in `shader.py`), so the codebase has grown past the paper's count — a normal and healthy sign for an alpha library. The released distribution is a single pure-Python wheel (`procfunc-0.37.0-py3-none-any.whl`) [10], so there is no compiled component to port to aarch64.

### The three components

**Primitives** are plain Python functions with type annotations, one per Blender operation, where all scene state is passed as arguments and the function's own output is its return value. The paper's framing is that this explicitness is what makes everything else possible: "This static analysis is made possible by our primitives' explicit inputs and outputs, which become incoming and outgoing edges of the compute graph" [6]. Infinigen 2.0's generators are written entirely against this surface — `pf.nodes.geo.extrude_mesh(...)`, `pf.ops.mesh.transform_apply(...)` — and the transpiled-chair example shows the resulting code reads like ordinary Python rather than node-graph soup.

**The transpiler** goes the other direction: Blender node tree → Python. `transpiler/bpy_to_computegraph.py` (1,298 lines) plus `parse_attrs.py`, `parse_default_values.py`, and `parse_special_cases.py` walk a `.blend`'s geometry-node trees and emit a `.py` file. The shipped example (`examples/transpile_simple_chair/transpiled_code.py`) turns a chair node graph into readable Python with a typed signature, docstring-free but type-annotated, reconstructing geometry with `pf.nodes.geo.mesh_grid`, `pf.nodes.geo.extrude_mesh`, `pf.nodes.geo.join_geometry`. The paper compares it to Infinigen's own transpiler but "adapted to ProcFunc's interface."

**The tracer** is the interesting one for us. It is explicitly modelled on `torch.fx.symbolic_trace`: it "executes a program in a special context to capture its compute graph without executing any expensive operations." Crucially it produces **two varieties**:

> Instance-level graphs capture only the control-flow path that was actually executed for a given random seed, and contains only the procedural parameters that affect a particular generated asset, which are useful as annotations. In contrast, a Distribution-level graph captures all possible control-flow paths, including all modules or parameters that could affect a large sample or dataset. [6]

The mechanism is `pf.control.choice`. At `TraceLevel.RANDOM_CONTROL` and above, `choice` *peeks through all options* — executing every branch's body — and records the full option list plus the chosen index in the graph node (`control/__init__.py:33-56, 95-123`). Below that level it resolves to the chosen branch only. This is implemented by a custom trace wrapper that intercepts `choice` itself, because "choice needs a custom tracing wrapper since we want to trace what happens inside its sub-options."

### Are procfunc programs our recipes?

**Partly — and the part that is not, matters more than the part that is.**

What matches our design: a procfunc program *is* a diffable, branchable, replayable description of a scene. It is a call sequence with explicit named parameters and an explicit `np.random.Generator` threaded through it (procfunc *bans* `np.random`/`random` module calls — every stochastic function takes an explicit `Generator`). The seed is therefore not ambient state; it is a first-class argument. That is very close to our recipe discipline. And the 2.0 CLI is literally a recipe interpreter: `uv run infinigen room_livingroom_rand render_cycles --seed 0`.

What does not match: **our recipe is data; a procfunc program is code.** Our vision's hard rule is that the recipe is the source of truth and *the code is fixed* — the crew changes the world, not the code. If the recipe is a Python program, then every recipe change is a code change, and the "diffable, branchable, replayable" property degenerates into "we are version-controlling Python." This is a real tension, and it is the single most important thing to get right before committing.

There is a way through, and it is the way procfunc itself points at. The programs are not arbitrary Python — they are built from a **fixed, closed vocabulary** of typed primitives, and every generator exposes a parallel `_rand_from_params` entry point (v2 has 667 `*_rand` functions; `landscape_rand_from_params`, `_boulder_rand_from_params` etc. take explicit parameters instead of a seed). So the recipe is not "the program" — it is **the program plus the concrete argument values that were sampled**, which is exactly what the tracer's *instance-level* graph captures: "only the procedural parameters that affect a particular generated asset." A procfunc instance-level graph *is* our recipe: a data document (the JSON serialization in `infinigen2/graph_json.py` emits `n0, n1, …` node ids, `$ref` edges, and nested subgraph lists) describing which generator was chosen, with what parameters, under which seed.

**That reframing is the core of the recommendation.** Our recipe layer should be built *on top of* the procfunc primitives and the tracer's JSON, not as a parallel invention. We write the fixed program (the generator graph); the recipe is the instance-level graph of that program under a given seed, plus any explicit overrides. Diffing two recipes is then a diff of two JSON DAGs, which is exactly the property our vision demands.

### Does the tracer give us the dependency graph our stage cache needs?

**For the intra-generator dependency structure, yes, unambiguously. For the inter-stage structure, no — and we must build that ourselves.**

What the tracer gives us, concretely:

- A DAG of `FunctionCallNode` / `MethodCallNode` / `GetAttributeNode` / `SubgraphCallNode` / `ProceduralNode` / `MutatedArgumentNode` / `ConstantNode` / `InputPlaceholderNode`, with `traverse_depth_first`, `traverse_breadth_first`, `traverse_nested_graphs`, and `usages_per_node` for reference counting.
- A JSON serialisation of it (`infinigen2/graph_json.py`), written by `--trace graph`.
- The ability to **rewrite** the graph: `replace_in_graph(graph, replacements)` swaps a node and recomputes its reachable parents; `transform_compute_graph(graph, transform_fn)` rewrites nodes post-order. Since 0.37.0 all of these are pure — they return new graphs and leave the input unchanged (`Make compute graphs and nodes immutable`).
- `control.choice` nodes carry `choice_options` and `chosen_idx`, so **re-running a branch with a different index is a graph edit, not a re-generation.** That is precisely the primitive behind our "placeholder-scoped asset swap" and "material re-noise" requirements.

What it does not give us:

- **A stage cache.** The tracer's DAG is *intra*-generator: it describes the calls inside one generator function. Our stage cache needs *inter*-generator edges — "this room depends on this furniture placement depends on this material" — with a content hash per stage. The tracer gives us the leaf-level call graph, not a scene-level dependency graph with cache keys.
- **A content-addressed key.** The graph has no notion of "the hash of this stage's output." `ComputeGraph.__call__` raises `NotImplementedError` — the graph is an *analysis* artifact, not an executable IR. To re-execute a stage you re-run the generator function with the same seed, not the graph.
- **Nested tracing** — `trace()` raises `RuntimeError("Nested tracing is not yet supported")` if a trace is already in progress (`tracer/trace.py:193-196`). So we cannot trace a scene composed of traced generators in one pass; tracing must be per-generator.
- **A working `chosen_idx` re-execution path in the tracer itself.** `choice(chosen_idx=...)` is documented as "Cannot be traced, but may appear in the output of the tracer" (`control/__init__.py:138`). So the re-index trick works through `replace_in_graph` on the *recorded* node, not by re-tracing with a forced index.

None of these are disqualifying, but they set the shape of the work: **the tracer gives us the vocabulary and the per-stage graph; we build the scene-level DAG, the content hashing, and the cache on top.**

There is a second, subtler benefit worth naming. The tracer's **distribution-level** mode — where `choice` peeks through *all* branches — gives us something we currently have no way to get: a machine-readable census of what a generator *could* produce. The paper uses it to measure diversity (base materials: 25.5 continuous params, 45 cyclomatic complexity, 81.3 bits entropy; multi-level composition: 41.7 params, 448 complexity, 134 bits) [6]. For us this is a **coverage oracle**: "does this recipe family still cover the space?" and "what does changing this parameter actually touch?" are answerable by graph analysis rather than by re-rendering. That is a genuine capability we would build from scratch otherwise.

### The bpy 4.2 / Python 3.11 constraint and aarch64

This is the section where the good news and the constraint land together.

procfunc's install line is blunt: "Note: ProcFunc depends on `bpy==4.2.0` which then requires Python==3.11.x. Other versions are not yet supported" [5]. The PyPI metadata confirms `Requires-Python: >=3.11,<3.12`, `bpy==4.2.0`, `numpy<2`. Since procfunc is not semver-1.0, upstream advises pinning `procfunc<0.XX`.

I checked PyPI directly for every published `bpy` version (4.2.0 through 5.2.3): **there is no Linux aarch64 wheel at any version** [11]. The only ARM artifacts are macOS `arm64` and Windows `arm64`. This is not new to us — our Thor spike already established it and built `bpy-4.2.0-cp311-cp311-manylinux_2_39_aarch64.whl` from source (≈70 min, ~5 patches).

The relevant point for *this* decision is the ordering of constraints. procfunc needs bpy 4.2.0 **exactly**, and 4.2.0 needs Python 3.11 **exactly**. Both infinigen 1.x and 2.0 pin the same pair (`bpy==4.2.0`, `requires-python = "==3.11.*"`). So procfunc imposes **no new constraint** on the Thor beyond what we already built. Our existing wheel satisfies it as-is.

The one genuinely new wrinkle is `numpy<2`, which procfunc and infinigen 2.0 both require (infinigen 2.0 additionally: `cvdpack>=0.6.0` — a pure-Python `py3-none-any` wheel [13], no aarch64 problem — and `shapely>=2,<3` and `trimesh>=3.22`, which do ship aarch64 wheels). numpy 1.26.4 has `cp311-manylinux_2_17_aarch64` wheels [12], so the constraint is satisfiable on the Thor. But it is a **conflict with our Warp terrain port**, whose venv is on numpy 2.5.4 [14]. Running Warp and procfunc in the same process is therefore not possible today. This is a solvable engineering problem (separate processes, or a numpy-1.x-compatible Warp build) but it is a real one, and it lands squarely on option (c).

Other aarch64-specific notes: procfunc's `ops/addons.py` can install Blender extensions from the online repository — used by v2's ANT Landscape binding (`require_blender_addon("antlandscape", allow_online=True)`), which is a network dependency on an appliance that should run unattended. That alone argues against depending on ANT Landscape for our terrain.

---

## 3. The engine decision

### Option A — build on 1.x

The 1.x tree is complete, battle-tested, and produces everything: nature terrain, constraint-solved rooms, articulated sim, custom GL ground truth, USD/GLB/FBX export. We already have a Thor-portable v1: bpy built for sm_110, CUDA terrain kernels patched for sm_110, the whole `thor/` toolchain.

The costs are severe and they land exactly on our design's load-bearing walls. The batch architecture hands state between processes via `.blend` files, which is the opposite of a warm scene server, and `split.md` already lists this as a required rewrite. The 38-minute Python annealer is the single biggest interactive-latency blocker in the whole system, and rewriting it means replacing the constraint engine — the part of 1.x we would most want to keep. The constraint language itself is a genuinely valuable asset that 2.0 has thrown away, and if we want "the architect asks for a room that feels open," we would be re-deriving it while simultaneously replacing it with something faster. Meanwhile the GT rasterizer needs headless EGL on the Thor, which nobody has ever run, and the v1 asset library is a large surface to keep carrying while 2.0 is producing better materials.

Working on 1.x also means working *against* upstream's direction. Upstream is two alphas into replacing 1.x, has moved 1.x to an opt-in legacy extra, and points its default console script at v2. Every future upstream improvement lands in the tree we would be declining to use.

### Option B — build on 2.0 + procfunc

2.0 gives us the shape our design needs. A single-process, in-memory generation pipeline with no `.blend` round-trip is the warm scene server's native form. Explicit typed parameters on every generator, with `_rand_from_params` twins, make a controllable, closed vocabulary — the thing the crew interacts with. The tracer gives us a per-generator DAG with rewriteable nodes and recorded choice indices, which is the substrate for partial regeneration and for coverage analysis. The GT path is Cycles-based, removing the EGL risk entirely. The materials are better than v1's. And the bpy 4.2 / Python 3.11 constraint costs us nothing we have not already paid.

The costs are equally real. 2.0 is an alpha at `2.0.0a3` whose interfaces upstream itself warns may change; it has no constraint solver, so declarative layout control is gone and we would rebuild it; it has no terrain, no sim, and — critically — **no mesh export producer at all**, so the USD export our vision depends on is ours to write; and its new `DenoiseMode` will hard-fail on our Thor unless we pin `denoise_mode=NONE` or build OIDN into our bpy. Our fork's console script already points here, so choosing B is partly choosing to stop fighting upstream.

### Option C — 2.0 + procfunc with our own Warp terrain and Thor-native stages

This is B plus the two substitutions that we already have the assets for. Our Warp port of the v1 `mountains` element is bit-identical (max |diff| 0.0 over 16 M points) and runs 44–56× the v1 CPU path and 6× v1's own CUDA kernel — so re-expressing it as a procfunc primitive is wrapping, not re-derivation. The stage-cache and warm-scene server are likewise ours to write either way, and writing them *into* 2.0 rather than *around* 1.x is cheaper.

The costs are the same as B's, plus the real risk that 2.0's alpha interfaces shift under us while we build, plus the numpy 1.x/2.x split between procfunc and Warp, plus the fact that a Warp terrain generator is a *new* asset with no upstream equivalent to fall back on if our schedule slips.

### Comparison

| | A: 1.x | B: 2.0 + procfunc | C: B + our Warp terrain |
|---|---|---|---|
| Warm scene server | Rewrite required; fights the batch architecture | Native shape; `execute_generators` is already in-process | Same as B |
| Recipe as source of truth | Fights it; state lives in `.blend` + `.gin` | Instance-level tracer graph is a data document | Same as B |
| Stage cache | `RandomStageExecutor` gives per-stage seeds and timings, but no content hashing | No stage executor; must be built on the tracer DAG | Same as B |
| Partial regeneration | Only `resample_scene` (re-noise in place) | Graph edits via `replace_in_graph` + `chosen_idx` | Same as B |
| Declarative layout control | **Yes** — the constraint language | **No** — must be rebuilt | Same as B (rebuild) |
| Terrain | Works; CUDA kernels sm_110-patched | **None** (ANT Landscape addon only) | **Ours, Warp-native, bit-identical, 6× v1 CUDA** |
| Ground truth on Thor | Needs headless EGL — untested risk | Cycles-based; risk removed | Same as B |
| Mesh/USD export | Present (usdc/usda/…) | **Absent** — must be written | Same as B |
| Denoiser on Thor | `denoise=False`, never asks | New hard failure unless `NONE`/OIDN | Same as B |
| Upstream direction | Being deprecated; extra-gated | Active alpha | Same as B |
| Maturity | Stable, 1.19.x | Alpha `2.0.0a3` | Alpha + our own new asset |
| aarch64 cost | Already paid (bpy build) | Already paid | Already paid + numpy 1.x/2.x split |

### Recommendation

**Option C, entered through B.** Build the engine on 2.0 + procfunc, and re-express our Warp terrain as a v2/procfunc primitive rather than carrying v1's terrain pipeline.

The reasoning is a single chain. Our product's value is a *warm, interactive, editable* world — the recipe is the source of truth, the crew changes the world, stages are cached, nothing relaunches. Of the two architectures, only 2.0's shape matches that, and only procfunc's tracer makes the "recipe is a data document" property real rather than aspirational. The things 2.0 dropped are not, with one exception, things we wanted: the constraint solver is the very thing whose 38-minute cost we could not afford, and we were going to rewrite it anyway; the GL ground-truth rasterizer was an untested EGL risk on the Thor that we are glad to delete; the sim tree is not in our near-term scope. The one thing 2.0 dropped that we genuinely wanted — terrain — is the one thing we already own in a better form than upstream does, in Warp, at 6× their CUDA kernel's speed. And our bpy 4.2 / Python 3.11 work, which was the largest fixed cost in this whole investigation, transfers unchanged.

One caveat on framing: C is not "B plus our Warp terrain" in the sense of a later add-on. Terrain is the largest single generator in the system and the one our `split.md` stage map treats as foundational. If we choose B and treat terrain as a follow-on, we will spend months in a world with no terrain. The recommendation is that terrain be in scope from day one, expressed as procfunc primitives so that it participates in the tracer graph, the recipe, and the stage cache like everything else.

### What would make this recommendation wrong

Honest falsifiers, in the order they would show up:

- **The alpha churn bites.** If 2.0's generator signatures and the tracer's node model change incompatibly faster than we build, our recipe format is hostage to upstream's schedule. Mitigation: define our own recipe schema *above* procfunc, so an upstream change is a re-implementation of one adapter rather than a change to every recipe we have written. We should build that adapter layer early, on purpose.
- **Rebuilding declarative layout is harder than replacing it.** If we find ourselves unable to express "this room should feel open" without the constraint language, and re-deriving it costs more than the 38 minutes it saves, the "solver was too slow anyway" argument weakens. Worth testing early.
- **The mesh-export gap bites harder than expected.** If USD export turns out to require deep Blender internals that procfunc does not expose, we may find ourselves writing a Blender-side exporter anyway, which is work v1 would have given us free.
- **numpy 1.x vs 2.x proves unbridgeable.** If our Warp terrain code fundamentally needs numpy 2, then option C means either a separate process for terrain (acceptable) or a Warp rebuild (costly). This is cheap to check and should be checked first.

### The first experiment that would confirm it

**A single v2-on-Thor scene, end to end, with the tracer on.** Concretely, in one process on the Thor, using our existing bpy aarch64 wheel and a fresh venv with `procfunc==0.37.0`, `numpy==1.26.4`:

1. Run `infinigen room_livingroom_rand render_cycles --seed 0` and get a Cycles GPU render out on the Thor.
2. Re-run with `--trace graph` and get `graph.json`; assert it is byte-stable across two runs at the same seed, and diff it against a second seed.
3. Take that `graph.json`, edit one `choice` node's `chosen_idx`, and re-execute to show a *single-parameter* variant of the room materialises without touching the rest of the scene.
4. Time the whole thing, and separately time a second, different scene in the *same* resident process — that second number is our first real measurement of the warm-scene win.
5. Separately: confirm `denoise_mode=NONE` is required (or that the Thor build needs OIDN), and confirm the numpy-1.x/2.x situation for Warp.

This is roughly a day of work, and it is decisive on the four questions that actually matter: does 2.0 run on the Thor at all; is the tracer graph stable and diffable enough to serve as a recipe; can a graph edit produce a partial regeneration; and what does the warm-process number look like. If all four hold, the recommendation is confirmed. If step 3 fails — if you cannot get a single-node edit to produce a targeted change — then the tracer is an analysis tool rather than the recipe substrate, and we should revisit whether the recipe layer is better built as a conventional data format over the generators with the tracer used only for coverage analysis.

---

## Appendix — verification notes

Facts asserted above and where they came from:

- **v2 manifest counts (253 generators, by category)** — computed directly from `src/infinigen2/manifest.json`.
- **No constraint solver in v2** — exhaustive search of `src/infinigen2/` for `*constraint*`/`*solver*` filenames and for the string `constraint`; contrasted with `src/infinigen/core/constraints/{constraint_language,evaluator,example_solver,reasoning,checks}.py`.
- **v2's `room_solve` is a polygon partitioner, not a solver** — read in full at `src/infinigen2/scenes/house/floor_plan.py:281-315`.
- **No mesh export producer in v2** — searched all of `src/infinigen2/` for `bpy.ops.export*` (zero hits), `wm.usd_export`, and `ExportType.MESH`/`OBJECTS_FILE` producers (only enum definitions, no emitters).
- **v2 GT is Cycles-based** — `src/infinigen2/exporters/render_cycles.py:589+` and `exporters/util/blender_render.py:518` (`override_shading_for_gt`).
- **v2 denoiser hard-fails** — `src/infinigen2/exporters/render_cycles.py:234-278` (`DenoiseMode`, `_DENOISER_PREFERENCE`, `_configure_denoising` raising `RuntimeError`).
- **v1 denoise is simply off** — `src/infinigen_examples/configs_indoor/base_indoors.gin:43` and `configs_nature/base.gin:29`, both `denoise = False`.
- **v1 per-stage determinism** — `src/infinigen/core/util/pipeline.py:41,84` (`int_hash((scene_seed, name))`, `FixedSeed`).
- **v1 `.blend` round-trip** — `src/infinigen/core/execute_tasks.py:219` (`bpy.ops.wm.open_mainfile`).
- **v1 resample** — `src/infinigen/core/rendering/resample.py:29` (`def resample_scene`).
- **v1 CUDA terrain elements** — `src/infinigen/terrain/source/cuda/elements/*.cu`.
- **v1 custom GT rasterizer** — `src/infinigen/datagen/customgt/{main.cpp,CMakeLists.txt,glsl/}`.
- **v1 export formats** — `src/infinigen/tools/export.py:29`, `FORMAT_CHOICES = ["fbx", "obj", "usdc", "usda", "stl", "ply"]`.
- **v2 `execute_generators` is single-process** — `src/infinigen2/generate.py:578+`.
- **v2 trace plumbing** — `generate.py:425-472` (`_execute_trace`), `--trace {codegen,codestats,graph}`, `--trace_level`; `src/infinigen2/graph_json.py` (JSON DAG serialisation).
- **procfunc graph node kinds and immutability** — `src/procfunc/compute_graph/node.py`, `compute_graph/compute_graph.py:36` (note `ComputeGraph.__call__` raises `NotImplementedError`).
- **`choice` peek-through and `chosen_idx`** — `src/procfunc/control/__init__.py:33-56, 95-123, 138`.
- **TraceLevel enum** — `src/procfunc/tracer/patch.py:23-35`.
- **Nested tracing unsupported** — `src/procfunc/tracer/trace.py:193-196`.
- **Graph transforms** — `src/procfunc/compute_graph/util.py:301` (`replace_in_graph`), `:363` (`transform_compute_graph`), plus `usages_per_node`, `traverse_*`.
- **497 primitives (paper) vs 725 counted** — paper §3.1; my AST count over `src/procfunc/{nodes,ops}/**/*.py` public functions in the 0.37.0 tree.
- **bpy has no Linux aarch64 wheel at any version** — queried `https://pypi.org/pypi/bpy/json` and every release's file list from 4.2.0 to 5.2.3; only macOS/Windows ARM artifacts exist. `bpy==4.2.0` requires Python `==3.11.*`.
- **numpy 1.26.4 aarch64 cp311 wheels exist** — `https://pypi.org/pypi/numpy/1.26.4/json`; `numpy-1.26.4-cp311-cp311-manylinux_2_17_aarch64.whl`.
- **cvdpack is pure Python** — `https://pypi.org/pypi/cvdpack/json`; `cvdpack-0.7.0-py3-none-any.whl`.
- **procfunc PyPI constraints** — `https://pypi.org/pypi/procfunc/json`; `Requires-Python >=3.11,<3.12`, `bpy==4.2.0`, `numpy<2`.
- **warp-lang has an aarch64 wheel** — `https://pypi.org/pypi/warp-lang/1.18.0/json`; `warp_lang-1.18.0-py3-none-manylinux_2_34_aarch64.whl`.
- **Our fork state** — `~/src/infinigen-thor`, `git log` vs `upstream/main`: merge-base `224598d`, 12 commits ahead; `pyproject.toml:101-103` console scripts; `src/infinigen2/__init__.py` `__version__ = "2.0.0a3"`.
- **Thor spike facts** (bpy source build, sm_110, OIDN/OptiX off, 7.1× GPU/CPU, ~70 min build) — `~/src/infinigen-thor/thor/SPIKE.md`.
- **Warp terrain port** (bit-identical, 44–56× CPU, 6× v1 CUDA) — `~/src/builder-ide/docs/lab/exp-warp-terrain-port.md`.
- **Release dates** — `git for-each-ref refs/tags` in the clone: `v2.0.0a1` tagged 2026-07-08; `a0d1a0d` (the `2.0.0a3` release commit) dated 2026-10-08. GitHub release page for `v2.0.0a1` shows publication 15 Jul 2026 [2].
- **Solver cost** — Infinigen Indoors paper, arXiv 2406.11824 (CVPR 2024), Table 3: "Full System" runtime 2280.68 s (5k solver steps, 20 scenes), "Full System 100 min." 6080.84 s with avg. score 114.72 vs 80.84. Independently corroborated by arXiv 2504.16930, which measures the solver at "an average 50.85 minutes per indoor scene on 4 Xeon Gold 5320 CPUs."

### References

1. Infinigen 2.0 documentation — https://github.com/princeton-vl/infinigen/blob/main/docs/source/Infinigen2.md
2. Infinigen releases (2.0.0a1 / 2.0.0a3) — https://github.com/princeton-vl/infinigen/releases
3. Release 2.0.0a3 rooms (commit a0d1a0d) — https://github.com/princeton-vl/infinigen/commit/a0d1a0dd5644904d3cb921ff24260160ac06ae08
4. Infinigen Indoors: Photorealistic Indoor Scenes using Procedural Generation (arXiv 2406.11824; Table 3 solver timings) — https://arxiv.org/abs/2406.11824
5. princeton-vl/procfunc README — https://github.com/princeton-vl/procfunc
6. ProcFunc: Function-Oriented Abstractions for Procedural 3D Generation in Python — https://arxiv.org/abs/2604.26943
7. Infinigen Installation guide (legacy 1.0 install path) — https://infinigen.cs.princeton.edu/docs/latest/_sources/Installation.md
8. Infinigen 2.0 API docs (scene generators) — https://infinigen.cs.princeton.edu/docs/latest/api/infinigen2.scenes.html
9. ExampleProjects.md (seed / trajectory_seed separation) — https://infinigen.cs.princeton.edu/docs/latest/_sources/ExampleProjects.md
10. procfunc on PyPI — https://pypi.org/pypi/procfunc/json
11. bpy on PyPI (wheel matrix) — https://pypi.org/pypi/bpy/json
12. numpy 1.26.4 on PyPI — https://pypi.org/pypi/numpy/1.26.4/json
13. cvdpack on PyPI — https://pypi.org/pypi/cvdpack/json
14. warp-lang 1.18.0 on PyPI — https://pypi.org/pypi/warp-lang/1.18.0/json
15. What Makes Good Synthetic Training Data for Zero-Shot (independent solver-timing measurement) — https://arxiv.org/html/2504.16930v2
