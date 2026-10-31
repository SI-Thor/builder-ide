"""The four backends, and the one wire they share.

Every backend answers the same canonical shape — a state plus typed
questions, back a probability per option — so the brief's "each backend
is a parameter with a default" is literally a constructor argument. The
wire tests run against a local HTTP stub; no network, no GPU, no key.

The key rule (jev.md): the key comes from the environment and is never
printed — not in a repr, not in an error, not in a refusal.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.judge.backends import (
    BackendReply,
    ClefBackend,
    D1Backend,
    FakeBackend,
    JevBackend,
    JudgeRefusal,
)
from core.judge.models import Question

CHOICE = Question(
    qid="tile",
    kind="choice",
    instructions="Which tile?",
    criteria={"plain": "plain crates", "weathered": "weathered crates"},
)
NOUL = Question(qid="alive", kind="noul", instructions="The root is alive.")


# --- the HTTP stub ------------------------------------------------------------


class _SystemOneStub(BaseHTTPRequestHandler):
    """A two-endpoint stub: /v1/systemone and a Clef envelope endpoint."""

    def log_message(self, *args):  # keep the test output quiet
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        if self.path == "/v1/systemone":
            payload, status = self._systemone_reply(body)
        elif self.path == "/clef":
            payload, status = self._clef_reply(body)
        else:
            payload, status = {"error": "no such endpoint"}, 404
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _systemone_reply(self, body):
        answers = {}
        for qid, q in body.get("questions", {}).items():
            if q["type"] == "choice":
                keys = sorted(q["criteria"])
                probs = {k: 1.0 / len(keys) for k in keys}
                probs[keys[-1]] += 1.0 - sum(probs.values())
            elif q["type"] == "score":
                n = len(q["criteria"])
                probs = {str(i): 1.0 / n for i in range(n)}
            else:
                probs = {"false": 0.07, "true": 0.93}
            answers[qid] = {"probabilities": probs, "confidence": 0.81}
        return (
            {"answers": answers, "usage": {"input_tokens": 146}},
            200,
        )

    def _clef_reply(self, body):
        inner, status = self._systemone_reply(body.get("input", {}))
        return {"ms": 12, "out": {**inner, "usage": {"input_tokens": 241}}}, status


@pytest.fixture
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SystemOneStub)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


# --- the fake -----------------------------------------------------------------


def test_the_fake_is_deterministic_given_the_same_questions():
    fake = FakeBackend()
    first = fake.ask("a dusk scene", (CHOICE, NOUL))
    second = fake.ask("a dusk scene", (CHOICE, NOUL))
    assert first.distributions == second.distributions
    assert first.confidences == second.confidences


def test_the_fake_changes_its_answer_when_the_state_changes():
    fake = FakeBackend()
    answers = {fake.ask(state, (CHOICE,)).distributions["tile"]["plain"] for state in range(50)}
    assert len(answers) > 1, "a fake that always answers the same is a stub, not a stand-in"


def test_the_fake_honours_a_scripted_answer():
    fake = FakeBackend(script={"tile": {"plain": 0.9, "weathered": 0.1}})
    reply = fake.ask("any state", (CHOICE,))
    assert reply.distributions["tile"] == {"plain": 0.9, "weathered": 0.1}


def test_the_fake_distributes_over_the_questions_own_keys():
    fake = FakeBackend()
    reply = fake.ask("state", (CHOICE, NOUL))
    assert set(reply.distributions["tile"]) == {"plain", "weathered"}
    assert set(reply.distributions["alive"]) == {"false", "true"}


def test_the_fake_costs_nothing_but_its_wall_time():
    fake = FakeBackend()
    cost = fake.cost_of(fake.ask("state", (CHOICE,)))
    assert cost.hosted_cents == 0 and cost.input_tokens == 0
    assert cost.cost_known


# --- the local d1 backend -----------------------------------------------------


def test_the_d1_backend_posts_the_systemone_shape(stub):
    d1 = D1Backend(url=f"http://127.0.0.1:{stub.server_port}", model="d1-2B")
    reply = d1.ask("a dusk scene", (CHOICE,))
    (request,) = stub.requests
    assert request["path"] == "/v1/systemone"
    assert request["body"]["state"] == "a dusk scene"
    assert request["body"]["questions"]["tile"]["type"] == "choice"
    assert reply.distributions["tile"]["weathered"] == pytest.approx(0.5)
    assert reply.confidences["tile"] == 0.81
    assert reply.input_tokens == 146


def test_the_d1_backend_serves_a_pack_over_one_state(stub):
    d1 = D1Backend(url=f"http://127.0.0.1:{stub.server_port}", model="d1-2B")
    reply = d1.ask("state", (CHOICE, NOUL))
    assert set(reply.distributions) == {"tile", "alive"}


def test_the_d1_backend_costs_gpu_time_and_no_cents(stub):
    d1 = D1Backend(url=f"http://127.0.0.1:{stub.server_port}", model="d1-2B")
    reply = d1.ask("state", (CHOICE,))
    cost = d1.cost_of(reply)
    assert cost.hosted_cents == 0
    assert cost.gpu_minutes > 0
    assert cost.input_tokens == 146


def test_a_dead_d1_backend_is_a_refusal_with_the_port_in_it():
    d1 = D1Backend(url="http://127.0.0.1:1", model="d1-2B")
    with pytest.raises(JudgeRefusal) as excinfo:
        d1.ask("state", (CHOICE,))
    assert excinfo.value.code == "transport_error"
    assert ":1" in str(excinfo.value)


# --- the TypeSafe Jev backend -------------------------------------------------


def test_the_jev_backend_sends_the_bearer_token_from_the_environment(stub, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "sentinel-jev-key")
    jev = JevBackend(url=f"http://127.0.0.1:{stub.server_port}/v1/systemone", model="jev-latest")
    reply = jev.ask("state", (CHOICE,))
    (request,) = stub.requests
    assert request["headers"]["Authorization"] == "Bearer sentinel-jev-key"
    assert reply.distributions["tile"]["plain"] == pytest.approx(0.5)


def test_the_jev_backend_refuses_to_call_without_a_key(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    jev = JevBackend(url="http://127.0.0.1:1/v1/systemone", model="jev-latest")
    with pytest.raises(JudgeRefusal) as excinfo:
        jev.ask("state", (CHOICE,))
    assert excinfo.value.code == "key_missing"


def test_the_jev_key_is_never_printed(stub, monkeypatch):
    key = "sentinel-jev-key-must-not-leak"
    monkeypatch.setenv("JEV_API_KEY", key)
    jev = JevBackend(url=f"http://127.0.0.1:{stub.server_port}/v1/systemone")
    assert key not in repr(jev)
    assert key not in str(jev)
    # and a refused call does not print it either
    jev_dead = JevBackend(url="http://127.0.0.1:1/v1/systemone", api_key=key)
    with pytest.raises(JudgeRefusal) as excinfo:
        jev_dead.ask("state", (CHOICE,))
    assert key not in str(excinfo.value)
    assert key not in repr(excinfo.value)


def test_the_jev_backend_records_tokens_but_admits_no_price_is_known(stub, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")
    jev = JevBackend(url=f"http://127.0.0.1:{stub.server_port}/v1/systemone")
    cost = jev.cost_of(jev.ask("state", (CHOICE,)))
    assert cost.input_tokens == 146
    assert cost.hosted_cents == 0 and not cost.cost_known


# --- the Cloudflare Clef backend ----------------------------------------------


def test_the_clef_backend_wraps_the_questions_in_the_workers_envelope(stub):
    clef = ClefBackend(url=f"http://127.0.0.1:{stub.server_port}/clef")
    reply = clef.ask("state", (CHOICE,))
    (request,) = stub.requests
    assert request["body"]["model"] == "@cf/cloudflare/clef-flash"
    assert request["body"]["input"]["state"] == "state"
    assert request["body"]["input"]["questions"]["tile"]["type"] == "choice"
    assert reply.distributions["tile"]["weathered"] == pytest.approx(0.5)
    assert reply.input_tokens == 241


def test_the_clef_backend_prices_its_neurons(stub):
    clef = ClefBackend(url=f"http://127.0.0.1:{stub.server_port}/clef")
    reply = clef.ask("state", (CHOICE,))
    cost = clef.cost_of(reply)
    # 241 input tokens at the published clef-flash rate (3,455 neurons / M
    # tokens, $0.011 per 1,000 neurons)
    assert cost.hosted_cents == pytest.approx(241 * 3455.0 / 1e6 / 1000.0 * 0.011, rel=1e-6)
    assert cost.cost_known


def test_the_clef_backend_sends_no_key_when_the_endpoint_needs_none(stub, monkeypatch):
    monkeypatch.delenv("CLEF_API_KEY", raising=False)
    clef = ClefBackend(url=f"http://127.0.0.1:{stub.server_port}/clef")
    clef.ask("state", (CHOICE,))
    (request,) = stub.requests
    assert "Authorization" not in request["headers"]


# --- the reply record ---------------------------------------------------------


def test_a_backend_reply_knows_which_backend_and_model_answered():
    reply = BackendReply(
        backend="d1",
        model="d1-2B",
        distributions={"tile": {"plain": 0.5, "weathered": 0.5}},
        confidences={"tile": 0.4},
        input_tokens=10,
        wall_seconds=0.03,
    )
    assert reply.author == "judge@d1:d1-2B"
