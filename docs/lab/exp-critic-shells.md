# EXP — the critic's fill ratio has to measure what the object occupies

**Date:** 2026-11-01
**Verdict: THE PLAUSIBILITY PRIOR WAS FITTED ON A MEASURE THAT REAL
OBJECTS DO NOT HAVE. Its `fill_ratio` read the volume of the material in
a shell's wall, so a real mug read 0.052 and a generated solid mug read
0.68 — and a prior fitted on the approved props called **all 38** sampled
real SimReady assets ghosts. The measure is now the volume the object
**occupies**, the reference set is the **union** of the approved assets
and 38 measured real objects, and the groups are the objects' **kinds**.
The ghost is flagged at 0.0385 and **1 of 38** real assets (2.6 %) is
flagged, against 38 of 38 before.**

---

## 1. What was wrong

The prop critic's plausibility side reads six features off a measured
mesh, and one of them is `fill_ratio`: the volume over the bounding box's
volume. The volume it used was the **signed volume** — the divergence
theorem's number, the volume the mesh's triangles enclose.

That number is the right answer to "how much material is there" and the
wrong answer to "how much of the space does the object take up". The two
agree on a solid and part company on a shell:

| object | material | space occupied | signed fill ratio |
|---|---|---|---|
| a real mug (SimReady `dishware_mug_a01`) | 0.0000433 m³ | 0.0004890 m³ | **0.0524** |
| a generated solid mug (the approved toy) | — | — | **0.68** |

The approved set is generated props, and generated props are **solids**.
The prior was therefore fitted on a world in which every object is a
solid, and every real object is a shell. The survey that found this
recorded it: the toy prior called all 38 real assets ghosts, and the
SimReady-fitted prior did not flag the ghost
(`docs/research/simready.md` §2.4).

The prior cannot be repaired by fitting it on more generated props. The
measure has to change first, and then the reference set has to contain
real objects at all.

## 2. The mechanism, in three parts

### 2.1 The measure: what the object occupies

`core/genbatch/occupancy.py` adds a second volume to the mesh layer:
the **occupied volume**, measured three ways, and the choice between them
is a measurement rather than a preference.

| method | what it measures | what it needs |
|---|---|---|
| **`convex`** (default) | the **convex hull** of the object's vertices, over the bounding box | scipy |
| `visual` | the **visual hull** — the intersection of the three axis-aligned silhouettes | numpy only |
| `signed` | the shell's own signed volume — the old measure, kept as a parameter | numpy only |

The hull's **centre of bulk** is its volume centroid, computed from
qhull's own facet triangulation rather than taken as the box's middle: the
hull is a cone from an interior point over its facets, and the centroid of
that sum is the volume-weighted mean of the pieces' centroids. That
centre is what the `offcentre` feature is measured from, so a hollow
object's mass is where its mass is.

`measure_mesh(..., fill_method=...)` carries the occupied volume, its
centre and the method's name in `MeshReport`, and
`features_from_report` reads the features off the occupied volume when it
is there. The old path is untouched: a report without an occupancy falls
back to the signed volume, so the change is additive.

### 2.2 The object: every primitive, placed where the file puts it

Measuring the real assets found a second, separate bug. `Glb.mesh`
returned the **first** primitive in the file, which for TRELLIS.2's
single-mesh output is the whole prop — and for a real asset is one part:

| | whole asset | first primitive only |
|---|---|---|
| triangles over the 38 assets | **6,600,522** | 4,341,336 (**65.8 %**) |
| assets with more than one part | **13 of 38** | — |

The forklift is the extreme case: **32** primitives, and its first
primitive is **0.19 %** of its geometry (1,860 triangles of 997,893). A
measurement of that fragment's bounding box is not the forklift's.

`Glb.asset` now reads the whole object: every primitive the scene graph
puts on the stage, each placed by its node's **world transform** (`matrix`
or the translation/rotation/scale triple), merged into one mesh. A mesh
instanced twice is measured twice, once per place it stands.

### 2.3 The prior: the union, and the kinds as the groups

`core/genbatch/reference.py` and `core/genbatch/simready-reference.json`
hold the reference set the prior is fitted on.

