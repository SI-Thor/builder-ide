# What NVIDIA SimReady assets teach our objects

A survey of `nvidia/simready-assets` (Hugging Face dataset, CC-BY-4.0,
77.29 GiB stored, 183,394 files, 2,677 packages) read on the Jetson AGX
Thor. The question behind it: *simulation-ready data helps us understand
objects more broadly* — so what does a SimReady asset actually carry, and
which of it can the prop critic and the world use?

Everything below was measured. Where a number came from a sample, the
sample is named; where it came from the whole dataset, it says so.

**The box, beside the numbers.** NVIDIA Jetson AGX Thor, aarch64,
122.8 GB unified memory, 14 Neoverse cores, NVMe with 136 GB free at
2026-11-01T10:48Z. 69.9 GB MemAvailable, five `thor-admit` leases running
(model servers and an Infinigen render). The survey ran over about two
hours on that shared box; where the load matters to a number — the glTF
conversion timings — the measurement is repeated and the spread is given
(§4.3).

---

## 1. What is in the dataset

### 1.1 The file index

`huggingface_hub.list_repo_tree` on the dataset root, walked in 40 s:

| | |
|---|---|
| tree entries | 228,417 (183,394 files, 45,023 folders) |
| packages (top-level folders) | 2,677 |
| category prefixes | 196 |
| bytes reported by the index | 456.0 GiB |
| bytes actually stored | 77.29 GiB (`usedStorage`) |
| last commit | `4763fbfaa4f8e97658e68b57d01b4c86659e08b5`, 2026-10-29T19:45:32Z |

The index sums to 456 GiB but the repository holds 77.29 GiB because the
index counts every file while the storage counts deduplicated blobs. The
gap is almost all PNG:

| extension | files | bytes in the index |
|---|---|---|
| `.png` | 117,916 | 424.42 GiB |
| `.usd` | 5,602 | 21.38 GiB |
| `.usda` | 34,465 | 9.70 GiB |
| `.json` | 13,559 | 0.05 GiB |
| `.mdl` | 9,094 | 0.18 GiB |
| `.txt` | 2,678 | 0.05 GiB |

Most of the PNG bytes are thumbnails — `.thumbs/256x256/` and
`.thumbs/512x512/` copies of the textures, repeated per package. They carry
no schema. The USD, the JSON and the MDL together are 31.3 GiB of the
index.

The README is four lines: a licence, a pointer to
`nvidia/simready-central-library`, and an invitation to contribute. There
is no schema document in the dataset. The schema has to be read off the
files.

### 1.2 The package layout

Every package is the same shape. From `kitchenware_fork_i01`, the smallest
complete one:

```
<asset>/.metadata/LICENSE.txt
<asset>/.metadata/com.nvidia.simready.conformance.Package@1.0.0.json
<asset>/.metadata/com.nvidia.simready.conformance.Package-Candidate@1.0.0.json
<asset>/.metadata/com.nvidia.simready.packaging.bom.json
<asset>/.metadata/com.nvidia.simready.root_usds.json
<asset>/com.nvidia.simready.packaging.json
<asset>/simready_usd/sm_<asset>_01.usd          <- the root stage
<asset>/simready_usd/payloads/base.usda         <- semantics, per-part mass
<asset>/simready_usd/payloads/geometries.usd    <- the tessellated meshes
<asset>/simready_usd/payloads/instances.usda    <- the neutral mesh instances
<asset>/simready_usd/payloads/instances_{physx,newton,mujoco}.usda
<asset>/simready_usd/payloads/materials.usda    <- the surfaces
<asset>/simready_usd/payloads/Physics/physics.usda
<asset>/simready_usd/payloads/{MuJoCo,Newton,PhysX}/{enabled,disabled}.usda
<asset>/simready_usd/Textures/t_*.png           <- alb, nor, orm
<asset>/simready_usd/source_assets/*.mdl, *.png <- the MDL library, duplicated
<asset>/simready_usd/runnables/physics/{mujoco,newton,physx}.usd
```

2,669 of the 2,679 packages carry the full payload set; 2,624 carry the MDL
material library. The root stage is `sm_<asset>_01.usd` for most packages
and `sm_<asset>_01.usda` for some — the package's own
`root_usds.json` says which, so a reader must ask the metadata rather than
guess the extension.

### 1.3 The schema, as a table

Measured over the 38-package sample (`data/sample_report.json`).

