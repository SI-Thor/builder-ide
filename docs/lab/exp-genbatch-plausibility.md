# EXP — the plausibility side of the prop critic: consistency alone certifies ghosts

**Date:** 2026-10-31
**Verdict: EVERY CHECK IN THE PROP CRITIC IS A CONSISTENCY CHECK, AND A
CONSISTENCY-ONLY CRITIC PASSES A PROP THAT MATCHES ITS IMAGE PERFECTLY AND
IS NOT A THING THAT COULD EXIST. The other side of the judge is now
designed, fitted on the approved assets, with the ambiguity gate measured
off the same assets.**

---

## 1. The idea

TRELLIS.2 turns a concept image into a mesh. That is an **inverse
problem**: one picture admits many shapes. The prop critic judges the
result, and every check it runs is a **consistency** check:

| check | what it asks |
|---|---|
| `watertight` | is it a closed solid? |
| `repair_fidelity` | did the repair keep the prop's silhouette? |
| `triangle_budget` | is it inside the budget? |
| `bbox_aspect` | are its proportions the ones asked for? |
| `solid_volume` | does it fill its box like a solid? |
| `surface` | is its surface big enough for its volume? |
| `centre_of_mass` | is its mass inside its box? |
| `degenerate` | does it have flat triangles? |

Every one of them asks whether the prop is **internally valid**. Not one
asks whether the shape is a shape a real object has. A prop that is
watertight, correctly proportioned, solid, and matches its image exactly —
and depicts nothing that exists — passes all eight.

## 2. The hypothesis

> A prior over the features of real objects, fitted on the approved assets,
> catches what the consistency checks cannot — and a fiber-width gate says
> when the image itself was too ambiguous to judge.

## 3. The setup

- `core/genbatch/plausibility.py` — the prior, the ambiguity gate, and the
  two-sided judge. **numpy only**, plus the repo's own numpy-declared
  dependencies; no GPU, no TRELLIS, no render.
- `tests/genbatch/test_plausibility.py` — 16 tests, no fixtures, no
  network, no GPU.
- `docs/lab/genbatch-plausibility-scripts/measure_plausibility.py` — prints
  every number below.

**The toy has known ground truth.** The approved set is 200 objects of two
known kinds: 180 **mugs** (solid, roundish, ordinary volume) and 20
**planks** (flat, long, rare). The rarity is the point. The features are
drawn from per-kind distributions, so "plausible" and "implausible" are
facts about the world the toy was built from, not opinions about the
scores.

| | |
|---|---|
| Machine | **the builder-ide sandbox** — x86_64 Linux, Python 3.12.14, numpy 2.5.4, pytest 9.2.0 |
| **Not** | the Thor, and not a TRELLIS box: nothing here needs one |
| Approved objects | 200 (180 mugs, 20 planks) |
| Groups found | **(180, 20)** — the kinds, found by seeded k-means |
| Ordinary width (how far real objects of one kind sit from their centre) | 1.9035 |

## 4. The numbers

### 4.1 The grouping is what saves the rare kind

Median plausibility of 200 fresh props of each kind:

| kind | grouped prior | **pooled** prior (one distribution) |
|---|---|---|
| mug (180 of 200) | 0.5635 | 0.6294 |
| **plank (20 of 200)** | **0.3810** | **0.0473** |

**A single distribution over the pooled approved set calls the plank a
ghost** — 0.047 against 0.381, an eightfold difference — because the plank
sits in the bottom tenth of the fill ratio and the top tenth of the
elongation of the pooled set. The common kind is unaffected. This is the
failure mode of "one distribution over a multimodal world", measured.

### 4.2 The ghost

A ghost: a valid solid, the wrong shape for anything.

| | |
|---|---|
| plausibility | **0.0238** |
| distance to its group | 55.19 (standardised) |
| per-feature tail | **0.0476 in all six** — outside the approved range in every dimension |

### 4.3 The control: a consistency-only critic passes the ghost

| | consistency | plausibility | two-sided |
|---|---|---|---|
| **the ghost** | **0.9900** | 0.0238 | **0.1102** |
| a real prop (median of 200) | 0.9850 | 0.5193 | 0.3708 |

The consistency-only critic sees **0.9900** for the ghost — better than the
real prop's 0.9850 — and **passes it**. The two-sided judge puts it at
0.1102 against 0.3708, a factor of 3.4.

### 4.4 The measured scale gap

The consistency side's spread over the approved set against the
plausibility side's:

| | |
|---|---|
| consistency population | [0.9800, 0.9996] — a saturated IoU, as it is in practice |
| consistency spread | 0.005831 |
| plausibility spread | 0.286559 |
| **the gap** | **0.020348** |

**The consistency side is twenty times narrower than the plausibility
side.** A fixed weighting would have given it two percent of the say, and
a critic whose consistency score is saturated near 1 cannot tell a prop
that matches from one that does not. Both sides are therefore put on the
approved set's own scale before they are combined, and the gap that was
closed is reported rather than left implicit.

### 4.5 The ambiguity gate

| | |
|---|---|
| ordinary width (real objects of one kind) | 1.9035 |
| three reconstructions of a clear image | 0.9806 — below the gate |
| two reconstructions of an ambiguous image | **2.3066 — above the gate** |

The gate fires on the ambiguous image and the verdict is **escalate**: "the
reconstructions disagree by 2.307, more than real objects of one kind do
(1.903): the image did not determine the shape". The threshold is read off
the approved set, so no constant was chosen.

## 5. Two design bugs this experiment caught

Both were caught by the controls, before anything was published:

1. **The plausibility side used a one-sided percentile.** A prop with a
   surface-to-volume ratio of 30 — *extreme*, off the end of the approved
   range — scored the **highest** percentile in the set, because it was
   above everything. The side now uses the **two-sided tail probability**:
   extreme in either direction is what makes a shape a ghost. This one
   would have made the whole module certify ghosts, which is the exact
   failure it was written to prevent.
2. **The geometric mean of six independent tails compresses toward zero.**
   Multiplying six tails lands a perfectly ordinary prop near 0.2,
   because the chance that six independent features are all within 1.5
   sigma is small. The geometric mean is the right *statistic* (one
   impossible feature is not averaged away by five ordinary ones) and the
   wrong *scale*. The score is now the prop's atypicality **ranked against
   the approved set's own distribution of it** — a p-value for
   atypicality — and the typical prop sits near 0.5 where it belongs.

A third, smaller one: the method `_atypicality` and the attribute
`_atypicality` collided, and the shadowing broke every call after the
first assignment. Caught by twelve tests failing at once.

## 6. What this does not say

- **The toy is synthetic.** The truth is exact because the toy was built to
  have an exact truth. What is *not* shown here is that the approved
  assets are a good reference set, or that the six features separate real
  objects from ghosts — that needs the real assets, on the box.
- **The consistency side is still the repair's silhouette IoU**, and that
  check compares the repaired mesh with the mesh the generator produced —
  **it never looks at the concept image**. So the inverse problem is still
  not verified against its input. The other half of that work is not in
  this branch: it needs the image assets and the executor's stage records.
- **The score is a rank, so it is coarse for a small group.** With 20
  approved planks, a single plank's score moves in steps of 1/21. The
  claims in the tests are therefore distributional (medians over 200
  draws), not per-draw.

## 7. Reproducing it

```bash
cd ~/lm-wt/tiles
.venv/bin/python -m pytest -q tests/genbatch/test_plausibility.py   # 16 tests
PYTHONPATH=. .venv/bin/python docs/lab/genbatch-plausibility-scripts/measure_plausibility.py
```

Every number in §4 comes out of that script.
