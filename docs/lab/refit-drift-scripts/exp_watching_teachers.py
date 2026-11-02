#!/usr/bin/env python3
"""the watching-teachers question: one policy, fine-tuned on all the demonstrations.

`docs/design/watching-teachers.md` keeps a lesson as data, then as a tile,
then as **weights** - "the student's policy fine-tuned on the demonstrations".
The question this answers is what that third step costs: when one policy is
fine-tuned on the demonstrations, **does the newest skill survive and do the
old ones degrade?**

The data is the real teacher: `~/lm-wt/crafter-lab`'s scripted Crafter
teacher, recorded as 51,395 frames with the achievement counter that rose on
each step. The frame at which a counter rose is the frame that *demonstrated*
that skill, so the teacher's demonstrations split into skills by the same
definition `lab/select.py` uses.

Four arms, each spending the **same total number of sample-passes**:

* **seq** - the weights path as the design states it: one policy, fine-tuned
  on the demonstrations **skill by skill**, in the order the teacher taught
  them. The newest skill is the last one.
* **seq_replay** - the same sequence, but every stage also replays the
  earlier skills' demonstrations. This is "keep the whole log" carried into
  the weights path.
* **whole** - one policy fine-tuned on all the demonstrations at once. The
  chooser's answer, carried into the weights path.
* **per_skill_heads** - a shared trunk trained on everything, and one head per
  skill trained only on that skill's demonstrations. The substrate rule the
  sleep-dreaming toy points at: the old knowledge has to live in parameters
  that nothing else touches.

The instrument is crafter-lab's own: **student-teacher agreement per skill**,
measured on a held-out half of each skill's demonstration frames, after every
stage. The design calls this the curve that says when a teacher can be
retired for a skill.

Everything runs on the CPU, on the Thor.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

CRAFTER_LAB = Path.home() / "lm-wt/crafter-lab"
if str(CRAFTER_LAB) not in sys.path:
    sys.path.insert(0, str(CRAFTER_LAB))

import torch as th  # noqa: E402

from lab import core as core  # noqa: E402
from lab import select as select  # noqa: E402
from lab import student as stu  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "docs" / "lab" / "lab3-scripts"))
from boxstate import box_state, format_box_state  # noqa: E402


# ---------------------------------------------------------------- the config


@dataclass(frozen=True)
class Config:
    """Every knob, so the numbers can be re-derived."""

    skills: int = 6
    passes_per_stage: int = 16384
    seeds: int = 3
    split_seed: int = 20261101
    env_episodes: int = 4
    env_length: int = 1000
    trajectory_frames: int = 2000
    arms: tuple[str, ...] = ("seq", "seq_replay", "whole", "per_skill_heads")


# ---------------------------------------------------------------- the data


def load_teacher(path: Path) -> dict[str, np.ndarray]:
    """The teacher's frames, in the layout the student trains on."""
    z = np.load(path, allow_pickle=False)
    return {
        "obs": np.ascontiguousarray(np.transpose(z["observations"], (0, 3, 1, 2))),
        "actions": z["actions"].astype(np.int64),
        "events": z["achievement_event"].astype(np.int64),
        "episode": z["episode"].astype(np.int64),
    }


def skill_order(frames: Mapping[str, np.ndarray], names: Sequence[str]) -> list[str]:
    """The order the teacher taught the skills in.

    The order a skill first appears in the teacher's episodes: the teacher
    teaches them in the order the world makes them available, and a student
    watching the teacher sees them in that order.
    """
    events = frames["events"]
    episode = frames["episode"]
    first: dict[int, int] = {}
    for index, event in enumerate(events):
        if event < 0:
            continue
        e = int(event)
        key = int(episode[index]) * 10_000_000 + index
        if e not in first or key < first[e]:
            first[e] = key
    order = sorted(first, key=lambda e: first[e])
    return [names[e] for e in order]


#: How many frames of the teacher's approach count as part of a skill's
#: demonstration. The frame at which a counter rose carries the action
#: ``do`` - the same action for every skill - so a demonstration measured
#: on that frame alone cannot tell one skill from another (and any policy
#: that says "do" scores 1.0 on all of them). The lesson is the **sequence**
#: the teacher played to get there: the frames before the interaction, where
#: the teacher walks to the resource and faces it.
DEMO_LEAD = 12


