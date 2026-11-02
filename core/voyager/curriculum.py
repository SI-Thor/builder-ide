"""The curriculum — what the loop works on next, and why.

Voyager's curriculum is the first of its three parts: an automatic,
novelty-biased list of things to achieve. This module is our
re-engineering of it, and the difference is deliberate.

Voyager picks the **first unachieved** landmark in a fixed list, so the
agent walks the tech tree in order and grinds on whatever it cannot do
yet. Our version keeps the tech tree as a **dependency** (iron needs a
pickaxe) but chooses among the eligible milestones by **novelty**:

    score = weight / (1 + attempts) x recency x jitter

* ``attempts`` — how many times the milestone has been tried. A
  milestone that keeps failing loses its score, so the loop rotates to
  something else instead of hammering one wall.
* ``recency`` — the milestone tried last is halved, so two adjacent
  steps do not repeat the same wall.
* ``jitter`` — a seeded uniform draw, so the choice is reproducible:
  the same seed and the same attempt counts give the same curriculum.

The score is a *preference*, not a plan: the planner model still picks
what to do, and the loop's measure of success is the environment's own
ground truth, never the curriculum's opinion.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .models import Milestone

__all__ = ["Curriculum", "CurriculumState"]


@dataclass
class CurriculumState:
    """One milestone's standing in the curriculum."""

    attempts: int = 0
    achieved: bool = False
    last_attempt_at: str = ""
    achieved_at: str = ""
    achieved_step: int = -1

    def as_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "achieved": self.achieved,
            "last_attempt_at": self.last_attempt_at,
            "achieved_at": self.achieved_at,
            "achieved_step": self.achieved_step,
        }


class Curriculum:
    """The automatic curriculum: which milestone to work on next."""

    def __init__(
        self,
        milestones: Sequence[Milestone],
        *,
        seed: int = 0,
        clock=None,
    ) -> None:
        if not milestones:
            raise ValueError("a curriculum needs at least one milestone")
        self._milestones: dict[str, Milestone] = {m.key: m for m in milestones}
        self._order: tuple[str, ...] = tuple(m.key for m in milestones)
        self._state: dict[str, CurriculumState] = {
            m.key: CurriculumState() for m in milestones
        }
        self._rng = random.Random(seed)
        self._clock = clock
        self._last: str = ""

    # -- the reads -------------------------------------------------------------

    def milestones(self) -> tuple[Milestone, ...]:
        """Every milestone, in the order it was declared."""
        return tuple(self._milestones[k] for k in self._order)

    def state(self, key: str) -> CurriculumState:
        return self._state[key]

    def achieved(self) -> tuple[str, ...]:
        """The milestones reached so far, in declaration order."""
        return tuple(k for k in self._order if self._state[k].achieved)

    def pending(self) -> tuple[str, ...]:
        """The milestones not reached yet, in declaration order."""
        return tuple(k for k in self._order if not self._state[k].achieved)

    def eligible(self) -> tuple[Milestone, ...]:
        """The milestones whose dependencies are met.

        A milestone with an unmet dependency is not a low-priority
        milestone — it is not a milestone yet. The tech tree is a
        precondition, not a preference.
        """
        out: list[Milestone] = []
        for key in self._order:
            milestone = self._milestones[key]
            if self._state[key].achieved:
                continue
            if all(self._state[n].achieved for n in milestone.needs):
                out.append(milestone)
        return tuple(out)

    def score(self, key: str) -> float:
        """The novelty score of a milestone. Higher is more worth trying."""
        milestone = self._milestones[key]
        state = self._state[key]
        novelty = 1.0 / (1.0 + state.attempts)
        recency = 0.5 if key == self._last else 1.0
        return milestone.weight * novelty * recency

    def pick(self) -> Milestone | None:
        """The milestone to work on next, or ``None`` when all are reached.

        The choice is a seeded weighted draw over the eligible set, so
        the same seed and the same attempt counts always give the same
        curriculum — a replay gives the same answer.
        """
        options = self.eligible()
        if not options:
            return None
        weights = [max(self.score(m.key), 1e-6) for m in options]
        chosen = self._rng.choices(options, weights=weights, k=1)[0]
        # The jitter is drawn on every pick so that two picks with the
        # same weights still differ — otherwise a milestone that was
        # drawn twice would be drawn again.
        self._rng.random()
        return chosen

    # -- the writes ------------------------------------------------------------

    def record_attempt(self, key: str, *, at: str | None = None) -> CurriculumState:
        """Note that a step was aimed at this milestone."""
        state = self._state[key]
        state.attempts += 1
        state.last_attempt_at = at or self._now()
        self._last = key
        return state

    def record_achieved(
        self, key: str, *, at: str | None = None, step: int = -1
    ) -> CurriculumState:
        """Note that this milestone was reached."""
        state = self._state[key]
        state.achieved = True
        state.achieved_at = at or self._now()
        state.achieved_step = step
        return state

    def snapshot(self) -> dict[str, object]:
        """The whole standing, for the log."""
        return {
            "milestones": {
                key: self._state[key].as_dict() for key in self._order
            },
            "last": self._last,
        }

    def _now(self) -> str:
        if self._clock is not None:
            return self._clock()
        from core.canon import now_utc

        return now_utc()
