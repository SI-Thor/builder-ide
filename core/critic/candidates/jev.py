"""Jev in the cloud as a critic: a typed judgement over a frame's evidence.

Jev (TypeSafe's System One model) answers **typed questions** with
probabilities, so a critic can be built from it without parsing prose: a
**Noul** per class ("is this frame's evidence consistent with a hole in it?")
and one **Choice** ("which class is this frame, or is it clean?").

What Jev sees is **not the picture**. It is a *text description of the frame*
plus the scripted checks' **measurements** — the numbers the checks read off
the pixels, without the thresholds and without the checks' verdicts. That is
the honest shape of a text-only critic, and it has a consequence the bake-off
has to state plainly: where a measurement already decides the class, Jev is
re-deciding the threshold in a slower and more expensive way. The arms are
therefore run twice —

* **with** the measurements (everything the critic knows), and
* **without** them (the description alone),

and the difference between the two arms is the price of the scripted
signals.

The API key is read from ``TYPESAFE_API_KEY`` — from the environment, or
from the last-mile secrets file. It is never printed, never logged and never
written to a result file.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..checks import DEFAULT_THRESHOLDS, Thresholds, run_image_checks
from ..critic import ReferenceCritic
from ..imaging import load_rgb
from ..models import DEFECT_TARGETS, IMAGE_DEFECTS, CheckOutcome, CriticVerdict
from ..set import MemberRecipe

__all__ = [
    "JEV_CLASSES",
    "JEV_QUESTIONS",
    "JevCritic",
    "read_api_key",
    "state_for",
]

#: The image classes Jev is asked about.
JEV_CLASSES: tuple[str, ...] = tuple(IMAGE_DEFECTS)

#: The fixed question per class — one Noul each, all in one request.
JEV_QUESTIONS: dict[str, str] = {
    "black_frame": (
        "Does this frame's evidence show a completely black picture with no "
        "visible scene?"
    ),
    "noise_fireflies": (
        "Does this frame's evidence show bright isolated speckles scattered "
        "over the picture, like dust or fireflies in a render?"
    ),
    "missing_object": (
        "Does this frame's evidence show a missing object — a flat, empty "
        "patch where something should be?"
    ),
    "holes": (
        "Does this frame's evidence show holes — dark empty gaps or pits in a "
        "surface?"
    ),
    "texture_swap": (
        "Does this frame's evidence show a rectangular block of texture that "
        "does not belong, as if a patch of the surface came from a different "
        "picture?"
    ),
    "floating_object": (
        "Does this frame's evidence show an object floating in mid-air, "
        "detached from the ground or hanging in empty space?"
    ),
}

#: The Choice question's options: every class, plus the clean answer. A
#: classifier that cannot say "none" cries wolf on clean frames.
JEV_CHOICE_OPTIONS: dict[str, str] = {
    "black_frame": "The picture is completely black, with no visible scene.",
    "noise_fireflies": "Bright isolated speckles are scattered over the picture.",
    "missing_object": "A prop is missing and left a flat, empty patch.",
    "holes": "There are dark empty gaps or pits in a surface.",
    "texture_swap": "A rectangular block of texture does not belong to the scene.",
    "floating_object": "An object floats in mid-air, detached from the ground.",
    "no_defect": "None of the above — the frame is clean.",
}

#: Where the API lives.
DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

#: The secrets file the last-mile keeps its keys in. The key is read from
#: it and never printed.
DEFAULT_SECRETS = Path.home() / ".config" / "last-mile" / "secrets.env"


def read_api_key(
    env_var: str = "TYPESAFE_API_KEY",
    secrets_file: str | Path = DEFAULT_SECRETS,
) -> str | None:
    """The API key, from the environment or from the secrets file.

    The key is returned, never logged: nothing in this module prints it, and
    nothing writes it into a result file.
    """
    key = os.environ.get(env_var)
    if key:
        return key.strip()
    path = Path(secrets_file)
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == env_var:
            return value.strip().strip('"').strip("'")
    return None


def state_for(
    member: MemberRecipe,
    *,
    description: str | None,
    measurements: Mapping[str, Mapping[str, float]] | None,
    thresholds: Thresholds,
) -> dict[str, Any]:
    """The state Jev is asked about: what the frame looks like and what the
    scripted checks measured on it.

    The **thresholds are not sent**. Jev gets the measurements and the
    description, not the answer key: sending the thresholds would turn the
    judge into a re-implementation of the checks, and the point of the
    comparison would be gone.
    """
    state: dict[str, Any] = {
        "frame": description or "(no description of this frame was available)",
    }
    if measurements:
        state["measurements"] = {
            check: {k: float(v) for k, v in values.items()}
            for check, values in measurements.items()
            if values
        }
    return state


class JevCritic:
    """Jev as a critic, over a description of the frame and its measurements.

    ``arm`` is which of Jev's two question types decides the verdict:

    * ``"verify"`` — the Noul per class: the class fires when the
      probability of "yes" is at least ``threshold``;
    * ``"classify"`` — the Choice: the class fires when it is the option Jev
      picked.

    ``measurements`` turns the scripted signals on or off, which is the
    difference between the two arms of the bake-off.
    """

    name = "jev"
    layers = ("image",)

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = "jev-latest",
        api_key: str | None = None,
        arm: str = "verify",
        threshold: float = 0.5,
        measurements: bool = True,
        classes: Sequence[str] = JEV_CLASSES,
        descriptions: Mapping[str, str] | None = None,
        captioner: Callable[[MemberRecipe], str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        if arm not in ("verify", "classify"):
            raise ValueError(f"unknown arm {arm!r}; use 'verify' or 'classify'")
        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key or read_api_key()
        self._arm = arm
        self._threshold = threshold
        self._measurements = measurements
        self._classes = tuple(classes)
        self._descriptions = dict(descriptions or {})
        self._captioner = captioner
        self._timeout = timeout

    @property
    def arm(self) -> str:
        return self._arm

    def _description(self, member: MemberRecipe) -> str | None:
        text = self._descriptions.get(member.member_id)
        if text:
            return text
        if self._captioner is not None:
            return self._captioner(member)
        return None

    def _measurements_for(
        self,
        member: MemberRecipe,
        thresholds: Thresholds,
    ) -> dict[str, dict[str, float]]:
        if not self._measurements:
            return {}
        if not member.derived_path:
            return {}
        image = load_rgb(member.derived_path)
        outcomes = run_image_checks(image, thresholds)
        return {o.check: dict(o.measured) for o in outcomes if o.measured}

    def _ask(self, state: dict[str, Any]) -> tuple[dict[str, Any], float]:
        if not self._api_key:
            raise RuntimeError(
                "no TYPESAFE_API_KEY: Jev is a cloud critic and needs the key"
            )
        questions: dict[str, Any] = {
            f"verify_{defect}": {
                "type": "noul",
                "instructions": JEV_QUESTIONS[defect],
            }
            for defect in self._classes
        }
        questions["classify"] = {
            "type": "choice",
            "instructions": (
                "Which defect class does this frame have? If the frame is "
                "clean, choose no_defect."
            ),
            "criteria": dict(JEV_CHOICE_OPTIONS),
        }
        body = {"model": self._model, "state": state, "questions": questions}
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            payload = json.loads(response.read())
        return payload, time.perf_counter() - started

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
        blender_python: str | None = None,
    ) -> CriticVerdict:
        """Jev's judgement of one frame."""
        t = thresholds or DEFAULT_THRESHOLDS
        measurements = self._measurements_for(member, t)
        state = state_for(
            member,
            description=self._description(member),
            measurements=measurements,
            thresholds=t,
        )
        payload, elapsed = self._ask(state)
        answers = payload.get("answers", {})

        choice = answers.get("classify", {})
        picked = choice.get("choice") or choice.get("selected") or ""

        outcomes: list[CheckOutcome] = []
        for defect in self._classes:
            key = f"verify_{defect}"
            answer = answers.get(key, {})
            probability = float(answer.get("noul", 0.0))
            if self._arm == "verify":
                fired = probability >= self._threshold
                because = f"noul={probability:.3f} >= {self._threshold}"
            else:
                fired = picked == defect
                because = f"choice={picked!r}"
            outcomes.append(
                CheckOutcome(
                    check=DEFECT_TARGETS[defect],
                    fired=fired,
                    detail=(
                        f"jev {self._arm}: {JEV_QUESTIONS[defect]} -> {because} "
                        f"(confidence {answer.get('confidence', '—')}, "
                        f"{elapsed:.2f} s, {payload.get('model', '?')})"
                    ),
                    measured={"jev_noul": probability, "jev_seconds": elapsed},
                )
            )
        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=tuple(outcomes),
            label=f"verdict@{self.name}",
            degraded=self.name,
            layer=member.layer,
        )
