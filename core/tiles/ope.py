"""Off-policy evaluation: what would a **new** chooser have earned?

The seat learns every night from the log, and it only ever learns from what
it played. That is the right way to learn and the wrong way to decide: the
builder's question before a policy swap is always

    *the new chooser looks better on the tiles it likes. What would it have
    earned on the tiles the old one played?*

The world does not re-run, so the answer cannot be measured directly. It
can be **estimated from the log**, with the estimators built for exactly
this: importance sampling (IPS), self-normalised importance sampling
(SNIPS), and the doubly robust estimator (DR).

**The log has to carry the propensity, and it did not.** An importance
weight is ``pi_new(action | context) / pi_old(action | context)``, and the
denominator is a number about the *chooser's own mind at that moment*: the
exploration rate it was on, and the tile it would have picked greedily
then. A play record that does not carry it cannot be weighted, and a
default of 1.0 is not a neutral placeholder — it is a lie that biases the
estimate in a direction nobody can see.

So this seat measures its own propensity:

* :class:`~core.tiles.chooser.ContextualBandit` computes the probability of
  the choice it is making *at the moment it makes it* and puts it on the
  :class:`~core.tiles.chooser.Choice`;
* the play record carries it (:attr:`~core.tiles.models.PlayRecord.propensity`)
  and the eligible set it was chosen from
  (:attr:`~core.tiles.models.PlayRecord.candidates`), because a target
  policy's probability has to normalise over the same candidate set;
* :func:`evaluate` **refuses** to weight a play whose propensity is missing,
  and says how many it dropped. It does not assume, and it does not quietly
  average them in.

**What the estimates are worth.** Every number here comes with its
denominator, an interval, and the weight diagnostics that say whether the
interval means anything: the effective sample size (Kish), the largest
weight, and the share of plays the target policy could have chosen. An IPS
estimate off a log where the target barely agrees with the logger is not a
number, it is a rounding of the logger's own value — and the diagnostics
say so instead of the estimate looking precise.

Three estimators, and when each is the right one:

* **IPS** — unbiased, but the variance is the whole story: one play where
  the target was 30 times likelier than the logger can move the estimate
  more than a thousand ordinary plays. It is the one to quote when the
  weights are tame, and it is the one that shows a corrupted log most
  honestly, because it does not normalise the damage away.
* **SNIPS** — self-normalised, so it is bounded by the rewards it saw and
  it survives a log where one weight dwarfs the rest. The price is a small
  bias, and the price of *that* is that SNIPS cannot see a uniformly
  corrupted propensity: normalising by the sum of the weights cancels a
  scale error exactly. Both facts are measured in
  ``docs/lab/exp-tiles-ope.md``.
* **DR** — doubly robust: correct if either the reward model or the
  propensities are right, and it is the only one of the three that can use
  the tiles the target policy would have chosen. Its variance is
  understated when the reward model is fitted on the plays it predicts, so
  :class:`CrossFittedRewardModel` fits the model on the folds it does not
  predict.

Nothing here replays the game, and nothing here needs the renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from .chooser import ContextualBandit
from .models import PlayRecord

__all__ = [
    "BanditRewardModel",
    "CrossFittedRewardModel",
    "DeterministicTarget",
    "FixedTarget",
    "METHODS",
    "OPEError",
    "OPEEstimate",
    "RewardModel",
    "SoftmaxTarget",
    "TargetPolicy",
    "corrupt_propensities",
    "evaluate",
    "weights_for",
]


class OPEError(Exception):
    """An estimate that cannot be made, with the reason it cannot.

    Raised rather than returned, because every one of these is a case where
    a number would be a fabrication: no usable plays, no support, a
    propensity that cannot be true, a reward model that is missing.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# --- the policies ------------------------------------------------------------


@runtime_checkable
class TargetPolicy(Protocol):
    """The policy whose value is being estimated."""

    name: str

    def probability(
        self,
        context: Mapping[str, Any],
        tile_id: str,
        candidates: Sequence[str],
    ) -> float:
        """The probability this policy gives to ``tile_id`` in ``context``.

        ``candidates`` is the eligible set the choice was made from. A policy
        that normalises over it needs it; a policy whose probabilities are
        already absolute may ignore it.
        """
        ...


