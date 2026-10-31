"""The cold-start gate: ask-mode and the melt (spec §3.5; decision 13a).

Decision 13 of `docs/plan.md`: cold start is **a mechanism, not a number of
nights** — recommendation (a), chosen: *questions and `guess` confidence
decay per builder, per reason code, at two observations*, which makes the
first week's melt auditable in the ledger rather than tuned by hand. Nothing
is switched off by hand (G §1.1.9: "the cold-start rules decay mechanically,
tied to the two-observation gate"); the first week's table is a prediction
the tests can falsify, not a schedule to enforce.

Three things flip at the same threshold, per builder × reason code:

* **ask → act**: below two observations the builder asks (a two-chip question
  whose answer *is* the observation); at two it may act alone — the same
  threshold as the `vocab` seat's `MIN_OBSERVATIONS_TO_ACT_ALONE`;
* **guess → claim**: below two, a sealed taste bet wears `confidence:
  "guess"` with the true count in its basis ("1 observation" — the ledger is
  never lied to about how thin the sample is); at two the bet must carry a
  real confidence with its denominator ("2/2 kept");
* **silence → speech**: below two the builder may not *say* a taste claim at
  all — no evidence, no claim (T §"The 'I think you'll like this' utterance",
  rule 4) — and below three the uncertainty leads the sentence (rule 3).

**Per builder** is load-bearing, and it is auditable because the attribution
rides in the ledger: a taste row written by answering a question is tagged
`asked-by:<builder>`, and the gate counts, for builder *b* on code *r*, the
author's active rows on *r* that are either attributed to *b* or unattributed
(the owner's unprompted keeps count for every builder — the ledger is shared
and readable). Rows by other authors and `pending_ratification` rows are
excluded, exactly as in every slice a builder reads (§1.7, §7.6).

The gate forbids pretending to a view, not betting (G §1 20:44): sealing
below the threshold is always allowed — with `guess` on its face.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .stubs import taste_rows_from_events

__all__ = [
    "MELT_AT",
    "MIN_OBSERVATIONS_FOR_CERTAINTY",
    "HIGH_CONFIDENCE_RATIO",
    "MEDIUM_CONFIDENCE_RATIO",
    "ASKED_BY_PREFIX",
    "asked_by_tag",
    "ColdDecision",
    "ColdStartGate",
]

#: Decision 13a — the one threshold: ask→act and guess→claim at two observations.
MELT_AT = 2

#: T rule 3 — below three observations the uncertainty leads the sentence.
MIN_OBSERVATIONS_FOR_CERTAINTY = 3

#: The merge's contract (this seat's README, stub table): the melt threshold
#: IS the vocabulary gate's — one number, both doors, or a builder could be
#: told to ask by one seat and to act by the other.
from core.vocab.gate import (  # noqa: E402
    MIN_OBSERVATIONS_TO_ACT_ALONE,
    MIN_OBSERVATIONS_TO_SPEAK_TASTE,
)

assert (
    MELT_AT == MIN_OBSERVATIONS_TO_ACT_ALONE == MIN_OBSERVATIONS_TO_SPEAK_TASTE
), "the melt threshold has drifted from the vocabulary gate's (decision 13a)"

#: T — the ratios that earn a confidence level. Denominators, never percentages.
HIGH_CONFIDENCE_RATIO = 0.75
MEDIUM_CONFIDENCE_RATIO = 0.5

#: The taste-row tag that attributes an answer to the builder whose question
#: elicited it — this is what makes the melt per-builder and auditable.
ASKED_BY_PREFIX = "asked-by:"


def asked_by_tag(builder: str) -> str:
    return f"{ASKED_BY_PREFIX}{builder}"


@dataclass(frozen=True)
class ColdDecision:
    """The gate's answer for one builder on one axis, with everything it rests on."""

    builder: str
    axis: Literal["reason_code", "claim_type"]
    key: str
    observations: int
    kept: int
    mode: Literal["ask", "act"]
    confidence: str
    basis: str
    may_speak: bool
    refusal: str | None
    lead_clause: str


