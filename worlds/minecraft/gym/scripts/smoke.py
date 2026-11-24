#!/usr/bin/env python3
"""The smoke experiment: does watching the community beat guessing?

The desk's question, in the world's own units. The pipeline:

1. the private world (a Paper server of its own on 127.0.0.1:25630) is
   played under a **scripted** policy, and every frame is recorded into a
   Minari dataset;
2. the **live community's** plays are read out of the world's ledger —
   read-only — and recorded into a second Minari dataset;
3. a behaviour-cloning student is trained on each dataset, and on the
   combination;
4. every student, and a random policy, is **rolled out in the private
   world** over a few seeds, and scored in the world's own
   achievements-equivalent: **projects and gathers per episode**.

Run on the Thor, from the repo root:

    XLA_PYTHON_CLIENT_PREALLOCATE=false .venv/bin/python gym/scripts/smoke.py

Needs: the private world and the bridge up (``gym/ops/gym-world.sh start``,
``gym/ops/gym-bot.sh start``), the live world's ledger at
``~/lm-wt/agent-world/runtime/world-ledger.sqlite3``, and the ``.venv``.
Takes about an hour: the world's own skills walk real ground, so a step
costs 20-40 seconds, and a rollout is a rollout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gym"))

# Minari pulls jax; the Thor's GPU memory is system memory, so the
# preallocation guard goes on before anything is imported.
os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")

import numpy as np  # noqa: E402

from agent_world_gym.actions import action_list  # noqa: E402
from agent_world_gym.bridge import GymBridge  # noqa: E402
from agent_world_gym.env import AgentWorldEnv  # noqa: E402
from agent_world_gym.ledger import WorldLedgerReader  # noqa: E402
from agent_world_gym.policies import ScriptedPolicy  # noqa: E402
from agent_world_gym.recorder import GymRecorder  # noqa: E402
from agent_world_gym.student import (  # noqa: E402
    RandomPolicy,
    dataset_frames,
    evaluate_in_env,
    train_student,
)

sys.path.insert(0, str(REPO / "reflex"))
from agent_world_reflex.library import SkillLibrary  # noqa: E402

DEFAULT_LEDGER = Path.home() / "lm-wt" / "agent-world" / "runtime" / "world-ledger.sqlite3"
DEFAULT_SKILLS = REPO / "runtime" / "skills"
DEFAULT_DATASETS = REPO / "runtime" / "datasets"
DEFAULT_REPORTS = REPO / "runtime" / "reports"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def box_state() -> dict[str, object]:
    """The box's state beside the numbers (DOC-RULES 3)."""
    state: dict[str, object] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                state["mem_available_gb"] = int(line.split()[1]) // (1024 * 1024)
    except OSError:
        pass
    try:
        state["load"] = os.getloadavg()
    except OSError:
        pass
    return state


