"""The iterator's seams — variants, the critic, the power meter, the depth policy.

A night task is **no longer one attempt** (core-spec v2 §3.2.4): for each goal
the night generates **N variants**, scores each with the critic, keeps the
best and **refines from it** (warm start) for up to **K rounds**, or until the
score stops improving by more than **ε**.

This module holds the small interfaces the loop is written against, so the
engine and the GPU stations can be swapped in without touching the loop:

* :class:`VariantSource` — *what else could we try?* Seeds, parameter
  perturbations and alternative recipe edits all come through this one door;
* :class:`Critic` — *how good is it?* The score that picks the winner. It is
  scripted for now, behind the seam;
* :class:`PowerMeter` — *what did it cost in joules?* It reads the board's
  **measured** rails (the whole-box ``VIN`` rail drew 47.5 W under load —
  ``docs/lab/exp-engines.md`` §4.4). A box whose rails nobody has measured
  still gets ``None``, and the field stays **unmeasured** rather than
  guessed;
* :class:`IterationPolicy` — the depth of the night (N, K, ε). It is part of
  the **rails**, so it is written into ``night.started`` and folded back like
  the rest of the bar.

Two rules the whole thing rests on:

* **determinism** — the same goal gives the same variants every time, because
  seeds are first-class (spec §1.9) and a night's work has to be replayable
  from its recipe (§1.1);
* **nothing is invented** — the critic refuses to score a variant it was not
  given a score for, and the power meter returns ``None`` rather than a
  plausible-looking number.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field

from core.night.cost.model import get_model
from core.night.cost.records import PowerRails
from core.night.models import IterationPolicy, Task

__all__ = [
    "Attempt",
    "Critic",
    "CriticScore",
    "IterationPolicy",
    "NullPowerMeter",
    "PerturbationSource",
    "PowerMeter",
    "RailPowerMeter",
    "RoundSummary",
    "ScriptedCritic",
    "ScriptedVariantSource",
    "Variant",
    "VariantSource",
    "best_of",
    "gain_of",
    "summarise_rounds",
]


class Variant(BaseModel):
    """One candidate for a goal: a seed, a parameter set, or a recipe edit.

    ``parent_id`` says where it came from — a variant refined from the
    previous round's winner carries that winner's id, and an independent
    alternative carries none. The morning shows both, because "we refined the
    best one" and "we tried something else" are different facts.
    """

    id: str
    label: str = ""
    seed: int | None = None
    params: dict[str, float] = Field(default_factory=dict)
    edit: dict[str, Any] | None = None
    parent_id: str | None = None
    round: int = 0


class CriticScore(BaseModel):
    """The critic's judgement of one variant."""

    score: float
    reason: str = ""
    degraded: bool = False


class Attempt(BaseModel):
    """One variant attempt: what it was, what it cost and what it scored.

    The log's fold produces these, and the morning reads them — the attempt is
    the unit the report talks about ("this variant beat that one").
    """

    task_id: str
    variant_id: str
    label: str = ""
    round: int = 1
    parent_id: str | None = None
    score: float = 0.0
    outcome: str = "kept"
    reason: str | None = None
    critic_reason: str = ""
    gpu_minutes: float = 0.0
    wall_minutes: float = 0.0
    hosted_cents: int = 0
    joules: float | None = None


@runtime_checkable
class VariantSource(Protocol):
    """What else could we try for this goal?"""

    def variants(
        self, task: Task, *, round: int, parent: Variant | None, count: int
    ) -> list[Variant]:
        """``count`` candidates for ``task`` in ``round``.

        ``parent`` is the winner of the previous round — the warm start — or
        ``None`` in the first round. A source that refines the parent says so
        by setting the child's ``parent_id``; a source that offers an
        independent alternative leaves it empty.
        """


@runtime_checkable
class Critic(Protocol):
    """How good is this variant?"""

    def score(self, task: Task, variant: Variant) -> CriticScore:
        """Score one variant. It must not invent a score it did not measure."""


