"""The batched d1 decision server.

It speaks the same wire as llama.cpp's ``/v1/systemone`` — the same
request body, the same answer shape — but it **batches the questions of
many requests into one forward pass**, which is the thing llama.cpp's
LFM3-d1 path cannot do.

A request arrives, its questions are rendered into prompts and tokenised
on the spot, and the prompts are put on a queue. A single worker thread
drains the queue into batches and runs each batch as one forward pass of
the engine. The answers go back to the waiting requests.

The batching window is deliberately short (a few milliseconds): a game
tick lands as a burst of requests, and the burst is what the batch is
made of.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import torch

from .decision import decision_probabilities, format_answer
from .model import D1Model
from .template import PromptBuilder, parse_question
from .tokenizer import D1Tokenizer


@dataclass
class PendingQuestion:
    """One question of one request, waiting for its batch."""

    qid: str
    question: Any
    tokens: list[int]
    groups: list[list[int]]
    request: "PendingRequest" = None  # type: ignore[assignment]
    out: dict[str, Any] = field(default_factory=dict)
    event: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


@dataclass
class PendingRequest:
    body: dict[str, Any]
    questions: list[PendingQuestion] = field(default_factory=list)
    event: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


class DecisionEngine:
    """The model, the tokenizer, the template, and the batcher."""

    def __init__(
        self,
        model: D1Model,
        tokenizer: D1Tokenizer,
        builder: PromptBuilder,
        *,
        max_batch_seqs: int = 96,
        max_batch_tokens: int = 24576,
        linger_ms: float = 4.0,
        first_wait_ms: float = 1.0,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.builder = builder
        self.max_batch_seqs = max_batch_seqs
        self.max_batch_tokens = max_batch_tokens
        self.linger = linger_ms / 1000.0
        self.first_wait = first_wait_ms / 1000.0

        self._queue: queue.Queue[PendingQuestion] = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        self.stats = {
            "requests": 0,
            "questions": 0,
            "batches": 0,
            "sequences": 0,
            "tokens": 0,
            "batch_hist": [],
        }
        self._stats_lock = threading.Lock()

    # -- the queue -----------------------------------------------------------

    def submit(self, body: dict[str, Any]) -> PendingRequest:
        req = PendingRequest(body=body)
        state = body.get("state")
        if state is not None and not isinstance(state, str):
            state = json.dumps(state, indent=2)
        for qid, q in body.get("questions", {}).items():
            wq = parse_question(qid, q)
            prompt, _, groups = self.builder.build(state, wq, self.tokenizer)
            tokens = self.tokenizer.encode(prompt, parse_special=True)
            pq = PendingQuestion(qid=qid, question=wq, tokens=tokens, groups=groups, request=req)
            req.questions.append(pq)
            self._queue.put(pq)
        with self._stats_lock:
            self.stats["requests"] += 1
            self.stats["questions"] += len(req.questions)
        return req

    # -- the worker ----------------------------------------------------------

    def _drain(self) -> list[PendingQuestion]:
        """Take the pending questions, up to the batch limits.

        The worker blocks until something arrives, then keeps the window
        open for a few milliseconds so that a burst — a game tick — lands
        in one batch rather than in a hundred.

        The first wait after the queue goes quiet is short, so a request
        that arrives alone is answered without waiting out the whole
        window; the window only opens up once a second request shows
        that there is a burst.
        """
        batch: list[PendingQuestion] = []
        n_tokens = 0
        try:
            first = self._queue.get(timeout=0.05)
        except queue.Empty:
            return batch
        batch.append(first)
        n_tokens += len(first.tokens)

        deadline = time.monotonic() + self.first_wait
        while len(batch) < self.max_batch_seqs:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                pq = self._queue.get(timeout=timeout)
            except queue.Empty:
                break
            if n_tokens + len(pq.tokens) > self.max_batch_tokens:
                self._queue.put(pq)
                break
            batch.append(pq)
            n_tokens += len(pq.tokens)
            # a burst: open the window up
            deadline = time.monotonic() + self.linger
        # the batch is right-padded to its longest prompt, so the shorter
        # prompts would pay for the padding; sorting by length puts the
        # prompts of a similar length in the same chunk of the forward
        # pass, and the padding is then a few percent instead of twenty
        batch.sort(key=lambda pq: len(pq.tokens))
        return batch

    def _run(self) -> None:
        while True:
            batch = self._drain()
            if not batch:
                continue
            try:
                self._answer(batch)
            except torch.cuda.OutOfMemoryError:
                # the box is shared and the GPU's memory goes to other
                # seats: rather than fail the whole burst, give the
                # memory back and do the batch in smaller pieces
                torch.cuda.empty_cache()
                self._answer_in_pieces(batch)
            except Exception as exc:  # keep the server alive
                for pq in batch:
                    pq.error = f"{type(exc).__name__}: {exc}"
                    pq.event.set()

    def _answer_in_pieces(self, batch: list[PendingQuestion]) -> None:
        """Answer a batch that did not fit, in halves."""
        if len(batch) == 1:
            pq = batch[0]
            pq.error = "OutOfMemoryError: the batch does not fit in the GPU's memory"
            pq.event.set()
            return
        mid = len(batch) // 2
        for half in (batch[:mid], batch[mid:]):
            try:
                self._answer(half)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                self._answer_in_pieces(half)
            except Exception as exc:
                for pq in half:
                    pq.error = f"{type(exc).__name__}: {exc}"
                    pq.event.set()

    def _answer(self, batch: list[PendingQuestion]) -> None:
        t0 = time.perf_counter()
        sequences = [pq.tokens for pq in batch]
        logits = self.model.forward_last(sequences)
        dt = time.perf_counter() - t0

        with self._stats_lock:
            self.stats["batches"] += 1
            self.stats["sequences"] += len(batch)
            self.stats["tokens"] += sum(len(s) for s in sequences)
            self.stats["batch_hist"].append({"n": len(batch), "ms": dt * 1000.0})
            if torch.cuda.is_available():
                self.stats["gpu_peak_alloc_gb"] = (
                    torch.cuda.max_memory_allocated() / (1024.0**3)
                )
                self.stats["gpu_peak_reserved_gb"] = (
                    torch.cuda.max_memory_reserved() / (1024.0**3)
                )

        # the questions of one request are answered from the same batch
        for i, pq in enumerate(batch):
            probs = decision_probabilities(
                logits[i].float().cpu(),
                pq.groups,
                self.model.temperature.get(pq.question.type, 1.0),
            )
            pq.out.update(format_answer(pq.question, probs))
            pq.event.set()


class Handler(BaseHTTPRequestHandler):
    engine: DecisionEngine
    model_name: str = "d1-2B"

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # the server is quiet; the benchmark reads the numbers

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/stats":
            with self.engine._stats_lock:
                stats = dict(self.engine.stats)
            stats["batch_hist"] = stats["batch_hist"][-64:]
            self._send(200, stats)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                cfg = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._send(400, {"error": f"invalid json: {exc}"})
                return
            e = self.engine
            with e._stats_lock:
                if "max_batch_seqs" in cfg:
                    e.max_batch_seqs = int(cfg["max_batch_seqs"])
                if "max_batch_tokens" in cfg:
                    e.max_batch_tokens = int(cfg["max_batch_tokens"])
                if "linger_ms" in cfg:
                    e.linger = float(cfg["linger_ms"]) / 1000.0
                if "first_wait_ms" in cfg:
                    e.first_wait = float(cfg["first_wait_ms"]) / 1000.0
            self._send(200, {
                "max_batch_seqs": e.max_batch_seqs,
                "max_batch_tokens": e.max_batch_tokens,
                "linger_ms": e.linger * 1000.0,
                "first_wait_ms": e.first_wait * 1000.0,
            })
            return
        if self.path != "/v1/systemone":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"invalid json: {exc}"})
            return
        try:
            req = self.engine.submit(body)
        except Exception as exc:
            self._send(400, {"error": f"{type(exc).__name__}: {exc}"})
            return

        done = threading.Event()
        results: list[PendingQuestion] = []

        def waiter() -> None:
            for pq in req.questions:
                pq.event.wait()
                if pq.error:
                    req.error = pq.error
                results.append(pq)
            done.set()

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        done.wait()

        if req.error:
            self._send(500, {"error": req.error})
            return
        answers = {pq.qid: pq.out for pq in req.questions}
        n_tokens = sum(len(pq.tokens) for pq in req.questions)
        self._send(
            200,
            {
                "model": self.model_name,
                "answers": answers,
                "usage": {"input_tokens": n_tokens, "output_tokens": 0},
            },
        )


class DecisionHTTPServer(ThreadingHTTPServer):
    """The HTTP server, with a backlog that can take a whole tick.

    A tick is 64 requests arriving at once, and socketserver's default
    backlog of 5 is far too small: when the box is busy the accept loop
    starves and the clients see their connections refused. The backlog
    has to hold the whole burst.
    """

    request_queue_size = 256
    allow_reuse_address = True
    daemon_threads = True


def serve(engine: DecisionEngine, host: str = "127.0.0.1", port: int = 8138) -> DecisionHTTPServer:
    handler = type("BoundHandler", (Handler,), {"engine": engine})
    httpd = DecisionHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