def skill_splits(
    frames: Mapping[str, np.ndarray],
    names: Sequence[str],
    chosen: Sequence[str],
    split_seed: int,
    eval_cap: int = 1000,
) -> dict[str, dict[str, np.ndarray]]:
    """Each skill's demonstrations, split into a train half and an eval half.

    A skill's demonstrations are the teacher's approach to it: the
    ``DEMO_LEAD`` frames before each frame at which the skill's counter rose,
    and that frame itself. The eval half is never trained on, so the
    agreement is measured on demonstrations the student has not seen for
    that skill.
    """
    events = frames["events"]
    rng = np.random.RandomState(split_seed)
    out: dict[str, dict[str, np.ndarray]] = {}
    for name in chosen:
        index = int(names.index(name))
        where = np.where(events == index)[0]
        window = np.unique(
            np.concatenate([np.arange(max(0, t - DEMO_LEAD), t + 1) for t in where])
        )
        order = rng.permutation(len(window))
        half = len(window) // 2
        train = np.sort(window[order[:half]])
        evaluate = window[order[half:]]
        if len(evaluate) > eval_cap:
            # A fixed random subsample: the agreement's standard error at
            # 1000 frames is about 1.5 points, and the evaluation runs after
            # every stage of every arm.
            evaluate = np.sort(evaluate[:eval_cap])
        out[name] = {"train": train, "eval": evaluate}
    return out


# ---------------------------------------------------------------- the students


class HeadStudent:
    """A shared trunk with one head per skill.

    The trunk (``features_extractor`` + ``mlp_extractor``) is the substrate;
    each skill gets its own linear head over the trunk's latent. The
    agreement for a skill is measured through that skill's head, which is
    what "per-skill heads" means: the old skills' outputs are not written by
    the new skill's training.
    """

    def __init__(self, policy: Any, device: str = "cpu"):
        self.policy = policy
        self.device = device
        self.heads: dict[str, th.nn.Linear] = {}
        self._latent_dim = policy.mlp_extractor.latent_dim

    def features(self, obs: np.ndarray) -> th.Tensor:
        arr = np.ascontiguousarray(np.asarray(obs, np.uint8))
        tensor = th.as_tensor(arr, device=self.device)
        with th.no_grad():
            feats = self.policy.extract_features(tensor)
            latent, _ = self.policy.mlp_extractor(feats)
        return latent

    def predict_with(self, head: th.nn.Linear, obs: np.ndarray) -> np.ndarray:
        with th.no_grad():
            logits = head(self.features(obs))
        return logits.argmax(1).cpu().numpy()

    def predict_batch(self, obs: np.ndarray) -> np.ndarray:
        """The default head's prediction (the policy's own action_net)."""
        return stu.Student(self.policy, self.device).predict_batch(obs)


def train_head(
    student: HeadStudent,
    head: th.nn.Linear,
    obs: np.ndarray,
    actions: np.ndarray,
    passes_budget: int,
    rng: np.random.RandomState,
    batch_size: int = stu.BATCH,
) -> None:
    """Cross-entropy on one head, with the trunk frozen."""
    params = list(student.policy.features_extractor.parameters())
    params += list(student.policy.mlp_extractor.parameters())
    for param in params:
        param.requires_grad_(False)
    optimiser = th.optim.Adam(list(head.parameters()), lr=stu.LR)
    acts = th.as_tensor(np.asarray(actions, np.int64))
    updates = int(math.ceil(passes_budget / batch_size))
    for _ in range(updates):
        idx = rng.randint(0, len(actions), batch_size)
        latent = student.features(obs[idx])
        loss = th.nn.functional.cross_entropy(head(latent), acts[idx])
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
    for param in params:
        param.requires_grad_(True)


# ---------------------------------------------------------------- the arms


