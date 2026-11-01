"""The first caller: the tiles shortlist, with the judge as the cold-start prior.

`docs/research/liquid-study.md` Part 3, item 1, last line: *"Wire the
first caller: the tiles shortlist. The judge answers ``choice`` over
the chooser's K candidates for a context. Keep the bandit; the judge is
the cold-start prior. Record the propensity for OPE."*

**How the judge is a prior, not a replacement.** The contextual bandit
estimates every (bucket, tile) reward as

    (reward + prior_count * prior_mean) / (plays + prior_count)

with a flat ``prior_mean`` of 0.5 — the tile nobody knows is trusted
neither way. When the bucket is cold, the chooser asks the judge once:
a ``choice`` question over the K eligible candidates, whose answer is a
probability per tile. Those probabilities become the bucket's prior
means, so a cold bandit's argmax **is** the judge's answer, and its
estimates move to the bandit's own at exactly the rate real plays
accumulate. The chooser stays replayable, ε-greedy, and propensity-
measuring — nothing in the bandit's learning changes.

**The gate is the policy's, not this module's.** A judge answer below τ
with nowhere to escalate is *surfaced, not acted on*: no prior is set,
the bandit keeps its flat prior, and the surfaced count goes up. The
judgment row (author, distribution, cost, latency) is already in the
ledger — the Judge records it — so the play needs no copy of it.

**The propensity is the bandit's own**, unchanged in its formula, so
the log stays off-policy evaluable by :mod:`core.tiles.ope` exactly as
the tiles seat's rule 8 requires.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from core.tiles.chooser import Choice, ContextualBandit
from core.tiles.models import Tile

from .judge import Judge
from .models import Question

__all__ = ["JudgePriorChooser"]

#: The default state renderer: the context, in one plain line. A caller
#: that wants the judge to see the scene as the game sees it passes its
#: own renderer.
DEFAULT_STATE_RENDERER: Callable[[Mapping[str, Any], Sequence[Tile]], str] = (
    lambda context, tiles: "Scene context: "
    + ", ".join(f"{key}={context[key]}" for key in sorted(context))
    + "."
)


def _candidate_text(tile: Tile) -> str:
    """What the judge sees for one candidate: the title, and what it is for."""
    text = tile.title or tile.id
    if tile.family:
        text += f" ({tile.family})"
    return text


class JudgePriorChooser(ContextualBandit):
    """The contextual bandit, seeded by one judged choice per cold bucket.

    A subclass on purpose: the door (:class:`core.tiles.chooser.TileChooser`),
    the exploration, the propensity arithmetic and the nightly refit are
    the bandit's own. The judge changes what the bandit believes before
    its first play in a bucket — nothing else.
    """

    name = "judge-prior/ctx-v1"
    version = "1"

    def __init__(
        self,
        judge: Judge,
        *,
        task: str = "tiles.shortlist",
        state_renderer: Callable[[Mapping[str, Any], Sequence[Tile]], str] | None = None,
        question_id: str = "tile",
        **bandit_kwargs,
    ) -> None:
        super().__init__(**bandit_kwargs)
        self.judge = judge
        self.task = task
        self.state_renderer = state_renderer or DEFAULT_STATE_RENDERER
        self.question_id = question_id
        #: bucket → the judged prior over tiles, or ``None`` where the
        #: judgment was surfaced and no prior may be set.
        self.priors: dict[str, dict[str, float] | None] = {}
        self.judge_calls = 0
        self.judge_surfaced = 0

    # -- the choice ------------------------------------------------------------

    def choose(self, context: Mapping[str, Any], tiles: Sequence[Tile]) -> Choice:
        """Pick a tile: the bandit's choice, on a prior the judge set."""
        bucket = self.bucket(context)
        if bucket not in self.priors:
            self._judge_prior(context, tiles, bucket)
        return super().choose(context, tiles)

    # -- the estimate, with the judged prior -------------------------------------

    def estimate(self, bucket: str, tile_id: str) -> float:
        """The posterior mean reward, on the judged prior mean where one exists.

        The bandit's own formula, with the judge's probability standing
        where the flat 0.5 stood. Real plays enter at the same rate as
        before, so the prior washes out at the pace ``prior`` sets.
        """
        arm = self._arms.get((bucket, tile_id))
        reward = arm.reward if arm else 0.0
        plays = arm.plays if arm else 0
        prior_mean = (self.priors.get(bucket) or {}).get(tile_id, 0.5)
        return (reward + self.prior * prior_mean) / (plays + self.prior)

    # -- the judgment ------------------------------------------------------------

    def _judge_prior(
        self, context: Mapping[str, Any], tiles: Sequence[Tile], bucket: str
    ) -> None:
        """Ask the judge once for this bucket, or stand down to the flat prior."""
        eligible = [
            tile for tile in tiles if tile.status == "active" and tile.is_eligible(context)
        ]
        if len(eligible) < 2:
            # one option is not a judgment: the only option is the only option
            self.priors[bucket] = None
            return
        question = Question(
            qid=self.question_id,
            kind="choice",
            instructions="Which tile should be played next?",
            criteria={tile.id: _candidate_text(tile) for tile in eligible},
        )
        self.judge_calls += 1
        answer = self.judge.judge(
            self.task,
            self.state_renderer(context, eligible),
            (question,),
            # the bucket names the decision, and the calibration fold joins
            # the judgment to the play that answers it by that name
            scope=bucket,
        )
        judgment = answer.judgment(self.question_id)
        if judgment.gate == "act":
            self.priors[bucket] = {
                tile_id: judgment.distribution.get(tile_id, 0.0)
                for tile_id in judgment.distribution
            }
        else:
            # surfaced, not acted on: the bandit keeps its own flat prior
            self.judge_surfaced += 1
            self.priors[bucket] = None
