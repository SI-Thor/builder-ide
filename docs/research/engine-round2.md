# ROUND 2 — traceable scenes, a byte-stable recipe graph, Warp terrain as a v2 stage

**Date:** 2026-10-31 (03:00–07:05 AKDT) · **Where:** `~/lm-wt/v2-next` ·
**Box:** NVIDIA Jetson AGX Thor (sm_110, 14× Cortex-X4A, 128 GB LPDDR5X,
Ubuntu 24.04, driver 595.78) · **Base:** infinigen `main @ 224598d4`
(= upstream 2.0.0a3, same commit as round 1), procfunc 0.37.0 (PyPI),
bpy 4.2.0 (phase-1 aarch64 wheel), numpy 1.26.4, warp-lang 1.18.0.

Round 1 (`~/src/builder-ide/docs/research/v2-thor-experiment.md`) established
that v2 + procfunc runs on the Thor and that the tracer works for *objects*,
and named the wall: `room_livingroom_rand --trace graph` died with
`ValueError: Proxy does not support __iter__` at `room_shape.py:133`. This
round takes that wall down and finishes the four tasks of the brief.

### The short version

| # | Task | Result |
|---|---|---|
| 1 | Make scene generators traceable | **Done.** `room_livingroom_rand --trace graph` (RANDOM_CONTROL) → **18,725-node graph, 342 choice nodes, 31 s**; the scene still renders **identically to an unpatched tree** (94-object inventory byte-equal; render diff vs round-1 baseline: **1 pixel, ±1 LSB**) |
| 2 | Canonical byte-stable graph | **Done.** Same seed → **byte-identical `graph.json`** across 2 sequential runs, 2 concurrent processes (`PYTHONHASHSEED=1` / `99`), and re-runs after later code changes — sha256 `ff33cc8f…` every time. Also byte-stable for an object scene and the new terrain scene |
| 3 | Warp terrain as a v2 stage | **Done.** `mountains` port wrapped as grammar + opaque-GPU-leaf; kernel re-verified **bit-identical** to Infinigen's CPU library in this venv (max\|diff\| = 0.0, 1M points); one outdoor scene rendered (140 s); terrain present in the traced graph (413 nodes; the Warp stage's six parameter draws are dataflow edges into it) |
| 4 | Scene-level partial regeneration | **Done.** One `chosen_idx` edit (desk: absent → present) → recipe grows **+2,698 nodes, 0 removed, 2 shared ids touched**; re-execution adds only the desk subtree (61 extra choice calls, +5.5 s generation; 1,104/1,432 profiled functions with identical call counts); render changes are 4.8 % structural (the desk) + a mean-3.4/255 global-illumination ripple |

**Box state, beside every number.** The box was again shared: load average
10–20 on 14 cores throughout, another seat's ComfyUI holding the GPU
(`maxGPUutil=98 %` in every sample below is the *share ceiling*, not our
work — see the per-run means), 32–54 GB system RAM in use. All wall-clock
numbers are upper bounds on an idle box.

---

## 0. What was inherited and what this run did

The previous agent (stopped by quota, per the handover note) left: the venv
(editable infinigen at `224598d4`, patched procfunc in site-packages), a
`ValueProxy` procfunc patch and its regen script, a first batch of scene-code
changes (`room_shape` wall count, `@pf.tracer.primitive` markings,
`generate.py` proxy guards), and probes. Its last trace died in sofa
placement (`snap.py:81`).

This run inherited all of that, then:

- **kept** the ValueProxy direction and the `room_shape` static-wall-count
  rewrite (verified them, extended them);
- **extended the procfunc patch** (choice results as `ValueProxy`; RNG method
  calls evaluate for real; the never-wrap-a-Proxy invariant;
  ufunc/builtin-safe function names; `$repr` pointer scrub);
- **replaced blanket `@pf.tracer.primitive` markings** on geometry services
  whose *results* steer control flow with trace-time assumptions guarded by a
  new `infinigen2.util.tracing.is_tracing()` (collision → no-hit, culling →
  keep-all, retries → first attempt), because an opaque leaf returns a
  `Proxy` the scene code cannot branch on;
