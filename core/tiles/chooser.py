"""The contextual bandit — the first rung of the chooser ladder (§4 of the design).

A decision model on the Thor picks a tile given the context. This is the
simplest one that can be **measured**: for each (context bucket, tile) pair
it keeps a reward estimate, and it chooses the tile with the best estimate,
exploring sometimes so that it can learn at all.

Why a bandit first, and not a learner: the point of this seat is a system
that gets better, and the first thing to prove is that it gets better at
all. A bandit's win rate is a number with a denominator, it fits in
milliseconds, and it is the **floor** every later rung has to beat. A small
learned ranker and an RL policy sit behind the same door
(:class:`TileChooser`), so swapping them in changes no caller.

Three things it does on purpose:

* **eligibility before scoring.** A tile whose preconditions do not hold in
  this context is not an option; it is not scored, not played, and not
  counted against anything.
* **it explores.** A builder that never explores never learns. The
  exploration rate decays with the number of plays, so the first night's
  plays buy the second night's win rate.
* **it is deterministic given a seed.** The same seed and the same sequence
  of calls give the same choices, so a night is replayable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .models import PlayRecord, Tile, TileRefusal

__all__ = ["Choice", "TileChooser", "ContextualBandit", "DEFAULT_EPSILON"]


#: The exploration rate at the start. It decays with the plays, so the
#: chooser spends most of a long night exploiting what it learned.
DEFAULT_EPSILON = 0.25


@dataclass(frozen=True)
class Choice:
    """What the chooser decided, and why.

    ``reason`` is on the record because a win rate that cannot say how the
    tile was picked is a win rate nobody can improve on.
    """

    tile_id: str
    reason: str
    bucket: str
    score: float


@runtime_checkable
class TileChooser(Protocol):
    """The chooser door (§4). Every rung of the ladder implements it."""

    name: str
    version: str

    def choose(self, context: Mapping[str, Any], tiles: Sequence[Tile]) -> Choice:
        """Pick a tile for this context."""
        ...

    def update(self, record: PlayRecord) -> None:
        """Learn from a play that happened."""
        ...


@dataclass
class _Arm:
    """One (context bucket, tile) estimate."""

    plays: int = 0
    reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.reward / self.plays if self.plays else 0.0


class ContextualBandit:
    """ε-greedy over (context bucket, tile) reward estimates.

    The estimate is a posterior mean with a small prior, so an unplayed
    tile is neither trusted nor written off: it starts at the prior mean
    and has to earn its way up.
    """

    name = "bandit/ctx-v1"
    version = "1"

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = (),
        epsilon: float = DEFAULT_EPSILON,
        epsilon_decay: float = 0.995,
        min_epsilon: float = 0.02,
        prior: float = 1.0,
        seed: int = 0,
    ) -> None:
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon is a rate in [0, 1]")
        if not 0.0 < epsilon_decay <= 1.0:
            raise ValueError("epsilon_decay is a rate in (0, 1]")
        if prior <= 0.0:
            raise ValueError("the prior is a count of pseudo-observations")
        self.feature_keys = tuple(feature_keys)
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.min_epsilon = min_epsilon
        self.prior = prior
        self._rng = random.Random(seed)
        self._arms: dict[tuple[str, str], _Arm] = {}
        self._global: dict[str, _Arm] = {}
        self._plays = 0

    # -- the buckets -----------------------------------------------------------

    def bucket(self, context: Mapping[str, Any]) -> str:
        """The context bucket: the features the chooser branches on.

        With no feature keys there is one bucket, and the chooser is an
        ordinary bandit. With them, the bucket is what the context says on
        those keys — and a key the context does not have is its own bucket,
        not the bucket of an empty value.
        """
        if not self.feature_keys:
            return ""
        parts = []
        for key in self.feature_keys:
            if key not in context:
                parts.append(f"{key}=<none>")
            else:
                parts.append(f"{key}={context[key]}")
        return "|".join(parts)

    # -- the choice ------------------------------------------------------------

    def choose(self, context: Mapping[str, Any], tiles: Sequence[Tile]) -> Choice:
        """Pick a tile for this context.

        Refuses when nothing is eligible: a context with no option is a
        refusal with a named reason, never a fallback to some other tile.
        """
        eligible = [
            tile
            for tile in tiles
            if tile.status == "active" and tile.is_eligible(context)
        ]
        if not eligible:
            raise TileRefusal(
                "no_eligible_tile",
                "no tile's preconditions hold in this context",
            )

        bucket = self.bucket(context)
        if len(eligible) == 1:
            only = eligible[0]
            return Choice(
                tile_id=only.id,
                reason="only_option",
                bucket=bucket,
                score=self.estimate(bucket, only.id),
            )

        if self._rng.random() < self.current_epsilon():
            explored = self._rng.choice(eligible)
            return Choice(
                tile_id=explored.id,
                reason="explore",
                bucket=bucket,
                score=self.estimate(bucket, explored.id),
            )

        best = min(eligible, key=lambda tile: self._rank(bucket, tile.id))
        cold = not any(self._arms.get((bucket, tile.id)) for tile in eligible)
        return Choice(
            tile_id=best.id,
            reason="cold" if cold else "greedy",
            bucket=bucket,
            score=self.estimate(bucket, best.id),
        )

    def current_epsilon(self) -> float:
        """The exploration rate right now — decayed by the plays so far."""
        return max(self.min_epsilon, self.epsilon * (self.epsilon_decay**self._plays))

    # -- the learning ----------------------------------------------------------

    def update(self, record: PlayRecord) -> None:
        """Learn from one play."""
        bucket = self.bucket(record.context)
        arm = self._arms.setdefault((bucket, record.tile_id), _Arm())
        arm.plays += 1
        arm.reward += record.reward

        overall = self._global.setdefault(record.tile_id, _Arm())
        overall.plays += 1
        overall.reward += record.reward

        self._plays += 1

    def fit(self, records: Sequence[PlayRecord]) -> None:
        """Refit from the play records — the whole point of the nightly loop.

        The statistics are a fold over the log, so this is the same
        computation the night does, and it can be run again at any time
        with the same answer.
        """
        self._arms.clear()
        self._global.clear()
        self._plays = 0
        for record in records:
            self.update(record)

    # -- the reads -------------------------------------------------------------

    def estimate(self, bucket: str, tile_id: str) -> float:
        """The posterior mean reward of a tile in a bucket."""
        arm = self._arms.get((bucket, tile_id))
        reward = arm.reward if arm else 0.0
        plays = arm.plays if arm else 0
        return (reward + self.prior * 0.5) / (plays + self.prior)

    def plays(self) -> int:
        """How many plays the chooser has seen."""
        return self._plays

    def stats(self) -> dict[str, Any]:
        """What the chooser knows — for the morning's report."""
        return {
            "name": self.name,
            "version": self.version,
            "plays": self._plays,
            "epsilon": self.current_epsilon(),
            "buckets": {
                bucket: {
                    tile_id: {
                        "plays": arm.plays,
                        "reward": arm.reward,
                        "mean": arm.mean,
                        "estimate": self.estimate(bucket, tile_id),
                    }
                    for (b, tile_id), arm in self._arms.items()
                    if b == bucket
                }
                for bucket in sorted({b for b, _ in self._arms})
            },
            "overall": {
                tile_id: {"plays": arm.plays, "reward": arm.reward, "mean": arm.mean}
                for tile_id, arm in sorted(self._global.items())
            },
        }

    # -- internals -------------------------------------------------------------

    def _rank(self, bucket: str, tile_id: str) -> tuple[float, float, str]:
        """The ordering key: the bucket estimate, then the overall one, then the id.

        Lower is better, and the id is the last key so that a tie is broken
        the same way every time — a chooser that breaks ties differently on
        two runs cannot be debugged.
        """
        overall = self._global.get(tile_id)
        return (
            -self.estimate(bucket, tile_id),
            -(overall.mean if overall else 0.0),
            tile_id,
        )
