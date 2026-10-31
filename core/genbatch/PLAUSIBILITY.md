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
**approved**. Six features, all of them derived from what the mesh layer
already measures (`MeshReport`), so nothing here needs a second pass over
the geometry:

| feature | what it says |
|---|---|
| `log_volume` | how big it is — logarithmic, because a mug and a cathedral are both ordinary |
| `sphericity` | `area / volume^(2/3)`; 4.836 is a sphere's, and nothing real is below it |
| `elongation` | longest axis over shortest |
| `fill_ratio` | the volume over its box — a solid fills a lot of it, a shell almost none |
| `offcentre` | how far the centre of mass sits from the middle of the box |
| `defect_rate` | the share of the mesh's triangles that are holes, seams or flat |

The approved set is **grouped** first (seeded k-means on the standardised
features) and each group keeps its own distribution. A prop is compared
with the group it most resembles. That grouping is the whole point: a
plank is 20 of 200 approved assets, and **a single distribution over the
pooled set calls every plank a ghost** — measured, 0.047 against 0.381 for
the grouped prior.

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
from core.genbatch.plausibility import features_from_report, judge, ReferencePrior

prior = ReferencePrior(approved_features, clusters=3, seed=0)
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
