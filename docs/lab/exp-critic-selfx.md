# EXP — critic-selfx: the three Open3D uses, inside the critic

**Date:** 2026-11-01
**Verdict: ADOPTED, AS THE REPORT RECOMMENDED AND NO FURTHER.** The critic
measures self-intersection (under a 200k-triangle cap), falls back to
ray-parity volume wherever the signed volume cannot be trusted, and offers
quadric decimation as a diet stage that is **off by default**. The
measurement path, the GLB reader and the watertight flag are untouched;
the reference re-run (38 meshes, load ~25, 147 s, peak RSS 710 MB) says
what changed and what did not. Follow-up to
[exp-open3d-critic.md](exp-open3d-critic.md); the numbers below are from
`critic-selfx-scripts/results/rerun.json`, reproduced by
`critic-selfx-scripts/rerun_reference.py`.

---

## 1. What was adopted, and where it lives

The sweep's verdict was adopt-for-three-things. This experiment is the
adoption: `core/genbatch/o3d_geometry.py` (new) holds the three calls,
`open3d==0.20.0` rides as the pinned `o3d` extra (the only cp312 aarch64
wheel — the pin is load-bearing), and every call **declines loudly, not
silently**, when the wheel is absent.

| use | where | default | cost on this box |
|---|---|---|---|
| self-intersection check | `o3d_geometry.self_intersection` → `MeshReport.self_intersection` → critic check (weight 1.5) | on, under the cap | median 0.16 s/mesh in the re-run's regime; 147 s for all 38 with everything else |
| ray-parity fallback volume | `o3d_geometry.parity_volume` → `MeshReport.parity_volume` → the solid-volume check reads it when the signed volume is unreliable | measured only when needed | 31 of 38 meshes, median tens of ms (the sweep: 18 ms) |
| quadric diet (LOD) | `o3d_geometry.quadric_diet` → `PropRequest.diet` → the executor's diet stage | **off** (`diet=None`) | the night pays it only if the recipe asks |

**The cap decision — "unchecked", not decimate-then-check.** Above
200,000 triangles the check declines and the critic reports
`unchecked` with that reason. The sweep measured why both halves of the
alternative fail: the check's cost above the cap is unbounded (801 s at
1.33 M triangles, 596 s at 1 M — §3.1 there), and a quadric stand-in
would be a verdict about a *different* mesh — the diet opened 14 of 19
closed meshes (§3.5), so it can both hide and create crossings. An
unanswered question stays unanswered; the check passes at 1.0 with its
reason so a prop never loses to a measurement that was not made.

**The diet default — off, because the report does not justify on.** The
diet is the one adoption that changes the mesh rather than measuring it,
and the sweep's own caveat is why it is opt-in: decimation to 10 %
opened 14 of 19 closed meshes, so a dieted prop measures differently
from the prop the generator handed over. When a request sets
`diet=DietRecipe(...)`, the executor decimates the repaired mesh, keeps
the dieted GLB (written by the new `write_glb` — the test fixtures'
writer promoted to production, one primitive, round-tripped by our own
reader), records it on the asset as a `diet` file with the numbers in
the recipe, and the critic measures the mesh the night keeps.

## 2. What the re-run changed (38 SimReady reference meshes)

`rerun_reference.py` measures each mesh twice — signals off (the
pre-Open3D measurement, bit-for-bit) and signals on — judges both
against one request (non-binding budget, so the verdict deltas are the
change and nothing else), and records every flipped check. The old
verdict is reconstructed exactly: the signals-off report's volume check
already behaves as the old code, so dropping the one new check and
recomputing the weighted mean is the old score to the digit.

**Box state:** load average 24.9 (1-min) at start and end — other seats
compiling; 102.7 GB available of 122.8 GB; CPU only, no lease. 38 meshes
in 146.8 s, peak RSS 710.5 MB — under the brief's 4 GB line. open3d
0.20.0, numpy 2.5.4, scipy 1.18.1, Python 3.12.3.

The self-intersection states line up with the sweep's uncapped 34-of-38:
**25 self-intersecting** (under the cap, found), **9 unchecked** (over
the cap: 306k–1.33 M triangles — IV pole, trunk lid, camshaft, cabinet,
hammer, brake lathe, forklift, conveyor belt, shelf a01), **4 clean**
(sponge, mug, spoon, golf ball). 25 + 9 = 34.

**Which verdicts changed, and why — all 38 scores moved, three ways:**

1. **8 closed meshes are now flagged self-intersecting** (score −0.10 to
   −0.13): the new check fails, and their signed volume is no longer
   trusted — the solid-volume check reads their ray-parity volume
   instead. These are exactly the sweep's closed-and-crossing meshes
   that sit under the cap. On them the parity read is close to the
   signed one (0.92×–1.11×): their crossings are thin, so the flag is
   the finding, not a volume correction. The sweep's big inflations —
   shelf a01 at **3.91×** (signed 0.2254 m³ vs parity 0.0576 m³) — sit
   *over* the cap and are therefore `unchecked` today; that is the cap's
   price, paid knowingly (§1).
