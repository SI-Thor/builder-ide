"""The decision model: d1-2B through builder-ide's judge.

The reflex must be fast, and the world must not stop when the model is
busy or down. Two rules come from ``docs/design/three-minds.md``:

* **the mediator never blocks the reflex** — and here the decision model
  never blocks the world either. Every ask has a deadline
  (``never-wait``, ``docs/lab/exp-never-wait.md``): past the deadline the
  best answer so far commits, and a late answer is recorded as a
  *supersede*, never as an edit to history.
* **every attempt is recorded** — the judge writes a ``judge.verdict`` row
  for every ask, including the ones it refused.

If the model cannot be reached at all, the world falls back to the
bandit's own prior and says so. The world keeps working; the log says
what happened.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from .ledger import ledger_paths

ledger_paths()

from core.judge.backends import D1Backend, JudgeRefusal  # noqa: E402
from core.judge.judge import Judge, JudgeAnswer  # noqa: E402
from core.judge.models import Question  # noqa: E402

__all__ = ["DecisionModel", "make_choice_question", "discover_d1_port"]


def make_choice_question(
    qid: str,
    *,
    role: str,
    options: dict[str, str],
    instructions: str = "",
) -> Question:
    """One choice over the skills a bot may do.

    The options are the skill ids and what they are for; the instruction
    says what the bot is trying to do. The judge answers with a
    probability per option, and the argmax is the answer.
    """
    text = instructions or (
        f"A {role} builder in a Minecraft world must choose the next thing to do. "
        "Which option serves its role best right now?"
    )
    return Question(qid=qid, kind="choice", instructions=text, criteria=dict(options))


THOR_ADMIT = Path.home() / "lm-tools" / "thor-admit"


def _answers(port: int, timeout: float = 2.0) -> bool:
    """Does a d1 answer the health door on this port right now?"""
    try:
        with urllib.request.urlopen(  # noqa: S310 - loopback, port is an int
            f"http://127.0.0.1:{port}/health", timeout=timeout
        ) as reply:
            return reply.status == 200
    except OSError:
        return False


def _speaks_systemone(port: int, timeout: float = 4.0) -> bool:
    """Does this server answer the API the judge speaks?

    ``/health`` only says a llama-server is up. The 2026-11-01 playtest
    found a seat serving ``d1-2B-old`` whose health was green but whose
    ``/v1/systemone`` was not the world's API — the reflex joined it and
    failed 480 of 486 asks in three milliseconds each. So a candidate
    port is asked a real question, and only a server that answers the
    real door counts as d1.
    """
    body = json.dumps(
        {
            "state": "probe",
            "questions": [{"qid": "probe", "kind": "choice", "instructions": "probe", "criteria": {"a": "a"}}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - loopback, port is an int
        f"http://127.0.0.1:{port}/v1/systemone",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status == 200
    except OSError:
        return False
    except urllib.error.HTTPError as err:
        # A server that knows the door may still refuse a probe payload;
        # one that does not know it answers 404.
        return err.code != 404


def lease_ports_for(model: str) -> list[tuple[str, int]]:
    """(label, port) for every lease the admission daemon holds whose label
    names this model, with the port that lease's process is listening on.

    The daemon's registry is keyed on the model — "a model is loaded once
    per box, not once per seat" — and after the Thor's 2026-11-01 reboot
    another seat's serve held the d1-2B lease while the world asked its
    configured port and got nothing. The registry says who serves; ``ss``
    says where.
    """
    try:
        raw = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [str(THOR_ADMIT), "status", "--json"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
        leases = json.loads(raw).get("leases", [])
    except (OSError, ValueError):
        return []
    pids = {
        int(lease["pid"]): str(lease.get("label", ""))
        for lease in leases
        if "pid" in lease and model in str(lease.get("label", ""))
    }
    if not pids:
        return []
    try:
        lines = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.splitlines()
    except OSError:
        return []
    found: list[tuple[str, int]] = []
    for line in lines:
        if "LISTEN" not in line:
            continue
        pid = re.search(r"pid=(\d+)", line)
        if pid is None or int(pid.group(1)) not in pids:
            continue
        port = line.split()[3].rsplit(":", 1)[-1]
        if port.isdigit():
            found.append((pids[int(pid.group(1))], int(port)))
    return found


def discover_d1_port(model: str = "d1-2B", configured: int = 8094) -> tuple[int, str]:
    """Which port d1 answers on, and how we know.

    The world's configured port first. If nothing answers there, another
    seat may hold the box's one d1 lease — join it rather than load a
    second copy. If nothing can be found, hand the configured port back
    and let the ask fail into the bandit-prior fallback as it always has;
    the source of the port travels with the model's stats.
    """
    if _answers(configured) and _speaks_systemone(configured):
        return configured, "configured"
    found = lease_ports_for(model)
    # The canonical lease (serve.<model>) first: a variant like
    # serve.d1-2B-old is a different build, and the world wants the
    # model it is named for when that one exists.
    found.sort(key=lambda item: item[0] != f"serve.{model}")
    for label, port in found:
        if _answers(port) and _speaks_systemone(port):
            return port, f"lease {label}"
    return configured, "none"


class DecisionModel:
    """d1-2B, served once on the Thor and shared by every bot."""

    def __init__(
        self,
        *,
        port: int = 8094,
        model: str = "d1-2B",
        ledger: Any | None = None,
        deadline_seconds: float = 3.0,
        timeout: float = 30.0,
    ) -> None:
        self.port, self.port_source = discover_d1_port(model=model, configured=port)
        self.backend = D1Backend(port=self.port, model=model, timeout=timeout)
        self.judge = Judge(backend=self.backend, ledger=ledger)
        self.deadline_seconds = deadline_seconds
        self._lock = threading.Lock()
        self.calls = 0
        self.failures = 0
        self.total_latency = 0.0
        self.total_questions = 0

    @property
    def available(self) -> bool:
        return True

    def ask(
        self,
        *,
        task: str,
        state: str,
        questions: Sequence[Question],
    ) -> JudgeAnswer:
        """Ask one pack over one state.

        One pack means **one** call to the model, no matter how many bots
        are in it. That is the whole reason the world shares one server:
        the per-question saving of the shared prefix is what makes a
        per-tick decision affordable for every builder at once.
        """
        started = time.monotonic()
        try:
            answer = self.judge.judge(
                task,
                state,
                list(questions),
                deadline_seconds=self.deadline_seconds,
            )
        finally:
            latency = time.monotonic() - started
            with self._lock:
                self.calls += 1
                self.total_latency += latency
                self.total_questions += len(questions)
        return answer

    def try_ask(
        self,
        *,
        task: str,
        state: str,
        questions: Sequence[Question],
    ) -> JudgeAnswer | None:
        """Ask, and never raise. A model that cannot be reached is a fact."""
        try:
            return self.ask(task=task, state=state, questions=questions)
        except (JudgeRefusal, OSError, ValueError, RuntimeError) as exc:
            with self._lock:
                self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            calls = self.calls
            failures = self.failures
            latency = self.total_latency
            questions = self.total_questions
        return {
            "backend": self.backend.name,
            "model": self.backend.model,
            "port": self.port,
            "port_source": self.port_source,
            "calls": calls,
            "failures": failures,
            "questions": questions,
            "questions_per_call": round(questions / calls, 2) if calls else 0.0,
            "mean_latency_ms": round(latency / calls * 1000, 1) if calls else 0.0,
        }
