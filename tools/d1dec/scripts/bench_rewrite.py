#!/usr/bin/env python3
"""The bandwidth of this Thor, and the candidate rewrites of the two hot spots.

The per-kernel profile says the forward pass is a fifth arithmetic and
four fifths data movement: the rotary and the short convolution
materialise their intermediates in fp32 and pay for every pass over
them. This measures the machine's bandwidth and then times the
candidate rewrites against the ones in the engine now, and checks that
the candidates give the same numbers.
"""

from __future__ import annotations

import statistics
import sys
import time

import torch
import torch.nn.functional as F

torch.manual_seed(0)
dev = "cuda"

B, L, E, H, D, KV = 64, 219, 2048, 16, 128, 4
NC = B * L


def bench(fn, n=10, warmup=3) -> float:
    ts = []
    for i in range(n + warmup):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        if i >= warmup:
            ts.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(ts)


print("=" * 74)
print("the bandwidth of this Thor")
print("=" * 74)

a16 = torch.randn(NC, E, device=dev, dtype=torch.float16)
b16 = torch.empty_like(a16)
a32 = a16.float()
b32 = torch.empty_like(a32)
MB = a16.numel() * 2 / 1e6

t = bench(lambda: b16.copy_(a16))
print(f"  fp16 copy   {t:6.2f} ms  -> {2 * MB / t * 1e3:6.0f} GB/s")
t = bench(lambda: b32.copy_(a32))
print(f"  fp32 copy   {t:6.2f} ms  -> {2 * MB * 2 / t * 1e3:6.0f} GB/s")
t = bench(lambda: torch.mul(a16, a16, out=b16))
print(f"  fp16 mul    {t:6.2f} ms  -> {3 * MB / t * 1e3:6.0f} GB/s")
t = bench(lambda: a16.float())
print(f"  fp16->fp32  {t:6.2f} ms  -> {3 * MB / t * 1e3:6.0f} GB/s")
t = bench(lambda: a32.half())
print(f"  fp32->fp16  {t:6.2f} ms  -> {3 * MB / t * 1e3:6.0f} GB/s")
t = bench(lambda: F.rms_norm(a16, (E,), torch.ones(E, device=dev, dtype=torch.float16), 1e-5))
print(f"  rms_norm    {t:6.2f} ms  -> {2 * MB / t * 1e3:6.0f} GB/s")

# ==========================================================================
print()
print("=" * 74)
print("the rotary")
print("=" * 74)

# the engine's layout: [B, L, H, D] -> transpose -> [B, H, L, D]
q = torch.randn(B, L, H, D, device=dev, dtype=torch.float16) * 0.1
qh = q.transpose(1, 2)                      # what the engine ropes
d = D // 2
pos = torch.arange(L, device=dev).expand(B, L)
base = (1000000.0 ** (-2.0 / 128)) ** torch.arange(d, device=dev, dtype=torch.float32)
theta = pos.float().unsqueeze(-1) * base.unsqueeze(0).unsqueeze(0)
cos = theta.cos().unsqueeze(1)             # [B, 1, L, d]
sin = theta.sin().unsqueeze(1)


def rope_now(x, cos, sin):
    """What the engine does now."""
    d = x.shape[-1] // 2
    x0 = x[..., :d].float()
    x1 = x[..., d:].float()
    out0 = x0 * cos - x1 * sin
    out1 = x0 * sin + x1 * cos
    return torch.cat([out0, out1], dim=-1).to(x.dtype)


def rope_fp16(x, cos, sin):
    """The same rotation, in fp16."""
    d = x.shape[-1] // 2
    x0 = x[..., :d]
    x1 = x[..., d:]
    out0 = x0 * cos.half() - x1 * sin.half()
    out1 = x0 * sin.half() + x1 * cos.half()
    return torch.cat([out0, out1], dim=-1)


def rope_cplx(x, cos, sin):
    """The rotation as one complex multiplication.

    With the head's two halves interleaved, the rotation of a pair
    (x0, x1) by (cos, sin) is exactly the product of the complex numbers
    x0 + i*x1 and cos + i*sin. One kernel instead of eight passes.
    """
    d = x.shape[-1] // 2
    xc = torch.view_as_complex(x.float().reshape(*x.shape[:-1], d, 2))
    wc = torch.view_as_complex(
        torch.stack([cos, sin], dim=-1).expand(*x.shape[:-1], d, 2).contiguous()
    )
    out = torch.view_as_real(xc * wc)
    return torch.cat([out[..., 0], out[..., 1]], dim=-1).to(x.dtype)


def rope_cplx_split(x, cos, sin):
    """The complex product without interleaving the weights."""
    d = x.shape[-1] // 2
    xc = torch.complex(x[..., :d].float(), x[..., d:].float())
    wc = torch.complex(cos, sin)
    out = torch.view_as_real(xc * wc)
    return torch.cat([out[..., 0], out[..., 1]], dim=-1).to(x.dtype)


