"""The chooser: which skill the world does next.

Two things know how to pick, and they are combined here:

* **The decision model (d1-2B).** A small local model, served once on the
  Thor and shared by every bot, answers "which of these options" over the
  world's shared state. It is the *reflex*: it runs in tens of
  milliseconds and it is the only thing that runs on every tick. The
  judge is builder-ide's seam for it (``core/judge``), which is where
  the confidence gate, the escalation ladder and the attempt log live.
* **The learned estimate.** A contextual bandit over (context bucket,
  skill), refit from the play records. This is what the world *knows*
  from having played.

How they are combined is the same rule the tiles seat uses
(``docs/design/tiles.md`` §4, and ``core/judge/shortlist.py``): **the
judge is the cold-start prior.** Where the bandit has no observation of
a skill in this bucket, the judge's probability stands where a flat
prior stood; as real plays arrive, the learned estimate washes the prior
out at the rate the bandit's prior count sets. The weight is

    w = prior / (plays + prior)

so ``w = 1`` for a skill nobody has played and ``w -> 0`` as the record
grows. Nothing is thrown away: the judge's answer is on every play
record's context, and the estimate it produced is in the log.
"""

from __future__ import annotations

import random
from typing import Any, Mapping, Sequence

from .ledger import ledger_paths

ledger_paths()

from core.tiles.chooser import ContextualBandit  # noqa: E402

from .models import PlayRecord, Skill  # noqa: E402

__all__ = ["Chooser", "Choice"]


class Choice:
    """What the chooser decided, and why.

    ``propensity`` is the probability this chooser, in this state, at this
    moment, picked this skill. It is measured **here**, at the choice,
    because it cannot be reconstructed afterwards: the exploration rate
    decays and the greedy arm moves as the chooser learns.
    """

    __slots__ = ("skill_id", "reason", "bucket", "score", "propensity", "candidates", "confidence")

    def __init__(
        self,
        *,
        skill_id: str,
        reason: str,
        bucket: str,
        score: float,
        propensity: float | None,
        candidates: Sequence[str],
        confidence: float | None = None,
    ) -> None:
        self.skill_id = skill_id
        self.reason = reason
        self.bucket = bucket
        self.score = score
        self.propensity = propensity
        self.candidates = tuple(candidates)
        self.confidence = confidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "reason": self.reason,
            "bucket": self.bucket,
            "score": self.score,
            "propensity": self.propensity,
            "candidates": list(self.candidates),
            "confidence": self.confidence,
        }


class _ArmRecord:
    """The bandit's view of a play.

    The bandit in ``core/tiles`` was written for tiles, so its play
    record carries ``tile_id``. A skill here is a tile under another
    name, so the chooser hands the bandit the same record with the field
    it expects. Nothing is copied twice and nothing is renamed in the
    log: the record on disk says ``skill_id``.
    """

    __slots__ = ("tile_id", "context", "reward")

    def __init__(self, record: PlayRecord) -> None:
        self.tile_id = record.skill_id
        self.context = record.context
        self.reward = record.reward


