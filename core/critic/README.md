# `core/critic` — the critic's calibration set, on real renders

Week 2 item 12 of `docs/plan.md`: *the critic's calibration set, first
members* — a fixed reference set of ~30 **real renders** with seeded defects,
run through the scripted checks, publishing false-positive and
false-negative rates **per defect class**.

The one-paragraph idea. Until a critic *model* is chosen and measured (X R4:
the critic is "the largest unchosen dependency in the whole stack"), every
automated verdict is a **scripted check** and wears `verdict@scripted` on
its face. Those checks have to be measured on something, and the something
has to be the pictures the critic will really be handed — so the reference
set is built from the **overnight Infinigen sweep's real renders**, not from
stand-ins. Each render gets one seeded defect, deterministically; the checks
run over the whole set; the FP/FN table says, per defect class, what the
scripted critic catches and what it misses.

The published table is [`CALIBRATION.md`](CALIBRATION.md). **Its first row is
the baseline that the critic model choice (week 3 item 18) has to beat.**

```
core/critic/
  models.py        the records: bases, members, check outcomes, verdicts
  harvest.py       the sweep's real renders, found read-only
  imaging.py       the analytic imaging helpers the checks share
  defects.py       the seeded defect vocabulary — the image plants
  checks.py        the scripted checks: analytic measurements, no model
  mesh.py          the mesh probe's seam, and the mesh defect plants
  probe_scene.py   the script that measures a scene inside Blender
  set.py           the reference set: the members, their recipes, the manifest
  critic.py        the critic: score the set, fold the FP/FN table
  grow.py          the set grows nightly — the function the night runner calls
  publish.py       write the table to CALIBRATION.md
  rebuild_mesh.sh  rebuild a sweep scene's geometry (the sweep deletes its own)
  measure_*.py     the measurement scripts the thresholds are set against
  exp_*.py         the experiments that decided how the checks are built
```

## Running it

```bash
# the tests
.venv/bin/python -m pytest tests/critic/ -q

# grow the set from the sweep, re-score, publish the table
.venv/bin/python -m core.critic --grow --publish
```

The mesh half needs an interpreter that has `bpy` — the Infinigen
checkout's virtualenv on the Thor:

```bash
export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
```

## The three rules the set is built on

1. **The renders are real.** Every member's base is a frame the sweep
   rendered on the Thor, with its sha256 recorded. Nothing is synthetic: a
   defect is seeded *into* a real render, so the checks are measured against
   the pictures the critic will really be handed.
2. **Every member is a recipe.** The defect's recipe rides with the member,
   so it can be re-derived from the base render alone. The render is the
   cache; the recipe is the truth (the house rule: store recipes, not
   meshes).
3. **There are clean controls.** Without them there is nothing to
   false-positive on, and the band's other half — "reject no more than a set
   fraction of the clean ones" — would be unfalsifiable.

Two rules govern how a defect may be **planted**, and both exist to keep the
table honest:

* **The plant may not know the check.** A defect is planted by what a
  *broken render* looks like, not by what the check measures. If a plant
  were tuned to a threshold, the table would be measuring the plant, not
  the critic.
* **The plant must be visible.** A defect nobody could see is a free false
  negative, and a free false negative makes the table a lie.

The second rule has a consequence the table depends on: a frame that
**cannot** carry a visible defect — dark water, where a hole is black on
black; a forest with no open sky to hang a copy in — does not become a
member at all. The plant says so (`placed: False`) and the set leaves the
base out. A member that does not exist is not a false negative.

## The two halves

| half | where the defect lives | how it is planted | what checks it |
|---|---|---|---|
| **image** | the render's pixels | deterministic in `(base, seed)` | the six image checks |
| **mesh** | the scene's geometry | the measured geometry, mutated | the three mesh checks |

The image classes are `black_frame`, `noise_fireflies`, `missing_object`,
`holes`, `texture_swap` and `floating_object`. The mesh classes are
`wrong_scale`, `hollow_mesh` and `clipped_geometry`.

The mesh half needs the scene's geometry, and the sweep **deletes its
`.blend` files** when a scene finishes (that is the sweep's disk policy, and
the sweep is read-only to this seat). So the geometry is rebuilt by
`rebuild_mesh.sh`, which re-runs the sweep's own coarse and fine stages with
the sweep's own argv into a scratch tree:

```bash
core/critic/rebuild_mesh.sh arctic:1 river:6
```

That it is *the same scene* is **checked, not assumed**: the coarse assets
are the scene's terrain, the sweep kept its copy, and the two are compared
byte-for-byte. The rebuild also reproduces the sweep's **render** — the
re-rendered frame matched the sweep's PNG to within 1/255.

## The counts, and what they mean

The counting rule is the cold-start seat's
(:mod:`core.coldstart.calibration`), and it is what keeps the table honest:

