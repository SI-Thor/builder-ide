# EXP — the mesh repair stage: TRELLIS.2's props were never open, only split

**Date:** 2026-10-31, 07:20–10:40 local (Alaska Daylight Time)
**Verdict: THE MINI-NIGHT'S HEADLINE FINDING WAS A MEASUREMENT ARTEFACT — and
the repair that proves it is 3 lines of numpy, with no new dependency**

---

## 1. The idea

The mini-night's first finding was that TRELLIS.2's meshes are **never
watertight**: 155 k–234 k boundary edges on all nine props, 0 non-manifold
edges, and the critic's heaviest check (weight 3) scoring zero for every
candidate (docs/lab/mini-night.md §3). The follow-up it named was a
post-process pass — hole filling, a voxel re-mesh, an SDF re-mesh.

This seat's brief: build that repair stage, measure it against the same nine
meshes on **watertightness, triangle count, visual fidelity (silhouette IoU
against the original) and CPU time on the Thor**, pick one with evidence, and
make the critic's watertightness check mean something again.

## 2. The hypothesis

> One of the repair methods closes the boundaries, keeps the prop's outline,
> costs the CPU lane a few seconds, and can be shipped with a clean licence.

## 3. The setup

- Venv `/home/caseydigennaro/lm-wt/mesh-repair/.venv` (Python 3.12.3), the
  repo's own suite plus `.[dev,propgen,usd]`. **The repair itself needs
  nothing beyond the repo's existing numpy.**
- A separate scratch venv `/home/caseydt/mesh-bench/.venv` holds the
  candidates: `trimesh 5.2.0`, `scikit-image 0.26.0`, `manifold3d 3.5.4`,
  `pymeshfix 0.18.1`.
- Scripts: `docs/lab/mesh-repair-scripts/` — `probe_boundaries.py` (what the
  open meshes actually are), `render_mesh.py` (the silhouette and the shaded
  view), `bake_off.py` (the nine meshes × six methods).