ref = rope_now(qh, cos, sin)
for name, fn in (("fp16", rope_fp16), ("complex", rope_cplx), ("complex split", rope_cplx_split)):
    try:
        got = fn(qh, cos, sin)
        err = (got.float() - ref.float()).abs().max().item()
        rel = ((got.float() - ref.float()).norm() / ref.float().norm()).item()
        t = bench(lambda: fn(qh, cos, sin))
        print(f"  {name:14s} {t:6.2f} ms   max abs err {err:.2e}   rel {rel:.2e}")
    except Exception as exc:
        print(f"  {name:14s} FAILED: {type(exc).__name__}: {exc}")

t_now = bench(lambda: rope_now(qh, cos, sin))
print(f"  {'now':14s} {t_now:6.2f} ms")

# ==========================================================================
print()
print("=" * 74)
print("the short convolution")
print("=" * 74)

conv_in = torch.randn(E, 3 * E, device=dev, dtype=torch.float16) / (E ** 0.5)
conv_w = torch.randn(6 + 1, E, device=dev, dtype=torch.float16) / 7.0
conv_out = torch.randn(E, E, device=dev, dtype=torch.float16) / (E ** 0.5)
x = torch.randn(B, L, E, device=dev, dtype=torch.float16) * 0.1


def conv_now(t):
    """What the engine does now: fp32 grouped conv1d on a padded copy."""
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    bx = F.pad(bx, (6, 0))
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = F.conv1d(bx.float(), w.float(), groups=E)
    y = cc.float() * conv.transpose(1, 2)
    return y.to(torch.float16) @ conv_out


def conv_fp16(t):
    """The convolution in fp16, the product in fp32."""
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = F.conv1d(bx, w, groups=E)           # cuDNN, fp32 accumulate
    y = cc.float() * conv.transpose(1, 2).float()
    return y.to(torch.float16) @ conv_out


def conv_f16_all(t):
    """Everything in fp16."""
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = F.conv1d(bx, w, groups=E)
    y = (cc * conv.transpose(1, 2)).to(torch.float16)
    return y @ conv_out


def conv_manual(t):
    """The seven taps by hand, in fp32, no padding copy."""
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)              # [B, E, L]
    w = conv_w                                    # [7, E]
    acc = torch.zeros(B, L, E, device=dev, dtype=torch.float32)
    for k in range(7):
        if k == 0:
            acc += w[k].float() * bx[..., :L].float()
        else:
            acc += w[k].float() * bx[..., k : k + L].float()
    y = cc.float() * acc.transpose(1, 2)
    return y.to(torch.float16) @ conv_out


ref_c = conv_now(x).float()
for name, fn in (("fp16 conv", conv_fp16), ("all fp16", conv_f16_all), ("manual fp32", conv_manual)):
    try:
        got = fn(x).float()
        err = (got - ref_c).abs().max().item()
        rel = ((got - ref_c).norm() / ref_c.norm()).item()
        t = bench(lambda: fn(x))
        print(f"  {name:14s} {t:6.2f} ms   max abs err {err:.2e}   rel {rel:.2e}")
    except Exception as exc:
        print(f"  {name:14s} FAILED: {type(exc).__name__}: {exc}")

print(f"  {'now':14s} {bench(lambda: conv_now(x)):6.2f} ms")

# ==========================================================================
print()
print("=" * 74)
print("the attention")
print("=" * 74)

kk = torch.randn(B, KV, L, D, device=dev, dtype=torch.float16)
vv = torch.randn(B, KV, L, D, device=dev, dtype=torch.float16)
mask = torch.ones(B, 1, L, L, dtype=torch.bool, device=dev).tril()
kr = kk.repeat_interleave(H // KV, dim=1)
vr = vv.repeat_interleave(H // KV, dim=1)
qh_c = qh.contiguous()

print(f"  repeated kv, masked : {bench(lambda: F.scaled_dot_product_attention(qh_c, kr, vr, attn_mask=mask)):6.2f} ms")
print(f"  enable_gqa, masked  : {bench(lambda: F.scaled_dot_product_attention(qh_c, kk, vv, attn_mask=mask, enable_gqa=True)):6.2f} ms")
print(f"  no mask             : {bench(lambda: F.scaled_dot_product_attention(qh_c, kr, vr)):6.2f} ms")
# the transposed (strided) query, which is what the engine passes
print(f"  strided q, masked   : {bench(lambda: F.scaled_dot_product_attention(qh, kr, vr, attn_mask=mask)):6.2f} ms")
print(f"  strided q, no mask  : {bench(lambda: F.scaled_dot_product_attention(qh, kr, vr)):6.2f} ms")
