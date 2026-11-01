"""Clef-flash on Workers AI as a critic: the cloud delegate, with the image.

``@cf/cloudflare/clef-flash`` is a 9 B **multimodal decision model**: it reads
a state, a schema of typed questions and up to four images, and returns a
probability for every allowed option of every question. It does not generate
text, so the shape of the answer is the same as the local decision model's:
a ``noul`` question comes back as the probability that the answer is *yes*.

The call goes through a throwaway Worker under ``wrangler dev --remote``: the
Worker holds the AI binding, the inference happens at Cloudflare's edge, and
**nothing is deployed** (see ``docs/lab/critic-delegate-scripts/worker``).

Two things about the path are worth knowing, because both cost time if they
are rediscovered:

* **The edge wants a User-Agent.** A request without one is refused with
  Cloudflare's ``1010`` before it reaches the Worker, and the answer looks
  like a model failure when it is a blocked request. The candidate therefore
  sends a fixed one.
* **The image is the expensive part.** Clef tokenises an image in 32×32
  patches and caps it at 1 024 tokens, so the frame is resized by the edge
  before it is scored. The wall time of a call is therefore mostly the
  picture, and a text-only call is not a fair proxy for the latency of
  this candidate.
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
    "CLEF_CLASSES",
    "CLEF_DEFAULT_ENDPOINT",
    "CLEF_MODEL",
    "CLEF_GATE",
    "ClefCritic",
    "ask_clef",
]

#: The image classes a pixel delegate can be asked about.
CLEF_CLASSES: tuple[str, ...] = tuple(IMAGE_CLASSES)

#: The default endpoint — the throwaway Workers AI proxy on loopback.
CLEF_DEFAULT_ENDPOINT = "http://127.0.0.1:8797"

#: The hosted model.
CLEF_MODEL = "@cf/cloudflare/clef-flash"

#: The probability at which a ``noul`` answer counts as *yes``.
CLEF_GATE = 0.5

#: A fixed User-Agent. Cloudflare's edge refuses a request without one
#: (error 1010) before the Worker sees it, and a refused request looks like
#: a model failure when it is not one.
USER_AGENT = "builder-ide-critic/1.0"

#: The state that goes with the picture. Clef requires a state; the frame is
#: the subject, so the state says only that this is a rendered frame and adds
#: nothing the delegate could use to guess the class.
CLEF_STATE = "A rendered frame of a scene."


def _encode_image(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def ask_clef(
    endpoint: str,
    image_path: str | Path,
    questions: dict[str, str],
    *,
    model: str = CLEF_MODEL,
    state: str = CLEF_STATE,
    timeout: float = 120.0,
) -> tuple[dict[str, float], float, float, dict[str, Any]]:
    """Ask the cloud decision model about one picture.

    Returns the probability of *yes* per question, the wall time in seconds,
    the Worker's own time in milliseconds, and the usage the model reported.
    The Worker's time is the edge's inference; the wall time is the whole
    path, including the proxy hop.
    """
    payload = {
        "model": model,
        "input": {
            "model": "clef-flash",
            "state": state,
            "questions": {
                qid: {"type": "noul", "instructions": text}
                for qid, text in questions.items()
            },
            "images": [_encode_image(image_path)],
        },
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read())
    elapsed = time.perf_counter() - started
    worker_ms = float(body.get("ms") or 0.0)
    if body.get("error"):
        raise RuntimeError(f"the clef worker returned an error: {body['error']}")
    out = body.get("out") or {}
    answers = out.get("answers") or {}
    probabilities: dict[str, float] = {}
    for qid, answer in answers.items():
        value = answer.get("noul")
        if value is not None:
            probabilities[qid] = float(value)
    return probabilities, elapsed, worker_ms, out.get("usage", {}) or {}


class ClefCritic:
    """Clef-flash on Workers AI as a critic: one fixed yes/no question per class.

    The candidate talks to a Worker that holds the AI binding; the Worker is
    started outside the critic (it is a process with a session, not a library),
    and the endpoint is a parameter so any proxy that speaks the same shape
    can be swapped in.
    """

    name = "clef"
    layers = ("image",)

    def __init__(
        self,
        *,
        endpoint: str = CLEF_DEFAULT_ENDPOINT,
        model: str = CLEF_MODEL,
        classes: Sequence[str] = CLEF_CLASSES,
        gate: float = CLEF_GATE,
        timeout: float = 120.0,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
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
        probabilities, elapsed, worker_ms, usage = ask_clef(
            self._endpoint,
            member.derived_path,
            questions,
            model=self._model,
            timeout=self._timeout,
        )
        outcomes: list[CheckOutcome] = []
        for defect in self.classes:
            question = CLASS_QUESTIONS[defect]
            probability = probabilities.get(defect)
            if probability is None:
                outcomes.append(
                    CheckOutcome(
                        check=DEFECT_TARGETS[defect],
                        fired=False,
                        detail=(
                            f"clef-flash: {question!r} -> no answer "
                            f"({elapsed:.1f} s wall, {worker_ms:.0f} ms at the edge)"
                        ),
                        measured={"clef_seconds": elapsed},
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
                        f"clef-flash: {question!r} -> p(yes) = {probability:.3f} "
                        f"({elapsed:.1f} s wall, {worker_ms:.0f} ms at the edge, "
                        f"{usage.get('input_tokens', '?')} input tokens)"
                    ),
                    measured={
                        "clef_probability": probability,
                        "clef_seconds": elapsed,
                        "clef_worker_ms": worker_ms,
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
