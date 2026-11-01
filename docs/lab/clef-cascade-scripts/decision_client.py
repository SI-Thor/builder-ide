"""One decision-model client for Jev and Clef.

Three backends, one canonical answer shape:

  clef-ai    Cloudflare Workers AI (Clef-flash 9B / Clef 27B), reached through a
             local `wrangler dev --remote` proxy so no API key lives here.
  clef-local the same Clef-flash weights served by llama.cpp's /v1/systemone
             endpoint (the Thor's :8096 style).
  jev        TypeSafe's Jev, System One API, Bearer auth, key read from
             ~/.config/last-mile/secrets.env and never printed.

The wire format is the same for all three: a state plus a schema of typed
questions, and back a probability for every allowed answer.  The only real
differences are the endpoint, the model id, and the auth header -- which is
exactly why one client can serve the whole cascade.

Canonical question shape (accepted by every backend here):

    {"type": "noul",   "instructions": "<what must be true>"}
    {"type": "choice", "instructions": "<which one>", "criteria": {opt: text}}

Canonical answer shape (what this module returns):

    {"<qid>": {"type": "noul",   "p": 0.93, "answer": True,  "confidence": None}}
    {"<qid>": {"type": "choice", "p": {"a": .7, "b": .3}, "answer": "a",
               "confidence": 0.4}}

Two older Jev spellings are accepted on input and translated:
`{"type": "boolean", "description": ...}` -> noul, and
`{"type": "choice", "options": [...], "description": ...}` -> choice/criteria.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence

# --------------------------------------------------------------------------
# Workers AI neuron rates (developers.cloudflare.com/workers-ai/platform/pricing/)
# "$0.011 per 1,000 Neurons"; neurons per million input tokens:
#   clef-flash $0.038/M -> 3455 neurons/M ; clef $0.240/M -> 21818 neurons/M
# --------------------------------------------------------------------------
NEURONS_PER_M_INPUT_TOKENS: dict[str, float] = {
    "@cf/cloudflare/clef-flash": 3455.0,
    "@cf/cloudflare/clef": 21818.0,
    "@cf/cloudflare/clef-omni": 13636.0,
}
NEURON_USD_PER_1000 = 0.011
FREE_NEURONS_PER_DAY = 10_000

MODELS: dict[str, str] = {
    "flash": "@cf/cloudflare/clef-flash",
    "clef27": "@cf/cloudflare/clef",
}


def neurons_for(model: str, input_tokens: int) -> float:
    """Neurons billed for one call, from the published per-model rate."""
    rate = NEURONS_PER_M_INPUT_TOKENS.get(model)
    if rate is None:
        return 0.0
    return input_tokens * rate / 1_000_000.0


def usd_for_neurons(neurons: float) -> float:
    return neurons / 1000.0 * NEURON_USD_PER_1000


# --------------------------------------------------------------------------
# question normalisation
# --------------------------------------------------------------------------

def canonical_question(q: dict[str, Any]) -> dict[str, Any]:
    """Normalise the older Jev spellings into the System One shape."""
    q = dict(q)
    t = str(q.get("type", "")).lower()
    if t == "boolean":
        q["type"] = "noul"
        if "instructions" not in q and "description" in q:
            q["instructions"] = q["description"]
        q.pop("description", None)
    if t == "choice" and "criteria" not in q and "options" in q:
        opts = q["options"]
        crit = q.get("criteria")
        q["criteria"] = {o: (crit.get(o) if isinstance(crit, dict) else None)
                         for o in opts}
        if "instructions" not in q and "description" in q:
            q["instructions"] = q["description"]
        q.pop("description", None)
        q.pop("options", None)
    if t == "noul" and "instructions" not in q and "description" in q:
        q["instructions"] = q["description"]
    q.setdefault("instructions", "")
    return q


def canonical_questions(questions: dict[str, Any]) -> dict[str, Any]:
    return {k: canonical_question(v) for k, v in questions.items()}


def normalize_answers(raw: dict[str, Any],
                      questions: dict[str, Any]) -> dict[str, Any]:
    """Normalise a backend's answers against the canonical question schema."""
    out: dict[str, Any] = {}
    for qid, q in questions.items():
        a = raw.get(qid) or {}
        t = a.get("type") or q.get("type")
        if t in ("noul", "boolean"):
            p = a.get("noul")
            if p is None:
                p = a.get("p")
            if p is None:
                p = a.get("probability")
            p = 0.0 if p is None else float(p)
            out[qid] = {"type": "noul", "p": p, "answer": p >= 0.5,
                        "confidence": a.get("confidence")}
        else:
            probs = a.get("probabilities") or a.get("p") or {}
            probs = {k: float(v) for k, v in probs.items()} if isinstance(probs, dict) else {}
            choice = a.get("choice")
            if choice is None and probs:
                choice = max(probs.items(), key=lambda kv: kv[1])[0]
            out[qid] = {"type": "choice", "p": probs, "answer": choice,
                        "confidence": a.get("confidence")}
    return out


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class Backend:
    name = "base"

    def ask(self, state: Any, questions: dict[str, Any],
            model: str | None = None) -> tuple[int, Any, float]:
        raise NotImplementedError

    def close(self) -> None:
        pass


