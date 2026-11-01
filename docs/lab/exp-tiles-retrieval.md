# EXP — the retrieval front and the score bands: E1 on the tiles acceptance rig

**Date:** 2026-11-01 (the tiles-retrieval seat; CPU-only, no GPU, no server — the
rig is the acceptance rig's own, run on the ProArt)

**Verdict: THE FRONT REACHES THE TOP OF THE RANGE AND PINCHER'S NUMBERS DO NOT
TRANSFER. The retrieval front played a tile of the requested style in 600 of
600 contexts and landed on the always-matching reference (504 against 503);
at pincher's 0.80 the fast path never fires — 0 of 600 — because that number
was measured in a different embedding space, and the calibrated line for ours
is 0.42, where all three of E1's bars pass. What the rig cannot say is
whether +0.04 over the bandit is a difference: the always-matching reference
itself is only p = 0.0724 against the learner at 600 plays.**

---

## 1. The idea

`core/tiles` had a chooser and no way to find things. The chooser is a
contextual bandit: it learns which tile wins in which bucket, and it picks well
*among the tiles it was handed*. With a library of six tiles that is enough.
With a library of six hundred it is not, because the bandit's estimate is one
number per (bucket, tile) and it can only act on what it is given.

The retrieval front is the missing half: it embeds the game's state, takes the
K tiles whose meaning matches, and hands those to the bandit, which then does
what it is good at — learning from outcomes. The front narrows; it does not
decide.

`quilt-pincher`'s reflex engine adds the second half of the idea, and this
seat borrowed its shape: a score in three bands — **execute** above 0.80,
**confirm** between 0.55 and 0.80, **compile** below 0.55, where compiling means
asking the cloud author for a new tile instead of playing the closest wrong
one.

## 2. The hypothesis

> A retrieval front in front of the bandit, with pincher's bands, beats the
> bandit on the tiles acceptance rig: it covers ≥ 30 % of contexts, its reward
> is within ε of the bandit's, and p95 is under 50 ms — and the propensity
> that makes it weighable survives the narrowing.

## 3. The setup

- `core/tiles/retrieval.py` — the front, the index, the embedders, the chooser
  that wraps another chooser.
- `core/tiles/bands.py` — the three bands, held by `core.hysteresis`'s gate.
- `core/tiles/nail.py` — the content-addressed export.
- `tests/tiles/test_retrieval.py`, `test_bands.py`,
  `test_retrieval_propensities.py`, `test_nail.py` — 55 tests, no network, no
  GPU.
- `docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py` — prints every
  number below.

**The rig is the acceptance rig's own, not a copy of its shape.** The harness
uses the acceptance run's `ScriptedAuthor`, the same specs, the same request,
the same registry, the same `contexts(600, 17)` and the same
`(tile, bucket, play index)` sha256 draw. **The bandit arm therefore
reproduces the published acceptance figure exactly — 479/600 = 0.7983** — which
is the check that the rig is the rig and not a rig that merely looks like it.
Every arm plays the identical game, so a difference between arms is a
difference between the policies and not between the luck.

| | |
|---|---|
| Machine | **the ProArt** — AMD Ryzen AI 9 HX 370 w/ Radeon 890M, 24 cores, 6.5 GB available, load1 0.41, WSL2 Linux 6.18.54.1 |
| **Not** | the Thor. Nothing here needs the box: it is numpy on a seeded world. The acceptance run on the box is still yours. |
| Python / numpy | 3.14.4 / 2.5.4 (model2vec 0.10.0) |
| Embedder (main run) | `minishlab/potion-base-8M`, **MIT**, 256 dimensions, CPU, static |
| Embedder (floor run) | feature hashing, 4096 buckets, no model, no licence |
| Plays | 600 per arm, five arms |
| Shortlist K | 3 |

**The embedder's licence was checked, not assumed** (`MODEL_LICENCES` in
`core/tiles/retrieval.py`): model2vec is MIT, `potion-base-8M` is MIT, and a
model that is not on that list is reported as *unchecked* rather than free.
The embedder's record — kind, model, licence, dimensions — travels with every
number the front produces, because a similarity of 0.62 means one thing under
one model and another thing under another.

## 4. The gap: the chooser could not find, and the log could not weigh it

Two things were missing before this seat, and they are the same kind of thing.

**The chooser could only choose.** Its estimate is one number per (bucket,
tile), so the quality of its choice depends entirely on the pool it was
handed. Nothing in the seat could say "the tiles that mean *crates that read
weathered* are these three". The front is that thing, and it is deliberately
not a chooser: it narrows the pool and hands the decision on.

