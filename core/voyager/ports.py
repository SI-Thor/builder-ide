"""The seams — what the Voyager loop needs from a world, and from a model.

The loop is **system-agnostic**: it knows about goals, skills, plays,
tokens and budgets, and it knows nothing about Minecraft, Crafter, a
vibe-sandbox or a Bevy world. Every world-specific fact arrives through
one of the two protocols below.

Two rules shape the interfaces, and both come from the harness rules the
autopilot study recorded (`docs/research/autopilot.md` §1.1):

* **the facts are in the player's terms.** ``observe()`` returns what a
  player would say ("there is oak at 12 blocks, the pickaxe broke"), not
  a dump of engine state. A fact nobody could act on is noise.
* **every action says what should change when it worked.** The ground
  truth of a goal is the environment's, not the model's: ``goal_truth``
  answers it, and the model's own self-verification is a second opinion,
  never the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = [
    "ExecResult",
    "CheckResult",
    "ProgressSnapshot",
    "EnvironmentPort",
    "ModelPort",
]


@dataclass(frozen=True)
class ExecResult:
    """What happened when a piece of skill code ran.

    ``ok`` is the sandbox's word, not the goal's: code that ran without
    throwing is ``ok`` even if it achieved nothing. The goal is judged
    separately (:meth:`EnvironmentPort.goal_truth` and the verifier), so
    the two verdicts cannot be confused for one.
    """

    ok: bool
    error: str = ""
    log: tuple[str, ...] = ()
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "log": list(self.log),
            "seconds": round(self.seconds, 3),
        }


@dataclass(frozen=True)
class CheckResult:
    """What happened when a self-verification snippet ran.

    ``passed`` is the snippet's own answer, and ``detail`` is why. A
    snippet that throws is not a pass: it is ``passed=False`` with the
    error in ``detail``.
    """

    passed: bool
    detail: str = ""
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
        }


@dataclass(frozen=True)
class ProgressSnapshot:
    """What the world has that it did not have before.

    ``unique_items`` is the count of **distinct item types** obtained over
    the whole run, which is the number the Voyager benchmark reports; the
    ``items`` map keeps the counts so the number can be recomputed from
    the log rather than trusted.
    """

    unique_items: int
    items: Mapping[str, int] = field(default_factory=dict)
    milestones: Mapping[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "unique_items": self.unique_items,
            "items": dict(self.items),
            "milestones": dict(self.milestones),
        }


@runtime_checkable
class EnvironmentPort(Protocol):
    """A world the loop can play in.

    An adapter implements this and nothing else; the loop never imports a
    world-specific module. The five operations are the whole contract:

    * ``observe`` — the facts, in the player's terms;
    * ``run_code`` — run a skill, and say what happened;
    * ``evaluate`` — run a self-verification snippet, and say what it said;
    * ``goal_truth`` — the environment's own answer to "is this goal met";
    * ``progress`` — the counts the report quotes.
    """

    #: The world's name, as the report prints it.
    name: str

    #: The language a skill is written in ("javascript", "python", …).
    language: str

    def open(self) -> None:
        """Bring the world up. Idempotent."""
        ...

    def close(self) -> None:
        """Take the world down cleanly. Idempotent."""
        ...

    def observe(self) -> dict[str, Any]:
        """The world's facts, in the player's terms."""
        ...

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        """Run a skill's body in the world's sandbox."""
        ...

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        """Run a self-verification snippet; it must return a boolean."""
        ...

    def goal_truth(self, key: str) -> bool:
        """The environment's own answer: is this milestone met?"""
        ...

    def progress(self) -> ProgressSnapshot:
        """The counts the report quotes."""
        ...

    def primitives(self) -> tuple[str, ...]:
        """The closed set of primitive names this world exposes."""
        ...


@runtime_checkable
class ModelPort(Protocol):
    """A language model, addressed by role.

    The three roles are separate models on purpose: the brief asks for a
    verifier **different from the coder**, because a model that writes the
    code and then marks its own homework measures nothing.
    """

    role: str
    model: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> tuple[str, dict[str, Any]]:
        """The reply text, and the usage record (tokens, seconds)."""
        ...
