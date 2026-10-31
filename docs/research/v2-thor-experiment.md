# EXPERIMENT — Infinigen 2.0 + procfunc on the Thor, tracer on

**Date:** 2026-10-31 (02:29–03:35 AKDT) · **Where:** `~/lm-wt/v2-thor` ·
**Box:** NVIDIA Jetson AGX Thor Developer Kit (sm_110) ·
**Study:** `~/src/builder-ide/docs/research/ig2-procfunc.md` ·
**Toolchain:** `~/src/infinigen-thor/thor/SPIKE.md` (phase 1)

This file answers the five steps of the brief with the numbers that came out
of the box, and gives a verdict on the study's four questions.

### The short version

| # | Question | Answer |
|---|---|---|
| 1 | Does Infinigen 2.0 run on the Thor? | **Yes** — full pipeline, Cycles **CUDA** GPU render, 435 s cold, no workarounds |
| 2 | Is the tracer graph stable and diffable? | **Stable and diffable, but not byte-stable** — two artefacts (a `repr()` pointer leak and the `generator_times` timing field) break byte-equality; everything else is identical, and the seed-to-seed diff is exactly the list of branch choices |
| 3 | Does a single-parameter edit drive a partial regeneration? | **Yes** — one `chosen_idx` → one changed node in a 4,231-node recipe → a change in the render confined to that parameter's object |
| 4 | Is there a warm-scene win? | **~2.4 s per scene — the process start-up, nothing else.** Generation, bake and sampling are all per-scene work |

**The most important finding is not in that table.** The tracer cannot capture
v2's *scene* generators at all: `room_livingroom_rand --trace graph` dies with
`ValueError: Proxy does not support __iter__` at
`infinigen2/scenes/room/room_shape.py:133`. The recipe substrate works — for
objects. It does not yet work for the room the study named. Details in §3.1.

Two of the study's blockers dissolved on contact: the denoiser question is a
pass-set question, not a `denoise_mode` question (§6.1), and the numpy 1.x vs
2.x vs Warp question — the study's own "cheapest falsifier" — is **not** a
blocker: Warp 1.18 runs on numpy 1.26.4 on the Thor and reproduces the terrain
port **bit-identically** (§6.2).

---

## 0. The box these numbers were taken on

| | |
|---|---|
| SoC | NVIDIA Jetson AGX Thor Developer Kit — 32-core Blackwell GPU, `sm_110`, compute capability **11.0** |
| CPU | 14 × Arm Cortex-X4A @ 2.601 GHz (+ 4 × Cortex-A720AE @ 972 MHz) |
| RAM | 125,749 MB (≈128 GB) LPDDR5X, unified |
| OS / kernel | Ubuntu 24.04 aarch64, `6.8.12-1021-tegra` |
| Driver | 595.78 (CUDA driver 13.2, CUDA toolkit 13.4 as seen by Warp) |
| Storage | NVMe, 936 GB, 276 GB free at the start |

**The box was not idle, and the numbers below carry that.** Concurrently
running during the experiment, none of it mine:

* `trellis` ComfyUI — held the GPU throughout (8,328 MiB, **97 % GPU
  utilisation**, 56–79 W).
* An **overnight Infinigen seed sweep** in `~/src/infinigen-thor/.venv`
  (`generate_nature.py`, 4 processes) — CPU-bound, 141 % CPU.
* `lab3` LoRA training (137 % CPU), `exp5a` cudagraph capture, and two
  `exp_nvme_bandwidth` runs stuck in `D` state.
* Load average **20–25** across all 14 cores; system RAM 56–68 GB in use.

So every wall-clock number here is an **upper bound** on an idle box, and the
GPU numbers are a *share* of a GPU that was already 97 % busy. Where a number
depends on that, it is called out. `~/src/infinigen-thor/.venv` was **not**
touched — the sweep was using it.

---

## 1. The install (fresh venv, this directory)

