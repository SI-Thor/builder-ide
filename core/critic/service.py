"""The chosen critic behind the core's ``Critic`` seam.

The night asks one question after the executor has run a variant: *how good
is this variant?* (``core.night.iterate.Critic``). The answer for a variant
whose output is a **render** is the chosen critic's opinion of the frame:
it looks at the picture and says which defect classes are in it.

The score is the fraction of the classes the critic did **not** find — a
clean frame scores 1.0, a frame with one class found scores 5/6 — so the
night's *best of* can order variants without the critic having to know
anything about taste.

Three things this keeps honest:

* **A frame the critic could not judge scores zero and says so.** A missing
  render is not a clean render, and a verdict nobody measured must never win
  a variant by accident.
* **The scripted critic is the fallback.** If the chosen critic cannot be
  built on this box, the seam gets the scripted one and the reason travels
  with it.
* **The label is on the score's face.** The reason says which critic
  answered, so a night's report never mixes verdicts from two critics
  without saying so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from core.night.iterate import CriticScore

from .critic import ReferenceCritic, ScriptedReferenceCritic
from .models import DEFECT_TARGETS
from .set import MemberRecipe

__all__ = ["RenderCritic", "render_of_artifact"]


def render_of_artifact(
    artifact: Any,
) -> str | None:
    """The frame a variant's artifact points at, if there is one."""
    if artifact is None:
        return None
    if isinstance(artifact, str):
        return artifact if Path(artifact).is_file() else None
    for attribute in ("render_path", "image_path", "path"):
        value = getattr(artifact, attribute, None)
        if isinstance(value, str) and Path(value).is_file():
            return value
    if isinstance(artifact, dict):
        for key in ("render_path", "image_path", "path"):
            value = artifact.get(key)
            if isinstance(value, str) and Path(value).is_file():
                return value
    return None


class RenderCritic:
    """The chosen critic, wired to the core's ``Critic`` seam.

    ``render_of`` resolves a ``(task, variant)`` pair to the frame to judge.
    It returns ``None`` when the variant has no frame — a deferred render,
    a failed attempt — and the score says so instead of guessing.
    """

    def __init__(
        self,
        critic: ReferenceCritic | None = None,
        *,
        render_of: Callable[[Any, Any], str | None] | None = None,
        classes: Sequence[str] | None = None,
    ) -> None:
        self._critic = critic or ScriptedReferenceCritic()
        self._render_of = render_of or (lambda task, variant: None)
        self._classes = tuple(classes) if classes is not None else None

    @property
    def critic(self) -> ReferenceCritic:
        """The critic that answers behind the seam."""
        return self._critic

    def score(self, task: Any, variant: Any) -> CriticScore:
        """Score one variant by looking at its frame."""
        path = self._render_of(task, variant)
        if not path:
            return CriticScore(
                score=0.0,
                reason=(
                    f"{self._critic.name}: no frame to judge for variant "
                    f"{getattr(variant, 'id', '?')}"
                ),
                degraded=True,
            )
        member = MemberRecipe(
            member_id=f"variant:{getattr(variant, 'id', '?')}",
            base_id=f"task:{getattr(task, 'id', '?')}",
            defect=None,
            layer="image",
            seed=0,
            recipe={"kind": "image", "source": "the variant's render"},
            derived_path=str(path),
        )
        verdict = self._critic.score(member)
        wanted = (
            set(self._classes)
            if self._classes is not None
            else set(DEFECT_TARGETS.values())
        )
        judged = [o for o in verdict.checks if o.check in wanted]
        fired = [o for o in judged if o.fired]
        score = (len(judged) - len(fired)) / len(judged) if judged else 0.0
        if fired:
            reason = (
                f"{self._critic.name}: "
                + ", ".join(f"{o.check} ({o.detail})" for o in fired)
            )
        else:
            reason = f"{self._critic.name}: every class the critic judges is clean"
        return CriticScore(
            score=score,
            reason=reason,
            degraded=verdict.degraded not in ("scripted", ""),
        )
