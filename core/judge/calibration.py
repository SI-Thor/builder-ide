"""One definition of confidence, and the calibration tracked against it.

**Why one definition.** The three d1 sizes answer the same shape and report
their confidence by three different formulas — the normalised margin (LFM2),
the raw top probability (LFM3), a third for ``score`` (liquid-study L7). A
threshold on "confidence" is therefore not the same quantity from one model to
the next, and a confidence column that mixes them compares a margin against a
probability. So the judge does not trust the backend's number: it computes
confidence from the distribution the backend returned, the same way for every
backend, and the row says which definition it used.

**The three definitions**, all computed from the returned distribution over
K options with probabilities p:

``top_probability``
    ``p_max`` — the probability the backend gave its own answer.
``normalised_margin``
    ``(p_max − 1/K) / (1 − 1/K)`` — the LFM2 formula: the top probability's
    excess over the uniform baseline, on [0, 1].
``entropy_normalised``
    ``1 − H(p) / log K`` — one when the answer is a point mass, zero when the
    distribution is uniform.

**The canonical one is ``top_probability``**, for three reasons that are
mechanisms rather than tastes:

1. **It is a probability of the answer.** A τ on it reads "act when the
   backend's own answer holds at least this much probability"; the margin and
   the entropy score are summaries of the shape of a distribution and are not
   probabilities of anything, so a τ on them is a τ on a different kind of
   number.
2. **It is the number the existing measurements are in.** The local d1-2B
   reports ``max(probs)`` (E1's τ = 0.5 was measured on it) and the fake
   backend reports the top probability, so the default keeps its meaning and
   the suite means what the hardware means.
3. **It is the quantity the Brier score is computed against.** The proper
   scoring rule is computed over the whole vector; the confidence is the
   model's own probability for the answer it gave, which is exactly the event
   the gate acts on.

The other two stay in the code because the seed asked for the comparison:
*re-score the same logs three ways and publish the numbers* (B15). The
comparison is in ``docs/lab/exp-judge-calibration.md``.

**The metrics**, per (backend, model, task) cell:

* **accuracy** — the share of judgments whose argmax was right;
* **Brier score** — the per-sample score ``(1/K)·Σ_i (p_i − y_i)²``, averaged
  over the cell's samples. For a binary question that is ``(p − y)²``, the
  usual definition; for a K-way question it is the multiclass Brier divided by
  K, so cells with different option counts sit on one scale.
* **expected calibration error** — over equal-width reliability bins on the
  confidence: ``Σ_b (n_b/N)·|accuracy_b − mean_confidence_b|``.
* **the reliability curve** — per bin: n, mean confidence, accuracy, and the
  gap between them.
* **the escalation sweep** — at each τ, the act rate, how many wrong
  judgments the gate would have caught, and how many right ones it would have
  taxed. The seed's question is not which number is best but whether *any* of
  them, at any threshold, would have fired the right number of escalations.

**Recalibration is a parameter, not a hand.** A temperature or an isotonic
map is fitted per (backend, model, task) on one split of the outcomes and
read on another; it is kept only if it improves the held-out Brier score.
The gate's τ is then read in the calibrated space, where it means what it
says: "act when the calibrated probability of being right is at least τ".

**Drift is measured, not declared.** Nothing here carries an invented
threshold. A cell drifts when one of three *measured* facts holds: the
confidence no longer orders right above wrong (the area under the curve falls
to the coin-flip line), the cell's calibration error has moved further than
anything that cell has done before (the noise floor is the cell's own
history), or the recalibration fitted on the older window no longer improves
the newer one. What is retuned when it drifts is stated with the line: the
recalibration for that cell is refitted on the newest outcomes and the gate's
τ is read from it again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Sequence

__all__ = [
    "ConfidenceDefinition",
    "CONFIDENCE_DEFINITIONS",
    "CANONICAL_CONFIDENCE",
    "confidence_of",
    "CalibrationSample",
    "ReliabilityBin",
    "SweepRow",
    "CalibrationCell",
    "cell_of",
    "cells_of",
    "brier_score",
    "accuracy",
    "mean_confidence",
    "expected_calibration_error",
    "reliability_curve",
    "escalation_sweep",
    "CalibrationScale",
    "TemperatureScale",
    "IsotonicScale",
    "fit_temperature",
    "fit_isotonic",
    "Recalibration",
    "recalibrate",
    "is_identity",
    "raw_floor_for",
    "DriftLine",
    "drift_of",
    "area_under_curve",
]

#: The three definitions the seed asked to be compared, by name.
ConfidenceDefinition = Literal["top_probability", "normalised_margin", "entropy_normalised"]

CONFIDENCE_DEFINITIONS: tuple[ConfidenceDefinition, ...] = (
    "top_probability",
    "normalised_margin",
    "entropy_normalised",
)

#: The one the judge uses. See the module docstring for the three reasons.
CANONICAL_CONFIDENCE: ConfidenceDefinition = "top_probability"

#: The reliability bins the ECE is computed over: equal width on [0, 1].
DEFAULT_BINS = 10


# --- the definitions ------------------------------------------------------------


def confidence_of(
    distribution: Mapping[str, float],
    definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
) -> float:
    """The confidence of one judgment, under one definition.

    The same function for every backend: the distribution comes in, a number
    in [0, 1] goes out, and the definition says which number it is. A
    distribution that does not sum to one is a typo, not a judgment, so it is
    refused here rather than quietly normalised somewhere downstream.
    """
    values = [float(value) for value in distribution.values()]
    if not values:
        raise ValueError("a judgment carries a distribution")
    total = sum(values)
    if not 0.999 <= total <= 1.001:
        raise ValueError(f"a distribution sums to one, not {total:.4f}")
    if any(value < 0.0 for value in values):
        raise ValueError("a probability is not negative")

    k = len(values)
    top = max(values)

    if definition == "top_probability":
        return top
    if definition == "normalised_margin":
        if k == 1:
            return 1.0
        uniform = 1.0 / k
        return (top - uniform) / (1.0 - uniform)
    if definition == "entropy_normalised":
        if k == 1:
            return 1.0
        entropy = -sum(value * math.log(value) for value in values if value > 0.0)
        return max(0.0, min(1.0, 1.0 - entropy / math.log(k)))
    raise ValueError(f"unknown confidence definition {definition!r}")


# --- the sample -----------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationSample:
    """One judgment with its outcome — the unit the calibration is computed on.

    ``distribution`` is the backend's own answer (renormalised); ``outcome`` is
    whether the answer it gave was right, learned later from the ledger (the
    tiles' play, the critic's verdict, the owner's keep). ``answer`` and
    ``truth`` are kept because a log that needs a computation to say what was
    judged is a log that lies by omission.
    """

    backend: str
    model: str
    task: str
    kind: str
    qid: str
    distribution: Mapping[str, float]
    outcome: bool
    answer: str | None = None
    truth: str | None = None
    at: str = ""

    def __post_init__(self) -> None:
        if not self.distribution:
            raise ValueError("a calibration sample carries a distribution")
        total = sum(float(value) for value in self.distribution.values())
        if not 0.999 <= total <= 1.001:
            raise ValueError(f"a distribution sums to one, not {total:.4f}")

    @property
    def cell(self) -> tuple[str, str, str]:
        """The cell this sample belongs to: (backend, model, task)."""
        return (self.backend, self.model, self.task)

    @property
    def top(self) -> str:
        """The option the judgment answered — the argmax, ties by name."""
        return max(sorted(self.distribution), key=lambda key: self.distribution[key])

    def confidence(self, definition: ConfidenceDefinition = CANONICAL_CONFIDENCE) -> float:
        """This sample's confidence under one definition."""
        return confidence_of(self.distribution, definition)

    def truth_key(self) -> str | None:
        """The option that was right, or ``None`` when it cannot be named.

        The outcome says *whether* the answer was right; the Brier score needs
        *which* option was right. On a binary question the outcome names it
        (the other option was right); on a K-way question only the caller
        knows, so a sample without a truth is counted for accuracy and not
        for the Brier score.
        """
        if self.truth is not None and self.truth in self.distribution:
            return self.truth
        if len(self.distribution) == 2:
            other = [key for key in self.distribution if key != self.top]
            if not other:
                return self.top
            if self.outcome:
                return self.top
            return other[0]
        return None

    def brier(self) -> float | None:
        """The per-sample Brier score: ``(1/K)·Σ_i (p_i − y_i)²``.

        ``None`` when the truth's option cannot be named (see
        :meth:`truth_key`).
        """
        truth_key = self.truth_key()
        if truth_key is None:
            return None
        total = 0.0
        for key, probability in self.distribution.items():
            target = 1.0 if key == truth_key else 0.0
            total += (float(probability) - target) ** 2
        return total / len(self.distribution)


# --- the metrics ----------------------------------------------------------------


def _brier_of(distribution: Mapping[str, float], truth_key: str | None) -> float | None:
    """The per-sample Brier score of one distribution against one truth."""
    if truth_key is None:
        return None
    total = 0.0
    for key, probability in distribution.items():
        target = 1.0 if key == truth_key else 0.0
        total += (float(probability) - target) ** 2
    return total / len(distribution)


def brier_score(samples: Sequence[CalibrationSample]) -> float | None:
    """The cell's Brier score — the mean over the scorable samples.

    A sample whose truth cannot be named (a K-way question whose outcome is
    known but whose right option was not recorded) is left out of this number
    and counted for accuracy all the same.
    """
    scores = [sample.brier() for sample in samples]
    scores = [score for score in scores if score is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def accuracy(samples: Sequence[CalibrationSample]) -> float | None:
    """The share of judgments whose answer was right."""
    if not samples:
        return None
    return sum(1 for sample in samples if sample.outcome) / len(samples)


def mean_confidence(
    samples: Sequence[CalibrationSample],
    definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
) -> float | None:
    """The cell's mean confidence under one definition."""
    if not samples:
        return None
    return sum(sample.confidence(definition) for sample in samples) / len(samples)


@dataclass(frozen=True)
class ReliabilityBin:
    """One reliability bin: what the model said, and what happened."""

    index: int
    low: float
    high: float
    n: int
    mean_confidence: float
    accuracy: float
    gap: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "low": round(self.low, 4),
            "high": round(self.high, 4),
            "n": self.n,
            "mean_confidence": round(self.mean_confidence, 4),
            "accuracy": round(self.accuracy, 4),
            "gap": round(self.gap, 4),
        }


def reliability_curve(
    samples: Sequence[CalibrationSample],
    *,
    bins: int = DEFAULT_BINS,
    definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
) -> list[ReliabilityBin]:
    """The reliability curve: per bin, the confidence and the accuracy.

    The bins are equal width on [0, 1] over the confidence; the gap is
    ``accuracy − mean_confidence``, so a positive gap means the model was
    right more often than it claimed.
    """
    if bins < 1:
        raise ValueError("the bins are a count")
    buckets: list[list[CalibrationSample]] = [[] for _ in range(bins)]
    for sample in samples:
        confidence = sample.confidence(definition)
        index = min(bins - 1, max(0, int(confidence * bins)))
        buckets[index].append(sample)

    curve: list[ReliabilityBin] = []
    for index, bucket in enumerate(buckets):
        low = index / bins
        high = (index + 1) / bins
        if not bucket:
            curve.append(
                ReliabilityBin(
                    index=index,
                    low=low,
                    high=high,
                    n=0,
                    mean_confidence=0.0,
                    accuracy=0.0,
                    gap=0.0,
                )
            )
            continue
        mean = sum(sample.confidence(definition) for sample in bucket) / len(bucket)
        hits = sum(1 for sample in bucket if sample.outcome) / len(bucket)
        curve.append(
            ReliabilityBin(
                index=index,
                low=low,
                high=high,
                n=len(bucket),
                mean_confidence=mean,
                accuracy=hits,
                gap=hits - mean,
            )
        )
    return curve


def expected_calibration_error(
    samples: Sequence[CalibrationSample],
    *,
    bins: int = DEFAULT_BINS,
    definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
) -> float | None:
    """The ECE over the reliability bins — the weighted mean of the gaps."""
    if not samples:
        return None
    curve = reliability_curve(samples, bins=bins, definition=definition)
    total = len(samples)
    return sum((bin_.n / total) * abs(bin_.gap) for bin_ in curve)


@dataclass(frozen=True)
class SweepRow:
    """One τ in the escalation sweep."""

    tau: float
    act_rate: float
    escalated: int
    catch: float
    tax: float
    caught_all: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "tau": self.tau,
            "act_rate": round(self.act_rate, 4),
            "escalated": self.escalated,
            "catch": round(self.catch, 4),
            "tax": round(self.tax, 4),
            "caught_all": self.caught_all,
        }