class Chooser:
    """The decision model over the library.

    The bandit arms come from builder-ide's ``core/tiles/chooser.py`` —
    the same ε-greedy, the same posterior mean, the same propensity
    arithmetic. What is added here is the judge's prior, which is what
    makes the world work before it has any record of its own.
    """

    name = "bandit/ctx-v1+judge"
    version = "1"

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = ("role", "phase"),
        epsilon: float = 0.15,
        epsilon_decay: float = 0.995,
        min_epsilon: float = 0.02,
        prior: float = 1.0,
        seed: int = 0,
    ) -> None:
        self.bandit = ContextualBandit(
            feature_keys=feature_keys,
            epsilon=epsilon,
            epsilon_decay=epsilon_decay,
            min_epsilon=min_epsilon,
            prior=prior,
            seed=seed,
        )
        self.prior = prior
        self._rng = random.Random(seed)

    # -- the bucket ------------------------------------------------------------

    def bucket(self, context: Mapping[str, Any]) -> str:
        return self.bandit.bucket(context)

    # -- the choice ------------------------------------------------------------

    def choose(
        self,
        context: Mapping[str, Any],
        skills: Sequence[Skill],
        *,
        judge: Mapping[str, float] | None = None,
        judge_confidence: float | None = None,
    ) -> Choice:
        """Pick a skill for this context.

        ``judge`` is the decision model's distribution over the eligible
        set, keyed by skill id. It is the cold-start prior: where the
        bandit has no observation of a skill, the judge's probability
        stands where a flat 0.5 stood.
        """
        eligible = [s for s in skills if s.status == "active" and s.is_eligible(dict(context))]
        if not eligible:
            raise Refusal("no_eligible_skill", "no skill's preconditions hold in this context")

        bucket = self.bucket(context)
        eligible_ids = tuple(s.id for s in eligible)
        if len(eligible) == 1:
            only = eligible[0]
            return Choice(
                skill_id=only.id,
                reason="only_option",
                bucket=bucket,
                score=self.bandit.estimate(bucket, only.id),
                propensity=1.0,
                candidates=eligible_ids,
                confidence=judge_confidence,
            )

        scores = {s.id: self._score(bucket, s, judge or {}) for s in eligible}
        total = sum(scores.values()) or 1.0

        epsilon = self.bandit.current_epsilon()
        if self._rng.random() < epsilon:
            explored = self._rng.choice(eligible)
            return Choice(
                skill_id=explored.id,
                reason="explore",
                bucket=bucket,
                score=scores[explored.id],
                propensity=epsilon / len(eligible),
                candidates=eligible_ids,
                confidence=judge_confidence,
            )

        best = max(sorted(eligible, key=lambda s: s.id), key=lambda s: scores[s.id])
        cold = not any(
            self.bandit.estimate(bucket, s.id) != 0.5 for s in eligible
        )
        # The greedy skill is picked outright with probability 1 - eps and
        # is also in the exploration pool with probability eps/|eligible|.
        # Both ways count.
        propensity = (1.0 - epsilon) * (scores[best.id] / total) + epsilon / len(eligible)
        return Choice(
            skill_id=best.id,
            reason="cold" if cold else "greedy",
            bucket=bucket,
            score=scores[best.id],
            propensity=propensity,
            candidates=eligible_ids,
            confidence=judge_confidence,
        )

    def _score(
        self,
        bucket: str,
        skill: Skill,
        judge: Mapping[str, float],
    ) -> float:
        """The judge's prior, washed out by the record."""
        learned = self.bandit.estimate(bucket, skill.id)
        plays = self._plays(bucket, skill.id)
        w = self.prior / (plays + self.prior)
        prior_value = float(judge.get(skill.id, 0.5))
        return (1.0 - w) * learned + w * prior_value

    def _plays(self, bucket: str, skill_id: str) -> int:
        stats = self.bandit.stats()
        bucket_stats = stats.get("buckets", {}).get(bucket, {})
        return int(bucket_stats.get(skill_id, {}).get("plays", 0))

    # -- the learning ----------------------------------------------------------

    def update(self, record: PlayRecord) -> None:
        """Learn from one play.

        A play with **no reward** — a partial: the skill ran and nothing
        could be measured — teaches nothing about the win rate, so it
        changes nothing here. The estimate reflects only the plays that
        could be scored; a skill whose every play is partial stays at
        the judge's prior and the choice says ``cold``, which is the
        honest reading: there is no evidence either way.
        """
        if record.reward is None:
            return
        self.bandit.update(_ArmRecord(record))

    def fit(self, records: Sequence[PlayRecord]) -> None:
        """Refit from the play records — the same computation the night does.

        The same rule as ``update``: a partial play carries no reward and
        is left out, so a refit from the log lands where the live updates
        would have.
        """
        self.bandit.fit([_ArmRecord(r) for r in records if r.reward is not None])

    def stats(self) -> dict[str, Any]:
        stats = dict(self.bandit.stats())
        stats["name"] = self.name
        stats["version"] = self.version
        return stats


class Refusal(Exception):
    """A refusal with a closed reason code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
