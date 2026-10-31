"""The confidence gate: when a builder may speak a claim, and when it may act alone.

Two gates, two namespaces (X §6 5, fixing T's conflation; spec §1.7):

* the **world** gate is per `claim_type` and requires a denominator;
* the **taste** gate is per reason code and requires ≥ 2 prior observations.

Both are hard gates in the core's prediction and utterance APIs, not prompt
instructions (T §"The 'I think you'll like this' utterance", rule 4): *a builder
must not predict on a reason code where it has fewer than two prior
observations*. Below three observations the uncertainty leads the sentence.

The gate **forbids pretending to a view, not betting** (G §1 20:44): a sealed
record with `confidence: "guess"` is always permitted, and cold start seals
zero-prior bets with `basis: "0 observations"` (spec §3.5).

What the gate decides, stated plainly:

* **speaking** — may the builder say a claim to the owner at all?
* **acting alone** — may the builder take the action unsupervised (at night,
  with nobody watching)? This is the question the overnight loop asks, and it
  is the one that matters for a builder on its first night: with no priors it
  may bet, and it may not decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .taste import TasteRow, taste_rows_from_events

__all__ = [
    "ObservationCounts",
    "GateDecision",
    "ConfidenceResult",
    "Gate",
    "MIN_OBSERVATIONS_TO_SPEAK_TASTE",
    "MIN_OBSERVATIONS_TO_ACT_ALONE",
    "MIN_OBSERVATIONS_FOR_CERTAINTY",
    "HIGH_CONFIDENCE_RATIO",
    "MEDIUM_CONFIDENCE_RATIO",
]

#: T §"The 'I think you'll like this' utterance", rule 4 — "no evidence, no claim".
MIN_OBSERVATIONS_TO_SPEAK_TASTE = 2

#: The same threshold for an unsupervised action: a builder with fewer than two
#: prior observations on a claim type asks instead of deciding.
MIN_OBSERVATIONS_TO_ACT_ALONE = 2

#: Below three observations the uncertainty leads the sentence (T, rule 3).
MIN_OBSERVATIONS_FOR_CERTAINTY = 3

#: Hit/kept ratios that earn a confidence level. Denominators, never percentages.
HIGH_CONFIDENCE_RATIO = 0.75
MEDIUM_CONFIDENCE_RATIO = 0.5


@dataclass(frozen=True)
class ConfidenceResult:
    """A confidence level and the denominator it rests on."""

    confidence: str
    basis: str
    observations: int


@dataclass(frozen=True)
class GateDecision:
    """The gate's answer, with the reason it gave it."""

    allowed: bool
    reason: str
    confidence: str
    basis: str
    observations: int

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


@dataclass
class ObservationCounts:
    """What a builder has observed, counted by axis.

    `world_sealed` / `world_hit` are per `claim_type`; `taste_observed` /
    `taste_kept` are per reason code and per author.
    """

    world_sealed: dict[str, int] = field(default_factory=dict)
    world_hit: dict[str, int] = field(default_factory=dict)
    taste_observed: dict[str, int] = field(default_factory=dict)
    taste_kept: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_events(
        cls,
        events: Sequence[Any],
        *,
        builder: str | None = None,
        author: str = "casey",
        subject_prefix: str | None = None,
    ) -> "ObservationCounts":
        """Count a builder's observations out of the audit log.

        World counts come from sealed/scored predictions; taste counts come
        from the owner's taste rows. Magnus's rows are excluded by
        construction: `taste_rows_from_events` reads them, but the author
        filter below keeps them out of anyone's counts (§7.6).

        `subject_prefix` narrows the taste count to one recipe entry
        ("harbor.crates"), so a claim about the crates is measured on the
        crates and not on every busy thing the owner has ever kept.
        """
        counts = cls()
        sealed_by_id: dict[str, tuple[str, str]] = {}

        for event in events:
            event_type = getattr(event, "type", None)
            payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
            if event_type == "prediction.sealed":
                sealed = payload.get("sealed_payload") or {}
                if builder is not None and sealed.get("builder") != builder:
                    continue
                claim_type = str(sealed.get("claim_type", ""))
                sealed_by_id[str(payload.get("prediction_id", ""))] = (
                    str(sealed.get("builder", "")),
                    claim_type,
                )
                counts.world_sealed[claim_type] = counts.world_sealed.get(claim_type, 0) + 1
            elif event_type == "prediction.scored":
                prediction_id = str(payload.get("prediction_id", ""))
                sealed_builder, claim_type = sealed_by_id.get(prediction_id, ("", ""))
                if not claim_type:
                    claim_type = str(payload.get("claim_type", ""))
                    sealed_builder = str(payload.get("builder", ""))
                if builder is not None and sealed_builder not in ("", builder):
                    continue
                if payload.get("verdict") == "hit":
                    counts.world_hit[claim_type] = counts.world_hit.get(claim_type, 0) + 1

        for row in taste_rows_from_events(events):
            if row.author != author or row.status != "active":
                continue
            if subject_prefix is not None:
                path = row.param_path or ""
                if not (path == subject_prefix or path.startswith(f"{subject_prefix}.")):
                    continue
            counts.taste_observed[row.reason_code] = (
                counts.taste_observed.get(row.reason_code, 0) + 1
            )
            counts.taste_kept.setdefault(row.reason_code, 0)
            if row.kept:
                counts.taste_kept[row.reason_code] = (
                    counts.taste_kept.get(row.reason_code, 0) + 1
                )
        return counts

    @classmethod
    def from_rows(
        cls, rows: Iterable[TasteRow], *, author: str = "casey"
    ) -> "ObservationCounts":
        """Count taste observations only (a builder with no bets yet)."""
        counts = cls()
        for row in rows:
            if row.author != author or row.status != "active":
                continue
            counts.taste_observed[row.reason_code] = (
                counts.taste_observed.get(row.reason_code, 0) + 1
            )
            counts.taste_kept.setdefault(row.reason_code, 0)
            if row.kept:
                counts.taste_kept[row.reason_code] = (
                    counts.taste_kept.get(row.reason_code, 0) + 1
                )
        return counts


