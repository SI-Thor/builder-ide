# EXP — the judge's confidence, on one definition, measured against the Brier score

**Date:** 2026-10-31 (the judge-calibration seat; **CPU-only, no GPU, no
server, no cloud key** — every vector below is a *recorded* probability
vector, replayed from disk). **Continued 2026-11-01:** the bootstrap
intervals (§5.1, §5.2) and the τ-gate analysis (§6) were added, and every
number was re-measured on that day — the re-measurement reproduces the
2026-10-31 numbers exactly, so nothing below moved.
**Verdict: ONE DEFINITION OF CONFIDENCE IS NECESSARY AND NOT SUFFICIENT.
MEASURED ON 1,470 RECORDED JUDGMENTS, THE CANONICAL DEFINITION (THE TOP
PROBABILITY) MAKES TWO CELLS' CONFIDENCE **ANTI-CORRELATED** WITH BEING
RIGHT (AUC 0.2815 [0.2167, 0.3474] AND 0.2944 [0.2255, 0.3652] — BOTH
INTERVALS BELOW THE COIN-FLIP LINE, SO THE INVERSION IS THE CELL'S AND NOT
A SMALL SAMPLE'S NOISE — THE MORE SURE THE MODEL IS, THE MORE OFTEN IT IS
WRONG), MAKES A THIRD CARRY NO SIGNAL AT ALL (AUC 0.5115 [0.4364, 0.5836],
AND THE ONLY τ THAT CATCHES EVERY ERROR ESCALATES EVERY GOOD ONE), AND MAKES
A FOURTH SEPARATE CLEANLY (AUC 1.0000). THE RECALIBRATION WORKS WHERE THE
SIGNAL IS THERE — TEN OF ELEVEN CELLS KEEP A SCALE THAT IMPROVES THE
HELD-OUT BRIER, AND THE PAIRED BOOTSTRAP SAYS WHICH OF THOSE GAINS ARE
ESTABLISHED — BUT A CALIBRATED τ IS STILL READ IN THE CALIBRATED SPACE, AND
ON A BINARY THE RAW FLOOR IT ASKS FOR IS NEVER BELOW A HALF. AND ON THE
LEAKY SEA-STATE TASK THE τ GATE'S SIGN IS WRONG: ITS ESCALATIONS LAND ON
THE RIGHT ANSWERS AND ITS ACTS ON THE WRONG ONES (§6).**

---

## 1. The idea