@runtime_checkable
class PowerMeter(Protocol):
    """What did the attempt cost in joules?"""

    def joules(self, *, gpu_minutes: float, wall_minutes: float) -> float | None:
        """The joules the attempt cost, or ``None`` when it was not measured."""


# -- the implementations ---------------------------------------------------


def _unit(key: str) -> float:
    """A deterministic number in [0, 1) for a key — no clock, no randomness."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def _delta(key: str) -> float:
    """A deterministic step in [-1, 1] that is never zero."""
    value = _unit(key)
    sign = -1.0 if value < 0.5 else 1.0
    magnitude = 0.05 + 0.95 * abs(value - 0.5) * 2.0
    return sign * min(1.0, magnitude)


def _seed_for(key: str) -> int:
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % (2**31 - 1)


class PerturbationSource:
    """Seeds and parameter perturbations around the warm start.

    Round one perturbs the base parameters; later rounds perturb the parent's
    parameters, so the loop narrows in on the winner instead of starting over.
    The step is deterministic, so the night's work replays.
    """

    def __init__(
        self,
        base_params: Mapping[str, float] | None = None,
        *,
        spread: float = 0.1,
    ) -> None:
        self._base_params = dict(base_params or {})
        self._spread = spread

    def variants(
        self, task: Task, *, round: int, parent: Variant | None, count: int
    ) -> list[Variant]:
        base = dict(parent.params) if parent is not None else dict(self._base_params)
        out: list[Variant] = []
        for index in range(count):
            key = f"{task.id}:{round}:{index}"
            seed = _seed_for(key)
            delta = _delta(f"{key}:delta") * self._spread
            params = {name: value * (1.0 + delta) for name, value in base.items()}
            out.append(
                Variant(
                    id=f"{task.id}_r{round}_v{index + 1}",
                    label=f"seed {seed}",
                    seed=seed,
                    params=params,
                    parent_id=parent.id if parent is not None else None,
                    round=round,
                )
            )
        return out


class ScriptedVariantSource:
    """The scripted variants: a task's round, spelled out.

    ``scripts`` maps a task id to its rounds and their variants. A round that
    is not scripted produces nothing — the loop then stops and says so,
    rather than inventing candidates.
    """

    def __init__(
        self, scripts: Mapping[str, Mapping[int, Sequence[Variant]]] | None = None
    ) -> None:
        self._scripts = {
            task_id: {round_no: list(variants) for round_no, variants in rounds.items()}
            for task_id, rounds in (scripts or {}).items()
        }

    def variants(
        self, task: Task, *, round: int, parent: Variant | None, count: int
    ) -> list[Variant]:
        scripted = self._scripts.get(task.id, {}).get(round, [])
        out: list[Variant] = []
        for variant in scripted:
            updates: dict[str, Any] = {"round": round}
            if variant.parent_id is None and parent is not None:
                updates["parent_id"] = parent.id
            out.append(variant.model_copy(update=updates))
        return out


class ScriptedCritic:
    """The scripted critic: a score per variant, and nothing else.

    A variant it was not given a score for raises: a score nobody measured
    must never win a variant by accident.
    """

    def __init__(
        self, scores: Mapping[str, Mapping[str, CriticScore]] | None = None
    ) -> None:
        self._scores = {
            task_id: dict(variants) for task_id, variants in (scores or {}).items()
        }

    def score(self, task: Task, variant: Variant) -> CriticScore:
        by_variant = self._scores.get(task.id, {})
        if variant.id not in by_variant:
            raise KeyError(
                f"no scripted score for variant {variant.id!r} of task {task.id!r}"
            )
        return by_variant[variant.id]


class NullPowerMeter:
    """The power meter that reads nothing.

    The stand-in for a box whose rails nobody has measured: the joules field
    stays **unmeasured** (``None``) — never a guess, and never a zero
    pretending to be a measurement.
    """

    def joules(self, *, gpu_minutes: float, wall_minutes: float) -> float | None:
        return None

    def joules_above_idle(self, *, gpu_minutes: float, wall_minutes: float) -> float | None:
        return None


class RailPowerMeter:
    """The power meter that reads the board's rails.

    Lab round 3 measured them (``docs/lab/exp-engines.md`` §4.4): the
    INA238's whole-box ``VIN`` rail drew **47.5 W** under load, and the
    board's own rail sensors agree with ``tegrastats`` to within 0.1 %. The
    box's idle floor is 26.5 W (``docs/research/split.md`` §5).

    So an attempt's joules are the box's draw over the attempt's wall time:
    the whole box runs while the attempt runs, whichever lane it is on. The
    reading *above* the idle floor is the other one the lab asks for — the
    work's own cost (``docs/lab/IDEAS.md`` #17) — and it comes out ``None``
    when the work is too small to dominate the box, in which case the wall
    time is the number to read.
    """

    def __init__(self, rails: PowerRails | None = None) -> None:
        self._rails = rails if rails is not None else get_model().data.rails

    @property
    def rails(self) -> PowerRails:
        """The measured rails this meter reads."""
        return self._rails

    def joules(self, *, gpu_minutes: float, wall_minutes: float) -> float | None:
        """The energy the whole box drew while the attempt ran."""
        seconds = max(0.0, wall_minutes) * 60.0
        return self._rails.vin_w * seconds / 1000.0

    def joules_above_idle(self, *, gpu_minutes: float, wall_minutes: float) -> float | None:
        """The energy above the box's idle floor, or ``None`` if it is negative."""
        seconds = max(0.0, wall_minutes) * 60.0
        marginal = self._rails.marginal_vin_w * seconds / 1000.0
        return marginal if marginal > 0 else None


