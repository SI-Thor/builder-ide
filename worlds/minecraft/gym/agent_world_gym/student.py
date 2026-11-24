"""The smoke student: behaviour cloning, in numpy.

The question the desk asked: **does a student that watches the community
beat a student that does not?** The smoke version of that question is a
behaviour-cloning student — a softmax linear policy over the state's
facts, trained on the recorded frames by maximum likelihood — measured
against a random policy on the same episodes, with the world's own
achievements-equivalent as the score: **projects and gathers per
episode**.

Why numpy and not a framework: the point of this stage is the *pipeline*
(the world's frames → a dataset → a student → a score in the world's own
units), not the student's capacity. A linear softmax policy is the
honest floor: it can only read the state facts and pick an option, so a
number that moves is evidence about the data and the contract, not about
the model class. Stable-Baselines3 is the next step, on the same
datasets, and the datasets are what it would read.

Two measures are reported, and they answer different questions:

* **agreement** — the fraction of held-out frames where the student's
  greedy choice is the one the community chose. It is cheap, and it is
  the *competence* proxy the crafter round-2 report settled on (decisive
  frames alone are a memorisation alarm, not a score).
* **projects / gathers per episode** — what the student actually did in
  the world. Agreement can be high and the score zero; only the second
  one is the world's opinion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

__all__ = [
    "BCStudent",
    "RandomPolicy",
    "features_of",
    "dataset_frames",
    "train_student",
    "agreement",
    "evaluate_in_env",
]


def features_of(observation: dict[str, Any]) -> np.ndarray:
    """The feature vector: the state facts.

    The grid is left out on purpose. The community's ledger holds no
    grids, so a student that used one could not be cloned from the
    community at all, and the comparison would be about the feature
    choice rather than about watching.
    """
    facts = observation["facts"]
    return np.asarray(facts, dtype=np.float32).reshape(-1)


def dataset_frames(dataset: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The frames of a Minari dataset: features, teacher actions, episode ids.

    Every frame is kept — the crafter round-2 rule. The episode id is
    returned so a held-out split can be made by *episode* rather than by
    frame: a split by frame would put a student's own next frame in the
    training set.
    """
    features: list[np.ndarray] = []
    actions: list[int] = []
    episodes: list[int] = []
    for index, episode in enumerate(dataset.iterate_episodes()):
        observations = episode.observations["facts"]
        episode_actions = episode.actions
        rewards = episode.rewards
        for step in range(len(rewards)):
            features.append(np.asarray(observations[step], dtype=np.float32).reshape(-1))
            actions.append(int(np.asarray(episode_actions[step]).reshape(-1)[0]))
            episodes.append(index)
    if not features:
        return (
            np.zeros((0, 0), dtype=np.float32),
            np.zeros((0,), dtype=np.int64),
            np.zeros((0,), dtype=np.int64),
        )
    return (
        np.stack(features),
        np.asarray(actions, dtype=np.int64),
        np.asarray(episodes, dtype=np.int64),
    )


