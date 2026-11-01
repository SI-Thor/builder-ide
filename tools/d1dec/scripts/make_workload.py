#!/usr/bin/env python3
"""Build the workload file and report its shape."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.template import PromptBuilder, QuotedSpellings, parse_question  # noqa: E402
from d1dec.tokenizer import D1Tokenizer  # noqa: E402
from d1dec.workload import build_workload, write_workload  # noqa: E402

DEFAULT_GGUF = "/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", default=DEFAULT_GGUF)
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--ticks", type=int, default=4)
    ap.add_argument("--chars", type=int, default=64)
    ap.add_argument("--questions", type=int, default=3)
    ap.add_argument("--out", default="workload/packs.jsonl")
    args = ap.parse_args()

    wl = build_workload(
        seed=args.seed,
        ticks=args.ticks,
        chars_per_tick=args.chars,
        questions_per_pack=args.questions,
    )
    out = Path(args.out)
    write_workload(out, wl)

    gguf = GGUFFile(args.gguf)
    tok = D1Tokenizer.from_gguf(gguf)
    builder = PromptBuilder(
        gguf.meta["tokenizer.chat_template.systemone"],
        QuotedSpellings(gguf.meta["tokenizer.ggml.tokens"], gguf.meta["tokenizer.ggml.token_type"]),
    )

    state_lens: list[int] = []
    prompt_lens: list[int] = []
    for pack in wl.packs:
        state_lens.append(len(tok.encode(pack.state, parse_special=False)))
        for qid, q in pack.questions.items():
            wq = parse_question(qid, q)
            prompt, _, _ = builder.build(pack.state, wq, tok)
            prompt_lens.append(len(tok.encode(prompt, parse_special=True)))

    def stats(xs: list[int]) -> str:
        xs = sorted(xs)
        n = len(xs)
        return (
            f"n={n} min={xs[0]} p50={xs[n // 2]} p95={xs[int(n * 0.95)]} "
            f"max={xs[-1]} mean={sum(xs) / n:.1f}"
        )

    print(f"workload -> {out}  ({len(wl.packs)} packs, {len(wl.packs) * args.questions} questions)")
    print(f"  state tokens:   {stats(state_lens)}")
    print(f"  prompt tokens:  {stats(prompt_lens)}")
    print(f"  total tokens/tick (N={args.chars}): {sum(prompt_lens) // args.ticks}")
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    print(f"  seed={meta['seed']} ticks={meta['ticks']} chars/tick={meta['chars_per_tick']}")


if __name__ == "__main__":
    main()
