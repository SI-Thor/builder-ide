"""The environment: one bot, one private world, the reflex's contract.

``AgentWorldEnv`` is a Gymnasium environment over the live agent-world. It
drives **one** mineflayer bot on a **private** Paper server (port 25630,
127.0.0.1, offline mode, a world of its own — never the live server and
never the live world), and it speaks the contract the d1 reflex already
speaks:

* **observation** — the reflex's state facts (``bots/src/agent.js``
  ``context()``), encoded by :mod:`agent_world_gym.facts`, plus an
  **optional** local block grid (off by default: the community's ledger
  holds no grids, so a grid-capable student could not be cloned from it);
* **action** — the reflex's option set, discrete: the skills the library
  holds, one index each, with the ineligible ones masked out of
  ``info["eligible_actions"]`` rather than refused by exception.

The reward is the world's own measure: the sealed prediction either held
(1.0) or did not (0.0). A **partial** — the skill ran and nothing could be
measured — carries no reward at all (``PlayRecord.reward`` in
``agent_world_reflex.models`` says so, and the 2026-11-01 playtest showed
what happens when a partial is scored as half a win). Gymnasium needs a
number, so a partial arrives as 0.0 with ``info["measurable"] = False``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .actions import action_list, is_project_id
from .bridge import GymBridge
from .facts import BLOCK_VOCAB, FACT_NAMES, encode_block_grid, encode_facts

__all__ = ["AgentWorldEnv", "GRID_HEIGHT", "REPO"]

#: Where the repo is, so ``reflex`` can be put on the import path.
REPO = Path(__file__).resolve().parents[2]

#: How many blocks above and below the agent the optional grid covers.
GRID_HEIGHT = 3


def _reflex_on_path() -> None:
    """The world's own library and models, on the import path.

    The gym reads the option set with the **world's** loader and the
    **world's** eligibility rule, so there is one rule for what an option
    is and not two.
    """
    path = str(REPO / "reflex")
    if path not in sys.path:
        sys.path.insert(0, path)


_reflex_on_path()

from agent_world_reflex.library import SkillLibrary  # noqa: E402


class AgentWorldEnv(gym.Env):
    """The world's own game, as a Gymnasium environment."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        bridge: GymBridge | None = None,
        role: str = "gatherer",
        skill_library: SkillLibrary | None = None,
        skill_root: Path | str | None = None,
        action_ids: Iterable[str] | None = None,
        max_steps: int = 12,
        block_grid: int = 0,
    ) -> None:
        super().__init__()
        self.bridge = bridge or GymBridge()
        self.role = role
        self.max_steps = int(max_steps)
        self.block_grid = int(block_grid)

        if skill_library is None:
            root = Path(skill_root) if skill_root else REPO / "runtime" / "skills"
            skill_library = SkillLibrary(root)
        self.library = skill_library

        if action_ids is None:
            action_ids = action_list(skill.id for skill in self.library.active())
        self.action_ids: list[str] = list(action_ids)
        self._index_of = {skill_id: index for index, skill_id in enumerate(self.action_ids)}

        self.action_space = spaces.Discrete(len(self.action_ids))
        # The grid is optional, and when it is off the observation has no
        # grid key at all: an empty array is not a neutral grid, it is a
        # zero-sized array, and a zero-sized array is a nuisance to write
        # into a dataset. The key set is the same on both sides of the
        # recorder, so the two sources stay interchangeable.
        spaces_dict = {
            "facts": spaces.Box(
                low=-1.0,
                high=1.0,
                shape=(len(FACT_NAMES),),
                dtype=np.float32,
            ),
        }
        if self.block_grid > 0:
            spaces_dict["block_grid"] = spaces.Box(
                low=0,
                high=len(BLOCK_VOCAB) - 1,
                shape=self.grid_shape,
                dtype=np.int32,
            )
        self.observation_space = spaces.Dict(spaces_dict)

        self._steps = 0
        self._facts: dict[str, Any] = {}
        self._counters = {"gathers": 0, "projects": 0, "gained": 0, "placed": 0, "mined": 0}

    # -- the spaces -------------------------------------------------------------

    @property
    def grid_shape(self) -> tuple[int, int, int]:
        """The shape of the optional grid: (height, width, width).

        Zero width means the grid is off, and the observation carries an
        empty array rather than a missing key — a Gymnasium ``Dict`` space
        keeps the same keys whatever the episode does.
        """
        if self.block_grid <= 0:
            return (0, 0, 0)
        width = 2 * self.block_grid + 1
        return (GRID_HEIGHT, width, width)

    # -- the option set ---------------------------------------------------------

    def eligible_actions(self, facts: Mapping[str, Any] | None = None) -> list[int]:
        """The indices of the options that apply in this context.

        The world's own rule: a skill whose preconditions do not hold here
        is not an option. A context with no eligible option is a refusal
        with a named reason, never a fallback to some other skill.
        """
        context = self._facts if facts is None else facts
        eligible = self.library.eligible(context, role=self.role)
        out = []
        for skill in eligible:
            index = self._index_of.get(skill.id)
            if index is not None:
                out.append(index)
        return sorted(out)

    def skill_id_for(self, action: int) -> str:
        return self.action_ids[int(action)]

    def family_of(self, skill_id: str) -> str:
        """The family of a skill — its job — or ``""`` if it is not one."""
        skill = self.library.get(skill_id)
        return skill.family if skill is not None else ""

    def predict_kind_of(self, skill_id: str) -> str:
        """What the skill predicted would change, or ``""`` if unknown."""
        skill = self.library.get(skill_id)
        return skill.predict.kind if skill is not None else ""

    # -- the episode ------------------------------------------------------------

    def _observation(self, payload: Mapping[str, Any]) -> dict[str, np.ndarray]:
        facts = dict(payload.get("facts") or {})
        self._facts = facts
        observation = {"facts": encode_facts(facts)}
        if self.block_grid > 0:
            grid = payload.get("block_grid")
            observation["block_grid"] = (
                encode_block_grid(grid, self.grid_shape)
                if grid is not None
                else np.zeros(self.grid_shape, dtype=np.int32)
            )
        return observation

    def _info(self, **extra: Any) -> dict[str, Any]:
        info: dict[str, Any] = {
            "eligible_actions": self.eligible_actions(),
            "gathers": self._counters["gathers"],
            "projects": self._counters["projects"],
            "steps": self._steps,
        }
        info.update(extra)
        return info

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        """Start an episode.

        The world's terrain is **not** regenerated: an episode boundary
        clears the agent's bag and its counters and puts it back on its
        mark. A world reset costs minutes of chunk generation, and the
        tasks here are gather-and-build loops rather than a survival run,
        so the honest boundary is the agent's, and it is said out loud in
        ``info["world_reset"] = False``.
        """
        super().reset(seed=seed)
        payload = self.bridge.reset()
        self._steps = 0
        self._counters = {"gathers": 0, "projects": 0, "gained": 0, "placed": 0, "mined": 0}
        observation = self._observation(payload)
        info = self._info(
            world_reset=False,
            episode_start=True,
            position=payload.get("position"),
            inventory=payload.get("inventory") or [],
        )
        return observation, info

    def step(
        self, action: int
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        """Run one option and measure what it did."""
        index = int(action)
        if index < 0 or index >= len(self.action_ids):
            raise ValueError(f"the action {action} is not one of this world's options")
        skill_id = self.action_ids[index]

        if is_project_id(skill_id):
            # A project step needs the community's board; the private
            # world has none. The refusal is recorded, not hidden.
            return self._refuse(skill_id, "the private world runs no project board")
        if self.library.get(skill_id) is None:
            # The action list may carry options the world has retired (the
            # community's ledger holds those). The refusal says which.
            return self._refuse(skill_id, "the option is not in this world's library")
        eligible = self.eligible_actions()
        if index not in eligible:
            return self._refuse(skill_id, "the option does not apply in this context")

        answer = self.bridge.step(skill_id)
        outcome = dict(answer.get("outcome") or {})
        result = str(outcome.get("result", "partial"))
        score = outcome.get("score")
        measurable = result in ("win", "lose")
        reward = 1.0 if result == "win" else 0.0

        observation = self._observation(answer)
        self._steps += 1

        kind = self.predict_kind_of(skill_id)
        gained = int(answer.get("gained", 0) or 0)
        placed = int(answer.get("placed", 0) or 0)
        mined = int(answer.get("mined", 0) or 0)
        self._counters["gained"] += gained
        self._counters["placed"] += placed
        self._counters["mined"] += mined

        # The achievements-equivalent: a **gather** is a play where the
        # world measured the agent taking material (into its bag, or out
        # of the ground); a **project** is a play where the world measured
        # the agent building something. The world checks the sealed
        # prediction against the world, so a win *is* a measured change —
        # the same fact the community's own ledger records, in the same
        # words: the gatherer's skills predict ``block_broken`` (chop,
        # mine) and ``inventory_delta`` (seeds, wheat, the depot), the
        # builder's and the farmer's predict ``block_placed``.
        gather = kind in ("inventory_delta", "block_broken") and result == "win"
        project = kind == "block_placed" and result == "win"
        if gather:
            self._counters["gathers"] += 1
        if project:
            self._counters["projects"] += 1

        truncated = self._steps >= self.max_steps
        terminated = bool(answer.get("dead", False))
        info = self._info(
            skill_id=skill_id,
            family=self.family_of(skill_id),
            outcome=outcome,
            measurable=measurable,
            score=score,
            gather=gather,
            project=project,
            predict_kind=kind,
            gained=gained,
            placed=placed,
            mined=mined,
            wall_seconds=float(answer.get("wall_seconds", 0.0) or 0.0),
            position=answer.get("position"),
            refused=None,
        )
        return observation, reward, terminated, truncated, info

    def _refuse(
        self, skill_id: str, why: str
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        """An option that cannot run here: no reward, no change, said out loud."""
        self._steps += 1
        observation: dict[str, np.ndarray] = {"facts": encode_facts(self._facts)}
        if self.block_grid > 0:
            observation["block_grid"] = np.zeros(self.grid_shape, dtype=np.int32)
        truncated = self._steps >= self.max_steps
        info = self._info(
            skill_id=skill_id,
            outcome={"result": "refused", "measure": "", "score": None, "detail": why},
            measurable=False,
            score=None,
            refused=why,
        )
        return observation, 0.0, False, truncated, info