def community_baseline(episodes, library) -> dict[str, object]:
    """The community's own rate, in the same units the students are scored in.

    A gather is a play where the world measured the agent taking
    material (into its bag, or out of the ground); a project is a play
    where the world measured the agent building something. The community's
    own ledger says which is which, through the skill's sealed
    prediction.
    """
    rows = []
    for episode in episodes:
        gathers = 0
        projects = 0
        wins = 0
        for play in episode.plays:
            if play.result != "win":
                continue
            wins += 1
            skill = library.get(play.skill_id)
            kind = skill.predict.kind if skill is not None else ""
            if kind in ("inventory_delta", "block_broken"):
                gathers += 1
            elif kind == "block_placed":
                projects += 1
        rows.append(
            {
                "bot": episode.bot,
                "plays": len(episode.plays),
                "wins": wins,
                "gathers": gathers,
                "projects": projects,
            }
        )
    return {
        "episodes": len(rows),
        "gathers_per_episode": float(np.mean([r["gathers"] for r in rows])) if rows else 0.0,
        "projects_per_episode": float(np.mean([r["projects"] for r in rows])) if rows else 0.0,
        "wins_per_episode": float(np.mean([r["wins"] for r in rows])) if rows else 0.0,
        "plays_per_episode": float(np.mean([r["plays"] for r in rows])) if rows else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--skills", type=Path, default=DEFAULT_SKILLS)
    parser.add_argument("--datasets", type=Path, default=DEFAULT_DATASETS)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--role", default="gatherer")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--env-episodes", type=int, default=3)
    parser.add_argument("--eval-episodes", type=int, default=2)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--gap-seconds", type=float, default=600.0)
    parser.add_argument("--tag", default="smoke")
    args = parser.parse_args()

    args.reports.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "role": args.role,
        "max_steps": args.max_steps,
        "seeds": args.seeds,
        "eval_episodes": args.eval_episodes,
        "box_at_start": box_state(),
    }

    # -- the option set ---------------------------------------------------------
    reader = WorldLedgerReader(args.ledger)
    log("reading the live world's ledger (read-only)")
    plays = reader.plays()
    episodes = reader.episodes(gap_seconds=args.gap_seconds, plays=plays)
    ledger_skill_ids = sorted({play.skill_id for play in plays if play.skill_id})
    log(f"the ledger holds {len(plays)} plays in {len(episodes)} episodes")

    env_library = SkillLibrary(args.skills)
    library_ids = [skill.id for skill in env_library.active()]
    # One action space for both sources: the library's live options and
    # every option the community chose, so a student cloned from the
    # community can be played in the private world with no translation.
    shared = action_list(library_ids + ledger_skill_ids)
    env = AgentWorldEnv(
        bridge=GymBridge(),
        role=args.role,
        skill_library=env_library,
        action_ids=shared,
        max_steps=args.max_steps,
    )
    report["action_space"] = len(shared)
    report["library_active"] = len(library_ids)
    report["ledger_options"] = len(ledger_skill_ids)
    report["community_baseline"] = community_baseline(episodes, env_library)
    log(f"the action space: {len(shared)} options ({len(library_ids)} of them live in the library)")
    log(
        "the community's own rate: "
        f"{report['community_baseline']['gathers_per_episode']:.2f} gathers and "
        f"{report['community_baseline']['projects_per_episode']:.2f} projects per episode"
    )

    # -- the two datasets -------------------------------------------------------
    recorder = GymRecorder(datasets_path=args.datasets)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    log(f"recording the private world's episodes ({args.env_episodes} episodes, scripted)")
    env_dataset = recorder.record_env_episodes(
        env,
        f"gym/{args.role}-private-{stamp}-v0",
        ScriptedPolicy("cycle", env=env),
        episodes=args.env_episodes,
        seed=100,
        description="the private agent-world (127.0.0.1:25630) under the cycle scripted policy",
    )
    report["env_dataset"] = {
        "id": env_dataset.id,
        "episodes": env_dataset.total_episodes,
        "steps": env_dataset.total_steps,
    }
    log(f"the private world's dataset: {env_dataset.total_episodes} episodes, {env_dataset.total_steps} frames")

    log("recording the live community's plays (read-only from the ledger)")
    community_dataset = recorder.record_community_episodes(
        f"gym/{args.role}-community-{stamp}-v0",
        ledger_path=args.ledger,
        action_ids=shared,
        episodes=len(episodes),
        gap_seconds=args.gap_seconds,
        description="the live agent-world community's plays, read-only from the world ledger",
    )
    report["community_dataset"] = {
        "id": community_dataset.id,
        "episodes": community_dataset.total_episodes,
        "steps": community_dataset.total_steps,
    }
    log(f"the community's dataset: {community_dataset.total_episodes} episodes, {community_dataset.total_steps} frames")

    # -- the students -----------------------------------------------------------
    community_features, community_actions, community_episode_ids = dataset_frames(community_dataset)
    env_features, env_actions, env_episode_ids = dataset_frames(env_dataset)
    log(f"the community's frames: {community_features.shape}, the private world's: {env_features.shape}")

    students: dict[str, object] = {}
    arms: dict[str, dict[str, object]] = {}

    def add_arm(name: str, student: object, train_report: dict) -> None:
        students[name] = student
        arms[name] = {"train": train_report}

    for name, (features, actions, episode_ids) in {
        "bc-community": (community_features, community_actions, community_episode_ids),
        "bc-private": (env_features, env_actions, env_episode_ids),
    }.items():
        log(f"training the {name} student")
        student, train_report = train_student(
            features,
            actions,
            n_actions=len(shared),
            episode_ids=episode_ids,
            seed=0,
        )
        add_arm(name, student, train_report)
        log(f"  {name}: {train_report}")

    # -- the rollouts -----------------------------------------------------------
    def rollout(name: str, policy: object) -> dict[str, object]:
        rows = []
        for seed in range(args.seeds):
            log(f"  {name}: episode set {seed + 1}/{args.seeds}")
            summary = evaluate_in_env(
                policy,
                env,
                episodes=args.eval_episodes,
                seed=1000 + seed,
                greedy=True,
            )
            summary["seed"] = seed
            rows.append(summary)
            log(
                f"    seed {seed}: gathers/episode {summary['gathers_per_episode']:.2f}, "
                f"projects/episode {summary['projects_per_episode']:.2f}, "
                f"reward/episode {summary['reward_per_episode']:.2f}, "
                f"refused/episode {summary['refused_per_episode']:.2f}"
            )
        return {
            "seeds": rows,
            "gathers_per_episode": float(np.mean([r["gathers_per_episode"] for r in rows])),
            "projects_per_episode": float(np.mean([r["projects_per_episode"] for r in rows])),
            "reward_per_episode": float(np.mean([r["reward_per_episode"] for r in rows])),
            "refused_per_episode": float(np.mean([r["refused_per_episode"] for r in rows])),
        }

    log("rolling out the students in the private world")
    results: dict[str, dict[str, object]] = {}
    for name, student in students.items():
        results[name] = rollout(name, student)
    results["random"] = rollout("random", RandomPolicy(seed=0))

    report["arms"] = arms
    report["results"] = results
    report["box_at_end"] = box_state()
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = args.reports / f"{args.tag}-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"the report is at {out}")

    print("\n=== the numbers ===")
    for name, result in results.items():
        print(
            f"  {name:14s} gathers/episode {result['gathers_per_episode']:.2f}  "
            f"projects/episode {result['projects_per_episode']:.2f}  "
            f"reward/episode {result['reward_per_episode']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