| layer | what it carries | notes |
|---|---|---|
| **units** | `metersPerUnit = 1`, `upAxis = "Z"` | 38/38 sampled packages; no per-asset scale |
| **package metadata** | `asset_type` (`"prop"`), `profile` (`"Robotics-Prop"`), `profile_version`, `uuid` | in the root layer's `customLayerData.SimReady_Metadata`; 38/38 sampled are `asset_type = prop` |
| **conformance** | `FET000_CORE`, `FET003_BASE_PHYSX`, `FET005_BASE_NEUTRAL`, `FET006_BASE_MDL`, … each with `passed` and `failing requirements` | per validation date, in `customLayerData` and in `.metadata/com.nvidia.simready.conformance.Package@1.0.0.json` |
| **semantics — object** | `semantics:labels:wikidata_class` (`["crate"]`), `semantic:wikidata_class:params:semanticData` (`"crate"`), and the Wikidata id (`"Q605384"`) | a real taxonomy, not a free-text tag |
| **semantics — material** | `["steel"]`, `["plastic"]`, `["rubber"]`, `["aluminum"]`, `["fabric"]`, `["cardboard"]`, `["paper"]`, `["clear_glass"]`, `["nylon"]`, `["brass"]`, `["wood"]`, `["frosted_glass"]` | 38/38 sampled packages carry at least one material label |
| **rigid body** | `physics:mass`, `physics:centerOfMass`, `physics:diagonalInertia`, `physics:principalAxes`, `physics:density`, `physics:collisionEnabled` | standard `UsdPhysics` attributes |
| **rigid body (duplicate)** | `pxr:usd:physics_mass`, `pxr:usd:physics_centerofmass`, `pxr:usd:physics_inertia` | the same body, on the wrapping Xform, in a custom namespace |
| **collider** | `PhysicsCollisionAPI` / `PhysicsColliderAPI`; `physics:approximation` = `sdf` (PhysX variant) or `convexDecomposition` (neutral) | 38/38 sampled packages carry a collider |
| **friction / restitution** | `physics:staticFriction`, `physics:dynamicFriction`, `physics:restitution` | e.g. the crate: 0.4 / 0.4 / 0.4 |
| **solver variants** | three variant sets on `/RootNode`: `MuJoCo`, `Newton`, `PhysX`, each `Enabled`/`Disabled` | 36/38 sampled ship with `PhysX = Enabled`; `dishware_mug_a01` and `warehouse_conveyorBelt_a33` ship `PhysX = Disabled` and fall back to the neutral collider |
| **articulation** | `/RootNode/Joints/joint_<part>_joint_00`: `PhysicsRevoluteJoint`, `PhysicsPrismaticJoint`, `PhysicsFixedJoint` | with `physics:axis`, `physics:lowerLimit`/`upperLimit`, `physics:localPos0/1`, `physics:localRot0/1`, `physics:jointEnabled` |
| **manipulation affordance** | `/RootNode/Grasp/grasp_identifier/grasp_identifier_curve` (a `BasisCurves` prim) | 22/38 sampled packages carry a grasp curve |
| **materials** | `UsdShade.Material` + a `Shader` (Principled BSDF), `UsdUVTexture` → PNG, and the OmniPBR MDL library (`OmniPBR.mdl`, `OmniPBRBase.mdl`, `OmniPBR_ClearCoat.mdl`) | 38/38 sampled packages have at least one material |
| **LOD** | none | **0 of 38** sampled packages carry a `LOD` prim |
| **meshes** | `geometries.usd`: `/Geometries/<name>` → an `Xform` wrapping one `Mesh` | instanced; see §1.4 |
| **bill of materials** | `.metadata/com.nvidia.simready.packaging.bom.json`: every file with its size and SHA-256 | plus a `package_hash` and a `content_hash` in `com.nvidia.simready.packaging.json` |

### 1.4 Two things a reader has to know, or it sees nothing

**The geometry is instanced.** The geometry prims carry `instanceable =
true`, so their contents live in USD prototypes under `/__Prototype_N` and
do not appear in `stage.Traverse()`. The meshes are reached with
`Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())`. A reader that
uses the default traversal reports **0 meshes, 0 triangles** for an asset
that has 60,744 triangles. The materials are instanced the same way.

**The mass is stated twice, on two prims.** The mesh prim carries the
standard `physics:mass`; the Xform that wraps it carries a copy of the
same number as `pxr:usd:physics_mass`. Adding both doubles every asset's
mass — the crate reads 5.67 kg instead of 2.84 kg. One body, one mass.