2. **2 open meshes are now flagged self-intersecting** (score −0.06):
   they were already failing watertight; the crossing is one more true
   defect against them.
3. **20 open meshes flipped solid_volume, all fail→pass** (score +0.02
   to +0.25): their old verdict graded a signed volume the divergence
   theorem cannot support — mostly a tiny partial-sum reading "a shell,
   not a solid" (the filing cabinet read 0.4 % of its box) — and the
   parity fallback reads them inside the band (the cabinet: 53 % of its
   box, which is what a cabinet occupies). The mean score moved +0.048;
   the loudest case is the forklift at +0.244, whose 1.83 m³ signed
   partial sum became a 1.62 m³ parity read.

**What did not change, on purpose.** The watertight flag: 15 of 38
closed by our census before, the same 15 after. The measurement path
(hull, volumes, areas) and the GLB reader: untouched, and the sweep
already showed exact agreement. The `surface` check still reads the
signed volume as it always did — it *scales* the volume rather than
judging it, and a self-intersecting mesh's inflated volume makes that
check more lenient there, not less; recorded as an unchanged path.

## 3. The 12 rows a watertight swap would flip (and why it was not made)

Open3D's `is_watertight` also demands vertex-manifoldness and no
self-intersection — a different word from the critic's edge census. The
sweep found 12 rows where the census says closed and Open3D says not a
valid solid boundary. Swapping the flag is a semantic decision the brief
kept separate; these are the rows it would flip (volumes in m³; the
ratio is signed ÷ parity):

| mesh | triangles | signed | ray-parity | signed/parity |
|---|---:|---:|---:|---:|
| bodyPart_door_front_a01 | 168,604 | 0.000790 | 0.000744 | 1.06 |
| bodyPart_trunk_lid_a01 | 317,648 | 0.001505 | 0.001358 | 1.11 |
| container_system_sterilising_e01 | 85,800 | 0.003341 | 0.003344 | 1.00 |
| decor_candle_l01 | 13,856 | 0.000171 | 0.000171 | 1.00 |
| equipment_bench_vise_a01 | 106,162 | 0.002474 | 0.002573 | 0.96 |
| fixture_cabinet_a01 | 483,180 | 0.05798 | 0.05870 | 0.99 |
| food_processed_cannedFood_k01 | 13,140 | 0.000486 | 0.000485 | 1.00 |
| kitchenware_knife_b01 | 7,660 | 0.000185 | 0.000201 | 0.92 |
| storage_shelf_basic_a01 | 1,326,754 | 0.2254 | 0.0576 | 3.91 |
| suspension_control_arm_rearward_left_a01 | 21,066 | 0.0000709 | 0.0000706 | 1.00 |
| tape_clear_a01 | 2,816 | 0.000171 | 0.000172 | 1.00 |
| storage_shelf_basic_c01 | 457,760 | 0.02765 | 0.04400 | 0.63 |

Eight of the twelve are under the cap and now carry the
self-intersection flag anyway — the crossing is caught without touching
the watertight word. The three over-cap shelves (a01, c01) and the
trunk lid stay `unchecked` until the cap question is decided on its own
evidence.

## 4. What this makes possible

- A generated prop can no longer win the night by passing a triangle
  through its own skin: 8 of the reference set's closed meshes would
  have sailed through the old critic with an inflated volume.
- The 20 open-mesh volume verdicts stop grading numbers the divergence
  theorem cannot produce — the parity read is not authoritative on an
  open mesh either, but it is the conservative, winding-free number and
  it is *labelled* in the check's detail ("the ray-parity volume stands
  in, because…").
- Nights that want smaller meshes have a diet step with the numbers in
  the recipe — and the report's caveat (diets open closed surfaces)
  keeps it off by default.

## 5. What was not verified

- **The over-cap meshes were never checked** here (by design); their
  self-intersection states come from the sweep's uncapped run. Whether
  the cap should rise to, say, 500k — where 6 of our 9 unchecked sit —
  is a cost measurement nobody has made; the sweep's §6 says the same.
- **The diet stage ran only in the unit tests** (a 12-triangle cube at
  fraction 0.5, and a 12k-triangle torus at 0.1 with <5 % volume drift);
  no night has run with `diet` set, and its executor wiring is tested
  with the fake ComfyUI client, not a real generation.
- **The parity fallback's value on open meshes is a reading, not a
  truth** — on an open mesh it measures whatever region the present
  faces happen to bound (§3.3 of the sweep measured this class of
  behaviour on the mug). The check's detail always says when parity
  stood in.
- The build123d/CAD props were not re-measured (the sweep's §6: they are
  feature rows, not meshes).

## 6. Reproduction

`critic-selfx-scripts/README.md` — one command on the Thor
(`.venv/bin/python docs/lab/critic-selfx-scripts/rerun_reference.py`),
what it needs, and the request it judges against. Tests:
`tests/genbatch/test_o3d_geometry.py` (both regimes), plus the mesh,
critic and executor additions; the full suite (physag excluded, mujoco
is that seat's env) is 1885 passed.
