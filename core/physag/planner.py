"""The planner seam: where the cloud model's spec comes from, and is repaired.

The brief's rule is that the plan is written by a **cloud** model and that
no language model runs on the Thor (CLAUDE.md, "No LLMs on the Thor"). The
planner is therefore a separate thing from everything else in this package:
it is the only piece that speaks to a language model, and it hands over a
typed :class:`~core.physag.spec.InteractionSpec` and nothing else.

Two implementations live here.

:class:`FixturePlanner` reads the plan from a directory of recorded specs.
That is how the experiment runs: the cloud model's plans are committed as
data, so the loop is reproducible without a model in the loop, and the
repair round is a *recorded* continuation — the revised spec, and the diff
against the one it replaces.

:class:`CloudApiPlanner` calls a cloud provider over HTTP. It is the
production shape, and it is the seam another seat can plug into: it takes
the same prompt the fixture planner's records were written from.

The repair round has one rule that the code enforces rather than the prompt
asking for: **the action and the joint limits are frozen**. A repair may
change the priors and the segmentation; it may not change what the prop is
asked to do, or the completion rate stops measuring the props.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.physag.spec import (
    InteractionSpec,
    SpecError,
    load_spec,
    repair_is_allowed,
    save_spec,
    spec_diff,
)

__all__ = [
    "CloudApiPlanner",
    "FixturePlanner",
    "Planner",
    "RepairFeedback",
    "repair_allowed",
]


@dataclass(frozen=True)
class RepairFeedback:
    """What the planner is told about the run that failed.

    It is the measurements and the render — never a change of the action.
    """

    prop: str
    interaction_status: str
    physics_status: str
    measurements: dict[str, Any]
    render_path: str | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "prop": self.prop,
            "interaction_status": self.interaction_status,
            "physics_status": self.physics_status,
            "measurements": self.measurements,
            "render": self.render_path,
            "notes": list(self.notes),
        }


class Planner(Protocol):
    """What the loop needs from a planner."""

    def plan(self, prop: str, kind: str) -> InteractionSpec:
        """The plan for a prop."""

    def repair(
        self, spec: InteractionSpec, feedback: RepairFeedback
    ) -> InteractionSpec | None:
        """A revised plan, or ``None`` when there is nothing to revise."""


class FixturePlanner:
    """A planner whose plans are recorded files.

    ``directory`` holds one ``<prop>.json`` per plan. A repair is recorded
    as ``<prop>.repair.json``; when it is absent the planner declines to
    repair, which is the honest answer for a prop with nothing to change.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def plan(self, prop: str, kind: str) -> InteractionSpec:
        path = self.directory / f"{prop}.json"
        if not path.exists():
            raise SpecError(f"{path}: no recorded plan for {prop!r}")
        spec = load_spec(path)
        if spec.prop != prop:
            raise SpecError(f"{path}: the spec is for {spec.prop!r}, not {prop!r}")
        return spec

    def repair(
        self, spec: InteractionSpec, feedback: RepairFeedback
    ) -> InteractionSpec | None:
        path = self.directory / f"{spec.prop}.repair.json"
        if not path.exists():
            return None
        repaired = load_spec(path)
        allowed, moved = repair_is_allowed(spec, repaired)
        if not allowed:
            # The recorded repair changed the action or the limits. It is
            # kept, and it is reported, but the prop does not count
            # towards the completion rate.
            repaired = repaired.with_planner(repair_changed_frozen_fields=",".join(moved))
        return repaired

    def save_plan(self, spec: InteractionSpec) -> Path:
        """Write a plan into the fixture directory."""
        return save_spec(spec, self.directory / f"{spec.prop}.json")

    def save_repair(self, spec: InteractionSpec) -> Path:
        """Write a repair into the fixture directory."""
        return save_spec(spec, self.directory / f"{spec.prop}.repair.json")


class CloudApiPlanner:
    """A planner that calls a cloud model over HTTP.

    The command is a template: the prompt is written to a temporary file
    and the path is substituted into the command, so the caller controls
    which provider and which model are used, and the whole call is one
    process that can be run under the box's memory rule.

    The model's answer is a JSON spec. A spec that does not validate is
    refused, and the refusal is the error the planner's own repair round
    would get.
    """

    def __init__(
        self,
        command: list[str],
        *,
        prompt_template: str,
        timeout_s: float = 300.0,
    ) -> None:
        self.command = list(command)
        self.prompt_template = prompt_template
        self.timeout_s = timeout_s

    def _call(self, prompt: str) -> str:
        with _temp_prompt(prompt) as path:
            command = [part.replace("{prompt}", str(path)) for part in self.command]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        if result.returncode != 0:
            raise SpecError(
                f"the planner failed (exit {result.returncode}): "
                f"{result.stderr.strip()[:500]}"
            )
        return result.stdout

    def plan(self, prop: str, kind: str) -> InteractionSpec:
        prompt = self.prompt_template.format(prop=prop, kind=kind)
        raw = self._call(prompt)
        return self._parse(raw)

    def repair(
        self, spec: InteractionSpec, feedback: RepairFeedback
    ) -> InteractionSpec | None:
        prompt = (
            self.prompt_template.format(prop=spec.prop, kind=spec.kind)
            + "\n\nRevise this spec so that the action completes and the prop "
            "stays stable. The action and the joint limits are frozen: you "
            "may change the priors and the segmentation only.\n\n"
            + json.dumps(spec.to_dict(), indent=2)
            + "\n\nWhat the check measured:\n"
            + json.dumps(feedback.to_dict(), indent=2)
        )
        raw = self._call(prompt)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> InteractionSpec:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise SpecError("the planner's answer holds no JSON object")
        data = json.loads(text[start : end + 1])
        return InteractionSpec.from_dict(data)


class _temp_prompt:
    """A temporary file holding the prompt, for the command to read."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.path: Path | None = None

    def __enter__(self) -> Path:
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".prompt.txt", delete=False, encoding="utf-8"
        )
        handle.write(self.text)
        handle.close()
        self.path = Path(handle.name)
        return self.path

    def __exit__(self, *exc: object) -> None:
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass


def repair_allowed(before: InteractionSpec, after: InteractionSpec) -> tuple[bool, list[str]]:
    """Whether a repaired spec keeps the action and the limits frozen."""
    return repair_is_allowed(before, after)


def diff_of(before: InteractionSpec, after: InteractionSpec) -> dict[str, Any]:
    """The field-by-field diff between two specs."""
    return spec_diff(before, after)