**The physics variant selects the collider.** `instances.usda` carries a
generic collider; `instances_physx.usda` replaces it with
`PhysicsMeshCollisionAPI` + `PhysxSDFMeshCollisionAPI` +
`physics:approximation = "sdf"` and adds `physxCollision:contactOffset`
(0.002 m) and `restOffset` (0.001 m). The neutral variant gives
`convexDecomposition`. The same asset, read under a different variant
selection, is a different collider.

---

## 2. Priors for the prop critic

**Deliverable:** `simready_priors.json` — 37 categories, each with the
measured mass range, size range, density, material labels and the critic's
own six features.

### 2.1 What the priors can carry

Mass, size, material and category are **stated in the USD**, and they are
in real units: the crate is 2.837 kg and 0.605 × 0.405 × 0.253 m; the
golf ball is 0.1416 kg and 42.6 mm across; the forklift is 1,028.9 kg over
32 bodies. These are priors over real objects, and the values check out
against each other — the crate's authored density is 950 kg/m³ (plastic)
and the mug's shell is a real shell.

The size range across the sample runs from a 13.2 mm fuse to a 5.4 m
structural beam; the mass range from 0.0072 kg to 6,021.7 kg.

The **mass** prior does not have to rest on the sample. `payloads/base.usda`
for every package in the dataset is 45.5 MiB in 2,669 files, and it carries
the per-part mass, so the mass of every asset in a category is known. The
mass distribution per category, measured over all 2,669 assets (every one
of them carries a mass; 196 of 196 categories have one):

| category | assets | min (kg) | median (kg) | p90 (kg) | max (kg) |
|---|---|---|---|---|---|
| food | 538 | 0.002 | 0.165 | 0.824 | 23.40 |
| kitchenware | 179 | 0.009 | 1.226 | 5.510 | 18.45 |
| box | 154 | 0.083 | 0.597 | 3.945 | 92.04 |
| handTool | 97 | 0.009 | 0.416 | 1.348 | 5.48 |
| consumable | 75 | 0.001 | 0.220 | 2.554 | 38.61 |
| paint | 68 | 0.044 | 0.273 | 0.346 | 1.43 |
| bodyPart | 67 | 0.126 | 8.271 | 185.395 | 348.02 |
| pallet | 64 | 6.477 | 41.645 | 66.257 | 116.19 |
| warehouse | 61 | 0.154 | 451.002 | 1,299.327 | 400,081.4 |
| equipment | 59 | 0.102 | 34.714 | 331.008 | 5,483.2 |
| serviceTool | 56 | 0.162 | 5.386 | 249.475 | 1,200.5 |
| engineComponent | 52 | 0.004 | 2.048 | 25.933 | 58.00 |
| container | 44 | 0.138 | 3.299 | 21.841 | 61.36 |
| instrument | 38 | 0.057 | 0.365 | 0.989 | 1.16 |
| stationery | 36 | 0.006 | 0.050 | 0.051 | 0.16 |

This is the brief's "a lantern is 0.3–2 kg, 15–40 cm" with a measured
population behind it. `simready_priors.json` carries these under
`dataset_mass_kg` next to the sample's own measurement.

Two rows say what the taxonomy does not: **`warehouse` runs from 0.15 kg
to 400 tonnes**, because the category holds both a small conveyor and a
building, and **`bodyPart` runs from 0.13 kg to 348 kg** for the same
reason. A category is a name, not a scale, and a prior built on a category
has to carry the spread or it will be wrong at both ends.

### 2.2 The material table, measured over the whole dataset

The physics layer carries a `PhysicsMaterialAPI` block per material, with
its density and its friction. Across all 2,669 packages that is **57
materials** with real values:

| material | assets | density (kg/m³) median | μ static | μ dynamic | restitution |
|---|---|---|---|---|---|
| metal | 1,502 | 7,850 | 0.30 | 0.30 | 0.10 |
| plastic | 1,393 | 950 | 0.40 | 0.40 | 0.40 |
| rubber | 491 | 1,200 | 0.80 | 0.80 | 0.80 |
| paper | 341 | 900 | 0.50 | 0.45 | 0.12 |
| glass | 310 | 2,500 | 0.40 | 0.40 | 0.05 |
| organic | 287 | 500 | 0.45 | 0.40 | 0.40 |
| cardboard | 264 | 689 | 0.70 | 0.70 | 0.40 |
| wood | 204 | 700 | 0.50 | 0.50 | 0.40 |
| nylon | 159 | 900 | 0.50 | 0.45 | 0.12 |
| fabric | 113 | 1,000 | 0.50 | 0.50 | 0.30 |
| ceramic | 58 | 2,600 | 0.35 | 0.30 | 0.05 |