@dataclass(frozen=True)
class SoftmaxTarget:
    """A policy that prefers the higher-scoring tile, softly.

    ``scores(context, tile_id)`` is a number; the probability is the softmax
    of those numbers over the eligible set at ``temperature``. A temperature
    of zero is the deterministic argmax. This is the shape a learned ranker
    takes: a score per (context, tile), normalised over the options.
    """

    scores: Callable[[Mapping[str, Any], str], float]
    temperature: float = 1.0
    name: str = "softmax"

    def probability(
        self,
        context: Mapping[str, Any],
        tile_id: str,
        candidates: Sequence[str],
    ) -> float:
        if not candidates:
            raise OPEError(
                "no_candidates",
                "a softmax policy has nothing to normalise over without the "
                "eligible set",
            )
        if tile_id not in candidates:
            # A policy never picks a tile that was not an option.
            return 0.0
        if self.temperature <= 0.0:
            best = max(candidates, key=lambda t: (self.scores(context, t), t))
            return 1.0 if tile_id == best else 0.0
        raw = np.array(
            [self.scores(context, t) for t in candidates], dtype=float
        )
        raw = raw - raw.max()
        weights = np.exp(raw / self.temperature)
        total = float(weights.sum())
        if total <= 0.0:
            raise OPEError(
                "degenerate_policy", "the softmax policy's weights summed to zero"
            )
        return float(weights[candidates.index(tile_id)] / total)


@dataclass(frozen=True)
class DeterministicTarget:
    """A policy that always picks the same tile for a context.

    The practical shape of a policy swap — "the new chooser would have
    picked this one" — and the shape with the worst variance: it only gets
    weight from the plays the logger agreed with, and it has no support at
    all where they disagreed.
    """

    pick: Callable[[Mapping[str, Any], Sequence[str]], str]
    name: str = "deterministic"

    def probability(
        self,
        context: Mapping[str, Any],
        tile_id: str,
        candidates: Sequence[str],
    ) -> float:
        if not candidates:
            raise OPEError(
                "no_candidates",
                "a deterministic policy cannot choose without the eligible set",
            )
        chosen = self.pick(context, tuple(candidates))
        return 1.0 if chosen == tile_id else 0.0


@dataclass(frozen=True)
class FixedTarget:
    """A policy whose probability for each tile is already known.

    Useful for a policy that does not depend on the context (a fixed mix),
    and for the negative controls: it needs no candidate set, so it can
    score a log that never recorded one.
    """

    probabilities: Mapping[str, float]
    name: str = "fixed"

    def probability(
        self,
        context: Mapping[str, Any],
        tile_id: str,
        candidates: Sequence[str],
    ) -> float:
        return float(self.probabilities.get(tile_id, 0.0))


# --- the reward models -------------------------------------------------------


@runtime_checkable
class RewardModel(Protocol):
    """What the world would have paid, predicted for an action.

    The prediction is asked for **per action**, not per play: the doubly
    robust estimator needs the model's opinion about the actions the target
    policy *would* have chosen, including the ones the logger never
    played. A model that can only score what was played cannot be used
    here, and that is the point — the direct method's whole contribution is
    the model's opinion about the unplayed actions.

    The record is passed alongside the action so that a cross-fitted model
    can pick the fold: a play is scored by a model that never saw it.
    """

    name: str

    def predict(self, record: PlayRecord, tile_id: str) -> float:
        """The predicted reward of ``tile_id`` in this play's context."""
        ...


@dataclass(frozen=True)
class BanditRewardModel:
    """The chooser's own estimate of a tile's reward in a context.

    The reward model the seat already has. It is fitted on the log, so used
    in-sample it makes the DR estimate optimistic — see
    :class:`CrossFittedRewardModel` for the honest version.
    """

    chooser: ContextualBandit
    name: str = "bandit"

    def predict(self, record: PlayRecord, tile_id: str) -> float:
        bucket = self.chooser.bucket(record.context)
        return float(self.chooser.estimate(bucket, tile_id))


