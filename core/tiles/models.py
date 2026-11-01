"""The tile seat's records — the tile, the play, the outcome.

`docs/design/tiles.md` is the contract; the citations in each docstring are
the pointers back to it.

    §1  the tile: a script in the closed, typed vocabulary
    §2  the library's tile: content addressed, versioned, never deleted
    §3  the play record: context, outcome, measure, cost, chooser
    §5  the feedback packet: "write a better one, here is why it lost"

Two rules shape everything here:

* **a tile is content addressed.** Its id is the hash of its body, so the
  same script is the same tile whoever wrote it, and a tile's body never
  changes — only its status does (``retired``).
* **the outcome says how it was measured.** ``win`` is not one thing: the
  critic's verdict, the owner's keep, the owner's undo and a sealed
  prediction that held are four different measurements, and the record says
  which one it was.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.canon import content_hash, is_content_hash, now_utc, short_hash

__all__ = [
    "Json",
    "TileKind",
    "TileStatus",
    "OutcomeMeasure",
    "OutcomeResult",
    "PreconditionOp",
    "StepOp",
    "REWARD_BY_RESULT",
    "TileRefusal",
    "TileAuthor",
    "Precondition",
    "TileStep",
    "Tile",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "FeedbackPacket",
    "build_tile",
    "build_play_record",
]

Json = Any

#: §1 — the three kinds of tile.
TileKind = Literal["behaviour", "build_step", "recipe_edit"]

#: §2 — a tile is retired, never deleted.
TileStatus = Literal["active", "retired"]

#: §3 — what measured the outcome.
OutcomeMeasure = Literal["critic", "owner_keep", "owner_undo", "sealed_prediction"]

#: §3 — what happened.
OutcomeResult = Literal["win", "lose", "partial"]

#: §1 — the operators a precondition may use.
PreconditionOp = Literal["eq", "ne", "in", "gte", "lte", "lt", "gt"]

#: §1 — the operators a step may use against the recipe.
StepOp = Literal["set", "add", "remove"]

#: §3 — the reward mapping. Fixed, and stated rather than tuned per tile:
#: the critic's verdict is a coarse three-valued thing, and the chooser
#: needs one number. A measure that brings its own score overrides this.
REWARD_BY_RESULT: dict[str, float] = {"win": 1.0, "partial": 0.5, "lose": 0.0}


class TileRefusal(Exception):
    """A tile write that is refused. Carries a closed reason code.

    The reason is the code the caller branches on; the detail is for the
    log. Refusals are not failures to be retried: a tile the vocabulary
    does not admit is a *wrong* tile.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class TileAuthor(BaseModel):
    """Who wrote the tile, and what that cost (§1).

    ``prompt_hash`` is what makes a tile comparable: two tiles written by the
    same model from the same prompt are the same tile, and the hash says so
    without keeping the prompt itself.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    provider: str
    prompt_hash: str
    cost_cents: int = 0
    temperature: float | None = None

    @field_validator("prompt_hash")
    @classmethod
    def _prompt_hash_is_a_content_hash(cls, value: str) -> str:
        if not is_content_hash(value):
            raise ValueError("prompt_hash must be a sha256 content hash")
        return value


class Precondition(BaseModel):
    """A condition on the game context a tile needs (§1).

    A precondition that does not hold means the tile is **not an option** —
    it is not scored, not played, and not counted against anything.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    op: PreconditionOp
    value: Json

    def holds(self, context: Mapping[str, Json]) -> bool:
        """True when this condition holds in ``context``.

        A key that is not in the context does **not** hold: the context is
        what the game knows, and a condition the game cannot answer is not
        a condition that was met.
        """
        if self.key not in context:
            return False
        actual = context[self.key]
        if self.op == "eq":
            return actual == self.value
        if self.op == "ne":
            return actual != self.value
        if self.op == "in":
            try:
                return actual in self.value
            except TypeError:
                return False
        return _compare(actual, self.value, self.op)


class TileStep(BaseModel):
    """One step of a tile's script: a vocabulary word and its params (§1).

    ``params`` is bounded by the word's own schema, exactly as a builder's
    call is. A tile that names an unknown word, or a parameter outside the
    schema, is refused at the door.
    """

    model_config = ConfigDict(frozen=True)

    word: str
    path: str
    op: StepOp = "set"
    params: dict[str, Json] = Field(default_factory=dict)


