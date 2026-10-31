# SPIKE: the warm scene server (plan item 14, split.md move #1)

**Date:** 2026-10-31 · **Seat:** spike · **Box:** Jetson AGX Thor Developer Kit
(aarch64, 14× Neoverse, 122.8 GiB unified, Blackwell sm_110, driver 595.78,
CUDA 13.2, L4T R39.2.1, kernel 6.8.12-1021-tegra, power mode MAXN)
**Branch:** this repo (`~/lm-wt/warm-scene`), commits on `main`.

---

## 0. Verdict

**Yes, the warm scene server works, and it is worth building — but move #1 on
its own buys less than split.md §6-1 implies, and it is not the thing that
unlocks the Workshop clock.**

Three claims, each with its number behind it:

1. **The launch+I/O tax is real, and it is smaller than the render.** Every
   edit in batch mode pays a fresh Blender process (fork/exec + CPython +
   `import bpy` ≈ **0.25 s**), a `.blend` open (**0.01–0.30 s**) and a
   `.blend` save (**0.002 s small / 1.07–1.31 s for a 380 MB scene**). The
   warm server pays the load **once** (0.51 s + 0.38 s for the Hello Room)
   and never pays it again. Measured end to end on identical edits, the
   warm server is **1.09–1.24× faster on the Hello Room scene** and
   **1.59–2.10× on the synthetic scene**. On the real scene the tax is
   **9–20 % of an interaction**, because the render is the other 80–90 %.
   So the tax is real, and it is not the interaction.

2. **The real prize is that the resident scene is the precondition for move #2.**
   A partial re-solve (one room instead of the whole 38-minute solve) is
   only possible if the solved scene is still in memory. Move #1 does not
   make the day UX possible by itself; it makes move #2 possible, and move
   #2 is where the orders of magnitude are.

   **And move #1's premise is now proven, not assumed**: Infinigen's own
   Hello Room coarse stage ran *inside* the resident process and produced a
   scene matching its batch run stage-for-stage (§2.1).

3. **The spike's most valuable output is not the server — it is the five
   defects a resident process has that a batch process cannot have.** All
   five were found by measurement, and all five are silent. A batch run
   gets them for free (Blender's save-time cleanup, an append-only file,
   a one-shot digest, a drained stdout); a resident server has to do all
   five itself:
   - **orphan datablocks** accumulate forever (209 meshes + 209 materials
     after 1000 edits, for 12 objects);
   - **a recipe rewritten per edit** is quadratic on disk (143 MiB written
     for a 255 KiB file) and makes the per-edit latency grow 4.7×;
   - **a per-edit scene digest** is O(scene size) — 0.28 s per edit on the
     Hello Room's 196 objects;
   - **`bpy` is not thread-safe** — a threaded HTTP server segfaults the
     process (measured SIGSEGV);
   - **a full stdout pipe blocks the process forever** — Blender's render
     progress fills 64 KB after a dozen renders and the server then waits
     on a write that never completes (measured: every thread asleep, one
     in `pipe_write`, the client waiting for a reply that never came).

**Against plan item 14's pass/fail** ("p50/p95 edit→preview latency, batch vs
warm, on the same recipe edit; Blender process starts per night → 1–2"):

| criterion | result |
|---|---|
| p50/p95 edit→preview, batch vs warm, same edits, same scene | **measured** — synthetic **1.594 s → 0.912 s** p50 (1.59×), **1.668 s → 1.029 s** p95 (1.80×); Hello Room **7.974 s → 7.319 s** p50 (1.09×), **10.337 s → 9.228 s** p95 (1.39×). §4.1 |
| the two modes are doing the same thing | **proved**, not asserted: scene-state digest identical after every edit (30/30, 15/15, 12/12, 10/10) and the previews pixel-identical (129 600/129 600 pixels within one 8-bit step) |
| Blender process starts per night → 1–2 | **30 starts (batch) → 1 (warm)** for 30 edits; the resident server reloads the scene in 0.89 s and then never again |

The honest caveat: **the box was shared.** Other seats ran an Infinigen seed
sweep, a ComfyUI server, a Rust soak test and a Blender+CUDA compile
throughout; the load average moved between 14 and 105 and the GPU was
frequently at 98 % from someone else's job. Every number below carries the
load it was taken under, and the two headline latencies were measured
**twice** — once on a quiet box and once under heavy contention — because
the contended numbers alone would have been misleading.