def agreement_table(
    student: Any,
    frames: Mapping[str, np.ndarray],
    splits: Mapping[str, Mapping[str, np.ndarray]],
    names: Sequence[str],
    heads: Mapping[str, th.nn.Linear] | None = None,
) -> dict[str, float | None]:
    """The student-teacher agreement per skill, on the held-out frames."""
    out: dict[str, float | None] = {}
    for name, split in splits.items():
        index = np.where(frames["events"] == names.index(name))[0]
        mask = split["eval"]
        if len(mask) == 0:
            out[name] = None
            continue
        if heads is not None:
            head = heads[name]
            preds = student.predict_with(head, frames["obs"][mask])
        else:
            preds = student.predict_batch(frames["obs"][mask])
        out[name] = float((preds == frames["actions"][mask]).mean())
    return out


def overall_agreement(
    student: Any,
    frames: Mapping[str, np.ndarray],
    trajectory: np.ndarray,
) -> float | None:
    """The agreement over a fixed subsample of the whole teacher trajectory.

    This is the whole-policy measure: the trajectory carries every action
    the teacher plays, not only the interactions, so a student that has
    learned nothing scores about what the most common action is worth.
    """
    if len(trajectory) == 0:
        return None
    preds = student.predict_batch(frames["obs"][trajectory])
    return float((preds == frames["actions"][trajectory]).mean())


def env_score(student: Any, n_episodes: int, length: int) -> dict[str, Any] | None:
    """The student's own achievement score, in fresh Crafter episodes.

    This is the design's "task success with the student alone": the number
    that must not fall. It is a coarse instrument - the students here are
    weak - so it is reported beside the agreement, not instead of it.
    """
    from lab import evaluate as ev

    summary = ev.evaluate(
        lambda obs, info: student.act(obs), n_episodes=n_episodes, length=length
    )
    return {
        "mean_achievements": summary["mean_achievements"],
        "mean_return": summary["mean_return"],
        "success_rate": summary["success_rate"],
    }


