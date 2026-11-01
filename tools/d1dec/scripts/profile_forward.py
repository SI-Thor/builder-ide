#!/usr/bin/env python3
"""Where the forward pass's time goes.

The score is a throughput, so the question is which part of the engine
costs what. This loads the model once and times the pieces: the whole
forward pass of a realistic batch, the same forward pass with one piece
stubbed out, and the raw GEMM shapes the model uses (so the efficiency of
the engine can be compared with the machine's peak).

Everything here is an engineering measurement, not a score: it decides
where to spend the effort.
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


def bench(fn, n: int = 3, warmup: int = 1) -> float:
    """The median wall time of ``fn`` in milliseconds."""
    ts = []
    for i in range(n + warmup):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        if i >= warmup:
            ts.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(ts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", default="/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf")
    ap.add_argument("--seqs", type=int, default=64)
    ap.add_argument("--tokens", type=int, default=267)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    print(torch.cuda.get_device_name(0), f"torch {torch.__version__}", flush=True)

    # -- the machine's GEMM peak, at the shapes the model uses ------------
    E, FF = 2048, 7680
    B, L = args.seqs, args.tokens
    x = torch.randn(B * L, E, device="cuda", dtype=torch.float16)
    w = torch.randn(FF, E, device="cuda", dtype=torch.float16)
    t = bench(lambda: x @ w.T, n=10)
    flops = 2 * B * L * E * FF
    print(f"\nGEMM [{B*L}x{E}]x[{E}x{FF}] fp16: {t:.1f} ms -> {flops / t * 1e-9:.1f} TFLOPS")
    del x, w
    torch.cuda.empty_cache()

    # -- the model ---------------------------------------------------------
    gguf = GGUFFile(args.gguf)
    model = D1Model(gguf=gguf)
    gguf.release()
    torch.cuda.synchronize()
    print("model loaded", flush=True)

    # a realistic batch: 64 sequences of the workload's length
    seqs = [list(range(1, args.tokens + 1)) for _ in range(args.seqs)]
    tokens = sum(len(s) for s in seqs)

    # the FLOPs of the whole model on this batch, from the shapes
    n_attn = sum(1 for lw in model.layers if not lw.is_conv)
    n_conv = sum(1 for lw in model.layers if lw.is_conv)
    per_tok = (
        n_attn * (2 * E * FF * 3 + 2 * E * E * 2 + E * 512 * 2 * 2)
        + n_conv * (2 * E * 3 * E + 2 * E * E)
    )
    print(f"\n{b'batch'}: {B} sequences, {tokens} tokens")
    print(f"  layers: {n_conv} conv, {n_attn} attention")

    full = bench(lambda: model.forward_last(seqs), n=5)
    tflops = per_tok * tokens / full * 1e-9
    print(f"  full forward: {full:.0f} ms -> {tflops:.1f} TFLOPS (useful FLOPs)")

    out = {
        "batch_seqs": B,
        "batch_tokens": tokens,
        "forward_ms": full,
        "useful_tflops": tflops,
    }

    # -- the same forward, with one piece stubbed out ---------------------
    import d1dec.model as M

    pieces = {}

    # the attention: the mask makes SDPA take its masked path
    orig_attn = M.D1Model._attn_block

    def no_attn(self, x, lw, positions, attn_mask):
        return x

    M.D1Model._attn_block = no_attn
    pieces["without_attention"] = bench(lambda: model.forward_last(seqs), n=3)
    M.D1Model._attn_block = orig_attn

    # the short convolution
    orig_conv = M.D1Model._short_conv

    def no_conv(self, x, lw):
        return x

    M.D1Model._short_conv = no_conv
    pieces["without_conv"] = bench(lambda: model.forward_last(seqs), n=3)
    M.D1Model._short_conv = orig_conv

    # the rotary
    orig_rope = M.D1Model._rope

    def no_rope(self, x, positions, is_swa, freqs):
        return x

    M.D1Model._rope = no_rope
    pieces["without_rope"] = bench(lambda: model.forward_last(seqs), n=3)
    M.D1Model._rope = orig_rope

    print("\nthe pieces:")
    for k, v in pieces.items():
        print(f"  {k:20s} {v:7.0f} ms   (the piece is worth {full - v:6.0f} ms)")

    out["pieces_ms"] = pieces

    # -- the attention on its own ----------------------------------------
    # the dense layers: non-causal, so the mask is only the padding
    # the sliding-window layers: causal, 256 positions
    H, KV, D = model.n_head, model.n_head_kv[2], model.n_head_dim
    q = torch.randn(B, H, L, D, device="cuda", dtype=torch.float16)
    k = torch.randn(B, KV, L, D, device="cuda", dtype=torch.float16)
    v = torch.randn(B, KV, L, D, device="cuda", dtype=torch.float16)
    mask = torch.ones(B, 1, L, L, dtype=torch.bool, device="cuda").tril()
    kr = k.repeat_interleave(H // KV, dim=1)
    vr = v.repeat_interleave(H // KV, dim=1)

    t_masked = bench(lambda: torch.nn.functional.scaled_dot_product_attention(q, kr, vr, attn_mask=mask), n=10)
    t_plain = bench(lambda: torch.nn.functional.scaled_dot_product_attention(q, kr, vr), n=10)
    t_gqa = bench(
        lambda: torch.nn.functional.scaled_dot_product_attention(q, k, v, attn_mask=mask, enable_gqa=True),
        n=10,
    )
    print(f"\nattention, one layer, {B}x{L} tokens:")
    print(f"  masked, kv repeated : {t_masked:6.1f} ms")
    print(f"  unmasked            : {t_plain:6.1f} ms")
    print(f"  masked, enable_gqa  : {t_gqa:6.1f} ms")
    out["attention_ms"] = {"masked_repeated": t_masked, "unmasked": t_plain, "masked_gqa": t_gqa}

    print("\n" + json.dumps(out, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