def escalation_sweep(
    samples: Sequence[CalibrationSample],
    taus: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
    *,
    definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
) -> list[SweepRow]:
    """What the gate would have done at each τ.

    ``catch`` is the share of the **wrong** judgments the gate would have
    escalated (the gate's job); ``tax`` is the share of the **right** ones it
    would have escalated (the gate's cost); ``caught_all`` says whether this τ
    catches every wrong judgment — the seed's "the right number of
    escalations", which is one escalation per wrong judgment and no more.
    """
    if not samples:
        return []
    wrong = [sample for sample in samples if not sample.outcome]
    right = [sample for sample in samples if sample.outcome]
    rows: list[SweepRow] = []
    for tau in taus:
        escalated = [sample for sample in samples if sample.confidence(definition) < tau]
        caught = [sample for sample in escalated if not sample.outcome]
        taxed = [sample for sample in escalated if sample.outcome]
        rows.append(
            SweepRow(
                tau=tau,
                act_rate=1.0 - len(escalated) / len(samples),
                escalated=len(escalated),
                catch=len(caught) / len(wrong) if wrong else 0.0,
                tax=len(taxed) / len(right) if right else 0.0,
                caught_all=bool(wrong) and len(caught) == len(wrong),
            )
        )
    return rows


def area_under_curve(pairs: Sequence[tuple[float, bool]]) -> float | None:
    """The AUC of a confidence against an outcome — the separability.

    Ties (the same confidence, one right and one wrong) count a half each,
    which is the standard reading. ``None`` when there is nothing to order.
    """
    if not pairs:
        return None
    positives = [confidence for confidence, right in pairs if right]
    negatives = [confidence for confidence, right in pairs if not right]
    if not positives or not negatives:
        return None
    total = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                total += 1.0
            elif positive == negative:
                total += 0.5
    return total / (len(positives) * len(negatives))


