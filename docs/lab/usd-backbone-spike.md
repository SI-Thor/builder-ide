# The USD backbone on the Thor — recipe → layered USD, byte-identical twice

**Idea.** A project is its recipe, and the recipe is the source of truth
(V §"the pieces"; CLAUDE.md). USD is what the recipe *compiles into*: an
assembly cache and an interchange format, one way, never back (res-cad §8;
core-spec v2 §7.11). Spike 3 (rev-tech §5, plan Week 2 item 8) is the
schema every later spike stamps into — res-cad §10 puts it first for a
reason: *nothing else lands without provenance and licence fields*.

**Hypothesis.** Three things, all of which the plan asks to be checked rather
than believed:

1. the same recipe emits **byte-identical** USD — across two runs and across
   two processes;
2. a build123d part becomes a **STEP master and a GLB interchange copy** that
   the USD references, and the GLB's bounding box matches the part;
3. the CAD lane costs **zero GPU memory**, so a night can build geometry on
   the CPU lane without disturbing the generative lane's residency
   (rev-tech §4: the pool is unified, so residency is the real constraint);
4. and the provenance — **prompt, model, weights revision, seed, licence** —
   round-trips through `customData`.

**Setup.** Branch `usd-backbone` of builder-ide, in this worktree. The
recipe store is on branch `core-recipe` and is **not merged**; the compiler
codes against a seam (`builder_usd.recipe_source.RecipeSource`) with two
sides: a stub, and an adapter over the store's own
`RecipeStore.get_document(version_id)`.

The recipe is a small Fjellvik harbour, in core-spec v2 §1.1's shape:
two materials, three CAD parts (`crate_lid`, `mooring_post`,
`hinge_bracket`), one placement with no geometry at all (the ground), with
semantics, physics and provenance on each.

The stage is **one layer per concern**:

| Layer | Says | Owns inside `customData` |
|---|---|---|
| `geometry.usda` | what is where: placement prims, transforms, **reference arcs** into each part's own USD layer | — |
| `materials.usda` | the surfaces (`UsdShade`, `UsdPreviewSurface`) and the bindings | — |
| `physics.usda` | rigid bodies: mass, collision approximation (`UsdPhysics` API schemas) | — |
| `semantics.usda` | what the things *are* (SimReady-lite class and tags) | — |
| `provenance.usda` | where everything came from | `provenance`, `asset` |
| `root.usda` | the composition root: the five layers, `World` as the default prim | — |

Each part also gets its own asset layer (`assets/<part>.usda`) holding the
tessellated mesh, and the geometry layer *references* it.

**Numbers.** NVIDIA Jetson AGX Thor Developer Kit, 14 Neoverse cores,
MemTotal 128 766 528 kB (≈122.8 GiB), Linux 6.8.12-1021-tegra aarch64,
glibc 2.39, Python 3.12.3, `nvidia-smi` → `NVIDIA Thor, 595.78, [N/A], 11.0`
(GPU memory reads `[N/A]` because the memory is unified with the CPU's —
rev-tech R3). Wheels: `usd-core 26.11` (Pixar, manylinux_2_28 aarch64),
`build123d 0.13.0`, `cadquery-ocp-novtk 8.0.1.1.0`, `py-lib3mf 2.5.0` — all
binary wheels from PyPI, no source builds. Measured 2026-10-30.

*The emission* — 16 files, 241 865 bytes, from one recipe:

| File | Bytes | sha256 (first 16) |
|---|---|---|
| `assets/crate_lid.glb` | 9 760 | `f164fd097bf3aed7` |
| `assets/crate_lid.step` | 43 408 | `9af9fef787abb9d2` |
| `assets/crate_lid.usda` | 5 074 | `21fdeba181fec7a1` |
| `assets/hinge_bracket.glb` | 23 936 | `df7cafee919b4da7` |
| `assets/hinge_bracket.step` | 19 143 | `973621b74256fcb9` |
| `assets/hinge_bracket.usda` | 23 983 | `a64adc87baef55d9` |
| `assets/mooring_post.glb` | 41 660 | `6bc565e6d661991f` |
| `assets/mooring_post.step` | 9 513 | `018444661e82f45c` |
| `assets/mooring_post.usda` | 46 785 | `6f1e78c4cef145f1` |
| `geometry.usda` | 1 195 | `a21f34fa6e4c979d` |
| `materials.usda` | 1 338 | `94723a02c5400509` |
| `physics.usda` | 914 | `eb8fba19b8b2921a` |
| `provenance.usda` | 8 597 | `f26ced444c7d41b6` |
| `root.usda` | 231 | `7382cdf188f06dcd` |
| `semantics.usda` | 664 | `c82c6b38253fdc06` |
| `manifest.json` | 5 664 | `a29abac822adca46` |

*Determinism.*

| Check | Result |
|---|---|
| two compiles, one process, same recipe | **identical bytes** (16/16 files) |
| two compiles, two processes, `PYTHONHASHSEED=0` and `=12345` | **identical bytes** |
| re-emit into a fresh directory and diff every file | **0 differences** |
| timestamps anywhere in the emitted text | **none** (the STEP header is pinned to `1970-01-01T00:00:00`) |
| prim order | sorted under every parent |

*Cost.* The whole stage — three CAD parts, five layers, the manifest —
compiles in **198 ms** (median of five warm runs; the first run, cold, is
1.96 s because OCCT is paged in). Per part: build 8–20 ms, tessellate
14–27 ms, export (STEP + GLB) 8–14 ms. The whole process, interpreter and
`build123d`/`OCP` import included, peaks at **477 MiB RSS** and 2.6 s wall.

*GPU.* The compile process maps **no** CUDA or NVIDIA library and opens **no**
`/dev/nvidia*` handle; `torch` is not in the installed dependency tree and
`build123d` requires nothing of the sort. The check is structural, not a
number, because this box cannot produce a GPU-memory number at all
(`nvidia-smi` says `[N/A]`).

