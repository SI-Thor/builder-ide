"""d1-2B as a critic: a local decision model that can **see** the frame.

The model is the Thor's own copy of **d1-2B** (LFM3 architecture — a *decision*
model, not a text model) together with its **mmproj**, the multimodal
projector that gives it an eye. llama.cpp serves the pair on loopback and
answers typed questions over ``POST /v1/systemone``: a ``noul`` question
returns the probability that the answer is *yes*.

Three things make it a fair candidate rather than a toy:

* **The question is fixed.** Every frame of every class is asked the same
  words (see :mod:`core.critic.candidates.questions`), so the candidate
  cannot be tuned per member and the numbers are comparable with the other
  delegates'.
* **The model sees the picture and nothing else.** No scripted
  measurements, no thresholds, no hints about which class is planted. It is
  a *pixel* critic: whatever it gets right, it got from the frame.
* **It is local.** The verdict costs no money and no network, and the weights
  are already on the box. The image is encoded **once** per frame and the
  whole question set is scored in the same pass, which is what a decision
  model is for.

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
from ..models import DEFECT_TARGETS, CheckOutcome, CriticVerdict
from ..set import MemberRecipe
from .questions import CLASS_QUESTIONS, IMAGE_CLASSES

__all__ = [
    "D1_CLASSES",
    "D1_DEFAULT_ENDPOINT",
    "D1_MODEL",
    "D1_GATE",
    "D1Critic",
    "ask_d1",
]

#: The image classes a pixel delegate can be asked about.
D1_CLASSES: tuple[str, ...] = tuple(IMAGE_CLASSES)

#: The default endpoint — the loopback llama.cpp server that carries the
#: decision model and its projector.
D1_DEFAULT_ENDPOINT = "http://127.0.0.1:8131"

#: The model the server is asked for. It is only a label in the request: the
#: weights are the ones the resident server loaded.
D1_MODEL = "d1-2B"

#: The probability at which a ``noul`` answer counts as *yes*. The answer is
#: a probability, so the gate is a line and the distance from it is in the
#: verdict: a delegate that answered 0.51 is not the same as one that
#: answered 0.99, and the table should be able to tell them apart.
D1_GATE = 0.5


def _encode_image(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def ask_d1(
    endpoint: str,
    image_path: str | Path,
    questions: dict[str, str],
    *,
    timeout: float = 120.0,
) -> tuple[dict[str, float], float, dict[str, Any]]:
    """Ask the decision model about one picture.

    Returns the probability of *yes* per question, the wall time in seconds,
    and the usage the server reported. The image goes in as ``images`` and the
    state is ``null``: the model is asked about the picture alone, which is
    what the endpoint allows for this model family.
    """
    body = {
        "state": None,
        "images": [_encode_image(image_path)],
        "questions": {
            qid: {"type": "noul", "instructions": text}
            for qid, text in questions.items()
        },
    }
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/systemone",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    elapsed = time.perf_counter() - started
    answers = payload.get("answers") or {}
    probabilities: dict[str, float] = {}
    for qid, answer in answers.items():
        value = answer.get("noul")
        if value is not None:
            probabilities[qid] = float(value)
    return probabilities, elapsed, payload.get("usage", {}) or {}


class D1Critic:
    """The local decision model as a critic: one fixed yes/no question per class.

    The model is loaded by a server that is **not** started here — the
    candidate talks to a System One endpoint, which is how llama.cpp serves a
    decision model, and any other server that speaks it can be swapped in
    without touching the critic.
    """

    name = "d1"
    layers = ("image",)

    def __init__(
        self,
        *,
        endpoint: str = D1_DEFAULT_ENDPOINT,
        model: str = D1_MODEL,
        classes: Sequence[str] = D1_CLASSES,
        gate: float = D1_GATE,
        timeout: float = 120.0,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        #: The classes this critic asks about. The hybrid narrows it to the
        #: classes it actually needs an answer for: asking a model about five
        #: classes whose answers are thrown away costs five times the price
        #: for nothing.
        self.classes = tuple(classes)
        self._gate = float(gate)
        self._timeout = timeout

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def gate(self) -> float:
        return self._gate

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
        questions = {defect: CLASS_QUESTIONS[defect] for defect in self.classes}
        probabilities, elapsed, usage = ask_d1(
            self._endpoint,
            member.derived_path,
            questions,
            timeout=self._timeout,
        )
        outcomes: list[CheckOutcome] = []
        for defect in self.classes:
            question = CLASS_QUESTIONS[defect]
            probability = probabilities.get(defect)
            if probability is None:
                # The model did not answer this question. That is a miss, and
                # the verdict says so rather than counting a silence as a no.
                outcomes.append(
                    CheckOutcome(
                        check=DEFECT_TARGETS[defect],
                        fired=False,
                        detail=(
                            f"{self._model}: {question!r} -> no answer "
                            f"({elapsed:.1f} s for the whole frame)"
                        ),
                        measured={"d1_seconds": elapsed},
                        applicable=False,
                    )
                )
                continue
            fired = probability >= self._gate
            outcomes.append(
                CheckOutcome(
                    check=DEFECT_TARGETS[defect],
                    fired=fired,
                    detail=(
                        f"{self._model}: {question!r} -> p(yes) = {probability:.3f} "
                        f"({elapsed:.1f} s for the whole frame, "
                        f"{usage.get('input_tokens', '?')} input tokens)"
                    ),
                    measured={
                        "d1_probability": probability,
                        "d1_seconds": elapsed,
                    },
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
