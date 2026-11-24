#!/usr/bin/env python3
"""The smoke student: behaviour cloning, and the floor it is measured against.

Three things are pinned here: the student learns a mapping it is shown (so
a null result in the world would be about the data, not about the
optimiser), the held-out split is by **episode** (a student's next frame
is not a held-out question), and the random policy draws only from the
options that apply.

Run on the Thor, from the repo root:

    .venv/bin/python gym/tests/test_gym_student.py

Needs no world and no server. Takes under a second.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))

from agent_world_gym.student import (  # noqa: E402
    BCStudent,
    RandomPolicy,
    _split_by_episode,
    features_of,
    train_student,
)

FAILS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILS
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def test_the_student_learns() -> None:
    print("the student learns what it is shown")
    # Two actions, and the action is the sign of the first fact.
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 1.0, size=(400, 3)).astype(np.float32)
    y = (x[:, 0] > 0).astype(np.int64)
    student = BCStudent(3, 2, seed=0, iterations=300)
    report = student.fit(x, y)
    check("the training loss falls", report["loss"] < 0.1, str(report["loss"]))
    check("the training accuracy is high", report["accuracy"] > 0.95, str(report["accuracy"]))
    predicted = student.logits(x).argmax(axis=-1)
    check("the student agrees with the teacher", float(np.mean(predicted == y)) > 0.95)


def test_the_split_is_by_episode() -> None:
    print("the split is by episode")
    episode_ids = np.array([0] * 10 + [1] * 10 + [2] * 10)
    train, held = _split_by_episode(30, episode_ids=episode_ids, holdout=0.34, seed=3)
    held_episodes = set(episode_ids[held].tolist())
    train_episodes = set(episode_ids[train].tolist())
    check("the held-out side is whole episodes", not (held_episodes & train_episodes),
          str(held_episodes & train_episodes))
    check("something was held out", held.size > 0, str(held.size))
    check("something was trained on", train.size > 0, str(train.size))


def test_the_report_says_how_it_split() -> None:
    print("the report")
    x = np.zeros((20, 2), dtype=np.float32)
    y = np.zeros((20,), dtype=np.int64)
    episode_ids = np.array([0] * 10 + [1] * 10)
    student, report = train_student(x, y, n_actions=3, episode_ids=episode_ids, seed=1)
    check("the report says the split was by episode", report.get("split") == "by episode",
          str(report.get("split")))
    check("the report counts the frames", report["train_frames"] + report["heldout_frames"] == 20,
          str(report))


def test_the_random_policy_stays_legal() -> None:
    print("the random policy")
    policy = RandomPolicy(seed=5)
    observation = {"facts": np.zeros(12, dtype=np.float32)}
    for _ in range(50):
        choice = policy.choose(observation, [2, 5])
        check_ok = choice in (2, 5)
        if not check_ok:
            check("the random policy stays inside the eligible set", False, str(choice))
            return
    check("the random policy stays inside the eligible set", True)


def test_the_features_are_the_facts() -> None:
    print("the features")
    observation = {"facts": np.arange(12, dtype=np.float32)}
    features = features_of(observation)
    check("the features are the facts, flat", features.shape == (12,), str(features.shape))
    check("the features keep the values", float(features[3]) == 3.0, str(features[3]))


if __name__ == "__main__":
    test_the_student_learns()
    test_the_split_is_by_episode()
    test_the_report_says_how_it_split()
    test_the_random_policy_stays_legal()
    test_the_features_are_the_facts()
    print(f"\n{'all checks passed' if FAILS == 0 else f'{FAILS} check(s) FAILED'}")
    sys.exit(1 if FAILS else 0)