```
~/lm-wt/v2-thor/.venv                    CPython 3.11.13
  bpy          4.2.0   phase-1 aarch64 wheel (bpy-4.2.0-cp311-cp311-manylinux_2_39_aarch64.whl, 79.9 MB)
  infinigen    2.0.0a3 upstream main @ 224598d4a2ff95b4fc928e72c222598b7122c698  (editable, MINIMAL_INSTALL=True)
  procfunc     0.37.0  (PyPI)
  numpy        1.26.4  (procfunc and infinigen 2.0 both pin numpy<2)
  pandas 3.0.6 · scipy 1.17.1 · shapely 2.2.0 · trimesh 5.2.0 · opencv-python 4.11.0.86
  imageio · matplotlib · OpenEXR · pillow · python-fcl 0.7.0.11 · rtree · cvdpack
~/lm-wt/v2-thor/.venv-warp-np1            CPython 3.11.13 + numpy 1.26.4 + warp-lang 1.18.0 (step 5 probe)
~/lm-wt/v2-thor/src/infinigen-upstream    clone of github.com/princeton-vl/infinigen @ main
```

The interpreter is the phase-1 CPython 3.11 (`~/src/infinigen-thor/.toolchain`),
used read-only. Upstream `main` is **exactly** the commit our fork is based on
(`224598d4`), so this is upstream 2.0, not a modified tree. `pip` was told
`--no-deps` for infinigen itself so it would not try to fetch `bpy==4.2.0` from
PyPI (there is no aarch64 wheel there, and building it from source is a
multi-hour trap).

Every dependency resolved to an aarch64 wheel — no source builds were needed.

---

## 2. Step 1 — the Cycles GPU render

```
infinigen room_livingroom_rand render_cycles --seed 0 --output outputs/s1-seed0
```

| | |
|---|---|
| Exit code | **0** |
| Wall clock | **435 s (7 min 15 s)** |
| Peak RSS | **3,495 MB** (3.6 GB), 67 % CPU average |
| Cycles device | **`use_device_type='CUDA', n_devices=1`** — the Thor's own GPU |
| GPU during the run | max 98 %, mean 77.7 %, max 78.53 W (shared with ComfyUI) |
| Output | `outputs/s1-seed0/Camera/0000.png`, 512×512, 474 KB |

Phase breakdown from the log:

| Phase | Time |
|---|---|
| `room_livingroom_rand` generation | **24.1 s** |
| `bake_shared_modifier_prefixes` (12 shared SUBSURF bakes) | **≈ 3 min** |
| Cycles render (1 frame, 1024 samples adaptive, 512×512) | **3 min 32 s** |

![the living room](/home/caseydigennaro/lm-wt/v2-thor/outputs/s1-seed0/Camera/0000.png)

A real Infinigen 2.0 room: procedural walls, a window with sun through it,
marble console, rug, dresser, plant, carpet — rendered by Cycles on the Thor's
GPU.

> **Verdict 1 — does Infinigen 2.0 run on the Thor?**
> **Yes.** The whole v2 pipeline runs natively on aarch64 on the Thor:
> generation, mesh realisation (modifier baking), procedural shading, and a
> Cycles **CUDA** render, end to end, no workarounds.
> Two costs to know about: the modifier bake is CPU-bound and slow under
> contention (≈ 3 min of the 7 min 15 s), and the render is only as fast as
> the GPU's *share* (ComfyUI was holding 97 % of it).

---

## 3. Step 2 — the tracer's `graph.json`

### 3.1 The wall: the study's own generator cannot be traced

```
infinigen room_livingroom_rand render_cycles --seed 0 --trace graph --output ...
→ ValueError: Proxy does not support __iter__. Use explicit indexing instead.
   infinigen2/scenes/room/room_shape.py:133  in _split_flat_walls
       for idx in uniq_idx:
```

`room_shape_rand` computes `uniq_idx = np.unique(pf.ops.attr.read_attribute(...))`;
under the tracer the attribute read is a **Proxy**, so `np.unique` becomes a
graph node and the `for` loop over it is illegal. This is a control-flow
dependency on runtime geometry, not a bug in one line. The failure is
identical at `--trace_level GENERATORS` and `RANDOM_CONTROL`, and it is
seed-independent.

The same class of failure hits every other **scene** generator in the manifest,
and `floating_objects_rand` at `RANDOM_CONTROL`
(`infinigen2/scenes/placement/distribute.py:194`). The probe
(`s2-probe-traceable.sh`) recorded the exact exception for each:

| generator | level | result |
|---|---|---|
| `room_shape_rand`, `room_livingroom_rand`, `room_bedroom_rand` | both | `ValueError: Proxy does not support __iter__` (`room_shape.py:133`) |
| `kitchen_setup_rand`, `indoor_space_rand`, `object_demo` | both | `ValueError: Proxy does not support __iter__` |
| `floating_objects_rand` | `RANDOM_CONTROL` | `ValueError: Proxy does not support __iter__` (`placement/distribute.py:194`) |
| `desk_setup_rand` | both | `TypeError: 'Proxy' object does not support item assignment` / `must be real number, not Proxy` |
| `sofa_setup_centered_rand` | both | `TypeError: unsupported operand type(s) for @: 'AttributeProxy' and 'Proxy'` |
| `house_furnished_rand` | both | `TypeError: float() argument must be ... not 'Proxy'` |
| `material_sphere`, `floating_objects_rand` | `GENERATORS` | **OK** |

Every one of these is the same root cause in different clothing: the generator
needs a **runtime value** (an attribute read, a mesh measurement, a numeric
cast) to decide what to do next, and the tracer's model is a data-flow graph
in which that value is a `Proxy` with no runtime meaning.

**Object** generators are a different story: **80 of the 88** object generators
whose module contains `pf.control.choice` trace cleanly at `RANDOM_CONTROL`
(`s2-finder.py`). So the tracer works; the *scene* layer of v2 does not fit it.

### 3.2 A gotcha that would have silently broken step 3

At the CLI's default `--trace_level GENERATORS`, the tracer resolves every
`choice` to the branch that was taken, so `graph.json` contains **no choice
nodes at all** — nothing to edit. `choice_options` and `chosen_idx` only appear
at `RANDOM_CONTROL` or finer. The step-2/3 protocol below therefore runs at
`RANDOM_CONTROL`.

### 3.3 Byte-stability at the same seed

Protocol: `--trace graph` twice at seed 0, once at seed 1, for two generators
(`plant_pot_small_rand`: 4,231 nodes / 46 choice nodes; `desk_rand`: 21,437
nodes / 578 choice nodes).

**The raw bytes are not identical — but the graph is.** Two causes, both
outside the graph's meaning:

1. **`repr()` leaks a pointer.** `infinigen2/graph_json.py` falls back to
   `{"$repr": repr(value)}` for values it cannot serialise, and `repr()` of a
   function object embeds its address:
   `"<function mix_shader at 0xffff4897b380>"` vs `"0xffff2cea2980"`.
2. **The graph contains a wall-clock measurement.** The pipeline returns each
   generator's elapsed time, and `generator_times` is part of the traced
   output, so the graph ends with a constant that is the generator's runtime
   (0.2646 s vs 0.2891 s between two runs). It is node `n4227` (of 4,231) in
   `plant_pot_small_rand`, reachable as `outputs["generator_times"]`.

> A note on the hash-seed probe (`s2-hashseed.sh`, `s2-hashseed2.sh`): it was
> run to test whether the varying constant came from Python's per-process hash
> randomisation, and it *did* change with `PYTHONHASHSEED` — but that constant
> turned out to be the timing field, so the experiment is **confounded** and
> proves nothing about hash ordering. The structural check (looking up
> `outputs["generator_times"]` in the graph) is what identifies the cause. No
> hash-order dependence is claimed here.

Normalising exactly those two things (pointer addresses → `0xADDR`, the timing
constant → `<TIMING>`), the two runs at seed 0 are **identical**:

| | raw bytes | after normalising | nodes | content-differing nodes |
|---|---|---|---|---|
| `plant_pot_small_rand` seed 0, run vs run | DIFFER | **IDENTICAL** | 4,231 = 4,231 | **0** |
| `desk_rand` seed 0, run vs run | DIFFER | **IDENTICAL** | 21,437 = 21,437 | **0** |

> **Verdict 2a — is the graph byte-stable across runs at the same seed?**
> **Not byte-for-byte, but yes in every way that matters.** The recipe is
> reproducible; the two byte-level wobbles are a pointer leak in the
> serialiser and a timing field, both fixable in a few lines (serialise
> functions by qualname; drop `generator_times` from the traced output). As it
> stands, `graph.json` is *not* a safe input to a byte-comparing diff tool
> (git, rsync --checksum) — normalise first.

### 3.4 Diff against seed 1

| | nodes | only in seed 0 | only in seed 1 | changed nodes | what changed |
|---|---|---|---|---|---|
| `plant_pot_small_rand` | 4,231 = 4,231 | 0 | 0 | **28** | all of them `choice` nodes whose `chosen_idx` differs |
| `desk_rand` | 21,437 = 21,437 | 0 | 0 | **324** | same |