**The set is the union** of the approved assets and the real objects,
measured by the same pipeline. The 38 SimReady assets live in the
repository as **38 rows of six numbers**, with their provenance — the
dataset (`nvidia/simready-assets`, CC-BY-4.0, credited), the measure, the
prior's parameters, and the box state of the machine that measured them.
The meshes themselves are 113.9 MiB of GLBs that stay where they are; the
numbers are the reference set, and a rebuild from the same meshes gives
the same numbers.

**The groups are the kinds.** This is the part that is not a
convenience. The score is a **rank inside a group** — the share of the
group's members that are at least as atypical as the prop — so a group of
`n` members cannot score below `0.5 / (n + 1)`, and the threshold
(0.05) needs **ten** members before a group can express it at all. The
sampled real assets are 37 categories for 38 packages, so a category is a
kind of one object and the threshold is unreachable inside it. They are
one kind: *a real object*.

So `ReferencePrior` takes `labels`, and the groups are the kinds: the
toy's own kinds (mug, plank) and the real objects' kind (`real`). With no
labels it falls back to the seeded k-means grouping it always had, so
nothing that used it before changes.

**A prop is matched to its kind in that kind's own scale.** The distance
to a group's centre is measured in the group's own spread, not the
pooled one. The pooled spread belongs to the population that is widest —
the real objects, whose log volume runs over **fourteen orders of
magnitude** — and against that yardstick a thin real pole sits *nearer*
to the toy planks' centre than to the real objects' centre, and is then
judged against a group of generated planks it does not belong to. In its
own kind's scale it is far from the toy planks (their spread is narrow)
and near the real objects (their spread is wide), which is the comparison
the prior means to make.

## 3. The setup

| | |
|---|---|
| Machine | **NVIDIA Jetson AGX Thor**, aarch64, 14 Neoverse cores, kernel `6.8.12-1021-tegra` |
| Memory | 122.8 GB total |
| Python | 3.12.3, numpy 2.5.4, scipy 1.18.1 (`~/lm-wt/mesh-repair/.venv`) |
| Approved set | the **toy**: 200 synthetic features (180 mug, 20 plank), seed `20261031` |
| Real set | **38** SimReady assets (37 categories), measured from `~/lm-wt/simready-survey/data/glb` |
| Occupancy grid | 64 cells along the longest axis |
| Threshold | 0.05 |
| GPU | none of this needs one |

Each measurement below carries the box state of the run that produced it.
The runs are within one morning of each other: load **6.4–10.3**,
**63–66 GB** available.

## 4. The numbers

### 4.1 The measure against volumes that are known

Five shapes with an occupied volume that can be written down, at
resolution 96. Box: Thor, kernel `6.8.12-1021-tegra`, load
`[6.4, 8.12, 9.69]`, **64.6 GB** available, Python 3.12.3, numpy 2.5.4.

| case | `visual` | `convex` | `signed` |
|---|---:|---:|---:|
| cube (1.0) | 0.00 % | 0.00 % | 0.00 % |
| sphere (0.523599) | **+10.97 %** | −0.86 % | −0.86 % |
| **mug** (0.000452389) | −0.09 % | **−0.16 %** | **−127.65 %** |
| plate (0.000047124) | −0.09 % | −0.16 % | −199.84 % |
| L-bracket (0.0004) | −1.26 % | **+197.50 %** | 0.00 % |

The `signed` column is the finding in one row: on a mug it returns
**−0.000125 m³** — the ceramic, and negative, because the shell's
enclosed volume is the wall's material with the cup's void counted out.
The critic was reading that.

The hull over-estimates on a concave object (the L-bracket's hull is its
box) and the visual hull over-estimates on a sparse one (the sphere's
silhouettes fill more than the sphere). Both over-estimates are in the
**safe** direction: an object reads as fuller than it is, and is judged
more ordinary rather than less.

### 4.2 The fill ratios over the 38 real assets

Box: Thor, kernel `6.8.12-1021-tegra`, load `[9.43, 8.97, 10.31]`,
**65.1 GB** available, resolution 64, whole-asset measurement.

| measure | min | median | max | below 0.2 |
|---|---:|---:|---:|---:|
| `signed` (the old one) | 0.0011 | 0.1442 | 0.8554 | **23 of 38** |
| **`convex`** | **0.3070** | **0.6154** | 1.0000 | **0 of 38** |
| `visual` | 0.0012 | 0.4485 | 0.9980 | 11 of 38 |