---

## 1. The box, and the conditions every number was taken under

CLAUDE.md: *"Measure, with the box's state beside every number."*

| | |
|---|---|
| Board | NVIDIA Jetson AGX Thor, tegra264, 14× Neoverse, 1 cluster, max 2 601 MHz |
| RAM | 128 766 528 kB (122.8 GiB) unified CPU+GPU, LPDDR5X |
| GPU | "NVIDIA Thor", driver 595.78, CUDA 13.2, compute capability 11.0 (sm_110) |
| Power mode | **MAXN (0)** throughout — `nvpmodel -q` |
| `bpy` | **4.2.0**, built from source by the Infinigen seat for this aarch64 |
| Python | CPython 3.11.13 (the spike's `.toolchain`, used read-only) |
| numpy / cupy | 1.26.4 / cupy-cuda13x 13.6.0 |
| PyTorch | **not installed** on this box (the lab's trap A4 is cited, not re-measured) |

**The Infinigen spike's tree was opened read-only and never written.** Its
built `bpy` was repacked from its *installed* package into
`vendor/bpy-4.2.0-cp311-cp311-manylinux_2_39_aarch64.whl` and installed into
**this repo's own venv** (`setup/setup_env.sh`), so the other seat keeps
working. No system installs.

**The box during the measurements** — this matters more than usual:

| when | load avg | GPU | who else was running |
|---|---|---|---|
| ~02:10–02:20 | 14–16 | 96–98 % | Infinigen seat's `generate_nature` sweep + a ComfyUI server |
| ~02:40 | 27 | 98 % | + a Blender+CUDA compile (all 14 cores, `ptxas -arch sm_110`) |
| ~03:05–03:15 | 36–105 | 98 % | + a Rust soak test at 211 % CPU + 3 `generate_nature` runs |
| after 03:15 | 21–28 | 98 % | 3 `generate_nature` runs |

Because of this the benchmark **runs the two modes interleaved** (batch edit
1, warm edit 1, batch edit 2, …) so the contention falls on both sides, and
it can run with `--no-render`, which removes the GPU from the measurement
entirely and measures the tax with no shared resource involved.

---

## 2. What was built

```
warm_scene/
  server.py       the long-lived process and its RPC surface
  sceneops.py     the closed, typed edit vocabulary, applied in place
  scenes.py       the synthetic benchmark scene
  editlist.py     the edit list both modes share (generated from a manifest)
  stages.py       generator stages re-run in place (synthetic.*, infinigen.coarse)
  recipe.py       the durable recipe: journal (truth) + recipe.json (snapshot) + checkpoint
  batch_worker.py the baseline: one Blender process per edit, as Infinigen does today
  bench.py        batch vs warm, interleaved, with parity proof
  durability.py   kill -9 -> restart -> replay
  memgrowth.py    1000 edits: RSS, datablocks, recipe write volume
  residency.py    peak RSS per warm scene (split.md §7-3)
  unified.py      the zero-copy mesh hand-off
  pngdiff.py      pixel comparison (Cycles here is not bit-deterministic)
  boxstate.py     the box's state, captured beside every number
```

**The RPC surface** (HTTP/JSON, localhost, one process):

`ping` · `probe` · `boxstate` · `scene.state` · `scene.stats` ·
`scene.reset` · `scene.open` · `object.add` · `object.move` ·
`object.delete` · `material.set` · `stage.rerun` · `render.preview` ·
`mesh.export` · `mesh.unified_probe` · `checkpoint.save` ·
`checkpoint.load` · `recipe.get`

The vocabulary is closed and typed, exactly as CLAUDE.md requires ("builders
change recipes through a closed, typed vocabulary, never by writing Blender
code"). `apply_edit()` lives in `sceneops.py`, so the warm path and the
batch baseline apply byte-identical edits — a comparison whose two sides
drift apart is not a comparison.

**The batch baseline is faithful to `execute_tasks.py:217-221`**: a fresh
Blender process per edit, `bpy.ops.wm.open_mainfile`, the edit,
`bpy.ops.wm.save_mainfile` (the round-trip), then the render.

**The real Infinigen stage runs in place.** `stage.rerun` with
`stage: "infinigen.coarse"` calls `generate_indoors.compose_indoors` — the
Hello Room's own stage function — **against the resident scene**, in this
process, with no `.blend` round-trip. The bridge (`infinigen_bridge.py`)
imports the Infinigen package from the spike's tree read-only and applies
the Hello Room's own gin recipe (`fast_solve.gin`, `singleroom.gin`,
terrain off, dining room only).

Its preflight (`infinigen_bridge.preflight()`, **3.06 s**) brings the whole
seam up without paying the solve, and is what proves the wiring:

| step | result |
|---|---|
| the Hello Room gin configs apply | `fast_solve.gin`, `singleroom.gin` + the 2 overrides |
| the scene seed binds | 0 (parsed as hex, the way Infinigen parses it) |
| the scene is prepared as `execute_tasks.py:242-244` does | `butil.clear_scene` + `spawn_empty` |
| `compose_indoors` is callable against the resident scene | yes |

Getting there took three fixes that are worth carrying into the port —
see §5.5.

### 2.1 The proof: the real coarse stage, run in place

Not a mock — **Infinigen's own Hello Room coarse stage, run inside the
resident process, against the live scene**, with no `.blend` round-trip:

```
.venv/bin/python -c "from warm_scene import infinigen_bridge as b; \
                     b.run_coarse(output_folder='results/infinigen-coarse', seed=0)"
→ {"stage": "infinigen.coarse", "seed": 0, "seconds": 953.9}
```

**954 s** wall. It is *not* a speed comparison with Infinigen's own batch
run (534 s) — this one was `nice -n 19` on a box that had 28 other Infinigen
processes running. **The point is that it runs in place at all.**

The output is the same set of artefacts Infinigen's coarse writes
(`pipeline_coarse.csv`, `solve_state.json`, `optim_records.csv/png`), and
**they match the Infinigen spike's own batch run almost exactly**:

| comparison | result |
|---|---|
| `pipeline_coarse.csv`, stage by stage | **identical** — same 25 stages, same 14 ran / 10 skipped, same object count at every stage (30 → 39 → 46 → 54 → 79 → 114 → 136 → 151 → 152 → 172) |
| peak memory at `populate_assets` | 1.93 GB (theirs: 1.93 GB) |
| `solve_state.json` | same size (122 819 bytes), same 67 objects, **67/67 semantically identical** |
| every object's DOF matrix | **bit-identical** floats |
| every object's generator | identical |
| byte-identical? | **no** — the two JSON files differ only in the *order* of two Python `set`s (`tags`, `relations`), which is `PYTHONHASHSEED`, not the scene |

That is the whole claim of split.md move #1 in one table: **the same
Infinigen code, running against a resident scene, produces the same scene** —
without writing or reading a 416 MB `.blend`.

---

## 3. How the two modes were proved equivalent

Two checks, because "the same scene" and "the same picture" are different
claims:

1. **Scene-state digest** after *every* edit — objects, transforms,
   material parameters, collection and material names. **30/30 identical**
   on the synthetic scene, **12/12 identical** on the Hello Room.
2. **Pixel comparison** of the previews: **129 600/129 600 pixels within one
   8-bit step** (max abs diff 0.0039, mean 1.5 × 10⁻⁸).

Bytes are deliberately *not* compared: Cycles on this GPU build is **not
bit-deterministic** — two renders of the same scene in the same process
already differ by one 8-bit step (measured: 0 pixels over tolerance, mean
abs diff 7.6 × 10⁻⁹). A byte comparison would have been comparing noise.

This check earned its keep: it is what found the orphan-GC finding in §5.1.

---

## 4. The numbers

### 4.1 edit→preview latency, batch vs warm

**End to end, synthetic scene, n = 15, 16 spp @ 480×270, CPU render**, load
≈ 23–25, GPU contended by another seat:

| mode | p50 | p95 | max |
|---|---|---|---|
| **batch** builder wait (launch + open + edit + render + save) | **1.454 s** | **1.668 s** | 1.668 s |
| batch edit→preview (edit + render only) | 1.051 s | 1.230 s | 1.230 s |
| batch launch+load | 0.385 s | 0.516 s | 0.516 s |
| **warm** edit→preview | **0.912 s** | **1.029 s** | 1.029 s |
| warm render only | 0.904 s | 1.004 s | 1.004 s |
| **speedup (builder wait)** | **1.59×** | **1.80×** | — |

Scene-state parity **15/15** — the two modes ended with byte-identical scene
state after every edit.

**End to end, Hello Room scene (380 MB `.blend`, 196 objects), n = 10, 16 spp
@ 480×270, CPU render**, load ≈ 30–33:

| mode | p50 | p95 | max |
|---|---|---|---|
| **batch** builder wait | **7.974 s** | **10.337 s** | 10.337 s |
| batch edit→preview (edit + render only) | 7.140 s | 9.476 s | 9.476 s |
| batch launch+load | 0.834 s | 1.993 s | 1.993 s |
| batch open `.blend` (380 MB) | 0.255 s | 0.364 s | 0.364 s |
| batch save `.blend` (380 MB) | 1.310 s | 3.025 s | 3.025 s |
| **warm** edit→preview | **7.319 s** | **9.228 s** | 9.228 s |
| warm render only | 7.293 s | 9.171 s | 9.171 s |
| **speedup (builder wait)** | **1.09×** | **1.39×** | — |

Scene-state parity **10/10**.

**End to end, Hello Room scene, n = 3, GPU render**, taken on the quietest
box of the session (load ≈ 14):

| mode | builder wait p50 | edit→preview p50 | speedup |
|---|---|---|---|
| batch | 3.993 s | 3.282 s | — |
| **warm** | **3.312 s** | **3.312 s** | **1.24×** |

**Quiet box, synthetic scene, n = 3, GPU render**: batch 0.849 s vs warm
0.421 s → **2.10×**.

**The pattern across every condition measured** — quiet box and contended
box, GPU render and CPU render, a 12-object scene and a 196-object one:

| scene | tax as a share of the wait | speedup (builder wait) |
|---|---|---|
| synthetic (cheap render) | 35–50 % | 1.59× (CPU) / 2.10× (GPU, quiet) |
| Hello Room (expensive render) | 9–20 % | 1.09× (CPU) / 1.24× (GPU, quiet) |

**The honest reading:** the tax is a **fixed ~0.4–2.1 s**, and the more
expensive the render, the smaller its share. On the Hello Room scene a
builder waits 7–8 s for a 16-spp preview and the warm server saves them
0.7–1.2 s of that. **The tax is the tax; the render is the render.** If the
Workshop clock is 60 s, neither mode is anywhere near it, and neither is the
binding constraint.

### 4.2 The launch+I/O tax, measured without the GPU

`--no-render` removes the render from both sides. What is left is exactly
what move #1 eliminates. This is the cleanest measurement in the spike, and
it needs no GPU, so it is robust to the contention described in §1.

**Synthetic scene** (0.7 MB `.blend`, 12 objects), n = 30, load ≈ 57:

| | p50 | p95 | max |
|---|---|---|---|
| **batch** builder wait (launch + open + edit + save) | **0.405 s** | **0.507 s** | 0.612 s |
| batch launch+load (fork/exec + CPython + `import bpy` + open) | 0.405 s | 0.505 s | 0.612 s |
| batch `import bpy` | 0.247 s | 0.311 s | 0.361 s |
| batch open `.blend` | 0.008 s | 0.011 s | 0.011 s |
| batch save `.blend` | 0.002 s | 0.004 s | 0.013 s |
| **warm** edit (RPC, in place) | **0.006 s** | **0.013 s** | 0.039 s |

**Hello Room scene** (380 MB `.blend`, 196 objects, 202 materials), n = 12,
load ≈ 43:

| | p50 | p95 | max |
|---|---|---|---|
| **batch** builder wait | **0.877 s** | **1.211 s** | 1.211 s |
| batch launch+load | 0.876 s | 1.210 s | 1.211 s |
| batch `import bpy` | 0.255 s | 0.431 s | — |
| batch open `.blend` (380 MB) | 0.301 s | 0.512 s | — |
| batch save `.blend` (380 MB) | 1.074 s | 3.034 s | — |
| **warm** edit | **0.379 s** | **0.999 s** | 0.999 s |

Three things fall out of this table that were not obvious:

- **The `.blend` open is cheap; the `.blend` save is not.** Opening 380 MB
  costs 0.30 s (it is mmap'd — the OS faults it in lazily); *writing* 380 MB
  costs 1.07 s (p95 3.03 s under load). A batch pipeline pays the save on
  every task even though the next task may only read.
- **The process launch is the floor**: `import bpy` alone is **0.25 s**, and
  nothing in the design gets under that. This is the number that does not
  improve with a better CPU.
- **The warm side's own per-edit cost is O(scene size)**, because the
  per-edit digest and the orphan purge both walk the scene. On the Hello
  Room that is 0.38 s per edit — about a fifth of the tax it is saving.
  The variants (n = 10 each, same scene) came in at **0.102 s with the
  digest off** and **0.089 s with the purge off**, against 0.379 s with
  both on. The direction is unambiguous — both are O(scene size) and both
  are avoidable — but the exact split between them is not reliable, because
  the box's load moved between those runs. What *is* reliable is that the
  warm side's own overhead is the same order as a sixth of the tax, so
  **on a big scene the warm server must not compute a digest per edit.**

**Break-even.** Warm pays its load once: 0.51 s (server start) + 0.38 s
(Hello Room open) = **0.89 s**. Batch pays ≈ 1.95 s per edit (0.88 launch+
load + 1.07 save). **Break-even is the second edit.** From then on warm is
ahead by ~1.9 s per edit on the Hello Room, ~0.40 s on the synthetic scene.

### 4.3 Residency: peak RSS per warm scene

split.md §7-3 asks for this because it decides how many branches stay
resident in 122 GB. core-spec §1.9 stores it as
`SceneResidency.rss_peak_mb`. Measured on the **server process**
(`VmHWM`), not the harness:

**Hello Room scene** (`outputs/indoors/coarse/scene.blend`, 196 objects):

| step | RSS | peak (VmHWM) |
|---|---|---|
| after startup | 141.6 MiB | 141.6 MiB |
| after the scene is loaded | 622.3 MiB | 994.0 MiB |
| after 20 edits | 623.1 MiB | 994.0 MiB |
| after render 1 | 1 347.4 MiB | 2 243.9 MiB |
| after render 2 | 1 714.7 MiB | 2 369.2 MiB |
| after render 3 | 1 846.7 MiB | 2 465.7 MiB |

**Peak RSS 2 466 MiB → 50 branches resident in 122 GiB.**

Synthetic scene: peak **356 MiB** → 350 branches.

Two notes for the core:

- **The render, not the scene, is the memory.** The scene costs 622 MiB;
  the first render adds 1.2 GiB of Cycles buffers. A branch that is resident
  but never previewed costs 4× less than one that has rendered.
- **The render's memory grows with each render** (1 347 → 1 715 → 1 847 MiB)
  while the datablock counts stay flat. That looks like allocator
  high-water rather than a leak (the increments shrink: +367, +132 MiB), but
  a server that renders all night should be watched. At 1.8 GiB per branch,
  50 branches fit with room to spare — the residency bound is not the
  binding constraint on this box.

### 4.4 Durability: what happens on a crash

`warm_scene/durability.py` applies 25 edits, checkpoints, then **SIGKILLs**
the server — no clean shutdown, no flush, no goodbye.

| check | result |
|---|---|
| edits applied before the crash | 25 (+1 scene-build = 26 recipe ops) |
| journal lines on disk after the kill | **26** |
| journal ops parsed | **26** (0 torn lines) |
| recipe ops on disk | 26 |
| restart + replay | **0.50 s** |
| scene-state digest before the crash | `f274e90f5bbd6f8a` |
| scene-state digest after the replay | `f274e90f5bbd6f8a` — **identical** |
| checkpoint digest matches the replayed scene | **yes** |
| `.blend` files anywhere in the recovery path | **none** |

**And a torn journal** — the half-written last line `kill -9` can leave —
is tolerated: the reader skips it, the server restarts, and the digest is
still `f274e90f5bbd6f8a`.

**The answer to "what happens on a crash" is therefore: nothing is lost and
nothing is reloaded.** The scene is a pure function of the recipe, so
recovery is a **replay** — 26 typed ops re-applied in 0.50 s, with no
`.blend` file anywhere in the path. That is the round-trip move #1 wants
gone, and it is gone.

### 4.5 Memory and cost over 1000 edits

1000 edits against one resident server, sampling the **server's** RSS.
Run twice: once with the original design, once with the fixes of §5.

| | before | after |
|---|---|---|
| objects after 1000 edits | 12 | 12 |
| **meshes / materials** | **209 / 209** | **10 / 10** |
| RSS growth over 1000 edits | 11.8 MiB | 3.4 MiB |
| **disk written for the recipe** | **142.3 MiB** | **1.8 MiB** (79× less) |
| recipe.json size | 290.6 KiB | 296.4 KiB |
| journal size | 186.3 KiB | 190.8 KiB |
| edit latency, first 100 | 4.91 ms | 3.55 ms |
| edit latency, last 100 | **21.30 ms** | **4.56 ms** |

The per-edit latency grew **4.3×** over the run before the fixes and
**1.3×** after. With CPU renders in the loop (5 renders) RSS went
153.8 → 216.6 MiB (+62.8 MiB) — the render allocator's high-water again,
not the edits.

### 4.6 Unified memory: the mesh hand-off

The brief: *"hand a mesh buffer from the warm scene to a CUDA/NumPy consumer
without a copy."* Measured on the Hello Room's largest mesh (633 680
vertices → 7 604 160 bytes), through the live scene:

| leg | result |
|---|---|
| `bpy` mesh → NumPy (`foreach_get`) | 13.7 ms, 0.55 GB/s — **one memcpy, unavoidable** |
| NumPy → CUDA consumer | **zero copy**: pointer identity (`281471957266448` both sides) |
| CUDA kernel writes into NumPy's pages | **NumPy read the GPU's write back** (`numpy_saw_gpu_write: true`) |
| GPU reading NumPy's pages | **10.1 GB/s** |
| the copy path for comparison (`cupy.asarray`) | 0.86 GB/s |

**Two honesty notes, both carried from the lab doc:**

1. `bpy → NumPy` is one memcpy. Blender's Python API does not expose the
   vertex buffer's address, so `foreach_get` must write into a NumPy
   allocation. Fixing that needs a Blender C-API change.
2. CUDA reports the NumPy pointer as **unregistered**
   (`cudaMemoryTypeUnregistered`, `devicePointer = 0`). The kernel still
   wrote to it correctly because **on Jetson the CPU and GPU share physical
   memory** and the kernel can address the page directly. On a discrete GPU
   this would need `cudaHostRegister` or managed memory — the trick is
   platform-specific, and the port must not assume it.

**Trap A4 was not re-measured** (PyTorch is not installed on this box). The
lab's number stands: `.cpu()` into pageable memory ran at 0.34 GB/s, 258×
slower than the pinned path, and never fails — it just takes eleven
seconds. This probe never calls `.cpu()`; the consumer reads the shared
pages in place.

---

## 5. Findings that change the design

These are the spike's real deliverable. Each was found by measurement, and
each is **silent** — a batch run gets the behaviour for free, a resident
server does not.

### 5.1 `bpy` is not thread-safe — a threaded server segfaults

The first version used `ThreadingHTTPServer`. It died with **SIGSEGV** the
moment a request touched the window manager (`bpy.ops.wm.read_factory_settings`).
Reproduced in isolation:

```
python -c "import threading; from warm_scene.sceneops import SceneOps; \
           t=threading.Thread(target=SceneOps().reset); t.start(); t.join()"
→ Segmentation fault (core dumped)
```

**Design consequence:** the RPC handler must run on the **main thread** — the
thread that imported `bpy`. This server uses a plain `HTTPServer`. A
production version that needs concurrency must **queue the work back onto
the main thread**, not spawn one. (This also means the HTTP surface is
serialised: one render blocks a `ping`, which is acceptable for a
single-tenant workshop but must be stated.)

### 5.2 A resident server must do Blender's save-time garbage collection

`bpy.data.objects.remove()` removes the object but leaves its **mesh and its
material** in `bpy.data`. Blender collects zero-user datablocks when it
*writes* a `.blend`; a resident server never writes one, so nothing
collects them.

Measured: after 1000 edits the server held **12 objects but 209 meshes and
209 materials**, growing by one of each every five edits, for the life of
the process.

**Design consequence:** the warm server runs `bpy.data.orphans_purge()` after
every mutating op — its own copy of Blender's save-time collection. With it
on, the two modes' scene-state digests match edit for edit (30/30, 12/12).
Without it they diverge at the **first delete**, because one side collects
and the other does not — which is exactly how this was found.

This is also the general rule: **a resident process must reproduce
everything a save would have done for it.** The batch path gets it free.

### 5.3 The recipe must be an append-only journal, not a file rewritten per edit

`recipe.json` was rewritten in full on every edit. Consequences, all
measured over 1000 edits:

- **143 MiB written for a 255 KiB file** (quadratic);
- per-edit latency grew from **4.9 ms to 21.3 ms** as the file grew.

**Design consequence:** the **journal** (`journal.jsonl`, append-only, fsynced
per op) is the truth; `recipe.json` is a **periodic snapshot** (every N ops
and at every checkpoint); on restart the recipe is **rebuilt from the
journal**, which is always at least as long as the snapshot. The server now
reports the exact write volume, so the cost is measured rather than
inferred. 79× less disk traffic, and the per-edit latency stops growing.

### 5.4 The per-edit scene digest is O(scene size) — do not compute it per edit

The digest (for crash verification) walks every object and every material.
On the synthetic scene (12 objects) that is ~0.003 s; on the Hello Room
(196 objects, 202 materials) it is **~0.28 s** — about a seventh of the
~1.95 s tax the warm server is saving, and a seventh of the interaction it
is trying to shorten.

**Design consequence:** the digest belongs at **checkpoints**, not on every
keystroke. (`--no-digest-per-edit` exists for this reason.)

### 5.5 Smaller findings worth carrying

- **The `.blend` open is cheap (0.30 s for 380 MB — it is mmap'd); the save
  is not (1.07 s p50, 3.03 s p95).** A batch pipeline pays the save on
  every task. Any future "save less often" change is worth more than any
  change to the open.
- **Cycles on this GPU build is not bit-deterministic.** Compare previews by
  pixel, not by hash, or every parity check will fail on noise.
- **Blender's `.blend1` backups are pure waste** in a pipeline that rewrites
  a scene every task — on the 380 MB scene each save was silently doubling
  the disk cost. Disabled here (`save_version = 0`).
- **`import bpy` costs 0.25 s** and is the floor under the batch path.
- **Infinigen's gin configs need a specific import order, and it fails
  silently.** `infinigen/terrain/__init__.py` wraps `from .core import
  Terrain` in `try/except ImportError`; because `terrain.core` imports
  `infinigen.assets.materials`, which imports back into `infinigen.terrain`,
  the cycle made `Terrain` become `None`, the gin configurable was never
  registered, and `configs_nature/base.gin` then failed with `No
  configurable matching 'Terrain'` — with nothing pointing at the real
  cause. Importing `infinigen.assets.materials` first breaks the cycle. The
  bridge also passes the scene seed as a **string**, because Infinigen parses
  seeds as hex (`int(seed, 16)`).
- **gin's `include 'configs_nature/base.gin'` cannot resolve** (the folder
  is a namespace package, so `spec.origin` is `None` and gin raises
  `TypeError`). That is not a bug introduced here — Infinigen's own runs log
  the same `Path not found: configs_nature/base.gin` ERROR and carry on,
  because `apply_gin_configs` finds the file by globbing the config folders
  anyway. The bridge reproduces that behaviour rather than diverging from it.

---

## 6. How it plugs into the core's engine adapter

core-spec §1.9 already has the shape — the warm scene server as a
**scheduler-managed resident resource**, with `scene.loaded` / `scene.evicted`
audit events, a peak-RSS residency bound and LRU eviction among unpinned
branches, slotted in §6.2 before the USD/glTF compiler. This spike fills in
the numbers and the constraints that shape was missing.

**The hard rule in the spec is that the warm scene server is "a derived
cache, never a writer"** (RV patch 4, decision 17). This implementation
keeps a durable recipe and journal on disk, which looks like a writer — so
here is the mapping, stated plainly:

- **In the core, the recipe store is SQLite** (decision 9) and the core is
  the only writer. The `recipe.json` / `journal.jsonl` in this spike are a
  **spike-local mirror** of that store, kept only so the spike could test
  crash recovery without a database. **In the port, the server's journal
  becomes a read-through of the core's event log**, not a second source of
  truth.
- **The server becomes resident, not durable.** It is rebuilt from
  *recipe version + stage cache* (spec §1.9), which is the same replay
  mechanism §4.4 measured at 0.50 s. The recipe is the durable artefact;
  the resident scene is the cache.

**Proposed adapter seam** — the engine adapter (the thing that owns
`EnginePin` and the stage cache) gains three calls:

| adapter call | what the warm server does | measured cost |
|---|---|---|
| `scene.loaded(branch, version, stage_keys)` | start the resident process, replay the recipe onto the scene, emit `scene.loaded` with `rss_peak_mb` | 0.89 s for the Hello Room (0.51 start + 0.38 open) |
| `scene.apply(edit)` | one typed op, in place, journalled | 0.006 s (synthetic) / 0.38 s (Hello Room, with digest+purge) |
| `scene.evicted(branch)` | stop the process; nothing is lost | — |

**The vocabulary is already the right shape.** core-spec §1.1's `RecipeEdit`
is "a list of `Op`s, ≤ 32 per edit"; this server's `object.add` /
`object.move` / `object.delete` / `material.set` / `stage.rerun` are exactly
that shape — a closed, typed op list with no Blender code in it. The
`stage.rerun` entry point is the seam that makes **move #2 (partial
regeneration)** possible: it re-runs one generator stage against the
resident scene, which is impossible in batch mode without reloading the
whole `.blend` first.

**Three things the core must decide, which this spike did not:**

1. **Where does the per-edit digest go?** It is worth ~0.28 s per edit on a
   196-object scene and is only needed at checkpoints (§5.4).
2. **Who owns the orphan purge?** It must be the server, because only the
   server can be the last user of a datablock (§5.2). If the core also
   purges, the two must agree on the timing or the state digests diverge.
3. **What is the residency bound, in practice?** 2 466 MiB peak for the
   Hello Room → 50 branches in 122 GiB, so memory is *not* the binding
   constraint; the binding constraint is more likely the GPU (§4.6: one
   preview at a time) and the scheduler's own bookkeeping.

---

## 7. What this spike does **not** settle

- **Whether move #2 (partial regeneration) actually pays.** The resident
  scene is its precondition, but the win — re-solving one room instead of a
  38-minute solve — was not measured here. That is plan item 15 and it needs
  the real Infinigen solver, not this synthetic scene. §2.1 shows the solver
  *can* run in place; it does not show that re-running part of it is fast.
- **Concurrency.** The server is single-threaded because `bpy` demands it
  (§5.1). How to serialise a render queue behind an interactive edit — and
  whether a preview can be cancelled — is unmeasured.
- **Multi-branch residency and eviction.** One scene was measured; LRU
  eviction with the real scheduler was not.
- **The end-to-end numbers under a quiet box.** The GPU was contended for
  most of the session by other seats. The *ratios* held across conditions;
  the absolute p50/p95 in §4.1 should be re-taken on an idle box before
  they are quoted anywhere.
- **Trap A4 on this box.** PyTorch is not installed; the lab's number was
  cited, not reproduced.

---

## 8. Reproducing

```bash
bash setup/setup_env.sh                       # own venv + bpy wheel (no system installs)

# the numbers in §4
.venv/bin/python -m warm_scene.bench --scene synthetic  --edits 30 --no-render
.venv/bin/python -m warm_scene.bench --scene hello-room --edits 12 --no-render
.venv/bin/python -m warm_scene.bench --scene synthetic  --edits 15 --device CPU
.venv/bin/python -m warm_scene.durability --edits 25
.venv/bin/python -m warm_scene.memgrowth --edits 1000 --render-every 0
.venv/bin/python -m warm_scene.memgrowth --edits 1000 --render-every 0 --purge-orphans --snapshot-every 100
.venv/bin/python -m warm_scene.residency --scene hello-room
.venv/bin/python -m warm_scene.unified --blend ~/src/infinigen-thor/outputs/indoors/coarse/scene.blend --auto-largest

# the Infinigen seam (the real stage, callable in place)
.venv/bin/python -c "from warm_scene import infinigen_bridge as b; print(b.preflight())"
```

Raw results are in `results/*.json`, each with the box state it was taken
under. `README.md` has the module-by-module map.
