#!/usr/bin/env python3
"""Start the batched d1 decision server."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.model import D1Model  # noqa: E402
from d1dec.server import DecisionEngine, serve  # noqa: E402
from d1dec.template import PromptBuilder, QuotedSpellings  # noqa: E402
from d1dec.tokenizer import D1Tokenizer  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", default="/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8138)
    ap.add_argument("--max-batch-seqs", type=int, default=128)
    ap.add_argument("--max-batch-tokens", type=int, default=24576)
    ap.add_argument("--linger-ms", type=float, default=4.0)
    ap.add_argument("--dtype", choices=["float16", "bfloat16"], default="float16")
    args = ap.parse_args()

    t0 = time.perf_counter()
    gguf = GGUFFile(args.gguf)
    tokenizer = D1Tokenizer.from_gguf(gguf)
    builder = PromptBuilder(
        gguf.meta["tokenizer.chat_template.systemone"],
        QuotedSpellings(gguf.meta["tokenizer.ggml.tokens"], gguf.meta["tokenizer.ggml.token_type"]),
    )
    dtype = torch.float16 if args.dtype == "float16" else torch.bfloat16
    model = D1Model(dtype=dtype, gguf=gguf)
    # the weights are on the GPU now; the file's bytes can go back
    gguf.release()
    torch.cuda.synchronize()
    print(f"model loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    engine = DecisionEngine(
        model,
        tokenizer,
        builder,
        max_batch_seqs=args.max_batch_seqs,
        max_batch_tokens=args.max_batch_tokens,
        linger_ms=args.linger_ms,
    )
    serve(engine, args.host, args.port)
    print(f"listening on http://{args.host}:{args.port}", flush=True)

    stop = False

    def handler(signum, frame):  # noqa: ANN001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    while not stop:
        time.sleep(0.2)
    print("stopping", flush=True)


if __name__ == "__main__":
    main()