- The nine meshes are the mini-night's own outputs, read from
  `~/lm-wt/trellis/out/genbatch/` — **not regenerated** (the brief says don't).
- Raw results: `artifacts/mesh-repair/bake_off.json` (gitignored, like every
  lab raw result).

### The box's state, beside the numbers

| | |
|---|---|
| Machine | NVIDIA Thor, aarch64, 14 cores, 122 GB unified |
| Kernel | 6.8.12-1021-tegra |
| Load average during this session | **13.3 → 26.2** (other seats) |
| The box's own note | a wall-clock without the load beside it is not comparable |

Every measurement below carries the load average it was taken at. The load
moved a lot during the session — the same repair on the same mesh cost 2.6 s
at load 13 and 18.2 s at load 19 — so **the CPU times are a range, not a
number**.

---

## 4. The numbers

### 4.1 What the open meshes actually are

The mini-night's numbers reproduce exactly:

| mesh | triangles | vertices | edges | boundary edges | non-manifold |
|---|---:|---:|---:|---:|---:|
| crate s1064508603 | 698,930 | 430,493 | 1,126,051 | 155,312 (13.8 %) | 0 |
| crate s455794046 | 699,784 | 459,214 | 1,153,480 | 207,608 (18.0 %) | 0 |
| crate s833331073 | 699,824 | 455,077 | 1,149,857 | 200,242 (17.4 %) | 0 |
| lantern s1427939119 | 698,756 | 525,601 | 1,211,534 | 326,800 (27.0 %) | 0 |
| lantern s424809304 | 698,234 | 474,588 | 1,164,557 | 234,412 (20.1 %) | 0 |
| lantern s913610340 | 698,184 | 458,702 | 1,149,721 | 204,890 (17.8 %) | 0 |
| anvil s1597230408 | 699,424 | 488,060 | 1,177,731 | 257,190 (21.8 %) | 0 |
| anvil s64961400 | 698,882 | 437,684 | 1,131,600 | 166,554 (14.7 %) | 0 |
| anvil s6984999 | 699,658 | 486,943 | 1,176,874 | 254,774 (21.6 %) | 0 |

The boundary is not a hole in the surface. It is **4,768–15,923 small loops**
(median 14–17 edges each), and those counts are the TRELLIS.2 spike's **UV
chart counts** (4,449 / 6,945 / 8,106 / 8,162 / 13,890 across runs of the same
recipe — docs/research/trellis-spike.md §5). The boundary edges are the seams
the unwrap opened.

### 4.2 The seam vertices are at the same place

The decisive measurement. For every duplicate group — the vertices the unwrap
split apart — the copies are at **bit-identical** positions:

| mesh | duplicate groups | max within-group deviation |
|---|---:|---:|
| crate s1064508603 | 74,213 | **0.0** (exactly, in 20,000 sampled groups) |
| lantern s424809304 | 108,857 | **0.0** |
| anvil s64961400 | 78,194 | **0.0** |

And the two copies of a seam vertex carry **different UVs** (2,000 of 2,000
sampled groups differ; the atlas is real, 0–1 in texture space). So the mesh
is a closed solid whose *index buffer* cannot see the closure: the unwrap
gives a vertex two copies, one per side of the seam, and the edge-counting
check reads the seam as a hole.

### 4.3 Welding closes every one of them

Merging the vertices that sit at the same place (tolerance 1e-6 of the
mesh's own diagonal) and **moving nothing**:

| mesh | welded | boundary after | triangles | area before → after | volume before → after |
|---|---:|---:|---:|---|---|
| crate s1064508603 | 81,044 | **0** | 698,930 | 6.391304 → 6.391304 | 0.911694 → 0.911694 |
| lantern s424809304 | 125,489 | **0** | 698,234 | 5.863045 → 5.863045 | 0.966917 → 0.966917 |
| anvil s64961400 | 88,241 | **0** | 698,882 | 5.796341 → 5.796341 | 0.952923 → 0.952923 |

The area and the volume are **unchanged to the last digit**: the weld is a
re-indexing, not a deformation. And the welded vertex count is 349,099 /
349,443 / 349,449 on three different props — the shape comes out of a fixed
voxel grid (the generator's [-0.5, 0.5]³ domain), so the number of dual
vertices barely depends on the object.

### 4.4 What the weld leaves behind

Welding leaves **0–4 edges used by four triangles**: the surface crosses
itself there. They are at the domain wall — the edges are 0.2–0.8 % of the
diagonal long, at z = −0.4988, x = +0.4981 and so on. Two kinds:

* a **crossing**: two sheets of the surface passing through each other;
* a **zero-volume flap**: a triangle that is in the mesh **twice**, once each
  way round (measured: the crate s833331073 has one such pair, whose two
  faces enclose no volume at all; four of the nine props carry 2–8 of them).

The repair undoes both without moving the prop: it collapses the flaps (they
cancel, so the volume does not move) and gives the pinched vertices a copy of
themselves (the copies sit at the same place, so the geometry does not move).
The edge-counting check then sees a closed, consistently wound solid.

**The result on all nine meshes:**

| | |
|---|---|
| boundary edges after the repair | **0** on all nine |
| non-manifold edges after the repair | **0** on all nine |
| consistently wound | yes, on all nine |
| volume | positive, and the same as before the repair to six decimals |
| silhouette IoU against the original | **1.000000** on all nine |
| cost | **2.6–18.2 s** per prop, at load 13–26 (3.4–4.6 s on a quieter box) |

### 4.5 The bake-off

All nine meshes, every method the brief names, the same four numbers. Raw
data: `artifacts/mesh-repair/bake_off.json`.

All nine meshes, every method the brief names, the same four numbers. The
IoU is against the mesh the method was given. The load average the
measurements were taken at is in the last column — the box ran at 18-26
throughout, so the CPU times are a range and not a number.

| method | watertight | triangles | silhouette IoU | CPU (s) | load |
|---|---:|---:|---|---:|---:|
| `none` (what TRELLIS.2 handed over) | **0/9** | 698,184-699,824 | 1.0000-1.0000 | 0.00 | 18-23 |
| **`weld` (the repair)** | **9/9** | 698,178-699,822 | **1.0000-1.0000** | 3.32-7.25 | 18-23 |
| `trimesh_fill_holes` | **0/9** | 845,626-996,190 | 0.8751-1.0000 | 1.64-11.19 | 20-24 |
| `manifold3d` | 9/9 | 698,176-699,820 | 0.9985-1.0000 | 1.69-3.31 | 20-25 |
| `voxel_128` (a voxel remesh) | 9/9 | 96,724-459,042 | 0.9495-0.9894 | 2.08-39.49 | 23-26 |
| `pymeshfix` (MeshFix) | **did not finish** | - | - | **>28 min for one prop** | 21-28 |

MeshFix is out on two counts, and the second one is measured. Its licence is
AGPL-3.0, which a BSD-3 repo cannot take. And it is far too slow for the
night's CPU lane: its constructor read the mesh and reported 4,253
boundaries in 3.5 s, but `repair()` **did not finish on a single 699 k-triangle
prop in 28 minutes** at load 21-28 - against a CPU lane that has about
100 s for the whole of one prop. It was stopped there. (It also reads the UV
seams as boundaries, so it would have been filling seams, not holes.)


What the table says:

* **hole filling is the wrong tool.** The boundaries are not holes, they are
  seams - two surfaces at the same place - so filling them adds 146 k to 300 k
  triangles and leaves **4,735 to 20,445 non-manifold edges**: the fans
  trimesh builds for a hole overlap the surface that is already there. It
  never once produced a watertight mesh.
* **manifold3d does the job, and it is the runner-up**: 9/9 watertight, an
  IoU of 0.9985-1.0000, and it is *faster* than the weld (1.7-3.3 s against
  3.3-7.3 s). It loses on two things. It is a dependency (Apache-2.0, a
  fine licence, but still one), and it reaches the answer through float32
  and a mesh library's own vertex merge - which throws away the vertex split
  that carries the UV atlas. The weld is exact: the geometry comes out
  bit-identical.
* **a voxel remesh is the expensive way to throw the prop away.** It is
  watertight, it costs 2-39 s, it rounds the silhouette (IoU 0.95-0.99), it
  drops 25-85 % of the triangles, and it has no UVs at all - the baked atlas
  is gone.

So the shipped repair is the weld: 9/9 watertight, an IoU of 1.0000, the
geometry bit-identical, the atlas untouched, and **no new dependency**.


### 4.6 The fidelity measure, and the mistake in it

The silhouette IoU is the number that says "the repair did not reshape the
prop", and it is easy to get wrong: **the first version measured its own
noise.** Sampling the surface and splatting it into a pixel grid leaves the
boundary pixels of the grid covered or uncovered depending on the sample
stream, and two meshes with *identical* geometry but a different triangle
order scored an IoU of **0.51**.

The fix is samples per **pixel**, not samples: 20 samples for every pixel of
the grid makes the outline stop flickering. At 128 × 128 with a million
samples, the same mesh against a shuffled copy of itself scores **0.9999**,
and the repair's own fidelity (which changes no geometry at all) scores
**1.000000**. Both are checked in the tests
(`tests/genbatch/test_repair.py::test_the_fidelity_measure_is_not_measuring_its_own_noise`).

---

## 5. The licences

Checked against PyPI and the wheels themselves, not from memory:

| library | licence | verdict |
|---|---|---|
| **the repair in this seat** (`core/genbatch/repair.py`) | **none — numpy only** | **shipped** |
| trimesh 5.2.0 | MIT | fine, but not needed |
| scikit-image 0.26.0 | BSD-3-Clause | fine, but not needed |
| manifold3d 3.5.4 | Apache-2.0 | fine, but not needed |
| **pymeshfix 0.18.1** | **AGPL-3.0** (the wheel ships the GPL-3.0 text; PyPI classifies it AGPL) | **rejected** |

**pymeshfix is rejected on licence, not on performance.** The repo is
BSD-3-Clause (or on its way there — the top README says "not yet chosen …
the recommendation BSD-3-Clause"), and an AGPL dependency would put a
copyleft obligation on everything that links it. It was measured anyway, in a
scratch venv, so the record says what it does — but it is not a dependency.

**The shipped repair adds no dependency at all**, which is the cleanest
licence answer there is.

---

## 6. The verdict

**Useful — and it overturns the mini-night's first finding.**

The mini-night said TRELLIS.2's meshes are never watertight. They are. What
they had was a **vertex buffer split at the UV seams**, and a watertightness
check that counted *index* edges could not tell a closed solid from an open
one. The repair stage makes the check mean something again: it welds the
seams, undoes the self-crossings the generator leaves at its domain wall, and
proves it changed nothing by measuring the prop's outline against the mesh it
was given (**IoU 1.000000**).

**The named candidates lose, and they lose on the numbers:**

* **hole filling** (trimesh) is the wrong tool: the boundaries are not holes,
  they are seams — two surfaces at the same place — so filling them adds
  146 k triangles and produces thousands of non-manifold edges;
* **MeshFix** (pymeshfix) is **not allowed** (AGPL) and would not fit the
  budget anyway: 28 minutes and counting on one 699 k-triangle prop;
* **manifold3d** is the runner-up and a close one: 9/9 watertight, an IoU of
  0.9985-1.0000, and *faster* than the weld. It loses on two things - it is
  a dependency, and it reaches the answer through float32 and a mesh
  library's own vertex merge, which throws away the vertex split that
  carries the atlas;
* a **voxel remesh** is the expensive way to throw the prop away: it costs
  tens of seconds, rounds the silhouette, and loses the texture atlas.

**What this changes:** the critic's heaviest check stops failing for a reason
that had nothing to do with the prop, and a night's props are judged on what
they are. The repair is part of the recipe, so the asset's provenance carries
it: the method, the parameters, the wall-clock, the counts and the fidelity.

**The asset's GLB is left as the generator wrote it.** The file's geometry was
never broken, so rewriting it would buy nothing and cost the atlas: a naive
weld keeps the correct UV for only **84.6 %** of the surface area, because the
two sides of a UV seam need different atlas coordinates and a welded vertex
has only one. What the repair supplies is the solid the pipeline measures and
judges, and the proof that it did not reshape the prop.

**The rest of the finding belongs to the generator, not the pipeline:**
TRELLIS.2's remesh stage leaves a surface that crosses itself at the edge of
its fixed [-0.5, 0.5]³ domain (3-4 edges on 699 k), and a zero-volume flap
where the shape stage doubled a triangle. A fix there would be worth more
than any repair downstream of it - but it is the generator's to make.

---

## 7. How to reproduce

```sh
# the diagnosis
.venv/bin/python docs/lab/mesh-repair-scripts/probe_boundaries.py

# the pictures
.venv/bin/python docs/lab/mesh-repair-scripts/render_mesh.py crate_s1064508603_00004_.glb

# the bake-off (needs the scratch venv with the candidates)
~/lm-wt/mesh-bench/.venv/bin/python docs/lab/mesh-repair-scripts/bake_off.py

# the tests
.venv/bin/python -m pytest tests/genbatch -q
```

The nine meshes come from the mini-night: `~/lm-wt/trellis/out/genbatch/`,
made on 2026-10-31 06:10–06:41 by the Prop-maker's batch.

## 8. Walls hit

* **The boundary edges are not a hole.** Two hours of the session went into
  hole filling before the boundary's *loop count* was matched against the
  spike's chart counts. Measuring the shape of the defect before trying to
  fix it is what turned the brief around.
* **The first silhouette IoU measured its own noise** (0.51 for identical
  geometry). Every fidelity number before the fix is meaningless; the fix
  and its check are in §4.6.
* **`np.unique(axis=0)` on 430 k rows** is the weld's cost (0.37 s), and
  `rng.multinomial` for the sampling is a trap: it allocates an array as
  big as the sample count times the triangle count (1.9 s for 500 k samples
  on a 12-triangle mesh). The cumulative-distribution search is 40× faster.
* **A triangle's edges are cyclic.** "Does this face use the edge a→b?" is
  not "is a before b in the face?" — the face (a, b, c) uses the edge b→c,
  and the face (c, b, a) uses the edge a→b. Getting that wrong makes the
  sheet pairing wrong, and the pairing is what the whole split rests on.
* **The duplicated triangle.** Two faces with the same three vertices and
  opposite winding are a zero-volume flap, and they are not two sheets that
  cross: they are one sheet that has been doubled. Collapsing them is
  volume-neutral; splitting them is not.