# --- the cell -------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationCell:
    """One (backend, model, task) cell and its numbers."""

    backend: str
    model: str
    task: str
    n: int
    accuracy: float | None
    brier: float | None
    ece: float | None
    mean_confidence: float | None
    curve: tuple[ReliabilityBin, ...] = ()
    per_definition: Mapping[str, Mapping[str, float | None]] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.backend, self.model, self.task)

    @property
    def name(self) -> str:
        """The cell as one name: ``backend:model`` on the task."""
        return f"{self.backend}:{self.model} · {self.task}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "task": self.task,
            "n": self.n,
            "accuracy": _round(self.accuracy),
            "brier": _round(self.brier),
            "ece": _round(self.ece),
            "mean_confidence": _round(self.mean_confidence),
            "curve": [bin_.as_dict() for bin_ in self.curve],
            "per_definition": {
                name: {key: _round(value) for key, value in values.items()}
                for name, values in self.per_definition.items()
            },
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def cell_of(
    samples: Sequence[CalibrationSample],
    *,
    bins: int = DEFAULT_BINS,
) -> CalibrationCell:
    """The cell's numbers, and the same numbers under each definition.

    The canonical definition's numbers are the cell's own; the other two are
    published beside them so the comparison the seed asked for is on the same
    rows rather than on a re-run.
    """
    if not samples:
        raise ValueError("a cell has samples")
    backend, model, task = samples[0].cell
    per_definition: dict[str, dict[str, float | None]] = {}
    for definition in CONFIDENCE_DEFINITIONS:
        per_definition[definition] = {
            "accuracy": accuracy(samples),
            "brier": brier_score(samples),
            "ece": expected_calibration_error(samples, bins=bins, definition=definition),
            "mean_confidence": mean_confidence(samples, definition),
        }
    canonical = per_definition[CANONICAL_CONFIDENCE]
    return CalibrationCell(
        backend=backend,
        model=model,
        task=task,
        n=len(samples),
        accuracy=canonical["accuracy"],
        brier=canonical["brier"],
        ece=canonical["ece"],
        mean_confidence=canonical["mean_confidence"],
        curve=tuple(reliability_curve(samples, bins=bins)),
        per_definition=per_definition,
    )


