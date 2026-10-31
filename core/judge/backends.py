"""The four backends, and the one wire they share.

All four speak the same canonical shape the liquid-study scripts used
against llama-server: a **state** plus a schema of typed **questions**,
back a probability for every allowed answer. The only real differences
are the endpoint, the model id and the auth header — which is why the
brief's "each backend is a parameter with a default" is literally a
constructor argument of :class:`core.judge.judge.Judge`.

===============  ==========================================================
backend          what it is, and what it costs
===============  ==========================================================
:class:`FakeBackend`        deterministic; scripted answers for tests
:class:`D1Backend`          llama-server's ``/v1/systemone`` (the local d1
                            decision models); GPU time, no cents
:class:`JevBackend`         TypeSafe's Jev over its System One HTTP
                            provider; the key comes from the environment
                            (``JEV_API_KEY``, or ``TYPESAFE_API_KEY``) and is
                            never printed
:class:`ClefBackend`        Cloudflare Clef on Workers AI, in the
                            ``{"model", "input"}`` envelope the prior PoC's
                            Worker took; priced from the published neuron
                            rates. Nothing here deploys anything.
===============  ==========================================================

Failures are :class:`JudgeRefusal` with a closed reason code, because a
backend that cannot be reached is exactly the case the escalation
ladder exists for — the caller needs to branch on *why*, not catch a
bare ``URLError``.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .models import JudgeCost, Question

__all__ = [
    "JudgeRefusal",
    "BackendReply",
    "JudgeBackend",
    "FakeBackend",
    "D1Backend",
    "JevBackend",
    "ClefBackend",
]


class JudgeRefusal(Exception):
    """A backend that cannot answer, with the reason it cannot.

    ``code`` is what the caller branches on (``transport_error``,
    ``http_error``, ``key_missing``, ``bad_reply``); the detail is for
    the log and never carries a key.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class BackendReply:
    """One backend's raw answers to one pack, before any policy.

    Distributions are keyed by question id, then by the question's own
    option keys — the caller completes and normalises them against the
    questions (a backend that omits an option gets it at 0.0).
    """

    backend: str
    model: str
    distributions: dict[str, dict[str, float]]
    confidences: dict[str, float | None]
    input_tokens: int = 0
    wall_seconds: float = 0.0

    @property
    def author(self) -> str:
        return f"judge@{self.backend}:{self.model}"


@runtime_checkable
class JudgeBackend(Protocol):
    """The seam every backend implements. Each is a parameter with a default."""

    name: str
    model: str

    def ask(self, state: str, questions: Sequence[Question]) -> BackendReply: ...

    def cost_of(self, reply: BackendReply) -> JudgeCost: ...


