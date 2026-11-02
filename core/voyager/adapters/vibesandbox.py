"""The vibe-sandbox adapter — a stub, and the interface it will meet.

The brief asks for stubs and an interface for the **vibe-sandbox build
skills** and the **Bevy world**. This is the first of the two.

The vibe-sandbox is where a builder writes *build* skills: a program
that changes a world rather than a program that plays in one. The loop
does not change at all — that is the point of the interface. What
changes is:

* the vocabulary — a builder's primitives are edits, not actions, and
  they are the closed vocabulary of :mod:`core.vocab`;
* the ground truth — a build skill is judged by the critic and the
  sealed prediction, not by an inventory;
* the feedback — a build skill's log is a diff, not a console.

What this stub does **not** do is pretend. Every operation that would
need the world raises ``NotImplementedError`` with the name of the seam
it would have to cross, so a caller that reaches this adapter learns
what is missing instead of getting a plausible wrong answer.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import Milestone
from ..ports import CheckResult, EnvironmentPort, ExecResult, ProgressSnapshot
from ..vocab import BODY_SCHEMA, BODY_WORD, SkillVocabulary

__all__ = ["VibeSandboxAdapter", "vibe_vocabulary", "VIBE_MILESTONES"]

#: The milestones a build loop would carry. They are placeholders with
#: the shape right, and the shape is the contract the real adapter will
#: meet.
VIBE_MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        key="first_build",
        title="land the first build",
        description="A build skill that changes the world and is kept.",
        items=("first_build",),
    ),
    Milestone(
        key="first_rewrite",
        title="rewrite a build that was not kept",
        description="A revision of a build the critic refused.",
        needs=("first_build",),
        items=("first_rewrite",),
    ),
)


def vibe_vocabulary() -> SkillVocabulary:
    """The closed vocabulary a build skill would use.

    The words are the *edits* — a builder's vocabulary, typed and
    bounded, the same door a child's call goes through. The schemas are
    placeholders: the real ones are ``core.vocab``'s, and this adapter
    will ask that registry rather than carry a copy of it.
    """
    words: dict[str, Mapping[str, Any]] = {
        "build.place": {
            "entry": {"type": "string", "hint": "the recipe entry path"},
            "count": {"type": "integer", "minimum": 0, "maximum": 1000},
        },
        "build.remove": {
            "entry": {"type": "string", "hint": "the recipe entry path"},
        },
        "build.set": {
            "entry": {"type": "string", "hint": "the recipe entry path"},
            "value": {"type": "string", "hint": "the value to write"},
        },
        BODY_WORD: BODY_SCHEMA,
    }
    return SkillVocabulary(words)


class VibeSandboxAdapter:
    """The vibe-sandbox, as an environment — not yet a world.

    Every seam is named, and the ones that are not built raise.
    """

    name = "vibe-sandbox"
    language = "python"

    def __init__(self, *, log=None) -> None:
        self._log = log or (lambda message: None)
        self._registry = vibe_vocabulary()

    def open(self) -> None:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: it needs the world seat's "
            "recipe-store port and the critic's verdict port"
        )

    def close(self) -> None:
        return None

    def observe(self) -> dict[str, Any]:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: the facts of a build world "
            "are the recipe's diff, and no diff reader exists yet"
        )

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: a build skill's log is a "
            "diff against the recipe, and no diff writer exists yet"
        )

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: the self-verification of a "
            "build is the sealed prediction, which the world seat owns"
        )

    def goal_truth(self, key: str) -> bool:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: a build's ground truth is "
            "the critic's verdict plus the owner's keep"
        )

    def progress(self) -> ProgressSnapshot:
        raise NotImplementedError(
            "the vibe-sandbox adapter is a stub: the counts would be the "
            "recipe's entries and the critic's cards"
        )

    def primitives(self) -> tuple[str, ...]:
        return self._registry.words()

    def primitive_schemas(self) -> Mapping[str, Any]:
        return self._registry.schema_map()

    def milestones(self) -> tuple[Milestone, ...]:
        return VIBE_MILESTONES
