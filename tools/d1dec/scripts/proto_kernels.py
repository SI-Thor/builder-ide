#!/usr/bin/env python3
"""Prototype the two fused kernels: the short convolution and the rotary.

The profile says the short convolution and the rotary are 56% of the
forward pass, and neither of them is arithmetic the model needs — they
are the cost of materialising the intermediates in eager mode. This
tries the fused versions and checks that they give the same numbers.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

torch.manual_seed(0)

B, L, E, D_CONV, D_HEAD, KV = 64, 267, 2048, 6, 128, 4
dev = "cuda"


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


# ==========================================================================
# the short convolution
# ==========================================================================
print("=" * 70)
print("the short convolution")
print("=" * 70)

x = torch.randn(B, L, E, device=dev, dtype=torch.float16) * 0.1
conv_in = torch.randn(E, 3 * E, device=dev, dtype=torch.float16) / (E ** 0.5)
conv_w = torch.randn(D_CONV + 1, E, device=dev, dtype=torch.float16) / 7.0
conv_out = torch.randn(E, E, device=dev, dtype=torch.float16) / (E ** 0.5)


def conv_eager(t):
    """What the engine does now: fp32 grouped conv1d on a padded copy."""
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    bx = F.pad(bx, (D_CONV, 0))
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = F.conv1d(bx.float(), w.float(), groups=E)
    y = cc.float() * conv.transpose(1, 2)
    return y.to(torch.float16) @ conv_out


def conv_fp16(t):
    """The same arithmetic with the convolution in fp16.

    cuDNN's fp16 convolution accumulates in fp32, so this is ggml's
    ssm_conv_f32 with one rounding at the end instead of three.
    """
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    bx = F.pad(bx, (D_CONV, 0))
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = F.conv1d(bx, w, groups=E)
    y = (cc * conv.transpose(1, 2).to(torch.float16)).to(torch.float16)
    return y @ conv_out


def _conv_core(bx, cc, w):
    """The fused body: read bb*xx and cc, write y."""
    bx = bx.contiguous()
    L = bx.shape[-1]
    acc = torch.zeros(bx.shape[0], bx.shape[1], L, device=bx.device, dtype=torch.float32)
    for k in range(w.shape[-1]):
        acc += w[..., k].float() * bx[..., k : k + L].float()
    return (cc.float() * acc).to(torch.float16)


def conv_compiled(t):
    bcx = t @ conv_in
    bb, cc, xx = torch.chunk(bcx, 3, dim=-1)
    bx = (bb * xx).transpose(1, 2)
    bx = F.pad(bx, (D_CONV, 0))
    w = conv_w.transpose(0, 1).unsqueeze(1).contiguous()
    conv = _conv_core(bx, cc, w)
    return conv @ conv_out


ref = conv_eager(x).float()
for name, fn in (("fp16 conv1d", conv_fp16), ("compiled", conv_compiled)):
    try:
        got = fn(x).float()
        err = (got - ref).abs().max().item()
        rel = ((got - ref).norm() / ref.norm()).item()
        t = bench(lambda: fn(x))
        print(f"  {name:14s} {t:7.2f} ms   max abs err {err:.3e}   rel {rel:.3e}")
    except Exception as exc:
        print(f"  {name:14s} FAILED: {type(exc).__name__}: {exc}")

t_eager = bench(lambda: conv_eager(x))
print(f"  {'eager (now)':14s} {t_eager:7.2f} ms")

# ==========================================================================
# the rotary
# ==========================================================================
print()
print("=" * 70)
print("the rotary")
print("=" * 70)

H = 16
q = torch.randn(B, H, L, D_HEAD, device=dev, dtype=torch.float16) * 0.1
pos = torch.arange(L, device=dev).expand(B, L)
base = (1000000.0 ** (-2.0 / 128)) ** torch.arange(64, device=dev, dtype=torch.float32)
theta = pos.float().unsqueeze(-1) * base.unsqueeze(0).unsqueeze(0)
cos = theta.cos().unsqueeze(1)
sin = theta.sin().unsqueeze(1)


def rope_eager(x, cos, sin):
    d = x.shape[-1] // 2
    x0 = x[..., :d].float()
    x1 = x[..., d:].float()
    out0 = x0 * cos - x1 * sin
    out1 = x0 * sin + x1 * cos
    return torch.cat([out0, out1], dim=-1).to(x.dtype)


def _rope_core(x, cos, sin):
    d = x.shape[-1] // 2
    x0 = x[..., :d].float()
    x1 = x[..., d:].float()
    out0 = x0 * cos - x1 * sin
    out1 = x0 * sin + x1 * cos
    return torch.cat([out0, out1], dim=-1).to(x.dtype)


ref_r = rope_eager(q, cos, sin).float()
t_eager = bench(lambda: rope_eager(q, cos, sin))
print(f"  {'eager (now)':14s} {t_eager:7.2f} ms")

try:
    compiled = torch.compile(_rope_core, dynamic=False)
    got = compiled(q, cos, sin).float()
    err = (got - ref_r).abs().max().item()
    t = bench(lambda: compiled(q, cos, sin))
    print(f"  {'compiled':14s} {t:7.2f} ms   max abs err {err:.3e}")
except Exception as exc:
    print(f"  compiled FAILED: {type(exc).__name__}: {exc}")

# -- the same rotary, but in the layout the model already has -------------
# the model makes q [B, L, H, D] and then transposes it to [B, H, L, D].
# the rope could run before the transpose, on the smaller strided view.
def rope_eager_nt(x, cos, sin):
    d = x.shape[-1] // 2
    x0 = x[..., :d].float()
    x1 = x[..., d:].float()
    out0 = x0 * cos - x1 * sin
    out1 = x0 * sin + x1 * cos
    return torch.cat([out0, out1], dim=-1).to(x.dtype)


q_nt = q.transpose(1, 2).contiguous()
cos_nt = cos.transpose(1, 2).contiguous()
sin_nt = sin.transpose(1, 2).contiguous()
print(f"  {'eager (nt)':14s} {bench(lambda: rope_eager_nt(q_nt, cos_nt, sin_nt)):7.2f} ms")

# -- a rotary with the cos/sin folded into one table ----------------------
# ggml computes cos and sin of the same angle; a fused kernel reads one
# table of (cos, sin) pairs instead of two.
def rope_compiled_pairs(x, cs):
    d = x.shape[-1] // 2
    x0 = x[..., :d].float()
    x1 = x[..., d:].float()
    cos, sin = cs[..., 0], cs[..., 1]
    out0 = x0 * cos - x1 * sin
    out1 = x0 * sin + x1 * cos
    return torch.cat([out0, out1], dim=-1).to(x.dtype)


cs = torch.stack([cos, sin], dim=-1).contiguous()
try:
    compiled2 = torch.compile(_rope_core, dynamic=False)
    t = bench(lambda: compiled2(q, cos, sin))
    print(f"  {'compiled again':14s} {t:7.2f} ms  (the warm shape)")
except Exception as exc:
    print(exc)

# ==========================================================================
# the attention: masked vs not
# ==========================================================================
print()
print("=" * 70)
print("the attention")
print("=" * 70)

kk = torch.randn(B, KV, L, D_HEAD, device=dev, dtype=torch.float16)
vv = torch.randn(B, KV, L, D_HEAD, device=dev, dtype=torch.float16)
mask = torch.ones(B, 1, L, L, dtype=torch.bool, device=dev).tril()
kr = kk.repeat_interleave(H // KV, dim=1)
vr = vv.repeat_interleave(H // KV, dim=1)

print(f"  masked, repeated  : {bench(lambda: F.scaled_dot_product_attention(q, kr, vr, attn_mask=mask)):6.2f} ms")
print(f"  masked, enable_gqa: {bench(lambda: F.scaled_dot_product_attention(q, kk, vv, attn_mask=mask, enable_gqa=True)):6.2f} ms")
print(f"  unmasked          : {bench(lambda: F.scaled_dot_product_attention(q, kr, vr)):6.2f} ms")

# the flex attention with a document mask: the dense layers only ever
# look at their own sequence
try:
    from torch.nn.attention.flex_attention import create_block_mask, flex_attention

    def doc_mask(b, h, q_idx, kv_idx):
        return (q_idx // 1) >= 0  # placeholder, replaced below

    # a real document mask: every token belongs to a sequence of L tokens
    seq_ids = torch.arange(B, device=dev).repeat_interleave(L)
    def flex_mask(b, h, q_idx, kv_idx):
        return seq_ids[q_idx] == seq_ids[kv_idx]

    bm = create_block_mask(flex_mask, B, H, L, L, device=dev)
    flex = torch.compile(flex_attention, dynamic=False)
    got = flex(q, kr, vr, block_mask=bm)
    ref_a = F.scaled_dot_product_attention(q, kr, vr, attn_mask=mask)
    print(f"  flex (document)   : {bench(lambda: flex(q, kr, vr, block_mask=bm)):6.2f} ms"
          f"   max abs err vs masked {(got - ref_a).abs().max().item():.3e}")
except Exception as exc:
    print(f"  flex FAILED: {type(exc).__name__}: {exc}")
