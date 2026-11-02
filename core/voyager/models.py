"""The records — what the loop writes down.

Every number the report quotes comes from one of these. They are frozen
where the house rule asks for it (the rule is ``core.tiles.models``'s:
*an identity is frozen, the log must not be able to rewrite it after the
fact*), and plain dataclasses where the record is a running tally.

The two vocabularies the house uses:

* **disposition** — what happened to a proposed skill: ``admitted``,
  ``rejected`` or ``superseded``;
* **verdict** — what the verifier model said: ``CONFIRMED``,
  ``DENIED`` or ``INCONCLUSIVE``, the three answers the autopilot
  harness uses (``docs/research/autopilot.md`` §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

__all__ = [
    "Role",
    "Disposition",
    "Verdict",
    "TokenUsage",
    "ModelReply",
    "Milestone",
    "SkillProposal",
    "SkillRecord",
    "StepRecord",
    "RunReport",
]

#: The three model roles. The verifier is a different model from the
#: coder: a model that grades its own code measures nothing.
Role = Literal["planner", "coder", "verifier"]

#: What happened to a proposed skill.
Disposition = Literal["admitted", "rejected", "superseded"]

#: What the verifier said.
Verdict = Literal["CONFIRMED", "DENIED", "INCONCLUSIVE"]


@dataclass(frozen=True)
class TokenUsage:
    """One model call's cost.

    ``prompt_tokens`` and ``completion_tokens`` are what DeepInfra
    reports; ``cost_cents`` is what the run is billed at, when the
    provider's price is known, and ``None`` when it is not — an unknown
    price is not zero.
    """

    role: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cost_cents: int | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "seconds": round(self.seconds, 2),
            "cost_cents": self.cost_cents,
        }


@dataclass(frozen=True)
class ModelReply:
    """A model's answer, and what it cost."""

    text: str
    usage: TokenUsage

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "usage": self.usage.as_dict()}


@dataclass(frozen=True)
class Milestone:
    """One rung of the tech tree.

    ``needs`` are the milestones that must be reached first, so the
    curriculum never asks for iron before a pickaxe exists. ``weight`` is
    a mild prior on how eagerly the milestone is tried; the novelty term
    in :mod:`core.voyager.curriculum` does the rest of the work.
    """

    key: str
    title: str
    description: str
    needs: tuple[str, ...] = ()
    weight: float = 1.0
    #: The items whose presence in the inventory means this milestone is
    #: reached. The adapter's ground truth reads the world; the core
    #: only carries the definition.
    items: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "needs": list(self.needs),
            "weight": self.weight,
            "items": list(self.items),
        }


@dataclass(frozen=True)
class SkillProposal:
    """A skill a model wrote, before it is admitted.

    ``code`` is the body; ``verify_code`` is the model's own
    self-verification snippet, a second opinion on whether the goal was
    reached. ``primitives`` are the closed-vocabulary words the body
    says it uses — the door checks them, and the sandbox enforces them.
    """

    title: str
    description: str
    family: str
    code: str
    verify_code: str = ""
    primitives: tuple[str, ...] = ()
    milestone: str = ""
    language: str = "javascript"

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "family": self.family,
            "code": self.code,
            "verify_code": self.verify_code,
            "primitives": list(self.primitives),
            "milestone": self.milestone,
            "language": self.language,
        }


@dataclass(frozen=True)
class SkillRecord:
    """A skill's entry in the library, and what became of it."""

    id: str
    title: str
    family: str
    version: int
    disposition: Disposition
    milestone: str = ""
    body_sha256: str = ""
    author_model: str = ""
    author_role: str = ""
    prompt_hash: str = ""
    created_at: str = ""
    reason: str = ""
    superseded_by: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "family": self.family,
            "version": self.version,
            "disposition": self.disposition,
            "milestone": self.milestone,
            "body_sha256": self.body_sha256,
            "author_model": self.author_model,
            "author_role": self.author_role,
            "prompt_hash": self.prompt_hash,
            "created_at": self.created_at,
            "reason": self.reason,
            "superseded_by": self.superseded_by,
        }


@dataclass
class StepRecord:
    """One turn of the loop: goal, plan, skill, execution, verdict.

    This is the unit the run's numbers are counted in, and the unit the
    ledger's ``tile.played`` row refers to.
    """

    index: int
    at: str
    goal: str
    plan: tuple[str, ...] = ()
    proposal: SkillProposal | None = None
    exec_ok: bool = False
    exec_error: str = ""
    exec_log: tuple[str, ...] = ()
    exec_seconds: float = 0.0
    self_verified: bool | None = None
    truth: bool = False
    verdict: Verdict = "INCONCLUSIVE"
    verdict_detail: str = ""
    disposition: Disposition = "rejected"
    reason: str = ""
    skill_id: str = ""
    usage: tuple[TokenUsage, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self.usage)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "at": self.at,
            "goal": self.goal,
            "plan": list(self.plan),
            "proposal": self.proposal.as_dict() if self.proposal else None,
            "exec_ok": self.exec_ok,
            "exec_error": self.exec_error,
            "exec_log": list(self.exec_log),
            "exec_seconds": round(self.exec_seconds, 2),
            "self_verified": self.self_verified,
            "truth": self.truth,
            "verdict": self.verdict,
            "verdict_detail": self.verdict_detail,
            "disposition": self.disposition,
            "reason": self.reason,
            "skill_id": self.skill_id,
            "usage": [u.as_dict() for u in self.usage],
            "total_tokens": self.total_tokens,
            "facts": dict(self.facts),
        }


@dataclass
class RunReport:
    """The run, counted.

    ``milestone_tokens`` is the headline the brief asks for: the tokens
    spent **before** each milestone was first reached, so the cost of a
    milestone is a cumulative number that grows with the run rather than
    a per-step number that hides the search.
    """

    world: str = ""
    started_at: str = ""
    finished_at: str = ""
    wall_seconds: float = 0.0
    steps: list[StepRecord] = field(default_factory=list)
    unique_items: int = 0
    items: dict[str, int] = field(default_factory=dict)
    milestones_reached: tuple[str, ...] = ()
    milestone_seconds: dict[str, float] = field(default_factory=dict)
    milestone_tokens: dict[str, int] = field(default_factory=dict)
    skills_admitted: int = 0
    skills_rejected: int = 0
    skills_superseded: int = 0
    tokens_by_role: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    cost_cents: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "world": self.world,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "wall_seconds": round(self.wall_seconds, 1),
            "steps": [s.as_dict() for s in self.steps],
            "unique_items": self.unique_items,
            "items": dict(self.items),
            "milestones_reached": list(self.milestones_reached),
            "milestone_seconds": dict(self.milestone_seconds),
            "milestone_tokens": dict(self.milestone_tokens),
            "skills_admitted": self.skills_admitted,
            "skills_rejected": self.skills_rejected,
            "skills_superseded": self.skills_superseded,
            "tokens_by_role": dict(self.tokens_by_role),
            "total_tokens": self.total_tokens,
            "cost_cents": self.cost_cents,
        }


def sum_usage(usages: Sequence[TokenUsage]) -> int:
    """The tokens in a sequence of usage records."""
    return sum(u.total_tokens for u in usages)