def run_arm(
    arm: str,
    config: Config,
    seed: int,
    frames: Mapping[str, np.ndarray],
    splits: Mapping[str, Mapping[str, np.ndarray]],
    names: Sequence[str],
    order: Sequence[str],
    trajectory: np.ndarray,
) -> dict[str, Any]:
    """One arm, one seed: the agreement after every stage."""
    obs_space, action_space = core.make_spaces()
    th.manual_seed(seed)
    np.random.seed(seed)
    rng = np.random.RandomState(seed)
    policy = stu.build_policy(obs_space, action_space, seed=seed)
    student = stu.Student(policy, "cpu")
    total_budget = config.passes_per_stage * len(order)
    stages: list[dict[str, Any]] = []

    if arm == "seq":
        for skill in order:
            split = splits[skill]
            stu.bc_train(
                student,
                frames["obs"][split["train"]],
                frames["actions"][split["train"]],
                config.passes_per_stage,
                rng=rng,
            )
            stages.append(
                {
                    "stage": skill,
                    "agreement": agreement_table(student, frames, splits, names),
                    "overall": overall_agreement(student, frames, trajectory),
                }
            )

    elif arm == "seq_replay":
        seen: list[str] = []
        for skill in order:
            split = splits[skill]
            new_obs = frames["obs"][split["train"]]
            new_act = frames["actions"][split["train"]]
            if seen:
                # Half of the stage's budget replays the earlier skills.
                half = max(1, len(new_obs))
                old_idx = np.concatenate([splits[s]["train"] for s in seen])
                pick = old_idx[rng.randint(0, len(old_idx), half)]
                train_obs = np.concatenate([new_obs, frames["obs"][pick]])
                train_act = np.concatenate([new_act, frames["actions"][pick]])
            else:
                train_obs, train_act = new_obs, new_act
            stu.bc_train(student, train_obs, train_act, config.passes_per_stage, rng=rng)
            seen.append(skill)
            stages.append(
                {
                    "stage": skill,
                    "agreement": agreement_table(student, frames, splits, names),
                    "overall": overall_agreement(student, frames, trajectory),
                }
            )

    elif arm == "whole":
        train_idx = np.concatenate([splits[s]["train"] for s in order])
        stu.bc_train(
            student,
            frames["obs"][train_idx],
            frames["actions"][train_idx],
            total_budget,
            rng=rng,
        )
        stages.append(
            {
                "stage": "all",
                "agreement": agreement_table(student, frames, splits, names),
                "overall": overall_agreement(student, frames, trajectory),
            }
        )

    elif arm == "per_skill_heads":
        head_student = HeadStudent(policy, "cpu")
        # The trunk: half the budget, on every skill's demonstrations.
        trunk_budget = total_budget // 2
        train_idx = np.concatenate([splits[s]["train"] for s in order])
        stu.bc_train(
            student,
            frames["obs"][train_idx],
            frames["actions"][train_idx],
            trunk_budget,
            rng=rng,
        )
        stages.append(
            {
                "stage": "trunk",
                "agreement": agreement_table(head_student, frames, splits, names),
                "overall": overall_agreement(head_student, frames, trajectory),
            }
        )
        # One head per skill, on that skill's demonstrations only.
        head_budget = (total_budget - trunk_budget) // len(order)
        heads: dict[str, th.nn.Linear] = {}
        for skill in order:
            head = th.nn.Linear(head_student._latent_dim, action_space.n).to("cpu")
            split = splits[skill]
            train_head(
                head_student,
                head,
                frames["obs"][split["train"]],
                frames["actions"][split["train"]],
                head_budget,
                rng,
            )
            heads[skill] = head
            stages.append(
                {
                    "stage": skill,
                    "agreement": agreement_table(
                        head_student, frames, splits, names, heads=heads
                    ),
                    "overall": overall_agreement(head_student, frames, trajectory),
                }
            )
    else:
        raise ValueError(f"unknown arm {arm!r}")

    # The behavioural check: what the finished student does on its own.
    env: dict[str, Any] | None = None
    if arm != "per_skill_heads":
        # The per-skill-heads arm has no single policy - which head answers
        # the environment is the question the design has not answered - so it
        # has no environment score. That is a cost of the design, and it is
        # named rather than papered over.
        env = env_score(student, config.env_episodes, config.env_length)

    # The summary the question is asked with.
    final = stages[-1]["agreement"]
    peaks: dict[str, float | None] = {}
    for skill in order:
        values = [stage["agreement"].get(skill) for stage in stages]
        values = [v for v in values if v is not None]
        peaks[skill] = max(values) if values else None
    old_skills = list(order[:-1])
    newest = order[-1]
    forgetting = {
        skill: (peaks[skill] - final.get(skill))
        for skill in order
        if peaks[skill] is not None and final.get(skill) is not None
    }
    old_final = [final[s] for s in old_skills if final.get(s) is not None]
    old_peak = [peaks[s] for s in old_skills if peaks.get(s) is not None]
    return {
        "arm": arm,
        "seed": seed,
        "stages": stages,
        "final": final,
        "peaks": peaks,
        "forgetting": forgetting,
        "newest_skill": newest,
        "newest_final": final.get(newest),
        "newest_peak": peaks.get(newest),
        "old_mean_final": (sum(old_final) / len(old_final)) if old_final else None,
        "old_mean_peak": (sum(old_peak) / len(old_peak)) if old_peak else None,
        "mean_forgetting_old": (
            sum(forgetting[s] for s in old_skills if s in forgetting)
            / max(1, len([s for s in old_skills if s in forgetting]))
        ),
        "overall_final": stages[-1]["overall"],
        "env": env,
    }


# ---------------------------------------------------------------- the statistics

_T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def t_critical(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df <= len(_T95):
        return _T95[df - 1]
    return 1.96


def mean_ci(values: Sequence[float | None]) -> dict[str, Any]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "sd": None}
    n = len(clean)
    mean = sum(clean) / n
    if n == 1:
        return {"n": 1, "mean": mean, "lo": mean, "hi": mean, "sd": 0.0}
    var = sum((v - mean) ** 2 for v in clean) / (n - 1)
    sd = math.sqrt(var)
    half = t_critical(n - 1) * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "lo": mean - half, "hi": mean + half, "sd": sd,
            "min": min(clean), "max": max(clean)}


