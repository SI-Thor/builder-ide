#!/usr/bin/env python3
"""The recorder: both sources, one writer, every frame kept.

Crafter round 2 (2026-11-02) settled which frames a student should learn
from — **all** of them. These checks pin that rule at the writer: the
dataset holds every play of every episode, the community's dataset holds
the community's **own** actions (not the ones the replay was handed), and
a partial stays a partial (no reward invented for it).

Run on the Thor, from the repo root:

    .venv/bin/python gym/tests/test_gym_recorder.py

Needs no world: the env is the fake bridge, the ledger is built in a
temporary file. Takes a few seconds (Minari writes HDF5).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILS
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def test_the_community_dataset() -> None:
    print("the community dataset")
    import minari

    from agent_world_gym.actions import action_list
    from agent_world_gym.recorder import GymRecorder
    from test_gym_ledger import build_ledger, play

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["MINARI_DATASETS_PATH"] = str(root / "datasets")
        ledger = root / "ledger.sqlite3"
        rows = []
        for index in range(6):
            rows.append(
                play(
                    "Pebble",
                    "skill_aaa" if index % 2 == 0 else "skill_bbb",
                    f"2026-11-02T10:00:{index:02d}Z",
                    "win" if index % 3 else "partial",
                    1 if index % 3 else None,
                )
            )
        build_ledger(ledger, rows)

        recorder = GymRecorder(datasets_path=root / "datasets")
        dataset = recorder.record_community_episodes(
            "gym-test/community-v0",
            ledger_path=ledger,
            action_ids=action_list(["skill_aaa", "skill_bbb"]),
            gap_seconds=600,
        )
        check("the dataset was created", dataset is not None)
        check("one episode per run", dataset.total_episodes == 1, str(dataset.total_episodes))
        check("every frame is kept", dataset.total_steps == 6, str(dataset.total_steps))

        episodes = list(dataset.iterate_episodes())
        actions = [int(a) for a in episodes[0].actions]
        check(
            "the community's own actions are the ones recorded",
            actions == [0, 1, 0, 1, 0, 1],
            str(actions),
        )
        rewards = [float(r) for r in episodes[0].rewards]
        check("a win is one", rewards[1] == 1.0, str(rewards[1]))
        check("a partial is zero, not half", rewards[0] == 0.0, str(rewards[0]))
        facts = episodes[0].observations["facts"]
        # Minari keeps the state before the first action as well, so a
        # six-step episode carries seven states and six actions.
        check("the facts are in the frame", facts.shape[0] == 7, str(facts.shape))
        check("the facts are the world's own", float(facts[0][0]) == 1.0, str(facts[0][0]))
        check("the actions line up with the states", len(episodes[0].actions) == 6,
              str(len(episodes[0].actions)))

        # The dataset must be readable again by id.
        again = minari.load_dataset("gym-test/community-v0")
        check("the dataset loads again", again.total_steps == 6, str(again.total_steps))


def test_the_env_dataset() -> None:
    print("the private world's dataset")
    from agent_world_gym.env import AgentWorldEnv
    from agent_world_gym.policies import ScriptedPolicy
    from agent_world_gym.recorder import GymRecorder
    from test_gym_env import FakeBridge, build_library

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["MINARI_DATASETS_PATH"] = str(root / "datasets")
        library = root / "skills"
        build_library(library)

        env = AgentWorldEnv(bridge=FakeBridge(), role="gatherer", skill_root=library, max_steps=4)
        recorder = GymRecorder(datasets_path=root / "datasets")
        policy = ScriptedPolicy("cycle", env=env)
        dataset = recorder.record_env_episodes(
            env,
            "gym-test/private-v0",
            policy,
            episodes=3,
            seed=1,
        )
        check("three episodes were recorded", dataset.total_episodes == 3, str(dataset.total_episodes))
        check("every frame was kept", dataset.total_steps == 12, str(dataset.total_steps))
        episodes = list(dataset.iterate_episodes())
        actions = {int(a) for a in episodes[0].actions}
        check("the scripted policy's actions are the ones recorded", actions == {0}, str(actions))
        check("the observation space is the world's", "facts" in dataset.observation_space.spaces,
              str(dataset.observation_space))


if __name__ == "__main__":
    test_the_community_dataset()
    test_the_env_dataset()
    print(f"\n{'all checks passed' if FAILS == 0 else f'{FAILS} check(s) FAILED'}")
    sys.exit(1 if FAILS else 0)
