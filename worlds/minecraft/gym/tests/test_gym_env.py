#!/usr/bin/env python3
"""The environment: the world's contract, without a world.

The env talks to a **bridge** — an HTTP door to the mineflayer bot — and
everything above that door is pure arithmetic, so the whole contract can
be tested against a fake bridge: the reward rule, the refusal of an option
that does not apply, the eligible set, and the achievements-equivalent
counters.

Run on the Thor, from the repo root:

    .venv/bin/python gym/tests/test_gym_env.py

Needs no world and no server: the fake bridge answers in-process. Takes
under a second.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))

from agent_world_gym.env import AgentWorldEnv  # noqa: E402
from agent_world_gym.library_helper import write_skill  # noqa: E402

FAILS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILS
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


FACTS = {
    "bot": "Pupil",
    "role": "gatherer",
    "phase": "day",
    "time_of_day": 0.5,
    "health": 20,
    "food": 20,
    "has_material": False,
    "humans": 0,
    "human_present": False,
    "confidence": None,
}


class FakeBridge:
    """A bridge that answers from a script instead of from a world."""

    def __init__(self, outcomes: dict[str, dict] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.steps = 0
        self.resets = 0
        self.inventory = {}
        self.mined = 0
        self.placed = 0

    def reset(self) -> dict:
        self.resets += 1
        self.inventory = {}
        self.mined = 0
        self.placed = 0
        return self.observation()

    def observation(self, grid: int = 0) -> dict:
        payload = {
            "ok": True,
            "facts": dict(FACTS),
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory": [{"name": k, "count": v} for k, v in self.inventory.items()],
        }
        if grid:
            payload["block_grid"] = ["air"] * ((2 * grid + 1) ** 2 * 3)
        return payload

    def step(self, skill_id: str) -> dict:
        self.steps += 1
        outcome = dict(
            self.outcomes.get(
                skill_id, {"result": "lose", "measure": "sealed_prediction", "score": 0, "detail": ""}
            )
        )
        kind = outcome.pop("_kind", "")
        if kind == "inventory":
            self.inventory["oak_log"] = self.inventory.get("oak_log", 0) + 2
        if kind == "placed":
            self.placed += 1
        return {
            "ok": True,
            "skill_id": skill_id,
            "outcome": outcome,
            "wall_seconds": 0.01,
            "inventory_before": {},
            "inventory_after": dict(self.inventory),
            "gained": 2 if kind == "inventory" else 0,
            "mined": 0,
            "placed": self.placed,
            "dead": False,
            "facts": dict(FACTS),
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory": [{"name": k, "count": v} for k, v in self.inventory.items()],
        }


def build_library(root: Path) -> None:
    """Two skills: one that gathers, one that builds."""
    write_skill(
        root,
        skill_id="skill_aaaa00000001",
        family="gatherer.wood",
        role="gatherer",
        title="chop the nearest oak log",
        body="return {done: true, detail: 'chopped'};",
        predict={"kind": "inventory_delta", "item": "oak_log", "min": 1},
    )
    write_skill(
        root,
        skill_id="skill_bbbb00000002",
        family="builder.wall",
        role="builder",
        title="lay a line of cobblestone",
        body="return {done: true, detail: 'laid'};",
        predict={"kind": "block_placed", "min": 1},
    )


def test_the_spaces() -> None:
    print("the spaces")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        env = AgentWorldEnv(bridge=FakeBridge(), role="gatherer", skill_root=root)
        check("the action space is discrete over the options",
              env.action_space.n == 2, str(env.action_space.n))
        check("the facts are in the observation", "facts" in env.observation_space.spaces)
        check("the grid is off by default", "block_grid" not in env.observation_space.spaces)
        env_grid = AgentWorldEnv(bridge=FakeBridge(), role="gatherer", skill_root=root, block_grid=2)
        check("the grid can be asked for", "block_grid" in env_grid.observation_space.spaces)
        check("the grid has the shape it says", env_grid.observation_space["block_grid"].shape == (3, 5, 5),
              str(env_grid.observation_space["block_grid"].shape))


def test_reset_and_step() -> None:
    print("reset and step")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        bridge = FakeBridge()
        env = AgentWorldEnv(bridge=bridge, role="gatherer", skill_root=root, max_steps=3)
        observation, info = env.reset()
        check("reset gives the facts", observation["facts"].shape == (12,), str(observation["facts"].shape))
        check("reset says which options apply", info["eligible_actions"] == [0], str(info["eligible_actions"]))
        check("the world was not regenerated", info["world_reset"] is False)
        observation, reward, terminated, truncated, info = env.step(0)
        check("a losing play is worth nothing", reward == 0.0, str(reward))
        check("a loss is a measurement", info["measurable"] is True)
        check("the episode is not over yet", terminated is False and truncated is False)
        observation, reward, terminated, truncated, info = env.step(0)
        observation, reward, terminated, truncated, info = env.step(0)
        check("the episode ends at the step limit", truncated is True, str(truncated))
        check("the bridge was asked three times", bridge.steps == 3, str(bridge.steps))


def test_the_reward_rule() -> None:
    print("the reward rule")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        bridge = FakeBridge(
            {
                "skill_aaaa00000001": {
                    "result": "win",
                    "measure": "sealed_prediction",
                    "score": 1,
                    "detail": "oak_log +2 (wanted 1)",
                    "_kind": "inventory",
                },
                "skill_bbbb00000002": {
                    "result": "partial",
                    "measure": "sealed_prediction",
                    "score": None,
                    "detail": "the skill ran; it made no measurable change",
                },
            }
        )
        env = AgentWorldEnv(bridge=bridge, role="gatherer", skill_root=root)
        env.reset()
        observation, reward, terminated, truncated, info = env.step(0)
        check("a win is worth one", reward == 1.0, str(reward))
        check("a win counts as a gather", info["gathers"] == 1, str(info["gathers"]))
        check("the gather is the world's own measure", info["gather"] is True)
        check("the bag really gained", info["gained"] == 2, str(info["gained"]))
        check("the predict kind is carried", info["predict_kind"] == "inventory_delta")


def test_a_partial_carries_no_reward() -> None:
    print("a partial")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        bridge = FakeBridge(
            {
                "skill_aaaa00000001": {
                    "result": "partial",
                    "measure": "sealed_prediction",
                    "score": None,
                    "detail": "the skill ran; nothing could be measured",
                }
            }
        )
        env = AgentWorldEnv(bridge=bridge, role="gatherer", skill_root=root)
        env.reset()
        observation, reward, terminated, truncated, info = env.step(0)
        check("a partial is worth zero, not half", reward == 0.0, str(reward))
        check("a partial says it carried no measurement", info["measurable"] is False)
        check("a partial is not a gather", info["gathers"] == 0)


def test_an_option_that_does_not_apply_is_refused() -> None:
    print("an option that does not apply")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        bridge = FakeBridge()
        env = AgentWorldEnv(bridge=bridge, role="gatherer", skill_root=root)
        env.reset()
        # index 1 is the builder's wall: the gatherer may not play it.
        observation, reward, terminated, truncated, info = env.step(1)
        check("the refusal is worth nothing", reward == 0.0, str(reward))
        check("the refusal is named", "does not apply" in str(info["refused"]), str(info.get("refused")))
        check("the world was never asked", bridge.steps == 0, str(bridge.steps))
        check("the refusal still counts as a step", info["steps"] == 1)


def test_the_eligible_set_is_the_worlds_own() -> None:
    print("the eligible set")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        env = AgentWorldEnv(bridge=FakeBridge(), role="gatherer", skill_root=root)
        env.reset()
        check("the gatherer's options are the gatherer's", env.eligible_actions() == [0],
              str(env.eligible_actions()))
        builder = AgentWorldEnv(bridge=FakeBridge(), role="builder", skill_root=root)
        builder.reset()
        check("the builder's options are the builder's", builder.eligible_actions() == [1],
              str(builder.eligible_actions()))


def test_the_achievements_equivalent() -> None:
    print("the achievements-equivalent")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_library(root)
        bridge = FakeBridge(
            {
                "skill_aaaa00000001": {
                    "result": "win",
                    "measure": "sealed_prediction",
                    "score": 1,
                    "detail": "",
                    "_kind": "inventory",
                }
            }
        )
        env = AgentWorldEnv(bridge=bridge, role="gatherer", skill_root=root, max_steps=3)
        env.reset()
        for _ in range(3):
            observation, reward, terminated, truncated, info = env.step(0)
        check("three gathers are three gathers", info["gathers"] == 3, str(info["gathers"]))
        check("no projects were built", info["projects"] == 0, str(info["projects"]))


if __name__ == "__main__":
    test_the_spaces()
    test_reset_and_step()
    test_the_reward_rule()
    test_a_partial_carries_no_reward()
    test_an_option_that_does_not_apply_is_refused()
    test_the_eligible_set_is_the_worlds_own()
    test_the_achievements_equivalent()
    print(f"\n{'all checks passed' if FAILS == 0 else f'{FAILS} check(s) FAILED'}")
    sys.exit(1 if FAILS else 0)