def summarise(runs: Sequence[dict[str, Any]], order: Sequence[str]) -> list[dict[str, Any]]:
    """The per-arm summary: the means and their intervals."""
    out: list[dict[str, Any]] = []
    arms = sorted({run["arm"] for run in runs})
    for arm in arms:
        subset = [r for r in runs if r["arm"] == arm]
        entry: dict[str, Any] = {
            "arm": arm,
            "seeds": len(subset),
            "newest_final": mean_ci([r["newest_final"] for r in subset]),
            "newest_peak": mean_ci([r["newest_peak"] for r in subset]),
            "old_mean_final": mean_ci([r["old_mean_final"] for r in subset]),
            "old_mean_peak": mean_ci([r["old_mean_peak"] for r in subset]),
            "mean_forgetting_old": mean_ci([r["mean_forgetting_old"] for r in subset]),
            "overall_final": mean_ci([r["overall_final"] for r in subset]),
            "env_achievements": mean_ci(
                [
                    r["env"]["mean_achievements"] if r.get("env") else None
                    for r in subset
                ]
            ),
            "per_skill_final": {
                skill: mean_ci([r["final"].get(skill) for r in subset]) for skill in order
            },
            "per_skill_forgetting": {
                skill: mean_ci([r["forgetting"].get(skill) for r in subset]) for skill in order
            },
        }
        out.append(entry)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--skills", type=int, default=6)
    parser.add_argument("--passes-per-stage", type=int, default=16384)
    parser.add_argument("--arms", default="seq,seq_replay,whole,per_skill_heads")
    parser.add_argument(
        "--frames",
        default=str(CRAFTER_LAB / "data" / "teacher_frames.npz"),
        help="the teacher frames crafter-lab recorded",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "results" / "watching_teachers.json"),
    )
    args = parser.parse_args()

    config = Config(
        skills=args.skills,
        passes_per_stage=args.passes_per_stage,
        seeds=args.seeds,
    )
    names = list(core.ACHIEVEMENTS)
    frames = load_teacher(Path(args.frames))
    order_all = skill_order(frames, names)
    counts = {
        name: int((frames["events"] == names.index(name)).sum()) for name in order_all
    }
    # The skills with the most demonstrations, kept in the order the teacher
    # taught them: the newest one is the last the teacher reached.
    chosen = sorted(order_all, key=lambda n: -counts[n])[: config.skills]
    order = [name for name in order_all if name in chosen]
    splits = skill_splits(frames, names, order, config.split_seed)
    # A fixed subsample of the whole teacher trajectory: the whole-policy
    # measure, on the same frames for every arm and every stage.
    trajectory = np.random.RandomState(config.split_seed).choice(
        len(frames["actions"]), size=min(config.trajectory_frames, len(frames["actions"])),
        replace=False,
    )

    started = box_state()
    runs: list[dict[str, Any]] = []
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    for arm in arms:
        for seed in range(args.seeds):
            t0 = time.monotonic()
            run = run_arm(arm, config, seed, frames, splits, names, order, trajectory)
            run["seconds"] = time.monotonic() - t0
            runs.append(run)
            print(
                f"  {arm:16s} seed {seed}  "
                f"newest {run['newest_final']:.3f} (peak {run['newest_peak']:.3f})  "
                f"old mean {run['old_mean_final']:.3f}  "
                f"overall {run['overall_final']:.3f}  "
                f"env {(run['env'] or {}).get('mean_achievements', float('nan')):.2f}  "
                f"{run['seconds']:.0f}s",
                flush=True,
            )
    finished = box_state()

    payload = {
        "experiment": "watching teachers: one policy, many demonstrations",
        "when": started.get("time"),
        "config": {
            **asdict(config),
            "arms": arms,
            "teacher_frames": str(args.frames),
        },
        "skills_in_order": order,
        "skill_demo_counts": {name: counts[name] for name in order},
        "split": {
            name: {
                "train": int(len(splits[name]["train"])),
                "eval": int(len(splits[name]["eval"])),
            }
            for name in order
        },
        "box_state_before": started,
        "box_state_after": finished,
        "runs": runs,
        "summary": summarise(runs, order),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"\n{len(runs)} runs -> {out}")
    print(format_box_state(finished))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
