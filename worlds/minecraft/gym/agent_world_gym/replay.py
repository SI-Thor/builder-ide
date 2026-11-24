"""The community's plays, replayed as an environment.

The live world's ledger is a log, not an environment. This is the
environment around it: a read-only Gymnasium env that hands back, frame by
frame, what the community actually did — the state facts the reflex saw,
the option it chose, and the outcome the world measured.

The replay is how the community's demonstrations become something a student
can be trained on **without the community changing anything**: the frames
come out of the log, and nothing goes back in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .actions import index_of
from .facts import FACT_NAMES, encode_facts
from .ledger import LedgerEpisode, WorldLedgerReader

__all__ = ["LedgerReplayEnv"]


class LedgerReplayEnv(gym.Env):
    """Read-only: the community's recorded plays, as an environment."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        ledger_path: Path | str,
        action_ids: list[str],
        episodes: list[LedgerEpisode] | None = None,
        gap_seconds: float = 600.0,
        limit: int | None = None,
    ) -> None:
        super().__init__()
        self.reader = WorldLedgerReader(ledger_path)
        self.action_ids = list(action_ids)
        self.episodes = (
            list(episodes)
            if episodes is not None
            else self.reader.episodes(gap_seconds=gap_seconds, limit=limit)
        )
        self.action_space = spaces.Discrete(len(self.action_ids))
        self.observation_space = spaces.Dict(
            {
                "facts": spaces.Box(
                    low=-1.0,
                    high=1.0,
                    shape=(len(FACT_NAMES),),
                    dtype=np.float32,
                ),
                # The ledger holds no block grids: a grid-capable student
                # cannot be cloned from the community, so the community's
                # frames carry no grid key at all. The key set matches the
                # private world's env with the grid off, so the two
                # datasets are interchangeable.
            }
        )
        self._episode_index = -1
        self._play_index = 0
        self._current: LedgerEpisode | None = None

    # -- the episode ------------------------------------------------------------

    def _facts_observation(self, facts: dict[str, Any]) -> dict[str, np.ndarray]:
        return {"facts": encode_facts(facts)}

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)
        self._episode_index += 1
        if self._episode_index >= len(self.episodes):
            raise RuntimeError("the replay has no more episodes")
        self._current = self.episodes[self._episode_index]
        self._play_index = 0
        first = self._current.plays[0]
        observation = self._facts_observation(first.facts)
        info = {
            "teacher_action": index_of(self.action_ids, first.skill_id),
            "episode_index": self._episode_index,
            "bot": first.bot,
            "skill_id": first.skill_id,
        }
        return observation, info

    def step(
        self, action: int
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        if self._current is None:
            raise RuntimeError("reset() before step()")
        plays = self._current.plays
        if self._play_index >= len(plays):
            raise RuntimeError("the episode is over")

        play = plays[self._play_index]
        score = play.score
        reward = 1.0 if play.result == "win" else 0.0
        measurable = score is not None
        terminated = self._play_index + 1 >= len(plays)
        self._play_index += 1

        if terminated:
            observation = self._facts_observation(play.facts)
            teacher_action = index_of(self.action_ids, play.skill_id)
        else:
            following = plays[self._play_index]
            observation = self._facts_observation(following.facts)
            teacher_action = index_of(self.action_ids, play.skill_id)

        info = {
            "teacher_action": teacher_action,
            "skill_id": play.skill_id,
            "bot": play.bot,
            "outcome": play.outcome,
            "measurable": measurable,
            "score": score,
            "at": play.at,
        }
        return observation, reward, terminated, False, info