class CrossFittedRewardModel:
    """K reward models, each fitted on the folds it does not predict.

    The doubly robust estimator's variance is understated when the reward
    model is fitted on the very plays it predicts, because the model has
    already seen the answer it is being asked for. The fix is the standard
    one: split the plays into folds, fit a model on all but each fold, and
    predict a play with a model that never saw it.
    """

    name = "cross-fitted"

    def __init__(
        self,
        records: Sequence[PlayRecord],
        *,
        folds: int = 5,
        seed: int = 0,
        chooser: ContextualBandit | None = None,
        feature_keys: Sequence[str] = (),
    ) -> None:
        if folds < 2:
            raise ValueError("cross-fitting needs at least two folds")
        self.records = list(records)
        self.folds = folds
        rng = np.random.default_rng(seed)
        order = rng.permutation(len(self.records))
        self._fold_of: dict[str, int] = {}
        for position, index in enumerate(order):
            self._fold_of[self.records[index].id] = position % folds
        self._models: list[ContextualBandit] = []
        for fold in range(folds):
            if chooser is not None:
                model = chooser
            else:
                model = ContextualBandit(feature_keys=tuple(feature_keys))
            model.fit(
                [r for r in self.records if self._fold_of.get(r.id, 0) != fold]
            )
            self._models.append(model)

    def predict(self, record: PlayRecord, tile_id: str) -> float:
        model = self._models[self._fold_of.get(record.id, 0) % self.folds]
        bucket = model.bucket(record.context)
        return float(model.estimate(bucket, tile_id))


# --- the estimate ------------------------------------------------------------


@dataclass(frozen=True)
class OPEEstimate:
    """One estimate, with everything needed to believe it.

    ``value`` is the estimated reward the target policy would have earned
    on the logged plays. ``stderr`` is the analytic standard error of the
    estimator; ``ci_low``/``ci_high`` are the interval (the bootstrap's
    percentiles when a bootstrap was asked for, the normal approximation
    otherwise).

    The diagnostics are not decoration:

    * ``effective_n`` — Kish's effective sample size, ``(sum w)^2 / sum w^2``.
      When it is a small fraction of ``n``, the interval is wide and the
      estimate is mostly the logger's own value.
    * ``coverage`` — the share of the offered plays that could be weighted
      at all. Plays without a propensity are dropped, not guessed at, and
      this says how many.
    * ``max_weight`` — the largest importance weight. One weight above a
      hundred means one play is carrying the estimate.
    * ``support`` — the share of plays the target policy could have chosen
      at all. Zero support is an error, not a small number.
    """

    method: str
    value: float
    stderr: float
    ci_low: float
    ci_high: float
    n: int
    n_offered: int
    effective_n: float
    max_weight: float
    coverage: float
    support: float
    warnings: tuple[str, ...] = ()

    @property
    def basis(self) -> str:
        """The denominator, kept with the number."""
        return (
            f"{self.n}/{self.n_offered} plays weighted "
            f"(effective n {self.effective_n:.1f})"
        )

    def line(self) -> str:
        """The one line the morning can show."""
        return (
            f"{self.method} {self.value:.4f} "
            f"95% CI [{self.ci_low:.4f}, {self.ci_high:.4f}] "
            f"· {self.basis}"
        )


