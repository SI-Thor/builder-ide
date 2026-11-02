"""The Bevy world adapter — a stub, and the interface it will meet.

The brief asks for stubs and an interface for the **Bevy world** as
well. This is the second.

Bevy is our own engine line: the world is a running program, the
builder is an avatar in it, and the primitives are *the world's own
actions* — move, look, use, place. The loop does not change here
either; the engine changes under it.

What this stub fixes down is the seam a Bevy adapter has to cross:

* the **facts** — a Bevy world's state is a scene graph, and the facts
  have to be a player's-eye view of it, not a dump of the graph;
* the **actions** — a Bevy action is an input to a running program, and
  the adapter has to own the input seam (the same question the
  autopilot study answered for its engines: what is the actuator);
* the **ground truth** — a Bevy world's "did you do the thing" is the
  world's own state change, read back from the program;
* the **latency** — a Bevy world runs at a frame rate, and a skill's
  steps are frames; the timeout has to be in frames, not seconds.

Like the vibe-sandbox stub, every unimplemented operation raises with
the name of the seam, so nothing here can return a plausible wrong
answer.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import Milestone
from ..ports import CheckResult, EnvironmentPort, ExecResult, ProgressSnapshot
from ..vocab import BODY_SCHEMA, BODY_WORD, SkillVocabulary

__all__ = ["BevyAdapter", "bevy_vocabulary", "BEVY_MILESTONES"]

#: The milestones a Bevy loop would carry.
BEVY_MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        key="walk_to_marker",
        title="walk to a marker",
        description="A skill that takes the avatar to a marked place.",
        items=("walk_to_marker",),
    ),
    Milestone(
        key="place_object",
        title="place an object",
        description="A skill that puts an object down in the world.",
        needs=("walk_to_marker",),
        items=("place_object",),
    ),
)


def bevy_vocabulary() -> SkillVocabulary:
    """The closed vocabulary a Bevy skill would use."""
    words: dict[str, Mapping[str, Any]] = {
        "bevy.move_to": {
            "x": {"type": "number", "minimum": -100000, "maximum": 100000},
            "y": {"type": "number", "minimum": -1000, "maximum": 1000},
            "z": {"type": "number", "minimum": -100000, "maximum": 100000},
        },
        "bevy.look_at": {
            "x": {"type": "number", "minimum": -100000, "maximum": 100000},
            "y": {"type": "number", "minimum": -1000, "maximum": 1000},
            "z": {"type": "number", "minimum": -100000, "maximum": 100000},
        },
        "bevy.place": {
            "kind": {"type": "string", "hint": "the kind of thing to place"},
        },
        "bevy.use": {
            "target": {"type": "string", "hint": "what to use"},
        },
        "bevy.frames": {
            "count": {"type": "integer", "minimum": 1, "maximum": 100000},
        },
        BODY_WORD: BODY_SCHEMA,
    }
    return SkillVocabulary(words)


class BevyAdapter:
    """The Bevy world, as an environment — not yet a world."""

    name = "bevy"
    language = "rust"

    def __init__(self, *, log=None) -> None:
        self._log = log or (lambda message: None)
        self._registry = bevy_vocabulary()

    def open(self) -> None:
        raise NotImplementedError(
            "the Bevy adapter is a stub: it needs the engine's own input "
            "seam (the actuator) and a reader for the scene's state"
        )

    def close(self) -> None:
        return None

    def observe(self) -> dict[str, Any]:
        raise NotImplementedError(
            "the Bevy adapter is a stub: the facts have to be a player's-eye "
            "view of the scene, and the scene reader does not exist yet"
        )

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        raise NotImplementedError(
            "the Bevy adapter is a stub: a skill's steps are inputs to a "
            "running program, and the input seam is not built"
        )

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        raise NotImplementedError(
            "the Bevy adapter is a stub: the self-verification is a read of "
            "the scene's state after the skill ran"
        )

    def goal_truth(self, key: str) -> bool:
        raise NotImplementedError(
            "the Bevy adapter is a stub: the ground truth is the world's own "
            "state change, read back from the program"
        )

    def progress(self) -> ProgressSnapshot:
        raise NotImplementedError(
            "the Bevy adapter is a stub: the counts would be the scene's "
            "objects and the frames rendered"
        )

    def primitives(self) -> tuple[str, ...]:
        return self._registry.words()

    def primitive_schemas(self) -> Mapping[str, Any]:
        return self._registry.schema_map()

    def milestones(self) -> tuple[Milestone, ...]:
        return BEVY_MILESTONES