def cells_of(samples: Sequence[CalibrationSample], *, bins: int = DEFAULT_BINS) -> list[CalibrationCell]:
    """Every cell, in a stable order."""
    grouped: dict[tuple[str, str, str], list[CalibrationSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.cell, []).append(sample)
    return [cell_of(grouped[key], bins=bins) for key in sorted(grouped)]


# --- the recalibration scales ----------------------------------------------------


@dataclass(frozen=True)
class CalibrationScale:
    """A recalibration: a map from the raw confidence to a calibrated one.

    A scale is a **parameter**, not a policy: it is fitted on one split of the
    outcomes and read on another, and it is kept only when it improves the
    held-out Brier score. The gate's τ is then read in the calibrated space.
    """

    kind: str
    params: Mapping[str, Any] = field(default_factory=dict)

    # -- the interface ----------------------------------------------------------

    def apply(self, distribution: Mapping[str, float]) -> dict[str, float]:
        """The recalibrated distribution."""
        raise NotImplementedError

    def calibrated_confidence(self, distribution: Mapping[str, float]) -> float:
        """The confidence the gate reads after the scale."""
        return confidence_of(self.apply(distribution), CANONICAL_CONFIDENCE)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": dict(self.params)}

    # -- the helpers ------------------------------------------------------------

    @staticmethod
    def _normalise(values: Mapping[str, float]) -> dict[str, float]:
        total = sum(values.values())
        if total <= 0.0:
            raise ValueError("a distribution with no mass")
        return {key: value / total for key, value in values.items()}


@dataclass(frozen=True)
class TemperatureScale(CalibrationScale):
    """Temperature scaling: ``p'_i ∝ p_i^(1/T)``.

    One number, fitted by minimising the Brier score. ``T > 1`` softens an
    over-confident model, ``T < 1`` sharpens a cautious one.
    """

    kind: str = "temperature"
    params: Mapping[str, Any] = field(default_factory=dict)

    def apply(self, distribution: Mapping[str, float]) -> dict[str, float]:
        temperature = float(self.params.get("temperature", 1.0))
        if temperature <= 0.0:
            raise ValueError("a temperature is positive")
        weights = {
            key: value ** (1.0 / temperature) if value > 0.0 else 0.0
            for key, value in distribution.items()
        }
        return self._normalise(weights)


@dataclass(frozen=True)
class IsotonicScale(CalibrationScale):
    """Isotonic regression: a monotone map from confidence to accuracy.

    Fitted by the pool-adjacent-violators algorithm on the (confidence,
    outcome) pairs, so the map is the empirical accuracy at each confidence,
    made monotone. The distribution's ranking is kept: the top option's mass
    becomes the calibrated value and the rest keeps its relative shares — the
    same reason the cascade's choice prior exists, because a ranking error is
    not a calibration error.
    """

    kind: str = "isotonic"
    params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def knots(self) -> tuple[tuple[float, float], ...]:
        return tuple((float(x), float(y)) for x, y in self.params.get("knots", ()))

    def map(self, confidence: float) -> float:
        """The calibrated value at one confidence."""
        knots = self.knots
        if not knots:
            return confidence
        if confidence <= knots[0][0]:
            return knots[0][1]
        if confidence >= knots[-1][0]:
            return knots[-1][1]
        for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
            if x0 <= confidence <= x1:
                if x1 == x0:
                    return max(y0, y1)
                weight = (confidence - x0) / (x1 - x0)
                return y0 + weight * (y1 - y0)
        return knots[-1][1]

    def apply(self, distribution: Mapping[str, float]) -> dict[str, float]:
        if len(distribution) == 1:
            return dict(distribution)
        top = max(sorted(distribution), key=lambda key: distribution[key])
        rest = [key for key in distribution if key != top]
        top_mass = float(distribution[top])
        calibrated = min(1.0, max(0.0, self.map(top_mass)))
        # the ranking is kept: the calibrated mass never drops below the
        # runner-up's, so the argmax does not change under a calibration.
        if rest:
            calibrated = max(calibrated, float(distribution[max(rest, key=lambda key: distribution[key])]))
        rest_mass = sum(float(distribution[key]) for key in rest)
        if rest_mass <= 0.0:
            # nothing else carries mass, so there is no remainder to share:
            # the whole distribution is the top option
            return {key: (1.0 if key == top else 0.0) for key in distribution}
        remaining = 1.0 - calibrated
        out = {top: calibrated}
        for key in rest:
            share = float(distribution[key]) / rest_mass
            out[key] = remaining * share
        return out


def fit_temperature(
    samples: Sequence[CalibrationSample],
    *,
    low: float = 0.05,
    high: float = 20.0,
    iterations: int = 60,
) -> TemperatureScale:
    """Fit the temperature that minimises the Brier score on these samples.

    A golden-section search on ``log T``: the objective is smooth in the log
    and one-dimensional, and the search is deterministic, so the same outcomes
    always give the same temperature.
    """
    if not samples:
        raise ValueError("a temperature is fitted on outcomes")

    def loss(temperature: float) -> float:
        scale = TemperatureScale(params={"temperature": temperature})
        scores = []
        for sample in samples:
            scaled = scale.apply(sample.distribution)
            score = _brier_of(scaled, sample.truth_key())
            if score is not None:
                scores.append(score)
        if not scores:
            raise ValueError("a temperature is fitted on outcomes with a known truth")
        return sum(scores) / len(scores)

    log_low, log_high = math.log(low), math.log(high)
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = log_low, log_high
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc, fd = loss(math.exp(c)), loss(math.exp(d))
    for _ in range(iterations):
        if fc <= fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = loss(math.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = loss(math.exp(d))
        if b - a < 1e-6:
            break
    temperature = math.exp((a + b) / 2.0)
    return TemperatureScale(params={"temperature": round(temperature, 6)})


def fit_isotonic(samples: Sequence[CalibrationSample]) -> IsotonicScale:
    """Fit the monotone confidence → accuracy map on these samples.

    The pool-adjacent-violators algorithm: sort by confidence, then merge
    neighbouring blocks whose empirical accuracy is out of order, until the
    block accuracies increase. The result is the isotonic (monotone) fit.
    """
    if not samples:
        raise ValueError("an isotonic map is fitted on outcomes")
    pairs = sorted(
        (sample.confidence(CANONICAL_CONFIDENCE), bool(sample.outcome))
        for sample in samples
    )
    blocks: list[list[tuple[float, float]]] = []  # (confidence, accuracy) blocks
    counts: list[int] = []
    totals: list[float] = []
    for confidence, right in pairs:
        blocks.append([(confidence, 1.0 if right else 0.0)])
        counts.append(1)
        totals.append(1.0 if right else 0.0)
        while len(blocks) > 1 and totals[-2] / counts[-2] > totals[-1] / counts[-1]:
            merged = blocks[-2] + blocks[-1]
            blocks[-2:] = [merged]
            counts[-2:] = [counts[-2] + counts[-1]]
            totals[-2:] = [totals[-2] + totals[-1]]
    knots = []
    for block, count, total in zip(blocks, counts, totals):
        accuracy = total / count
        knots.append((block[0][0], accuracy))
        knots.append((block[-1][0], accuracy))
    # the knots are the block edges; the map between them is the linear
    # interpolation of the two neighbouring block accuracies.
    deduped: list[tuple[float, float]] = []
    for x, y in knots:
        if deduped and deduped[-1][0] == x:
            deduped[-1] = (x, y)
        else:
            deduped.append((x, y))
    return IsotonicScale(params={"knots": [[x, y] for x, y in deduped]})


def is_identity(scale: CalibrationScale | None) -> bool:
    """Whether a scale changes nothing at all.

    A scale that maps every input to itself was never a recalibration, so
    nothing fitted with it can go stale. The drift rule needs this: without
    it, a cell whose confidence is already honest would report "the
    recalibration went stale" every night, because the identity does not
    improve the held-out Brier score — it cannot, it is the same number.
    """
    if scale is None:
        return True
    if isinstance(scale, TemperatureScale):
        return abs(float(scale.params.get("temperature", 1.0)) - 1.0) < 1e-6
    if isinstance(scale, IsotonicScale):
        return all(abs(y - x) < 1e-9 for x, y in scale.knots)
    return False


@dataclass(frozen=True)
class Recalibration:
    """The outcome of a recalibration attempt, and whether it was kept.

    ``kept`` is the rule the cascade's harness taught: a fit that does not
    improve the held-out Brier score is not a calibration, it is a curve
    through noise, and it is dropped.
    """

    kind: str
    scale: CalibrationScale | None
    brier_before: float | None
    brier_after: float | None
    held_out_brier_before: float | None
    held_out_brier_after: float | None
    kept: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scale": self.scale.as_dict() if self.scale else None,
            "brier_before": _round(self.brier_before),
            "brier_after": _round(self.brier_after),
            "held_out_brier_before": _round(self.held_out_brier_before),
            "held_out_brier_after": _round(self.held_out_brier_after),
            "kept": self.kept,
            "reason": self.reason,
        }


def _brier_with(samples: Sequence[CalibrationSample], scale: CalibrationScale | None) -> float | None:
    if not samples:
        return None
    if scale is None:
        return brier_score(samples)
    scores = []
    for sample in samples:
        scaled = scale.apply(sample.distribution)
        score = _brier_of(scaled, sample.truth_key())
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return sum(scores) / len(scores)


def raw_floor_for(
    scale: CalibrationScale,
    tau: float,
    shape: Mapping[str, float],
    *,
    steps: int = 2000,
) -> float:
    """The raw confidence at which the calibrated confidence reaches τ.

    **This is "the gate's τ read from the calibrated space" made into a
    number.** The gate compares the *calibrated* confidence with τ, so the
    operator sets τ in the calibrated space — "act when the calibrated
    probability of being right is at least τ" — and this says what the raw
    number has to be for that to happen.

    The map from a raw confidence to a calibrated one depends on the whole
    distribution, not on the top probability alone, so ``shape`` is the
    reference: the distribution's options and their relative shares. The
    top option's mass is then swept from 0 to 1, the rest keeping their
    shares of what is left, and the first sweep point whose calibrated
    confidence reaches τ is the floor.

    An identity scale returns τ itself, which is the check that the sweep
    and the scale agree.
    """
    keys = list(shape)
    if not keys:
        raise ValueError("a shape has options")
    top = max(keys, key=lambda key: float(shape[key]))
    rest = [key for key in keys if key != top]
    rest_total = sum(float(shape[key]) for key in rest)
    shares = {
        key: (float(shape[key]) / rest_total if rest_total > 0 else 0.0) for key in rest
    }
    max_share = max(shares.values()) if shares else 0.0

    def calibrated(raw: float) -> float:
        distribution = {top: raw}
        for key, share in shares.items():
            distribution[key] = (1.0 - raw) * share
        return scale.calibrated_confidence(distribution)

    # The sweep starts where the intended option is at least tied for the
    # top. Below that the option the confidence belongs to is not the one
    # the model answered with — on a binary that is exactly the half, which
    # is why a binary's raw floor can never be under a half.
    lower = max_share / (1.0 + max_share) if max_share > 0 else 0.0
    if calibrated(lower) >= tau:
        return lower
    low, high = lower, 1.0
    for index in range(1, steps + 1):
        candidate = lower + (1.0 - lower) * index / steps
        if calibrated(candidate) >= tau:
            low, high = lower + (1.0 - lower) * (index - 1) / steps, candidate
            break
    else:
        return 1.0
    # the sweep is a grid; a short bisection puts the floor on the crossing
    for _ in range(40):
        middle = (low + high) / 2.0
        if calibrated(middle) >= tau:
            high = middle
        else:
            low = middle
        if high - low < 1e-6:
            break
    return high


def recalibrate(
    fit_samples: Sequence[CalibrationSample],
    holdout_samples: Sequence[CalibrationSample],
) -> Recalibration:
    """Fit a scale on one split and keep it only if the other split likes it.

    Both scales are fitted on ``fit_samples`` and scored on
    ``holdout_samples``; the better of the two is kept only if it **improves**
    the held-out Brier score. The pair is a parameter: the caller passes the
    split, and the rule decides.
    """
    if not fit_samples:
        return Recalibration(
            kind="none",
            scale=None,
            brier_before=None,
            brier_after=None,
            held_out_brier_before=None,
            held_out_brier_after=None,
            kept=False,
            reason="no outcomes to fit on",
        )
    before_fit = brier_score(fit_samples)
    before_holdout = brier_score(holdout_samples)
    candidates: list[tuple[str, CalibrationScale]] = []
    try:
        candidates.append(("temperature", fit_temperature(fit_samples)))
    except ValueError:
        # a cell whose outcomes never named a truth (a K-way question whose
        # right option was not recorded) has no Brier score to fit against;
        # the isotonic map below still has the outcomes to work with
        pass
    candidates.append(("isotonic", fit_isotonic(fit_samples)))
    best_kind = "none"
    best_scale: CalibrationScale | None = None
    best_holdout = before_holdout
    for kind, scale in candidates:
        after_holdout = _brier_with(holdout_samples, scale)
        if after_holdout is None:
            continue
        if best_scale is None or after_holdout < best_holdout:
            best_kind, best_scale, best_holdout = kind, scale, after_holdout
    if best_scale is None:
        return Recalibration(
            kind="none",
            scale=None,
            brier_before=before_fit,
            brier_after=before_fit,
            held_out_brier_before=before_holdout,
            held_out_brier_after=before_holdout,
            kept=False,
            reason="nothing to compare against",
        )
    kept = best_holdout is not None and (
        before_holdout is None or best_holdout < before_holdout
    )
    reason = (
        f"{best_kind} improves the held-out Brier "
        f"({_fmt(before_holdout)} → {_fmt(best_holdout)})"
        if kept
        else (
            "no scale improved the held-out Brier "
            f"({_fmt(before_holdout)}); the raw confidence is kept"
        )
    )
    return Recalibration(
        kind=best_kind,
        scale=best_scale,
        brier_before=before_fit,
        brier_after=_brier_with(fit_samples, best_scale),
        held_out_brier_before=before_holdout,
        held_out_brier_after=best_holdout,
        kept=kept,
        reason=reason,
    )


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


# --- the drift -------------------------------------------------------------------


@dataclass(frozen=True)
class DriftLine:
    """One drifting model, in one line, with the numbers behind it."""

    backend: str
    model: str
    task: str
    kind: str
    detail: str
    numbers: Mapping[str, Any] = field(default_factory=dict)
    retune: str = ""

    @property
    def name(self) -> str:
        return f"{self.backend}:{self.model} · {self.task}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "task": self.task,
            "kind": self.kind,
            "detail": self.detail,
            "numbers": dict(self.numbers),
            "retune": self.retune,
        }


