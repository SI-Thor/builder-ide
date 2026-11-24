"""The scripted policies: the teacher in the private world.

Two deterministic policies, so a recorded episode can be reproduced from
its seed:

* **priority** — the world's own order of need, per role: the gatherer
  gathers wood, then stone, then fuel; the builder builds stone, then the
  wall, then the pillar, then the depot; and so on. The first eligible
  option in that order is the one taken.
* **cycle** — the eligible options in order, one per tick, wrapping around.
  It visits every option the context allows, which is what a recorded
  demonstration wants to show a student.

Both refuse to choose an option that does not apply: the eligible set comes
from the world's own rule, and a policy that plays an ineligible option
would be recording the env's refusals instead of the world's behaviour.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

__all__ = ["DEFAULT_PRIORITY", "ScriptedPolicy", "make_policy"]

#: The world's order of need, per role. The families are the world's own
#: family names — the same names the library uses.
DEFAULT_PRIORITY: dict[str, tuple[str, ...]] = {
    "gatherer": ("gatherer.wood", "gatherer.stone", "gatherer.fuel"),
    "builder": ("builder.stone", "builder.wall", "builder.pillar", "builder.depot"),
    "scout": ("scout.ground", "scout.sight"),
    "farmer": ("farmer.ground", "farmer.seed", "farmer.plant", "farmer.wheat"),
}


class ScriptedPolicy:
    """A deterministic policy over the world's eligible options."""

    def __init__(
        self,
        name: str = "priority",
        *,
        env: Any | None = None,
        priority: dict[str, Sequence[str]] | None = None,
    ) -> None:
        self.name = name
        self.env = env
        self.priority = dict(priority or DEFAULT_PRIORITY)
        self._counter = 0

    # -- the choice -------------------------------------------------------------

    def choose(self, observation: dict[str, np.ndarray], eligible: Sequence[int]) -> int:
        if not eligible:
            raise RuntimeError("no option applies here: the world's rule says refuse")
        options = sorted(int(x) for x in eligible)
        if self.name == "cycle":
            choice = options[self._counter % len(options)]
            self._counter += 1
            return choice
        if self.name == "priority":
            order = self.priority.get(self.role, ())
            best: tuple[int, int] | None = None
            for index in options:
                family = self.family_of(index)
                rank = order.index(family) if family in order else len(order)
                key = (rank, index)
                if best is None or key < best:
                    best = key
            return int(best[1]) if best is not None else options[0]
        raise ValueError(f"there is no scripted policy called {self.name!r}")

    def __call__(
        self, observation: dict[str, np.ndarray], info: dict[str, Any]
    ) -> int:
        eligible = info.get("eligible_actions") or []
        return self.choose(observation, eligible)

    # -- the world's own names --------------------------------------------------

    @property
    def role(self) -> str:
        return getattr(self.env, "role", "")

    def family_of(self, index: int) -> str:
        if self.env is None:
            return ""
        return self.env.family_of(self.env.skill_id_for(index))


def make_policy(
    name: str = "priority",
    *,
    env: Any | None = None,
    priority: dict[str, Sequence[str]] | None = None,
) -> Callable[[dict[str, np.ndarray], dict[str, Any]], int]:
    """The scripted policy, as the callable the recorder wants."""
    return ScriptedPolicy(name, env=env, priority=priority)
