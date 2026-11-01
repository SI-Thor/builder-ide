# The plausibility side of the prop critic

**The gap.** Every check in `core/genbatch/critic.py` asks whether the prop
is a **valid solid**: watertight, filling its box, surface big enough for
its volume, mass inside it. Those are real checks and they catch a broken
mesh. None of them asks whether the shape is the kind of shape a real
object has.

The repair-fidelity check is a **consistency** check — the silhouette IoU
between the repaired mesh and the mesh the generator handed over. It says
*"the repair did not quietly reshape the prop"*. It does not say the prop is
a thing that could exist.

**Consistency is not plausibility, and a consistency-only critic certifies
ghosts.** A generator that satisfies the measurement perfectly and produces
an object no camera has ever seen passes every check in the current critic.
This module is the other side of the judge.

## The prior over real-object features

A prop is plausible when it looks like the things that have been
**approved** — and like the **real** objects, because the approved props
are generated and a generated prop is a solid while most real things are
shells. Six features, all of them derived from what the mesh layer
already measures (`MeshReport`), so nothing here needs a second pass over
the geometry:

| feature | what it says |
|---|---|
| `log_volume` | how big it is — logarithmic, because a mug and a cathedral are both ordinary |
| `sphericity` | `area / volume^(2/3)`; 4.836 is a sphere's, and nothing real is below it |
| `elongation` | longest axis over shortest |
| `fill_ratio` | the volume the object **occupies** over its box — a solid and a hollow mug of the same size read alike |
| `offcentre` | how far the centre of mass sits from the middle of the box |
| `defect_rate` | the share of the mesh's triangles that are holes, seams or flat |

## The volume the features are measured against

`fill_ratio` used to divide the mesh's **signed volume** by its bounding
box, and that number answers "how much material is there" rather than
"how much of the space does the object take up". The two agree on a solid
and part company on a shell: the real SimReady mug encloses **43 cm³ of
ceramic** in a box that holds **826 cm³**, and the signed measure reads
its fill ratio as **0.052** where the toy mug's solid reads **0.68**.

So the features are read off the **occupied volume** — the space the
object takes up — measured by `occupancy.py` in one of three ways, the
convex hull of its vertices by default. A real mug's occupied volume is
**489 cm³**, and its fill ratio reads **0.592**. The old measure is kept
as a parameter (`signed`) so a before-and-after can be measured on the
same meshes.

The hull over-estimates a concave object — the hull of an L-bracket is
its box — and that is the safe direction here: an object reads as fuller
than it is, and is judged more ordinary rather than less.

## The reference set is the union

A prior over the features of **real** objects can only be that if real
objects are in it, and the approved props are **generated** — they are
solids. A prior fitted on them alone called **every one** of the 38
sampled real SimReady assets a ghost, because a real object is a shell and
the toy is not.

So the reference set is the **union**: the approved assets the library
has accepted, and the real objects, measured by the same pipeline. The
real objects live in `simready-reference.json` — 38 rows of six numbers
each, with their provenance — and `reference.py` loads them and fits the
prior over the two halves.

**The groups are the kinds.** The score is a **rank inside a group** — the
share of the group's members that are at least as atypical as the prop — so
a group of `n` members cannot score below `0.5 / (n + 1)`, and the
threshold (0.05) needs **ten** members before a group can express it at
all. The sampled real assets are 37 categories for 38 packages, so a
category is a kind of one object and the threshold is unreachable inside
it. They are one kind: *a real object*.

`ReferencePrior` takes `labels` and the groups are the kinds: the toy's
own kinds (a mug is a mug, a plank is a plank) and the real objects' kind.
Without labels it falls back to the seeded k-means grouping it always had,
so nothing that used it before changes.

**A prop is matched to its kind in that kind's own scale.** The distance
to a group's centre is measured in the group's own spread, not the pooled
one: the pooled spread belongs to the population that is widest — the real
objects, whose log volume runs over fourteen orders of magnitude — and
against that yardstick a thin real pole looks more like a toy plank than
like a real object, and is then judged against a group it does not belong
to.

The grouping is the whole point: a plank is 20 of 200 approved assets, and
**a single distribution over the pooled set calls every plank a ghost** —
measured, 0.047 against 0.381 for the grouped prior.

The score itself is a **p-value for atypicality**: the share of the
approved objects of that kind that are *at least as atypical* as this one.
A prop in the middle of its kind scores around 0.5; a ghost scores near
zero. The per-feature reading is the **two-sided tail probability**, so a
value that is extreme in *either* direction counts — a surface-to-volume
ratio of 30 is extreme, and a one-sided percentile would have called it the
most ordinary value in the set.

## The ambiguity gate

TRELLIS.2 turns an image into a mesh: an inverse problem, where one
picture admits many shapes. The set of shapes consistent with a picture is
a **fiber**, and a wide fiber means the picture did not determine the
shape.

The seat already draws N reconstructions of the same request (the night's
seeds), so the fiber's width is **measured**, not assumed: it is how much
the reconstructions disagree, in the same standardised units the approved
set uses. The threshold is read off the approved set too — the 90th
percentile of how far real objects of one kind sit from their own centre —
so no magic number is involved.

A wide fiber is not a bad prop. It is an **ambiguous** one, and the verdict
is *escalate* (another seed, another model, or a question) — not *accept*
and not *reject*.

## The weighting, measured rather than guessed

The two sides are not the same kind of number. A silhouette IoU lives near
1 and saturates there; the plausibility score spreads over the whole range.
Add them with a hand-picked weight and the wider side silently wins.

So both sides are put on **the approved set's own scale** first — each
becomes a percentile among real objects — and the two are combined as a
weighted geometric mean, so a prop that is perfect on one side and
impossible on the other does not average out. The scale gap that was closed
is **measured and reported**: with a saturated consistency population the
gap is **0.0203**, so a fixed weighting would have given the consistency
side two percent of the say.

## What it refuses

Nothing — it reports. But it reports a gap of zero when the gap was not
measured (no consistency population), because **an unmeasured gap is not a
small gap**, and it reports the fiber width as `nan` rather than zero when
there is only one reconstruction, because **one sample is not evidence of
agreement**.

## Using it

```python
from core.genbatch.plausibility import features_from_report, judge
from core.genbatch.reference import union_prior

# the prior: the approved assets and the measured real objects, grouped by kind
prior = union_prior(approved_features, approved_kinds)

verdict = judge(
    features=features_from_report(report),
    consistency=repair.fidelity,
    prior=prior,
    reconstructions=[features_from_report(other) for other in the night's seeds],
    consistency_population=[asset.fidelity for asset in the approved set],
)
print(verdict.line())
```

`verdict.ambiguous` is the gate; `verdict.escalate` is what the night
should do about it.

## What it measures

The confusion table, the three fill measures against volumes that are
known, the leave-one-out reading, and the ways that were tried and
failed, are in
[docs/lab/exp-critic-shells.md](../../docs/lab/exp-critic-shells.md).

The short form: with the prior fitted on the union, the ghost scores
**0.0385** and is flagged, and **1 of 38** real SimReady assets (2.6 %) is
flagged — against **38 of 38** before. Held out of the fit, 3 of 38
(7.9 %) are flagged, which is structural for a kind of 38 and is written
up rather than glossed.