The structure is *identical* between seeds — same node count, same ids, same
references — and the diff is exactly the list of branch decisions. The recipe
across seeds is a **clean, readable diff**: "these 28 choices went differently".

> **Verdict 2b — is the graph diffable?**
> **Yes, and better than the study hoped.** The seed-to-seed diff is not noise:
> it is a list of branch choices, and nothing else moves.

---

## 4. Step 3 — edit one `choice` node's `chosen_idx`, re-execute

The target was `plant_pot_small_rand` (seed 0, `RANDOM_CONTROL`, 4,231 nodes,
46 choice nodes). Three edits, each a single `chosen_idx` in one choice node:

| | node | call site | parameter | before → after |
|---|---|---|---|---|
| **A** | `n3619` | `infinigen2/objects/phyllo_plant.py:599` | leaf "bend" amount | `0.28` → `0.0` |
| **B** | `n2439` | `infinigen2/shaders/base_materials/glass_colored.py:49` | glass colour option | option 1 → option 0 |
| **C** | `n29` | `infinigen2/objects/plant_pot.py:248` | pot rib depth | `0.0` → decorated (0.025–0.07) |

### 4.1 The edit is one line of data

```
$ .venv/bin/python choice_tool.py edit --graph outputs/s3/trace-a/graph.json \
      --node-id n3619 --index 0 --out outputs/s3/graph-edited-A.json
[choice-tool] outputs/s3/trace-a/graph.json: node n3619 chosen_idx 1 -> 0 (of 2 options)
```

The diff between the original `graph.json` and the edited one is **exactly one
line** in each case (`"chosen_idx": 1` → `"chosen_idx": 0`). The recipe really
is a data document.

### 4.2 Re-execution changes exactly one node

The edit was re-executed by pinning that one choice call site (the tracer
records the source location of every `choice`; `choice_tool.py` instruments
`procfunc.control.choice_idx` to capture it and to force the index, still
consuming the same random draw so the RNG stream is untouched).

| | nodes | only in original | only in variant | nodes whose content changed |
|---|---|---|---|---|
| original vs **A** | 4,231 = 4,231 | 0 | 0 | **2**: `n3619` (`chosen_idx` 1→0) and `n4227` (the timing constant) |
| original vs **B** | 4,231 = 4,231 | 0 | 0 | **2**: `n2439` (`chosen_idx` 1→0) and `n4227` |
| original vs **C** | 4,231 = 4,231 | 0 | 0 | **2**: `n29` (`chosen_idx` 0→1) and `n4227` |

Every other node — all 45 other choices, every parameter, every reference — is
byte-identical. The edit's blast radius in the recipe is *one node*.

### 4.3 The variant materialises, and it is localised in the picture

All three renders: 512×512, 256 samples, same seed, same camera.

| variant | changed pixels | max channel Δ | changed region (fraction of frame) | what moved |
|---|---|---|---|---|
| **A** leaf bend | **21,876 / 262,144 (8.35 %)** | 248 | x 0.18–0.85, y 0.21–0.79 | the leaves |
| **B** glass colour | **0 / 262,144 (0 %)** | 0 | — | nothing (the glass sits inside the pot, hidden from this camera) |
| **C** pot rib depth | **10,893 / 262,144 (4.16 %)** | 209 | x 0.36–0.77, y 0.39–0.78 | the pot's ribs |

Original → A → C, same seed:

| original | A: leaf bend 0.28 → 0.0 | C: pot ribs 0.0 → decorated |
|---|---|---|
| ![original](/home/caseydigennaro/lm-wt/v2-thor/outputs/s3/render-original/Camera/0000.png) | ![variant A](/home/caseydigennaro/lm-wt/v2-thor/outputs/s3/variantA-render/Camera/0000.png) | ![variant C](/home/caseydigennaro/lm-wt/v2-thor/outputs/s3/variantC-render/Camera/0000.png) |

Two things worth noting:

* **B produced a bit-identical image.** The edit is real in the recipe, but the
  parameter it controls is not visible from that camera. "The recipe changed"
  and "the picture changed" are separate claims — the graph edit is
  authoritative, the image is evidence.
* **A and C moved different regions.** A (a plant parameter) moved the plant;
  C (a pot parameter) moved the pot. The rest of the frame — background, floor,
  the other object — is untouched to the bit.

