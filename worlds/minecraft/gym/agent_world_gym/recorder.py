"""The Minari writer: both sources, one writer.

Crafter round 2 (2026-11-02, ``docs/lab/exp-crafter-r2.md``) settled
which frames a student should learn from: **all** of them, at the largest
gradient budget available. A subset is a compute-saving shortcut for a small
budget, not a way to pick better lessons — the round-2 verdict was that the
teaching-moment filter keeps 98.8 % of the decisive frames anyway and
teaches nothing beyond its own selection.

So this recorder keeps **every** frame it is handed: the private world's
scripted episodes and the live community's plays alike. It never filters.
The only thing it subsamples is nothing; if storage ever forces it to, the
subsample is random and says so.

Two sources, one writer:

* ``record_env_episodes`` — the private world, under a scripted policy;
* ``record_community_episodes`` — the live community, read-only from the
  world's ledger.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .actions import action_list
from .env import AgentWorldEnv
from .replay import LedgerReplayEnv

__all__ = ["GymRecorder", "TeacherActionCallback"]

#: Minari imports jax for its tree utilities, and jax on this box is CPU
#: only — but the rule from the 13:22 OOM still stands, so the guard is set
#: before anything else is imported.
os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")

import minari  # noqa: E402
from minari import StepDataCallback  # noqa: E402


class TeacherActionCallback(StepDataCallback):
    """Record the teacher's action, not the one the replay was handed.

    The replay env is asked to step with whatever the student would have
    chosen, but the frame that belongs in the dataset is the one the
    community actually played. The teacher's action rides in ``info`` and
    the callback puts it in the record.
    """

    def __call__(  # type: ignore[override]
        self,
        env,
        obs,
        info,
        action=None,
        rew=None,
        terminated=None,
        truncated=None,
    ):
        step_data = super().__call__(
            env=env,
            obs=obs,
            info=info,
            action=action,
            rew=rew,
            terminated=terminated,
            truncated=truncated,
        )
        teacher = info.get("teacher_action") if isinstance(info, dict) else None
        if isinstance(teacher, (int, np.integer)) and int(teacher) >= 0:
            step_data["action"] = int(teacher)
        return step_data


class GymRecorder:
    """Writes Minari datasets from the world's two sources."""

    def __init__(self, *, datasets_path: Path | str | None = None) -> None:
        if datasets_path is not None:
            path = Path(datasets_path).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            os.environ["MINARI_DATASETS_PATH"] = str(path)
        self.datasets_path = Path(
            os.environ.get("MINARI_DATASETS_PATH", str(Path.home() / ".minari" / "datasets"))
        )

    # -- the private world ------------------------------------------------------

    def record_env_episodes(
        self,
        env: AgentWorldEnv,
        dataset_id: str,
        policy: Callable[[dict[str, np.ndarray], dict[str, Any]], int],
        *,
        episodes: int = 5,
        seed: int = 0,
        description: str = "",
        author: str = "agent-world-gym",
    ):
        """Record episodes of the private world under a scripted policy.

        Every frame of every episode is kept: the observation, the action
        the policy took, the reward, the end flags.
        """
        collector = minari.DataCollector(env, jpeg_encoding=False)
        dataset = collector.create_dataset(
            dataset_id,
            author=author,
            description=description
            or "the private agent-world under a scripted policy (gym/agent_world_gym)",
            algorithm_name="scripted",
            requirements=["gymnasium>=1.4.0", "minari>=0.5.4"],
        )
        for episode in range(int(episodes)):
            observation, info = collector.reset(seed=int(seed) + episode)
            done = False
            while not done:
                action = int(policy(observation, info))
                observation, reward, terminated, truncated, info = collector.step(action)
                done = bool(terminated) or bool(truncated)
        collector.add_to_dataset(dataset)
        return dataset

    # -- the live community -----------------------------------------------------

    def record_community_episodes(
        self,
        dataset_id: str,
        *,
        ledger_path: Path | str,
        action_ids: Sequence[str] | None = None,
        episodes: int | None = None,
        gap_seconds: float = 600.0,
        limit: int | None = None,
        description: str = "",
        author: str = "agent-world-gym",
    ):
        """Record the live community's plays, read-only from the ledger.

        The world's log is read through a read-only SQLite connection; the
        gym writes nothing back to the live world, and the dataset holds
        the frames exactly as the community played them.
        """
        from .ledger import WorldLedgerReader

        reader = WorldLedgerReader(ledger_path)
        plays = reader.plays()
        reader_episodes = reader.episodes(
            gap_seconds=gap_seconds, limit=limit, plays=plays
        )
        if action_ids is None:
            skill_ids = [play.skill_id for play in plays]
            action_ids = action_list(skill_ids)
        else:
            action_ids = list(action_ids)

        env = LedgerReplayEnv(
            ledger_path=ledger_path,
            action_ids=action_ids,
            episodes=reader_episodes,
            gap_seconds=gap_seconds,
            limit=limit,
        )
        collector = minari.DataCollector(env, step_data_callback=TeacherActionCallback, jpeg_encoding=False)
        dataset = collector.create_dataset(
            dataset_id,
            author=author,
            description=description
            or "the live agent-world community's plays, read-only from the world ledger",
            algorithm_name="community",
            requirements=["gymnasium>=1.4.0", "minari>=0.5.4"],
        )
        total = len(env.episodes) if episodes is None else int(episodes)
        for episode in range(total):
            observation, info = collector.reset()
            done = False
            while not done:
                # The action the collector is handed does not matter: the
                # callback records the community's own action for the frame.
                observation, reward, terminated, truncated, info = collector.step(0)
                done = bool(terminated) or bool(truncated)
        collector.add_to_dataset(dataset)
        return dataset