class Tile(BaseModel):
    """A script a cloud model wrote, in the closed vocabulary (§1).

    **Frozen.** A tile's body never changes: it is content addressed, so a
    changed body is a *different* tile. The only thing that changes is the
    status — a tile leaves the eligible set by being retired, and it keeps
    its body, its plays and its history (§2).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    family: str
    version: int = 1
    kind: TileKind
    title: str
    steps: tuple[TileStep, ...] = ()
    preconditions: tuple[Precondition, ...] = ()
    author: TileAuthor
    provenance: dict[str, Json] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_utc)
    status: TileStatus = "active"
    retired_at: str | None = None
    retire_reason: str | None = None

    @field_validator("steps")
    @classmethod
    def _a_tile_has_at_least_one_step(cls, value: tuple[TileStep, ...]):
        if not value:
            raise ValueError("a tile has at least one step")
        return value

    @field_validator("retire_reason")
    @classmethod
    def _a_retired_tile_says_why(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("a retired tile says why it was retired")
        return value

    @model_validator(mode="after")
    def _a_retired_tile_is_dated_and_reasoned(self) -> "Tile":
        if self.status == "retired":
            if not self.retired_at:
                raise ValueError("a retired tile carries the moment it was retired")
            if not self.retire_reason:
                raise ValueError("a retired tile says why it was retired")
        return self

    # -- the body --------------------------------------------------------------

    def body(self) -> dict[str, Json]:
        """The canonical body — what the content hash covers.

        The status is **not** in it: retiring a tile does not change what
        the tile is, and two tiles that differ only in status are the same
        tile. The *family* is in it — what a tile is **for** is part of what
        it is, so the same script serving two families is two options.
        """
        return {
            "family": self.family,
            "kind": self.kind,
            "title": self.title,
            "steps": [step.model_dump() for step in self.steps],
            "preconditions": [p.model_dump() for p in self.preconditions],
            "author": self.author.model_dump(),
        }

    @property
    def content_hash(self) -> str:
        """``sha256:…`` over the canonical body (§2)."""
        return content_hash(self.body())

    @property
    def words(self) -> tuple[str, ...]:
        """The vocabulary words the tile uses, in order, without repeats."""
        seen: list[str] = []
        for step in self.steps:
            if step.word not in seen:
                seen.append(step.word)
        return tuple(seen)

    # -- eligibility -----------------------------------------------------------

    def is_eligible(self, context: Mapping[str, Json]) -> bool:
        """True when every precondition holds in ``context`` (§4)."""
        return all(p.holds(context) for p in self.preconditions)

    def unmet(self, context: Mapping[str, Json]) -> tuple[str, ...]:
        """The keys of the preconditions that do not hold — for the log."""
        return tuple(p.key for p in self.preconditions if not p.holds(context))

    # -- the two state changes a tile may undergo ------------------------------

    def retired(self, *, reason: str, at: str | None = None) -> "Tile":
        """A retired copy of this tile. The original is untouched (§2)."""
        return self.model_copy(
            update={
                "status": "retired",
                "retired_at": at or now_utc(),
                "retire_reason": reason,
            }
        )

    def at_version(self, version: int) -> "Tile":
        """A copy stamped with the library's version number (§2)."""
        return self.model_copy(update={"version": version})