**The log could not weigh a narrowed choice.** The estimators in
`core.tiles.ope` need `pi_target(action) / pi_logging(action)`, and the
denominator is a number about the *whole* policy that made the choice. Once
two mechanisms make a choice — the front proposes, the bandit disposes — the
denominator is the **product** of both draws, not the bandit's own number
measured over a shortlist. And the shortlist has to travel with the record, or
a target policy normalises over the wrong set.

That is why `Choice` gained a `candidates` field and `PlayRecord` already had
one: the shortlist is the set the propensity was measured over.

## 5. The numbers

### 5.1 The arms

Five arms, the same 600 contexts, the same seeded game. The last one is the
reference: a policy that always plays a tile of the requested style, which is
the best *class* of policy the game allows (it pays 0.85 for a match and 0.15
for a miss). It is not a ceiling — it always plays the *first* matching tile,
and the two matching tiles have different draws, so it is one draw of that
class.

| arm | wins / plays | win rate | 95 % CI | against the bandit |
|---|---|---|---|---|
| bandit (from zero) | 479 / 600 | 0.7983 | [0.7644, 0.8285] | — |
| **retrieval-only** (pincher's similarity pick) | **504 / 600** | **0.8400** | [0.8085, 0.8672] | **+0.0417**, CI [−0.0019, +0.0851], p = 0.0608 |
| retrieval-bandit (retrieve K = 3, then choose) | 493 / 600 | 0.8217 | [0.7890, 0.8502] | +0.0233, CI [−0.0211, +0.0677], p = 0.3029 |
| fastpath (τ = 0.42, calibrated) | 486 / 600 | 0.8100 | [0.7767, 0.8394] | +0.0117, CI [−0.0333, +0.0566], p = 0.6106 |
| always-matching (the reference) | 503 / 600 | 0.8383 | [0.8067, 0.8656] | +0.0400, CI [−0.0037, +0.0836], p = 0.0724 |

**Two readings, and the second one is the careful one.**

1. **The front reaches the top of the range.** Its top-1 was the tile whose
   style the context asked for in **600 of 600** contexts, with no learning at
   all, and it landed on the always-matching reference (504 against 503). The
   front is not *nearly* as good as a perfect policy on this rig; it is at it.
2. **The rig cannot resolve whether that is worth +0.04.** The retrieval
   arm's advantage over the bandit is +0.0417 with p = 0.0608, and the
   **always-matching reference itself** — a policy that cannot do better — is
   +0.0400 with p = 0.0724. **Even a perfect policy is not significantly
   better than the learner on 600 plays of this game.** So the honest claim is
   the mechanism's ("the front plays a matching tile on every context, at the
   reference's level"), and the value of that over the learner is +0.04 with
   an interval that just includes zero. Reading it as a *significant win*
   would be reading more out of the rig than the rig carries.

### 5.2 The cold start is what the front removes

Win rate by 50 plays (600 plays, twelve buckets):

```
bandit            0.66 0.78 0.76 0.86 0.76 0.82 0.82 0.68 0.88 0.82 0.78 0.96
retrieval-only    0.84 0.86 0.80 0.76 0.82 0.82 0.88 0.82 0.92 0.84 0.76 0.96
retrieval-bandit  0.74 0.82 0.80 0.86 0.74 0.82 0.86 0.74 0.90 0.84 0.78 0.96
fastpath          0.64 0.82 0.78 0.76 0.80 0.82 0.86 0.76 0.92 0.84 0.76 0.96
always-matching   0.84 0.90 0.86 0.92 0.86 0.78 0.76 0.72 0.86 0.78 0.88 0.90
```

The bandit opens at 0.66 and the front at 0.84, and by the last bucket they are
both at 0.96. **The difference is entirely in the first half of the night** —
which is the part where a builder is watching, and the part the front
changes. The learning is not slower; it is *later*, because the front has
already answered the question the learner would have spent its first hundred
plays on.

### 5.3 E1's three bars

**At pincher's thresholds** (execute at ≥ 0.80, compile below 0.55):

| bar | measured | verdict |
|---|---|---|
| coverage ≥ 30 % | **0.0000** | **FAIL** — the fast path never fires |
| reward within ε = 0.02 of the bandit | +0.0000, CI [−0.0454, +0.0454], p = 1.0000 | pass, vacuously |
| p95 < 50 ms | 0.127 ms | pass |

**At the calibrated execute line** (τ = 0.42):

| bar | measured | verdict |
|---|---|---|
| coverage ≥ 30 % | **0.3333** | pass |
| reward within ε = 0.02 of the bandit | **+0.0117**, CI [−0.0333, +0.0566], p = 0.6106 | pass |
| p95 < 50 ms | **0.124 ms** | pass |

**How the threshold was calibrated, so it cannot be accused of fitting the
answer:** τ_hi is the **most selective** threshold whose coverage still
reaches E1's own 30 % bar — it is read off the sweep, not off the win rate.
τ_lo is the median score of a tile that does *not* match the context (0.2699):
below it the front cannot tell the two apart.

### 5.4 The thresholds do not transfer, and the sweep says why

The offline τ sweep (computed from the recorded scores, so it can be re-read
without running anything; the static run):

| τ | coverage | win rate | agreement with the bandit |
|---|---|---|---|
| 0.20 | 1.0000 | 0.8400 | 0.6433 |
| 0.30 | 1.0000 | 0.8400 | 0.6433 |
| 0.35 | 0.6667 | 0.8233 | 0.6717 |
| 0.40 | 0.3333 | 0.8100 | 0.6883 |
| 0.45 | 0.0000 | 0.7983 | 1.0000 |
| 0.80 (pincher) | 0.0000 | 0.7983 | 1.0000 |

**The whole dynamic range of the score is between 0.33 and 0.43.** The
matching tile's score: p10 0.3230, median 0.3847, p90 0.4263. The mismatching
tile's: p10 0.2482, median 0.2699, p90 0.3328. Pincher's 0.80 is not a line
near the top of our range; it is a line above the whole range.

This is the finding the D1 seed warned about — *"the bands (0.80 / 0.55) are
pincher's defaults, not ours"* — and it is now a measurement rather than a
caution. **The band's mechanism is a mechanism; its numbers are a calibration
of one embedding space and have to be re-derived per space.** `BandConfig` is
a parameter for exactly that reason, and this note is the derivation for ours.

### 5.5 What the three bands do

The band distribution over the rig's 600 contexts:

| thresholds | execute | confirm | compile |
|---|---|---|---|
| pincher's (0.80 / 0.55) | 0.0 % | 0.0 % | **100 %** |
| calibrated (0.42 / 0.2699) | 33.3 % | 66.7 % | 0.0 % |

At pincher's thresholds the band says "the library has nothing for this" about
every single context — the library would never have played at all. At the
calibrated thresholds a third of the contexts are executed outright, two thirds
are confirmed, and none are compiled. **The mechanism only has to be
re-calibrated once; after that it does the thing it was built for.**

The compile band is the one with teeth: below τ_lo **nothing is played** and a
request goes to the cloud author for a new tile. The band is not a score to
report — it is a decision about whether the library has an answer.

### 5.6 The fast path costs nothing

Per play, on the ProArt, with the static model loaded:

| arm | p50 | p90 | p95 | max |
|---|---|---|---|---|
| retrieval-only | 0.071 ms | 0.145 ms | 0.160 ms | 0.618 ms |
| retrieval-bandit | 0.081 ms | 0.164 ms | 0.176 ms | 0.308 ms |
| fastpath | 0.048 ms | 0.081 ms | **0.123 ms** | 0.409 ms |

E1's bar is 50 ms; the fast path is **0.12 ms** at p95, more than two orders
of magnitude inside it. A static embedding model is a token table and a
tokenizer — a query is one matrix lookup per token, with no forward pass — so
the whole cost of the front is the dot products over the library. With the
hashing floor it is **0.031 ms** at p95, four times faster and with no model
at all.

### 5.7 The propensity survives the narrowing

| arm | plays with a propensity | min | max |
|---|---|---|---|
| bandit | 600 | 0.003333 | 0.983333 |
| retrieval-bandit | 600 | 0.006667 | 0.986667 |

The front's arm's propensities are *smaller* than the bandit's, and that is
the point: the inner chooser inside a shortlist of three explores at ε/3
rather than ε/6, so its greedy pick is less certain — (1 − ε) + ε/3 — and the
number on the record is that number. The **whole policy's** probability is the
front's draw (1.0 for a tile it returned) times the inner chooser's draw over
the shortlist. Recording only the inner number would have made the weights
too large, and the estimates too confident.

### 5.8 The log alone: the estimators' reading of the frozen policies

The policy-swap question, answered from the bandit's log and nothing else.
The targets are **frozen** policies (the retrieval pick; the fast path falling
back to the band's *final* argmax), and the truth is the direct replay of the
same frozen policy over the same 600 contexts.

| target | direct replay | IPS | SNIPS | effective n | max weight | support |
|---|---|---|---|---|---|---|
| retrieval-only | 0.8400 | 1.1112 | 0.7115 | 15.3 | 210.3 | 0.64 |
| fastpath | 0.8400 | 1.1112 | 0.7115 | 15.3 | 210.3 | 0.64 |

(On this rig the two frozen policies are the same policy: the band's final
argmax is also the tile the front returns, so the fast path's fallback never
fires and the two rows are one measurement.)

**Three things to read here.**

1. **SNIPS is inside its interval and IPS is not.** SNIPS 0.7115 with the
   interval [0.3908, 1.0000] covers the direct 0.8400 — a wide interval, but
   an honest one. IPS leaves the reward range entirely (1.1112, above what
   any play could pay) and the estimator says so in its own warnings. The
   same finding as the OPE note's, on a different log: the self-normalised
   estimator forgives what plain IPS does not.
2. **The support is the story.** The retrieval-only target is supported on
   64 % of the log's plays and the effective sample size is **15.3 of 600** —
   one or two plays are carrying the estimate, and the largest weight is 210.
   **The narrow, deterministic policy is the hard one to weigh**, because the
   logger rarely agrees with it and the disagreement plays carry the whole
   weight. The hashing floor's log is better supported (effective n 44.9,
   largest weight 49.1) because the front's pick agrees with the logger more
   often.
3. **The gap between the estimate and the truth is a quantity the log cannot
   recover.** On the plays where the logger and the target disagree, the log
   holds the *logger's* outcome, not the target's. No estimator can invent the
   missing one. The rig can, because its game is a seeded function — which is
   why this rig answers E1 exactly and a real night can only estimate it.

### 5.9 The paraphrase probe: where the rig cannot see

The rig's task is **lexical** — the context says "wanted_style: weathered" and
the tile says "weathered" — so the front's top-1 was right in 600 of 600
contexts and the rig cannot show the difference between an embedder that
matches words and one that matches meaning. A probe asks the front for a
paraphrase instead, and measures the **margin**: the best matching-style
candidate's score minus the best mismatching candidate's.

| embedder | literal requests | paraphrases |
|---|---|---|
| static (`potion-base-8M`, MIT) | 3 of 3 on top, mean margin **+0.0914** | 1 of 3 on top, mean margin **+0.0247** |
| hashing floor (no model) | 3 of 3 on top, mean margin **+0.1759** | 0 of 3 on top, mean margin **0.0000** |

**On the rig's own requests the fallback is sharper** (+0.1759 against
+0.0914) and free — no model, no licence, no download, and 0.031 ms against
0.123 ms at p95. **On a paraphrase the fallback has no signal at all**: its
margin is exactly zero, because the query shares no word with any tile and
every tile scores the same. The static model is the only one of the two that
separates anything there, and it separates one of the three.

