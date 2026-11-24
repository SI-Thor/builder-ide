"""The reflex service: the world's decision seam, on one port.

The bots ask this service for their next move. The service batches what
arrives inside one window into **one** pack and asks the decision model
**once**, so four builders cost one model call rather than four.

    POST /decide   {bot, role, context, candidates:[{id, title}], state}
                   -> {skill_id, reason, confidence, propensity, candidates}
    POST /play     the play record
                   -> {ok: true}
    GET  /skills   the library
    GET  /stats    the numbers
    GET  /health   is the world up

The service is on **loopback**: it is an internal door between the bots
and the decision model, not something the LAN needs to reach.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .chooser import Chooser, Refusal
from .decision import DecisionModel, make_choice_question
from .library import SkillLibrary
from .models import PlayRecord

#: The lease the world takes on the box. Heavy work holds this lock, one
#: at a time (the stopgap from the 13:22 OOM). The world takes it for the
#: heavy part of its life — world generation — and lets it go the moment
#: the world is up.
HEAVY_LOCK = Path(os.environ.get("AW_HEAVY_LOCK", str(Path.home() / "lm-wt" / "heavy.lock")))

#: The rule the lock stands in for: keep this much of the box free.
FREE_FLOOR_GB = int(os.environ.get("AW_FREE_FLOOR_GB", "25"))


def free_gb() -> int:
    """How much of the box is free right now, in GB."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // (1024 * 1024)
    except OSError:
        pass
    return 0


def lease_held() -> bool:
    """Is another seat running heavy work right now?

    This is information, not admission: it says the box is busy, not
    that the world must stand aside.
    """
    try:
        HEAVY_LOCK.parent.mkdir(parents=True, exist_ok=True)
        if not HEAVY_LOCK.exists():
            HEAVY_LOCK.touch()
        handle = open(HEAVY_LOCK, "r+")
    except OSError:
        return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        handle.close()


def may_act() -> tuple[bool, str]:
    """May the world act this tick? And why not, if it may not.

    The rule from the 13:22 OOM is not "nothing heavy may run at the
    same time" — it is **"keep 25 GB free"**. The lock is the stopgap for
    that, and it is a poor instrument for a resident service: one long
    generation sweep would freeze the world for an hour even though the
    world uses 2 GB and runs at `nice 10`.

    So the admission test the world applies every tick is the rule
    itself: the free memory. The world stands aside when the box is
    full, and carries on when there is room — and it says which in the
    log.
    """
    free = free_gb()
    if free < FREE_FLOOR_GB:
        return False, f"the box has {free} GB free; the rule is {FREE_FLOOR_GB} GB"
    return True, ""

#: The drift detector's pause file. ``core/drift/pause.py`` (in
#: builder-ide) writes it; the world only reads it. A file is a door
#: that needs no process killed and no service restarted — §3.5's
#: "cheap to undo" — and a missing file, an unreadable file or a
#: malformed one means **no pause**: the world never invents a pause
#: out of a read error.
PAUSE_FILE = Path(
    os.environ.get(
        "AW_DRIFT_PAUSE",
        str(
            Path(
                os.environ.get(
                    "AW_RUNTIME",
                    str(Path.home() / "lm-wt" / "agent-world" / "runtime"),
                )
            ).expanduser()
            / "drift-pause.json"
        ),
    )
)


