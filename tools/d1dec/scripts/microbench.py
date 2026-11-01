#!/usr/bin/env python3
"""Micro-benchmarks of the pieces of the engine.

Not a measurement of the server — a measurement of the kernels, so the
design choices (fp16 vs fp8, one conv implementation vs another, the
attention backend) are made on numbers and not on guesses.
"""

from __future__ import annotations

import time

import torch
import torch.nn.functional as F


def bench(fn, n: int = 10, warmup: int = 3) -> float:
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / n * 1000.0


def main() -> None:
    dev = "cuda"
    print(torch.cuda.get_device_name(0))
    print(f"torch {torch.__version__}")

    # -- the GEMM shapes the model actually uses -------------------------
    B, L, E, FF = 96, 250, 2048, 7680
    x = torch.randn(B * L, E, device=dev, dtype=torch.float16)
    w = torch.randn(FF, E, device=dev, dtype=torch.float16)
    t = bench(lambda: x @ w.T)
    flops = 2 * B * L * E * FF
    print(f"\nfp16 GEMM [{B*L}x{E}]x[{E}x{FF}]: {t:.1f} ms -> {flops / t * 1e-9:.1f} TFLOPS")

    # fp8 with a per-channel weight scale
    try:
        xq = x.to(torch.float8_e4m3fn)
        wq = w.to(torch.float8_e4m3fn)
        sx = torch.ones(B * L, 1, device=dev, dtype=torch.float32)
        sw = torch.ones(1, FF, device=dev, dtype=torch.float32)
        out = torch._scaled_mm(xq, wq.T.contiguous().t(), scale_a=sx, scale_b=sw,
                               out_dtype=torch.float16)
        t8 = bench(lambda: torch._scaled_mm(xq, wq.T.contiguous().t(), scale_a=sx, scale_b=sw,
                                            out_dtype=torch.float16))
        print(f"fp8  GEMM same shape:              {t8:.1f} ms -> {flops / t8 * 1e-9:.1f} TFLOPS"
              f"  ({t / t8:.2f}x)")
        del xq, wq, out
    except Exception as exc:
        print(f"fp8 GEMM unavailable: {type(exc).__name__}: {exc}")

    # -- the short convolution -------------------------------------------
    C = 2048
    bx = torch.randn(B, C, L, device=dev, dtype=torch.float16)
    kern = torch.randn(7, C, device=dev, dtype=torch.float16)
    w1 = kern.transpose(0, 1).unsqueeze(1).contiguous()
    padded = F.pad(bx, (6, 0))

    def conv_grouped():
        return F.conv1d(padded, w1, groups=C)

    def conv_shifted():
        acc = torch.zeros_like(bx)
        for k in range(7):
            acc += padded[:, :, k : k + L] * kern[k].view(1, C, 1)
        return acc

    t1 = bench(conv_grouped)
    t2 = bench(conv_shifted)
    print(f"\nshort conv (grouped conv1d): {t1:.2f} ms   (x{B*L} tokens)")
    print(f"short conv (shifted mul-add): {t2:.2f} ms")
    print("  -> the faster one is", "shifted" if t2 < t1 else "grouped")

    # -- the attention ----------------------------------------------------
    H, KV, D = 16, 4, 128
    q = torch.randn(B, H, L, D, device=dev, dtype=torch.float16)
    kk = torch.randn(B, KV, L, D, device=dev, dtype=torch.float16)
    vv = torch.randn(B, KV, L, D, device=dev, dtype=torch.float16)
    mask = torch.ones(B, 1, L, L, dtype=torch.bool, device=dev).tril()
    ta = bench(lambda: F.scaled_dot_product_attention(q, kk.repeat_interleave(4, 1), vv.repeat_interleave(4, 1),
                                                      attn_mask=mask))
    print(f"\nattention (sdpa, bool mask): {ta:.2f} ms")

    # -- the elementwise cost of the norms -------------------------------
    h = torch.randn(B * L, E, device=dev, dtype=torch.float16)
    wn = torch.randn(E, device=dev, dtype=torch.float16)

    def norm():
        xf = h.float()
        return (xf * torch.rsqrt(xf.pow(2).mean(-1, keepdim=True) + 1e-5)).to(torch.float16) * wn

    def norm_fp16():
        return h * torch.rsqrt(h.float().pow(2).mean(-1, keepdim=True) + 1e-5).to(torch.float16) * wn

    print(f"\nrms norm (fp32 accumulate): {bench(norm):.2f} ms")
    print(f"rms norm (fp16 accumulate): {bench(norm_fp16):.2f} ms")

    # -- the weight streaming cost ---------------------------------------
    w_bytes = 1.85e9
    print(f"\nweights: fp16 = {2 * 1.47e9 / 1e9:.2f} GB -> {2 * 1.47e9 / 166e9 * 1e3:.1f} ms at 166 GB/s")
    print(f"         fp8  = {1.47e9 / 1e9:.2f} GB -> {1.47e9 / 166e9 * 1e3:.1f} ms at 166 GB/s")


if __name__ == "__main__":
    main()
