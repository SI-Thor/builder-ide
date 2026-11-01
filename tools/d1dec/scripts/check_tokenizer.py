#!/usr/bin/env python3
"""Check the tokenizer against llama.cpp's own ``/tokenize``.

The prompts have to be token for token the same, or the answers are not
comparable. llama.cpp's server exposes the tokenizer, so the check is
direct.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.template import PromptBuilder, QuotedSpellings, parse_question  # noqa: E402
from d1dec.tokenizer import D1Tokenizer  # noqa: E402
from d1dec.workload import read_workload  # noqa: E402


def llama_tokenize(base_url: str, text: str) -> list[int]:
    body = json.dumps({"content": text, "add_special": False, "parse_special": True}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/tokenize", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read())
    return out["tokens"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8137")
    ap.add_argument("--gguf", default="/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf")
    ap.add_argument("--workload", default="workload/packs.jsonl")
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()

    gguf = GGUFFile(args.gguf)
    tok = D1Tokenizer.from_gguf(gguf)
    builder = PromptBuilder(
        gguf.meta["tokenizer.chat_template.systemone"],
        QuotedSpellings(gguf.meta["tokenizer.ggml.tokens"], gguf.meta["tokenizer.ggml.token_type"]),
    )

    packs = read_workload(Path(args.workload))
    checked = 0
    bad = 0
    for pack in packs[: max(1, args.n // 3)]:
        for qid, q in pack["questions"].items():
            wq = parse_question(qid, q)
            prompt, _, _ = builder.build(pack["state"], wq, tok)
            mine = tok.encode(prompt, parse_special=True)
            theirs = llama_tokenize(args.server, prompt)
            checked += 1
            if mine != theirs:
                bad += 1
                if bad <= 3:
                    print(f"MISMATCH pack={pack['char_id']} q={qid}")
                    print(f"  mine  ({len(mine)}): {mine[:40]}")
                    print(f"  llama ({len(theirs)}): {theirs[:40]}")
                    for i, (a, b) in enumerate(zip(mine, theirs)):
                        if a != b:
                            print(f"  first difference at {i}: {a} vs {b}")
                            print(f"  mine  ctx: {mine[max(0,i-6):i+6]}")
                            print(f"  llama ctx: {theirs[max(0,i-6):i+6]}")
                            break
    print(f"prompts checked: {checked}, mismatches: {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