The seed bank (#2, B15): **measure whether the small model's confidence is
honest, and retune when it drifts.** The seed's kernel is that the drift
thresholds in the sources are invented and nobody says what is retuned.

The seed also names the thing that had to be fixed first: **the three d1
sizes report "confidence" by three different formulas**, so a threshold on
confidence is not the same quantity from one model to the next, and any
cross-model confidence column compares a margin against a probability.

So the work is in three parts, and this note reports all three:

1. **one definition of confidence**, computed the same way for every
   backend from the distribution the backend returned, with the row saying
   which definition it used;
2. **the calibration tracked against it** — the Brier score, the expected
   calibration error over reliability bins, the reliability curve and the
   escalation sweep, per (backend, model, task);
3. **recalibration as a parameter** — a temperature or an isotonic map
   fitted on one split of the outcomes and read on another, kept only when
   it improves the held-out Brier, with the gate's τ read in the
   calibrated space.

## 2. The hypothesis

> The confidence the backends report can be re-scored under one definition
> from the vectors they already returned; the Brier score and the expected
> calibration error then say, per (backend, model, task), whether the
> number means anything — and where it does not, no threshold on it can
> fire the right number of escalations, so the router has to be driven by
> something else.

The seed's own kill condition is written into the hypothesis: *"if no
definition separates correct from incorrect at any threshold, the
confidence carries no signal in any form and the router must use model
disagreement or the bandit's estimate instead."*

**The hypothesis is half wrong, and the half that is wrong is the
interesting half.** It assumed the confidence would be *uncalibrated* — too
high, too low, or uninformative. On two of the cells it is the opposite:
it is **inverted**, and it is inverted for a reason the reliability curve
shows bin by bin.

## 3. The data, and the setup

**No new model runs.** The seed's promise was that the endpoint already
returned the full probability vector, so the same week of logs can be
re-scored. Everything here is a replay of recorded vectors.

| data | what it is | n |
|---|---|---|
| the liquid study's d1-2B traces | five-way sea-state task, recorded on the Thor 2026-10-31 (`exp_c_trace_d1-2B.json`) | 240 |
| the liquid study's d1-3B traces | the same task on the 3B (`exp_c_trace_d1-3B.json`) | 240 |
| the tiles rig, judge-only arm | 600 plays of the acceptance rig's simulated game with the judge's distribution over the six tiles (`judge-tiles-coldstart.json`) | 428 |
| the clef cascade's teacher | 200 cases of raw vectors over the scene, defect and tile questions (`c3-calibration-runs.json`) | 460 |
| the clef cascade's student | clef-flash's baseline harness on the two boolean questions, labelled by the teacher | 122 |

**The tiles rig's outcomes are replayed, not copied.** That arm wrote its
distributions but not its play rows, so the outcome is recomputed from the
rig's own seeded draw — `sha256(tile|bucket|play_index)` against the
match/miss chance of the tile's style against the context's wanted style.
The replay is exact (the draw is a hash, not a random number) and it
reproduces the rig's published win rate: the judge-only arm won 0.6900
over its 600 plays and the replay wins 0.6900 as well.

**A judgment is scored by the play that answers it.** A surfaced judgment
(below τ) fell back to a seeded uniform pick, so that play is not the
judgment's answer and does not score it: 400 acted, 172 of the 200
surfaced plays were of another tile, and 428 judgments are scored.

**The ground truth is the cascade's own.** The clef cases are rebuilt from
`cascade.build_all(80, 60, 60)` — all 200 case ids match the recorded run
— so the truth is the truth the teacher saw, not a re-derivation.

### The box the numbers were measured on

| | |
|---|---|
| machine | the ProArt (the laptop): AMD Ryzen AI 9 HX 370, 24 cores, 15 GiB RAM |
| GPU | RTX 4050 Laptop (6,141 MiB) — **not used**, no model was run |
| kernel | Linux 6.18.54.1-microsoft-standard-WSL2 (WSL2) |
| python / numpy | 3.14.4 / 2.5.4 |
| git | `b3bb9e0` (the branch `judge-calibration`) — the intervals were added and every number re-measured at `3ed1f6f`, with identical results |
| GPU-resident | none; the vectors are replayed from disk |

The **recordings** were made elsewhere and their own box state is in their
own files: the liquid traces on the Thor (2026-10-31 14:16, GPU 53.7 °C,
28.3 GB of 125.7 GB used, `exp_c_hysteresis_d1-2B.json`'s `box_at_start`);
the tiles rig on the Thor (GPU 40.8 °C → 45.5 °C, 25.9 GB used, server
peak RSS 774.7 MB, 0.424 GPU-minutes); the clef runs on Cloudflare's
Workers AI (6,778.97 neurons, $0.0746, 107.9 s wall for the teacher's
200 cases).

## 4. The mechanisms

### 4.1 One definition, and the three formulas, measured

`core/judge/calibration.py` computes the confidence from the distribution
the backend returned, the same way for every backend:

| definition | formula | what it is |
|---|---|---|
| `top_probability` | `p_max` | the probability the backend gave its own answer |
| `normalised_margin` | `(p_max − 1/K) / (1 − 1/K)` | the LFM2 formula |
| `entropy_normalised` | `1 − H(p) / log K` | one on a point mass, zero on the uniform |

**The canonical one is `top_probability`**, for three reasons that are
mechanisms rather than tastes: it is a probability *of the answer*, so a τ
on it reads "act when the backend's own answer holds at least this much";
it is the number the existing measurements are in (E1's τ = 0.5 was
measured on the d1-2B's `max(probs)`), so the default keeps its meaning;
and it is the quantity the Brier score is computed against.

The seed's claim is not a matter of opinion here — it is measurable on the
recorded vectors:

| model | the reported confidence is | matches | reported mean | canonical mean |
|---|---|---|---|---|
| d1-2B | `top_probability` | **240 / 240** | 0.7478 | 0.7478 |
| d1-3B | `normalised_margin` | **240 / 240** | 0.7252 | 0.7802 |

So **the same τ = 0.5 is not the same gate on the two models.** Measured
on the cells' own distributions, a τ of 0.5 means "top probability ≥ 0.5"
on the 2B and "top probability ≥ **0.6000**" on the 3B (the margin
formula's own arithmetic: `1/5 + 0.5 × 4/5 = 0.6`). At τ = 0.7 the two
are 0.7000 and 0.7600. A cross-model confidence column was comparing a
probability against a margin, and a threshold set on one was a different
threshold on the other.

Every `judge.verdict` row now carries `confidence_definition` — the one
the row's confidences were computed under — and the backend's own number
rides beside it as `backend_confidence`, because the edge between the two
is worth having on the log.

### 4.2 The metrics, and what each one can and cannot say

Per (backend, model, task) cell:

* **accuracy** — the share of judgments whose argmax was right;
* **Brier score** — `(1/K)·Σ_i (p_i − y_i)²`, averaged. It is computed over
  the **whole vector**, so it does not depend on the confidence definition
  at all (the tables below show the same Brier under all three). Dividing
  by K puts cells with different option counts on one scale;
* **expected calibration error** — over equal-width reliability bins:
  `Σ_b (n_b/N)·|accuracy_b − mean_confidence_b|`. This one *does* depend
  on the definition;
* **the reliability curve** — per bin: n, mean confidence, accuracy, gap;
* **the escalation sweep** — at each τ: the act rate, the share of the
  **wrong** judgments the gate would have caught (its job) and the share of
  the **right** ones it would have taxed (its cost).

The **AUC** — the confidence's ability to put the right judgments above
the wrong ones — is the number the seed's question turns on, and it is
not part of the calibration machinery: it is the measure of whether there
is anything to calibrate.

### 4.3 Recalibration as a parameter

A **scale** is a map from the raw distribution to a calibrated one. Two are
fitted per cell:

* **temperature** (`p'_i ∝ p_i^(1/T)`), one number, fitted by minimising the
  Brier score with a golden-section search on log T;
* **isotonic** (the pool-adjacent-violators fit of confidence → accuracy),
  which keeps the distribution's ranking: the top option's mass becomes
  the calibrated value and the rest keeps its relative shares, because a
  ranking error is not a calibration error.

Both are fitted on the **older half** of the cell's outcomes and scored on
the **newer half**, and the split is **time-ordered**: the cell's judgments
are kept in the order the recording made them and the cut is a prefix/suffix
cut, so the half that was fitted always *precedes* the half that is scored —
a calibration fitted on the future describes nothing about the past. (The
recordings carry no wall-clock timestamps: the order is the recording's own
— the trace's step order, the rig's play order, the cascade's case order —
and every number in the tables below is scored on the half that came after
the half it was fitted on.) A scale is **kept only if it improves
the held-out Brier score**; otherwise the raw confidence stands and the
report says so.

Where a scale is fitted, the judge computes the calibrated confidence as
well and **the gate reads that one**, so τ is read in the calibrated space:
*act when the calibrated probability of being right is at least τ*.
`raw_floor_for()` turns that into a number an operator can set — the raw
confidence that has to clear a calibrated τ, for a reference shape.

### 4.4 The paired gate, and which half of it this is

The keep rule is the cascade's, unchanged in shape. There the teacher
labelled every case once and the student was scored against it — a
**paired** score — and the harness's rule was *"keep the edit only if the
paired score improves; otherwise revert"*. Here the pairing is the same
shape (the outcomes the cell's judgments are scored against are held out
from the fit) and the score is the proper scoring rule, the Brier score,
because it is the only one of the two that is a proper scoring rule at
all.

But the cascade's paired gate has **two halves**, and this is the first:

* the **value half** — a map that says how confident the model should be
  (the Platt map there, the temperature and the isotonic map here). The
  isotonic map here is built never to change the answer: the top option's
  mass becomes the calibrated value and the rest keep their relative
  shares, because a ranking error is not a calibration error;
* the **ranking half** — an additive prior on the options, for the cells
  whose error is a *ranking* error. The cascade found the value map could
  not help its multiple-choice cells for exactly this reason: "per-question
  calibration helps the booleans; it cannot help the multiple-choice
  questions, where the error is a ranking error and needs an additive
  prior on the options."

**Only the value half is built here**, and the measurement says why the
other half would be needed. On the clef `tile` cell the confidence orders
the outcomes weakly (AUC 0.6149) while the model picks the wrong tile
41.7 % of the time: the recalibration improves that cell's Brier (0.1199
→ 0.1084) and leaves its **accuracy exactly where it was** (0.5667 →
0.5667 on the held-out half), because no value map can move a ranking.
The same is true of the teacher's `beacon_bearing` cell (accuracy 0.8875,
AUC 0.7480) — the map sharpens the confidence, it does not turn the
bearing. And the accuracy column does not move **in any of the eleven
cells**: that is the property that makes this the value half.

So the honest reading of this seat's result is: **the value half is
measured, and the cells whose error is a ranking error are named by the
measurement rather than fixed by it.** The ranking half is the next piece
of work, and it is the cascade's choice prior, not a new invention.

### 4.5 The drift rule, and why it has no invented threshold

The seed's kernel is that the drift thresholds in the sources are
invented. So the drift here is three **measured** facts, compared against
the cell's own history:

1. **separability lost** — the newest window's AUC has *fallen* to the
   coin-flip line (the previous window has to have been above it: a cell
   whose confidence never varied has not drifted, it has never separated);
2. **calibration moved** — the newest window's ECE is further from the
   previous one's than any window-to-window move this cell has made
   before (the noise floor is the cell's own history, so the first window
   cannot declare drift);
3. **the recalibration went stale** — a scale fitted on the previous
   window no longer improves the newest one. A scale that changes nothing
   (T = 1, an identity isotonic map) cannot go stale: it was never a
   recalibration.

What is retuned is stated with the line: the cell's recalibration is
refitted on the newest outcomes, and the gate's τ is read from it again.

## 5. The numbers

### 5.1 Before the recalibration

| cell | n | accuracy | Brier | ECE | mean confidence | AUC |
|---|---|---|---|---|---|---|
| d1-2B · liquid trace | 240 | 0.5250 | 0.1699 | 0.3438 | 0.7478 | **0.2815** |
| d1-3B · liquid trace | 240 | 0.3292 | 0.2135 | 0.4682 | 0.7802 | **0.2944** |
| tiles rig · judge-only | 428 | 0.8458 | 0.0647 | 0.2803 | 0.5654 | **0.5115** |
| clef teacher · scene.enemy_visible | 80 | 1.0000 | 0.0005 | 0.0172 | 0.9828 | — |
| clef teacher · scene.action | 80 | 1.0000 | 0.0070 | 0.0660 | 0.9340 | — |
| clef teacher · scene.beacon_bearing | 80 | 0.8875 | 0.0487 | 0.0657 | 0.8918 | 0.7480 |
| clef teacher · scene.beacon_reachable | 80 | 1.0000 | 0.0021 | 0.0398 | 0.9602 | — |
| clef teacher · defect.defect_class | 60 | 0.9833 | 0.0140 | 0.2768 | 0.7197 | 1.0000 |
| clef teacher · tile.tile | 60 | 0.5833 | 0.1185 | 0.1802 | 0.7305 | 0.6149 |
| clef student · scene.enemy_visible | 61 | 1.0000 | 0.0160 | 0.0785 | 0.9215 | — |
| clef student · scene.beacon_reachable | 61 | 1.0000 | 0.0470 | 0.2089 | 0.7911 | — |

An AUC of "—" means the cell has no wrong judgment to order against
(accuracy 1.0000), so there is nothing for a threshold to catch.

**The AUCs carry error bars.** A separability measured on 240 judgments is
a number with a spread, and the spread is what says whether the number is
worth reading. The bootstrap resamples the **judgments** (2,000 draws,
seeded, so the interval repeats): the d1-2B's AUC is 0.2815 with a 95 %
interval of **[0.2167, 0.3474]** and the d1-3B's is 0.2944 with
**[0.2255, 0.3652]** — **both intervals lie entirely below a half**, so
the anti-correlation is a property of these cells and not the noise of a
small sample. The tiles rig's AUC of 0.5115 has the interval
**[0.4364, 0.5836]**, which **straddles** the coin-flip line: "no signal
here" is what the data says, and "a little signal" is what the data does
not say. The teacher's `beacon_bearing` cell, at 0.7480
[0.5957, 0.8715], is above the line for the whole interval, and
`defect_class` is at 1.0000 [1.0000, 1.0000]. The teacher's `tile.tile`
cell, at 0.6149 [0.4630, 0.7557], straddles it — a weak signal, not a
measured one.

### 5.2 Before and after, on the same judgments

The two halves of the measurement on **one basis**: every row below is the
cell's **held-out half** (the newer half, the one the scale never saw),
scored twice — once with the raw confidence and once with the scale — so
the numbers are comparable. The cell-wide numbers of §5.1 are the cells as
they are; these are the same cells on the half that is scored.

| cell | scale | kept | accuracy | Brier | ECE | the Brier's improvement, 95 % |
|---|---|---|---|---|---|---|
| d1-2B · liquid trace | isotonic | yes | 0.5583 → 0.5583 | 0.1588 → **0.1355** | 0.3198 → 0.0364 | **+0.0233** [+0.0086, +0.0387] |
| d1-3B · liquid trace | isotonic | yes | 0.3750 → 0.3750 | 0.2018 → **0.1437** | 0.4633 → 0.3332 | **+0.0580** [+0.0285, +0.0857] |
| tiles rig · judge-only | temperature (T = 0.1723) | yes | 0.8224 → 0.8224 | 0.0647 → **0.0499** | 0.2535 → 0.0841 | **+0.0148** [+0.0041, +0.0238] |
| clef teacher · scene.enemy_visible | isotonic | yes | 1.0000 → 1.0000 | 0.0008 → **0.0000** | 0.0189 → 0.0000 | +0.0008 [+0.0002, +0.0019] |
| clef teacher · scene.action | isotonic | yes | 1.0000 → 1.0000 | 0.0089 → **0.0000** | 0.0747 → 0.0000 | +0.0089 [+0.0038, +0.0145] |
| clef teacher · scene.beacon_bearing | isotonic | **no** | 0.9250 → 0.9250 | 0.0327 → 0.0359 | 0.0639 → 0.0894 | −0.0032 [−0.0104, +0.0055] |
| clef teacher · scene.beacon_reachable | isotonic | yes | 1.0000 → 1.0000 | 0.0022 → **0.0000** | 0.0404 → 0.0000 | +0.0022 [+0.0014, +0.0032] |
| clef teacher · defect.defect_class | temperature (T = 0.05) | yes | 0.9667 → 0.9667 | 0.0241 → **0.0057** | 0.4344 → 0.0309 | **+0.0183** [+0.0072, +0.0246] |
| clef teacher · tile.tile | isotonic | yes | 0.5667 → 0.5667 | 0.1199 → **0.1084** | 0.2128 → 0.1026 | +0.0116 [−0.0042, +0.0269] |
| clef student · scene.enemy_visible | isotonic | yes | 1.0000 → 1.0000 | 0.0160 → **0.0000** | 0.0704 → 0.0000 | +0.0160 [+0.0025, +0.0355] |
| clef student · scene.beacon_reachable | isotonic | yes | 1.0000 → 1.0000 | 0.0448 → **0.0000** | 0.2054 → 0.0000 | **+0.0448** [+0.0372, +0.0530] |

The last column is the **paired** bootstrap of the improvement: the same
judgments scored with and without the scale, so every draw is the
*difference* of two means over one resample of the judgments (2,000
draws, seeded). Positive means the recalibration helped. An interval in
**bold** excludes zero.

**Two of the intervals change what the tables can claim.** The teacher's
`tile.tile` cell keeps its isotonic map by the rule — the held-out Brier
improved — but the improvement's interval **[−0.0042, +0.0269] straddles
zero**: on 30 held-out judgments the improvement is *not* established, and
the table's `0.1199 → 0.1084` is a point estimate with that spread behind
it. The same is true, more weakly, of the `beacon_bearing` cell that was
dropped. The other **nine** kept cells' improvements are established: their
intervals exclude zero, and the two liquid-trace cells and the tiles rig are
among them (+0.0233 [+0.0086, +0.0387], +0.0580 [+0.0285, +0.0857] and
+0.0148 [+0.0041, +0.0238]). So the keep rule and the interval agree on ten
of the eleven cells, and the one they disagree on is the cell with the
fewest held-out judgments.

**The accuracy column does not move, in any cell, by any amount.** That
is the property that makes this the *value* half of the cascade's paired
gate: a map that never changes the answer can only say how sure to be
about the answer it already gave. The Brier and the ECE move; the
accuracy does not.

**Ten of the eleven cells keep a scale; one drops it.** The drop is the
rule working: the teacher's `beacon_bearing` cell is the one whose
confidence carries signal (AUC 0.7480) and the one where a fitted map
fitted on the older half made the newer half *worse* — so the raw
confidence stands and the report says so.

Two of the numbers deserve to be read carefully rather than skimmed:

* **the teacher's `defect_class` temperature is 0.05**, the bottom of the
  search range. The Brier score of a cell that is right 98.3 % of the time
  is minimised by a degenerate map — a distribution pushed onto its argmax
  — so the Brier alone cannot pick the operating point. The scale is
  bounded by its search range, and a scale at the bound is a signal to look
  at the cell rather than to trust the fit.
* **the Brier and the ECE can disagree.** On the d1-3B the Brier improves
  (0.2018 → 0.1437) while the ECE improves less (0.4633 → 0.3332) and
  stays high; on `beacon_bearing` the recalibration improves neither. The
  Brier is the rule the scale is kept by, because it is the proper scoring
  rule and it is what the outcome supports — but the ECE is the number a
  reader of the reliability curve should look at.

### 5.3 The threshold, read in the calibrated space

`raw_floor_for()` answers the operator's question — *if τ is set in the
calibrated space, what raw number has to clear it?*

| cell | scale | raw floor for a calibrated τ of 0.5 | 0.6 | 0.7 |
|---|---|---|---|---|
| tiles rig · judge-only | temperature 0.1723 | **0.2749** | 0.2891 | 0.3050 |
| d1-2B · liquid trace | isotonic | 0.5242 | 1.0000 | 1.0000 |
| clef teacher · scene.action | isotonic | 0.3724 | 0.3724 | 0.3724 |
| clef teacher · tile.tile | isotonic | 0.7738 | 0.7742 | 0.8817 |

The tiles rig's temperature is 0.1723 because that cell is *under*-confident
(claims 0.5654, is right 0.8458), so the calibrated space is sharper and
the raw floor moves **down** — a gate at a raw 0.28 is a calibrated 0.5.

And the fact that constrains all of it: **on a binary question the raw
floor can never be below a half.** One of two options always holds at
least half the mass, so the confidence — the probability of the answer —
is never below 0.5, and **a gate at τ = 0.5 on a binary escalates
nothing at all.** The τ that catches an undecided noul is above a half.
The measured sweeps show this directly: on the two clef student cells, at
τ = 0.5 the sweep escalates 0 of 61 judgments, and the first τ that
escalates anything is 0.6.

### 5.4 The escalation sweep — the seed's question

*The question that matters is not which number is best but whether any of
them, at any threshold, would have fired the right number of escalations.*

| cell | AUC | a τ that catches **every** wrong judgment | its cost |
|---|---|---|---|
| d1-2B · liquid trace | 0.2815 | **none exists** | — |
| d1-3B · liquid trace | 0.2944 | **none exists** | — |
| tiles rig · judge-only | 0.5115 | τ = 0.7 only | escalates **all 428**, tax 1.000 |
| clef teacher · defect.defect_class | 1.0000 | τ = 0.4 | tax **0.000** — catches 1 of 60, taxes none |
| clef teacher · scene.beacon_bearing | 0.7480 | τ = 0.95 | tax 0.563 |
| clef teacher · tile.tile | 0.6149 | τ = 0.95 | tax 0.914 |
| the five cells with accuracy 1.0000 | — | nothing to catch | — |

**For the two liquid-trace cells no threshold under any of the three
definitions catches every wrong judgment.** The seed's kill condition is
met, and in the worse direction than the seed imagined: the confidence is
not uninformative, it is *inverted*.

### 5.5 Why the confidence is inverted on the sea-state task

The reliability curve shows it bin by bin. The d1-2B's cells:

| bin | n | mean confidence | accuracy | gap |
|---|---|---|---|---|
| [0.5, 0.6) | 27 | 0.5237 | 0.7037 | **+0.1800** |
| [0.6, 0.7) | 71 | 0.6386 | 0.7746 | **+0.1360** |
| [0.7, 0.8) | 70 | 0.7387 | 0.5000 | **−0.2387** |
| [0.8, 0.9) | 11 | 0.8283 | 0.6364 | **−0.1919** |
| [0.9, 1.0) | 61 | 0.9701 | 0.1639 | **−0.8062** |

The most confident bin is right 16 % of the time. The cause is in the
task, and the split is exact:

| | n | accuracy | mean confidence |
|---|---|---|---|
| the prompt named the **true** state first | 158 | 0.7975 | 0.6826 |
| the prompt named the **decoy** first | 82 | **0.0000** | **0.8735** |

(d1-3B: truth first → 0.5000 at 0.7444; decoy first → 0.0000 at 0.8491.)

The task names two sea states, the *shown* one first, and in 35 % of the
steps the shown one is the decoy — the study's own noise rate. The model
answers the first-named condition, and it is **confident about which
condition the prompt named**: the d1-2B's argmax is the shown state in
208 of 240 steps. So the confidence measures the *presentation*, not the
world, and in the rows where the presentation lies the model is maximally
sure and maximally wrong.

**This is not a contradiction of E1.** E1 measured the d1-2B's confidence
on the *action gate* task, where all three of its errors sat below 0.5 and
it was 196/196 right above it. The same model, the same definition, a
different task: there the confidence was an excellent error detector; here
it is inverted. **The calibration is a property of the cell — (backend,
model, task) — not of the model**, and the sign of the relationship is not
guaranteed. That is the reason the unit of the tracking has to be the cell
and not the model, and the reason a τ that worked on one task cannot be
carried to another without the cell's own measurement.

### 5.6 The tiles rig: a confidence with no signal, and an under-confident one

The tiles rig's confidence carries **no** signal: AUC 0.5115. The
reliability curve's gaps are all positive — +0.2865, +0.3465, +0.2133 —
so the model is *under*-confident (claims 0.5654, is right 0.8458), but
the ordering is not monotone (bin 5 is right 0.8600, bin 6 is right
0.8450), so the number does not say which judgment to trust.

And the sweep's answer is stark: the only τ that catches every wrong
judgment is τ = 0.7, and it escalates **all 428** — tax 1.000. A gate on
this number can either catch nothing or escalate everything.

The rig's own τ sweep agrees from the other side: at τ = 0.5 the act rate
was 0.6667 and the judge-only win rate 0.6900; at τ = 0.6 the act rate
fell to 0.3333 and the win rate to 0.5500; at τ = 0.7 the act rate was
0.000 and the win rate 0.3867. **Below τ = 0.5 the gate escalated nothing
at all** (the act rate was 1.000 for τ ≤ 0.4) — the binary-ish floor of a
six-way choice is 1/6, so at τ = 0.5 this gate was already tight, and the
measured calibration says it was tight for the wrong reason.

### 5.7 Clef's lopsided booleans

The seed names Clef's lopsided booleans as the test case for
recalibration. They are lopsided in a measurable way — the student's
probability for a boolean is **bimodal, with an empty band in the middle**:

| question | histogram of P(true) | widest empty band | min | max |
|---|---|---|---|---|
| `enemy_visible` | 0.0×43, 0.1×3, 0.5×2, 0.6×2, 0.7×2, 0.8×5, 0.9×4 | **[0.2, 0.5)** | 0.0114 | 0.9417 |
| `beacon_reachable` | 0.6×3, 0.7×33, 0.8×24, 0.9×1 | **[0.0, 0.6)** | 0.6678 | 0.9173 |

That is the shape behind the cascade's own finding that the fitted
threshold wants to be at 0.05–0.20 rather than 0.50: the empty band
[0.2, 0.5) means **every threshold inside it gives the same decisions**,
so the threshold is not a delicate setting on this model — it is a
switch, and the switch's position in the gap does not matter.

On the teacher's labels the student was right every time on both booleans
(accuracy 1.0000, n = 61 each), so the recalibration here is not fixing
wrongness — it is fixing the *scale* of the confidence, and it does: the
held-out Brier goes 0.0160 → 0.0000 and 0.0448 → 0.0000, and the held-out
ECE 0.0704 → 0.0000 and 0.2054 → 0.0000.

## 6. What it means for the τ gate

The decoy-first finding is a finding about the **gate**, not only about the
model. A τ on this cell's confidence is a threshold on *which condition the
prompt named*, and the prompt names the decoy first in exactly the rows
where the model is wrong. So the gate's job (escalate the wrong judgments)
and the gate's cost (tax the right ones) are **both inverted** on this
cell, and no τ fixes it.

**What the gate does, group by group** (the d1-2B's 240 recorded
judgments; the two groups are the prompt's order, and every decoy-first
judgment is wrong):

| τ | truth-first (158): escalated · catch · tax | decoy-first (82): escalated · catch |
|---|---|---|
| 0.5 | 0 · 0.000 · 0.000 | 0 · 0.000 |
| 0.6 | 19 · 0.000 · 0.151 | 8 · 0.098 |
| 0.7 | 90 · 0.500 · 0.587 | 8 · 0.098 |
| 0.8 | 141 · **1.000** · 0.865 | 27 · 0.329 |
| 0.9 | 148 · **1.000** · 0.921 | 31 · 0.378 |

Read the table by group. In the truth-first group the gate works as a gate
should: at τ = 0.8 it catches **every** wrong judgment (catch 1.000) and
taxes 86.5 % of the right ones. In the decoy-first group — where the
confidence is *highest* — the gate catches almost nothing: at τ = 0.9 it
still misses 62 % of them, because they sit above every threshold the
confidence can offer. **The gate's escalations land on the right answers and
its acts land on the wrong ones**, and the AUC's interval says the
inversion is not noise: 0.2815 **[0.2167, 0.3474]**, the whole interval
below the coin-flip line (the d1-3B: 0.2944 **[0.2255, 0.3652]**).

**The consequence for the routing.** The seed's kill condition is met on
this cell, and the τ is not a number to tune: it is a number to stop
using. The calibration report publishes the AUC and now its interval, so a
cell whose separability sits below a half is *named* as one that carries no
routing signal — and the router there has to be driven by something else
(the tiles rig's own numbers prefer the band's estimate, 0.7867, to the
judge-only arm's 0.6900). This is the same conclusion the tiles rig's cell
reaches by a different road (AUC 0.5115, interval **[0.4364, 0.5836]** —
the interval that says "no signal", not "a little signal").

**The fix, upstream.** The confidence is not broken; the **prompt** is. The
same model on the same definition, on a task that does not name a decoy
(E1's action gate), had a confidence that caught 100 % of its errors and
taxed 2 % of its traffic. A prompt that names two conditions and asks
which is shown leaks the answer's *position* to a model that answers
positionally; the leak has to be removed upstream, by asking a question
whose answer cannot be read off the order.

**The fix, in the judge.** The judge can also refuse to be fooled by the
position: ask the same question with the two named conditions **in the
other order** and escalate when the two answers disagree. Measured on the
recording, for the d1-2B:

| | the τ gate at τ = 0.8 | the both-order protocol |
|---|---|---|
| escalations | 168 of 240 | 208 of 240 |
| the wrong judgments caught | 59 of 114 (51.8 %) | **82 of 114 (71.9 %)** |
| the right judgments taxed | 109 of 126 (86.5 %) | 126 of 126 (100 %) |
| calls a judgment | 1 | **2** |
| added latency, p50 | — | **+32.21 ms** (the 3B: +50.70 ms) |

The protocol catches more of the errors, and it costs everything: it taxes
every right answer and it doubles the calls. **The recording does not hold
the reversed replies** — the trace asked each question in one order only —
so the protocol's row is computed under one stated assumption: that the
model treats the reversed prompt as the same question with the two named
conditions **swapped**, so its answer follows the option it chose,
renamed. Under that assumption the two orders disagree exactly when its
answer was one of the two named conditions — and the recording shows the
answer is the **first**-named condition in 208 of its 240 steps (and in
**82 of 82** of the decoy-first ones) and the second-named one in
**none** of them, so on this trace the two orders disagree exactly on
those 208 steps. A recording of the reversed replies would settle it; that
is a run on the Thor, and it is not run here.

**What the both-order protocol is worth.** Not a better gate — on this
cell no gate is. It is a **diagnostic**: it turns "confidently wrong" into
"undecided", so the leak shows up as a disagreement between two runs
instead of hiding behind a confident answer. And it says plainly what the
τ gate would have done here: acted on the model's surest mistakes.

**Its yield is a property of the model, not of the protocol.** The 3B
answers positionally in 141 of its 240 steps against the 2B's 208, so the
same protocol on the same task catches 62 of its 161 errors (**38.5 %**)
against the 2B's 82 of 114 (71.9 %). A weaker leak buys a weaker
diagnostic, and the 3B's τ gate is no better: at τ = 0.9 it catches
47.6 % of the decoy-first errors against the 2B's 37.8 %. The protocol
does not manufacture signal; it surfaces the signal that is there.

**Averaging the two confidences does not help, and the reason is the
mechanism.** The confidence is a property of the *position*, so averaging
two position-confidences leaves two position-confidences: the average
would be about as large as either. What cancels the position is averaging
the two **vectors** — the average of the first-named answer and the
second-named answer puts the pair near 50/50, and the number the gate reads
becomes the probability of the *pair*, not of the presentation. That is the
same object as the τ gate's own finding in §5.3: on a binary, the raw
floor is never below a half, because one of two options always holds at
least half the mass. The both-order average on a binary *is* that floor.

## 7. What this does not say

* **It does not say the d1 models are useless.** It says their confidence
  is not a routing signal *on the sea-state task*, where the prompt
  names the answer. On E1's action gate the same model's confidence was a
  perfect error detector. The measurement is per cell for that reason.
* **It does not say the confidence should be discarded.** It says the
  decision to route on it has to be made from the cell's own numbers, and
  that the numbers can come out negative. Where the AUC is high
  (`defect_class` 1.0000, `beacon_bearing` 0.7480) the confidence is worth
  a threshold; where it is not, the router has to be driven by model
  disagreement or by the bandit's estimate — which is the seed's own
  fallback, and the tiles rig already has one (`core/tiles/ope`, and the
  cold-start rig's own numbers: the bandit 0.7867 against the judge-only
  arm's 0.6900).
* **It does not say the recalibration fixes the models.** It fixes the
  *scale* of their confidence. The clef `tile` cell's accuracy is 0.5833
  before the recalibration and 0.5833 after it; what moved is the Brier
  (0.1199 → 0.1084) and the ECE (0.2128 → 0.1026). A cell whose error is a
  ranking error needs the cascade's choice prior, not a map (§4.4).
* **It does not say the clef teacher's booleans are a weak model.** The
  teacher was right 100 % of the time on both; its confidence was simply
  under-confident, and the scale fixes that.
* **The critic's and the owner's outcomes are contracts, not
  measurements.** The fold asks three sources — the tiles' play, the
  critic's verdict, the owner's keep — but only the tiles' source is
  measured here. The critic's `critic.verdict` rows in `core/coldstart`
  carry a synthetic ground truth, not a "keep"/"fix" verdict, so the
  critic's and the owner's sources are exercised by the suite and not by
  this experiment.
* **The drift lines did not fire on these cells.** The cells here are
  windows of one recording each: the drift rule needs a cell's own
  history (at least three windows of 50), and the recordings are one
  window long. The rule is exercised by the suite, on synthetic windows
  where each of the three kinds fires — and by the morning report's own
  test, which builds a night whose confidence stops separating and checks
  that the morning carries one line for it.

## 8. Reproducing it

```bash
# the suites (no network, no GPU, no LLM)
.venv/bin/python -m pytest -q tests/judge/test_calibration.py   # 54 tests
.venv/bin/python -m pytest -q tests/judge/test_tracking.py      # 23 tests
.venv/bin/python -m pytest -q tests/judge                       # 187 tests

# the measurement (replays the recorded vectors; writes the JSON)
.venv/bin/python docs/lab/judge-calibration-scripts/measure_calibration.py
```

The script reads five files and writes one:

| reads | from |
|---|---|
| `exp_c_trace_d1-2B.json`, `exp_c_trace_d1-3B.json` | `/home/proart/lm-wt/liquid-study/results/` |
| `judge-tiles-coldstart.json` | `docs/lab/judge-scripts/results/` |
| `hysteresis-d1-sweep.json` | `docs/lab/hysteresis-scripts/results/` |
| `c3-calibration-runs.json` | `/home/proart/lm-wt/clef-cascade/results/` |
| the tiles rig, imported for its constants and its tile set | `docs/lab/judge-scripts/measure_tiles_coldstart.py` |
| the clef cases, rebuilt for their ground truth | `docs/lab/clef-cascade-scripts/cascade.py` |

and writes
`docs/lab/judge-calibration-scripts/results/calibration-measurement.json`
with every number in this note, the reliability curves, the full sweeps
under all three definitions, the fitted scales, the bootstrap intervals
(each AUC's, and each cell's paired Brier improvement) and the machine
state.

The clef results live on another machine's worktree; copy them in, or
point the script at that path.

The whole core, on the ProArt at this commit: **1,669 passed, 13 skipped,
16 deselected** (the deselected are the opt-in real-engine run). The
`pxr` collection error in `tests/usd` is pre-existing — the USD extra's
wheels are not installed here.

## 9. The verdict

**One definition of confidence is necessary and not sufficient.** The
mechanism the seed asked for is built and measured: one function computes
the confidence for every backend from the vector the backend returned, the
row says which definition it used, and the Brier score, the ECE, the
reliability curve and the escalation sweep are published per
(backend, model, task).

What the measurement adds, on 1,470 recorded judgments:

1. **The three formulas are real and they move the threshold.** The d1-2B
   reports the top probability and the d1-3B the normalised margin, on
   240/240 judgments each; the same τ = 0.5 is a top probability of 0.5
   on one and 0.6 on the other. A threshold carried between models was
   never the same threshold.
2. **A confidence can be anti-correlated with being right.** On the
   sea-state task the d1-2B's AUC is 0.2815 and the d1-3B's 0.2944, and
   the most confident bin is right 16 % of the time — because the model is
   confident about which condition the *prompt* named, and the prompt
   names the decoy first in 35 % of the steps. The bootstrap intervals
   (**[0.2167, 0.3474]** and **[0.2255, 0.3652]**) lie entirely below a
   half, so the inversion is the cell's property, not a small sample's
   noise.
3. **A confidence can carry no signal at all.** The tiles rig's AUC is
   0.5115 with the interval **[0.4364, 0.5836]** — it straddles the
   coin-flip line, which is the measurement saying "no signal here"
   rather than "a little signal"; and the only τ that catches every wrong
   judgment escalates all 428. There the router has to be driven by
   something else — the band's own estimate, which the rig's own numbers
   prefer (0.7867 against 0.6900).
4. **The recalibration works where the signal is there.** Ten of the
   eleven cells keep a scale that improves the held-out Brier, and the
   one that drops it is the one where the fit made the newer half worse.
   The **paired** bootstrap says which of those improvements are
   established: nine of the ten kept cells' intervals exclude zero —
   among them the two liquid-trace cells (+0.0233 [+0.0086, +0.0387]
   and +0.0580 [+0.0285, +0.0857]) and the tiles rig (+0.0148 [+0.0041,
   +0.0238]) — while the teacher's `tile.tile` cell's improvement
   (+0.0116 [−0.0042, +0.0269]) does not: on 30 held-out judgments that
   cell's gain is a point estimate with the interval behind
   it. The Brier and the ECE can disagree, and a Brier-optimal scale can
   be degenerate (the teacher's `defect_class` temperature hit the bound
   of its search), so the scale is kept by the rule and read with the ECE
   beside it. The **accuracy does not move in any cell** — a map that
   never changes the answer can only say how sure to be about the answer
   it already gave, which is the value half of the cascade's paired gate
   and not the whole of it (§4.4).
5. **A calibrated τ is read in the calibrated space, and a binary's raw
   floor is never below a half.** The tiles rig's calibrated τ of 0.5
   corresponds to a raw 0.2749; on a binary, τ = 0.5 escalates nothing,
   because one of two options always holds at least half the mass.
6. **The drift thresholds are measured, not invented**: the cell's own
   history is the noise floor, and the three drift kinds are the
   separability falling to the coin-flip line, the ECE moving further
   than it ever has, and a fitted scale going stale.
7. **On a leaky task the gate's sign is wrong, and no τ fixes it.** The
   sea-state prompt names the decoy first in 35 % of the steps, and the
   model's certainty is about *which condition the prompt named* — so the
   gate's escalations land on the right answers and its acts on the wrong
   ones (§6). The fix is upstream, in the prompt; the judge's own version
   of it — ask both orders and escalate when they disagree — catches more
   of the errors (71.9 % against 51.8 % at τ = 0.8) at twice the calls
   and the full tax of every right answer, and the recording does not hold
   the reversed replies, so that row is computed under a stated
   assumption.

The practical consequence for the builder: **the confidence gate's τ is a
per-cell parameter with a measured value, not a default.** `core/judge`
now computes one definition for every backend and records it, the nightly
job writes the calibration report (`NightsService.stop()` folds the night's
judgments against the outcomes that answered them and puts the report in
the artifact store beside the morning), and the morning report carries
**one line per drifting model**. Where a cell's AUC says the number
carries no signal, the cell's τ is not a number to tune — it is a number
to stop using.

---

*Recorded 2026-10-31 on the ProArt (WSL2, Python 3.14.4, numpy 2.5.4),
CPU-only; the vectors were recorded on the Thor (the liquid study, the
tiles rig) and on Cloudflare's Workers AI (the clef cascade), and their
own box states are in their own files. The scripts are in
[`judge-calibration-scripts/`](judge-calibration-scripts/).*

## Limits of the both-order protocol (Hy4 adversarial review, 2026-11-01)
The 71.9% catch rate is not yet a gate:
- it assumes a purely positional model, and no reversed replies were recorded;
- the protocol escalates 208 of 240 steps (86.7%) and taxes every right answer;
- averaging two position-confidences does not cancel position (the AUC would stay inverted); only averaging the **vectors** might, and that is unmeasured.

One replay settles all five points below: the 240 recorded steps with the two named conditions swapped, d1-2B and d1-3B, recording argmax + full vector (minutes on the Thor). It is queued as `judge-reversed-replay`.

 1 The swap assumption (model is purely positional). Trap: 71.9% assumes the    
   reversed prompt makes the model answer the other named condition (it always  
   picks first-named). If the model answers by content/salience, the reversed   
   answer may equal the original (no disagreement) on decoy-first steps → catch 
   rate far below 82/114, or it may disagree on truth-first steps too. Cheapest 
   Thor run: Replay the 240-step sea-state trace with the reversed prompt (swap 
   the two named conditions) for d1-2B/3B, recording argmax + full vector. Count
   how often reversed argmax = the other named condition; recompute the actual  
   disagreement set and catch rate. (240 steps, one run, minutes; no new model.)
 2 “Average the confidence” fails by the document’s own mechanism. Trap: The    
   71.9% is for escalate-on-disagreement, not for averaging confidences. The    
   document says averaging two position-confidences leaves two                  
   position-confidences (the average is about as large as either), so a gate on 
   the averaged confidence still acts on the surest mistakes; AUC stays inverted
   (~0.28). If the judge implements “average the confidence”, it does not cancel
   position. Cheapest Thor run: From the recorded original + reversed vectors,  
   compute the average of the two confidences (not vectors) and measure AUC and 
   the escalation sweep; confirm no τ catches every wrong judgment and the AUC  
   is still below 0.5. (CPU replay once reversed vectors exist.)                
 3 The averaged-vector gate is unmeasured. Trap: The proposed cancellation is   
   averaging the two vectors (putting the pair near 50/50), but no reversed     
   vectors were recorded, so the averaged vector’s confidence, AUC, and sweep   
   are unknown; it may still carry no signal or be inverted, so no τ catches all
   wrong. Cheapest Thor run: Using original + reversed vectors, compute the     
   elementwise average per step, take max prob as confidence; measure AUC and   
   the escalation sweep (does any τ catch all wrong? tax?). Compare to 71.9% and
   raw AUC 0.2815. (CPU replay.)                                                
 4 Latency/cost are assumed; the protocol escalates nearly everything. Trap:    
   “+32.21 ms p50” and “2 calls” are computed under the assumption; actual      
   sequential latency may be higher. The protocol escalates 208/240 (86.7%) and 
   taxes 100% of right answers, so 71.9% is the max catch of a                  
   near-total-escalation diagnostic, not a usable gate; at any sane escalation  
   budget the effective catch is unmeasured. Cheapest Thor run: On the Thor, run
   both-order live (two prompts per step) for the 240 steps; measure p50/p95    
   added latency, GPU/CPU state, and confirm escalation/tax counts with real    
   replies; test whether the two prompts can be batched in one call to halve    
   latency.                                                                     
 5 Decoy-first error may be content/salience, not position. Trap: The 82        
   decoy-first steps are all wrong and all first-named, but the trace never     
   reversed the order; if the model prefers the decoy state regardless of       
   position (content bias), reversing yields the same decoy answer, no          
   disagreement, and the protocol catches 0 of 82 (71.9% collapses). The finding
   would be a prompt artifact, not a positional leak. Cheapest Thor run: On the 
   Thor, run a fresh controlled set (240 steps) where the true/decoy order is   
   swapped and salience is decorrelated (plus a neutral phrasing that does not  
   name a shown state first). Measure whether argmax follows position or the    
   decoy’s content; if content, the both-order protocol fails and the fix is    
   upstream (prompt), not the judge.                                            