*The GLB.* Each GLB opens, carries UVs (`TEXCOORD_0`, forced on by
build123d's writer), and its bounding box matches the part: the tessellated
mesh sits *inside* the part's true bounds, never outside, and the extents
agree to within the 0.5 mm tessellation deflection. The STEP master is the
same part in millimetres (OCCT's STEP length unit): the `crate_lid` measures
600 × 400 × 60 mm there and 0.6 × 0.4 × 0.06 m in the GLB and the USD.

*Provenance.* The record written into `customData` comes back out of the
composed stage key for key and value for value: `prompt`, `model`, `seed`,
`version`, `licence` (SPDX, dependency terms, `commercial_ok`), the weights
repo and revision, the library versions, the recipe hash and the engine pin.
Each asset's files are pinned by path, sha256 and byte count.

**What the measurements taught us.** Six things about USD that the design
had to be changed to fit — all of them measured on this box, not assumed:

1. **`customData` merges; it does not replace.** Two layers that both author
   `customData` on a prim produce a *merged* dictionary, with the stronger
   opinion winning **per key** — the dictionary is never replaced wholesale.
   The design therefore gives each concern its **own key** (`provenance`,
   `asset`, `part`) instead of relying on layer order to keep them apart.
2. **A typed prim carries `userDocBrief`** in its `customData` — USD's
   schema documentation, not ours. Any reader of the stage has to ignore it.
3. **The first sublayer is the strongest.** `[geometry, materials, …]` means
   the geometry layer leads; a `Scope` in a later layer does not override an
   `Xform` in the first.
4. **A direct opinion beats a referenced one.** The part's own record, which
   arrives through the geometry layer's reference arc, never overrides the
   placement's record in the provenance layer.
5. **USD cannot compose a GLB.** Pointing a reference arc at `part.glb`
   gives, at every stage open: `Could not open asset @…/part.glb@ for
   reference … Cannot determine file format`. The reference survives as an
   inert arc and the stage still opens — but no geometry arrives. So the
   backbone does the honest thing: the part's geometry is composed through a
   **USD asset layer** (`assets/<part>.usda`, a real `UsdGeom.Mesh`
   referenced by the placement), and the GLB is **pinned by path and sha256**
   in the placement's `customData`, which is what the ProArt client and
   Blender actually open.
6. **USD prints doubles with the shortest round-trip representation.** An
   unquantised `0.1 + 0.2` lands in the file as `0.30000000000000004`. All
   floats are therefore quantised to six decimals *before* they are
   authored, which is what makes the text both stable and reviewable.

And two about the CAD kernel:

7. **build123d's `export_step` takes a `timestamp`.** OCCT writes the wall
   clock into the STEP header; the parameter pins it to the epoch, the same
   convention `SOURCE_DATE_EPOCH` uses. Without it, every re-emission is a
   diff.
8. **Three conventions, one part.** CAD is Z-up and the part is authored in
   metres; the STEP is written in millimetres (OCCT's unit) with build123d
   scaling the shape into it; the GLB and the USD mesh are Y-up in metres.
   The test compares the GLB's bounds, the mesh's bounds and the part's
   bounds in the same frame, and it caught the axis swap the first time.

**How to reproduce.**

```bash
cd ~/lm-wt/usd-backbone            # this worktree
.venv/bin/python -m pytest tests/usd -q          # 78 passed, 1 skipped

# compile the demo recipe into a layered stage
PYTHONPATH=core/usd/src .venv/bin/python -m builder_usd compile --demo --out /tmp/stage

# re-emit and compare, byte for byte
PYTHONPATH=core/usd/src .venv/bin/python -m builder_usd verify --demo --out /tmp/stage
#   IDENTICAL: /tmp/stage re-emits byte for byte

# open the composed stage
PYTHONPATH=core/usd/src .venv/bin/python -m builder_usd read --out /tmp/stage

# the zero-GPU claim, measured
PYTHONPATH=core/usd/src .venv/bin/python -m builder_usd probe
#   gpu free:      True
```

The determinism test itself runs the CLI twice in **separate processes** with
different `PYTHONHASHSEED` values and compares every emitted file by hash;
the provenance test opens the composed stage and compares the record that
came back with the record that went in.

**Verdict: useful — the spike passes.** Against rev-tech spike 3's
pass/fail: `usd-core` imports on aarch64 ✓; a build123d part exports STEP
and GLB into a layered stage with one layer per concern ✓; provenance
round-trips in `customData` ✓; emission is deterministic, sorted, timestamp-
free ✓; build123d uses zero GPU memory ✓. USD has not become the source of
truth — the recipe still is, and the stage is a compiled output with a
manifest that names the recipe hash it came from.

**What this spike does not do (deviations, on the record).**

- **The GLB is referenced by pin, not by arc** — USD cannot compose one
  (finding 5). The geometry the stage composes is the USD asset layer; the
  GLB is the interchange copy, pinned by sha256.
- **SimReady's semantic keys live in custom attributes here**
  (`semantic:type`, `semantic:tags`), not in `customData` as SimReady
  writes them — because `customData` merges (finding 1) and two writers on
  one key would quietly decide the record.
- **The part's own record and the placement's record are separate keys**
  (`part` and `provenance`) rather than one merged blob.
- **No LOD, no impostors, no `since_version` delta** — that is plan Week 3
  item 16 and the ghost/LOD path (core-spec v2 §6.2 item 4); this spike is
  the backbone it will sit on.
- **The recipe store is stubbed behind a seam**, not merged: the adapter
  calls `RecipeStore.get_document(version_id)` and is tested against a fake
  store with the same interface. When `core-recipe` merges, the adapter
  becomes the only thing that changes.
- **The stage's structure is the recipe's**, not the engine's: the geometry
  layer holds placements and references, and it is the Infinigen port's job
  later to fill the room. Nothing here depends on that being true.