- **found and fixed a render-time regression in the inherited work**: the
  overlap-wall-edges loop had been moved to a different point in the room
  build, which changed skirting geometry (one mesh, +84 verts). Caught by
  diffing a full scene inventory against an unpatched tree; after restoring
  the loop to its exact upstream position (trace-guarded), the patched and
  unpatched trees generate identical scenes;
- **wrapped the Warp port** as a v2 stage + outdoor scene, **rebuilt the
  choice tool** for the room (round 1's choice re-registration is
  incompatible with the ValueProxy choice patch), and ran the
  partial-regeneration measurement;
- wrote `patches/RATIONALE.md` (layered: procfunc capability → scene-code
  rule → terrain stage) and this file.

---

## 1. Task 1 — the room traces, and the render is unchanged

### 1.1 The failure class, named

`Proxy does not support __iter__` was one symptom of one thing: v2's scene
generators interleave *grammar* (choices, draws, composition — what a recipe
should record) with *runtime geometry services* (collision tests, bbox reads,
snapping, culling, realized-datablock identity) whose results steer control
flow but depend on meshes that do not exist while tracing. The tracer's model
is a dataflow graph; it had no answer for "what does `intersection_test`
return?" and no way to hand back "what did the chosen branch produce?".

The fix is one rule per kind (details and per-site comments in
`patches/RATIONALE.md`):

| scene-code kind | treatment | examples |
|---|---|---|
| statically knowable control flow | rewritten static | wall count is always 4 (`room_shape._split_flat_walls`; verified seeds 0–39, `logs/probe-wall-groups.json`) |
| geometry predicate / filter / retry | trace-time optimistic assumption via `is_tracing()` | `intersection_test→False`, `keep_non_colliding→keep all`, `retry_place→first attempt`, surface/small décor → no targets (defers to render) |
| pure realized side effect | opaque leaf (`@pf.tracer.primitive`) | `snap_to_plane`, `collision_set`, `propagate_modifiers_to_instances`, `delete_object(s)` |
| cosmetic realized write | skipped while tracing | `name_objects`, datablock renames |