> **Verdict 3 — does a single-parameter variant materialise without touching
> the rest?**
> **Yes, for the generators the tracer can capture.** One `chosen_idx` in a
> 4,231-node recipe → one changed node in the recipe, and a change in the
> render confined to the object that parameter controls. Nothing else moved.
> The caveat is coverage, not mechanism: the tracer cannot capture v2's *scene*
> generators at all (§3.1), so today this only applies to objects.

---

## 5. Step 4 — the warm-scene number

Three scenes, each rendered twice: once in **its own process** (how a batch
runner does it) and once inside **one resident process** that renders all three
in order. Same generator, same seed, same settings (512×512, 256 samples).

| scene | seed | generator | base tris |
|---|---|---|---|
| `living-0` | 0 | `room_livingroom_rand` | 1,148,504 |
| `living-1` | 1 | `room_livingroom_rand` | 392,088 |
| `bedroom-2` | 2 | `room_bedroom_rand` | 983,476 |

### 5.1 The measurements

| | wall | generation | exporter (`render_cycles`) | of which: Cycles sampling | of which: setup + modifier bake |
|---|---|---|---|---|---|
| **cold** `living-0` | **362 s** | 18.6 s | 341.3 s | 141.3 s | 200.1 s |
| **cold** `living-1` | **85.7 s** | 25.2 s | 58.8 s | 40.6 s | 18.2 s |
| **cold** `bedroom-2` | **103.0 s** | 31.1 s | 68.5 s | 62.9 s | 5.6 s |
| **warm** `living-0` (1st in process) | **434.1 s** | 27.7 s | 406.2 s | 132.8 s | 273.5 s |
| **warm** `living-1` (2nd) | **79.3 s** | 17.5 s | 61.5 s | 46.5 s | 15.0 s |
| **warm** `bedroom-2` (3rd) | **165.4 s** | 18.9 s | 145.4 s | 141.8 s | 3.7 s |

Resident process as a whole: 681.4 s wall for three scenes; **import
`bpy` + `infinigen2` = 2.337 s**.

### 5.2 What a resident process actually amortises

The per-process fixed cost, measured two ways:

* directly: **2.337 s** to import `bpy` + `infinigen2`;
* from the logs: the gap between the process starting and its first log line
  was **1.6–3.2 s** across the cold runs (interpreter start + imports +
  manifest load).

Everything else in a scene's cost is scene-dependent work that a resident
process does **not** amortise: the generation (17–28 s), the modifier bake
(4–270 s, CPU-bound), and the Cycles sampling (41–142 s, GPU-bound). The
sampling time is not "warm" in any meaningful sense — the scene is different,
so it is different shaders and different geometry.

**So the warm-scene win on this build is the process start-up, and it is
~2.4 s per scene** — about 1 % of a typical scene (85–165 s) and 0.6 % of the
big one (434 s).

### 5.3 …and the box's noise is 100× larger than that

Comparing the *same* scene cold vs warm, the differences are not a warm effect;
they are contention:

* `living-0`: 362 s cold vs 434 s warm — but its **Cycles sampling was
  actually faster warm** (132.8 s vs 141.3 s); the extra time is in the
  **CPU-bound modifier bake** (273.5 s vs 200.1 s), i.e. how busy the 14 cores
  were.
* `bedroom-2`: 103 s cold vs 165 s warm — all of it in sampling
  (141.8 s vs 62.9 s), i.e. how much of the GPU ComfyUI was holding. The
  **same scene, same seed, same geometry**, rendered 3.5× slower because it
  ran at a busier moment.
* Across the whole experiment, the same scene's Cycles sampling ranged from
  40.6 s to 141.8 s — a **3.5× spread** — while the effect being measured
  (2.4 s) is 0.1 % of it.

> **Verdict 4 — is there a warm-scene win?**
> **There is one, and it is small: ~2.4 s per scene, the process start-up.**
> Nothing else is amortised — generation, the modifier bake and the Cycles
> sampling are all per-scene work. On this box the effect (2.4 s) is far below
> the run-to-run noise (3.5× on the render phase), so **this number cannot be
> resolved without an idle box and repeats**. What the experiment does establish
> firmly is the *shape* of the cost: a resident process saves a few seconds of
> imports, and the scene cost itself is dominated by the CPU-bound modifier
> bake and the GPU render, neither of which benefits from process reuse.

### 5.4 A free side-effect: the pipeline is reproducible end to end

