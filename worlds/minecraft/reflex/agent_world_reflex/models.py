"""The records of the world's skill library.

A **skill** is a tile: a small script that a local decision model may
choose, with an author, a family, a version and a play record for every
time it is used. The discipline is the tiles discipline from
``docs/design/tiles.md`` — content addressed, versioned per family,
retired rather than deleted — with one change: a tile in builder-ide is a
list of steps in a closed typed vocabulary, and a skill here is a small
JavaScript function over the mineflayer API.

That change does not loosen the door. The door for this world is
:mod:`agent_world_reflex.door`: a skill may only use the words in the
world's vocabulary, and the world refuses what it does not know rather
than repairing it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Skill",
    "SkillAuthor",
    "Precondition",
    "Prediction",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "FeedbackPacket",
    "SkillRefusal",
    "now_utc",
    "content_id",
    "canonical_bytes",
]

SkillKind = Literal["behaviour", "build_step"]
"""What a skill changes. The world's skills are behaviours (what a builder
does) and build steps (a step of a build). There is no recipe to edit
here: the world *is* the state, and the log is the history."""

OutcomeResult = Literal["win", "lose", "partial"]
OutcomeMeasure = Literal["sealed_prediction", "owner_keep", "owner_undo", "critic"]
"""The three measures, plus the one this world writes most of: a sealed
prediction that held. A skill says what it expects to change; the world
checks it; the record says which measure said so."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_bytes(payload: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def content_id(body: dict[str, Any]) -> str:
    """``skill_<12 hex>`` over the canonical body.

    The body is what a skill *is*: its family, kind, role, title, source,
    the words it uses, its preconditions and its prediction. The author
    and the timestamps are **not** in the hash, because the same script
    written twice by the same model is the same skill, and because a
    skill's id must not change when it is retired.
    """
    digest = hashlib.sha256(canonical_bytes(body)).hexdigest()
    return f"skill_{digest[:12]}"


class SkillRefusal(Exception):
    """The door refused a skill. The reason is a closed code.

    A refusal is never repaired and never clamped: a skill that names an
    unknown word is not a skill with a bad word in it, it is not a skill.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class SkillAuthor(BaseModel):
    """Who wrote it. Every skill records its author."""

    model_config = ConfigDict(frozen=True)

    model: str
    provider: Literal["groq", "minimax", "z.ai", "claude", "human", "seed"]
    prompt_hash: str = ""
    cost_cents: int = 0
    temperature: float | None = None


class Precondition(BaseModel):
    """A condition on the context. The same shape the tiles use."""

    key: str
    op: Literal["eq", "ne", "in", "gte", "lte", "lt", "gt"]
    value: Any = None


class Prediction(BaseModel):
    """What the skill expects to change. This is the measure.

    A skill that makes no prediction cannot be scored, so it cannot win
    and cannot lose: it is admitted, and it plays, and the play is
    recorded as ``partial``. The door prefers a prediction; it does not
    require one, because some skills are worth watching even when we
    cannot say what they did.
    """

    kind: Literal["inventory_delta", "block_placed", "block_broken", "moved_to", "none"] = "none"
    item: str = ""
    min: int = 1


class Skill(BaseModel):
    """One option: a script the decision model may choose."""

    id: str
    family: str
    version: int = 1
    kind: SkillKind = "behaviour"
    role: str
    title: str
    body: str
    api: tuple[str, ...] = ()
    preconditions: tuple[Precondition, ...] = ()
    predict: Prediction = Field(default_factory=Prediction)
    author: SkillAuthor
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_utc)
    status: Literal["active", "retired"] = "active"
    retired_at: str | None = None
    retire_reason: str | None = None

    # -- the door ---------------------------------------------------------------

    def is_eligible(self, context: dict[str, Any]) -> bool:
        """Whether this skill's preconditions hold in this context.

        The same rule the tiles use: a skill that cannot apply here is not
        an option, and a context with no eligible skill is a refusal with
        a named reason, never a fallback.
        """
        if self.status != "active":
            return False
        for pre in self.preconditions:
            if pre.key not in context:
                return False
            actual = context[pre.key]
            if not _compare(actual, pre.op, pre.value):
                return False
        return True


def _compare(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "in":
            return actual in expected
        if op == "gte":
            return float(actual) >= float(expected)
        if op == "lte":
            return float(actual) <= float(expected)
        if op == "lt":
            return float(actual) < float(expected)
        if op == "gt":
            return float(actual) > float(expected)
    except (TypeError, ValueError):
        return False
    return False


class Outcome(BaseModel):
    """What happened, and which measure said so."""

    result: OutcomeResult
    measure: OutcomeMeasure = "sealed_prediction"
    score: float | None = None
    detail: str = ""


class PlayCost(BaseModel):
    wall_seconds: float = 0.0
    gpu_minutes: float = 0.0
    hosted_cents: int = 0


class PlayRecord(BaseModel):
    """One use of a skill. This is the only thing that teaches anything."""

    id: str
    at: str
    skill_id: str
    skill_version: int
    context: dict[str, Any] = Field(default_factory=dict)
    outcome: Outcome
    cost: PlayCost = Field(default_factory=PlayCost)
    chooser: str = ""
    chooser_version: str = ""
    night: str | None = None
    # The probability the chooser measured at the choice. It cannot be
    # reconstructed afterwards, so it is measured when the choice is made.
    propensity: float | None = None
    candidates: tuple[str, ...] = ()

    @property
    def reward(self) -> float | None:
        """The reward the chooser's arithmetic needs: one number, or none.

        A **partial** play — the skill ran, but no sealed prediction
        could be checked — carries no signal about whether the skill
        works, so it carries **no reward**. The arithmetic that stood
        here before scored a partial as 0.5, which read "we could not
        measure this" as "this wins half the time": a fabricated,
        constant reward, and a high one — higher than any working
        gatherer's true rate. A skill that cannot be scored sat at 0.5
        on every play, taught the bandit nothing, and held its role on
        a number nobody measured (the scout's survey played 18,066
        times at exactly 0.5 on 2026-11-01). A partial is not half a
        win; it is no measurement.
        """
        if self.outcome.score is not None:
            return float(self.outcome.score)
        if self.outcome.result == "partial":
            return None
        return {"win": 1.0, "lose": 0.0}[self.outcome.result]


class FeedbackPacket(BaseModel):
    """What goes back to the cloud author. Deliberately blunt.

    "Write a better one; here is why it lost."
    """

    skill_id: str
    family: str
    kind: str
    api: tuple[str, ...] = ()
    plays: int = 0
    wins: int = 0
    win_rate: float = 0.0
    measure: str = ""
    contexts: tuple[str, ...] = ()
    request: str = ""
    source: str = ""
