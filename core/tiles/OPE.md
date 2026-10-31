# OPE — what a new chooser would have earned

**The question.** The seat refits the chooser every night from the log, and
it only ever learns from what it played. Before a policy swap the builder
wants a number the loop does not produce:

> *the new chooser looks better on the tiles it likes. What would it have
> earned on the tiles the old one played?*

The world does not re-run, so the answer is estimated from the log:
**importance sampling (IPS)**, **self-normalised importance sampling
(SNIPS)** and the **doubly robust estimator (DR)**.

`core/tiles/ope.py` implements all three, with the variance, the interval,
the weight diagnostics, and a negative control.

## The gap this closes: the log had no propensity

An importance weight is `pi_new(action | context) / pi_old(action | context)`.
The denominator is a number about the **chooser's own mind at that moment**:
the exploration rate it was on, and the tile it would have picked greedily
then. A play record that does not carry it cannot be weighted.

So the seat now measures its own propensity:

| where | what |
|---|---|
| `chooser.py` | `choose()` computes the probability of the choice **at the moment it makes it** and puts it on `Choice.propensity` |
| `models.py` | `PlayRecord.propensity` and `PlayRecord.candidates` carry it and the eligible set into the log |
| `plays.py` | `record_play(..., propensity=..., candidates=...)` writes them; the fold reads them back |
| `ope.py` | `evaluate()` **refuses** to weight a play whose propensity is missing, and says how many it dropped |

The propensity cannot be reconstructed after the fact: the exploration rate
decays and the greedy arm moves as the chooser learns, so a propensity
computed later would be a different number from the one the choice was
actually drawn from. **Measured**: over 20,000 draws of an ε-greedy
chooser, the recorded propensities match the observed frequencies to within
0.0011 (0.8325 / 0.0830 / 0.0844 observed against 0.8333 / 0.0833 / 0.0833
recorded). The full run is in `docs/lab/exp-tiles-ope.md`.

A missing propensity is **never** defaulted to 1.0. A default is not a
neutral placeholder; it is a bias in a direction nobody can see.

## The estimators

| | what it is | when it is the right one |
|---|---|---|
| **IPS** | `mean(w r)`, unbiased | the weights are tame; it shows a corrupted log most honestly |
| **SNIPS** | `sum(w r) / sum(w)`, bounded | one weight dwarfs the rest |
| **DR** | the direct method plus `w (r - q)` | the reward model is good, and the variance matters |

Every estimate carries: the value, the standard error, the 95% interval,
the **denominator** (`n` of `n_offered` plays weighted), Kish's **effective
sample size**, the **largest weight**, the **coverage** (the share of plays
that could be weighted at all) and the **support** (the share the target
policy could have chosen).

## What was measured, and what it cost

The world is synthetic and its truth is exact — three tiles with known win
rates and a logging policy whose value is computable in closed form — so
the estimators are checked against a number that was written down before
they ran.

* **All three land on the truth.** Target policy's true value 0.853694:
  IPS 0.852827, SNIPS 0.851545, DR 0.851170; every interval covers it.
* **A uniformly scaled propensity error: IPS is off by exactly the factor,
  SNIPS is exactly unchanged, and the effective sample size is unchanged.**
  The corruption is invisible to the estimator that normalises, and to the
  diagnostic that says how many plays are carrying the estimate. Only the
  raw largest weight moves (1.3030 → 2.6060).
* **A guessed (uniform) propensity pushes IPS out of the reward range
  entirely** (1.608412 — above what any play could pay) while SNIPS moves
  by +0.028 and stays plausible-looking. The corruption a system that
  *guesses* produces is the one the self-normalised estimator barely
  notices.
* **A permuted propensity is the one the diagnostics do catch**: the
  effective sample size collapses from 25,257 to 11,817 and the largest
  weight grows from 1.3030 to 9.6280.
* **Cross-fitting is correct and, at this size, nearly free**: at 200 plays
  it widens the doubly robust interval by 2% of the standard error; at
  30,000 the gap has vanished under the sixth decimal, because the reward's
  own noise dominates the model's error long before the log is big.

Full numbers, and how to reproduce them: `docs/lab/exp-tiles-ope.md`.

## What it refuses

* a play with **no propensity** — dropped and counted, never assumed;
* a log with **no usable plays** — refused (`no_usable_plays`);
* a **propensity outside (0, 1]** — refused (`bad_propensity`): it cannot
  be true;
* a target policy with **no support** on the log — refused (`no_support`):
  there is nothing to estimate;
* a **doubly robust estimate without a reward model** — refused: it would
  be IPS with extra steps;
* a **softmax policy with no candidate set** — refused: it has nothing to
  normalise over.

## Using it

```python
from core.tiles.ope import SoftmaxTarget, evaluate

target = SoftmaxTarget(
    scores=lambda context, tile_id: score_for(tile_id),
    temperature=1.0,
    name="ranker/v2",
)
estimate = evaluate(fold_plays(ledger.events()), target, method="snips")
print(estimate.line())
```

`method="dr"` additionally needs a reward model — `BanditRewardModel(chooser)`
for the chooser's own estimate, or `CrossFittedRewardModel(records, folds=5)`
for the honest version.

## The caveat that is not a caveat

The logging policy here is **learning**, so it is not stationary: the
exploration rate decays and the greedy arm moves. That is fine, and it is
why the propensity is recorded **per play** rather than reconstructed from
the chooser's final state: a per-decision propensity is what makes the
importance weight correct for that play. What does *not* follow is a claim
about a policy that was never run — this estimates the target policy's
value **on the contexts the logger visited**, which is what the log can
speak to.