class Outcome(BaseModel):
    """What happened when a tile was played, and how it was measured (§3)."""

    model_config = ConfigDict(frozen=True)

    result: OutcomeResult
    measure: OutcomeMeasure
    score: float | None = None
    detail: str = ""

    @field_validator("score")
    @classmethod
    def _score_is_a_reward(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("a score is a reward in [0, 1]")
        return value

    @property
    def reward(self) -> float:
        """The number the chooser learns from."""
        if self.score is not None:
            return self.score
        return REWARD_BY_RESULT[self.result]


class PlayCost(BaseModel):
    """What the play cost (§3)."""

    model_config = ConfigDict(frozen=True)

    gpu_minutes: float = 0.0
    wall_seconds: float = 0.0
    hosted_cents: int = 0


class PlayRecord(BaseModel):
    """One use of a tile, recorded (§3).

    The context is on the record because a play without its context cannot
    be learned from — that is the whole difference between a contextual
    bandit and a lookup table.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    at: str
    tile_id: str
    tile_version: int
    context: dict[str, Json] = Field(default_factory=dict)
    outcome: Outcome
    cost: PlayCost = Field(default_factory=PlayCost)
    chooser: str = ""
    chooser_version: str = ""
    night: str | None = None
    #: How likely the chooser was to make this choice, in this state, at
    #: that moment. Without it the play cannot be weighted for an
    #: off-policy estimate (:mod:`core.tiles.ope`). ``None`` means it was
    #: not measured — never a default of 1.0, which would be a bias nobody
    #: could see.
    propensity: float | None = None
    #: The eligible set the choice was made from. A target policy's
    #: probability has to normalise over the same set, so this travels with
    #: the play.
    candidates: tuple[str, ...] = ()
    #: The name of the decision this play answers — the bucket, usually.
    #: It is the join key the calibration fold uses to pair a judgment with
    #: the play that answers it (``core.judge.tracking``). ``None`` when the
    #: caller did not name one: the play is still recorded, it is just not
    #: scored.
    scope: str | None = None

    @property
    def reward(self) -> float:
        return self.outcome.reward

    @property
    def won(self) -> bool:
        return self.outcome.result == "win"


class FeedbackPacket(BaseModel):
    """A losing tile, handed back to the cloud author (§5).

    "Write a better one, here is why it lost." The packet carries the
    denominator with every rate, because a rate without one is a
    fabrication.
    """

    model_config = ConfigDict(frozen=True)

    tile_id: str
    family: str
    kind: TileKind
    words: tuple[str, ...] = ()
    plays: int = 0
    wins: int = 0
    win_rate: float = 0.0
    measure: str = ""
    contexts: tuple[str, ...] = ()
    request: str = ""


# --- the builders ------------------------------------------------------------


def build_tile(
    *,
    family: str,
    kind: str,
    title: str,
    steps: tuple[TileStep, ...],
    author: TileAuthor,
    preconditions: tuple[Precondition, ...] = (),
    provenance: Mapping[str, Json] | None = None,
    created_at: str | None = None,
) -> Tile:
    """Build a tile whose id **is** its content address (§1, §2).

    The version is left at 1: the library owns it (§2), because the author
    does not get to claim a version number.
    """
    body = {
        "family": family,
        "kind": kind,
        "title": title,
        "steps": [step.model_dump() for step in steps],
        "preconditions": [p.model_dump() for p in preconditions],
        "author": author.model_dump(),
    }
    return Tile(
        id=f"tile_{short_hash(body, 12)}",
        family=family,
        version=1,
        kind=kind,  # type: ignore[arg-type]
        title=title,
        steps=tuple(steps),
        preconditions=tuple(preconditions),
        author=author,
        provenance=dict(provenance or {}),
        created_at=created_at or now_utc(),
    )


def build_play_record(
    *,
    at: str,
    tile: Tile,
    context: Mapping[str, Json],
    outcome: Outcome,
    cost: PlayCost | None = None,
    chooser: str = "",
    chooser_version: str = "",
    night: str | None = None,
    propensity: float | None = None,
    candidates: Sequence[str] = (),
    scope: str | None = None,
) -> PlayRecord:
    """Build a play record. Its id is derived from the play itself (§3).

    Content-derived, so a replay of the same night produces the same ids —
    the house rule that a rebuild gives the same answer.
    """
    payload = {
        "at": at,
        "tile_id": tile.id,
        "tile_version": tile.version,
        "context": dict(context),
        "outcome": outcome.model_dump(),
        "cost": (cost or PlayCost()).model_dump(),
        "chooser": chooser,
        "chooser_version": chooser_version,
        "night": night,
        "propensity": propensity,
        "candidates": list(candidates),
        "scope": scope,
    }
    return PlayRecord(
        id=f"play_{short_hash(payload, 12)}",
        at=at,
        tile_id=tile.id,
        tile_version=tile.version,
        context=dict(context),
        outcome=outcome,
        cost=cost or PlayCost(),
        chooser=chooser,
        chooser_version=chooser_version,
        night=night,
        propensity=propensity,
        candidates=tuple(candidates),
        scope=scope,
    )


# --- internals ---------------------------------------------------------------


def _compare(actual: Any, expected: Any, op: str) -> bool:
    """A numeric comparison that refuses rather than raising."""
    try:
        left = float(actual)  # type: ignore[arg-type]
        right = float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if op == "gte":
        return left >= right
    if op == "lte":
        return left <= right
    if op == "gt":
        return left > right
    if op == "lt":
        return left < right
    return False
