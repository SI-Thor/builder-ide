# EXP — the judge's confidence, on one definition, measured against the Brier score

**Date:** 2026-10-31 (the judge-calibration seat; **CPU-only, no GPU, no
server, no cloud key** — every vector below is a *recorded* probability
vector, replayed from disk)
**Verdict: ONE DEFINITION OF CONFIDENCE IS NECESSARY AND NOT SUFFICIENT.
MEASURED ON 1,470 RECORDED JUDGMENTS, THE CANONICAL DEFINITION (THE TOP
PROBABILITY) MAKES TWO CELLS' CONFIDENCE **ANTI-CORRELATED** WITH BEING
RIGHT (AUC 0.2815 AND 0.2944 — THE MORE SURE THE MODEL IS, THE MORE OFTEN
IT IS WRONG), MAKES A THIRD CARRY NO SIGNAL AT ALL (AUC 0.5115, AND THE
ONLY τ THAT CATCHES EVERY ERROR ESCALATES EVERY GOOD ONE), AND MAKES A
FOURTH SEPARATE CLEANLY (AUC 1.0000). THE RECALIBRATION WORKS WHERE THE
SIGNAL IS THERE — NINE OF ELEVEN CELLS KEEP A SCALE THAT IMPROVES THE
HELD-OUT BRIER — BUT A CALIBRATED τ IS STILL READ IN THE CALIBRATED SPACE,
AND ON A BINARY THE RAW FLOOR IT ASKS FOR IS NEVER BELOW A HALF.**

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
| git | `b3bb9e0` (the branch `judge-calibration`) |
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
the **newer half** (chronologically — a calibration fitted on the future
describes nothing about the past). A scale is **kept only if it improves
the held-out Brier score**; otherwise the raw confidence stands and the
report says so.

Where a scale is fitted, the judge computes the calibrated confidence as
well and **the gate reads that one**, so τ is read in the calibrated space:
*act when the calibrated probability of being right is at least τ*.
`raw_floor_for()` turns that into a number an operator can set — the raw
confidence that has to clear a calibrated τ, for a reference shape.

### 4.4 The drift rule, and why it has no invented threshold

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

### 5.2 After the recalibration (fitted on the older half, read on the newer)

| cell | scale | kept | held-out Brier | held-out ECE |
|---|---|---|---|---|
| d1-2B · liquid trace | isotonic | yes | 0.1588 → **0.1355** | 0.3198 → 0.0364 |
| d1-3B · liquid trace | isotonic | yes | 0.2018 → **0.1437** | 0.4633 → 0.3332 |
| tiles rig · judge-only | temperature (T = 0.1723) | yes | 0.0647 → **0.0499** | 0.2535 → 0.0841 |
| clef teacher · scene.enemy_visible | isotonic | yes | 0.0008 → **0.0000** | 0.0189 → 0.0000 |
| clef teacher · scene.action | isotonic | yes | 0.0089 → **0.0000** | 0.0747 → 0.0000 |
| clef teacher · scene.beacon_bearing | isotonic | **no** | 0.0327 → 0.0359 | 0.0639 → 0.0894 |
| clef teacher · scene.beacon_reachable | isotonic | yes | 0.0022 → **0.0000** | 0.0404 → 0.0000 |
| clef teacher · defect.defect_class | temperature (T = 0.05) | yes | 0.0241 → **0.0057** | 0.4344 → 0.0309 |
| clef teacher · tile.tile | isotonic | yes | 0.1199 → **0.1084** | 0.2128 → 0.1026 |
| clef student · scene.enemy_visible | isotonic | yes | 0.0160 → **0.0000** | 0.0704 → 0.0000 |
| clef student · scene.beacon_reachable | isotonic | yes | 0.0448 → **0.0000** | 0.2054 → 0.0000 |

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

## 6. What this does not say

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
  where each of the three kinds fires.

## 7. Reproducing it

```bash
# the suites (no network, no GPU, no LLM)
.venv/bin/python -m pytest -q tests/judge/test_calibration.py   # 48 tests
.venv/bin/python -m pytest -q tests/judge/test_tracking.py      # 23 tests
.venv/bin/python -m pytest -q tests/judge                       # 148 tests

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
under all three definitions, the fitted scales and the machine state.

The clef results live on another machine's worktree; copy them in, or
point the script at that path.

## 8. The verdict

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
   names the decoy first in 35 % of the steps.
3. **A confidence can carry no signal at all.** The tiles rig's AUC is
   0.5115; the only τ that catches every wrong judgment escalates all
   428. There the router has to be driven by something else — the
   band's own estimate, which the rig's own numbers prefer (0.7867
   against 0.6900).
4. **The recalibration works where the signal is there.** Ten of the
   eleven cells keep a scale that improves the held-out Brier, and the
   one that drops it is the one where the fit made the newer half worse.
   The Brier and the ECE can disagree, and a Brier-optimal scale can be
   degenerate (the teacher's `defect_class` temperature hit the bound of
   its search), so the scale is kept by the rule and read with the ECE
   beside it.
5. **A calibrated τ is read in the calibrated space, and a binary's raw
   floor is never below a half.** The tiles rig's calibrated τ of 0.5
   corresponds to a raw 0.2749; on a binary, τ = 0.5 escalates nothing,
   because one of two options always holds at least half the mass.
6. **The drift thresholds are measured, not invented**: the cell's own
   history is the noise floor, and the three drift kinds are the
   separability falling to the coin-flip line, the ECE moving further
   than it ever has, and a fitted scale going stale.

The practical consequence for the builder: **the confidence gate's τ is a
per-cell parameter with a measured value, not a default.** `core/judge`
now computes one definition for every backend and records it, the nightly
job writes the calibration report per cell, and the morning report carries
one line per drifting model. Where a cell's AUC says the number carries
no signal, the cell's τ is not a number to tune — it is a number to stop
using.

---

*Recorded 2026-10-31 on the ProArt (WSL2, Python 3.14.4, numpy 2.5.4),
CPU-only; the vectors were recorded on the Thor (the liquid study, the
tiles rig) and on Cloudflare's Workers AI (the clef cascade), and their
own box states are in their own files. The scripts are in
[`judge-calibration-scripts/`](judge-calibration-scripts/).*