plus the procfunc capability (patch 1) that makes sampled values usable:
rng-only draws evaluate for real (keeping the tracer's RNG stream identical
to the renderer's — `logs/probe-rng-stream-micro.json`), `choice` at
`RANDOM_CONTROL` returns the chosen branch's concrete result, `rng.choice(...)`
evaluates on the real generator.

### 1.2 The numbers

```
$ .venv/bin/infinigen room_livingroom_rand --seed 0 --trace graph \
    --trace_level RANDOM_CONTROL --output outputs/r2-trace-room-final
→ rc=0 in 31 s, peak RSS 389 MB, graph.json 5,276,063 bytes
```

| | |
|---|---|
| nodes | **18,725** (10,210 FunctionCall, 3,315 MethodCall, 4,019 MutatedArgument, 1,178 GetAttribute, 3 Constant) |
| choice nodes | **342** (round 1 never got here — the trace died before any graph was written) |
| seed 1 | also traces: **21,165 nodes** (seed 1 activates the desk branch) |
| CPU | 88 % of one mostly-loaded box; GPU idle (tracing realizes nothing) |

### 1.3 The scene still renders — proven, not assumed

Every patch is either `is_tracing()`-guarded or a decorator (inert outside a
trace), so the un-traced pipeline had to be unchanged. An early draft of this
work *did* change it (the inherited `overlap_wall_plane_edges` move — see §0),
so both checks below are part of the deliverable:

- **Object level:** a 94-object scene inventory (name/type/location/rotation/
  scale/vertex+polygon counts/materials, seed 0) is **byte-identical** to the
  same seed generated by the unpatched v2-thor venv at the same commit
  (`probe_scene_inventory.py`; the bisect that caught the skirting
  regression is described in `patches/RATIONALE.md`).
- **Pixel level:** `outputs/r2-render-room-final/Camera/0000.png`
  (rc=0, 392 s, peak RSS 3,044 MB, Cycles CUDA) vs round 1's unpatched
  baseline `s1-seed0`: **1 changed pixel of 262,144, ±1 in 8-bit** — the GPU
  accumulation noise round 1 itself measured between two identical renders.

> **Verdict 1 — can the tracer capture v2's scene layer?**
> **Yes, with the split above.** The recipe graph now contains the room:
> 18,725 nodes and 342 recorded choices where round 1 got an exception. The
> cost is honesty about the boundary: everything that reads realized geometry
> is recorded as an opaque call or an optimistic assumption, and its true
> outcome still only exists at render time. The graph is a *structural*
> recipe — grammar and composition exactly, placement approximately.

### 1.4 What the trace-time assumptions mean (and don't)

The assumptions are optimistic: placements succeed, nothing collides,
everything placed is kept, the first retry wins. Two consequences worth
stating plainly:

1. **Render-time culling can still drop objects the recipe contains.** The
   recipe describes the *candidate* structure; the render is the candidate
   structure minus collision rejections.
2. **RNG fidelity is scoped by `rng.spawn`.** v2 draws every grammar decision
   from `spawn`ed children (independent numpy bit-streams), so a draw that
   depends on realized geometry (and is therefore not consumed at trace time)
   can shift only that child's later draws — it cannot cascade into sibling
   choices. The 342 recorded `chosen_idx` values are the ones a render takes
   as long as its placements match the optimistic path; renders that retry
   diverge only inside the retrying child.

---

## 2. Task 2 — a canonical, byte-stable graph

Round 1 found two byte-level wobbles: a `repr()` pointer leak in
`infinigen2/graph_json.py`'s fallback serializer, and wall-clock fields
(`generator_times`, triangle counts) baked into the traced output as
constants. Both are fixed *in the serializer/pipeline* (not by
post-processing), so `--trace graph` now writes a canonical document
directly:

- functions serialize as `module.qualname` (never `repr()`), with
  ufunc/builtin-safe fallbacks (`numpy.add`, `builtins.min` — this also fixed
  a crash: round 2's graphs contain ufunc nodes that round 1's object graphs
  never hit);
- the `$repr` fallback scrubs pointer addresses (`0x[0-9a-f]+ → 0xADDR`);
- `generate.py` keeps measurement fields out of the traced outputs
  (`generator_times`, `base_tris`, `subdiv_tris`, `render_time_sec` are still
  logged in real runs; they just do not become graph constants).

**Proof.** Same seed (0), `room_livingroom_rand`, `RANDOM_CONTROL`:

| run | process | `PYTHONHASHSEED` | sha256 of `graph.json` |
|---|---|---|---|
| A (first success) | 1 | default | `ff33cc8f66d929a834010b6237de69ae61c937c1d04c37599912a5e3741e559a` |
| B (sequential re-run) | 2 | default | `ff33cc8f…` (identical) |
| C (concurrent) | 3 | `1` | `ff33cc8f…` (identical) |
| D (concurrent with C) | 4 | `99` | `ff33cc8f…` (identical) |
| E (after later code changes) | 5 | default | `ff33cc8f…` (identical) |

5,276,063 bytes, 18,725 nodes — byte-identical across **two runs and two
concurrent processes with different hash seeds**. Also byte-stable:
`plant_pot_small_rand` seed 0 (2 runs, `79f649e2…`) and the new terrain scene
seed 0 (2 runs, `96af97fd…`).

Cross-seed for the record: seed 1 traces to 21,165 nodes — a *superset*
(seed 1's desk-active choice is True), 0 nodes of seed 0's graph removed;
the same structural relationship the forced-desk edit of task 4 produces
deterministically.

> **Verdict 2 — is the recipe byte-stable?**
> **Yes, now, without post-processing.** `graph.json` is a safe input to a
> byte-comparing diff tool, a content hash, or a cache key.

---

## 3. Task 3 — Warp `mountains` as a procfunc-traceable v2 stage

`infinigen2/terrain/warp_mountains.py` (patch 3) wraps the lab-7 port in the
same two layers as the scene fix:

- `mountains_params_rand(rng)` — the grammar, drawing v1 landtiles' ranges
  (`min_freq` U(5e-4, 2e-3), `max_freq` U(3e-3, 4e-3), `height` U(60, 90),
  `coverage` U(0.4, 0.6), `slope_height` U(4, 6), plus a 31-bit seed);
- `mountains_heightfield(params, size, resolution)` — an opaque
  `@pf.tracer.primitive` that launches the (verbatim, unmodified) Warp
  kernel over a 512×512 grid and builds the displaced plane (~262 k verts);
- `terrain_scene_rand(rng)` — a Scene generator: terrain + granite material +
  Hosek-Wilkie sky with sun + a grammar-driven camera (distance/height/
  azimuth drawn, look-at computed). Registered in `manifest.json` together
  with the Object-category `mountains_terrain_rand`.

### 3.1 The kernel is still the validated one

Re-verified in *this* venv (numpy 1.26.4 + warp 1.18 + procfunc coexisting,
as round 1 §6.2 predicted): module kernel vs the vendored Infinigen CPU
library (`mountains_cpu.so`), 1,000,000 points, identical packed parameters:

```
max |warp_module − infinigen_cpu| = 0.000000e+00   mean = 0.000000e+00
```

Bit-identical, not close. The kernel source is byte-for-byte the lab-7 port
including its quirks (`FastFloor` truncation, float-precision `log_uniform`,
the `b`-not-`c` rotate in `hash_bit_final`); only the wrapper is new.

### 3.2 It renders, and it is in the graph

```
$ .venv/bin/infinigen terrain_scene_rand render_cycles --seed 0 \
    --output outputs/r2-render-terrain
→ rc=0, 140 s, peak RSS 1,122 MB, mean GPU util 92.9 %
   outputs/r2-render-terrain/Camera/0000.png  (512×512, 256 samples)
```

Granite mountains under sky, filling most of the frame (two earlier
iterations are part of the record: an 11 s blank render from a wrong
look-at formula — fixed after deriving and numerically verifying the
camera math — and a washed-out render from the missing material).

```
$ .venv/bin/infinigen terrain_scene_rand --seed 0 --trace graph \
    --trace_level RANDOM_CONTROL
→ rc=0, 413 nodes, 122 random draws, 5 choice nodes
```

The terrain is *in* the recipe: node `n33` =
`infinigen2.terrain.warp_mountains.mountains_heightfield`, its `params`
argument referencing the six grammar draw nodes (`n22` seed-int, `n24`
min_freq, `n26` max_freq, `n28` height, `n30` coverage, `n32` slope_height).
The graph is byte-stable (2 runs, `96af97fd…`). A terrain parameter edit is
therefore a graph edit at exactly the same level of detail as any v2
parameter.

> **Verdict 3 — can our Warp terrain be a v2 stage?**
> **Yes, and cheaply.** The expensive part (the kernel) was already done and
> ports unchanged; the v2 integration is one grammar function, one opaque
> leaf, and one scene generator. Terrain now participates in the recipe graph
> like any other stage — option C's "terrain in scope from day one" is
> demonstrated, not just argued.

---

## 4. Task 4 — a scene-level partial regeneration

**The edit.** One choice inside the traced room: `room.py:661`,
`pf.control.choice(rng_desk_active, [(False, 2.0), (True, 1.0)])` — at seed 0
it chose **False** (no desk). Forced to **True** by pinning the index at the
`choice_idx` call while still consuming the same draw (RNG stream position
unchanged; tool: `choice_tool.py`, rebuilt for the room — see §0).

### 4.1 What re-executes — three measurements

**(a) In the recipe** (`outputs/r4-trace-a` vs `outputs/r4-trace-desk`, both
seed 0, `RANDOM_CONTROL`):

| | original | variant | |
|---|---|---|---|
| nodes | 18,725 | 21,423 | **+2,698 added, 0 removed** |
| shared ids that differ | | | **2** — one real (the `_operator.add` node where the desk's objects join the room's lists), one a positional-id artifact at the graph tail |
| added-node kinds | | | 889 MutatedArgument, 727 `random.uniform`, 206 `random.clip_gaussian`, 136 `__getitem__`, +49 `choice` nodes (the desk's internal choices), … |

The edit is **purely additive**: the desk subtree appears; nothing else in
the recipe moves. Content-level multiset diff confirms no signature shrinks.

**(b) In execution** (un-traced, `render_cycles`, cProfile over the whole
CLI run; both runs on identical code):

| | baseline | forced (desk on) |
|---|---|---|
| `choice` calls | 469 | **530** (+61, all in the desk subtree; 1 forced) |
| scene generation | 21.6 s | **27.1 s** (+5.5 s, +25 % — the desk's chair/monitor/materials/collisions) |
| whole run (gen + bake + Cycles) | 369 s | 339 s (GPU-share noise; both 98 %-ceiling-shared) |
| functions with **identical call counts** | | **1,104 of 1,432** shared infinigen2/procfunc functions |
| where the deltas are | | desk subtree only: +1,014 collision registrations (`_register_object`), +1,103 `_object_transform`/`_mesh_id`, graph/pytree machinery under them |

**(c) In the picture** (512², 256 samples, same seed and camera):

| | |
|---|---|
| strongly changed pixels (Δ > 40) | **12,454 / 262,144 (4.8 %)**, confined to y ∈ [0.25, 1.0] — the desk |
| everything else | global-illumination ripple, mean **3.4 / 255**, p99 34 |
| max channel Δ | 223 (the desk itself) |

The ripple is physics, not leakage: adding an object changes light transport
everywhere. The *structural* change is the desk and only the desk.

*(Both task-4 renders ran on the pre-skirting-fix code — internally valid,
since baseline and variant used identical code; the absolute
baseline-equivalence claim rests on §1.3's final render.)*

> **Verdict 4 — does a one-choice edit regenerate partially?**
> **Yes, at scene scale.** One `chosen_idx` in an 18,725-node recipe adds
> exactly the desk's subtree (+2,698 nodes, 0 removed), re-executes exactly
> the desk's work (+61 choices, +5.5 s, collision registrations for its
> meshes), and changes the picture only where the desk is plus GI ripple.
> What a *cached* pipeline would save here is the 21.6 s of shared
> generation that re-ran identically — the measurement the stage-cache
> design needs.

---

## 5. Artifacts

| what | where |
|---|---|
| traced room graph (canonical, sha `ff33cc8f…`) | `outputs/r2-trace-room-final/graph.json` |
| the same graph, 2 concurrent processes | `outputs/r2-trace-room-p1/`, `outputs/r2-trace-room-p2/` |
| seed-1 room trace | `outputs/r2-trace-room-seed1/graph.json` |
| room render (baseline-equivalent) | `outputs/r2-render-room-final/Camera/0000.png` |
| terrain render | `outputs/r2-render-terrain/Camera/0000.png` |
| terrain trace (byte-stable) | `outputs/r2-trace-terrain/graph.json` |
| partial-regen original / variant graphs | `outputs/r4-trace-a/`, `outputs/r4-trace-desk/` (+ `choices.json` each) |
| partial-regen renders + profiles | `outputs/r4-run-orig/`, `outputs/r4-run-desk/`, `logs/r4-{orig,desk}.pstats` |
| kernel re-verification | `verify_terrain_kernel.py` (run of §3.1) |
| probes (RNG fidelity, wall groups) | `logs/probe-rng-stream-micro.json`, `logs/probe-wall-groups.json` |
| every run's time/RSS/tegrastats/GPU | `logs/*.summary`, `logs/*.stats`, `logs/*.gpu` |
| patches + rationale | `patches/` (`RATIONALE.md`, `procfunc-0.37.0/`, `infinigen2-traceable-scenes.patch`, `infinigen2-warp-terrain-stage.patch`) |

## 6. How to reproduce

```bash
cd ~/lm-wt/v2-next
./apply-procfunc-patch.sh                      # procfunc ValueProxy patch into the venv

# task 1 + 2: trace the room (byte-stable) and render it
.venv/bin/infinigen room_livingroom_rand --seed 0 --trace graph \
    --trace_level RANDOM_CONTROL --output outputs/rep-trace
.venv/bin/infinigen room_livingroom_rand render_cycles --seed 0 \
    --output outputs/rep-render

# task 3: terrain
.venv/bin/infinigen terrain_scene_rand render_cycles --seed 0 --output outputs/rep-terrain
.venv/bin/infinigen terrain_scene_rand --seed 0 --trace graph \
    --trace_level RANDOM_CONTROL --output outputs/rep-terrain-trace

# task 4: force the desk choice, re-trace and re-render
.venv/bin/python choice_tool.py force-trace room_livingroom_rand --seed 0 \
    --site "$PWD/src/infinigen-upstream/src/infinigen2/scenes/room/room.py:661" \
    --occurrence 0 --index 1 --out outputs/rep-desk-trace
.venv/bin/python choice_tool.py run room_livingroom_rand render_cycles \
    --seed 0 --site "$PWD/src/infinigen-upstream/src/infinigen2/scenes/room/room.py:661" \
    --occurrence 0 --index 1 --out outputs/rep-desk-render
```
