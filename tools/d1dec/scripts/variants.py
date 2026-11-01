#!/usr/bin/env python3
"""The engine's settings, measured on the real workload, in one session.

Two things have to be true of the settings this server runs with: the
forward pass has to be fast, and the GPU's memory has to stay under the
line (the peak of the host's resident set plus the peak of the GPU's
pool is what the score counts, and the complex rotary's temporaries
push that up).

This builds the real tick — the workload's own prompts, tokenised the
way the server tokenises them — and measures, for each combination of
the engine's switches, the wall time of the tick's forward passes and
the GPU's high-water mark.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.model import D1Model  # noqa: E402
from d1dec.template import PromptBuilder, QuotedSpellings, parse_question  # noqa: E402
from d1dec.tokenizer import D1Tokenizer  # noqa: E402
from d1dec.workload import read_workload  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", default="/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf")
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    gguf = GGUFFile(args.gguf)
    tokenizer = D1Tokenizer.from_gguf(gguf)
    builder = PromptBuilder(
        gguf.meta["tokenizer.chat_template.systemone"],
        QuotedSpellings(gguf.meta["tokenizer.ggml.tokens"], gguf.meta["tokenizer.ggml.token_type"]),
    )

    # the real tick: one tick's packs, rendered and tokenised the way the
    # server does it
    packs = read_workload(Path(args.workload))
    by_tick: dict[int, list[dict]] = {}
    for p in packs:
        by_tick.setdefault(p.get("tick", 0), []).append(p)
    tick = sorted(by_tick)[1]
    seqs: list[list[int]] = []
    for pack in by_tick[tick]:
        for qid, q in pack["questions"].items():
            wq = parse_question(qid, q)
            prompt, _, _ = builder.build(pack["state"], wq, tokenizer)
            seqs.append(tokenizer.encode(prompt, parse_special=True))
    seqs.sort(key=len)
    lens = [len(s) for s in seqs]
    print(f"a tick: {len(seqs)} sequences, {sum(lens)} tokens, "
          f"length {min(lens)}-{max(lens)}, mean {sum(lens) / len(lens):.0f}")

    model = D1Model(gguf=gguf)
    gguf.release()
    torch.cuda.synchronize()
    print("model loaded", flush=True)

    combos = [
        ("native", "native", 64),
        ("native", "native", 32),
        ("cplx", "native", 32),
        ("native", "fp16", 32),
        ("cplx", "fp16", 32),
        ("fp16", "fp16", 32),
    ]

    rows = []
    for rope, conv, chunk in combos:
        model.rope_mode = rope
        model.conv_mode = conv
        model.gqa = True
        model.forward_chunk = chunk
        try:
            # the timing
            ts = []
            for i in range(4):
                torch.cuda.synchronize()
                t0 = time.perf_counter()
                model.forward_last(seqs)
                torch.cuda.synchronize()
                if i >= 1:
                    ts.append((time.perf_counter() - t0) * 1000.0)
            t = statistics.median(ts)
            # the memory: the peak of one chunk, which is what the
            # server's peak is
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            model.forward_last(seqs)
            torch.cuda.synchronize()
            peak = torch.cuda.max_memory_reserved() / (1024.0**3)
            alloc = torch.cuda.max_memory_allocated() / (1024.0**3)
            rows.append({"rope": rope, "conv": conv, "chunk": chunk,
                         "ms": t, "gpu_peak_reserved_gb": peak,
                         "gpu_peak_alloc_gb": alloc})
            print(f"  {rope:7s} {conv:7s} chunk {chunk:3d}  {t:7.0f} ms   "
                  f"gpu peak {peak:5.2f} GB (alloc {alloc:5.2f})", flush=True)
        except Exception as exc:
            print(f"  {rope:7s} {conv:7s} chunk {chunk:3d}  FAILED: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        torch.cuda.empty_cache()

    base = rows[0]["ms"] if rows else 0.0
    print("\n=== the settings ===")
    for r in rows:
        print(f"  {r['rope']:7s} {r['conv']:7s} chunk {r['chunk']:3d}  "
              f"{base / r['ms']:5.2f}x of the engine as it was   "
              f"gpu peak {r['gpu_peak_reserved_gb']:5.2f} GB")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
