# EXP — Open3D on the Thor: what it would add to the prop critic

**Date:** 2026-11-01
**Verdict: ADOPT FOR THREE THINGS, NOT FOR THE MEASUREMENT PATH.** Open3D
0.20 installs from a wheel on aarch64 (cp312, `manylinux_2_35`, glibc 2.39)
and its geometry kernels **agree with the critic's own to 4.4 × 10⁻¹⁵**
(hull volume, signed volume, area — 45 meshes, identical arrays), so there
is nothing to re-fit and nothing to fix. What it adds is what the critic
lacks: a **self-intersection check** (34 of the 38 SimReady reference
meshes self-intersect, 11 of them closed — invisible to the critic's edge
census, and inflating its signed volume up to 3.9 × on the worst one),
**quadric simplification** (7.41 M → 741 k triangles in 79 s), and a
**winding-free volume** by ray parity (answers on all 45 meshes where the
divergence theorem is nonsense on 25 of them). What it should not replace:
the measurements themselves (no accuracy gain; scipy's hull is slightly
faster), the watertight flag (a different word — §3.1), and the GLB reader
(correct on all 43 files, but 8 × slower than ours).

---

## 1. What was asked, and the set it was measured on

The brief: evaluate Open3D (MIT) against the critic's current geometry
checks — the occupancy `fill_ratio`, watertightness and multi-primitive
GLB handling of critic-shells, and the build123d-prop side — and report
adopt / adopt-for-X / skip with numbers.

The wheel question first, because it gates everything: **open3d 0.20.0 is
the only release with a cp312 aarch64 wheel** (`manylinux_2_35`; 0.17 and
0.18 stop at cp310/cp311 on aarch64), and the Thor's glibc 2.39 accepts
it. It installs with `uv venv` + `uv pip` (shared cache) and imports
against numpy 2.5.4 — the same versions the critic-shells run used. No
build, no lease: the whole experiment is CPU-only and peaked at
**1111 MB RSS** on the biggest mesh (1.33 M triangles), under the brief's
4 GB line.

The mesh set — 45 meshes, 7 410 024 triangles:

| group | meshes | what |
|---|---|---|
| reference | 38 | the SimReady sample the plausibility prior is fitted on (`core/genbatch/simready-reference.json`) |
| fresh | 5 | packages the prior never saw, picked by rule (`fetch_extra_samples.py`): a mug, a forklift, a golf ball, a hospital board, a storage shelf — 379 MB fetched, converted by the survey's own pxr loader |
| controls | 2 | a unit cube and the hollow mug, whose volumes are written down |

Every number below was produced by `compare.py` (both stacks fed
**identical vertex and index arrays**) and digested by `summarize.py`, both
committed in `docs/lab/open3d-critic/` with the full per-mesh rows in
`results/results.json`.

## 2. The setup

| | |
|---|---|
| Machine | NVIDIA Jetson AGX Thor, aarch64, 14 Neoverse cores, kernel `6.8.12-1021-tegra` |
| Box state | load 20.9–25.2 → 21.3–23.5 across the run; 109–111 GB available; other seats compiling throughout |
| Versions | open3d 0.20.0, numpy 2.5.4, scipy 1.18.1, pydantic 2.14.2, Python 3.12.3 |
| Occupancy grid | 64 cells along the longest axis (both stacks), the critic's own default |
| Simplification | quadric decimation to 10 % of each mesh's triangles |

## 3. The numbers

### 3.1 Watertightness: two different words, and a check we do not have