These are the values a physics world should use, and they are the
`material.wood.weathering` word's business: builder-ide's material word
carries `wear` and `tone`, and the physics layer carries `wood` at 700
kg/m³ with μ 0.5 and restitution 0.4 — the numbers a worn wooden surface
would have to stay near.

The table has a hygiene problem a lookup has to handle: the material names
carry spelling drift (`platic`, `plasic` and `pastic` for plastic,
`cemaric` for ceramic, `metalBass` and `metalPaint` for a metal base and a
painted metal), and one `aluminum` material carries the **plastic**
density of 950 kg/m³. A closed list has to be built from the names with
normalisation and the outliers checked by hand.

### 2.3 The measurement against the critic's test set

`tests/genbatch/test_plausibility.py` has ground truth: a toy with two
kinds of real object (a **mug**, 180 of 200 approved assets, and a
**plank**, 20 of 200) and a **ghost** — a valid solid whose shape is the
wrong shape for anything, which the test file calls the control a
consistency-only critic cannot pass. The ghost's features are
`log_volume = -2.5, sphericity = 30, elongation = 12, fill_ratio = 0.02,
offcentre = 0.4, defect_rate = 0`.

The critic's `ReferencePrior` was refitted on the SimReady sample — the
same six features, measured by the critic's own pipeline (`read_glb` →
`measure_mesh` → `features_from_report`) over the converted GLBs.

| prior fitted on | ghost score | flagged (< 0.05)? | toy mug median | toy plank median |
|---|---|---|---|---|
| the critic's own toy approved set | **0.0238** | **yes** | 0.470 | 0.357 |
| SimReady sample, 2 clusters | 0.171 | **no** | 0.145 | 0.303 |
| SimReady sample, 3 clusters | 0.149 | **no** | 0.122 | 0.284 |

**The SimReady priors do not flag the critic's known-bad prop.** The
ghost's distance from the nearest group is 1.39 standardised units, not
the > 3.0 the test requires, and its score does not separate it from the
toy mug (0.149 against 0.122).

The reason is visible per feature. The ghost's position inside the
SimReady distribution, as a percentile:

| feature | log_volume | sphericity | elongation | fill_ratio | offcentre | defect_rate |
|---|---|---|---|---|---|---|
| ghost | 0.910 | 0.577 | 0.885 | 0.141 | 0.936 | 0.205 |
| toy mug (median) | 0.987 | 0.090 | 0.115 | 0.859 | 0.526 | 0.500 |

The ghost is an **ordinary point** in the space real objects occupy. Its
`sphericity = 30` is unremarkable against a real range of 2.7 to 410 among
the watertight assets (and to 1.18 × 10⁹ across all of them, the top of
that range being the open-mesh cabinet); its `elongation = 12` against a
real range of 1.0 to 83; its `fill_ratio = 0.02` against a real range of
0.0036 to 2.26. The toy mug's `fill_ratio = 0.68`, by contrast, is *more*
extreme than the real median (0.143).

### 2.4 The other direction, which is the finding that matters

The critic's own prior, fitted on its own toy approved set, was run over
the 38 real SimReady assets:

| | |
|---|---|
| assets scored | 38 |
| median score | 0.0028 |
| best (highest) score | 0.0238 |
| **share scored below 0.05** | **100 %** |
| share scored below 0.20 | 100 % |

**Every real object in the sample is a ghost to the critic's prior**, on
the critic's own threshold. The toy reference set is two Gaussian blobs;
the real assets are not near them.

The mechanism is in the feature definition. `fill_ratio` is "the volume
over its bounding box — a solid fills a lot of it, a shell almost none",
and the volume it divides by is the **signed volume of a closed mesh**.
Real objects are hollow: a mug's wall encloses 43.3 cm³, not the 826 cm³
of its box, so its fill ratio is 0.052; the crate's is 0.024. The critic's
toy mug is a **solid** with fill ratio 0.68. The gap between "generated
solid blob" and "real hollow object" is wider than the gap between "real
object" and "ghost", so a prior fitted on generated meshes calls real
objects ghosts before it calls ghosts ghosts.

Two further facts make the gap concrete:

* **The meshes are not closed.** 21 of the 38 sampled packages are not
  watertight (17 are, per part). The critic's features are computed from
  the signed volume of a closed mesh, so on an open mesh the volume is
  meaningless: the cabinet measures −0.0052 m³ and a sphericity of
  1.18 × 10⁹.