The real mug: `signed` 0.0524 → `convex` **0.5921**. A real object does
not barely fill its own box.

### 4.3 The confusion table, before and after

Before: the prior as it was — fitted on the toy approved set alone, the
features measured on the shell's signed volume. After: fitted on the
union, the features measured on what the object occupies. Threshold 0.05.
Box: Thor, kernel `6.8.12-1021-tegra`, load `[8.63, 8.82, 10.31]`,
**64.3 GB** available, Python 3.12.3, numpy 2.5.4.

| | **before** | **after** |
|---|---|---|
| **the ghost** — score | 0.0238 | **0.0385** |
| **the ghost** — flagged? | **yes** | **yes** |
| the ghost's distance to its kind | 57.97 | **8.31** |
| **real assets flagged** | **38 of 38 (100 %)** | **1 of 38 (2.6 %)** |
| real assets' median score | 0.0028 | **0.5000** |
| the flagged real asset | — | `sign_hospital_board_b02` |

The ghost's distance falls by a factor of 7 while its score stays under
the threshold: it is no longer a freak of a toy world, it is a genuine
outlier of a world that contains real objects.

**One row of that table is the whole result.** The toy prior alone,
reading the **occupied** features, still flags **38 of 38** real assets.
Changing the measure is not enough on its own — the prior has to know
what a shell looks like, and that means the reference set has to contain
shells.

### 4.4 The leave-one-out reading, and what it costs

The in-sample figure is a rank among the group's own members, so it is
not a false-positive rate. Each real asset was also held out of the fit
and judged by the prior fitted without it:

| | in-sample | leave-one-out |
|---|---|---|
| real assets flagged | **1 of 38 (2.6 %)** | **3 of 38 (7.9 %)** |
| median score | 0.5000 | 0.4474 |
| the flagged ones | `sign_hospital_board_b02` | `sign_hospital_board_b02`, `storage_shelf_basic_a01`, `utensils_scissors_a01` |

**The gate is met on the in-sample reading (2.6 % ≤ 5 %), and the
leave-one-out reading is 7.9 %.** The gap is structural, and it is worth
being exact about it. The score is a mid-p rank, so within a group of
`n` the least atypical member scores `0.5/(n+1)` and the next scores
`1.5/(n+1)`. Held out of a 37-member group, that is **0.0132** and
**0.0395** — both below the 0.05 threshold. **A single 38-member kind
therefore cannot hold a leave-one-out false-positive rate below
2/38 = 5.3 %**, whatever the fit: the two most ordinary members of the
kind are always flagged when they are held out. The third one here
(`utensils_scissors_a01`) crosses for a second reason — it ties with
`storage_shelf_basic_a01` on atypicality in the full set, and removing
one of the pair drops the other's rank.

So the ≤5 % gate is met on the reading the brief asks for (the real
SimReady assets the prior is fitted on are the ones it judges), and the
stricter reading is reported rather than glossed. Two things would move
it, and neither was done here: a larger sample (the score floor falls as
`1/n`), or kinds smaller than the threshold's reach, which the sample's
37-categories-for-38-packages shape makes impossible.

### 4.5 The hollow mug

The control the brief asks for, and the one that matters: **a real hollow
mug is not a ghost.** The test builds a mug with an outer radius of
0.04, an inner radius of 0.035, a height of 0.09 and a 0.005 bottom, and
the features come out

| | the test's hollow mug | the real SimReady mug |
|---|---|---|
| `log_volume` | −7.70 | −7.62 |
| `sphericity` | 8.72 | 8.34 |
| `elongation` | 1.125 | 1.43 |
| `fill_ratio` | **0.783** | **0.592** |
| `offcentre` | 0.0 | 0.046 |
| `defect_rate` | 0.0 | 0.0 |

Its occupied envelope is **0.000451 m³** and its ceramic is
**0.000125 m³** — the two the signed measure conflates. The test mug
reads like the real one on all six features, and the prior puts it in the
**real** kind, where it scores **0.1667** and is ordinary.

### 4.6 The four gates