Open3D's `is_watertight` and the critic's edge census agree on **33 of 45**
meshes. Every one of the 12 disagreements is the same shape: the critic
says **closed** (every edge used exactly twice) and Open3D says **not a
valid solid boundary**, because Open3D's definition adds vertex-manifoldness
and **no self-intersections** — verified on a closed, self-intersecting
mesh before the sweep (`bodyPart_door_front_a01`: the formula reproduces
Open3D's own flag). The critic counts 20 closed; Open3D counts 8.

The disagreement is informative, not a bug on either side — and the
self-intersection part of it is the finding. **34 of the 38 reference
meshes self-intersect** (3 of the 5 fresh ones; 0 of the 2 controls),
11 of them closed: the critic calls them watertight, measures their signed
volume, and that volume **double-counts overlapped material**. The worst
case is the storage shelf: signed 0.2254 m³ against ray-parity 0.0576 m³
(3.9 ×) on the same mesh. The critic's `defect_rate` reads edges
(boundary, non-manifold, degenerate) and cannot see any of this.

Cost: `is_self_intersecting` is sub-second on prop-sized meshes — median
**0.16 s**, max 18.5 s under 200 k triangles (n = 34) — but has a heavy
tail: 801 s on the 1.33 M-triangle shelf, 596 s on the 1 M-triangle
forklift. It belongs behind a triangle cap on the critic's path.

### 3.2 Volumes: exact agreement where both answer, and a wider answer

Where both stacks give a number, they are the same number to floating-point
dust: signed volume rel. diff ≤ 1.7 × 10⁻¹⁵ (the 8 meshes Open3D will
answer on), surface area ≤ 2.9 × 10⁻¹³ (all 45), **convex-hull volume
≤ 4.4 × 10⁻¹⁵ (all 45)** — scipy's qhull and Open3D's hull agree, and
scipy is slightly faster (median 10.4 ms vs 14.7 ms).

The difference is coverage and robustness, not accuracy. The divergence
theorem needs closed and consistently wound; `get_volume` needs
Open3D-watertight (8 of 45 here); ray parity needs neither: on the 20
closed meshes it sits a median **1.1 %** from the signed volume (the grid
resolution), and it answers on **all 45** — including the 25 the critic's
signed volume is nonsense on (open meshes) — in a median **18 ms**. On
closed but self-intersecting meshes the two diverge by construction
(§3.1), and neither is authoritative there; parity is the one that does
not inflate.

### 3.3 Occupancy: the rasteriser is not the envelope, measured twice

Two Open3D-native readings that sound like "what the object occupies" are
not it, and both were measured before being ruled out (the dead ends are
kept, §5): ray parity gives the **enclosed solid** — the hollow mug reads
0.000128 m³ (its ceramic, analytic 0.000119), not the 0.000452 m³ cylinder
it occupies — and flood-fill reachability of the surface voxel grid gives
**sealed regions**, which a mug's open cup is not (the mug reads −53 %).

The honest Open3D route to the critic's semantic is the **visual hull on
its voxel grid** (the intersection of the three axis projections). It
behaves like our `visual` measure and inherits its failure: sparse frames
collapse (grid fill below 0.2 on **11 of 43** files — the same class as
the 11 of 38 in critic-shells §4.2). The two implementations are also not
interchangeable cell-for-cell (our grid is 64 cells per axis, Open3D's is
isotropic-cell and rounds axes up — its raw fill can exceed 100 % of the
bounding box, 131.9 % on the thin hospital board), and they disagree by a
median 25 %, up to 2 ×+ on thin geometry (the IV pole: 0.0009 vs 0.021 m³).
**The hull stays.** Nothing in Open3D measures the envelope better than
the convex hull the reference already chose.

### 3.4 The reader: correct on every multi-primitive file, and slower

On all **43 files** (38 reference + 5 fresh), `o3d.io.read_triangle_mesh`
returns **exactly the same triangle count** as the critic's whole-asset
reader `Glb.asset`, with a maximum bounding-box gap of **0.0 m** — every
primitive, every node transform, the 32-primitive forklift included.
The critic's reader is 8 × faster (0.53 s vs 4.12 s over the set) and
already exists; Open3D's is the cross-check, not the replacement.

### 3.5 Simplification: 79 seconds for a 10 % diet of everything

Quadric decimation to 10 % took **79 s total** for 7 410 024 → 741 233
triangles (exactly 10.0 %), median 0.22 s per mesh, worst 15.4 s (the
1.33 M-triangle shelf). On the meshes whose volume survives the cut, the
volume drifts a median 0.4 %, max 3.2 % (n = 5). The caveat: quadric
decimation **opened 14 of the 19 closed meshes** (controls included; only
5 stayed watertight) — simplified meshes are for display and LOD, not for
re-measuring watertightness or volume. The 12-triangle control cube
collapses to 0 triangles at a target of 1; that row is excluded from the
drift stats and noted rather than hidden.

### 3.6 Reproduction: the reference set is bit-exact

Re-measuring the 38 reference assets on this box reproduced every recorded
row exactly: occupied volume and signed volume rel. diff **0.0** (38 of
38), watertight flags 38 of 38. The reference set is as reproducible as
it claims to be, and the agreement columns above are not comparing against
stale numbers.

## 4. The decision

**Adopt Open3D 0.20 for three specific uses**, pinned `==0.20.0` (the only
cp312 aarch64 wheel):

1. **the self-intersection check** on the critic's path, under a triangle
   cap (~200 k): a median 0.16 s there (worst 18.5 s), and it is the only
   thing that sees what 34 of 38 reference meshes have — including 11 the
   critic calls watertight while their signed volume is inflated by
   overlap (up to 3.9 ×).
2. **quadric simplification** for mesh diet and LODs (79 s for the whole
   set to 10 %), never for re-measuring.
3. **ray-parity volume** as the fallback volume on meshes that are not
   closed-and-wound (median 18 ms, answers everywhere) — with the note
   that on closed self-intersecting meshes it is the conservative number,
   not the true one.

**Not** for: the hull, volumes, areas or features (agreement is exact and
scipy is faster); the watertight flag (a semantic change that would flip
12 of 45 rows and the recorded reference set — a decision, not a swap);
the GLB reader (correct but slower; ours exists). The wheel itself is the
one dependency risk: aarch64 cp312 exists only in 0.20.0, so the pin is
load-bearing.

## 5. The dead ends, measured

| tried | measured | why it failed |
|---|---|---|
| ray parity as the occupied volume | mug 0.000128 m³ vs the 0.000452 m³ it occupies | it is the enclosed solid (the ceramic), the old signed-volume trap in grid form |
| flood-fill reachability of the surface voxels as the envelope | mug −53 % (0.000214 vs 0.000452) | a mug's cup is open to the sky; sealed regions are not occupancy |
| Open3D's VoxelGrid fill against the bounding box | hospital board 131.9 % | the grid rounds each axis up to whole cells; fills must be read against the grid's own volume |
| `is_watertight` / `get_volume` as-is in the loop | 80–90 s each at 300 k triangles | both re-run the self-intersection test inside; computed once and the flag derived from the verified definition |

## 6. What this does not say

- **The build123d props were not re-measured as meshes.** The toy approved
  set is 200 feature rows, not meshes, and the CAD-bakeoff oracles measure
  against the CAD kernel's own numbers. The two analytic controls stand in
  for clean solids: the cube is exact on both stacks, and the mug's parity
  volume sits 7 % from the written-down ceramic at this grid.
- **The self-intersection tail is unbounded in triangle count** (801 s at
  1.33 M); the cap in the recommendation is from the 34-mesh measurement
  under 200 k, not a model of the scaling.
- **The fresh five are a sample of convenience by rule**, one per kind;
  they say the agreements held off the fitted set (43/43 reader, hull
  ≤ 4.4 × 10⁻¹⁵ including them), not that every SimReady asset behaves.
- **Watertightness of the fresh mug and golf ball (2 of 5) is not evidence
  the dataset is clean** — the other three self-intersect like the rest.
- The 379 MB of fresh payloads are on `~/lm-cold` and the five GLBs beside
  the survey's; **none of the meshes are in the repo**, only the numbers.