class BCStudent:
    """A softmax linear policy, trained by maximum likelihood."""

    def __init__(
        self,
        n_features: int,
        n_actions: int,
        *,
        seed: int = 0,
        learning_rate: float = 0.5,
        l2: float = 1e-4,
        iterations: int = 600,
    ) -> None:
        self.n_features = int(n_features)
        self.n_actions = int(n_actions)
        self.seed = int(seed)
        self.learning_rate = float(learning_rate)
        self.l2 = float(l2)
        self.iterations = int(iterations)
        rng = np.random.default_rng(self.seed)
        scale = 0.01 / max(1.0, float(np.sqrt(self.n_features)))
        self.weights = rng.normal(0.0, scale, size=(self.n_features, self.n_actions)).astype(np.float32)
        self.bias = np.zeros(self.n_actions, dtype=np.float32)
        self.history: list[float] = []

    # -- the arithmetic ---------------------------------------------------------

    def logits(self, features: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(features, dtype=np.float32))
        return x @ self.weights + self.bias

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - logits.max(axis=-1, keepdims=True)
        exponentials = np.exp(shifted)
        return exponentials / exponentials.sum(axis=-1, keepdims=True)

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        return self._softmax(self.logits(features))

    def fit(self, features: np.ndarray, actions: np.ndarray) -> dict[str, Any]:
        """Maximum likelihood, full batch, plain gradient descent.

        Full batch on purpose: the frames are a few thousand at most, the
        matrix work is milliseconds, and a deterministic optimiser means a
        number can be reproduced from the seed alone.
        """
        x = np.asarray(features, dtype=np.float32)
        y = np.asarray(actions, dtype=np.int64)
        if x.size == 0:
            self.history = []
            return {"frames": 0, "loss": None, "accuracy": None}
        n = x.shape[0]
        onehot = np.zeros((n, self.n_actions), dtype=np.float32)
        onehot[np.arange(n), y] = 1.0

        for _ in range(self.iterations):
            probabilities = self._softmax(x @ self.weights + self.bias)
            error = probabilities - onehot
            gradient_w = (x.T @ error) / n + self.l2 * self.weights
            gradient_b = error.mean(axis=0)
            self.weights -= self.learning_rate * gradient_w
            self.bias -= self.learning_rate * gradient_b
            loss = float(
                -np.mean(np.log(np.clip(probabilities[np.arange(n), y], 1e-12, 1.0)))
            )
            self.history.append(loss)
        return {
            "frames": int(n),
            "loss": self.history[-1] if self.history else None,
            "accuracy": float(self.accuracy(x, y)),
        }

    def accuracy(self, features: np.ndarray, actions: np.ndarray) -> float:
        x = np.asarray(features, dtype=np.float32)
        y = np.asarray(actions, dtype=np.int64)
        if x.size == 0:
            return 0.0
        predicted = self.logits(x).argmax(axis=-1)
        return float(np.mean(predicted == y))

    # -- the choice -------------------------------------------------------------

    def choose(
        self,
        observation: dict[str, Any],
        eligible: Sequence[int],
        *,
        greedy: bool = True,
        rng: np.random.Generator | None = None,
    ) -> int:
        """The option to play: the best eligible one, or a masked sample."""
        options = sorted(int(x) for x in eligible)
        if not options:
            raise RuntimeError("no option applies here")
        logits = self.logits(features_of(observation))[0]
        masked = np.full(self.n_actions, -np.inf, dtype=np.float32)
        masked[options] = logits[options]
        if greedy:
            return int(options[int(np.argmax(masked[options]))])
        generator = rng or np.random.default_rng()
        probabilities = self._softmax(masked[None, :])[0]
        probabilities = np.clip(probabilities, 0.0, None)
        total = probabilities.sum()
        if total <= 0:
            return int(options[0])
        probabilities = probabilities / total
        return int(generator.choice(options, p=probabilities[options] / probabilities[options].sum()))

    # -- the disk ---------------------------------------------------------------

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            weights=self.weights,
            bias=self.bias,
            meta=json.dumps(
                {
                    "n_features": self.n_features,
                    "n_actions": self.n_actions,
                    "seed": self.seed,
                    "learning_rate": self.learning_rate,
                    "l2": self.l2,
                    "iterations": self.iterations,
                    "final_loss": self.history[-1] if self.history else None,
                }
            ),
        )

    @classmethod
    def load(cls, path: Path | str) -> "BCStudent":
        with np.load(Path(path), allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            student = cls(
                meta["n_features"],
                meta["n_actions"],
                seed=meta.get("seed", 0),
                learning_rate=meta.get("learning_rate", 0.5),
                l2=meta.get("l2", 1e-4),
                iterations=meta.get("iterations", 600),
            )
            student.weights = data["weights"]
            student.bias = data["bias"]
        return student


class RandomPolicy:
    """The floor: a uniform draw over the eligible options."""

    def __init__(self, *, seed: int = 0) -> None:
        self.rng = np.random.default_rng(int(seed))

    def choose(self, observation: dict[str, Any], eligible: Sequence[int], **_: Any) -> int:
        options = sorted(int(x) for x in eligible)
        if not options:
            raise RuntimeError("no option applies here")
        return int(options[int(self.rng.integers(len(options)))])


def train_student(
    features: np.ndarray,
    actions: np.ndarray,
    *,
    n_actions: int,
    episode_ids: np.ndarray | None = None,
    seed: int = 0,
    holdout: float = 0.2,
    **kwargs: Any,
) -> tuple[BCStudent, dict[str, Any]]:
    """Train a student and hold out whole episodes for the agreement.

    The split is by episode, never by frame: a student's next frame in the
    same episode is not a held-out question. With no episode ids to hand
    (a caller that flattened the frames already), the frames are split in
    order and the report says so.
    """
    x = np.asarray(features, dtype=np.float32)
    y = np.asarray(actions, dtype=np.int64)
    student = BCStudent(
        x.shape[1] if x.size else 0,
        n_actions,
        seed=seed,
        **kwargs,
    )
    if x.size == 0:
        return student, {"frames": 0, "train_frames": 0, "heldout_frames": 0}

    train_idx, held_idx = _split_by_episode(
        x.shape[0],
        episode_ids=episode_ids,
        holdout=holdout,
        seed=seed,
    )
    fit_report = student.fit(x[train_idx], y[train_idx])
    report = dict(fit_report)
    report["train_frames"] = int(train_idx.size)
    report["heldout_frames"] = int(held_idx.size)
    report["train_accuracy"] = student.accuracy(x[train_idx], y[train_idx])
    report["heldout_accuracy"] = (
        student.accuracy(x[held_idx], y[held_idx]) if held_idx.size else None
    )
    report["split"] = "by episode" if episode_ids is not None else "by order"
    return student, report


def _split_by_episode(
    n_frames: int,
    *,
    episode_ids: np.ndarray | None,
    holdout: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Whole episodes to the held-out side, never whole frames."""
    if episode_ids is None or len(episode_ids) != n_frames:
        cut = int(n_frames * (1.0 - float(holdout)))
        cut = max(1, min(cut, n_frames - 1)) if n_frames > 1 else n_frames
        return np.arange(cut), np.arange(cut, n_frames)
    ids = np.asarray(episode_ids)
    unique = np.unique(ids)
    generator = np.random.default_rng(int(seed))
    shuffled = generator.permutation(unique)
    n_held = max(1, int(round(len(unique) * float(holdout)))) if len(unique) > 1 else 0
    held_ids = set(shuffled[:n_held].tolist())
    held_mask = np.array([int(i) in held_ids for i in ids], dtype=bool)
    # With one episode there is nothing to hold out: the whole of it is
    # training, and the report says the held-out side is empty rather
    # than quietly stealing a frame from the training side.
    return np.nonzero(~held_mask)[0], np.nonzero(held_mask)[0]


def agreement(student: BCStudent, features: np.ndarray, actions: np.ndarray) -> float:
    """The fraction of frames where the student's greedy choice is the teacher's."""
    return student.accuracy(features, actions)


def evaluate_in_env(
    policy: Any,
    env: Any,
    *,
    episodes: int = 3,
    seed: int = 0,
    greedy: bool = True,
) -> dict[str, Any]:
    """Play episodes and report the world's own achievements-equivalent.

    **projects** and **gathers** per episode: a project is a play whose
    sealed placement prediction held, a gather is a play whose sealed
    inventory prediction held. Those are the numbers the live community
    reports, in the same units.
    """
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(int(seed))
    for episode in range(int(episodes)):
        observation, info = env.reset(seed=int(seed) + episode)
        total_reward = 0.0
        refused = 0
        done = False
        while not done:
            eligible = list(info.get("eligible_actions") or [])
            if not eligible:
                eligible = list(range(int(env.action_space.n)))
            action = policy.choose(observation, eligible, greedy=greedy, rng=rng)
            observation, reward, terminated, truncated, info = env.step(int(action))
            total_reward += float(reward)
            if info.get("refused"):
                refused += 1
            done = bool(terminated) or bool(truncated)
        rows.append(
            {
                "episode": episode,
                "gathers": int(info.get("gathers", 0)),
                "projects": int(info.get("projects", 0)),
                "reward": total_reward,
                "steps": int(info.get("steps", 0)),
                "refused": refused,
            }
        )
    summary = {
        "episodes": len(rows),
        "gathers_per_episode": float(np.mean([r["gathers"] for r in rows])) if rows else 0.0,
        "projects_per_episode": float(np.mean([r["projects"] for r in rows])) if rows else 0.0,
        "reward_per_episode": float(np.mean([r["reward"] for r in rows])) if rows else 0.0,
        "steps_per_episode": float(np.mean([r["steps"] for r in rows])) if rows else 0.0,
        "refused_per_episode": float(np.mean([r["refused"] for r in rows])) if rows else 0.0,
        "rows": rows,
    }
    return summary