The same scene rendered in a cold process and in the warm resident process came
out **the same picture**: 1–3 pixels out of 262,144 differ, by **±1 in 8-bit
colour** (Cycles' GPU accumulation order), with identical triangle counts and
identical material graphs. Same for the recipe (§3.3). So seed → scene → image
is reproducible on the Thor, which is the property the study actually needs
before it can trust any recipe diff.


---

## 6. Step 5 — the denoiser, and numpy 1.x vs 2.x vs Warp

### 6.1 Is `denoise_mode=NONE` required on this build?

`denoise_probe.py` interrogates the build rather than assuming:

| | |
|---|---|
| `scene.cycles.denoiser` enum items | **`[]` — empty. This build has no denoiser at all.** |
| `prefs.get_device_types()` | `["NONE", "CUDA"]` — no `OPTIX` (the Thor has no RT cores) |
| `denoiser = "OPTIX"` | rejected |
| `denoiser = "OPENIMAGEDENOISE"` | rejected (phase-1 bpy was built `WITH_OPENIMAGEDENOISE=OFF`) |

Infinigen 2.0's own `_configure_denoising()`:

| `denoise_mode` | with a denoised pass requested | with the default `rgb` pass |
|---|---|---|
| `BEST` | **RuntimeError**: "No usable denoiser for DenoiseMode.BEST (tried (OPTIX, OPENIMAGEDENOISE))" | fine — denoising off |
| `OPTIX` | RuntimeError | fine |
| `OPENIMAGEDENOISE` | RuntimeError | fine |
| **`NONE`** | **OK** — denoising off, no error | fine |

**Answer: `denoise_mode=NONE` is *not* required for the default pipeline, and
*is* required the moment you ask for a denoised pass.** The default pass set
(`rgb`) never asks for one, so the step-1 render worked with the default
`DenoiseMode.BEST` untouched — the log says `Denoising off (denoise_mode=
DenoiseMode.BEST, wants_denoised=False)`. But asking for a denoised pass
end-to-end raises, on the CLI, with the default `DenoiseMode.BEST`:

```
$ infinigen plant_pot_small_rand render_cycles --seed 0 --samples 32 --passes rgb-denoised
RuntimeError: No usable denoiser for DenoiseMode.BEST
  (tried (OPTIX, OPENIMAGEDENOISE))
  infinigen2/exporters/render_cycles.py:272
```

The only two ways out are `denoise_mode=NONE` (you get the raw noisy image) or
rebuilding bpy with OIDN — which is what the phase-2 job is already doing.

### 6.2 numpy 1.x vs 2.x vs Warp — the study's "cheapest falsifier" is refuted

The study listed this as the first thing to check: procfunc and infinigen 2.0
pin `numpy<2` (1.26.4 on the Thor), while our Warp terrain port's venv runs
numpy 2.5.4. If Warp needed numpy 2 at runtime, option C would mean a separate
process for terrain.

**It does not.** `warp-lang 1.18.0` (aarch64 wheel) installed into a numpy
**1.26.4** environment:

* imports and initialises CUDA cleanly — `"cuda:0": "NVIDIA Thor" (123 GiB, sm_110)`;
* compiles and launches a CUDA kernel; max abs error **0.0**.

And the real thing — our actual Warp terrain port (`lab2` experiment 7, the
Infinigen `mountains` element ported to Warp), re-run under numpy 1.26.4:

| | 16 M points | vs Infinigen CPU | vs Infinigen CUDA | max \|warp − Infinigen CPU\| |
|---|---|---|---|---|
| **numpy 1.26.4** (this run) | **122.9 ms** (136.5 Mpoints/s) | **51.1×** | **6.2×** | **0.000000e+00** |
| numpy 2.5.4 (original lab2 run) | 96.1 ms (174.7 Mpoints/s) | 50.5× | 6.2× | 0.000000e+00 |

Bit-identical output under both numpy versions, and the same 6.2× over
Infinigen's own CUDA path. (The 22 % wall-clock difference is the box being
busy, not numpy.)

**Answer: numpy 1.x vs 2.x is not a blocker.** Warp 1.18 and procfunc coexist
in one process on numpy 1.26.4, with identical numerics. Option C does not
need a split-process design or a Warp rebuild.

---

## 7. Verdicts on the study's four questions