* a planted defect of class K that the check targeting K does not fire on
  is a **false negative** — including a defect the check could not see at
  all, because a seeded defect is a seeded defect and the table must not
  hide a miss;
* a check firing on a member carrying a *different* class of planted defect
  is **excluded** from all four counts: the member is defective, so the
  report is neither true of its own class nor false;
* on a **clean control**, any firing is a false positive and any silence is
  a true negative.

The band is §1.9's: catch the seeded defects (no false negatives) and
reject no more than a set fraction of the clean ones (default one in ten).

## The thresholds are measurements, not guesses

Every threshold in `checks.py` was set against a **measurement of the clean
controls** — the real sweep renders — and the scripts that produce those
numbers are in the package, so the thresholds can be re-derived from the
same sweep:

```bash
.venv/bin/python core/critic/measure_image.py     # the image checks
.venv/bin/python core/critic/measure_mesh.py <scene.blend>   # the mesh checks
.venv/bin/python core/critic/measure_set.py        # what the defects score
```

The measurements changed the checks many times, and each change is a story
the table tells. The short version: **every threshold that failed had a
reason that the real renders could state.**

* **`floating_blob` fired on 8 of 34 clean frames** — a 23.5 % false
  positive rate, well over the band. The cause was real: a bump on a
  smooth hillside looks, to a local statistic, exactly like a prop hanging
  in the air. The first fix was the **horizon** — the frame's skyline — and
  the measurement killed that too: the horizon came out at the *top row* of
  the picture in ten of the 41 real frames, because their sky is textured,
  and at the bottom row in two, because they have no texture at all. A
  horizon that is sometimes the top of the frame is not an oracle. The
  check now measures the **open space under the thing** — how far the
  frame's empty space extends below it before the next detailed row —
  which needs no horizon at all.
* **`patch_seam` caught 3 % of the planted swaps.** The frame's global row
  and column profiles could not carry the decision: a patch covering a
  fifth of the frame's width shifts the row profile by only a fifth of the
  colour difference it contains. The next version looked for the block's
  four edges but kept only the six strongest candidates in each direction,
  and a natural frame has more than six straight edges. The version after
  that measured the block's interior against the ring around it, which a
  landscape reproduces easily (a sky over a desert measured 0.74 on that
  statistic). What is left is the **weakest of the block's four sides**,
  measured in the frame's own pixels: a pasted rectangle is bounded by
  four straight, sharp steps, and a landscape does not have four of them.
* **`watertight` fired on every real scene.** Infinigen's terrain is a
  heightfield and is never watertight, and its eroded rock shells are open
  surfaces. Openness is not the defect; a **hollow** shell is one whose
  faces point inwards, and the probe measures that fraction. The clean
  props' worst was 0.593 — vegetation is full of inward faces — so the
  threshold sits above that.
* **`scale_bounds` could never catch a modest scale error.** Within one
  asset family Infinigen's own instances vary by up to **5.48×** their
  family's median (a family of chopped trees holds both stumps and whole
  trees), so a 1.45× error sits *inside* the natural spread and no
  threshold could separate it. The defect is therefore a **gross** scale
  error and the rule is "a prop far bigger than every other prop of its
  kind", with the threshold above the measured natural spread.
* **`edge_cut` fired on every real scene.** A camera standing in a
  landscape cuts geometry all the time: 98 clean props are cut by the near
  plane, 149 by the picture's edge, and 73 are sliced through the middle.
  What the measurement separated was the *severity*: the closest a clean
  prop's middle comes to the picture's edge is 0.0105 of its own
  half-width, and no clean scene has a prop that close.

## The nightly growth

The set is meant to grow: the sweep keeps producing renders, and the
calibration set should grow with it. `core.critic.grow.grow` is the
function the night runner calls, and it does three things in this order:

1. **Harvest** the sweep's real renders (read-only — the sweep belongs to
   another night's work).
2. **Grow** the set: for each base that is not in the set yet, add the
   members it earns, up to the target. The members already in the set are
   never rebuilt and never duplicated.
3. **Re-score** the whole set and publish the table.

The growth is **sized to the night's unused lane** — the same rule the
cold-start seat uses: at most a night's cap (8 members), never past the
target (~30), and never more than the leftover rail affords. The cost per
member is the CPU-lane cost of a scripted check; the GPU lane is untouched
by design, because the scripted critic runs no model.

```bash
.venv/bin/python -m core.critic --grow --publish
```

It is safe to call every night: a night with no new renders adds nothing
and re-publishes the same table.

## What this seat does not do

* **Choose a critic model.** That is week 3 item 18, and this table is the
  baseline it has to beat.
* **Re-render the sweep.** The sweep belongs to another night's work and is
  read-only here; the geometry this seat needs is rebuilt separately, and
  the frames are the sweep's own.
* **Audit to the ledger.** The critic returns verdicts and a table; the
  night runner is the one that audits them (§1.8's one log).
