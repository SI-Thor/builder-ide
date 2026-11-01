# EXP — the judge's confidence, on one definition, measured against the Brier score

**Date:** 2026-10-31 (the judge-calibration seat; **CPU-only, no GPU, no
server, no cloud key** — every vector below is a *recorded* probability
vector, replayed from disk). **Continued 2026-11-01:** the bootstrap
intervals (§5.1, §5.2) and the τ-gate analysis (§6) were added, and every
number was re-measured on that day — the re-measurement reproduces the
2026-10-31 numbers exactly, so nothing below moved. **Continued 2026-11-01
(again, on the Thor):** §7 replays the 240 recorded sea-state steps with the
two named conditions **swapped**, for the d1-2B and the d1-3B, recording the
argmax and the full vector of every reply. It measures the both-order
protocol instead of assuming it, and it **corrects the rows in §6** that the
assumption produced: the protocol's catch rate is **24.6 %** on the 2B (not
71.9 %), **2.5 %** on the 3B (not 38.5 %), and averaging the two vectors does
not cancel the position. **Continued 2026-11-01 (a third time, on the
Thor):** §8 builds the fix §7 left upstream — the state's named conditions
in an order the answer cannot be read off, and the named pair the
recorder's docstring always claimed — and re-measures the same 240 steps
under it: the AUC un-inverts (**0.2815 → 0.5766 [0.5050, 0.6457]** on the
2B, the interval wholly above the coin-flip line), the decoy-first steps
become answerable, **the d1-3B passes every criterion**, and the d1-2B
stays positional — so the cell routes to the 3B.
**Continued 2026-11-01 (a fourth time, on the
Thor):** §9 fixes the recorder that built the trace — its noise steps left
the truth out of the prompt entirely (82 of 240 prompts, 43 of them naming
one condition twice) — and **re-records the 240 steps the fixed recorder
builds**: the truth and the drawn decoy, once each, in the canonical
order, on the same seed and stream. The instrument reproduces the
recording (the 2B's vectors bit-exact on the 82 comparable steps), the
inversion stays gone on the recorder's own trace (2B 0.2815 → 0.5300
[0.4583, 0.5979], 3B 0.2944 → 0.4797 [0.4091, 0.5540] — both intervals now
straddle the line: the confidence is not a routing signal on this cell),
the once-unwinnable steps become answerable (the 43 doubled: 0.0 → 0.4419
on the 3B), the 3B keeps the accuracy edge (0.5208 against 0.4833) and
§8.3's route stands — applied end to end through the shipped judge seam at
the calibrated τ. §9.5 corrects two §8 statements in writing.

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
whose answer cannot be read off the order. **§8 builds that fix and
measures it.**

**The fix, in the judge.** The judge can also refuse to be fooled by the
position: ask the same question with the two named conditions **in the
other order** and escalate when the two answers disagree. Measured on the
recording, for the d1-2B, and **measured again on the reversed replay**
(§7, where the reversed replies are recorded rather than assumed):

| | the τ gate at τ = 0.8 | the both-order protocol |
|---|---|---|
| escalations | 168 of 240 | **137 of 240** (§7) |
| the wrong judgments caught | 59 of 114 (51.8 %) | **28 of 114 (24.6 %)** (§7) |
| the right judgments taxed | 109 of 126 (86.5 %) | **109 of 126 (86.5 %)** (§7) |
| calls a judgment | 1 | **2** |
| added latency, p50 | — | **+32.21 ms** on the recording's own box; **+73.4 ms** on the replay's (§7) |

Measured, the protocol catches **fewer** of the errors than the τ gate does
at τ = 0.8 (28 against 59), and it costs two calls a judgment. **The
recording does not hold the reversed replies** — the trace asked each
question in one order only — so this row was first computed under one stated
assumption: that the model treats the reversed prompt as the same question
with the two named conditions **swapped**, so its answer follows the option
it chose, renamed. Under that assumption the two orders disagree exactly
when its answer was one of the two named conditions — and the recording
shows the answer is the **first**-named condition in 208 of its 240 steps
(and in **82 of 82** of the decoy-first ones) and the second-named one in
**none** of them, so on this trace the two orders would disagree exactly on
those 208 steps.

**§7 measured that assumption and it does not hold.** The reversed replies
are now recorded: the 2B's two orders disagree on **137** steps, not 208 —
43 steps name one condition twice, so their reversed prompt is byte-identical
and they cannot disagree, and 28 more answer by content and keep their
condition. The catch falls with it: **28 of 114 (24.6 %)**, not 82 of 114
(71.9 %). The numbers in this table are §7's; the assumption is retired.

**What the both-order protocol is worth.** Not a better gate — on this
cell no gate is. It is a **diagnostic**: it turns "confidently wrong" into
"undecided", so the leak shows up as a disagreement between two runs
instead of hiding behind a confident answer. And it says plainly what the
τ gate would have done here: acted on the model's surest mistakes.

**Its yield is a property of the model, not of the protocol — and the
replay says which model.** The 3B answers positionally in 141 of its 240
steps against the 2B's 208, so the same protocol on the same task catches
62 of its 161 errors (**38.5 %**) against the 2B's 82 of 114 (71.9 %). A
weaker leak buys a weaker diagnostic, and the 3B's τ gate is no better: at
τ = 0.9 it catches 47.6 % of the decoy-first errors against the 2B's
37.8 %. The protocol does not manufacture signal; it surfaces the signal
that is there. **§7 corrects both of those rows**: the 3B's answers are
**order-invariant** (its two orders disagree on 4 of its 240 steps), so the
protocol catches **4 of its 161 errors (2.5 %)** — it has almost nothing to
escalate — while the 2B's two orders disagree on 137 of 240 and it catches
**28 of 114 (24.6 %)**.

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
**§7 measured the averaged vector too, and it does not cancel the
position**: on the 2B its AUC is **0.1332 [0.0922, 0.1800]**, *below* the
canonical 0.2815 — further from the coin-flip line, not nearer it (§7.4).

## 7. The reversed replay

The five points the "Limits of the both-order protocol" section (at the end
of this note) left open are settled here, by one replay: the **240 recorded
sea-state steps asked again with the two named conditions swapped**, for the
d1-2B and the d1-3B, with the argmax and the full probability vector of
every reply recorded. The scripts are in
[`judge-reversed-scripts/`](judge-reversed-scripts/); the raw replies are in
`judge-reversed-scripts/results/replay-d1-2B.json` and
`…/replay-d1-3B.json`, and every number below is in
`…/results/reversed-measurement.json`.

**What was asked.** The state text of a step is two sentences, one per named
condition: `The sea is <shown>: …. The sea is <other>: ….`. The reversed
prompt is those two sentences the other way round. Nothing else moves — the
question, its five criteria and their letters A–E, the ground truth (always
the true condition) and the shape of the call. Half the steps ask the
original prompt first and half ask the reversed one first, so "which
condition the prompt named first" and "which call came first in the pair" are
not the same variable. 480 calls a model.

