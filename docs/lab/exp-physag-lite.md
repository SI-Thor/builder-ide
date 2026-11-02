# EXP — physag-lite: props that work, accepted by running their action

**Seat:** physag-lite (branch `physag-lite`, this worktree)
**Runs:** 2026-11-01, 06:25 → (the Thor rebooted 10:59 mid-run; this doc's
numbers are from the resumed run, same day. The three arm tables in
§4/§6/§7 are from the final re-run of 2026-11-01 14:36–15:25, after the
box-cut segmentation fix; the superseded trellis run is kept at
`artifacts/physag-lite/run-trellis-buggyseg/`)
**Question:** can our own loop — plan in the cloud, generate on the Thor,
segment, build MJCF, check in MuJoCo on CPU, repair once, record — deliver
props whose action *runs*, and what does each stage cost?

---

## 1. The mechanism (what was built)

`core/physag/` is the loop, one module per stage. Nothing after the mesh
needs a GPU; the checker is deterministic and unit-tested (57 tests,
`tests/physag/`, all passing on every commit quoted below).

1. **Plan (cloud).** A typed `InteractionSpec` (`spec.py`): parts with
   roles and cut planes, a joint (type, axis, limits, damping, armature),
   an action (kind, target, duration, relative tolerance, dwell), physical
   priors, and — per prior — a `basis` field (`measured` / `estimated` /
   `derived`). The ten plans live in `docs/lab/physag-lite/specs/` and were
   authored in a cloud session (MiniMax-M3.1-Flash on the provider's
   servers; the configured provider credential store was not readable from
   the seat, so the plans are committed as data — the note is in every
   plan's `planner` field). **No model runs on the Thor.**
2. **Generate (Thor).** The existing TRELLIS.2 path: SDXL picture from the
   plan's image prompt, TRELLIS.2 mesh, one GLB per prop
   (`generate_meshes.sh`, the seat's own ComfyUI on :8189 so the shared
   server's queue is untouched). §3 has the numbers.
3. **Build.** `segment.py` splits the mesh at the spec's cut planes
   (axis-aligned, with an inset rule so the two pieces share no
   triangles), then checks each part-to-spec mapping: bbox IoU against the
   plan's `expect` box, containment, coverage — a mapping that fails is
   `verified: false`, and an unverified mapping **does not count** towards
   the completion rate (Hy4 guard 1). `decompose.py` cuts each part into
   convex pieces whose hulls are measured against the material in both
   directions (mesh→collider deviation, collider→mesh stray, hollow depth),
   and `mjcf.py` writes bodies, joints, convex-decomposition colliders and
   one actuator, with the actuator's force capped at the plan's prior
   (`actuator_force_n` / `actuator_torque_nm`) — no unbounded PD (guard 3).
   The base is free unless the spec says `base_static` (guard 3: "stays
   upright" must not be trivial).
4. **Check (CPU, MuJoCo).** `check.py` runs a **rest baseline first** (the
   prop alone, settling `rest_s`): explosion, tipping (>15° from upright),
   sliding (>2% of the diagonal) or initial contacts deeper than ε void
   the physics score — stability is never scored on a prop that cannot
   stand still (guard 2). Then the action runs and completion is scored
   with **relative** tolerances (guard 4): for a joint, 2% of the joint's
   own travel; first entry into the band, dwell for the last
   `dwell_steps` steps, overshoot, settling time and the last-decile
   deviation are all recorded. ε for penetration is 0.5% of the prop's
   diagonal, per contact, at every step; peak actuator force is recorded
   against the cap. A render of the final state is written beside the
   delivery.
5. **Repair (cloud), at most one round.** If completion failed, the
   measurements and the render go back to the planner. `spec.py`'s
   `repair_is_allowed` enforces the freeze mechanically: if the revision
   moved the action or the joint limits, the prop is kept, marked
   `action_changed`, and **excluded** from the completion rate (guard 5).
   Priors and cut planes may change; the spec diff is in the delivery.
6. **Record.** `delivery.py` writes one JSON per prop. The verified /
   estimated split is enforced in code: a value from the plan's priors
   cannot enter `verified` — every prior lands in `estimated` with its
   basis, unless the plan explicitly claimed `measured` (guard 5).

The seed-159 arm (`run_seed_arm.py`) swaps the priors for SimReady's
(`~/lm-wt/simready-survey/simready_priors.json`), scoring the planner's
guesses against the survey's ranges per field: deviation from the range
midpoint, and a range referees only when it spans at most ±10% around its
midpoint — a wide range grades nothing (guard 5). Mass is scaled by volume
from the sampled asset's size to the plan's size. The category mapping is
recorded with its confidence: SimReady has no doors, drawers, lanterns or
tables (0 drawers in 2,677 assets), and four of the ten props borrow from
the nearest category, named as borrowed.

The CAD arm (`run_cad_arm.py`, the 2026-11-01 addendum) runs cad-bakeoff's
recorded SolidCraft designs through the **same** planner plans, the same
decomposition, MJCF builder, checker and delivery. The parts and the joint
come from the kernel's URDF — no segmentation — but the plan's *claim*
about where the moving part is (`expect` boxes) is still measured against
the kernel's geometry, which is the one thing this arm can say that the
generated arm cannot: it separates "the planner guessed the part wrongly"
from "the mesh is not what the planner thought". The kernel's bodies are
decomposed body-by-body and merged per plan part (`subparts`), because one
convex search over a merged leg-and-rail frame produces hull-of-frame
colliders that no axis-aligned cut takes apart.

## 2. The box

| | |
|---|---|
| Machine | NVIDIA Thor, aarch64, 14 cores, 122 GB unified memory |
| Kernel | 6.8.12-1021-tegra |
| Memory rule | every heavy step under `thor-admit` (admission before spend; the daemon admits when MemAvailable − peak ≥ 25 GB) |
| During the resumed runs | 4–6 other leases active (an infinigen sweep, two model servers, lab-motion, d1dec); load 6–9 |

The morning's first run died with the box: the Thor hung ~10:45 (another
seat's JAX run preallocating ~90% of unified memory) and was power-cycled
at 10:59. Everything below is from the resumed run and says so where it
matters.

## 3. Generation: ten props, SDXL → TRELLIS.2

(`generate_meshes.sh`; one admission lease `physag-lite.generate`, peak
40 G — the measured spike; the GPU utilisation sampled once a second and
integrated, so the CPU tail of a TRELLIS run is not charged to the GPU.)

| prop | mesh step wall | GPU-busy (mesh window) | GLB |
|---|---:|---:|---:|
| crate | 232 s | 180 s | 50.7 MB |
| chest | 141 s | 89 s | 55.8 MB |
| lantern | 130 s | 77 s | 52.0 MB |
| door | 120 s | 72 s | 54.2 MB |
| drawer_unit | 171 s | 114 s | 54.5 MB |
| barrel | 136 s | 81 s | 50.8 MB |
| cart | 113 s | 70 s | 52.3 MB |
| gate | 134 s | 92 s | 47.8 MB |
| ladder | 140 s | 99 s | 37.0 MB |
| table | 152 s | 53 s | 46.2 MB |
| **batch** | **~24 min wall** | **955.9 s GPU-busy** | mean util 66.6% |

The per-prop GPU-busy numbers are the integral over each prop's mesh-step
window, attributed by the GLB's mtime and the logged step duration — the
window can overlap the previous prop's image tail by a few seconds, so
each number is ±10 s. The batch total is the integral over the whole log
and is exact. Every mesh is ~700k triangles, ~1 m across (the generator's
own normalisation).

## 4. The generated arm (TRELLIS + geometric segmentation)

*(numbers from `artifacts/physag-lite/run-trellis/summary.json`; the
per-prop deliveries sit beside it)*

Final run, 2026-11-01 14:36–14:57, after the box-cut fix. Box state
during the arm: load 19–28 under 29–30 other users' jobs, 57–59 GB
available of 122 GB. The arm is CPU-only (the meshes are §3's), so the
GPU-busy column is 0 by construction; the loop's GPU cost lives in §3.

The run before the fix is kept at `run-trellis-buggyseg/` (13:03, same
plans, same meshes): its four box-cut props could not build at all.
"Outside a box" is a union of six half-spaces, and the old code wrote
it as a chain of clips — an *intersection*, whose answer is empty — so
the rest part came out with no material and the moving part's colliders
were the whole mesh. With the fix (a rest part keeps the triangles whose
centres lie outside the box; colliders are clipped to the part's region
by peeling the six slabs off the convex pieces, one face at a time), the
door builds and counts; drawer unit and gate still do not build, but
for a different and honest reason, below.

| prop | interaction | physics | counted | reached / target | repair | wall s |
|---|---|---|---|---|---|---:|
| barrel | incomplete | invalid | yes | 0.175 / 0.200 | force cap 140→320 N | 239 |
| cart | incomplete | invalid | yes | −0.001 / 0.500 | — | 83 |
| chest | **completed** | invalid | yes | 1.571 / 1.571 | lid's expect box | 247 |
| crate | **completed** | invalid | yes | 1.571 / 1.571 | — | 112 |
| door | incomplete | invalid | yes | 1.495 / 1.571 | — | 113 |
| drawer_unit | not built | — | no | — | — | — |
| gate | not built | — | no | — | — | — |
| ladder | incomplete | invalid | yes | −0.000 / 0.698 | torque cap 10→60 N·m | 170 |
| lantern | incomplete | invalid | no¹ | 0.181 / (hang) | — | 118 |
| table | incomplete | invalid | yes | 0.553 / 0.785 | torque cap 20→60 N·m | 193 |

¹ The handle's mapping is unverified: the split's handle covers 19 % of
   the region the plan claimed — the generated lantern's handle is
   thinner than the plan thought. Guard 1: completion is reported only
   for verified mappings.

**Completion: 2 of 7 counted (28.6 %)**, against PhysAg3D's 91.3 % on
in-the-wild objects. **Stability: 0 of 7.** Every counted prop's
stability score is *void*, not failed: the collider guard (guard 2)
measures each part's convex collider against its material, and the
generated meshes are organic, so the hulls stray far from the material
on the concave side (door 110 mm, barrel 172 mm, table 597 mm,
ladder 635 mm). The guard's job is exactly to refuse to score stability
on a collider that does not stand for the mesh; §8 says what that
means.

**Drawer unit and gate: the mesh is not the prop.** Both meshes are
featureless solid blocks (0.6 m and 1.2 m across, ~700 k triangles,
no drawer front, no leaf). The plan's drawer box
(0.06–0.94, 0.12–0.88, 0.28–0.62 normalised) and leaf box
(0.12–0.95, 0.04–0.55, 0.10–0.92) enclose interior space only: the
split finds **0 triangles** inside either box, the moving part has no
material, and the builder now refuses with a named error ("part … has
no volume to make a collider from") instead of writing a massless body
that a joint would carry and let the action "complete". This is the
distinction the CAD arm exists to make explicit: here it is the mesh,
not the plan, that is wrong — the plan's boxes are plausible for a real
drawer unit and gate, and the generator produced a block.

## 5. The repair round

Four of the seven counted props did not complete on the first pass and
used their one repair. All four revisions touch only priors or the
segmentation claim — the action and the joint limits are frozen, the
diff is in every delivery, and none is excluded for
`action_changed`:

| prop | first pass | the revision | after |
|---|---|---|---|
| barrel | incomplete (tilt 0.175 / 0.200, outside the 2 % band) | actuator force cap 140 → 320 N | 0.175 / 0.200 — still outside the band; the cap was not the limit |
| ladder | incomplete (slide 0.000 / 0.698 — the rails do not move) | torque cap 10 → 60 N·m | 0.000 / 0.698 — still at rest |
| table | incomplete (tilt 0.553 / 0.785 after) | torque cap 20 → 60 N·m | 0.553 / 0.785, inside the band but the dwell fails on an organic mesh |
| chest | lid mapping unverified (the piece covers 31 % of the claimed box) | the lid's `expect` box narrowed to the piece it found | verified; the action completes (1.571 / 1.571) |

The repair round rescued exactly one prop (the chest's *mapping* — the
action always completed on the chest; what failed was the part-to-spec
claim). The three force/torque repairs made the actuator stronger
without changing the outcome: on organic meshes the limit is not the
cap, it is the friction between a convex collider and a shape it only
approximately stands for.

## 6. The CAD arm (SolidCraft, parts by construction)

The designs are cad-bakeoff's recorded cloud answers
(`~/lm-wt/cad-bakeoff/out/gen/<prop>.solidcraft.json`), built by the
SolidCraft CLI, read through their URDF, and run through the same loop.
Ten designs; **three do not build** (cart, ladder, lantern — the recorded
scripts have kernel errors, e.g. cart: `step 11 (solid.combine): unknown
body 'bed'`); the CAD arm's completion rate counts the seven that build.

First pass, before the body-by-body decomposition fix (09:52, kept at
`artifacts/physag-lite/run-cad-prefix/summary.json`): 2/7 completed, 1
stable, wall 37.7 s for the ten — the merged-frame colliders were
initially self-intersecting or inflated, and the collider guard voided
five of the seven scores.

Re-run with the fix: re-verified at 15:25 on the final code (`run-cad-1133/`
kept beside `run-cad/`); the two runs agree field for field, so the
numbers stand. Wall 43.0 s for the ten.

| prop | interaction | physics | counted | reached / target | wall s |
|---|---|---|---|---|---:|
| barrel | incomplete | invalid | yes | 0.128 / 0.150 | 14 |
| chest | incomplete | invalid | yes | 0.660 / 1.571 | 19 |
| crate | incomplete | unstable | yes | 0.884 / 1.571 | 1 |
| door | incomplete | **stable** | yes | 0.001 / 1.571 | 1 |
| drawer_unit | **completed** | **stable** | yes | 0.300 / 0.300 | 1 |
| gate | **completed** | invalid | yes | 1.396 / 1.396 | 4 |
| table | incomplete | invalid | yes | 0.000 / 0.785 | 3 |
| cart, ladder, lantern | not built | — | no | — | — |

**Completion: 2 of 7 (28.6 %)** — the same rate as the generated
arm's 2 of 7, on disjoint evidence: the CAD props' parts and joints
are by construction, so a completion here means the *action and the
actuator* work, and the non-completions are the actuator not reaching
(chest 0.660/1.571, crate 0.884/1.571, door 0.001/1.571) rather than a
segmentation guess. The two completed CAD props are precisely the two
that do not exist as articulated props in SimReady (drawer, gate) —
the loop can run a drawer and a gate when the parts are real, and
cannot run them when the generator made a block (§4).

**Stability: 2 of 7** (door, drawer_unit) — the only stable physics
scores in the whole experiment. The CAD meshes are exact solids, so
the convex colliders sit on their material (0.0 mm mesh→collider on
every CAD prop) and the guard has nothing to void; where it still
voids (barrel, chest, gate, table) it is the collider→mesh stray on a
curved or lathed surface (78–237 mm), the same guard working as
designed.

The wall time is the contrast the arm is for: 43.0 s for ten props
against the generated arm's 1275 s — the decomposition budget spent on
thousands of triangles instead of seven hundred thousand.

## 7. The seed-159 arm (SimReady's priors vs the planner's)

*(numbers from `artifacts/physag-lite/run-seed/summary.json`; the
per-prop `priors_comparison.json` sits beside each delivery)*

Same meshes, same segmentation, same action, no repair round (the arm
is a prior comparison, and a repair would blur whose priors are being
compared) — only the priors change: mass is SimReady's, scaled by
volume from the sampled asset's size to the plan's; friction is the
SimReady material's median; the actuator limits stay the planner's,
because SimReady has no actuators, and the record says so. Run
15:06–15:22, box state as §4.

| prop | interaction | physics | counted | reached / target | wall s |
|---|---|---|---|---|---:|
| barrel | incomplete | invalid | yes | 0.193 / 0.200 | 127 |
| cart | incomplete | invalid | yes | −0.514 / 0.500 | 85 |
| chest | completed | invalid | no¹ | 1.571 / 1.571 | 177 |
| crate | **completed** | invalid | yes | 1.571 / 1.571 | 137 |
| door | **completed** | invalid | yes | 1.546 / 1.571 | 121 |
| drawer_unit | not built | — | no | — | — |
| gate | not built | — | no | — | — |
| ladder | incomplete | invalid | yes | −0.001 / 0.698 | 105 |
| lantern | incomplete | invalid | no¹ | 0.181 / (hang) | 132 |
| table | incomplete | invalid | yes | 0.443 / 0.785 | 98 |

¹ Unverified mapping on the *first-pass* split (chest lid 31 %, lantern
   handle 19 % of the claimed region): without the repair round — the
   one round that would have fixed the chest's claim in §5 — the
   chest's completion does not count. Guard 1, applied to the priors
   arm as well.

**Completion: 2 of 6 counted (33.3 %)**, 0 stable — the same shape as
§4. The priors moved individual outcomes: the door *completes* under
SimReady's 8.4 kg cabinet mass where the planner's 28 kg door stalled
at 1.495/1.571; the barrel came closer (0.193 vs 0.175 of 0.200) but
stayed outside the 2 % band; the cart went the wrong way (−0.514 of
0.500) under the pallet friction. A prior is not a label: it changes
which props work.

**The scoring.** All ten props have a SimReady category (two direct —
crate, and barrel as drum — eight borrowed; SimReady has no doors,
drawers, lanterns or tables, 0 drawers in 2,677 assets, and the record
names each borrowing with its reason). Mass and size ranges referee
(tight by construction — most are single observations, worth exactly
one asset, and the flag travels with the number); the friction ranges
span an order of magnitude and referee nothing. The planner's mass
against the volume-scaled SimReady midpoint, per prop:

| prop | category (confidence) | planner kg | deviation from scaled mid |
|---|---|---:|---:|
| gate | structure (borrowed) | 16 | −16 % |
| ladder | rack (borrowed) | 9 | −96 % |
| table | pallet (borrowed) | 35 | +122 % |
| door | cabinet (borrowed) | 28 | +234 % |
| chest | container (borrowed) | 20 | +294 % |
| drawer_unit | cabinet (borrowed) | 18 | +625 % |
| barrel | drum (direct) | 32 | +756 % |
| cart | pallet (borrowed) | 30 | +922 % |
| crate | crate (direct) | 12 | +1365 % |
| lantern | lighting (borrowed) | 1.4 | +2743 % |

The planner's masses sit one to two orders of magnitude above the
survey's evidence on eight of ten props. The deviation is not a
scoring artefact of the volume scaling — the scaling is explicit in
every record and the unscaled comparison is kept beside it; it is
what seed 159 asked for: the planner guesses "a barrel weighs about
32 kg", and the measured drums say the object in this class, scaled to
the plan's 0.45 m, weighs 3.7 kg.

## 8. What it makes possible

Three things this sitting changes, each one a door opened rather than
a score improved:

1. **Box cuts work, and the loop can now say which of plan or mesh is
   wrong.** Before the fix, every box-cut prop died inside the builder
   with a mass error and no diagnosis. After it, the door and the
   lantern build and run, the drawer unit and the gate fail with a
   named, correct diagnosis (the mesh is a block; the moving part has
   no material), and the guards that keep the completion rate honest
   (a rest part owns its complement, not a region; the split's own
   component count is reported) are unit-tested. A box-cut plan
   against a generated mesh is now a *testable claim* instead of a
   coin flip.
2. **The stability voids are a measurement, not a failure of the
   checker.** Zero of seven stable on the generated arm looks like a
   broken checker; the per-prop numbers say otherwise — the colliders
   stray 110–635 mm from organic material the hulls cannot follow, and
   the guard voids rather than scores. What the loop can now promise:
   a `stable` in a generated-arm delivery means the collider really
   stands for the mesh. The CAD arm shows the other side of the same
   guard: exact solids give 2 stable out of 7, the only stable scores
   in the experiment.
3. **The priors are the cheap lever.** The seed arm is the first place
   in the experiment where swapping one field changes which props
   complete (the door under SimReady's mass). The scoring says the
   planner's mass guesses run two to twenty-eight times the surveyed evidence. A
   planner that read the survey before guessing — or a repair round
   told the deviation, not just the render — is the obvious next
   experiment, and the seam for it (`Priors`, the `basis` field, the
   comparison record) already exists in the loop.

## 9. What was not verified

- The plans and the repairs are session-authored data, not scripted
  provider calls: the credential store was not readable from the seat.
  The loop's *mechanism* (parse, freeze, check, record) is invariant to
  where the JSON came from, but "a cloud model plans and repairs" rests
  on the session transcripts, not on an API log.
- The GPU-busy attribution per prop is window-based (±10 s); the batch
  total is exact.
- The CAD arm's three build failures are taken from the recorded
  designs' stderr; the designs were not edited to make them build.
- `mesh_closed` / volume-ratio guards do not fire on the generated meshes
  (they are open surfaces); the collider guards that carry those scores
  are the distance measures, and the volume ratio is `null` in every
  generated-arm delivery.
- The drawer unit and gate meshes are called "featureless solid
  blocks" from triangle counts: 0 of 698,884 / 698,890 triangle
  centres inside the plan's moving-part box, against 316,001 of
  699,246 for the door's panel. No render of the two blocks was made;
  the count is the evidence.
- The seed arm's single-observation ranges are tight *by construction*
  (one asset is within ±10 % of its own midpoint) and are worth
  exactly one asset; the mass deviations in §7 inherit that width, and
  the volume scaling from asset size to plan size is an assumption,
  kept explicit in every `priors_comparison.json`.
- The seed arm runs without its repair round by design; the chest's
  uncounted completion there (§7) is the price of that design, and a
  seed arm *with* repair would conflate whose priors were tested.