* **The repair stage does not close them.** `core/genbatch/repair.py` welds
  coincident vertices and splits non-manifold edges — it is built for the
  seams a generator leaves. Run on the four sampled assets with the
  largest defects, it reports `boundary_edges_closed = 0` on all four and
  leaves them open. Closing a shell is a different job from welding a
  seam, and nothing in the repo does it.

### 2.5 What this means for the critic

The priors are usable, but not as the critic's feature vector:

1. **Mass, size, material and category are usable now.** They come from
   the USD, they are in real units, and they do not depend on the
   tessellation. They are the right basis for a *category-and-scale*
   check — "a crate of this size weighs 2.8 kg, and this one claims
   0.01 kg".
2. **The shape features are not usable as they stand.** Either the
   SimReady meshes have to be closed first (new work; the repo's repair
   does not do it), or the critic's volume-based features have to become
   shell-aware — a convex or watertight-bound volume rather than the
   signed volume of an open surface.
3. **The critic's own approved set is the thing to fix first.** Whatever
   reference set the critic ends up using, it has to contain real hollow
   objects, or the critic will reject every real object that reaches it.

---

## 3. Vocabulary

Three vocabularies, measured against each other
(`data/vocabulary_mapping.json`).

| vocabulary | size | shape |
|---|---|---|
| SimReady | 2,677 assets, 196 categories | category = the first underscore-delimited token of the folder name (`handTool`, `vehicleSupport`, `IV`) |
| builder-ide | **3 words** | `props.harbor.crates`, `props.harbor.racks`, `material.wood.weathering` |
| builder-ide namespaces | 14 | `prop`, `props`, `material`, `materials`, `terrain`, `weather`, `motion`, `light`, `structure`, `structures`, `character`, `characters`, `constraint`, `constraints` |
| builder-ide tile kinds | 3 | `behaviour`, `build_step`, `recipe_edit` |
| builder-ide SimReady-lite semantics | an **open string** | `semantic_type` accepts any string; the USD compiler's demo uses `crate`, `post`, `bracket`, `ground` |
| Infinigen | 147 asset factories in 38 groups | `shelves` 13, `creatures` 12, `tableware` 9, `leaves` 8, `organizer` 7, … |

### 3.1 Overlap

Matching on whole-word names (the suffix `Factory`/`Base` dropped, so
"factory" is not a token of every factory):

| | |
|---|---|
| SimReady categories with an Infinigen factory | **41 of 196** |
| SimReady assets covered by one | **1,269 of 2,677 (47.4 %)** |

This is a **name-level** overlap, so it bounds the real overlap from
below; a few matches are loose (`structure` → `WallArtFactory` on the
word "wall", `syringe` → `PineNeedleFactory` on the word "needle").

### 3.2 The gap, and it has a shape

The uncovered half is not random. It is the **industrial** end:

| SimReady category | assets | an Infinigen factory? |
|---|---|---|
| `food` | 538 | yes — `FoodBagFactory`, `FoodBoxFactory` |
| `box` | 154 | yes — `FoodBoxFactory` |
| `handTool` | 97 | **no** |
| `consumable` | 77 | **no** |
| `paint` | 68 | yes — `CanFactory` |
| `bodyPart` | 67 | yes — `BaseDoorFactory` |
| `pallet` | 64 | yes — `PalletFactory` |
| `serviceTool` | 57 | **no** |
| `engineComponent` | 52 | **no** |
| `instrument` | 38 | **no** |
| `stationery` | 36 | **no** |
| `cleaning` | 29 | **no** |
| `misc` | 28 | **no** |
| `sign` | 25 | **no** |
| `testingTool` | 25 | **no** |
| `vehicleSupport` | 22 | **no** |
| `powerTool` | 20 | **no** |

Infinigen builds **rooms** — a kitchen, a living room, a bathroom — and
its factories are the objects those rooms contain. SimReady is a
**warehouse and a workshop**: tools, engine parts, test equipment,
vehicles. The two sets meet in the domestic and decorative middle
(`box`, `pallet`, `container`, `cabinet`, `dishware`, `chair`, `table`,
`lamp`) and separate everywhere else. 155 categories have no Infinigen
counterpart.

### 3.3 What builder-ide can take

* **The semantic class.** builder-ide's `semantic_type` is an open string
  with no closed list. SimReady carries a **populated** taxonomy — over
  the whole dataset, **1,246 distinct semantic labels**: Wikidata classes
  (`Q605384` = crate, `Q32489` = knife, `Q41577` = forklift) beside human
  labels ("crate", "knife", "forklift", "cardboard box", "waste container",
  "belt conveyor") and material labels ("steel", "plastic", "glass"). That
  is a ready-made closed vocabulary for the slot, and it is the one place
  where SimReady is immediately useful to builder-ide without any new code.
