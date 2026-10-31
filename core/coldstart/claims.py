"""Rendering a taste claim — the utterance gate, in code (T rules 3 and 4; gaps §7 test 3).

"A builder must not predict on a reason code where it has fewer than two
prior observations. No evidence, no claim. This is a hard gate at generation
time, not a style instruction" — so a claim line below the gate does not
render at all; there is no softened version that squeaks through. What the
caller gets instead is the refusal with the counts, which is exactly the
material ask-mode turns into a two-chip question.

A line that does render must cite counts, not adjectives, carry its own
denominator, and — under three observations — lead with its own uncertainty
(T §"The 'I think you'll like this' utterance"): the lead is the first
clause, never a footnote.
"""

from __future__ import annotations

from dataclasses import dataclass

from .gate import ColdStartGate

__all__ = ["ClaimLine"]


@dataclass(frozen=True)
class ClaimLine:
    """Either a rendered line or the gate's refusal — never both, never neither."""

    line: str | None
    refusal_reason: str | None
    basis: str
    observations: int

    @property
    def rendered(self) -> bool:
        return self.line is not None


def render_taste_claim(
    gate: ColdStartGate,
    *,
    builder: str,
    reason_code: str,
    claim: str,
) -> ClaimLine:
    """Render `claim` for speaking, or refuse it below the two-observation gate."""
    decision = gate.decide(builder, reason_code)
    if not decision.may_speak:
        return ClaimLine(
            line=None,
            refusal_reason=decision.refusal,
            basis=decision.basis,
            observations=decision.observations,
        )
    lead = f"{decision.lead_clause} " if decision.lead_clause else ""
    return ClaimLine(
        line=f"{lead}{claim} — {decision.basis}",
        refusal_reason=None,
        basis=decision.basis,
        observations=decision.observations,
    )