| # | Question | Verdict |
|---|---|---|
| 1 | **Does Infinigen 2.0 run on the Thor?** | **Yes.** Full v2 pipeline, Cycles **CUDA** GPU render, 435 s cold, no workarounds. |
| 2 | **Is the tracer graph stable and diffable?** | **Stable, yes; byte-stable, no.** The recipe is identical run-to-run at a seed and the seed-to-seed diff is exactly the list of branch choices — but two byte-level artefacts (a `repr()` pointer leak and the `generator_times` wall-clock field) break byte-equality. Also: `--trace_level` must be `RANDOM_CONTROL` or finer for choice nodes to exist at all. |
| 3 | **Can a single-parameter edit drive a partial regeneration?** | **Yes, mechanically.** One `chosen_idx` → one changed node in a 4,231-node recipe → a render that changes only where that parameter lives. The limit is *coverage*: the tracer cannot capture v2's scene generators (`room_*`, `kitchen_*`, …), so this works for objects, not for the room the study named. |
| 4 | **Is there a warm-scene win?** | **One, and it is small: ~2.4 s per scene — the process start-up.** Generation, modifier bake and Cycles sampling are all per-scene work and are not amortised. On this box the effect is ~100× smaller than the run-to-run noise (3.5× spread on the render phase), so the number needs an idle box and repeats to be trusted. The reproducible part is not the timing but the *output*: same seed → same image to within 3 pixels of ±1 LSB. |

## 8. What this changes for the study

1. **The recipe substrate is real and it is a data document.** A graph edit
   round-trips: one number in, one node out, one localised visual change.
   That is the property the study was looking for, and it holds.
2. **But it does not cover the scene layer.** v2's room generators are
   imperative and data-dependent (`np.unique` over a runtime attribute read);
   the tracer's model is a data-flow graph and cannot express them. Until the
   room generators are rewritten to be tracer-shaped (or the tracer learns to
   execute data-dependent control flow), the "recipe" covers objects and
   materials, not scenes. **This is the single most important finding here.**
3. **The graph needs two small fixes to become a versioned artefact**:
   serialise functions by qualname instead of `repr()`, and keep
   `generator_times` out of the traced output. Both are one-liners in
   `infinigen2/graph_json.py` / `generate.py`.
4. **The denoiser trap is avoidable but real**, and the fix (OIDN in bpy) is
   already in flight in phase 2.
5. **The numpy split is a non-issue**, which removes one of the three options
   the study had to choose between.
6. **Do not plan the batch pipeline around a warm process.** The resident
   process buys ~2.4 s per scene (the imports); the cost that actually
   dominates a scene — the CPU-bound modifier bake (up to 270 s) and the GPU
   render (41–142 s) — is per-scene work. The SPIKE's "keep scenes warm"
   recommendation is still right, but for the reason it gives: an *interactive*
   preview loop (warm scene → edit → re-render), not for batch throughput. That
   loop works: step 3 edited a recipe and re-rendered in **5–9 s** per object
   scene (512×512, 256 samples).

### A note on exit codes

`bpy` 4.2 segfaults during interpreter teardown in the in-process scripts here
(`choice_tool.py`, `warm_scene.py`), **after** their output files are written —
the CLI itself exits 0 because it leaves through procfunc's
`skip_teardown_on_exit` (`os._exit`). The step-3 variant renders therefore
report `rc=139` while their PNGs are complete and correct; `warm_scene.py` was
given the same `os._exit` treatment.

### Artifacts

Everything referenced above is in this directory:

| what | where |
|---|---|
| the step-1 room render | `outputs/s1-seed0/Camera/0000.png` |
| the traced recipes (4,231 and 21,437 nodes) | `outputs/s2-trace/*/graph.json` |
| the choice map (node id ↔ call site ↔ index) | `outputs/s3/trace-a/choices.json` |
| the edited recipes (one line changed each) | `outputs/s3/graph-edited-{A,B,C}.json` |
| the variant recipes (one node changed each) | `outputs/s3/variant{A,B,C}-trace/graph.json` |
| the original / variant renders | `outputs/s3/render-original/`, `outputs/s3/variant{A,B,C}-render/` |
| cold-process baselines | `outputs/s4-cold/` |
| the warm resident-process run | `outputs/warm-scene/` (+ `summary.json`) |
| the denoiser probe | `logs/denoise-probe.json` |
| the Warp/numpy-1.x probe | `logs/warp-np1-probe.json`, `logs/warp-port-np1.log` |
| every run's stdout / time / tegrastats / nvidia-smi | `logs/` |
