"""The judgment records: typed questions, distributions, costs.

`docs/research/jev.md` names the seam and the shape: *typed verdicts with
probability distributions and a confidence score*. The liquid study
(`docs/research/liquid-study.md` §4.1, §1.4) established that the local d1
decision models answer **the same shape** — a probability over a fixed
option set, zero generated tokens — and that the 2B's confidence is a
usable gate (act at or above 0.5, escalate below).

Four question kinds, one canonical answer shape:

============  ==============================================================
kind          the question, and what comes back
============  ==============================================================
``choice``    named options; a probability per option; the argmax answers
``score``     an ordered scale of 2–10 levels; a probability per level
``noul``      a calibrated probability that a claim is true
``verify``    a claim checked against evidence — carried on the wire as a
              noul question, because that is what the System One backends
              accept; the record keeps the claim and the evidence apart
============  ==============================================================

Two rules this module enforces so no caller can forget them:

* **a distribution sums to one.** A probability vector that does not is
  not a judgment; it is a typo wearing one's clothes.
* **the pack is hashed.** A question set over one shared state is asked
  in one call (§4.1 measured the saving), and its hash — state plus
  questions, ids, kinds and order — is what every recorded verdict
  cites, so two judgments of the same pack are comparable and a changed
  question set is a different pack.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.canon import content_hash

__all__ = [
    "QuestionKind",
    "Question",
    "Judgment",
    "JudgeCost",
    "state_hash",
    "question_set_hash",
]

#: The four kinds of typed judgment.
QuestionKind = Literal["choice", "score", "noul", "verify"]

#: The gate decisions a judgment can carry. ``act`` at or above τ;
#: ``escalate`` below τ when a next backend exists; ``surfaced`` below τ
#: when the ladder is exhausted — a consequential low-confidence answer
#: is surfaced, not acted on (jev.md's rules).
GateDecision = Literal["act", "escalate", "surfaced"]

#: The keys of a noul/verify distribution, in wire order.
NOUL_KEYS: tuple[str, str] = ("false", "true")


def state_hash(state: str) -> str:
    """``sha256:…`` over the shared state the pack was asked over."""
    return content_hash(state)


def question_set_hash(questions: Sequence["Question"]) -> str:
    """``sha256:…`` over the pack — ids, kinds and order included.

    Two packs that differ in nothing but question order are different
    packs: a pack is a request, and the same questions in another order
    is another request.
    """
    body = [q.to_wire_record() for q in questions]
    return content_hash(body)


class Question(BaseModel):
    """One typed question inside a pack.

    ``criteria`` names the options of a ``choice`` (option id → what the
    option is); ``levels`` is the ordered scale of a ``score``; a
    ``noul`` is a bare claim; a ``verify`` carries the claim and the
    evidence it is checked against, and rides the wire as a noul.
    """

    model_config = ConfigDict(frozen=True)

    qid: str
    kind: QuestionKind
    instructions: str = ""
    criteria: dict[str, str | None] = Field(default_factory=dict)
    levels: tuple[str, ...] = ()
    claim: str = ""
    evidence: str = ""

    @field_validator("criteria")
    @classmethod
    def _criteria_keys_are_non_empty(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        for key in value:
            if not key:
                raise ValueError("an option key is non-empty")
        return value

    @model_validator(mode="after")
    def _the_kind_and_its_arguments_agree(self) -> "Question":
        if self.kind == "choice":
            if len(self.criteria) < 2:
                raise ValueError("a choice names at least two options")
            if self.levels or self.claim:
                raise ValueError("a choice takes criteria, not levels or a claim")
        elif self.kind == "score":
            if not 2 <= len(self.levels) <= 10:
                raise ValueError("a score is rated on an ordered scale of 2 to 10 levels")
            if self.criteria or self.claim:
                raise ValueError("a score takes levels, not criteria or a claim")
        elif self.kind == "noul":
            if self.criteria or self.levels or not self.instructions:
                raise ValueError("a noul is a claim in its instructions")
        elif self.kind == "verify":
            if not self.claim.strip():
                raise ValueError("a verify names the claim it checks")
            if self.criteria or self.levels:
                raise ValueError("a verify takes a claim and evidence, not options")
        return self

    # -- the reads -------------------------------------------------------------

    @property
    def option_keys(self) -> tuple[str, ...]:
        """The keys the answer's distribution is over, in wire order."""
        if self.kind == "choice":
            return tuple(sorted(self.criteria))
        if self.kind == "score":
            return tuple(str(i) for i in range(len(self.levels)))
        return NOUL_KEYS

    @property
    def distribution_keys(self) -> tuple[str, ...]:
        """Alias of :attr:`option_keys` — what a judgment of this question carries."""
        return self.option_keys

    # -- the wire --------------------------------------------------------------

    def to_wire(self) -> dict[str, Any]:
        """The canonical System One question shape.

        The same shape the liquid-study scripts post to llama-server's
        ``/v1/systemone``, and the same shape the Jev HTTP provider and
        the Clef Workers take inside their envelopes. ``verify`` becomes
        a noul whose instructions compose the claim and the evidence.
        """
        if self.kind == "choice":
            return {
                "type": "choice",
                "instructions": self.instructions,
                "criteria": dict(sorted(self.criteria.items())),
            }
        if self.kind == "score":
            return {"type": "score", "instructions": self.instructions, "criteria": list(self.levels)}
        if self.kind == "noul":
            return {"type": "noul", "instructions": self.instructions}
        # verify: the claim against the evidence, as a noul
        instructions = f"Claim: {self.claim}"
        if self.evidence:
            instructions += f"\nEvidence: {self.evidence}"
        instructions += "\nIs the claim true given the evidence?"
        return {"type": "noul", "instructions": instructions}

    def to_wire_record(self) -> dict[str, Any]:
        """The question as it enters the pack's hash — the typed record, not the wire."""
        return {
            "qid": self.qid,
            "kind": self.kind,
            "instructions": self.instructions,
            "criteria": dict(sorted(self.criteria.items())),
            "levels": list(self.levels),
            "claim": self.claim,
            "evidence": self.evidence,
        }