So the choice is not "the model is better". It is: the floor is enough when
the request and the tile share words, and only the model survives the request
being phrased differently — and on this rig's three paraphrases it survives
one. **The model is not yet earning its extra 0.09 ms; the rig is not the
place that would show it.** A larger, more varied tile library and real
requests are the experiment that would settle it, and this note does not
settle it.

## 6. What this does not say

- **It is a six-tile rig.** The whole library is two tiles per style, and the
  request names the style. The front's 600-of-600 says the mechanism works,
  not that it works on a library of six hundred tiles with overlapping
  families.
- **The rig cannot resolve +0.04.** Even the always-matching reference is only
  p = 0.0724 against the learner at 600 plays. The interval on the front's
  advantage is [−0.0019, +0.0851]. **More plays would be needed to say the
  front is better, and this rig does not have them.**
- **The thresholds are ours for this embedder and this rig.** 0.42 and 0.2699
  are readings off these scores. A different library, a different embedder or
  a different request wording moves them, and nothing here says they would
  not.
- **The estimator's support is thin.** Effective n of 15.3 and a largest weight
  of 210 on 600 plays: the SNIPS number is real but it is carried by a few
  plays, and the interval is wide enough to be nearly useless on its own. A
  real night's log would be bigger; a real night's log would also have a
  policy that changed under it, which this rig does not model.
- **The rig's game is deterministic in the tile.** The OPE gap in §5.8 is
  partly a property of that (the reward realisation is tied to the action, so
  the log's replay is exact); a live world draws the reward afresh.
- **The front narrows the pool, so it also narrows what can be learned.** A
  tile the front never returns is never played and never learned from. The
  cost is not visible on this rig, where the front was right every time; on a
  library where it is sometimes wrong, the same narrowing would starve the
  tiles it needs to learn about. **K is the knob and it was not swept here.**
- **Nothing was run on the Thor.** The seat is CPU-only and the rig is
  arithmetic on a seeded world; the acceptance run on the box is still yours.

## 7. Reproducing it

```bash
cd ~/lm-wt/tiles-retrieval
.venv/bin/python -m pytest -q tests/tiles/test_retrieval.py tests/tiles/test_bands.py \
    tests/tiles/test_retrieval_propensities.py tests/tiles/test_nail.py   # 55 tests
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py \
    --embedder hashing --out docs/lab/tiles-retrieval-scripts/results/tiles-retrieval-e1-hashing.json
```

Every number in §5 comes out of that script. The results land in
`docs/lab/tiles-retrieval-scripts/results/` as JSON, with the box state
beside them.