* **"prop" does not mean what builder-ide means by prop.** All 2,669
  assets declare `asset_type = "prop"` and `profile = "Robotics-Prop"` —
  the forklift, the conveyor belt, the structural beam and the 400-tonne
  warehouse are all typed as props. In SimReady "prop" means *a simulated
  object*, where in builder-ide it means *a thing in a room*. The
  vocabulary needs a different word for the SimReady sense.
* **The categories as prop words.** 196 categories over 2,677 assets map
  onto the `props.<place>.<thing>` shape, and the largest ones —
  `food` (538), `box` (154), `handTool` (97) — are the crowded everyday
  vocabulary a `props.harbor.crates` word already belongs to. The
  industrial categories have no builder-ide word at all; the tile library
  would need words for them before the cloud could write a tile that
  places a torque wrench.
* **The tile vocabulary is not a content vocabulary.** A tile is a script
  in the closed vocabulary: `{word, path, op ∈ set/add/remove, params}`.
  SimReady supplies what a tile's `params` and `semantic_type` may talk
  about; it does not supply tile kinds, families or preconditions.
* **Collision models.** builder-ide's compiler accepts `none`,
  `boundingCube`, `boundingSphere`, `convexHull`, `mesh`. SimReady ships
  `sdf` and `convexDecomposition` — neither is in that list, so the
  closed set needs a decision about `sdf` (PhysX's SDF mesh collider is
  not expressible in builder-ide's five).

---

## 4. Loaders

### 4.1 Can the Thor read USD?

Yes, and it already does. `usd-core` 26.11 publishes a
`manylinux_2_27_aarch64.manylinux_2_28_aarch64` wheel for cp311/cp312/cp313
(26.4 MiB), and **eleven** project venvs on the Thor already have it
installed: `usd-backbone`, `stage-cache`, `engine-adapter`,
`integrate-core`, `m1-real`, `daytime-world`, `critic-select`,
`critic-delegate`, `mesh-repair`, `render-rung`, `propmaker-batch`. All
eleven also carry numpy, so the loader runs in any of them unchanged.

The version matters: **26.3, 26.5 and 26.8 publish no aarch64 wheel at
all** (only macOS, Windows and x86_64). 26.11 is the first recent release
where a Thor install is a `pip install` away. `Usd.GetVersion()` returns
`(0, 26, 11)` on the Thor.

### 4.2 The loader

`scripts/simready_loader.py` — pxr and numpy, no glTF library, matching
builder-ide's own rule from `core/genbatch/glb.py` ("There is no glTF
library on the Thor and the Thor does not need one"). Three commands:

```bash
python3 scripts/simready_loader.py probe   ~/lm-cold/simready-sample/dishware_mug_a01
python3 scripts/simready_loader.py convert ~/lm-cold/simready-sample/dishware_mug_a01 out.glb
python3 scripts/simready_loader.py batch   ~/lm-cold/simready-sample outdir/
```

It reads the package's own `root_usds.json` to find the root stage,
composes the stage, traverses with instance proxies, and reports the
schema of §1.3 as JSON.

### 4.3 Converting to glTF, and how long it takes

38 packages, 6,600,522 triangles, on the Thor. The converter was run
**three times** and the per-asset median is reported, because the Thor is
shared: a single run is a timing of the machine as well as of the
converter. The three run totals were 20.08 s, 23.74 s and 22.95 s — an
18 % spread from the load alone.

| | |
|---|---|
| converted | **38 / 38** |
| total, median of three runs | **21.56 s** |
| per asset, median | **0.103 s** |
| fastest | 0.0149 s (`sign_hospital_board_b02`, 3,920 triangles) |
| slowest | 4.67 s (`vehicle_forklift_blue_c01`, 997,893 triangles; 3.07–5.72 s over the three runs) |
| output | 113.9 MiB of GLB (18.3 MiB for the largest) |

The cost tracks the triangle count, not the file size: the biggest package
on disk (`IV_pole_a01`, 394 MiB) converts in 0.68 s, because the bulk of
those bytes is texture.

**The GLBs were checked with builder-ide's own reader**, not with this
survey's (`core.genbatch.glb.read_glb`), so the writer is not agreeing with
itself:

| check | result |
|---|---|
| opened by `core.genbatch.glb.read_glb` | 38 / 38 |
| NaN in positions | 0 |
| reader warnings | 0 |
| bounding box against the USD, first primitive | max error **5.96 × 10⁻⁸ m** |
| bounding box against the USD, all primitives | max error **1.19 × 10⁻⁷ m** |
| triangle count against the USD | exact |

That check earned its keep. The first writer put numpy's default float64
bytes under a glTF `float32` accessor, so every reader decoded the
positions into garbage — and builder-ide's reader raised
`invalid value encountered in cast` on 13 of the 38 files. The defect was
invisible to a writer-side check, because the writer and the writer agreed.

### 4.4 What the loader does not do

* No textures in the GLB. The PBR scalars are carried; the PNGs are not.
  A viewer that needs the albedo has to be handed the texture files too.
* No material binding per mesh: the GLB carries the material list and the
  mesh list, and the binding between them is not written.
* The `sdf` collider and the `convexDecomposition` collider are not
  translated into builder-ide's five collision models.

---

## 5. Physics for motion

### 5.1 What is articulated

Of the 38 sampled packages, **12 carry joints** (78 joints in total) and
**22 carry a grasp curve**:

| asset | revolute | prismatic | fixed | total |
|---|---|---|---|---|
| `vehicle_forklift_blue_c01` | 20 | 10 | 1 | 31 |
| `IV_pole_a01` | 14 | 1 | 0 | 15 |
| `serviceTool_brake_lathe_a01` | 5 | 2 | 2 | 9 |
| `testingTool_multimeter_clamp_b01` | 1 | 4 | 1 | 6 |
| `cabinet_file_a03` | 2 | 0 | 2 | 4 |
| `equipment_bench_vise_a01` | 2 | 2 | 0 | 4 |
| `fixture_cabinet_a01` | 2 | 0 | 0 | 2 |
| `stationery_pen_plastic_a01` | 0 | 0 | 2 | 2 |
| `utensils_scissors_a01` | 2 | 0 | 0 | 2 |
| `decor_candle_l01` | 0 | 0 | 1 | 1 |
| `drum_fiber_a02` | 0 | 0 | 1 | 1 |
| `powerTool_cutting_tool_a01` | 1 | 0 | 0 | 1 |

The joints are in `/RootNode/Joints/joint_<part>_joint_00` and they are
fully specified:

```
joint_door_01_joint_00        PhysicsRevoluteJoint
    physics:axis = "Z"        physics:lowerLimit = -90.0   physics:upperLimit = 0.0
    physics:jointEnabled = True    physics:collisionEnabled = False
    physics:localPos0/1, physics:localRot0/1
```

So the answers to the brief's question are concrete:

* **Doors.** `cabinet_file_a03` has two revolute joints on its two doors,
  each limited to 90° in opposite directions, with the glass panels held by
  fixed joints. A cabinet whose doors open is exactly the target the brief
  asks for.
* **Drawers: there are none.** Searching all 2,677 package names for
  "drawer" returns **zero** assets. The dataset has cabinets with doors,
  a `desk_a01`, three shelves and one `shelve_steel_heavyDuty_a06`, and no
  drawer. The nearest articulated sliding mechanism in the sample is
  `equipment_bench_vise_a01`: a prismatic joint on a sliding jaw, limited
  to −0.045…+0.055 m along X. If the world needs drawers, they have to be
  built, not sampled.
* **Handles.** `utensils_scissors_a01`: two revolute joints about Z,
  limited to ±32 rad. The scissors open and close.
* **Vehicles.** The forklift has 31 joints across its mast, steering and
  wheels.

### 5.2 Are they usable as targets

**For a physics simulation: yes, directly.** The joints are standard
`UsdPhysics` schema objects with axis, limits, frames and enable flags —
`UsdStage` alone is enough to instantiate them, and the three solver
variants (MuJoCo, Newton, PhysX) are already authored as variant sets, so
the same asset can be handed to a MuJoCo-based agent world without being
re-authored.

**For an agent or a motion script: partly.** Two things are missing at
the dataset's level, and one is missing at ours:

1. **No joint naming discipline.** The joint prims are
   `joint_<part>_joint_00`, where `<part>` is the mesh part name. That is
   usable — `joint_door_01_joint_00` says which door — but it is not a
   taxonomy, and an agent cannot ask for "the drawer" and be sure of
   getting it.
2. **The grasp curves are not a handle set.** 22 of 38 packages carry a
   `grasp_identifier_curve`, a `BasisCurves` prim under
   `/RootNode/Grasp/grasp_identifier`. It marks where a hand goes, but it
   does not name a handle, and it is a curve rather than a transform.
3. **The collision approximation is not one of ours.** `sdf` and
   `convexDecomposition` are not in builder-ide's five collision models.
   A door that swings on an SDF collider needs a collider the world can
   actually build.

The `world-stream` and `thor-motion` side is the open question this survey
cannot settle: `thor-world` is a separate repository
([SI-Thor/thor-world](https://github.com/SI-Thor/thor-world)) and is not
checked out on this box, so the glTF path was verified against builder-ide's
own GLB reader rather than against the viewer that will consume it. The
conversion produces standard glTF 2.0 with a POSITION accessor, normals and
UVs, which is what a viewer needs; whether the viewer's expectations about
materials and scale are met is a measurement on the thor-world side.

---

## 6. What would be next

In the order the measurements put them:

1. **Close the shells.** The critic's features need closed meshes and 21 of
   38 sampled packages are open. `core/genbatch/repair.py` welds seams and
   does not close holes; closing them is new work and it gates everything
   else about using SimReady as a reference set.
2. **Rebuild the critic's approved set from real objects.** The current
   prior calls 100 % of the sampled real assets ghosts. That is the single
   most consequential number in this survey.
3. **Make `semantic_type` a closed list** and seed it from the Wikidata
   classes the assets already carry. No new code, and it closes a slot that
   is currently open.
4. **Decide about `sdf`.** It is the collider the PhysX variant ships, and
   it is not one of builder-ide's five.
5. **Widen the sample where it matters.** 37 categories is enough to see
   the shape of the vocabulary and the physics, and not enough to put a
   distribution on any one category. The physics payload for the whole
   dataset is 24 MiB in 2,669 files and gives every asset's mass; the
   geometries for the same assets are the expensive part.

---

## Appendix: what was fetched, and what it cost

| what | size | requests |
|---|---|---|
| the file index (`list_repo_tree`) | 228,417 entries, metadata only | 40 s of API |
| the README | 545 bytes | 1 |
| the sample: 38 packages, 37 categories | **3.00 GiB** (3.1 GiB on disk with block rounding) | 1,372 files |
| the physics payload for every package | 24.1 MiB | 2,669 files |
| the base payload for every package | 45.5 MiB | 2,669 files |
| the package metadata for every package | ~0.1 GiB | 16,047 files |

The brief's budget was 3 GiB for the sample and 5 GiB before asking the
director. The sample is at 3.00 GiB and the whole download is under 3.2
GiB, so nothing was fetched that the brief did not already allow, and
nothing was fetched from the 456 GiB the file index sums to.

The two dataset-wide sweeps (69.6 MiB in 5,338 files) are *metadata* in the
brief's sense — the physics and base layers are small text files describing
mass, materials and semantics, not the mesh payloads — and they are what
turns the category priors from one observation per category into a measured
distribution. The expensive part of the dataset, the geometry and the
textures, was only taken for the 38 sampled packages.

**Fetching the tree is the expensive part.** Hugging Face answers an
anonymous client with two rate limits — 5,000 resolver requests per five
minutes and 1,000 API requests per five minutes — and `snapshot_download`
spends an API call per file on a token. Downloading straight from the
`resolve` endpoint, driven by the index already on disk, is one GET per
file and finished the 3.00 GiB sample in 117 s with no failures.

**Credit.** NVIDIA SimReady Assets, `nvidia/simready-assets` on Hugging
Face, CC-BY-4.0. Used here by reading and sampling.

**On the box's rules.** The heavy-step rule is `thor-admit run` for work
over 8 GB. The heaviest step here — composing a 1.33 M-triangle USD stage
and converting it — peaked at **558 MB** of resident memory
(`/usr/bin/time -v` on `storage_shelf_basic_a01`), and the download is
network-bound with no large allocation, so no lease was taken. The box's
memory floor was never at risk: `MemAvailable` stayed between 69.9 GB and
78.0 GB throughout, against a 25.0 GB floor, with five other leases
running. A `thor-admit run` invocation was attempted for the sample
download and refused by the desktop permission gate; the work was
light enough that it did not need one.

## What it means for the critic (director, 2026-11-01)
The plausibility prior's `fill_ratio` feature (signed volume over bounding box) is wrong for real assets: they are hollow shells, so all 38 real SimReady assets score as ghosts. Fix (queued): measure fill on a watertight or voxel-filled hull (manifold3d, already in mesh-repair), or drop fill_ratio for shells, then refit the prior on the union of the toy set and SimReady and re-run `tests/genbatch/test_plausibility.py`. Pass: the ghost is flagged and at most 5% of real assets are. Seed 166.

Note for physag-lite: SimReady has **no drawers** (0 of 2,677 names). Its drawer-unit priors must come from the cabinet/door classes, or be marked estimated.