class Judgment(BaseModel):
    """One answered question, with its distribution and its gate decision.

    ``author`` is the house rule — every row records who made it — in the
    form ``judge@<backend>:<model>``. ``tau`` and ``gate`` are the
    confidence policy's decision on this judgment at the moment it was
    made; a judgment recorded without them was gated by no policy.
    """

    model_config = ConfigDict(frozen=True)

    qid: str
    kind: QuestionKind
    backend: str
    model: str
    distribution: dict[str, float]
    confidence: float | None = None
    tau: float | None = None
    #: Set when this judgment was escalated away from: a later rung's
    #: judgment governs. The row stays on the log — the edges are the story.
    escalated: bool = False

    @field_validator("confidence", "tau")
    @classmethod
    def _a_rate_is_a_rate(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("a confidence and a tau are rates in [0, 1]")
        return value

    @field_validator("distribution")
    @classmethod
    def _a_distribution_sums_to_one(
        cls, value: dict[str, float]
    ) -> dict[str, float]:
        if not value:
            raise ValueError("a judgment carries a distribution")
        total = sum(value.values())
        if not 0.999 <= total <= 1.001:
            raise ValueError(f"a distribution sums to one, not {total:.4f}")
        for key, probability in value.items():
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probability {key}={probability} is not in [0, 1]")
        return value

    # -- the reads -------------------------------------------------------------

    @property
    def author(self) -> str:
        return f"judge@{self.backend}:{self.model}"

    @property
    def gate(self) -> GateDecision | None:
        """The confidence policy's decision on this judgment.

        ``act`` at or above τ. Below τ the judgment is not acted on: when
        it was escalated to a later rung the decision reads
        ``escalate`` — the governing answer lives elsewhere — and when
        the ladder was exhausted it reads ``surfaced``, which is the
        record of an answer a human or a bigger system must look at
        before anything acts on it. ``None`` when no policy gated it.
        """
        if self.tau is None or self.confidence is None:
            return None
        if self.confidence >= self.tau:
            return "act"
        return "escalate" if self.escalated else "surfaced"

    @property
    def answer(self) -> str | bool:
        """The argmax: the option id of a choice/score, a bool of a noul/verify."""
        top = max(
            sorted(self.distribution), key=lambda key: self.distribution[key]
        )
        if self.kind in ("noul", "verify"):
            return top == "true"
        return top


class JudgeCost(BaseModel):
    """What a pack cost, in the units the budget speaks (§1.3).

    ``hosted_cents`` is what the cloud charged (computable for Clef from
    the published neuron rates; not published for Jev, whose
    ``input_tokens`` are recorded so the cost is recomputable when a
    price is known). A local backend costs GPU time and no cents.
    """

    model_config = ConfigDict(frozen=True)

    wall_seconds: float
    input_tokens: int = 0
    gpu_minutes: float = 0.0
    hosted_cents: float = 0.0
    cost_known: bool = True

    def added(self, other: "JudgeCost") -> "JudgeCost":
        """The cost of two attempts on one question — an escalation's bill."""
        return JudgeCost(
            wall_seconds=self.wall_seconds + other.wall_seconds,
            input_tokens=self.input_tokens + other.input_tokens,
            gpu_minutes=self.gpu_minutes + other.gpu_minutes,
            hosted_cents=self.hosted_cents + other.hosted_cents,
            cost_known=self.cost_known and other.cost_known,
        )


def judgment_from_distribution(
    *,
    question: Question,
    backend: str,
    model: str,
    distribution: Mapping[str, float],
    confidence: float | None,
) -> Judgment:
    """Build a judgment, renormalising against the question's own keys.

    A backend that omits an option (a d1 head that never saw an option
    as argmax still assigns it its probability) gets it at 0.0; the
    vector is completed and renormalised so the sum-to-one rule holds of
    everything that reaches the ledger.
    """
    keys = question.option_keys
    missing = [key for key in keys if key not in distribution]
    extra = [key for key in distribution if key not in keys]
    if extra:
        raise ValueError(
            f"backend {backend} answered option(s) {extra} the question does not name"
        )
    vector = {key: float(distribution.get(key, 0.0)) for key in keys}
    total = sum(vector.values())
    if total <= 0.0:
        raise ValueError(f"backend {backend} returned a non-positive distribution")
    return Judgment(
        qid=question.qid,
        kind=question.kind,
        backend=backend,
        model=model,
        distribution={key: value / total for key, value in vector.items()},
        confidence=None if confidence is None else float(confidence),
    )