def drift_of(
    samples: Sequence[CalibrationSample],
    *,
    window: int = 50,
    bins: int = DEFAULT_BINS,
) -> list[DriftLine]:
    """The drift of one cell, measured against the cell's own history.

    Three measured facts, and no invented threshold anywhere:

    1. **the confidence stopped separating** — the area under the curve of
       the newest window's confidence against its outcomes has fallen to the
       coin-flip line (0.5), so the number orders right above wrong no
       better than chance. It has to have **fallen**: the previous window
       has to have been above the line, because a cell whose confidence was
       never a routing signal (a window of one-sided outcomes, or a
       constant confidence) has not drifted, it has never separated;
    2. **the calibration moved** — the newest window's ECE is further from
       the previous window's than any window-to-window move this cell has
       made before (the noise floor is the cell's own history, so the first
       window cannot declare drift: it is the baseline);
    3. **the recalibration went stale** — the scale fitted on the previous
       window no longer improves the newest window's Brier score, so the
       calibration that was fitted has stopped describing the model. A
       scale that changes nothing is not stale: it was never a
       recalibration, and a cell whose confidence is already honest must not
       report drift every night.

    What is retuned is stated with the line: the cell's recalibration is
    refitted on the newest outcomes, and the gate's τ is read from it again.
    """
    if len(samples) < window:
        return []
    windows = [list(samples[index : index + window]) for index in range(0, len(samples), window)]
    if len(windows) < 2:
        return []
    recent = windows[-1]
    reference = windows[-2]
    lines: list[DriftLine] = []

    # 1 — separability.
    pairs = [(sample.confidence(CANONICAL_CONFIDENCE), sample.outcome) for sample in recent]
    auc = area_under_curve(pairs)
    reference_auc = area_under_curve(
        [(sample.confidence(CANONICAL_CONFIDENCE), sample.outcome) for sample in reference]
    )
    if auc is not None and auc <= 0.5 and reference_auc is not None and reference_auc > 0.5:
        lines.append(
            DriftLine(
                backend=samples[0].backend,
                model=samples[0].model,
                task=samples[0].task,
                kind="separability_lost",
                detail=(
                    f"the confidence no longer orders right above wrong "
                    f"(AUC {auc:.3f} over the last {len(recent)} judgments, "
                    f"the previous window {reference_auc if reference_auc is None else round(reference_auc, 3)})"
                ),
                numbers={
                    "auc": round(auc, 4),
                    "reference_auc": _round(reference_auc),
                    "n": len(recent),
                },
                retune=(
                    "the confidence is not a routing signal on this cell any more: "
                    "the escalation must be driven by model disagreement or the "
                    "bandit's estimate, not by this number"
                ),
            )
        )

    # 2 — calibration moved, against the cell's own history.
    recent_ece = expected_calibration_error(recent, bins=bins)
    reference_ece = expected_calibration_error(reference, bins=bins)
    history = windows[:-1]
    moves: list[float] = []
    for earlier, later in zip(history, history[1:]):
        first = expected_calibration_error(earlier, bins=bins)
        second = expected_calibration_error(later, bins=bins)
        if first is not None and second is not None:
            moves.append(abs(second - first))
    if recent_ece is not None and reference_ece is not None and moves:
        floor = max(moves)
        if abs(recent_ece - reference_ece) > floor:
            lines.append(
                DriftLine(
                    backend=samples[0].backend,
                    model=samples[0].model,
                    task=samples[0].task,
                    kind="calibration_moved",
                    detail=(
                        f"the ECE moved {abs(recent_ece - reference_ece):.3f} "
                        f"({_fmt(reference_ece)} → {_fmt(recent_ece)}), more than this "
                        f"cell has ever moved ({floor:.3f})"
                    ),
                    numbers={
                        "recent_ece": _round(recent_ece),
                        "reference_ece": _round(reference_ece),
                        "history_floor": round(floor, 4),
                        "n": len(recent),
                    },
                    retune=(
                        "the cell's recalibration is refitted on the newest outcomes; "
                        "the gate's τ is read from the refitted scale"
                    ),
                )
            )

    # 3 — the recalibration went stale.
    stale = recalibrate(reference, recent)
    if stale.scale is not None and not stale.kept and not is_identity(stale.scale):
        lines.append(
            DriftLine(
                backend=samples[0].backend,
                model=samples[0].model,
                task=samples[0].task,
                kind="recalibration_stale",
                detail=(
                    f"the {stale.kind} scale fitted on the previous window no longer "
                    f"improves the newest one ({stale.reason})"
                ),
                numbers={
                    "held_out_brier_before": _round(stale.held_out_brier_before),
                    "held_out_brier_after": _round(stale.held_out_brier_after),
                    "n": len(recent),
                },
                retune=(
                    "the scale is refitted on the newest outcomes; if it still does not "
                    "improve the held-out Brier, the raw confidence is kept and the "
                    "cell's τ table is read as it stands"
                ),
            )
        )
    return lines