# --- the shared HTTP plumbing -------------------------------------------------


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict[str, Any], float]:
    """POST one JSON payload; return (status, body, wall seconds)."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body, time.perf_counter() - started
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")[:400]
        try:
            body: dict[str, Any] = json.loads(raw)
        except ValueError:
            body = {"error": raw}
        return error.code, body, time.perf_counter() - started
    except Exception as error:  # transport: refused, timed out, no route
        raise JudgeRefusal(
            "transport_error", f"{url} gave {type(error).__name__}: {error}"
        ) from error


def _wire_questions(questions: Sequence[Question]) -> dict[str, dict[str, Any]]:
    return {question.qid: question.to_wire() for question in questions}


def _parse_answers(
    raw_answers: Mapping[str, Any], questions: Sequence[Question]
) -> tuple[dict[str, dict[str, float]], dict[str, float | None]]:
    """Normalise a System One ``answers`` object against the questions.

    Two spellings are accepted (the Jev provider's and llama-server's):
    a choice/score answers under ``probabilities`` (or ``p``), a noul
    answers its probability under ``noul`` (or ``p``/``probability``)
    and is read as P(true).
    """
    distributions: dict[str, dict[str, float]] = {}
    confidences: dict[str, float | None] = {}
    for question in questions:
        raw = raw_answers.get(question.qid)
        if raw is None:
            raise JudgeRefusal(
                "bad_reply", f"the backend answered no question named {question.qid!r}"
            )
        probabilities = raw.get("probabilities") or raw.get("p")
        if probabilities is None:
            probability = raw.get("noul", raw.get("probability"))
            if probability is not None:
                probabilities = {"false": 1.0 - float(probability), "true": float(probability)}
        if not isinstance(probabilities, dict) or not probabilities:
            raise JudgeRefusal(
                "bad_reply", f"the backend answered {question.qid!r} with no probabilities"
            )
        distributions[question.qid] = {
            str(key): float(value) for key, value in probabilities.items()
        }
        raw_confidence = raw.get("confidence")
        confidences[question.qid] = None if raw_confidence is None else float(raw_confidence)
    return distributions, confidences


# --- the fake -----------------------------------------------------------------


class FakeBackend:
    """A deterministic stand-in for tests — no network, no GPU, no key.

    A scripted ``{qid: distribution}`` wins where it names a question;
    everything else is answered from a hash of the state and the
    question, so the same call always answers the same and different
    states answer differently. Its confidence is the top probability —
    the same monotone-in-the-margin shape the real heads report.
    """

    name = "fake"
    model = "fake/scripted-v1"

    def __init__(self, script: Mapping[str, Mapping[str, float]] | None = None) -> None:
        self.script = {qid: dict(row) for qid, row in (script or {}).items()}

    def __repr__(self) -> str:
        return f"FakeBackend(scripted={sorted(self.script)})"

    def ask(self, state: str, questions: Sequence[Question]) -> BackendReply:
        started = time.perf_counter()
        distributions: dict[str, dict[str, float]] = {}
        confidences: dict[str, float | None] = {}
        for question in questions:
            scripted = self.script.get(question.qid)
            if scripted is not None:
                vector = {key: float(scripted.get(key, 0.0)) for key in question.option_keys}
                total = sum(vector.values())
                if total <= 0:
                    raise JudgeRefusal(
                        "bad_reply",
                        f"the script for {question.qid!r} puts no probability on any option",
                    )
                distributions[question.qid] = {key: value / total for key, value in vector.items()}
            else:
                distributions[question.qid] = self._hash_distribution(state, question)
            top = max(distributions[question.qid].values())
            confidences[question.qid] = top
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=0,
            wall_seconds=time.perf_counter() - started,
        )

    def cost_of(self, reply: BackendReply) -> JudgeCost:
        return JudgeCost(wall_seconds=reply.wall_seconds, input_tokens=0)

    def _hash_distribution(self, state: str, question: Question) -> dict[str, float]:
        keys = question.option_keys
        seed = f"{state}|{json.dumps(question.to_wire_record(), sort_keys=True)}"
        rng = random.Random(seed)
        weights = [0.001 + rng.random() for _ in keys]
        total = sum(weights)
        return {key: weight / total for key, weight in zip(keys, weights)}


# --- the local d1 backend -----------------------------------------------------


class D1Backend:
    """llama-server's ``/v1/systemone`` — the local d1 decision models.

    The exact call ``docs/research/liquid-study-scripts/`` makes, on
    whatever port the caller configures. The server is the caller's to
    start and stop (under the heavy lock; one server at a time); this
    backend only speaks to it. Cost is GPU time and no cents.
    """

    name = "d1"

    def __init__(
        self,
        *,
        port: int | None = None,
        url: str | None = None,
        model: str = "d1-2B",
        timeout: float = 120.0,
    ) -> None:
        if (port is None) == (url is None):
            raise ValueError("configure exactly one of port or url")
        self.url = url or f"http://127.0.0.1:{port}"
        self.model = model
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"D1Backend({self.url}, model={self.model!r})"

    def ask(self, state: str, questions: Sequence[Question]) -> BackendReply:
        payload = {"state": state, "questions": _wire_questions(questions)}
        status, body, wall = _post_json(
            self.url.rstrip("/") + "/v1/systemone", payload, timeout=self.timeout
        )
        if status != 200:
            raise JudgeRefusal("http_error", f"/v1/systemone returned {status}: {body}")
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, dict):
            raise JudgeRefusal("bad_reply", f"/v1/systemone returned no answers: {body}")
        distributions, confidences = _parse_answers(raw_answers, questions)
        usage = body.get("usage") or {}
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            wall_seconds=wall,
        )

    def cost_of(self, reply: BackendReply) -> JudgeCost:
        return JudgeCost(
            wall_seconds=reply.wall_seconds,
            input_tokens=reply.input_tokens,
            gpu_minutes=reply.wall_seconds / 60.0,
        )


# --- the TypeSafe Jev backend -------------------------------------------------


class JevBackend:
    """TypeSafe's Jev over its System One HTTP provider.

    The key comes from the environment — ``JEV_API_KEY``, or the
    established ``TYPESAFE_API_KEY`` — and is never printed: not in a
    repr, not in an error, not in a refusal. Jev's price per call is not
    published, so the cost records the input tokens and admits the price
    is unknown; it is recomputable when a price is known.
    """

    name = "jev"

    def __init__(
        self,
        *,
        url: str = "https://api.typesafe.ai/v1/systemone",
        model: str = "jev-latest",
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.url = url
        self.model = model
        self._explicit_key = api_key
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"JevBackend({self.url}, model={self.model!r})"

    def _key(self) -> str:
        key = self._explicit_key or os.environ.get("JEV_API_KEY") or os.environ.get(
            "TYPESAFE_API_KEY"
        )
        if not key:
            raise JudgeRefusal(
                "key_missing",
                "no Jev key: set JEV_API_KEY (or TYPESAFE_API_KEY) in the environment",
            )
        return key

    def ask(self, state: str, questions: Sequence[Question]) -> BackendReply:
        key = self._key()
        payload: dict[str, Any] = {
            "state": state,
            "questions": _wire_questions(questions),
            "model": self.model,
        }
        status, body, wall = _post_json(
            self.url,
            payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=self.timeout,
        )
        if status != 200:
            raise JudgeRefusal("http_error", f"jev returned {status}: {body}")
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, dict):
            raise JudgeRefusal("bad_reply", f"jev returned no answers: {body}")
        distributions, confidences = _parse_answers(raw_answers, questions)
        usage = body.get("usage") or {}
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            wall_seconds=wall,
        )

    def cost_of(self, reply: BackendReply) -> JudgeCost:
        return JudgeCost(
            wall_seconds=reply.wall_seconds,
            input_tokens=reply.input_tokens,
            hosted_cents=0.0,
            cost_known=False,
        )


# --- the Cloudflare Clef backend ----------------------------------------------


#: Workers AI's published neuron rates (neurons per million input tokens)
#: and the neuron price ($0.011 per 1,000 neurons). Clef models are not
#: charged for output tokens.
NEURONS_PER_M_INPUT_TOKENS: dict[str, float] = {
    "@cf/cloudflare/clef-flash": 3455.0,
    "@cf/cloudflare/clef": 21818.0,
    "@cf/cloudflare/clef-omni": 13636.0,
}
NEURON_USD_PER_1000 = 0.011


class ClefBackend:
    """Cloudflare Clef on Workers AI, in the prior PoC's envelope.

    The request is ``{"model": ..., "input": {"state", "questions"}}`` —
    the shape ``clef-cascade/prior-poc/worker-index.js`` took — so the
    endpoint may be a ``wrangler dev`` proxy holding the AI binding (no
    key on this side) or a deployed Worker (an optional bearer key from
    ``CLEF_API_KEY``). Nothing here deploys anything; the endpoint is
    the caller's. Jev-compatible request shape: the same typed
    questions inside the envelope.
    """

    name = "clef"

    def __init__(
        self,
        *,
        url: str,
        model: str = "@cf/cloudflare/clef-flash",
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.url = url
        self.model = model
        self._explicit_key = api_key
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"ClefBackend({self.url}, model={self.model!r})"

    def _headers(self) -> dict[str, str]:
        key = self._explicit_key or os.environ.get("CLEF_API_KEY")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def ask(self, state: str, questions: Sequence[Question]) -> BackendReply:
        payload = {
            "model": self.model,
            "input": {"state": state, "questions": _wire_questions(questions)},
        }
        status, body, wall = _post_json(
            self.url, payload, headers=self._headers(), timeout=self.timeout
        )
        if status != 200:
            raise JudgeRefusal("http_error", f"clef returned {status}: {body}")
        out = body.get("out", body)
        if not isinstance(out, dict):
            raise JudgeRefusal("bad_reply", f"clef returned no answers: {body}")
        raw_answers = out.get("answers")
        if not isinstance(raw_answers, dict):
            raise JudgeRefusal("bad_reply", f"clef returned no answers: {out}")
        distributions, confidences = _parse_answers(raw_answers, questions)
        usage = out.get("usage") or {}
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            wall_seconds=wall,
        )

    def cost_of(self, reply: BackendReply) -> JudgeCost:
        rate = NEURONS_PER_M_INPUT_TOKENS.get(self.model)
        if rate is None:
            return JudgeCost(
                wall_seconds=reply.wall_seconds,
                input_tokens=reply.input_tokens,
                cost_known=False,
            )
        neurons = reply.input_tokens * rate / 1_000_000.0
        return JudgeCost(
            wall_seconds=reply.wall_seconds,
            input_tokens=reply.input_tokens,
            hosted_cents=neurons / 1000.0 * NEURON_USD_PER_1000,
        )