class ColdStartGate:
    """The melt, folded out of the ledger on every question.

    Every method is a pure fold over the audit log: the same ledger, rebuilt
    after a kill -9, yields the same decisions (§5 — projections are folds).
    """

    def __init__(self, ledger: Any, *, author: str = "casey") -> None:
        self._ledger = ledger
        self._author = author

    # -- the taste axis: per builder × reason code ---------------------------

    def observations(self, builder: str, reason_code: str) -> tuple[int, int]:
        """(observed, kept) for this builder on this reason code.

        A row counts when the author matches, the row is active (Magnus's
        pre-ratification rows are inert), the reason code matches, and the row
        is either attributed to this builder's questions or unattributed.
        """
        observed = 0
        kept = 0
        mine = asked_by_tag(builder)
        for row in taste_rows_from_events(self._ledger.events()):
            if row.author != self._author or row.status != "active":
                continue
            if row.reason_code != reason_code:
                continue
            tags = set(row.tags)
            if any(tag.startswith(ASKED_BY_PREFIX) for tag in tags) and mine not in tags:
                continue  # another builder's question, another builder's melt
            observed += 1
            if row.kept:
                kept += 1
        return observed, kept

    def decide(self, builder: str, reason_code: str) -> ColdDecision:
        """Ask or act, guess or claim — mechanically, from the counts."""
        observed, kept = self.observations(builder, reason_code)
        if observed < MELT_AT:
            # Cold: it may bet (a guess on its face) but not decide or claim.
            return ColdDecision(
                builder=builder,
                axis="reason_code",
                key=reason_code,
                observations=observed,
                kept=kept,
                mode="ask",
                confidence="guess",
                basis=_plural_observations(observed),
                may_speak=False,
                refusal="below_two_observations",
                lead_clause=self.lead_clause(observed),
            )
        ratio = kept / observed
        if observed < MIN_OBSERVATIONS_FOR_CERTAINTY:
            confidence = "low"
        elif ratio >= HIGH_CONFIDENCE_RATIO:
            confidence = "high"
        elif ratio >= MEDIUM_CONFIDENCE_RATIO:
            confidence = "medium"
        else:
            confidence = "low"
        return ColdDecision(
            builder=builder,
            axis="reason_code",
            key=reason_code,
            observations=observed,
            kept=kept,
            mode="act",
            confidence=confidence,
            basis=f"{kept}/{observed} kept",
            may_speak=True,
            refusal=None,
            lead_clause=self.lead_clause(observed),
        )

    def melted_codes(self, builder: str) -> set[str]:
        """The reason codes this builder no longer needs to ask about."""
        return {
            row.reason_code
            for row in taste_rows_from_events(self._ledger.events())
            if self.decide(builder, row.reason_code).mode == "act"
        }

    # -- the world axis: per builder × claim type -----------------------------

    def world_counts(self, builder: str, claim_type: str) -> tuple[int, int]:
        """(sealed, hit) for this builder on this claim type."""
        claim_by_id: dict[str, str] = {}
        for event in self._ledger.events():
            payload = event.payload or {}
            if event.type == "prediction.sealed":
                sealed = payload.get("sealed_payload") or {}
                if sealed.get("builder") == builder:
                    claim_by_id[str(payload.get("prediction_id", ""))] = str(
                        sealed.get("claim_type", "")
                    )
        sealed = sum(1 for claim in claim_by_id.values() if claim == claim_type)
        hits = 0
        for event in self._ledger.events():
            payload = event.payload or {}
            if (
                event.type == "prediction.scored"
                and payload.get("verdict") == "hit"
                and claim_by_id.get(str(payload.get("prediction_id", ""))) == claim_type
            ):
                hits += 1
        return sealed, hits

    def decide_world(self, builder: str, claim_type: str) -> ColdDecision:
        """The world axis of the melt.

        A world bet with no priors is a sealed guess ("0 observations" — spec
        §1.7: `guess` is the zero-prior bet); with a denominator the
        confidence follows the `vocab` gate's ratio rules. Acting alone on a
        world claim needs the same two observations as the taste axis.
        """
        sealed, hits = self.world_counts(builder, claim_type)
        if sealed == 0:
            confidence, basis = "guess", "0 observations"
        else:
            ratio = hits / sealed
            if sealed < MIN_OBSERVATIONS_FOR_CERTAINTY:
                confidence = "low"
            elif ratio >= HIGH_CONFIDENCE_RATIO:
                confidence = "high"
            elif ratio >= MEDIUM_CONFIDENCE_RATIO:
                confidence = "medium"
            else:
                confidence = "low"
            basis = f"{hits}/{sealed} hit"
        mode: Literal["ask", "act"] = "act" if sealed >= MELT_AT else "ask"
        return ColdDecision(
            builder=builder,
            axis="claim_type",
            key=claim_type,
            observations=sealed,
            kept=hits,
            mode=mode,
            confidence=confidence,
            basis=basis,
            may_speak=sealed > 0,
            refusal=None if sealed > 0 else "no_denominator",
            lead_clause=self.lead_clause(sealed),
        )

    # -- the utterance rules (T, rules 3 and 4) --------------------------------

    @staticmethod
    def lead_clause(observations: int) -> str:
        """The clause that opens a claim sentence when the sample is thin.

        The three forms are fixed (T): the lead is the uncertainty itself,
        never a footnote.
        """
        if observations >= MIN_OBSERVATIONS_FOR_CERTAINTY:
            return ""
        if observations == 0:
            return "This is a guess. I've nothing on you yet."
        return "This is a guess."


def _plural_observations(count: int) -> str:
    return f"{count} observation" if count == 1 else f"{count} observations"