class Gate:
    """The confidence gate over one builder's observations."""

    def __init__(self, counts: ObservationCounts | None = None) -> None:
        self.counts = counts or ObservationCounts()

    # -- confidence -------------------------------------------------------------

    def world_confidence(self, claim_type: str) -> ConfidenceResult:
        """Confidence for a claim about the world (namespace `world`)."""
        sealed = self.counts.world_sealed.get(claim_type, 0)
        if sealed == 0:
            return ConfidenceResult("guess", "0 observations", 0)
        hits = self.counts.world_hit.get(claim_type, 0)
        ratio = hits / sealed
        if sealed < MIN_OBSERVATIONS_FOR_CERTAINTY:
            confidence = "low"
        elif ratio >= HIGH_CONFIDENCE_RATIO:
            confidence = "high"
        elif ratio >= MEDIUM_CONFIDENCE_RATIO:
            confidence = "medium"
        else:
            confidence = "low"
        return ConfidenceResult(confidence, f"{hits}/{sealed} hit", sealed)

    def taste_confidence(self, reason_code: str) -> ConfidenceResult:
        """Confidence for a claim about the owner (namespace `taste`)."""
        observed = self.counts.taste_observed.get(reason_code, 0)
        if observed == 0:
            return ConfidenceResult("guess", "0 observations", 0)
        kept = self.counts.taste_kept.get(reason_code, 0)
        ratio = kept / observed
        if observed < MIN_OBSERVATIONS_FOR_CERTAINTY:
            confidence = "low"
        elif ratio >= HIGH_CONFIDENCE_RATIO:
            confidence = "high"
        elif ratio >= MEDIUM_CONFIDENCE_RATIO:
            confidence = "medium"
        else:
            confidence = "low"
        return ConfidenceResult(confidence, f"{kept}/{observed} kept", observed)

    # -- gates ------------------------------------------------------------------

    def may_speak_world(self, claim_type: str) -> GateDecision:
        """May the builder *say* a claim about the world?

        The world gate requires a denominator: at least one prior observation
        of that claim type. With none, the builder has no basis and the
        sentence would be a guess dressed as a claim.
        """
        result = self.world_confidence(claim_type)
        if result.observations == 0:
            return GateDecision(
                False,
                "no_denominator",
                result.confidence,
                result.basis,
                result.observations,
            )
        return GateDecision(
            True, "has_denominator", result.confidence, result.basis, result.observations
        )

    def may_speak_taste(self, reason_code: str) -> GateDecision:
        """May the builder *say* a taste claim on this reason code?

        Below two prior observations the claim is refused outright (T rule 4).
        """
        result = self.taste_confidence(reason_code)
        if result.observations < MIN_OBSERVATIONS_TO_SPEAK_TASTE:
            return GateDecision(
                False,
                "below_two_observations",
                result.confidence,
                result.basis,
                result.observations,
            )
        return GateDecision(
            True, "has_observations", result.confidence, result.basis, result.observations
        )

    def may_act_alone(
        self,
        *,
        namespace: str,
        claim_type: str | None = None,
        reason_code: str | None = None,
    ) -> GateDecision:
        """May the builder take the action unsupervised?

        This is the question the overnight loop asks. A builder with fewer
        than two prior observations on the axis may **bet** (sealing is always
        allowed) but may not **decide**: it has to ask.
        """
        if namespace == "taste":
            if reason_code is None:
                raise ValueError("a taste action names the reason code it bets on")
            result = self.taste_confidence(reason_code)
            observations = result.observations
        else:
            if claim_type is None:
                raise ValueError("a world action names the claim type it bets on")
            result = self.world_confidence(claim_type)
            observations = result.observations

        if observations < MIN_OBSERVATIONS_TO_ACT_ALONE:
            return GateDecision(
                False,
                "below_two_observations",
                result.confidence,
                result.basis,
                observations,
            )
        return GateDecision(
            True, "has_observations", result.confidence, result.basis, observations
        )

    # -- utterances -------------------------------------------------------------

    def uncertainty_leads(self, observations: int) -> bool:
        """True when the sentence must lead with its own uncertainty (T rule 3)."""
        return observations < MIN_OBSERVATIONS_FOR_CERTAINTY

    def lead_clause(self, *, namespace: str, claim_type: str | None = None,
                    reason_code: str | None = None) -> str:
        """The clause that opens a claim sentence when the sample is thin.

        The three forms are fixed (T §"The 'I think you'll like this'
        utterance"): the lead is the uncertainty itself, never a footnote.
        """
        if namespace == "taste":
            result = self.taste_confidence(reason_code or "")
        else:
            result = self.world_confidence(claim_type or "")
        if not self.uncertainty_leads(result.observations):
            return ""
        if result.observations == 0:
            return "This is a guess. I've nothing on you yet."
        return "This is a guess."