def drift_pauses() -> dict[str, dict[str, Any]]:
    """The pause entries in force right now, by actor.

    An entry is ``{"level": "soft"|"tier"|"hard", "reason": str,
    "until": <epoch or null>}``. An expired entry is not in force —
    that is the undo: a pause lapses on its own unless renewed. The
    actor ``"world"`` is the whole world; any other actor is a bot.
    """
    try:
        document = json.loads(PAUSE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    now = time.time()
    in_force: dict[str, dict[str, Any]] = {}
    for actor, entry in document.items():
        if not isinstance(entry, dict):
            continue
        until = entry.get("until")
        try:
            if until is not None and float(until) < now:
                continue
        except (TypeError, ValueError):
            continue
        in_force[str(actor)] = entry
    return in_force


__all__ = ["ReflexService", "serve", "drift_pauses"]


class _Pending:
    """One bot's request, waiting for the pack to be answered."""

    __slots__ = ("bot", "role", "context", "options", "state", "event", "result", "error")

    def __init__(self, bot: str, role: str, context: dict[str, Any], options: list[dict[str, Any]], state: str) -> None:
        self.bot = bot
        self.role = role
        self.context = context
        self.options = options
        self.state = state
        self.event = threading.Event()
        self.result: dict[str, Any] | None = None
        self.error: str | None = None


class ReflexService:
    """The batching, the asking and the recording."""

    def __init__(
        self,
        *,
        library: SkillLibrary,
        chooser: Chooser,
        model: DecisionModel,
        ledger: Any | None = None,
        batch_window: float = 0.12,
        request_timeout: float = 6.0,
    ) -> None:
        self.library = library
        self.chooser = chooser
        self.model = model
        self.ledger = ledger
        self.batch_window = batch_window
        self.request_timeout = request_timeout
        self._queue: list[_Pending] = []
        self._lock = threading.Lock()
        self._batches = 0
        self._pack_latencies: list[float] = []
        self._last_busy = False
        self._yielded = 0

    # -- the batching ---------------------------------------------------------

    def submit(self, pending: _Pending) -> dict[str, Any]:
        """Queue one bot's request and wait for the pack's answer."""
        with self._lock:
            self._queue.append(pending)
        if not pending.event.wait(self.request_timeout):
            return {
                "skill_id": None,
                "reason": "refused",
                "detail": "the reflex did not answer in time (never-wait)",
                "candidates": [o["id"] for o in pending.options],
            }
        if pending.error:
            return {
                "skill_id": None,
                "reason": "refused",
                "detail": pending.error,
                "candidates": [o["id"] for o in pending.options],
            }
        return pending.result or {}

    def _collector(self) -> None:
        """The loop: gather the batch, ask once, hand the answers back.

        It never dies: a thread that died would take the world's
        decisions with it, and the world's job is to keep deciding.
        """
        while True:
            batch: list[_Pending] = []
            try:
                with self._lock:
                    pending = self._queue.pop(0) if self._queue else None
                if pending is None:
                    time.sleep(self.batch_window)
                    continue

                # Let the other bots of this tick arrive: they are asking
                # at the same time and they share one model call.
                deadline = time.monotonic() + self.batch_window
                batch = [pending]
                while time.monotonic() < deadline:
                    with self._lock:
                        if self._queue:
                            batch.extend(self._queue)
                            self._queue.clear()
                        else:
                            break
                    time.sleep(0.005)

                started = time.monotonic()
                self._answer(batch)
                latency = time.monotonic() - started
                self._batches += 1
                self._pack_latencies.append(latency)
            except Exception as exc:  # pragma: no cover - defensive
                # A bad batch must not take the collector down. Every
                # request in it is released, so the builders get a
                # refusal rather than a silence.
                self._last_error = f"{type(exc).__name__}: {exc}"
                for item in batch:
                    item.error = self._last_error
                    item.event.set()

    def _record_yield(self, bots: list[str], why: str) -> None:
        """Write one drift.yield event, or say loudly that it could not be.

        The log must not take the world down; a yield that is not
        recorded is a blind spot in the detector's evidence, not an
        outage, so the failure is named in the service's own error
        field instead of raised through the collector.

        It is also **printed**: the error field is not in the service's
        ``/stats`` and nobody reads it, so a yield that never reached
        the log was invisible for an hour and a half (2026-11-02, the
        closed event set refused ``drift.yield`` and the world kept
        holding the agent it was holding because of it). A stand-aside
        that is not recorded is the one failure this service must not
        make quietly.
        """
        if self.ledger is None:
            print(
                f"drift.yield not recorded: no ledger is attached "
                f"(bots={','.join(bots) or 'none'}; why={why})",
                file=sys.stderr,
                flush=True,
            )
            return
        try:
            self.ledger.yielded(bots, why)
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"yield not recorded: {type(exc).__name__}: {exc}"
            print(self._last_error, file=sys.stderr, flush=True)

    def _answer(self, batch: list[_Pending]) -> None:
        # The admission test: the box's own rule, applied every tick.
        # The world stands aside when the box is full; it carries on
        # when there is room, and it records that another seat is busy.
        allowed, why = may_act()
        self._last_busy = lease_held()
        pauses = drift_pauses()
        world_pause = pauses.get("world")
        if not allowed or world_pause:
            # The world stands aside: the box's own admission rule, or
            # the drift detector's tier/hard pause (§3.5). Both are the
            # same act — the world declines new work politely, nobody
            # is killed — and both are recorded as a yield, so the
            # stall signal can tell a deliberate wait from a stall.
            if not allowed:
                reason = why
            else:
                reason = (
                    f"drift pause ({world_pause.get('level', 'tier')}): "
                    f"{world_pause.get('reason', '')}"
                )
            self._yielded += len(batch)
            self._record_yield([item.bot for item in batch], reason)
            for item in batch:
                item.error = f"yielded: {reason}"
                item.event.set()
            return
        held = []
        for item in batch:
            pause = pauses.get(item.bot)
            if pause is not None:
                item.error = (
                    f"paused: drift pause ({pause.get('level', 'soft')}): "
                    f"{pause.get('reason', '')}"
                )
                held.append(item)
        if held:
            # The soft level of §3.5: this agent waits on its own
            # branch and stops committing; the rest of the pack is
            # answered. A held bot is a yield, not a failure.
            self._yielded += len(held)
            self._record_yield(
                [item.bot for item in held],
                f"drift pause (soft): held by the drift detector",
            )
            for item in held:
                item.event.set()
            batch = [item for item in batch if item not in held]
            if not batch:
                return

        # One state, one pack, one call.
        state = batch[0].state or "a Minecraft world with builders at work"
        questions = []
        for item in batch:
            options = {o["id"]: o.get("title", o["id"]) for o in item.options}
            if len(options) < 2:
                # A choice needs at least two options; the judge refuses
                # a one-option question. The bot with one option is
                # answered on its own below.
                continue
            questions.append(
                make_choice_question(item.bot, role=item.role, options=options)
            )

        distributions: dict[str, dict[str, float]] = {}
        confidences: dict[str, float | None] = {}
        if questions:
            answer = self.model.try_ask(task="agent-world: choose the next skill", state=state, questions=questions)
            if answer is not None:
                for judgment in answer.judgments:
                    distributions[judgment.qid] = dict(judgment.distribution)
                    confidences[judgment.qid] = judgment.confidence

        for item in batch:
            try:
                skills = [self.library.require(o["id"]) for o in item.options]
                judge_dist = distributions.get(item.bot) or {}
                confidence = confidences.get(item.bot)
                choice = self.chooser.choose(
                    item.context,
                    skills,
                    judge=judge_dist,
                    judge_confidence=confidence,
                )
                chosen = next((s for s in skills if s.id == choice.skill_id), None)
                answer = choice.as_dict()
                if chosen is not None:
                    answer["body"] = chosen.body
                    answer["title"] = chosen.title
                    answer["predict"] = chosen.predict.model_dump()
                    answer["skill_version"] = chosen.version
                    answer["api"] = list(chosen.api)
                item.result = answer
            except Refusal as exc:
                item.error = f"{exc.reason}: {exc.detail}"
            except Exception as exc:  # pragma: no cover - defensive
                item.error = f"{type(exc).__name__}: {exc}"
            finally:
                item.event.set()

    # -- the API --------------------------------------------------------------

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        bot = str(payload.get("bot", "bot"))
        role = str(payload.get("role", "builder"))
        context = dict(payload.get("context") or {})
        options = list(payload.get("candidates") or [])
        state = str(payload.get("state", ""))
        family = str(payload.get("family") or "")
        if family and not options:
            # A person asked for a job by name ("gather wood" is the
            # gatherer's wood family). The family narrows the question;
            # the chooser still makes the choice, the judge still sees
            # it, and the play is still a play the bandit learns from.
            # No model ever parses the words — the mapping from chat to
            # family is a table on the bots' side.
            options = [
                {"id": s.id, "title": s.title}
                for s in self.library.all()
                if s.status == "active" and s.family == family
            ]
        if not options:
            # The library is the source of the options: the skills that
            # apply to this builder, in this context, for this role.
            options = [
                {"id": s.id, "title": s.title}
                for s in self.library.eligible(context, role=role)
            ]
        if not options:
            return {
                "skill_id": None,
                "reason": "refused",
                "detail": "no skill applies to this builder in this context",
            }
        pending = _Pending(bot, role, context, options, state)
        return self.submit(pending)

    def play(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            record = PlayRecord(**payload)
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        self.chooser.update(record)
        if self.ledger is not None:
            self.ledger.played(record, actor=str(record.context.get("bot", "bot")))
        return {"ok": True, "id": record.id}

    def stats(self) -> dict[str, Any]:
        mean_pack = (
            round(sum(self._pack_latencies) / len(self._pack_latencies) * 1000, 1)
            if self._pack_latencies
            else 0.0
        )
        return {
            "batches": self._batches,
            "yielded_ticks": self._yielded,
            "box_busy": self._last_busy,
            "free_gb": free_gb(),
            "mean_pack_latency_ms": mean_pack,
            "model": self.model.stats(),
            "chooser": self.chooser.stats(),
            "skills": {
                "total": len(self.library.all()),
                "active": len(self.library.active()),
                "families": list(self.library.families()),
            },
        }


def serve(
    service: ReflexService,
    *,
    host: str = "127.0.0.1",
    port: int = 8110,
) -> ThreadingHTTPServer:
    """Start the service. The collector runs on its own thread."""
    threading.Thread(target=service._collector, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/health"):
                self._reply({"ok": True, "service": "agent-world reflex"})
            elif self.path.startswith("/stats"):
                self._reply(service.stats())
            elif self.path.startswith("/skills"):
                self._reply(
                    {
                        "skills": [
                            {
                                "id": s.id,
                                "family": s.family,
                                "version": s.version,
                                "role": s.role,
                                "title": s.title,
                                "api": list(s.api),
                                "status": s.status,
                            }
                            for s in service.library.all()
                        ]
                    }
                )
            else:
                self._reply({"error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read()
            except Exception as exc:
                self._reply({"error": f"bad request: {exc}"}, status=400)
                return
            if self.path.startswith("/decide"):
                self._reply(service.decide(payload))
            elif self.path.startswith("/play"):
                self._reply(service.play(payload))
            else:
                self._reply({"error": "not found"}, status=404)

        def log_message(self, fmt: str, *args: Any) -> None:
            return  # the world's own log is the ledger, not the access log

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
