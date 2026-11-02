"""The Crafter adapter — the second world, and the fast one.

Crafter is the 2D Minecraft-like world the auto-play stack adopted as
"the fast lab": thousands of episodes an hour on the Thor's CPUs. It is
here for two reasons.

First, it is the **honest second measurement**. The Minecraft world is
slow, its actions take real time, and a small model driving a real bot
through a real tech tree is a hard thing to measure. Crafter is the
same loop with the latency and the graphics removed, so the loop's own
numbers (skills admitted, tokens per milestone) can be separated from
the world's difficulty.

Second, its milestones are the environment's own: ``info['achievements']``
is Crafter's list of twenty-two achievements, and they are the ground
truth here exactly as the inventory is in Minecraft.

The env is crafter-lab's (``~/lm-wt/crafter-lab``), the same one the
teacher–student experiments use, so the numbers can be compared with
``docs/lab/exp-crafter-lab.md``.
"""

from __future__ import annotations

import builtins
from typing import Any, Mapping, Sequence

from ..models import Milestone
from ..ports import CheckResult, EnvironmentPort, ExecResult, ProgressSnapshot
from ..vocab import BODY_SCHEMA, BODY_WORD, SkillVocabulary

__all__ = ["CrafterAdapter", "CRAFTER_MILESTONES", "crafter_vocabulary"]

#: Crafter's seventeen actions.
CRAFTER_ACTIONS: tuple[str, ...] = (
    "noop", "move_left", "move_right", "move_up", "move_down", "do", "sleep",
    "place_stone", "place_table", "place_furnace", "place_plant",
    "make_wood_pickaxe", "make_stone_pickaxe", "make_iron_pickaxe",
    "make_wood_sword", "make_stone_sword", "make_iron_sword",
)

#: The milestones this adapter's curriculum uses: a path through
#: Crafter's own achievements, in the order a player would take them.
CRAFTER_MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        key="collect_wood",
        title="collect wood",
        description="Chop a tree and pick up the wood.",
        items=("collect_wood",),
    ),
    Milestone(
        key="make_wood_pickaxe",
        title="make a wood pickaxe",
        description="Craft the wood pickaxe.",
        needs=("collect_wood",),
        items=("make_wood_pickaxe",),
    ),
    Milestone(
        key="collect_stone",
        title="collect stone",
        description="Mine stone with the pickaxe.",
        needs=("make_wood_pickaxe",),
        items=("collect_stone",),
    ),
    Milestone(
        key="make_stone_pickaxe",
        title="make a stone pickaxe",
        description="Craft the stone pickaxe.",
        needs=("collect_stone",),
        items=("make_stone_pickaxe",),
    ),
    Milestone(
        key="collect_coal",
        title="collect coal",
        description="Mine coal, deeper than the surface.",
        needs=("make_stone_pickaxe",),
        items=("collect_coal",),
    ),
    Milestone(
        key="make_iron_pickaxe",
        title="make an iron pickaxe",
        description="Smelt iron and craft the iron pickaxe.",
        needs=("collect_coal", "place_furnace"),
        items=("make_iron_pickaxe",),
    ),
    Milestone(
        key="collect_iron",
        title="collect iron",
        description="Mine iron ore.",
        needs=("make_stone_pickaxe",),
        items=("collect_iron",),
    ),
    Milestone(
        key="collect_diamond",
        title="collect a diamond",
        description="Mine a diamond, deep down.",
        needs=("make_iron_pickaxe",),
        items=("collect_diamond",),
    ),
)


def crafter_vocabulary() -> SkillVocabulary:
    """The closed primitive set of the Crafter world.

    A Crafter skill is a **sequence of actions**, so the primitives are
    the seventeen actions plus the two ways to run them (once, or many
    times). Nothing else is reachable from a skill.
    """
    actions = list(CRAFTER_ACTIONS)
    words: dict[str, Mapping[str, Any]] = {
        "mc.act": {
            "action": {
                "type": "string",
                "enum": actions,
                "hint": "one of crafter's seventeen actions",
            },
            "times": {"type": "integer", "minimum": 1, "maximum": 512},
        },
        "mc.act_seq": {
            "actions": {
                "type": "array",
                "maxItems": 512,
                "hint": "a list of crafter action names",
            },
        },
        "mc.move": {
            "direction": {
                "type": "string",
                "enum": ["left", "right", "up", "down"],
                "hint": "which way to walk",
            },
            "steps": {"type": "integer", "minimum": 1, "maximum": 512},
        },
        "mc.achievements": {},
        "mc.reward": {},
        BODY_WORD: BODY_SCHEMA,
    }
    return SkillVocabulary(words)