**The instrument, and its fidelity to the recording.** The d1-2B was asked on
the box's resident thor-admit-served d1-2B Q8 server (port 8094, 8 slots,
ctx 4096); the d1-3B was served for this run under a thor-admit lease (port
8320, 2 slots, ctx 4096, the recorder's flags). Every live original-order
reply was compared with the October recording, vector against vector:

| model | compared | max abs diff | mean abs diff | the argmax is the same |
|---|---|---|---|---|
| d1-2B | 240 of 240 | **0.0** | 0.0 | **240 of 240** |
| d1-3B | 240 of 240 | 0.0168 | 0.0017 | **240 of 240** |

The d1-2B's live replies are the recorded vectors, exactly. The d1-3B's
probabilities differ in the third decimal — the recording was made on a
4096-context single-slot server and this one runs two 2048-token slots — but
its **decisions are the same on every one of the 240 steps**, so the 3B's
argmaxes and counts below are the recorded ones and its vectors carry that
difference.

**The determinism control.** 43 of the 240 steps name the *same* condition
twice, so their reversed prompt is byte-identical and the reversal is a
no-op there. Both models returned **byte-identical vectors on all 43**, which
is the run's own check that the difference between the two orders is the
prompt and not the run.

**The box, beside the numbers.** The recording was made on a quiet box: at
its start the load was 10.3, 115.3 GB of memory were available, 27.6 GB were
resident, the GPU stood at 0 % and 53.7 °C, and the per-decision p50 was
32.21 ms (the 3B: 50.68 ms, at 0 % and 52.3 °C). The replay ran on a busier
one: 68.9 GB resident at its start (2.5× the recording's), the GPU at 0 % and
57.0 °C when the first call was made and **97–98 %** for the rest of the
run, 63.5–64.1 °C, the load between 8.6 and 10.7, the memory available
between 71.2 and 87.9 GB. The 3B's replay ran with the GPU at 97 % throughout
(64.3 → 68.3 °C, VDD_GPU 40.1 → 58.2 W). **The absolute latencies in §7.5
are this box's, not the protocol's**; the recorded trace's p50 (32.21 ms) and
the replay's (73.8 ms) are not the same measurement.

**The leases.** `thor-admit serve` queues at priority 0 — nineteen other
requests were ahead of the d1-3B's — while `thor-admit run --priority 1` is
granted at the next memory spike, so the d1-3B server and both replay
clients ran under `thor-admit run` leases (`judge-reversed-replay.serve-d1-3B`
and `judge-reversed-replay.replay`, the latter waiting 133 s for room). The
d1-2B needed no new server: the box's resident one answered.

### 7.1 The positional share

For each step, the reversed answer is compared with the two named
conditions: did it name the condition the **reversed** prompt named first
(**position**), the condition the **original** prompt named first
(**content**), or a third option? Over the 197 steps whose prompt names two
different conditions:

| model | position | content | a third option |
|---|---|---|---|
| d1-2B | **169 (85.8 %)** | 28 (14.2 %) | **0** |
| d1-3B | 95 (48.2 %) | **102 (51.8 %)** | **0** |

Neither model ever answers with a condition the prompt did not name. The
same tally by the prompt's order, with the original and the reversed reading
side by side — "named the first-named condition" means the condition the
prompt named first *in that reading*:

| model | the prompt's order | n | original named the first | reversed named the first |
|---|---|---|---|---|
| d1-2B | truth-first | 158 | **126** | **17** |
| d1-2B | decoy-first (two conditions) | 39 | **39** | 28 |
| d1-3B | truth-first | 158 | **79** | **79** |
| d1-3B | decoy-first (two conditions) | 39 | 19 | 23 |

**The d1-2B answers by position.** On the truth-first prompts it named the
truth 126 times; on *the same prompts with the two sentences swapped* it
named the truth 17 times. A model that chose by content would not move; the
2B moved on 141 of the 158. **The d1-3B answers by content**: it named the
same condition in 236 of its 240 steps, and its truth-first tally is 79 and
79 — the reversed prompt changed nothing.

**Why the reversed accuracy is not the original's complement.** The d1-2B's
accuracy is 0.5250 in the original reading and **0.0708** in the reversed
one (the d1-3B's is 0.3292 in both). A perfectly positional model would
score 0.4750 reversed — the decoy-first steps, where the first-named
condition is the decoy, would come out right. They do not, because **the
truth is not in those prompts at all**: the recorder names the shown
condition and a neighbour of the truth, so on the 82 decoy-first steps no
answer can be right (both readings score 0.0000 there, and the 2B's 17
reversed-correct answers are all truth-first steps). This is a property of
the trace, and it bounds what any gate can do on this cell: 82 of the 2B's
114 errors are unwinnable, and a gate can only act on the 32 that are not.

### 7.2 The real disagreement set

The both-order protocol escalates when the two orders disagree. The
disagreement set, measured:

| | the assumption said | **d1-2B, measured** | **d1-3B, measured** |
|---|---|---|---|
| escalations | 208 (2B) / 141 (3B) | **137 of 240 (57.1 %)** | **4 of 240 (1.7 %)** |
| the wrong judgments caught | 82 of 114 (71.9 %) | **28 of 114 (24.6 %)** | **4 of 161 (2.5 %)** |
| the right judgments taxed | 126 of 126 (100 %) | **109 of 126 (86.5 %)** | **0 of 79 (0 %)** |

**Why the assumption was wrong, in two parts.** It said the two orders
disagree exactly when the answer was one of the two named conditions. (i)
**43 steps name one condition twice**, so their reversed prompt is
byte-identical and they cannot disagree whatever the model does. (ii) The
model answers by **content** on 28 of the 2B's 197 two-condition steps and
keeps its condition. 208 − 43 − 28 = **137**, the measured number.

**Where the catch comes from, and where it cannot come from.** The 2B's 114
errors are 32 truth-first steps (where it named the decoy in **both**
readings — so the two orders agree and nothing is escalated) and 82
decoy-first steps (where the truth is not in the prompt). Of those 82, 43
are the no-op steps and 11 more answer by content: **28 disagree, 28 are
caught, and 32 of the errors are invisible to the protocol.** Its ceiling on
this cell is 39 of 114 (34.2 %) even if every two-condition decoy-first step
disagreed.

**The joint table — did the answer move, and from what to what?** For the
d1-2B over the 240 steps: 17 named the truth in both readings, 109 named the
truth and then an other, **0** named an other and then the truth, and 114
named an other in both. The model never went from an "other" answer to the
truth: it either kept its condition (the content cases) or moved to the
other named condition (the position cases). For the d1-3B: 79 named the
truth in both, 161 an other in both, and 0 changed their truth-status — the
4 disagreements are steps where both readings were wrong and named different
non-truth conditions.

### 7.3 The average of the confidences, and the average of the vectors

The AUC of the confidence against the judgment (the original reading's
answer, right or wrong), with its bootstrap interval (2,000 draws, seed
20261031):

| what the gate reads | d1-2B | d1-3B |
|---|---|---|
| the original confidence (canonical) | 0.2815 [0.2167, 0.3474] | 0.3046 [0.2345, 0.3752] |
| **the average of the two confidences** | **0.1104 [0.0640, 0.1628]** | 0.3518 [0.2855, 0.4207] |
| **the average of the two vectors** (its top probability) | **0.1332 [0.0922, 0.1800]** | 0.3518 [0.2855, 0.4207] |

**Neither un-inverts the AUC; on the 2B both make it worse.** The published
0.2815 becomes 0.1104 (the average of the confidences) and 0.1332 (the
average of the vectors) — both *further* from the coin-flip line, and both
intervals wholly below it. On the 3B both move towards the coin-flip line
(0.3046 → 0.3518) and stay below it; there the two averages are the *same
number* (0.3518), because the 3B's two readings almost always share an argmax
and then the averaged vector's top probability is exactly the average of the
two confidences.

**The mechanism, now that it is measured.** The 2B's errors are its
*surest* steps — the decoy-first group carries a mean confidence of 0.8735
against the truth-first group's 0.6826 — and every average of two
confidences keeps that ordering, because both readings of a decoy-first step
are confident and both readings of a truth-first step are not. The averaged
vector does not cancel the position either: on the 94 steps where the two
readings disagree, the original's top probability sits on the first-named
condition and the reversed's on the second-named one, so their average
spreads the mass over the pair and the top probability becomes "how sure is
the model about the *pair*" — the raw floor §5.3 describes — which on the
decoy-first steps is a high number about a wrong answer. **§6's proposal
that averaging the vectors is what cancels the position is wrong**, and the
measurement says why: the position is not in the *scale* of the confidence,
it is in *which condition* the confidence is about.

**No τ catches every wrong judgment** for either average, on either model
(the sweeps' `caught_all` is false at every τ from 0.1 to 0.95).

### 7.4 Sane budgets

What a gate catches when it is allowed to escalate only a sane share of the
traffic. The τ gate's τ is the largest one (on a 0.005 grid) whose
escalation share stays under the budget; the both-order protocol is ranked
by the original reading's confidence, least confident first, and spends the
budget there — the ranking is not part of the published protocol, and the
catch depends on it, which is why it is named.

**d1-2B** (114 wrong, 126 right):

| budget | the τ gate | the both-order protocol |
|---|---|---|
| 10 % | **cannot be set**: the largest τ under 10 % is 0.52 and it escalates **nothing** — the confidences jump to 0.525, where 27 steps (11.3 %) escalate and catch **0** of the 114 | 24 steps (10.0 %): catches **8 of 114 (7.0 %)**, taxes 16 of 126 (12.7 %) |
| 20 % | τ = 0.625 → 44 steps (18.3 %): catches **8 of 114 (7.0 %)**, taxes 36 of 126 (28.6 %) | 48 steps (20.0 %): catches **8 of 114 (7.0 %)**, taxes 40 of 126 (31.7 %) |
| 30 % | τ = 0.645 → 60 steps (25.0 %): catches **24 of 114 (21.1 %)**, taxes 36 of 126 (28.6 %) | 72 steps (30.0 %): catches **8 of 114 (7.0 %)**, taxes 64 of 126 (50.8 %) |
| — (the protocol as published) | — | 137 steps (57.1 %): catches **28 of 114 (24.6 %)**, taxes 109 of 126 (86.5 %) |

**Inside a sane budget the protocol is not better than the τ gate**: at 10 %
and 20 % they catch the same 8 errors, and at 30 % the τ gate catches three
times as many (24 against 8). The reason is the ranking: the errors are the
*confident* ones, so a budget spent on the least confident steps spends it on
the right answers. The protocol's edge appears only above half the traffic,
and there it costs 86.5 % of the right answers to catch a quarter of the
wrong ones.

**d1-3B** (161 wrong, 79 right):

| budget | the τ gate | the both-order protocol |
|---|---|---|
| 10 % | τ = 0.575 → 24 steps (10.0 %): catches **0 of 161**, taxes 24 of 79 (30.4 %) | 4 steps (1.7 %) — fewer than the budget allows: catches 4 of 161 (2.5 %), taxes 0 |
| 20 % | τ = 0.705 → 39 steps (16.3 %): catches 15 of 161 (9.3 %), taxes 24 of 79 (30.4 %) | as above |
| 30 % | τ = 0.71 → 66 steps (27.5 %): catches 42 of 161 (26.1 %), taxes 24 of 79 (30.4 %) | as above |

The 3B has no disagreements to escalate, so the protocol is empty on it
while the τ gate still has (inverted) signal to give.

### 7.5 The latency

**The two prompts cannot be one call.** `/v1/systemone` takes **one state
per request** — the questions share the request's single state — so two
prompts cannot be one HTTP request, and the endpoint's `n_variants` (which
asks a choice in two orders, to cancel a preference for the first label) is
applied to the LEV decision type and **not** to d1. The closest the box gets
is two requests at the same time, and whether the server merges them into
one batch is the server's business: llama.cpp sets `decision.no_batching`
for the LFM3-d1, so on the d1-2B the two decision tasks are never merged into
one graph.

Measured on 120 pairs, interleaved — for each step the sequential pair and
the concurrent pair are measured back to back, so both see the same load:

| | one call | two calls in sequence | two calls at the same time | the concurrent pair's saving |
|---|---|---|---|---|
| d1-2B | p50 **73.8** / p95 **101.4** ms | p50 **147.2** / p95 **226.7** ms | p50 **139.9** / p95 **207.9** ms | **5.0 %** at p50 |
| d1-3B | p50 **112.8** / p95 **168.6** ms | p50 **225.2** / p95 **330.3** ms | p50 **208.4** / p95 **278.6** ms | **7.5 %** at p50 |

(box state beside: the 2B's replay ran with the GPU at 97–98 %, 69.8 GB
resident, 63.5–64.1 °C; the 3B's with the GPU at 97 %, 64.3–68.3 °C,
VDD_GPU 40–58 W. The recorded trace's own per-decision p50 was 32.21 ms and
50.68 ms with the GPU at 0–15 % and 27.7 GB resident — so the added cost of
the second call is **+73.4 ms** (2B) and **+112.4 ms** (3B) at p50 *on this
box*, against the +32.21 ms and +50.70 ms the recording's idle box implies.)

**The concurrent pair is not a batched pair.** Inside the concurrent pair
each call takes about **1.55× as long** as it does alone (the 2B: p50 115.0 ms
against 73.8 ms; the 3B: p50 174.0 ms against 112.8 ms) — which is what two
calls sharing one saturated GPU look like, not what one batch looks like.
The pair still costs ~1.9× a single call (147.2 ms against 73.8 ms) either
way, so the protocol's second call buys its information at full price.

### 7.6 What this changes

1. **The decoy-first finding's mechanism is settled, and it differs by
   model.** The d1-2B's inverted confidence is a **position** leak (85.8 % of
   its two-condition steps follow the prompt's order; the truth-first
   prompts score 126 in the original reading and 17 in the reversed one). The
   d1-3B's is **not** — its answers are order-invariant (236 of 240 steps
   unchanged), so its inverted confidence is about the content of the state,
   not about the order of the sentences.
2. **The both-order protocol's catch rate is 24.6 % on the 2B and 2.5 % on
   the 3B**, not the 71.9 % and 38.5 % the assumption produced. §6's row is
   retired; the assumption is retired with it.
3. **Averaging the vectors does not cancel the position** (0.1332 on the 2B,
   below the canonical 0.2815). The proposal in §6 is refuted by the
   measurement, and the reason is that the position is in *which condition*
   the confidence is about, not in the confidence's scale.
4. **Inside a sane escalation budget the protocol is no better than the τ
   gate** (7 % against 7 % at 20 %, 7 % against 21 % at 30 %), because the
   errors are the confident ones.
5. **The recommendation is unchanged in its direction, and now has its
   numbers.** Do not route on this cell's confidence; the gate's sign is
   wrong and no τ fixes it. The fix is upstream, in the prompt — a question
   whose answer cannot be read off the order. §8 builds that fix and
   measures it; on the fresh recording the recommendation becomes
   **route this cell to the d1-3B**. The both-order protocol stays
   what §6 called it, a **diagnostic**: it turns "confidently wrong" into
   "undecided" on 57 % of the 2B's steps, at two calls a judgment, and it
   catches 28 of 114 errors. It is not a gate, and on the d1-3B it is not
   even a diagnostic.

## 8. The prompt fix

§7 left the fix upstream, in the prompt: *"a question whose answer cannot
be read off the order."* This section builds it and measures it, on the
same 240 recorded steps, the same two models, one session, 2026-11-01. The
scripts are in [`judge-prompt-fix-scripts/`](judge-prompt-fix-scripts/);
the raw replies are in `…/results/fresh-d1-2B.json` and
`…/results/fresh-d1-3B.json`, and every number below is in
`…/results/prompt-fix-measurement.json`.

**Where the leak lived.** The recorder's state builder names two conditions
— ``The sea is <shown>: …. The sea is <other>: ….`` — with the shown
condition first. The order was the presentation, and the d1-2B reads the
presentation as the answer (§7: 85.8 % positional), so the prompt's least
incidental choice was its most consequential one. The builder's docstring
says the state *"mentions the true condition plus a decoy, and with
probability p the decoy is presented as the true one"*; the code does
something worse than presenting the decoy first on the noise steps — it
**leaves the truth out of the prompt entirely** (the decoy named twice, or
the decoy and the truth's neighbour), which is the §7.1 bound no gate could
lift: 82 of the 2B's 114 errors were unwinnable. A fix that only reordered
the recorded sentences would have kept that bound — the decoy-first
accuracy is pinned at 0.0 by arithmetic on any order of a prompt that does
not name the truth. The fix therefore has the two halves the recorder's own
docstring intended:

* **the named pair is the true condition and the decoy, on every step** —
  the docstring's *"mentions the true condition plus a decoy"*; and
* **the order is not informative**, from `core/judge/ordering.py`: the
  **canonical** order (sorted by the condition's own name — a key of what
  the condition is, not of whether it is true) or the **balanced** order
  (a seeded coin per step, sha256 over the step's ``(trial, t)`` key —
  half the steps name either condition first, deterministic for replay).

**The arms.** Every step was asked three times: ``recorded`` (the
recording's own text — the control), ``canonical`` and ``balanced`` (the
fixed pair in the two neutral orders). The arms rotate with the step index,
so "which arm went first" is not a variable; 720 calls a model. The
judgment is the arm's own answer, scored against the ground truth (always
the true condition); the "before" numbers are the ``recorded`` arm's,
computed in the same walk.

**The instrument.** The d1-2B was asked on the box's resident thor-admit
server (port 8094); the d1-3B was served for this run under a lease (port
8320, 2 × 2048-token slots, the §7 flags), and both replay clients ran
under thor-admit leases (``judge-prompt-fix.replay-d1-2B``,
``…replay-d1-3B``). Every live ``recorded`` reply was compared with the
October recording, vector against vector:

| model | compared | max abs diff | the argmax is the same | the 43 no-op steps' vectors |
|---|---|---|---|---|
| d1-2B | 240 of 240 | **0.0** | **240 of 240** | **43 of 43 identical** |
| d1-3B | 240 of 240 | 0.0168 | **240 of 240** | 0 of 43 (the two-slot server's third decimal, as in §7) |

The ``recorded`` arm's numbers are the published ones, to the fourth
decimal: the 2B's accuracy 0.5250 and AUC **0.2815 [0.2167, 0.3474]**, the
3B's 0.3292 and **0.3046 [0.2345, 0.3752]** (§7.3's row) — the instrument
is the recording's. **[Corrected in §9.5: the 0.3046 is §7.3's live replay
arm — the recording re-asked on the two-slot server — not the recording's
own vectors, whose AUC is 0.2944 [0.2255, 0.3652], the number §5.1
publishes; "to the fourth decimal" holds for the 2B only.]** The
determinism control re-asked the first 12 steps in
all three arms at the end of the run: **36 of 36 vectors identical**, per
model.

**The box, beside the numbers.** The GPU stood at 94–98 % for both runs
(other seats' leases held it: a 40 GB generator, a BF16 server, a
live-view export), 39.6–40.3 GB of RAM used, 54.8–54.9 °C, the load
6.4–6.9 at the starts. The per-call p50 across arms: the 2B 77.7–78.7 ms,
the 3B 47.1–47.2 ms — **the 3B was the faster model on this box today**,
against §7.5's 112.8 ms; the two servers' configurations differ (the
resident 2B carries an mmproj, 8 slots and a 32 k context; the 3B ran 2
slots and a 4 k one), so the latencies are this box's and these
configurations', not the models'.

### 8.1 What the fix did to the cell

| model | arm | accuracy | truth-first (158) | decoy-first (82) | AUC [interval] |
|---|---|---|---|---|---|
| d1-2B | recorded (before) | 0.5250 | 0.7975 | 0.0000 | 0.2815 [0.2167, 0.3474] |
| d1-2B | canonical | 0.3708 | 0.4620 | **0.1951** | **0.5766 [0.5050, 0.6457]** |
| d1-2B | balanced | 0.3625 | 0.4241 | **0.2439** | 0.5438 [0.4672, 0.6159] |
| d1-3B | recorded (before) | 0.3292 | 0.5000 | 0.0000 | 0.3046 [0.2345, 0.3752] |
| d1-3B | canonical | **0.4875** | 0.5000 | **0.4634** | 0.5082 [0.4329, 0.5817] |
| d1-3B | balanced | **0.4875** | 0.5000 | **0.4634** | 0.5107 [0.4349, 0.5858] |

**The inversion is gone, and on the 2B the interval proves it.** The
canonical arm's AUC is 0.5766 [0.5050, 0.6457] — wholly above the
coin-flip line, where 0.2815 [0.2167, 0.3474] was wholly below it. The
mechanism is visible in the confidences: before, the decoy-first steps
carried the *higher* mean confidence (0.8735 against the truth-first
group's 0.6826), because the presentation agreed with itself; after, the
two groups' confidences are the same number within noise (canonical:
0.7124 against 0.7082) — the confidence has stopped reading the
presentation, because the presentation has stopped saying anything.

**The decoy-first steps are answerable now.** They were not answerable
before — not because the model failed, but because the truth was not in
the prompt (§7.1). Naming it moves that group off 0.0 on both models: to
0.1951 (canonical) and 0.2439 (balanced) on the 2B, to 0.4634 on the 3B.

**The two models split, exactly along the line §7 drew.**

* **The d1-3B passes all three of the brief's criteria, on both arms.** Its
  truth-first accuracy is 0.5000 before and after — and it is the *same*
  79 steps: the 3B names the truth on the same truth-first steps in all
  three arms, the §7 order-invariance showing up again as
  presentation-invariance (its answer is the same in all three arms on 202
  of its 240 steps). Its decoy-first accuracy rises from 0.0000 to 0.4634;
  its overall accuracy rises from 0.3292 to 0.4875; its AUC moves above
  the line (0.5082 canonical, 0.5107 balanced) — though only just, and
  both intervals straddle 0.5: the inversion is gone, and what remains is
  a little signal, honestly named a little.
* **The d1-2B stays positional, and pays for it.** It answers the
  first-named condition on 207 of its 240 canonical steps (86.3 %; 84.2 %
  balanced) — the neutral order changed what the first-named condition
  *is*, not what the model does with it. Its decoy-first accuracy rises
  (the fix worked on the group the leak had pinned), but its truth-first
  accuracy falls from 0.7975 to 0.4620, because that number was the leak's
  own product: the prompt named the truth first 65.8 % of the time, and
  the model answered the first-named condition. Its overall accuracy
  falls from 0.5250 to 0.3708. **The brief's pass therefore fails for the
  2B on its third criterion** — and §8.3 measures the route.

### 8.2 The order mode, chosen by measurement

The brief offered canonical or balanced and asked the measurement to pick.

| | canonical | balanced |
|---|---|---|
| d1-2B AUC | **0.5766 [0.5050, 0.6457]** — the only interval wholly above the line | 0.5438 [0.4672, 0.6159] — straddles it |
| d1-2B decoy-first | 0.1951 | **0.2439** |
| d1-3B | accuracy 0.4875, AUC 0.5082 | the same accuracy, AUC 0.5107 |
| the prompt | byte-stable per named pair — no step key to carry | moves with the step key, by design |

**The policy ships canonical** (`core.judge.ordering.neutral_state`, mode
``canonical``). It is the only arm whose 2B interval clears the coin-flip
line; it ties balanced everywhere else that matters; and its determinism
needs no step key, so the same named pair always asks the same prompt —
the property a replay needs. The balanced order stays in the module for
the caller whose condition pairs cluster on one side of the canonical key
(a process whose truths sit at low indices would see the decoy named
first more often than not; the coin breaks that correlation).

### 8.3 The τ gate after the fix, and the routing

The gate's semantics are the repository's (escalate when the confidence is
below τ; the canonical confidence is the top probability).

**d1-2B** (151 wrong, 89 right on the canonical arm — against 114 wrong,
126 right before):

| τ | before: escalated · catch · tax | canonical: escalated · catch · tax |
|---|---|---|
| 0.7 | 98 · 0.210 · 0.587 | 138 · 0.656 · 0.438 |
| 0.8 | 168 · 0.517 · 0.865 | 197 · 0.781 · 0.888 |
| 0.9 | 179 · 0.553 · 0.921 | 197 · 0.781 · 0.888 |

By group at τ = 0.8, canonical: truth-first escalates 132 (catch 0.812,
tax 0.863); **decoy-first escalates 65 and catches 0.742 of the group's
errors** — before, the same τ caught 0.329 of a group whose errors were
its surest answers. The gate's sign is right for the first time on this
cell, and the budget table agrees: inside the 30 % budget the canonical
arm's τ = 0.625 catches **0.298 at a 0.191 tax** (before: 0.211 at
0.286). Inside 10–20 % the canonical arm still cannot set a useful τ (the
confidences jump from 0.600, where nothing escalates, to 0.605, where
25.8 % do — a gap in the distribution, §7.4's shape); the balanced arm
can, and catches 0.170 at a 0.103 tax inside 20 %.

**d1-3B** (123 wrong, 117 right on the canonical arm — against 161 wrong,
79 right before):

| τ | before: escalated · catch · tax | canonical: escalated · catch · tax |
|---|---|---|
| 0.7 | 39 · 0.093 · 0.304 | 59 · 0.154 · 0.342 |
| 0.8 | 130 · 0.460 · 0.709 | 178 · 0.862 · 0.615 |
| 0.9 | 197 · 0.733 · 1.000 | 240 · 1.000 · 1.000 |

At τ = 0.8 the gate catches 0.862 of the errors at a 0.615 tax — more
catch, less tax than before — and the by-group reading is the fix's
clearest fingerprint: the decoy-first group's catch rises from 0.281 to
**1.000** (its errors are no longer the confident ones; τ = 0.8 escalates
every one of them, taxing 0.421 of the group's right answers), while the
truth-first group's catch is 0.785 at a 0.709 tax.

**The routing.** The 2B stayed positional under a neutral order — the
brief's own condition for measuring the route:

| the canonical arm | d1-2B | d1-3B |
|---|---|---|
| accuracy | 0.3708 | **0.4875** |
| decoy-first accuracy | 0.1951 | **0.4634** |
| AUC | **0.5766** [0.5050, 0.6457] | 0.5082 [0.4329, 0.5817] |
| the τ gate at 0.8 | catch 0.781 · tax 0.888 | **catch 0.862 · tax 0.615** |
| latency p50, this box | 78.3 ms | **47.1 ms** |
| the steps one model is right on | the 2B only: **17** | the 3B only: **45** |

**The recommendation: route this cell — any decision prompt of this
shape — to the d1-3B.** It is right on 45 steps the 2B gets wrong and
wrong on 17 the 2B gets right; its gate catches more and taxes less; and
on this box today it is also the faster model. The 2B keeps the cells
where its confidence is a real signal (E1's action gate, where it was
196/196 above τ = 0.5); the sea-state cell was never its cell — the
prompt named its answer's position, and under a neutral order it has
nothing else to read.

**What the fix does not do.** It does not make the task easy. The fixed
state names two conditions and nothing in the text says which holds, so a
model that reads content lands near the half a symmetrical question
deserves (the 3B: 0.4875). The fix removes the *wrong* signal; it does not
add a right one. A cell that needs accuracy above that needs a state
that carries evidence — which is the caller's perception to provide, not
the order policy's.

**§9 continues this section**: the recorder itself is fixed, the trace is
re-recorded on the prompts the fixed recorder builds, the cell and the
route are re-measured on it, and two §8 statements are corrected in
writing (§9.5).

## 9. The recorder, fixed at the source

§8 fixed the prompt at replay time, on the recorded steps. This section
fixes the recorder that wrote those steps, re-records the trace it should
have written, and re-measures the cell on the recorder's own prompts — one
session, 2026-11-01, the same two models. The scripts are in
[`judge-recorder-fix-scripts/`](judge-recorder-fix-scripts/); the raw
recordings are `…/results/rerecorded-d1-2B.json` and
`…/results/rerecorded-d1-3B.json`, the numbers in
`…/results/recorder-fix-measurement.json`, and the routed cell's rows in
`…/results/routed-end-to-end-d1-3B.json` and
`…/results/routed-end-to-end-d1-2B.json`.

**The fault, in the code.** The recorder is liquid-study's
`scripts/exp_c_hysteresis.py::make_trial`, and its docstring always
claimed the right design: *"the state text mentions the true condition
plus a decoy"*. What the code built was:

```python
other = decoy if shown != decoy else (truth + 1) % len(SEA_STATES)
state = (TRUE_TEXT[shown] + " " + TRUE_TEXT[other])
```

On a noise step (p = 0.35) `shown` *is* the decoy, so the second named
condition is `(truth + 1) % 5` — the decoy again when the decoy came from
above, the truth's other neighbour when it came from below. **The truth is
absent from every noise prompt** — the §7.1 bound no gate could lift. The
audit (`recorder.py --october`, run on the committed copy of the old
builder, kept verbatim): **82 of 240 prompts omit the truth, 43 name one
condition twice**; the October file `exp_c_trace_d1-2B.json` audits to the
same 82/43, so the committed copy is the recorded code. The fixed builder
audits to 0 and 0.

**The fix, and what it keeps.** The fixed builder (`recorder.py`,
committed beside its tests; the liquid-study script is patched in place to
build through the same policy) names **the true condition and the drawn
decoy, once each, in `core/judge/ordering.py`'s canonical order** — the
mode §8.2 shipped. It spends the random stream exactly as the old builder
spent it — same draws, in the same order — so the truths, the dwells, the
decoys and the noise labels are the October task's, step for step; only
the state text changed. `tests/judge/test_recorder_fix.py` (9 tests) pins
the whole contract: the invariant — *no prompt omits the truth, no prompt
names an option twice* — passes on the fixed builder and fails on the old
one with the counts above; the order is canonical; the named pair is truth
+ drawn decoy; the task equals the old builder's; the builder is
byte-deterministic.

**What the noise label means now.** With the pair fixed and the order
neutral, the presentation no longer depends on `shown`: on the fixed
prompts the noise process has nothing left to present itself through, and
`shown` survives only as the label of which group a step belonged to in
the October task. The groups below are kept so the numbers sit beside
§8's; on the fixed prompts no group's prompt differs from another's, so
the honest expectation is no group difference — and the fixed cell shows
none beyond noise.

### 9.1 The re-record, and its fidelity to the recording

One prompt per step, one call a step: 240 calls a model, on fresh
single-slot ctx-4096 servers under thor-admit leases — the recorder's own
server flags, so the instrument is the recording's — plus the determinism
control (the first 12 steps re-asked). On the **82 steps whose fixed
prompt is byte-identical to the recorded one** (the clean steps whose
canonical order keeps the recorded order), the live reply must equal the
October recording's vector:

| model | compared | max abs diff | the argmax is the same | vector identical | determinism (12 steps) |
|---|---|---|---|---|---|
| d1-2B | 82 of 240 | **0.0** | **82 of 82** | **82 of 82** | **12 of 12** |
| d1-3B | 82 of 240 | 0.0134 | **82 of 82** | 0 of 82 (the third decimal again, as in §7 and §8) | **12 of 12** |

The instrument is the recording's. **The box, beside the numbers:** the
box was quiet — load 3.9–4.5, 114.8–115.6 GB of memory available, the GPU
at 0 % at both starts (90 % at the 3B run's end sample), 34.9–38.6 °C,
VDD_GPU 2.4–8.7 W. The 240 calls took the 2B ~12 s (p50 31.76 ms) and the
3B ~15 s (p50 46.28 ms). No prompt failed the audit (`faulty_prompts: 0`
in both recordings).

### 9.2 What the fixed cell says

| model | accuracy before → after | truth-presented (158) | decoy-presented (82) | the 43 doubled | AUC before → after [after's interval] |
|---|---|---|---|---|---|
| d1-2B | 0.5250 → 0.4833 [0.4209, 0.5463] | 0.7975 → 0.4620 | 0.0000 → **0.5244** | 0.0000 → 0.1860 | 0.2815 → **0.5300 [0.4583, 0.5979]** |
| d1-3B | 0.3292 → **0.5208 [0.4578, 0.5832]** | 0.5000 → 0.5000 | 0.0000 → **0.5610** | 0.0000 → **0.4419** | 0.2944 → 0.4797 [0.4091, 0.5540] |

(The "before" is the October recording's own vectors; on the 3B that is
0.2944, not §8's 0.3046 — see §9.5.)

**The once-unwinnable steps are answerable.** The 43 steps whose October
prompt named one condition twice — accuracy 0.0 by arithmetic, on every
ordering of that prompt — score 0.1860 (2B) and 0.4419 (3B) once the
prompt names the truth. The whole decoy-presented group: 0.5244 and
0.5610.

**The inversion stays gone, and the confidence stays no signal.** Both
AUCs move from wholly below the coin-flip line to straddling it: the 2B's
0.2815 → 0.5300 [0.4583, 0.5979], the 3B's 0.2944 → 0.4797 [0.4091,
0.5540]. On the recorder's own trace neither model's confidence separates
right from wrong — which is what a prompt that names two conditions and no
evidence deserves: the fix removes the wrong signal; it does not add a
right one (§8's own closing paragraph).

**The 2B is still positional, and its gain is name-sorting's accident.**
It answers the first-named condition on 203 of 240 steps (84.6 %; §8.1's
86.3 % again). The canonical order puts the truth first on roughly half
the steps by the accident of which of two neighbouring condition names
sorts first, so the positional habit lands near a coin-flip instead of on
the leak. Its truth-presented accuracy falls from 0.7975 to 0.4620 for
the reason §8.1 gave: that number was the leak's own product. (73 of its
73 fixed-cell truth-presented wins are inside the 126 it used to take.)

**The 3B reads content, and it is literally the same 79 steps.** Its
truth-presented accuracy is 0.5000 before and after — and it is the same
79 steps: the §7 order-invariance showing up once more as
presentation-invariance. Its decoy-presented group goes 0.0000 → 0.5610
on prompts that finally name the truth. Its positional tally is 144/240
(60.0 %), with 96 answers on the second-named condition: content-reading,
imperfectly.

### 9.3 The τ gate on the fixed cell

The gate's semantics are the repository's (escalate when the confidence is
below τ; the canonical confidence is the top probability). The "before"
columns are the recorded arm's, as §8.3 printed them.

**d1-2B** (124 wrong, 116 right on the fixed trace — against 114 wrong,
126 right before):

| τ | before: escalated · catch · tax | fixed: escalated · catch · tax |
|---|---|---|
| 0.7 | 98 · 0.210 · 0.587 | 142 · 0.613 · 0.569 |
| 0.8 | 168 · 0.517 · 0.865 | 197 · 0.798 · 0.845 |
| 0.9 | 179 · 0.553 · 0.921 | 197 · 0.798 · 0.845 |

By group at τ = 0.8: truth-presented escalates 132 (catch 0.812, tax
0.863); decoy-presented escalates 65 (catch 0.769, tax 0.814). Inside the
30 % budget, τ = 0.625 catches 0.274 at a 0.216 tax; inside 10–20 % nothing
useful exists — the confidences jump from 0.600, where nothing escalates,
to 0.605, where 24.6 % do (§7.4's gap again).

**d1-3B** (115 wrong, 125 right on the fixed trace — against 161 wrong,
79 right before):

| τ | before: escalated · catch · tax | fixed: escalated · catch · tax |
|---|---|---|
| 0.7 | 39 · 0.093 · 0.304 | 55 · 0.200 · 0.256 |
| 0.8 | 130 · 0.460 · 0.709 | 181 · 0.783 · 0.728 |
| 0.9 | 197 · 0.733 · 1.000 | 240 · 1.000 · 1.000 |

By group at τ = 0.8: truth-presented escalates 118 (catch 0.785, tax
0.709); decoy-presented escalates 63 (catch 0.778, tax 0.761) — the
gate's word no longer depends on which group a step is in, because the
prompt no longer tells it. Inside 30 %, τ = 0.735 catches 0.200 at a
0.256 tax; inside 10–20 % nothing (nothing below τ 0.555, 22.9 % at it —
the same shape of gap).

### 9.4 The routing re-measured, and the routed cell end to end

| the fixed recorder's trace | d1-2B | d1-3B |
|---|---|---|
| accuracy | 0.4833 | **0.5208** |
| decoy-presented accuracy | 0.5244 | **0.5610** |
| AUC [interval] | **0.5300** [0.4583, 0.5979] | 0.4797 [0.4091, 0.5540] |
| the τ gate at 0.8 | catch 0.798 · tax 0.845 | **catch 0.783 · tax 0.728** |
| latency p50, matched flags, this box | **31.8 ms** | 46.3 ms |
| the steps one model is right on | the 2B only: 25 | the 3B only: **34** |

**The §8.3 route stands: this cell goes to the d1-3B** — 34 steps it is
right on that the 2B gets wrong, against 25 the other way; more accuracy
overall and in the group the leak had pinned; and at the operative τ the
gate catches about the same while taxing 12 points less. **The margins are
narrower than §8.3's table showed**: §8's arms asked the truth's +1
neighbour on the 39 noise steps where the drawn decoy came from below (the
recording's decoy field carried it; see §9.5), and that pair flattered the
route a little. What inverts is the latency row: on matched configurations
(the same server flags, the same session) **the 2B is the faster model**
(31.8 against 46.3 ms p50). §8's "the 3B was the faster model today"
compared two different servers' configurations, as that section itself
flagged; matched, the smaller model is faster — the route rests on the
answers, not on the clock.

**Applied, end to end, through the shipped seam.** The routed cell is not
a spreadsheet: `route_end_to_end.py` runs the fixed recorder's 240 states
through `core.judge`'s own `Judge` — `D1Backend` on the routed model, the
shipped `CALIBRATED_TAUS` resolving τ per ask, every attempt a
`judge.verdict` row (240 rows a run) — and reports what the operator would
see:

| the routed cell, end to end | d1-3B (the route) | d1-2B (the contrast) |
|---|---|---|
| the policy's τ | 0.76 (`tau_source: calibrated`) | 0.7 (`calibrated`) |
| gate words | act 59 · surfaced 181 | act 98 · surfaced 142 |
| catch · tax at that τ | **0.783 · 0.728** | 0.613 · 0.569 |
| accuracy | **0.5208** | 0.4833 |
| latency p50 through the seam | 46.5 ms | **30.7 ms** |

On a one-rung ladder the below-τ word is `surfaced` — the ladder's end is
surfaced rows, and acting on one is the caller's decision (the judge
README's contract). The routed run surfaces three steps in four and, when
it escalates, catches 0.783 of the errors at a 0.728 tax. That is what an
honest cell looks like: near a half by construction, a gate that knows it,
and the accuracy the cell has is the routed model's own.

### 9.5 Corrections, in writing

* **§8's "before" for the d1-3B was the replay arm's number, not the
  recording's.** §8 prints the 3B's recorded-arm AUC as 0.3046
  [0.2345, 0.3752] ("§7.3's row … the instrument is the recording's").
  The 0.3046 is §7.3's *live replay* of the recording — the same 240
  steps re-asked on the two-slot server, whose vectors differ from the
  recording's in the third decimal. The recording's own vectors score
  **0.2944 [0.2255, 0.3652]** — the number §5.1 publishes, and the number
  this section's "before" uses. §8's claim "to the fourth decimal" holds
  for the 2B (max diff 0.0, 240 of 240) and fails for the 3B by §8's own
  fidelity table two paragraphs above it (max diff 0.0168). This note's
  convention from here on: 0.2944 wherever the recording's vectors are
  meant (§5.1, §9, §12's item 2), 0.3046 only where the replay's are.
* **§8's fixed arms asked a different pair on 39 noise steps.** §8's
  `canonical` and `balanced` arms built their pair from the recording's
  decoy field — which the old recorder wrote as the *second-named
  condition* (the truth's +1 neighbour on every noise step), not as the
  decoy it had drawn. The recorder's own pair is the truth and the drawn
  decoy; the two differ on the 39 noise steps where the drawn decoy came
  from below — (truth, truth+1) against (truth, truth−1) — and on 119
  clean steps only the order moved. §8's numbers stand as the replay
  measurement on its pairs; this section's are the recorder's, and §9.4's
  route is measured on those.
* Nothing in §1–§7 changes: the leak, the positional share, the both-order
  protocol and the un-inversion are all measured on the prompts this
  section's fix removes at the source. §8 was the fix's rehearsal; §9 is
  the fix.

## 10. What this does not say

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
  arm's 0.6900). **Model disagreement is now measured too, and it is not a
  free substitute**: on the sea-state cell the both-order disagreement turns
  57 % of the 2B's steps into undecided and catches 24.6 % of its errors
  (§7), and on the 3B it is nearly empty.
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

## 11. Reproducing it

```bash
# the suites (no network, no GPU, no LLM)
.venv/bin/python -m pytest -q tests/judge/test_calibration.py   # 54 tests
.venv/bin/python -m pytest -q tests/judge/test_tracking.py      # 23 tests
.venv/bin/python -m pytest -q tests/judge                       # 209 tests

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

**§7's replay, on the Thor.** §7 was the first part of this note that
*asked a model*: the 240 recorded steps were asked again with the two named
conditions swapped, on a served d1, and the replies were recorded. §8 and
§9 ask models the same way; the three runs' wrappers are the same shape.

```bash
# the replay (needs a served d1; under a lease, on a shared box)
python3 docs/lab/judge-reversed-scripts/replay_reversed.py \
  --model d1-2B --port 8094 --out docs/lab/judge-reversed-scripts/results/replay-d1-2B.json
python3 docs/lab/judge-reversed-scripts/replay_reversed.py \
  --model d1-3B --port 8320 --out docs/lab/judge-reversed-scripts/results/replay-d1-3B.json

# the analysis (CPU, no model; reads the two replies and the October trace)
.venv/bin/python docs/lab/judge-reversed-scripts/measure_reversed.py
```

It reads the October trace
(`/home/caseydigennaro/lm-wt/liquid-study/results/exp_c_trace_d1-*.json`) and
writes `docs/lab/judge-reversed-scripts/results/replay-d1-2B.json`,
`…/replay-d1-3B.json` (every reply, the fidelity check against the
recording, the box state and the latency) and
`…/results/reversed-measurement.json` (every number in §7). The scripts and
what they read are in
[`judge-reversed-scripts/`](judge-reversed-scripts/); the suite for them is
`tests/judge/test_reversed_replay.py`.

**§8's fresh recording, on the Thor.** §8 asks a model too: the same 240
steps under the three arms (the recorded text, and the fixed pair in the
two neutral orders), on the served d1 models.

```bash
# the fresh recording (needs a served d1; under a lease, on a shared box)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/replay_fixed.py \
  --model d1-2B --port 8094 --out docs/lab/judge-prompt-fix-scripts/results/fresh-d1-2B.json
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/replay_fixed.py \
  --model d1-3B --port 8320 --out docs/lab/judge-prompt-fix-scripts/results/fresh-d1-3B.json

# the analysis (CPU, no model; reads the fresh recordings)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/measure_fixed.py
```

The replay reads the same October traces the reversed replay reads and
writes `docs/lab/judge-prompt-fix-scripts/results/fresh-d1-2B.json`,
`…/fresh-d1-3B.json` (every reply of every arm, the fidelity check, the
determinism control, the box state and the per-arm latency) and the
analysis writes `…/results/prompt-fix-measurement.json` (every number in
§8). The order policy the arms ask under is `core/judge/ordering.py`; the
suites are `tests/judge/test_ordering.py` (the policy) and
`tests/judge/test_prompt_fix.py` (the replay's arms and the analysis's
semantics).

**§9's re-recording, on the Thor.** §9 fixes the recorder and asks a model
on the prompts the fixed recorder builds.

```bash
# the audit (CPU; the 82/43 in §9's first paragraphs)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/recorder.py \
  --october /home/caseydigennaro/lm-wt/liquid-study/results/exp_c_trace_d1-2B.json

# the re-recording (needs a served d1; under a lease, on a shared box)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/rerecord.py \
  --model d1-2B --port 8094 --out docs/lab/judge-recorder-fix-scripts/results/rerecorded-d1-2B.json
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/rerecord.py \
  --model d1-3B --port 8320 --out docs/lab/judge-recorder-fix-scripts/results/rerecorded-d1-3B.json

# the analysis (CPU, no model)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/measure_rerecord.py

# the routed cell, end to end (needs the routed model served)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/route_end_to_end.py \
  --model d1-3B --port 8320 --out docs/lab/judge-recorder-fix-scripts/results/routed-end-to-end-d1-3B.json
```

(The runs went under `thor-admit` leases — `judge-recorder-fix.rerecord-*`
— and the served models under `thor-admit serve`; the wrapper adds nothing
to the numbers.) The suite for the fixed builder is
`tests/judge/test_recorder_fix.py`; what the scripts read and write is in
[`judge-recorder-fix-scripts/`](judge-recorder-fix-scripts/)'s README.

The whole core, on the ProArt at this commit: **1,669 passed, 13 skipped,
16 deselected** (the deselected are the opt-in real-engine run). The
`pxr` collection error in `tests/usd` is pre-existing — the USD extra's
wheels are not installed here.

## 12. The verdict

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
   ones (§6). The fix is upstream, in the prompt. The judge's own version
   of it — ask both orders and escalate when they disagree — **was measured,
   not assumed** (§7): it catches **24.6 %** of the 2B's errors (28 of 114,
   against 51.8 % at τ = 0.8) at twice the calls and an 86.5 % tax, and
   **2.5 %** of the 3B's (4 of 161), because the 3B's answers do not move
   when the prompt's order does. Inside a 10–30 % escalation budget it is no
   better than the τ gate (§7.4). It stays a **diagnostic**, not a gate.
8. **The prompt fix was built, and it did what the mechanism said it
   would.** The fixed state names the true condition and the decoy — the
   recorder's own docstring, which its code did not carry out — in an
   order no answer can be read off, and the cell's numbers move the way
   the leak's removal moves them: the AUC un-inverts (**0.2815 → 0.5766
   [0.5050, 0.6457]** on the 2B, the interval wholly above the line it
   was wholly below), the confidence stops reading the presentation
   (the two groups' mean confidences converge to within noise), the
   decoy-first steps become answerable (0.0 → 0.4634 on the 3B), and the
   τ gate's sign comes right (at τ = 0.8 the 3B catches 0.862 at a 0.615
   tax, against 0.460 at 0.709 before). The split §7 found holds under
   the fix: **the d1-3B passes every criterion and gains 16 points of
   accuracy; the d1-2B stays positional (86.3 %) and loses its
   leak-inflated truth-first score.** The shipped order is canonical,
   the measurement's choice (§8.2). The recommendation this note leaves
   the builder is now concrete: **route decision prompts of this shape
   to the d1-3B** — more right answers, a gate with the right sign, less
   tax, and (on the box that measured it) less latency (§8.3).
9. **The recorder was fixed at the source, and the cell's honest baseline
   is a near-coin-flip with a working gate.** The builder that left the
   truth out of 82 of its 240 prompts now names the truth and the drawn
   decoy, once each, in the canonical order, on the October seed and
   stream (§9); the trace is re-recorded and the cell re-measured on it.
   The inversion stays gone and the confidence stays no signal (both AUC
   intervals straddle the line: 0.5300 [0.4583, 0.5979] on the 2B, 0.4797
   [0.4091, 0.5540] on the 3B) — so on this cell the τ is still not a
   number to tune, it is a number to stop tuning on. What the route buys
   is accuracy, not signal: the 3B is right on 0.5208 against the 2B's
   0.4833, keeps 34 steps the 2B misses against 25 the other way, and its
   gate taxes 12 points less at the same catch — §8.3's route, re-measured
   on the recorder's own prompts and narrower, but standing. Applied end
   to end through the shipped judge seam at the calibrated τ (0.76), the
   routed cell acts on 59 steps, surfaces 181, and catches 0.783 of its
   errors when it escalates — an honest cell, whose further accuracy has
   to come from evidence in the state (the caller's perception), not from
   the order policy or the model size.

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
[`judge-calibration-scripts/`](judge-calibration-scripts/). §7 was recorded
on the **Thor** on 2026-11-01 (aarch64, CUDA 13.2, 122 GB unified) — the
replay's own box state is in §7 and in the replies' file; its scripts are in
[`judge-reversed-scripts/`](judge-reversed-scripts/). §8 was recorded on the
**Thor** the same day, against the same traces — the fresh recordings' box
state is in §8 and in the replies' files; its scripts, and the order policy
they ask under, are in
[`judge-prompt-fix-scripts/`](judge-prompt-fix-scripts/) and
`core/judge/ordering.py`. §9 was recorded on the **Thor** the same day too
— the re-recordings' box state is in §9.1 and in the recordings' files;
the fixed builder, the re-record, the analysis and the routed seam run are
in [`judge-recorder-fix-scripts/`](judge-recorder-fix-scripts/), and the
liquid-study recorder itself is patched in place on the Thor
(`scripts/exp_c_hysteresis.py`; the tested copy of both builders, old and
fixed, is `recorder.py` in that directory).*

## Limits of the both-order protocol (Hy4 adversarial review, 2026-11-01)
**Answered by §7** (the replay named in this section's last paragraph was
run on 2026-11-01; the review is kept as it was written, and the answers are
at the end of it).

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

### What the replay answered (2026-11-01, §7)

| the review's point | the measurement |
|---|---|
| 1 · the swap assumption (a purely positional model) | **Half right, and the halves are different models.** The d1-2B follows the position on **169 of its 197 two-condition steps (85.8 %)**; the d1-3B answers by content (**102 of 197, 51.8 %**) and keeps the same condition on **236 of 240 steps**. The 2B's two orders disagree on **137** steps (not 208: 43 name one condition twice, so their reversed prompt is identical, and 28 answer by content); the 3B's on **4**. The catch is **28 of 114 (24.6 %)** on the 2B and **4 of 161 (2.5 %)** on the 3B — the 71.9 % and the 38.5 % are retired (§7.2). |
| 2 · "average the confidence" fails by the document's own mechanism | **Confirmed, and measured.** The averaged confidence's AUC is **0.1104 [0.0640, 0.1628]** on the 2B — *further* below the coin-flip line than the canonical 0.2815 — and **0.3518 [0.2855, 0.4207]** on the 3B. No τ catches every wrong judgment at any τ from 0.1 to 0.95 (§7.3). |
| 3 · the averaged-vector gate was unmeasured | **Measured, and it does not cancel the position.** The averaged vector's AUC is **0.1332 [0.0922, 0.1800]** on the 2B (below the canonical 0.2815) and 0.3518 on the 3B. §6's proposal that averaging the vectors is what cancels the position is **wrong**, and the reason is in §7.3: the position is in *which condition* the confidence is about, not in its scale. |
| 4 · latency and cost were assumed | **Measured.** `/v1/systemone` takes **one state per request**, so the two prompts cannot be one call; the endpoint's two-order `n_variants` does not apply to d1, and llama.cpp sets `no_batching` for the LFM3-d1. Two requests **at the same time** save **5.0 %** (2B) and **7.5 %** (3B) at p50 on the replay's box — each call takes ~1.55× as long inside the pair — so the pair costs ~1.9× a single call either way. The p50s (73.8 ms for one call, 147.2 ms for the pair on the 2B) are the **loaded** box's: the GPU at 97–98 % and 69.8 GB resident, against the recording's idle 0–15 % and 27.7 GB (§7.5). The escalation counts are the measured ones: 137 of 240 (57.1 %), not 208. |
| 5 · content/salience rather than position | **Both, and the model decides which.** The d1-2B is the positional one (85.8 % of its two-condition steps follow the prompt's order; its truth-first prompts score 126 in the original reading and 17 in the reversed one). The d1-3B is the content one: its answers do not move when the order does, so its inverted confidence is about the state's content, not the prompt's order — and on that cell the protocol is empty. The fresh controlled set this point asked for is therefore not needed for the recorded trace: the reversed replay answers it on the trace itself. |           