# -- the loop's arithmetic -------------------------------------------------


def best_of(attempts: Sequence[Attempt]) -> Attempt | None:
    """The best attempt of a round: the highest score, the earliest on a tie.

    Only attempts that were **kept** can win — a variant that failed must
    never win by scoring high.
    """
    kept = [attempt for attempt in attempts if attempt.outcome == "kept"]
    if not kept:
        return None
    return max(kept, key=lambda attempt: (attempt.score, -attempt.round))


def gain_of(round_best: float, previous_best: float | None) -> float:
    """The quality gained in a round over the best the loop had before.

    The first round's gain is measured against nothing (zero), so it is the
    quality the first sweep found; later rounds are measured against the
    winner they have to beat.
    """
    return round_best - (previous_best if previous_best is not None else 0.0)


class RoundSummary(BaseModel):
    """One round of a loop: what it scored, what it gained, what it cost."""

    round: int
    variants: int = 0
    best_score: float = 0.0
    gain: float = 0.0
    gpu_minutes: float = 0.0
    wall_minutes: float = 0.0
    hosted_cents: int = 0
    joules: float | None = None


def summarise_rounds(attempts: Sequence[Attempt]) -> list[RoundSummary]:
    """The rounds of one task's loop, with the quality gained in each.

    This is the data the depth policy is tuned from: how much a round bought,
    what it cost, and — once the power meter reads — how many joules it
    took. The gain of each round is measured against the best the loop had
    before that round, which is the same number the loop stops on.
    """
    by_round: dict[int, list[Attempt]] = {}
    for attempt in attempts:
        by_round.setdefault(attempt.round, []).append(attempt)

    summaries: list[RoundSummary] = []
    previous_best: float | None = None
    for round_no in sorted(by_round):
        round_attempts = by_round[round_no]
        best = best_of(round_attempts)
        best_score = best.score if best is not None else 0.0
        gain = gain_of(best_score, previous_best)
        joules_values = [attempt.joules for attempt in round_attempts]
        joules = (
            sum(value for value in joules_values if value is not None)
            if all(value is not None for value in joules_values)
            else None
        )
        summaries.append(
            RoundSummary(
                round=round_no,
                variants=len(round_attempts),
                best_score=best_score,
                gain=gain,
                gpu_minutes=sum(attempt.gpu_minutes for attempt in round_attempts),
                wall_minutes=sum(attempt.wall_minutes for attempt in round_attempts),
                hosted_cents=sum(attempt.hosted_cents for attempt in round_attempts),
                joules=joules,
            )
        )
        if best is not None and (previous_best is None or best.score > previous_best):
            previous_best = best.score
    return summaries