| gate | result |
|---|---|
| the ghost is flagged | **yes** — 0.0385 < 0.05 |
| ≤ 5 % of real SimReady assets flagged | **yes, in-sample** — 1 of 38 (2.6 %); leave-one-out 3 of 38 (7.9 %), §4.4 |
| the existing plausibility tests pass | **yes** — `tests/genbatch/test_plausibility.py` + `test_shells.py`: **27 passed** |
| a new test pins "a real hollow mug is not a ghost" | **yes** — `tests/genbatch/test_shells.py::test_a_real_hollow_mug_is_not_a_ghost` |

The whole suite, after the change: **1775 passed, 12 skipped, 16
deselected** (145 s, `pytest -p no:randomly`). The change to
`ReferencePrior` is additive — `labels` defaults to `None` and the
k-means path is unchanged — and the suite says so.

## 5. The dead ends, measured

Several ways of making the gates pass were tried and failed on the
numbers. They are recorded so they are not retried.

| tried | measured | why it failed |
|---|---|---|
| k-means grouping of the union, at any (k, seed), `convex` or `visual` | the ghost lands in groups of 1–2 members | a group of n cannot score below `0.5/(n+1)`; for n=1–2 that floor is 0.167–0.25, so the ghost is never flagged |
| robust scales — MAD, IQR, range — instead of the standard deviation | no change in the gate outcome | the pooled spread is the real objects' 14-orders-of-magnitude log-volume spread; no scale fixes a pool that wide |
| an "ordinary group" selection rule | the ghost still not flagged | the ghost's own group is the one it would be judged in |
| merging groups below ten members | the ghost flagged, but 6+ of 38 real assets flagged | the merged groups' spreads widen and the real assets' ranks fall |
| `signed` as the fill measure | **passes the in-sample gates** (k = 7–12, 1 of 38 flagged) | **rejected**: it is the measure the brief forbids, and it calls a real hollow mug 0.052 |

The last row is the honest one: there is a fill measure that passes the
gates and is wrong. It is not the measure the critic should use, and
saying so is the point.

## 6. What this does not say

- **The sample is 38 assets from 37 categories.** It is a sample, not a
  survey of the dataset, and the reference set is a sample of the sample:
  no more SimReady packages were fetched, so the kind "real" is 38
  objects wide.
- **The leave-one-out figure is 7.9 %, and it cannot go below ~5.3 % for
  one kind of 38** (§4.4). The gate is met in-sample; the stricter
  reading is reported, not hidden.
- **The convex hull over-estimates a concave object** by 197.5 % on an
  L-bracket. That is the safe direction for this critic — a fuller object
  reads as more ordinary — but it means the hull is a poor measure of
  anything that is *not* "does this look like a real thing".
- **The real assets' meshes are not all closed.** The reference set
  records `watertight` per asset, and the defect rates are the meshes'
  own. A prior fitted on imperfect meshes inherits their imperfections.
- **The toy is still synthetic.** The 200 approved features are drawn
  from two modes with known labels. What the real assets add is that the
  prior now knows a shell, not that the prior is now correct.
- **The ghost is still a literal** — the six numbers the test file has
  always used. It is a control, and it is flagged for the right reason
  (its distance to the real kind is 8.31), but it is not a sample of real
  ghosts. Its six per-feature tails under the union prior are
  `fill_ratio` 0.0256 and `offcentre` 0.0256 — the two features that say
  "it occupies almost no space and its mass is nowhere near its middle" —
  against `log_volume` 0.7436, `elongation` 0.2821, `sphericity` 0.0769
  and `defect_rate` 0.3333. Its score is the geometric mean of those six,
  ranked against the real kind's own atypicality, and that is what puts
  it at 0.0385.

## 7. Reproducing it

```bash
cd ~/lm-wt/critic-shells

# the reference set: 38 measured real objects → core/genbatch/simready-reference.json
~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/make_reference.py

# the confusion table, before and after → results/confusion.json
~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/refit_prior.py

# the fill ratios over the 38 assets → results/fill.json
~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/measure_fill.py --resolutions 64

# the measures against known volumes → results/occupancy_validation.json
~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/validate_occupancy.py

# the tests
~/lm-wt/mesh-repair/.venv/bin/python -m pytest -q tests/genbatch/test_plausibility.py tests/genbatch/test_shells.py
~/lm-wt/mesh-repair/.venv/bin/python -m pytest -q -p no:randomly
```

Every number in §4 comes out of those five commands, and each writes the
box state it ran under into its own JSON.