def weights_for(
    records: Sequence[PlayRecord],
    target: TargetPolicy,
    *,
    clip: float | None = None,
) -> tuple[np.ndarray, np.ndarray, tuple[PlayRecord, ...], list[str]]:
    """The importance weights and the rewards they multiply.

    Returns ``(weights, rewards, used, warnings)``. A play whose logging
    propensity is missing is **dropped** — it cannot be weighted, and
    assuming a propensity is how an estimate becomes a fabrication. The
    warnings say how many were dropped.

    ``clip`` caps the weights (the standard remedy for a log with one
    enormous weight). Clipping trades the bias for the variance and says so
    in the warnings.
    """
    weights: list[float] = []
    rewards: list[float] = []
    used: list[PlayRecord] = []
    warnings: list[str] = []
    dropped = 0
    clipped = 0

    for record in records:
        propensity = record.propensity
        if propensity is None:
            dropped += 1
            continue
        if not (propensity > 0.0) or propensity > 1.0 + 1e-9:
            raise OPEError(
                "bad_propensity",
                f"play {record.id} has a logging propensity of {propensity!r}; "
                "a probability is in (0, 1]",
            )
        target_p = float(
            target.probability(record.context, record.tile_id, record.candidates)
        )
        if target_p < 0.0 or target_p > 1.0 + 1e-9:
            raise OPEError(
                "bad_target_probability",
                f"play {record.id}: the target policy gives {target_p!r} to "
                f"{record.tile_id}",
            )
        weight = target_p / propensity
        if clip is not None and weight > clip:
            weight = clip
            clipped += 1
        weights.append(weight)
        rewards.append(float(record.reward))
        used.append(record)

    if dropped:
        warnings.append(
            f"{dropped} of {len(records)} plays had no logging propensity and "
            "were not weighted"
        )
    if clipped:
        warnings.append(f"{clipped} weights were clipped at {clip}")

    return (
        np.asarray(weights, dtype=float),
        np.asarray(rewards, dtype=float),
        tuple(used),
        warnings,
    )


