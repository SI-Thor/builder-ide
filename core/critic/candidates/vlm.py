"""A local vision-language model as a critic: one fixed yes/no question per class.

The model is served by llama.cpp on loopback and is asked the *same* question
for every frame — one yes/no question per defect class — and its answer is
the verdict. The questions live in
:mod:`core.critic.candidates.questions`, because the decision-model
delegates ask the same words.

**There is no default model.** The candidate used to default to the Thor's
copy of **Muse Glimmer 30B**, and that default is gone: a 30 B model is a
large resident load on a box the project shares, and the rule (B2) is that
no language model runs on the Thor. A caller that wants this candidate must
say which model it is talking to, so the weights are a decision on the
caller's side rather than a hidden default.

Three things make it a fair candidate rather than a toy:

* **The question is fixed.** Every frame of every class gets the same words,
  so the candidate cannot be tuned per member, and the numbers are
  comparable across classes.
* **The model sees the picture and nothing else.** No scripted
  measurements, no thresholds, no hints about which class is planted. It is
  a *pixel* critic: whatever it gets right, it got from the image.
* **It is local.** The verdict costs no money and no network.

The class it is most likely to be *asked* about is the one the scripted
checks miss — ``floating_object`` — because that is the class the checks
are out of band on.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from ..checks import Thresholds
from ..critic import ReferenceCritic
from ..models import DEFECT_TARGETS, IMAGE_DEFECTS, CheckOutcome, CriticVerdict
from ..set import MemberRecipe
from .questions import CLASS_QUESTIONS

__all__ = ["VLM_CLASSES", "VLM_QUESTIONS", "VLMCritic", "ask_vlm"]


#: The image classes a pixel critic can be asked about. The mesh classes
#: live in the geometry, and the reference set never re-renders a mesh
#: defect, so there is no picture of them to look at.
VLM_CLASSES: tuple[str, ...] = tuple(IMAGE_DEFECTS)

#: The fixed question per class, shared with the decision-model delegates.
VLM_QUESTIONS: dict[str, str] = dict(CLASS_QUESTIONS)

#: The default endpoint — the loopback llama.cpp server.
DEFAULT_ENDPOINT = "http://127.0.0.1:8123/v1"


def _encode_image(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def ask_vlm(
    endpoint: str,
    image_path: str | Path,
    question: str,
    *,
    model: str,
    timeout: float = 300.0,
    max_tokens: int = 512,
) -> tuple[str, float, dict[str, Any]]:
    """Ask the model one question about one picture.

    Returns the answer, the wall time in seconds, and the usage the server
    reported. The server is asked for a *greedy* answer (temperature 0), so
    the same picture and the same words give the same verdict twice.
    """
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": _encode_image(image_path)}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "top_p": 1.0,
        "chat_template_kwargs": {"reasoning_strength": "low"},
    }
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    elapsed = time.perf_counter() - started
    message = payload["choices"][0]["message"]
    answer = (message.get("content") or "").strip()
    return answer, elapsed, payload.get("usage", {})


def _is_yes(answer: str) -> bool:
    """Did the model say yes?

    The answers are one word ("Yes", "No", "Yes — the picture is black").
    Anything that does not start with yes is a **no**: a critic that
    guesses "maybe" must not be read as a detection.
    """
    text = answer.strip().lower()
    if not text:
        return False
    if text.startswith("yes"):
        return True
    if text.startswith("no"):
        return False
    # A longer answer: look for the first yes/no word.
    for word in text.replace(",", " ").replace(".", " ").split():
        if word in ("yes", "no"):
            return word == "yes"
    return False


class VLMCritic:
    """The local VLM as a critic: one fixed yes/no question per class.

    The model is loaded by a server that is **not** started here — the
    candidate talks to an OpenAI-compatible endpoint, which is how the
    llama.cpp server, and any other server, can be swapped without touching
    the critic.
    """

    name = "vlm"
    layers = ("image",)

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str,
        classes: Sequence[str] = VLM_CLASSES,
        timeout: float = 300.0,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        #: The classes this critic asks about. The hybrid narrows it to the
        #: classes it actually needs an answer for: asking a 30 B model about
        #: five classes whose answers are thrown away costs five times the
        #: price for nothing.
        self.classes = tuple(classes)
        self._timeout = timeout

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
        blender_python: str | None = None,
    ) -> CriticVerdict:
        """The model's answers about one frame, one question per class."""
        if not member.derived_path:
            raise ValueError(f"member {member.member_id!r} has no derived image")
        outcomes: list[CheckOutcome] = []
        total = 0.0
        for defect in self.classes:
            question = VLM_QUESTIONS[defect]
            answer, elapsed, usage = ask_vlm(
                self._endpoint,
                member.derived_path,
                question,
                model=self._model,
                timeout=self._timeout,
            )
            total += elapsed
            fired = _is_yes(answer)
            outcomes.append(
                CheckOutcome(
                    check=DEFECT_TARGETS[defect],
                    fired=fired,
                    detail=(
                        f"{self._model}: {question!r} -> {answer!r} "
                        f"({elapsed:.1f} s, {usage.get('completion_tokens', '?')} tokens)"
                    ),
                    measured={"vlm_seconds": elapsed},
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