class CrafterAdapter:
    """Crafter, as an environment."""

    name = "crafter"
    language = "python"

    def __init__(
        self,
        *,
        seed: int = 0,
        length: int = 1000,
        area: tuple[int, int] = (64, 64),
        view: tuple[int, int] = (9, 9),
        log=None,
    ) -> None:
        self.seed = seed
        self.length = length
        self.area = area
        self.view = view
        self._log = log or (lambda message: None)
        self._registry = crafter_vocabulary()
        self._env = None
        self._achievements: dict[str, int] = {}
        self._seen: set[str] = set()
        self._milestones = {m.key: m for m in CRAFTER_MILESTONES}

    # -- the world -------------------------------------------------------------

    def open(self) -> None:
        if self._env is not None:
            return
        import crafter

        self._env = crafter.Env(
            area=self.area,
            view=self.view,
            size=self.area,
            length=self.length,
            seed=self.seed,
            reward=True,
        )
        self._env.reset()
        self._log("the crafter world is open")

    def close(self) -> None:
        self._env = None

    def _require_env(self):
        if self._env is None:
            raise RuntimeError("the crafter world is not open")
        return self._env

    # -- the environment -------------------------------------------------------

    def observe(self) -> dict[str, Any]:
        """The facts, in the player's terms."""
        env = self._require_env()
        player = env._player
        inventory = {
            str(name): int(count)
            for name, count in (getattr(player, "inventory", {}) or {}).items()
            if int(count) > 0
        }
        return {
            "world": "crafter",
            "position": {
                "x": int(player.pos[0]) if getattr(player, "pos", None) else 0,
                "y": int(player.pos[1]) if getattr(player, "pos", None) else 0,
            },
            "health": int(getattr(player, "health", 0)),
            "energy": int(getattr(player, "energy", 0)),
            "food": int(getattr(player, "food", 0)),
            "inventory": inventory,
            "achievements": dict(self._achievements),
            "achievements_reached": sorted(
                name for name, count in self._achievements.items() if count > 0
            ),
            "unique_materials": sorted(self._seen),
        }

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        """Run a skill: a program that calls the action primitives."""
        env = self._require_env()
        captured: list[str] = []
        started = __import__("time").time()

        def act(action: str, times: int = 1) -> int:
            name = str(action)
            if name not in CRAFTER_ACTIONS:
                raise ValueError(f"{name!r} is not one of crafter's actions")
            count = max(1, min(512, int(times)))
            for _ in range(count):
                obs, reward, done, info = env.step(CRAFTER_ACTIONS.index(name))
                self._absorb(info)
                if done:
                    break
            return count

        def act_seq(actions: Sequence[str]) -> int:
            for name in actions:
                act(name, 1)
            return len(list(actions))

        def move(direction: str, steps: int = 1) -> int:
            name = {
                "left": "move_left",
                "right": "move_right",
                "up": "move_up",
                "down": "move_down",
            }.get(str(direction))
            if name is None:
                raise ValueError(f"{direction!r} is not a direction")
            return act(name, steps)

        primitives = {
            "act": act,
            "act_seq": act_seq,
            "move": move,
            "achievements": lambda: dict(self._achievements),
            "reward": lambda: float(getattr(env, "_reward", 0.0)),
        }
        safe_builtins = {
            name: getattr(builtins, name)
            for name in (
                "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
                "int", "len", "list", "max", "min", "print", "range", "reversed",
                "round", "set", "sorted", "str", "sum", "tuple", "zip", "Exception",
                "ValueError", "KeyError", "IndexError", "True", "False", "None",
            )
            if hasattr(builtins, name)
        }
        safe_builtins["print"] = lambda *args: captured.append(" ".join(str(a) for a in args))
        namespace = {"__builtins__": safe_builtins, "mc": primitives}
        try:
            exec(compile(code, "<skill>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            return ExecResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}"[:600],
                log=tuple(captured),
                seconds=__import__("time").time() - started,
            )
        return ExecResult(
            ok=True,
            error="",
            log=tuple(captured),
            seconds=__import__("time").time() - started,
        )

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        """Run a self-verification snippet; it must end with a boolean."""
        namespace: dict[str, Any] = {"mc": {"achievements": lambda: dict(self._achievements)}}
        try:
            exec(compile(code, "<verify>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            return CheckResult(passed=False, detail=f"{type(exc).__name__}: {exc}"[:300])
        value = namespace.get("result")
        if value is None:
            value = namespace.get("__result__")
        return CheckResult(passed=bool(value), detail=str(value))

    def goal_truth(self, key: str) -> bool:
        """Crafter's own answer: is this achievement unlocked?"""
        milestone = self._milestones.get(key)
        if milestone is None:
            return False
        return all(self._achievements.get(name, 0) > 0 for name in milestone.items)

    def progress(self) -> ProgressSnapshot:
        """The counts the report quotes."""
        return ProgressSnapshot(
            unique_items=len(self._seen),
            items={name: count for name, count in sorted(self._achievements.items())},
            milestones={key: self.goal_truth(key) for key in self._milestones},
        )

    def primitives(self) -> tuple[str, ...]:
        return self._registry.words()

    def primitive_schemas(self) -> Mapping[str, Any]:
        return self._registry.schema_map()

    def milestones(self) -> tuple[Milestone, ...]:
        return CRAFTER_MILESTONES

    # -- internals -------------------------------------------------------------

    def _absorb(self, info: Mapping[str, Any]) -> None:
        achievements = info.get("achievements") or {}
        for name, count in achievements.items():
            self._achievements[str(name)] = int(count)
            if int(count) > 0:
                self._seen.add(str(name))
