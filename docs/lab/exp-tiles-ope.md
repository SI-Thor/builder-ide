# EXP — off-policy evaluation for the tiles chooser: the log had no propensity

**Date:** 2026-10-31
**Verdict: THE TILES LOG COULD NOT ANSWER "WHAT WOULD THE NEW CHOOSER HAVE
EARNED?" — NOT BECAUSE THE ESTIMATORS WERE MISSING, BUT BECAUSE THE LOG
DID NOT CARRY THE NUMBER THE ESTIMATORS NEED. The seat now measures its own
propensity, and the three estimators land on an exact truth.**

---

## 1. The idea

The tiles seat refits the chooser every night from the log, and it only
ever learns from what it played. Before a policy swap the builder wants a
number the loop does not produce:

> *the new chooser looks better on the tiles it likes. What would it have
> earned on the tiles the old one played?*

The world does not re-run, so the answer has to come from the log. That is
what off-policy evaluation is for: IPS, self-normalised IPS, and the doubly
robust estimator, with their variances and their intervals.

## 2. The hypothesis

> The estimators can score a new policy from the old log, with an interval,
> and the log can be made to carry what they need.

## 3. The setup

- `core/tiles/ope.py` — the estimators. numpy only, plus the repo's own
  `core.tiles`.
- `tests/tiles/test_ope.py` — 21 tests, no fixtures, no network, no GPU.
- `docs/lab/tiles-ope-scripts/measure_ope.py` — prints every number below.

**The world is synthetic, and its truth is exact.** Three tiles with known
win rates (0.2 / 0.6 / 0.9), a logging policy whose value is computable in
closed form, and a target policy whose value is computable the same way.
Every estimate below is checked against a number that was written down
before the estimator ran — not against another estimator.

| | |
|---|---|
| Machine | **the builder-ide sandbox** — x86_64 Linux, Python 3.12.14, numpy 2.5.4, pytest 9.2.0 |
| **Not** | the Thor. Nothing here needs the box: it is arithmetic on a synthetic world. The acceptance run on the box is still yours. |
| Plays | 30,000 |
| Logging policy | softmax over (0, 1, 2) → (0.090031, 0.244728, 0.665241) |
| Target policy | softmax over (0, 2, 4) → (0.015876, 0.117310, 0.866813) |
| Logging policy's true value | **0.763560** |
| Target policy's true value | **0.853694** |

## 4. The gap: the log carried no propensity

An importance weight is `pi_new(action | context) / pi_old(action | context)`.
The denominator is a number about the **chooser's own mind at that moment**:
the exploration rate it was on, and the tile it would have picked greedily
then.

`PlayRecord` had `chooser` and `chooser_version`. It had **no propensity**,
and no record of the eligible set. So the estimators were not
"missing" — they were *impossible*: there was no number to divide by.

The propensity also cannot be reconstructed after the fact. The
exploration rate decays with the plays and the greedy arm moves as the
chooser learns, so a propensity computed later is a different number from
the one the choice was drawn from. It has to be measured **at the choice**.

The fix, in four places:

| where | what |
|---|---|
| `core/tiles/chooser.py` | `choose()` computes the probability of the choice and puts it on `Choice.propensity` |
| `core/tiles/models.py` | `PlayRecord.propensity`, `PlayRecord.candidates` |
| `core/tiles/plays.py` | `record_play(..., propensity=..., candidates=...)`; the fold reads them back |
| `core/tiles/ope.py` | `evaluate()` refuses to weight a play whose propensity is missing, and counts what it dropped |

**A missing propensity is never defaulted to 1.0.** A default is not a
neutral placeholder; it is a bias in a direction nobody can see.

## 5. The numbers

### 5.1 The estimators land on the truth

| estimator | value | 95% CI | se | effective n | max weight |
|---|---|---|---|---|---|
| **truth** | **0.853694** | | | | |
| IPS | 0.852827 | [0.846398, 0.859257] | 0.003280 | 25,257.1 | 1.3030 |
| SNIPS | 0.851545 | [0.847541, 0.855548] | 0.002043 | 25,257.1 | 1.3030 |
| DR | 0.851170 | [0.847273, 0.855066] | 0.001988 | 25,257.1 | 1.3030 |

Every interval covers the truth. On the logging policy itself, IPS and SNIPS
both give 0.762200 (CI [0.757382, 0.767018]) against a truth of 0.763560.

### 5.2 The negative control: propensities that are wrong

| corruption | IPS | SNIPS | effective n | max weight |
|---|---|---|---|---|
| none (honest) | 0.851545 | 0.851545 | 25,257.1 | 1.3030 |
| **scaled ×0.5** | **1.705654** | **0.851545** | 25,257.1 | 2.6060 |
| **uniform (guessed)** | **1.608412** | 0.881454 | 21,990.1 | 2.6004 |
| **shuffled** | 1.600963 | 0.878707 | **11,817.3** | **9.6280** |

Four measured facts, and the third is the one to keep:

1. **A uniformly scaled propensity error moves IPS by exactly the factor**
   (0.851545 → 1.705654 = 2×) **and leaves SNIPS exactly unchanged** —
   SNIPS divides by the sum of the weights, so a uniform scale cancels.
2. **The effective sample size is blind to it too.** Kish's ESS is a ratio
   of sums of weights, so it is scale-invariant: 25,257.1 either way. The
   *only* diagnostic that moves is the raw largest weight (1.3030 → 2.6060).
   **So a scaled propensity error is invisible to the estimator that
   normalises and to the diagnostic that says how many plays are carrying
   the estimate.** It has to be caught by cross-checking, not by looking
   harder at the weights.
3. **A guessed (uniform) propensity is the corruption the self-normalised
   estimator nearly forgives.** IPS leaves the reward range entirely
   (1.608412 — above what any play could pay, and the estimate says so);
   SNIPS moves by +0.028 and still looks like a plausible win rate. A
   system that *guesses* a propensity and then reports a self-normalised
   estimate would show a number nobody could argue with. **This is the
   argument for logging the propensity and refusing to estimate without
   it.**
4. **A permuted propensity is the one the diagnostics do catch**: the
   effective sample size collapses from 25,257 to 11,817 (−53%) and the
   largest weight grows from 1.3030 to 9.6280 (7.4×).

### 5.3 The chooser's recorded propensity is the propensity it has

ε-greedy, ε = 0.25, three eligible tiles, 20,000 draws, the chooser not
updated between draws:

| tile | observed frequency | recorded propensity | difference |
|---|---|---|---|
| tile_a (the greedy one) | 0.8325 | 0.8333 | −0.0008 |
| tile_b | 0.0830 | 0.0833 | −0.0003 |
| tile_c | 0.0844 | 0.0833 | +0.0011 |

The standard error of a frequency at n = 20,000 is 0.0026, so all three are
inside half a standard error. **The number the record carries is the number
the choice was drawn from** — which is the whole link the estimators rest
on, and it is the one thing that had to be measured rather than reasoned
about.

### 5.4 Cross-fitting: correct, and nearly free at this size

The doubly robust estimator's variance is understated when the reward model
is fitted on the plays it predicts. Measured (contexts vary over two
phases, the model buckets on the phase):

| plays | in-sample se | cross-fitted se | gap |
|---|---|---|---|
| 200 | 0.025954 | 0.026473 | +0.000519 (2.0%) |
| 1,000 | 0.011522 | 0.011562 | +0.000041 (0.4%) |
| 5,000 | 0.005040 | 0.005044 | +0.000005 (0.1%) |
| 30,000 | 0.001988 | 0.001988 | +0.000000 |

**The control fired, and it fired small.** The reward's own noise (a
Bernoulli reward, variance ≈ 0.09) dominates the model's error long before
the log is big, so the in-sample optimism is at most 2% of the standard
error and vanishes. Cross-fitting is kept because it is the right thing,
not because it bought anything measurable here.

## 6. The failure this experiment caught

**The first implementation of the doubly robust estimator was wrong**, and
it was wrong in a way that looked right. It used the *logged* action's
reward-model prediction as the model term:

```
V = mean(q(x_i, a_i) + w_i (r_i - q(x_i, a_i)))
```

With a **perfect** reward model this estimator reports the **logging**
policy's value (0.761429) rather than the target's (0.853694) — the model
term cancels the correction term instead of completing it. The direct
method has to be the model's prediction averaged over the **target
policy's own distribution** over the eligible set:

```
V = mean( sum_a pi_e(a|x_i) q(x_i, a)  +  w_i (r_i - q(x_i, a_i)) )
```

With that form the two halves cancel when the propensities are right and
the model is wrong, and the model term carries the target's value when the
model is right — which is the whole of "doubly robust". The oracle test is
what caught it: the estimate was 0.09 away from a truth it could not
possibly be wrong about.

A second bug, found by the same test: the estimate was computed **before**
the support check, so a target with no support produced a division by zero
and a NaN instead of a refusal. The support check now comes first.

## 7. What this does not say

* **It is a synthetic world.** The truth is exact because the world was
  built to have an exact truth. On the real night the reward model has to
  be good enough for DR to be worth using, and nothing here says it is.
* **The log's propensities do not exist yet.** Every play recorded before
  this change has `propensity = None` and **cannot be weighted**: the
  estimator refuses them and counts them. The first night's log will be
  mostly unweightable; the value of the estimator starts the night the
  chooser starts recording.
* **The candidates travel with the play**, so the payload grows. The
  ledger's cap is 4 KiB and a play that would exceed it is refused, not
  truncated — which is the cap working as designed, but a context with more
  than ~200 eligible tiles would start refusing plays.

## 8. Reproducing it

```bash
cd ~/lm-wt/tiles
.venv/bin/python -m pytest -q tests/tiles/test_ope.py     # 21 tests
PYTHONPATH=. .venv/bin/python docs/lab/tiles-ope-scripts/measure_ope.py
```

Every number in §5 comes out of that script.
