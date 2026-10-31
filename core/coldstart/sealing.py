"""Sealing under the melt: which confidence a builder may write (spec §3.5; decision 13a).

The `vocab` seat's sealer is deliberately permissive — a sealed record with
`confidence: "guess"` is always permitted, because the gate "forbids
pretending to a view, not betting" (G §1 20:44). This policy is the other
side of the same honesty, and it is mechanical, per builder, per reason code:

* **below two observations** a taste bet must wear `guess` — sealing a real
  confidence on a code the builder has barely observed would be a claim
  dressed as a bet (`no_basis_yet`);
* **at two or more** the bet must carry a real confidence with its
  denominator ("2/2 kept") — sealing `guess` on a code the builder has
  observations for would be dodging the record it is about to be scored on
  (`guess_expired`).

The confidence is therefore **not the builder's choice**: it is computed from
the ledger, stamped with the basis that justifies it, and any caller-supplied
value that disagrees is refused. The melt is auditable because every seal
event carries the basis in its sealed payload, and the counts fold back out
of the log (§1.7).

World bets follow the spec's own gloss (§1.7: `guess` is *the zero-prior
bet*): a world claim type with no sealed history seals `guess`/"0
observations"; with a denominator the confidence follows the ratio rules, and
a supplied `guess` against a non-zero history is refused (`guess_expired`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .gate import ColdStartGate
from .models import Actor, Prediction
from .ports import SealerPort

__all__ = ["SealPolicyRefusal", "ColdStartSealer"]


class SealPolicyRefusal(Exception):
    """The cold-start seal policy refused a write. Closed reason codes."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SealedUnderPolicy:
    prediction: Prediction
    confidence: str
    basis: str
    observations: int
    mode: str


class ColdStartSealer:
    """Seals bets with the melt's confidence computed, never chosen."""

    def __init__(
        self,
        *,
        ledger: Any,
        clock: Any,
        sealer: SealerPort,
        gate: ColdStartGate | None = None,
        author: str = "casey",
    ) -> None:
        self._sealer = sealer
        self._gate = gate or ColdStartGate(ledger, author=author)

    def seal_taste_bet(
        self,
        *,
        builder: str,
        reason_code: str,
        claim: str,
        branch_ref: str,
        render_spec: Mapping[str, Any] | None = None,
        confidence: str | None = None,
        actor: Actor | None = None,
    ) -> SealedUnderPolicy:
        """Seal a `taste_keep` bet under the two-observation policy."""
        decision = self._gate.decide(builder, reason_code)
        if confidence is not None and confidence != decision.confidence:
            self._refuse_confidence(confidence, decision)
        prediction = self._sealer.seal(
            builder=builder,
            claim=claim,
            claim_type="taste_keep",
            confidence=decision.confidence,
            basis=decision.basis,
            branch_ref=branch_ref,
            render_spec=render_spec,
            reason_code=reason_code,
            actor=actor,
        )
        return SealedUnderPolicy(
            prediction=prediction,
            confidence=decision.confidence,
            basis=decision.basis,
            observations=decision.observations,
            mode=decision.mode,
        )

    def seal_world_bet(
        self,
        *,
        builder: str,
        claim_type: str,
        claim: str,
        branch_ref: str,
        render_spec: Mapping[str, Any] | None = None,
        confidence: str | None = None,
        actor: Actor | None = None,
    ) -> SealedUnderPolicy:
        """Seal a world bet — `guess` only while the claim type has no history."""
        decision = self._gate.decide_world(builder, claim_type)
        if confidence is not None and confidence != decision.confidence:
            self._refuse_confidence(confidence, decision)
        prediction = self._sealer.seal(
            builder=builder,
            claim=claim,
            claim_type=claim_type,
            confidence=decision.confidence,
            basis=decision.basis,
            branch_ref=branch_ref,
            render_spec=render_spec,
            actor=actor,
        )
        return SealedUnderPolicy(
            prediction=prediction,
            confidence=decision.confidence,
            basis=decision.basis,
            observations=decision.observations,
            mode=decision.mode,
        )

    @staticmethod
    def _refuse_confidence(confidence: str, decision: Any) -> None:
        if confidence == "guess":
            raise SealPolicyRefusal(
                "guess_expired",
                f"{decision.observations} observations on {decision.key!r}: "
                "the melt is past guesses; seal the confidence the ledger shows",
            )
        raise SealPolicyRefusal(
            "no_basis_yet",
            f"{decision.observations} observations on {decision.key!r}: "
            "below the two-observation gate the bet wears 'guess'",
        )