@dataclass
class ClefAI(Backend):
    """Cloudflare Workers AI behind a local `wrangler dev --remote` proxy.

    The proxy holds the AI binding, so no Workers AI token is needed on this
    side and nothing is deployed.
    """

    url: str = "http://127.0.0.1:8797"
    timeout: float = 120.0
    name: str = "clef-ai"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    total_neurons: float = 0.0
    total_calls: int = 0
    total_errors: int = 0

    def ask(self, state, questions, model=None):
        model = model or MODELS["flash"]
        body = json.dumps({"model": model,
                           "input": {"state": state, "questions": questions}}).encode()
        req = urllib.request.Request(
            self.url.rstrip("/") + "/", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "lm-clef-cascade/0.1"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                j = json.loads(r.read())
            ms = (time.perf_counter() - t0) * 1000.0
            if "error" in j and "out" not in j:
                with self._lock:
                    self.total_errors += 1
                return 500, j, ms
            out = j.get("out", j)
            if isinstance(out, dict) and "ms" in j:
                out["__worker_ms__"] = j["ms"]
            usage = out.get("usage") or {}
            n = neurons_for(model, int(usage.get("input_tokens", 0) or 0))
            with self._lock:
                self.total_neurons += n
                self.total_calls += 1
            return 200, out, ms
        except urllib.error.HTTPError as e:
            ms = (time.perf_counter() - t0) * 1000.0
            body_txt = e.read().decode(errors="replace")[:400]
            with self._lock:
                self.total_errors += 1
            return e.code, {"error": body_txt}, ms
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                self.total_errors += 1
            return 599, {"error": f"{type(e).__name__}: {e}"}, ms


@dataclass
class SystemOne(Backend):
    """POST /v1/systemone: llama.cpp's endpoint (local Clef) and TypeSafe Jev.

    Both take {"state":..., "questions":..., "model":...} and answer with
    {"answers": {...}}.  Jev needs a Bearer token; the local server does not.

    The local llama.cpp build serves only this route (its /v1/chat/completions
    answers 501) and the request body it documents is {"state", "questions"};
    it selects the model by the alias it was started with.  So for the local
    server we leave "model" out of the body entirely, exactly as the Thor
    side's own client does.
    """

    url: str
    model: str
    api_key: str | None = None
    timeout: float = 120.0
    name: str = "systemone"
    send_model: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    total_calls: int = 0
    total_errors: int = 0

    def ask(self, state, questions, model=None):
        payload: dict[str, Any] = {"state": state, "questions": questions}
        if self.send_model and (model or self.model):
            payload["model"] = model or self.model
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                j = json.loads(r.read())
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                self.total_calls += 1
            return 200, j, ms
        except urllib.error.HTTPError as e:
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                self.total_errors += 1
            return e.code, {"error": e.read().decode(errors="replace")[:400]}, ms
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                self.total_errors += 1
            return 599, {"error": f"{type(e).__name__}: {e}"}, ms


def _secret(name: str) -> str | None:
    p = pathlib.Path(os.path.expanduser("~/.config/last-mile/secrets.env"))
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return v or None
    return None


def jev_backend(model: str = "jev-latest",
                url: str = "https://api.typesafe.ai/v1/systemone") -> SystemOne:
    key = _secret("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("no TYPESAFE_API_KEY in ~/.config/last-mile/secrets.env")
    return SystemOne(url=url, model=model, api_key=key, name="jev")


def local_clef_backend(base: str = "http://127.0.0.1:8096",
                        model: str = "clef-flash") -> SystemOne:
    """A llama.cpp server's /v1/systemone endpoint."""
    return SystemOne(url=base.rstrip("/") + "/v1/systemone", model=model,
                     name="clef-local", send_model=False)


# --------------------------------------------------------------------------
# the one client
# --------------------------------------------------------------------------

class DecisionClient:
    """Ask typed questions of any decision model; get the same answers back.

    >>> c = DecisionClient(ClefAI())
    >>> c.ask({"scene": "..."}, {"ok": {"type": "noul", "instructions": "..."}})
    """

    def __init__(self, backend: Backend, model: str | None = None):
        self.backend = backend
        self.model = model

    def ask(self, state: Any, questions: dict[str, Any],
            model: str | None = None) -> tuple[int, dict[str, Any], float, dict[str, Any]]:
        """Returns (status, normalised answers, ms, raw)."""
        qs = canonical_questions(questions)
        status, raw, ms = self.backend.ask(state, qs, model or self.model)
        if status != 200:
            return status, {}, ms, raw
        answers = raw.get("answers", raw)
        return 200, normalize_answers(answers, qs), ms, raw


# --------------------------------------------------------------------------
# scoring helpers shared by every experiment
# --------------------------------------------------------------------------

def score(answers: dict[str, Any], truth: dict[str, Any]) -> dict[str, bool]:
    """Per-question correctness.  truth values are bool or a single option."""
    out: dict[str, bool] = {}
    for qid, want in truth.items():
        a = answers.get(qid) or {}
        if isinstance(want, bool):
            got = float(a.get("p", 0.0)) >= 0.5
            out[qid] = (got == want)
        else:
            out[qid] = (a.get("answer") == want)
    return out


def agreement(a: dict[str, Any], b: dict[str, Any],
              questions: Sequence[str]) -> float:
    """Fraction of questions where two answer sets give the same decision."""
    if not questions:
        return 0.0
    same = 0
    for qid in questions:
        aa, bb = a.get(qid) or {}, b.get(qid) or {}
        if aa.get("type") == "noul":
            same += 1 if (float(aa.get("p", 0)) >= 0.5) == (float(bb.get("p", 0)) >= 0.5) else 0
        else:
            same += 1 if aa.get("answer") == bb.get("answer") else 0
    return same / len(questions)


def pct(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile on a sorted copy."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return float(s[idx])