def evaluate(
    records: Sequence[PlayRecord],
    target: TargetPolicy,
    *,
    method: str = "snips",
    reward_model: RewardModel | None = None,
    alpha: float = 0.05,
    clip: float | None = None,
    bootstrap: int = 0,
    seed: int = 0,
) -> OPEEstimate:
    """Estimate what ``target`` would have earned on the logged plays.

    ``method`` is ``"ips"``, ``"snips"`` or ``"dr"``. The doubly robust
    estimator needs a ``reward_model``; without one it is refused rather
    than quietly reduced to IPS.

    ``bootstrap`` asks for a bootstrap interval instead of the analytic one
    (percentiles over ``bootstrap`` resamples, seeded, so the same call
    gives the same interval). The analytic interval is the normal
    approximation, which is optimistic when the weights are heavy-tailed —
    the diagnostics say when that is the case.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {METHODS}")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha is a rate in (0, 1)")
    if bootstrap < 0:
        raise ValueError("bootstrap is a count")

    weights, rewards, used, warnings = weights_for(records, target, clip=clip)
    n = int(weights.size)
    if n == 0:
        raise OPEError(
            "no_usable_plays",
            "no play could be weighted: the log has no logging propensities",
        )

    if method == "dr":
        if reward_model is None:
            raise OPEError(
                "no_reward_model",
                "the doubly robust estimator needs a reward model; without "
                "one it is just IPS with extra steps",
            )
        q, model_term = _dr_terms(used, target, reward_model)
    else:
        q = None
        model_term = None

    total_weight = float(weights.sum())
    if total_weight <= 0.0:
        raise OPEError(
            "no_support",
            "the target policy's probability of every logged play was zero: "
            "it never agrees with the log, so there is nothing to estimate",
        )

    value, variance = _estimate(weights, rewards, q, method, model_term)

    effective_n = total_weight**2 / float((weights**2).sum())

    if bootstrap:
        ci_low, ci_high = _bootstrap_interval(
            weights, rewards, q, method, bootstrap, seed, alpha, model_term
        )
        stderr = (ci_high - ci_low) / (2.0 * _z(alpha))
    else:
        stderr = math.sqrt(max(variance, 0.0))
        z = _z(alpha)
        ci_low = value - z * stderr
        ci_high = value + z * stderr

    # The reward is in [0, 1]; the estimate can leave that range when the
    # weights are wild, and the interval is clipped to the range the reward
    # can take rather than to a range the estimate happens to sit in.
    ci_low = max(0.0, ci_low)
    ci_high = min(1.0, ci_high)
    if value > 1.0:
        warnings.append(
            f"the estimate {value:.4f} is above the reward range: the weights "
            "are carrying it past what any play could pay"
        )
    if value < 0.0:
        warnings.append(
            f"the estimate {value:.4f} is below the reward range: the weights "
            "are carrying it past what any play could pay"
        )

    support = float(np.mean(weights > 0.0))
    if support < 0.5:
        warnings.append(
            f"the target policy had support on only {support:.0%} of the "
            "plays: the estimate leans on the logger"
        )
    if n > 1 and effective_n < 0.5 * n:
        warnings.append(
            f"the effective sample size is {effective_n:.1f} of {n} plays: "
            "one or two plays are carrying the estimate"
        )
    if float(weights.max()) > 20.0:
        warnings.append(
            f"the largest weight is {float(weights.max()):.1f}: one play is "
            "carrying the estimate, and a bootstrap interval is the honest one"
        )

    return OPEEstimate(
        method=method.upper() if method == "dr" else method.upper(),
        value=value,
        stderr=stderr,
        ci_low=ci_low,
        ci_high=ci_high,
        n=n,
        n_offered=len(records),
        effective_n=effective_n,
        max_weight=float(weights.max()),
        coverage=n / len(records) if records else 0.0,
        support=support,
        warnings=tuple(warnings),
    )


#: The estimators, and what each one needs.
METHODS: tuple[str, ...] = ("ips", "snips", "dr")


# --- internals ---------------------------------------------------------------


def _z(alpha: float) -> float:
    """The two-sided normal quantile for a level."""
    return NormalDist().inv_cdf(1.0 - alpha / 2.0)


def _dr_terms(
    records: Sequence[PlayRecord],
    target: TargetPolicy,
    reward_model: RewardModel,
) -> tuple[np.ndarray, np.ndarray]:
    """The two halves of the doubly robust estimator.

    ``q[i]`` is the model's prediction for the action that was **played**,
    and ``model_term[i]`` is the direct method: the model's prediction
    averaged over the **target policy's own distribution** over the
    eligible set.

    The direct method has to be over the target's distribution, not the
    logged action. A model that is right about everything says the same
    thing either way, but the estimator's consistency depends on it: with
    the logged action's prediction in that slot, a perfect model makes the
    estimator report the **logging** policy's value instead of the
    target's. The two terms cancel when the propensities are right and
    the model is wrong, and the model term carries the target's value when
    the model is right — which is the whole of "doubly robust".
    """
    q: list[float] = []
    model_term: list[float] = []
    for record in records:
        candidates = tuple(record.candidates)
        if not candidates:
            raise OPEError(
                "no_candidates",
                "the doubly robust estimator needs the eligible set: the "
                "direct method asks the model about the actions the target "
                "policy would have chosen",
            )
        q.append(float(reward_model.predict(record, record.tile_id)))
        total = 0.0
        for candidate in candidates:
            probability = float(
                target.probability(record.context, candidate, candidates)
            )
            if probability <= 0.0:
                continue
            total += probability * float(
                reward_model.predict(record, candidate)
            )
        model_term.append(total)
    return (
        np.asarray(q, dtype=float),
        np.asarray(model_term, dtype=float),
    )


def _estimate(
    weights: np.ndarray,
    rewards: np.ndarray,
    q: np.ndarray | None,
    method: str,
    model_term: np.ndarray | None = None,
) -> tuple[float, float]:
    """The point estimate and its asymptotic variance.

    * **IPS** — ``mean(w r)``. The variance is the variance of the
      weighted observations, because the estimator is their mean.
    * **SNIPS** — ``sum(w r) / sum(w)``. The variance is the delta method's:
      ``mean(w^2 (r - V)^2) / (n mean(w)^2)``.
    * **DR** — ``mean(direct method + w (r - q))``. The variance is the
      **sum** of the two terms' variances: a conservative bound, because
      the two are not independent and the true covariance is not known.
      With a model that is right about every action the direct method is
      constant, and the whole variance is the correction term's.
    """
    n = weights.size
    if method == "ips":
        weighted = weights * rewards
        value = float(weighted.mean())
        variance = float(weighted.var(ddof=1)) / n if n > 1 else 0.0
        return value, variance
    if method == "snips":
        total = float(weights.sum())
        value = float((weights * rewards).sum() / total)
        mean_weight = total / n
        if mean_weight <= 0.0:
            return value, 0.0
        variance = float(np.mean((weights * (rewards - value)) ** 2)) / (
            n * mean_weight**2
        )
        return value, variance
    if method == "dr":
        assert q is not None and model_term is not None
        residual = weights * (rewards - q)
        value = float(np.mean(model_term + residual))
        variance = 0.0
        if n > 1:
            variance = float(residual.var(ddof=1)) / n
            variance += float(model_term.var(ddof=1)) / n
        return value, variance
    raise ValueError(f"unknown method {method!r}")


def _bootstrap_interval(
    weights: np.ndarray,
    rewards: np.ndarray,
    q: np.ndarray | None,
    method: str,
    rounds: int,
    seed: int,
    alpha: float,
    model_term: np.ndarray | None = None,
) -> tuple[float, float]:
    """The percentile interval over ``rounds`` resamples of the plays."""
    rng = np.random.default_rng(seed)
    n = weights.size
    values = np.empty(rounds, dtype=float)
    for round_index in range(rounds):
        index = rng.integers(0, n, size=n)
        sampled_w = weights[index]
        sampled_r = rewards[index]
        sampled_q = q[index] if q is not None else None
        sampled_m = model_term[index] if model_term is not None else None
        value, _ = _estimate(sampled_w, sampled_r, sampled_q, method, sampled_m)
        values[round_index] = value
    low = float(np.quantile(values, alpha / 2.0))
    high = float(np.quantile(values, 1.0 - alpha / 2.0))
    return low, high


def corrupt_propensities(
    records: Sequence[PlayRecord],
    *,
    mode: str = "scale",
    factor: float = 2.0,
    seed: int = 0,
) -> tuple[PlayRecord, ...]:
    """Corrupt the logged propensities on purpose — the negative control.

    Three ways to be wrong about a propensity, and each is wrong in a
    different direction:

    * ``"scale"`` — every propensity multiplied by a constant. The weights
      all scale, so the **IPS** estimate scales with it and the **SNIPS**
      estimate does not: SNIPS divides by the sum of the weights, so a
      uniform scale error cancels exactly. The bias is precisely the
      factor, and no diagnostic that only looks at the shape of the weights
      can see it. This is the control that keeps SNIPS honest.
    * ``"shuffle"`` — the propensities are permuted across the plays, so
      the weights are decorrelated from the rewards. Both estimators drift
      towards the logger's own value and the effective sample size
      collapses.
    * ``"uniform"`` — every propensity is replaced by ``1/k`` for ``k``
      candidates. This is what a system that *guesses* a plausible
      propensity produces, and it is the corruption that is hardest to
      notice because every weight stays the same size.
    """
    if mode not in ("scale", "shuffle", "uniform"):
        raise ValueError(f"unknown corruption mode {mode!r}")
    if not records:
        return ()

    if mode == "scale":
        return tuple(
            record.model_copy(
                update={
                    "propensity": (
                        None
                        if record.propensity is None
                        else record.propensity * factor
                    )
                }
            )
            for record in records
        )

    if mode == "shuffle":
        rng = np.random.default_rng(seed)
        values = np.array(
            [
                record.propensity if record.propensity is not None else 0.0
                for record in records
            ],
            dtype=float,
        )
        order = rng.permutation(values.size)
        return tuple(
            record.model_copy(update={"propensity": float(value)})
            for record, value in zip(records, values[order])
        )

    return tuple(
        record.model_copy(
            update={
                "propensity": 1.0
                / len(record.candidates or (record.tile_id,))
            }
        )
        for record in records
    )
