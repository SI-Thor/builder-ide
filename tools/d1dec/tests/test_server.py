"""The server's plumbing: the wire, the batcher, the answers.

The model is stubbed — the arithmetic is checked by
``test_batching_exactness.py`` — so this test is about the parts that
are easy to get wrong: the request shape, the batching, the answer
format, and the fact that a burst really does land in one batch.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.server import DecisionEngine, serve  # noqa: E402
from d1dec.template import PromptBuilder, QuotedSpellings, parse_question  # noqa: E402
from d1dec.tokenizer import D1Tokenizer  # noqa: E402

GGUF = "/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf"


class StubModel:
    """A model that returns the same logits for every sequence."""

    def __init__(self, n_vocab: int = 128000) -> None:
        self.temperature = {"choice": 1.3373984098434448, "score": 1.3373984098434448, "noul": 1.3373984098434448}
        self.n_vocab = n_vocab
        self.calls: list[int] = []
        self._logits = torch.zeros(n_vocab)

    def forward_last(self, sequences):  # noqa: ANN001
        self.calls.append(len(sequences))
        out = torch.zeros(len(sequences), self.n_vocab)
        # a fixed pattern of logits, so the probabilities are predictable
        for i in range(self.n_vocab):
            out[:, i] = float((i * 37) % 11)
        return out


def main() -> None:
    gguf = GGUFFile(GGUF)
    tok = D1Tokenizer.from_gguf(gguf)
    builder = PromptBuilder(
        gguf.meta["tokenizer.chat_template.systemone"],
        QuotedSpellings(gguf.meta["tokenizer.ggml.tokens"], gguf.meta["tokenizer.ggml.token_type"]),
    )
    model = StubModel()
    engine = DecisionEngine(model, tok, builder, max_batch_seqs=64, max_batch_tokens=100000, linger_ms=20.0)
    httpd = serve(engine, "127.0.0.1", 8199)
    base = "http://127.0.0.1:8199"

    def post(body):
        req = urllib.request.Request(
            f"{base}/v1/systemone",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    state = "Night cycle, scene arctic (arctic-s1), render seed 1, 960x540.\nchar_00 is working."

    # -- a single pack ---------------------------------------------------
    body = {
        "state": state,
        "questions": {
            "q0": {
                "type": "choice",
                "instructions": "Which tile next?",
                "criteria": {"opt0": "weathered crates (harbor.crates.style)", "opt1": "rope coils (props.harbor.rope)",
                             "opt2": "bollards (props.harbor.bollards)", "opt3": "nets (props.harbor.nets)"},
            },
            "q1": {"type": "score", "instructions": "How good is the render?",
                   "criteria": ["unusable", "poor", "fair", "good", "excellent"]},
            "q2": {"type": "noul", "instructions": "Claim: the render carries a wrong_scale defect."},
        },
    }
    out = post(body)
    assert set(out["answers"]) == {"q0", "q1", "q2"}, out["answers"]
    a0 = out["answers"]["q0"]
    assert a0["type"] == "choice" and a0["choice"] in {"opt0", "opt1", "opt2", "opt3"}, a0
    assert len(a0["probabilities"]) == 4
    assert abs(sum(a0["probabilities"].values()) - 1.0) < 1e-9
    a1 = out["answers"]["q1"]
    assert a1["type"] == "score" and a1["score"] in range(5), a1
    a2 = out["answers"]["q2"]
    assert a2["type"] == "noul" and 0.0 <= a2["noul"] <= 1.0, a2
    assert out["usage"]["output_tokens"] == 0
    print("single pack OK:", json.dumps(out["answers"], indent=1)[:400])

    # the label groups are what the prompt says
    wq = parse_question("q0", body["questions"]["q0"])
    texts, groups = builder.labels_for(wq, tok)
    assert texts == ["A", "B", "C", "D"], texts
    assert all(len(g) >= 1 for g in groups), groups
    wq2 = parse_question("q1", body["questions"]["q1"])
    texts2, _ = builder.labels_for(wq2, tok)
    assert texts2 == ["0", "1", "2", "3", "4"], texts2
    wq3 = parse_question("q2", body["questions"]["q2"])
    texts3, _ = builder.labels_for(wq3, tok)
    assert texts3 == ["true", "false"], texts3
    print("label groups OK:", texts, texts2, texts3)

    # -- a burst ---------------------------------------------------------
    model.calls.clear()
    n_packs = 32
    results = []

    def one(i):
        b = dict(body)
        b["state"] = state + f"\ncharacter {i}."
        results.append(post(b))

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n_packs)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.perf_counter() - t0
    assert len(results) == n_packs
    print(f"burst: {n_packs} packs in {dt * 1000:.0f} ms, batches={model.calls}")
    assert sum(model.calls) == n_packs * 3, model.calls
    assert max(model.calls) > 1, f"the burst did not batch: {model.calls}"

    httpd.shutdown()
    print("OK")


if __name__ == "__main__":
    main()
