#!/usr/bin/env python3
"""EXP 2 -- One shared model, N agents batched: where does batching stop being free?

Kimi's claims (round 3 brief):
    "One shared model, N agents batched: weights stream once per pass, so batching
     N agents costs ~the bandwidth of one; only compute scales."
    "FP4 as an iteration multiplier (bandwidth wall: T_pass ~= active_params x
     bytes/param / 273 GB/s). Our lab round 1 measured FP4 a no on this stack and
     FP8 1.6-1.7x: re-derive the real multiplier."

This script measures the claims directly on a resident model:

  * a LLaMA-shaped transformer decoder stack (RMSNorm, GQA, SwiGLU) held resident
    in unified memory and stepped with a batch dimension N;
  * four precision policies over the *same* weights:
      bf16    weights BF16, activations BF16                      (the reference)
      naive   weights FP8, activations BF16  (round 1's C4b path, rebuilt)
      fused   weights FP8, activations stay FP8 between GEMMs, NO activation scale
      scaled  weights FP8, activations FP8 with *calibrated per-tensor scales*
  * two KV-cache regimes -- S=1 (weights only, isolates the claim) and S=1024
    (a realistic agent context, where the cache grows with N).

Per (precision, S, N) it reports step latency, aggregate items/s, achieved
bandwidth against 273 GB/s (NVIDIA's spec for this module) and against the
plateau this experiment itself measures, the CPU-side issue time (to separate a
*launch-bound* step from a *bandwidth-bound* one), and joules per item read from
the rails.

Corrections over the first run of this script (kept, because both changed the
answer and both are easy to get wrong again):

  1. joules per item must divide the window's joules by (steps x N), not by N.
  2. grouped-query attention must NOT materialise a `repeat_interleave` copy of
     the KV cache -- that copy is 4x the cache and turns the S=1024 sweep into a
     measurement of the attention implementation, not of the model.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boxstate import (PowerMeter, format_box_state, box_state,  # noqa: E402
                      gpu_clock_mhz, warm_gpu)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
FP8 = torch.float8_e4m3fn
E4M3_MAX = 448.0


# ----------------------------------------------------------------- config

@dataclass
class Cfg:
    d_model: int = 2048
    n_layers: int = 16
    n_heads: int = 16
    n_kv_heads: int = 4
    head_dim: int = 128
    ffn: int = 8192
    ctx_weights: int = 1        # S for the "weights only" regime
    ctx_realistic: int = 1024   # S for the "realistic agent" regime


@dataclass
class Sweep:
    n_list: tuple = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
    n_list_realistic: tuple = (1, 2, 4, 8, 16, 32, 64, 128)
    reps: int = 20
    warmup: int = 5
    min_window_s: float = 1.5


# ------------------------------------------------------------------ model

class Stack:
    """A LLaMA-shaped decoder stack with flat weights, so the byte count is exact.

    BF16 path : torch.matmul in bfloat16.
    FP8 path  : every weight is float8_e4m3fn with a per-tensor scale, and the
                activations can stay in FP8 end to end. _scaled_mm with *per-tensor*
                scaling is the only configuration in torch 2.15 that can emit an
                FP8 output (rowwise scaling refuses), and that is exactly what
                makes the cast-free chain possible.

    The attention *core* (the two batched score matmuls) runs in BF16, because
    torch 2.15 has no FP8 batched-matmul path; the KV cache is therefore BF16.
    That costs nothing in weight traffic -- the core has no weights -- and it
    keeps the KV-byte accounting honest.

    The two stacks (bf16 and fp8) are built from the *same* generator seed, so
    they hold the same underlying weights: the FP8 stack is a quantization of
    the BF16 stack. That makes the numeric comparison exact in intent.
    """

    def __init__(self, cfg: Cfg, dtype: torch.dtype, seed: int = 0):
        self.cfg = cfg
        self.dtype = dtype
        self.is_fp8 = dtype == FP8
        g = torch.Generator(device="cuda").manual_seed(seed)
        d, kv, ff = cfg.d_model, cfg.n_kv_heads * cfg.head_dim, cfg.ffn

        def mk(out_f, in_f, scale=0.02):
            return torch.randn(out_f, in_f, device="cuda", dtype=torch.float32,
                               generator=g) * scale

        self.w: list[dict[str, torch.Tensor]] = []
        self.wscale: list[dict[str, float]] = []
        self.scale_t: list[dict[str, torch.Tensor]] = []
        for _ in range(cfg.n_layers):
            raw = {
                "q": mk(d, d), "k": mk(kv, d), "v": mk(kv, d), "o": mk(d, d),
                "gate": mk(ff, d), "up": mk(ff, d), "down": mk(d, ff),
            }
            if self.is_fp8:
                wq, sq, st = {}, {}, {}
                for k, v in raw.items():
                    s = float(v.abs().max()) / E4M3_MAX
                    wq[k] = (v / s).to(FP8)     # scale into e4m3's finite range
                    sq[k] = s                    # true value = fp8 value * s
                    # the scale tensors are allocated ONCE, here: creating them
                    # inside the timed loop is a synchronous H2D copy per GEMM,
                    # which costs more than the GEMM (see Part D trap 16).
                    st[k] = torch.tensor(s, device="cuda", dtype=torch.float32)
                self.w.append(wq)
                self.wscale.append(sq)
                self.scale_t.append(st)
            else:
                self.w.append({k: v.to(dtype) for k, v in raw.items()})
                self.wscale.append({k: 1.0 for k in raw})
                self.scale_t.append({k: None for k in raw})

        self.weight_bytes = sum(
            t.numel() * t.element_size() for layer in self.w for t in layer.values()
        )
        self.n_params = sum(t.numel() for layer in self.w for t in layer.values())

        self.norms = [
            {"n1": torch.ones(d, device="cuda", dtype=torch.float32),
             "n2": torch.ones(d, device="cuda", dtype=torch.float32)}
            for _ in range(cfg.n_layers)
        ]

        # per-tensor activation scales, filled in by calibrate() for the FP8 stack
        self.act_scales: list[dict[str, float]] = []
        self.act_scale_t: list[dict[str, torch.Tensor]] = []


def rmsnorm(x: torch.Tensor, gain: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    v = x.float().pow(2).mean(-1, keepdim=True)
    return (x.float() * torch.rsqrt(v + eps) * gain).to(x.dtype)


ONE_SCALAR = torch.ones((), device="cuda", dtype=torch.float32)


def _mm(a: torch.Tensor, w: torch.Tensor, scale_a: torch.Tensor,
        scale_b: torch.Tensor, out_dtype: torch.dtype) -> torch.Tensor:
    """a @ w.T, in whichever precision the weights are stored.

    `scale_a` / `scale_b` are pre-allocated 0-dim device tensors: allocating one
    here would be a synchronous H2D copy inside the timed region.
    """
    if w.dtype == FP8:
        return torch._scaled_mm(a, w.t(), scale_a, scale_b, out_dtype=out_dtype)
    return (a @ w.t()).to(out_dtype)


def _amax(x: torch.Tensor) -> float:
    return float(x.abs().max())


def forward(stack: Stack, x: torch.Tensor, kv_cache: torch.Tensor, pos: int,
            policy: str = "fused", collect: dict | None = None) -> torch.Tensor:
    """One decode step.

    x        : [N, d_model]      current token embedding of each agent
    kv_cache : [L, 2, N, kv_heads, S, head_dim]  (BF16)
    pos      : which slot the new token writes into
    policy   : "bf16"   weights BF16, activations BF16
               "naive"  weights FP8, every GEMM input cast from BF16 and every
                        GEMM output cast back to BF16  (round 1's C4b path)
               "fused"  weights FP8, activations stay FP8 *between* the GEMMs of a
                        block, with no activation scale at all
               "scaled" weights FP8, activations FP8 with calibrated per-tensor
                        scales, so nothing saturates e4m3's range
    collect  : if a dict, the per-layer activation maxima are recorded into it
               (used to calibrate the "scaled" policy)
    """
    cfg = stack.cfg
    N = x.shape[0]
    d, h, hd, kvh = cfg.d_model, cfg.n_heads, cfg.head_dim, cfg.n_kv_heads
    scale_att = 1.0 / math.sqrt(hd)
    fp8 = stack.is_fp8
    rep = h // kvh

    def to8(t: torch.Tensor) -> torch.Tensor:
        return t.to(FP8) if fp8 else t

    def to8s(t: torch.Tensor, s: float) -> torch.Tensor:
        """Quantize to FP8 with a per-tensor scale: value = fp8 * s."""
        return (t / s).to(FP8)

    for li in range(cfg.n_layers):
        w, sc, st, norms = stack.w[li], stack.wscale[li], stack.scale_t[li], stack.norms[li]
        ascale = stack.act_scales[li] if (fp8 and stack.act_scales) else None
        at = stack.act_scale_t[li] if (fp8 and stack.act_scale_t) else None

        # ---- attention projections
        hn = rmsnorm(x, norms["n1"])
        if collect is not None:
            collect.setdefault(li, {})["attn"] = _amax(hn)
        if fp8 and policy == "scaled":
            s = ascale["attn"]
            q = _mm(to8s(hn, s), w["q"], at["attn"], st["q"], torch.bfloat16)
            k = _mm(to8s(hn, s), w["k"], at["attn"], st["k"], torch.bfloat16)
            v = _mm(to8s(hn, s), w["v"], at["attn"], st["v"], torch.bfloat16)
        elif fp8 and policy == "fused":
            q = _mm(to8(hn), w["q"], ONE_SCALAR, st["q"], FP8)
            k = _mm(to8(hn), w["k"], ONE_SCALAR, st["k"], FP8)
            v = _mm(to8(hn), w["v"], ONE_SCALAR, st["v"], FP8)
        elif fp8:
            q = _mm(to8(hn), w["q"], ONE_SCALAR, st["q"], torch.bfloat16)
            k = _mm(to8(hn), w["k"], ONE_SCALAR, st["k"], torch.bfloat16)
            v = _mm(to8(hn), w["v"], ONE_SCALAR, st["v"], torch.bfloat16)
        else:
            q = _mm(hn, w["q"], ONE_SCALAR, st["q"], torch.bfloat16)
            k = _mm(hn, w["k"], ONE_SCALAR, st["k"], torch.bfloat16)
            v = _mm(hn, w["v"], ONE_SCALAR, st["v"], torch.bfloat16)
        q = q.reshape(N, h, hd)
        k = k.reshape(N, kvh, hd)
        v = v.reshape(N, kvh, hd)
        kv_cache[li, 0, :, :, pos, :] = k.to(torch.bfloat16)
        kv_cache[li, 1, :, :, pos, :] = v.to(torch.bfloat16)

        # ---- attention core (BF16: torch 2.15 has no FP8 batched matmul)
        #      grouped-query attention done with einsum: the KV cache is read
        #      ONCE, with no repeat_interleave copy of it.
        kk = kv_cache[li, 0, :, :, : pos + 1, :]          # [N, kvh, S', hd]
        vv = kv_cache[li, 1, :, :, : pos + 1, :]
        qb = q.to(torch.bfloat16).reshape(N, kvh, rep, hd)
        scores = torch.einsum("nkrd,nksd->nkrs", qb, kk) * scale_att
        p = torch.softmax(scores.float(), dim=-1).to(torch.bfloat16)
        ctx = torch.einsum("nkrs,nksd->nkrd", p, vv).reshape(N, d)
        if collect is not None:
            collect[li]["ctx"] = _amax(ctx)

        # ---- attention output projection
        if fp8 and policy == "scaled":
            s = ascale["ctx"]
            o = _mm(to8s(ctx, s), w["o"], at["ctx"], st["o"], torch.bfloat16)
        elif fp8 and policy == "fused":
            o = _mm(ctx.to(FP8), w["o"], ONE_SCALAR, st["o"], FP8)
        elif fp8:
            o = _mm(ctx.to(FP8), w["o"], ONE_SCALAR, st["o"], torch.bfloat16)
        else:
            o = _mm(ctx, w["o"], ONE_SCALAR, st["o"], torch.bfloat16)
        x = x + o.reshape(N, d).to(torch.bfloat16)

        # ---- MLP (SwiGLU)
        hn = rmsnorm(x, norms["n2"])
        if collect is not None:
            collect[li]["mlp"] = _amax(hn)
        if fp8 and policy == "scaled":
            s = ascale["mlp"]
            g = _mm(to8s(hn, s), w["gate"], at["mlp"], st["gate"], torch.bfloat16)
            u = _mm(to8s(hn, s), w["up"], at["mlp"], st["up"], torch.bfloat16)
        elif fp8 and policy == "fused":
            g = _mm(to8(hn), w["gate"], ONE_SCALAR, st["gate"], FP8)
            u = _mm(to8(hn), w["up"], ONE_SCALAR, st["up"], FP8)
        elif fp8:
            g = _mm(to8(hn), w["gate"], ONE_SCALAR, st["gate"], torch.bfloat16)
            u = _mm(to8(hn), w["up"], ONE_SCALAR, st["up"], torch.bfloat16)
        else:
            g = _mm(hn, w["gate"], ONE_SCALAR, st["gate"], torch.bfloat16)
            u = _mm(hn, w["up"], ONE_SCALAR, st["up"], torch.bfloat16)

        if fp8 and policy == "scaled":
            act = g * torch.nn.functional.silu(u)
            sa = ascale["act"]
            down = _mm(to8s(act, sa), w["down"], at["act"], st["down"], torch.bfloat16)
        elif fp8 and policy == "fused":
            # activations stay FP8 between the three GEMMs -- no cast at all
            act = (g.float() * torch.nn.functional.silu(u.float())).to(FP8)
            down = _mm(act, w["down"], ONE_SCALAR, st["down"], FP8)
        elif fp8:
            gb = g.to(torch.bfloat16)
            ub = u.to(torch.bfloat16)
            act = (gb * torch.nn.functional.silu(ub)).to(FP8)
            down = _mm(act, w["down"], ONE_SCALAR, st["down"], torch.bfloat16)
        else:
            gb = g.to(torch.bfloat16)
            ub = u.to(torch.bfloat16)
            act = gb * torch.nn.functional.silu(ub)
            down = _mm(act, w["down"], ONE_SCALAR, st["down"], torch.bfloat16)
        if collect is not None:
            collect[li]["act"] = _amax(act)
        x = x + down.reshape(N, d).to(torch.bfloat16)
    return x


# -------------------------------------------------------------- calibration

def calibrate(bf16_stack: Stack, fp8_stack: Stack, N: int = 8, S: int = 8,
              seed: int = 5) -> dict:
    """Per-tensor activation scales for the FP8 stack, from the BF16 reference.

    A real FP8 inference engine does exactly this: run a calibration set in
    high precision, record the per-tensor activation maxima, and derive one
    scale per tensor so that the maximum maps to e4m3's 448. The scale is then
    *static* -- it costs nothing at inference time.
    """
    cfg = bf16_stack.cfg
    g = torch.Generator(device="cuda").manual_seed(seed)
    x = torch.randn(N, cfg.d_model, device="cuda", dtype=torch.bfloat16, generator=g)
    kv = torch.zeros(cfg.n_layers, 2, N, cfg.n_kv_heads, S, cfg.head_dim,
                     device="cuda", dtype=torch.bfloat16)
    collect: dict = {}
    with torch.no_grad():
        forward(bf16_stack, x, kv, pos=S - 1, policy="bf16", collect=collect)

    scales, scale_t = [], []
    for li in range(cfg.n_layers):
        row, rowt = {}, {}
        for k in ("attn", "ctx", "mlp", "act"):
            a = collect[li][k]
            s = max(a, 1e-12) / E4M3_MAX
            row[k] = s
            rowt[k] = torch.tensor(s, device="cuda", dtype=torch.float32)
        scales.append(row)
        scale_t.append(rowt)
    fp8_stack.act_scales = scales
    fp8_stack.act_scale_t = scale_t
    return {"collect": collect, "scales": scales}


# ------------------------------------------------------------------ bench

def bench_one(stack: Stack, N: int, S: int, reps: int, warmup: int,
              policy: str = "fused", min_window_s: float = 1.5,
              rounds: int = 3) -> dict:
    cfg = stack.cfg
    fp8 = stack.is_fp8
    d, kvh, hd = cfg.d_model, cfg.n_kv_heads, cfg.head_dim

    kv_cache = torch.zeros(cfg.n_layers, 2, N, kvh, S, hd, device="cuda",
                           dtype=torch.bfloat16)
    x = torch.randn(N, d, device="cuda", dtype=torch.bfloat16)

    def one_step():
        return forward(stack, x, kv_cache, pos=S - 1, policy=policy)

    for _ in range(warmup):
        one_step()
    torch.cuda.synchronize()

    # Rounds, not one block: the GPU clock ramps with sustained load and decays
    # when idle, so a single timed block can be taken at the wrong clock.
    # Each round's median is a sample; the reported number is the median of the
    # round medians, and the spread across rounds is reported too.
    round_medians = []
    all_times = []
    for _ in range(rounds):
        times = []
        for _ in range(reps):
            s, e = torch.cuda.Event(True), torch.cuda.Event(True)
            s.record()
            one_step()
            e.record()
            torch.cuda.synchronize()
            times.append(s.elapsed_time(e) / 1000.0)
        times.sort()
        round_medians.append(times[len(times) // 2])
        all_times.extend(times)
    round_medians.sort()
    median = round_medians[len(round_medians) // 2]
    # The *least contended* round is the best estimator of the step time on a
    # shared box: other tenants steal GPU time and host time from some rounds
    # and not from others, so the minimum round median is the cleanest sample.
    best = round_medians[0]
    all_times.sort()

    # The CPU-side issue cost: how long the host spends *issuing* the step.
    # If this is close to the step time, the step is launch-bound, not
    # bandwidth-bound, and adding rows to the batch is nearly free.
    issue = []
    for _ in range(max(5, reps // 2)):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        one_step()
        issue.append(time.perf_counter() - t0)
    torch.cuda.synchronize()
    issue.sort()
    issue_med = issue[len(issue) // 2]

    # the joules window: a fixed *duration* of the measured region, so the INA
    # sampler (25 ms) always gets samples to integrate.
    with PowerMeter() as pm:
        torch.cuda.synchronize()
        t0 = pm.mark()
        count = 0
        deadline = time.perf_counter() + min_window_s
        while time.perf_counter() < deadline:
            one_step()
            count += 1
        torch.cuda.synchronize()
        t1 = pm.mark()
        j_total = pm.joules_between("VIN_total", t0, t1)
        j_gpu = pm.joules_between("VDD_GPU", t0, t1)
        j_total_bl = pm.joules_above_baseline("VIN_total", t0, t1)
        j_gpu_bl = pm.joules_above_baseline("VDD_GPU", t0, t1)
        w_total = pm.watts_between("VIN_total", t0, t1)
        w_gpu = pm.watts_between("VDD_GPU", t0, t1)
        box = pm.box
        baseline = dict(pm.baseline_w)

    weight_bytes = stack.weight_bytes
    kv_bytes = cfg.n_layers * 2 * N * kvh * S * hd * 2   # BF16 cache in both precisions
    total_bytes = weight_bytes + kv_bytes
    wb = weight_bytes / best / 1e9
    wb_median = weight_bytes / median / 1e9
    items = count * N

    return {
        "N": N, "S": S,
        "precision": "fp8_e4m3" if fp8 else "bf16",
        "policy": policy,
        "step_median_s": median,
        "step_best_round_s": best,
        "step_round_medians_s": round_medians,
        "step_min_s": all_times[0],
        "step_max_s": all_times[-1],
        "gpu_clock_mhz": gpu_clock_mhz(),
        "cpu_issue_median_s": issue_med,
        "launch_bound_ratio": issue_med / median if median else float("nan"),
        "items_per_s": N / median,
        "items_per_s_window": items / (t1 - t0),
        "window_steps": count,
        "window_items": items,
        "weight_bytes": weight_bytes,
        "weight_gb": weight_bytes / 1e9,
        "kv_gb": kv_bytes / 1e9,
        "weight_bw_gbs": wb,
        "weight_bw_gbs_median": wb_median,
        "total_bw_gbs": total_bytes / best / 1e9,
        "bw_vs_273_spec": wb / 273.0,
        "joules_total_window": j_total,
        "joules_gpu_window": j_gpu,
        "joules_per_item_total": j_total / items,
        "joules_per_item_gpu": j_gpu / items,
        "joules_per_item_total_above_baseline": j_total_bl / items,
        "joules_per_item_gpu_above_baseline": j_gpu_bl / items,
        "baseline_w": baseline,
        "mean_w_total": w_total,
        "mean_w_gpu": w_gpu,
        "wall_window_s": t1 - t0,
        "box_state": box,
    }


def numeric_error(stacks: dict, policy: str = "scaled") -> dict:
    """FP8 chain vs the BF16 chain on the same weights and the same input."""
    cfg = stacks["bf16"].cfg
    N, S = 4, 8
    kv_b = torch.zeros(cfg.n_layers, 2, N, cfg.n_kv_heads, S, cfg.head_dim,
                       device="cuda", dtype=torch.bfloat16)
    kv_f = torch.zeros(cfg.n_layers, 2, N, cfg.n_kv_heads, S, cfg.head_dim,
                       device="cuda", dtype=torch.bfloat16)
    torch.manual_seed(1)
    x_b = torch.randn(N, cfg.d_model, device="cuda", dtype=torch.bfloat16)
    y_b = forward(stacks["bf16"], x_b, kv_b, pos=S - 1).float()
    y_f = forward(stacks["fp8_e4m3"], x_b, kv_f, pos=S - 1, policy=policy).float()
    diff = (y_b - y_f).abs()
    denom = y_b.abs().max().item()
    # relative error against the *RMS* of the reference too: a max-relative
    # number on a residual stream can flatter or damn a policy unfairly.
    rms = float(torch.sqrt((diff ** 2).mean()) / torch.sqrt((y_b ** 2).mean()))
    return {"policy": policy, "max_abs": float(diff.max()), "ref_max": denom,
            "rel": float(diff.max() / denom) if denom else float("nan"),
            "rel_rms": rms}


def fp8_multiplier(tokens: int = 4096, min_window_s: float = 1.0) -> dict:
    """Re-derive the real FP8 multiplier, cleanly.

    Round 1's C4b measured "FP8 weights alone buy nothing (0.95x)" -- but that
    chain regenerated a fresh random weight matrix *inside the timed region*
    for every GEMM, so it measured randn + cast, not the matmul. This rebuilds
    the same 8 shapes as a real chain with the weights allocated once.

    Four variants over identical weights:
      bf16    : weights BF16, activations BF16
      naive   : weights FP8, activation cast to FP8 at every GEMM input
      fused   : weights FP8, activations stay FP8 between GEMMs, unit scales
      scaled  : weights FP8, activations FP8 with calibrated per-tensor scales,
                so that the GEMM output *is* the next GEMM's input representation
                (the scale_a = s_i/s_{i+1} trick) -- zero casts, no saturation
    """
    dims = [1280, 320, 640, 1280, 5120, 1280, 1920, 640, 1280]
    g = torch.Generator(device="cuda").manual_seed(7)
    weights = []
    for i in range(len(dims) - 1):
        din, dout = dims[i], dims[i + 1]
        w = torch.randn(dout, din, device="cuda", dtype=torch.float32, generator=g)
        w = w / math.sqrt(din)                      # keep the chain O(1)
        weights.append(w)

    x0 = torch.randn(tokens, dims[0], device="cuda", dtype=torch.float32, generator=g)

    # ---- BF16 reference, and a check that the chain stays inside e4m3's range
    wb = [w.to(torch.bfloat16) for w in weights]
    x0_bf16 = x0.to(torch.bfloat16)
    xb = x0_bf16
    acts, c = [], []
    amax = float(xb.abs().max())
    acts.append(amax)
    for i in range(len(wb)):
        xb = xb @ wb[i].t()
        acts.append(float(xb.abs().max()))
    chain_amax = max(acts)

    # ---- pre-quantised FP8 weights (allocated ONCE) and unit input scales
    wq, cw = [], []
    for w in weights:
        s = float(w.abs().max()) / E4M3_MAX
        wq.append((w / s).to(FP8))
        cw.append(s)
    scale_t = [torch.tensor(s, device="cuda", dtype=torch.float32) for s in cw]
    one = torch.ones((), device="cuda", dtype=torch.float32)

    # ---- calibrated activation scales, from the BF16 chain's own maxima
    act_scales = [max(a, 1e-12) / E4M3_MAX for a in acts]
    # GEMM i takes its input scaled by s_i and must deliver the output scaled by
    # s_{i+1}:  out = (x/s_i) @ (W/c) * alpha * c  ->  alpha = s_i / s_{i+1}
    alpha = [torch.tensor(act_scales[i] / act_scales[i + 1], device="cuda",
                           dtype=torch.float32) for i in range(len(wq))]

    # ---- the inputs every chain starts from are prepared ONCE, outside the
    #      timed region. chain_fused and chain_scaled would otherwise pay for
    #      their input cast inside the measurement, which is input preparation,
    #      not the thing being compared.
    x_in_fused = x0_bf16.to(FP8)
    x_in_scaled = (x0_bf16.float() / act_scales[0]).to(FP8)

    def chain_bf16():
        x = x0_bf16
        for i in range(len(wb)):
            x = x @ wb[i].t()
        return x

    def chain_naive():
        """FP8 weights; the activation is cast to FP8 at every GEMM input and the
        GEMM output comes back as BF16 -- two casts per layer."""
        x = x0_bf16
        for i in range(len(wq)):
            a = x.to(FP8)
            x = torch._scaled_mm(a, wq[i].t(), one, scale_t[i], out_dtype=torch.bfloat16)
        return x

    def chain_fused():
        """FP8 weights; the GEMM output IS the next GEMM's input, in FP8, with
        no cast and no rescale between them (unit activation scale)."""
        x = x_in_fused
        for i in range(len(wq)):
            x = torch._scaled_mm(x, wq[i].t(), one, scale_t[i], out_dtype=FP8)
        return x

    def chain_scaled():
        """FP8 weights; calibrated per-tensor activation scales, chosen so the
        GEMM output lands directly in the next GEMM's FP8 representation.

        The returned value is the *scaled* representation (the last scale
        factor is applied by chain_scaled_true); the reconstruction is kept
        OUT of the timed region, because it is a post-processing step the other
        three chains do not pay."""
        x = x_in_scaled
        for i in range(len(wq)):
            x = torch._scaled_mm(x, wq[i].t(), alpha[i], scale_t[i], out_dtype=FP8)
        return x

    def chain_scaled_true():
        return chain_scaled().float() * act_scales[-1]

    flops = 2 * tokens * sum(dims[i] * dims[i + 1] for i in range(len(dims) - 1))
    out = {"tokens": tokens, "flops": flops, "shapes": dims,
           "chain_amax": chain_amax, "e4m3_max": E4M3_MAX,
           "activations_fit_e4m3": chain_amax < E4M3_MAX,
           "act_scales": act_scales}

    variants = (("bf16", chain_bf16), ("naive", chain_naive),
                ("fused", chain_fused), ("scaled", chain_scaled))
    for _, fn in variants:
        for _ in range(3):
            fn()
    torch.cuda.synchronize()

    # Time in *interleaved rounds*: each round times every variant once, so no
    # variant can be penalised by being measured first (which on this box means
    # being measured at a lower GPU clock).
    per_round: dict[str, list[float]] = {n: [] for n, _ in variants}
    for _ in range(7):
        for name, fn in variants:
            s, e = torch.cuda.Event(True), torch.cuda.Event(True)
            s.record()
            fn()
            e.record()
            torch.cuda.synchronize()
            per_round[name].append(s.elapsed_time(e))

    for name, _ in variants:
        ts = sorted(per_round[name])
        med = ts[len(ts) // 2]
        out[name + "_ms"] = med
        out[name + "_ms_min"] = ts[0]
        out[name + "_ms_max"] = ts[-1]
        out[name + "_tflops"] = flops / (med / 1000.0) / 1e12

    # accuracy of each FP8 chain vs the bf16 chain
    ref = chain_bf16().float()
    for name, fn in (("naive", chain_naive), ("fused", chain_fused),
                     ("scaled", chain_scaled_true)):
        f = fn().float()
        out[name + "_max_abs"] = float((ref - f).abs().max())
        out[name + "_rel"] = float((ref - f).abs().max() / ref.abs().max())
        out[name + "_rel_rms"] = float(
            torch.sqrt(((ref - f) ** 2).mean()) / torch.sqrt((ref ** 2).mean()))

    out["speedup_naive_vs_bf16"] = out["bf16_ms"] / out["naive_ms"]
    out["speedup_fused_vs_bf16"] = out["bf16_ms"] / out["fused_ms"]
    out["speedup_scaled_vs_bf16"] = out["bf16_ms"] / out["scaled_ms"]
    out["speedup_fused_vs_naive"] = out["naive_ms"] / out["fused_ms"]
    out["speedup_scaled_vs_fused"] = out["fused_ms"] / out["scaled_ms"]

    # ---- per-shape breakdown: which GEMM shapes does FP8 actually help?
    per_shape = []
    for i in range(len(wq)):
        a = torch.randn(tokens, dims[i], device="cuda", dtype=torch.bfloat16)
        a8 = a.to(FP8)
        b16 = wb[i]
        b8 = wq[i]

        def t16():
            return a @ b16.t()

        def t8():
            return torch._scaled_mm(a8, b8.t(), one, scale_t[i], out_dtype=FP8)

        for _ in range(3):
            t16(); t8()
        torch.cuda.synchronize()
        ms16 = ms8 = 0.0
        for _ in range(5):
            s, e = torch.cuda.Event(True), torch.cuda.Event(True)
            s.record(); t16(); e.record(); torch.cuda.synchronize()
            ms16 += s.elapsed_time(e)
            s, e = torch.cuda.Event(True), torch.cuda.Event(True)
            s.record(); t8(); e.record(); torch.cuda.synchronize()
            ms8 += s.elapsed_time(e)
        fl = 2 * tokens * dims[i] * dims[i + 1]
        per_shape.append({
            "shape": [tokens, dims[i], dims[i + 1]],
            "gflop": fl / 1e9,
            "bf16_ms": ms16 / 5, "fp8_ms": ms8 / 5,
            "bf16_tflops": fl / (ms16 / 5 / 1000.0) / 1e12,
            "fp8_tflops": fl / (ms8 / 5 / 1000.0) / 1e12,
            "fp8_speedup": (ms16 / 5) / (ms8 / 5),
        })
        del a, a8
    out["per_shape"] = per_shape
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    cfg, sweep = Cfg(), Sweep()
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.manual_seed(0)

    results = {"config": asdict(cfg), "sweep": asdict(sweep), "runs": []}

    print("=" * 78)
    print("EXP 2 -- one shared model, N agents batched")
    print("=" * 78)
    st = box_state()
    print(format_box_state(st))

    # Ramp the GPU clock first. On this box the GPU idles at 315 MHz and takes
    # ~1.4 s of sustained load to reach its 1575 MHz maximum; a measurement
    # taken before that is 2.6x slow and measures the governor, not the code.
    w = warm_gpu(seconds=2.5)
    print(f"  gpu clock warmed: {w['clock_before_mhz']:.0f} -> "
          f"{w['clock_after_mhz']:.0f} MHz over {w['warm_seconds']} s")
    results["gpu_warmup"] = w

    stacks = {"bf16": Stack(cfg, torch.bfloat16), "fp8_e4m3": Stack(cfg, FP8)}
    for name, s in stacks.items():
        print(f"  {name:9s}: {s.n_params / 1e6:7.1f} M params, "
              f"{s.weight_bytes / 1e9:6.3f} GB of weights resident")

    cal = calibrate(stacks["bf16"], stacks["fp8_e4m3"])
    results["calibration"] = {"act_scales": cal["scales"],
                              "act_amax": {str(k): v for k, v in cal["collect"].items()}}
    print(f"  calibration: per-tensor activation scales from the BF16 reference "
          f"(layer 0: {cal['scales'][0]})")

    errors = {}
    for pol in ("naive", "fused", "scaled"):
        e = numeric_error(stacks, pol)
        errors[pol] = e
        print(f"  numeric check FP8[{pol:6s}] vs BF16 (same weights): "
              f"max abs {e['max_abs']:.4f}, rel(max) {e['rel']:.3%}, "
              f"rel(RMS) {e['rel_rms']:.3%}")
    results["fp8_vs_bf16_rel_error"] = errors

    print("\n" + "=" * 78)
    print("  FP8 MULTIPLIER, re-derived (round 1's C4b rebuilt correctly)")
    print("=" * 78)
    mult = fp8_multiplier(tokens=4096)
    results["fp8_multiplier"] = mult
    print(f"    chain {mult['shapes']} at {mult['tokens']} tokens, "
          f"{mult['flops'] / 1e9:.1f} GFLOP, activation amax "
          f"{mult['chain_amax']:.2f} (fits e4m3: {mult['activations_fit_e4m3']})")
    print(f"    bf16                 {mult['bf16_ms']:7.3f} ms  {mult['bf16_tflops']:7.1f} TFLOPS")
    print(f"    fp8 weights, cast/lyr{mult['naive_ms']:7.3f} ms  {mult['naive_tflops']:7.1f} TFLOPS"
          f"   -> {mult['speedup_naive_vs_bf16']:.2f}x bf16  (rel {mult['naive_rel']:.2%})")
    print(f"    fp8 weights+acts     {mult['fused_ms']:7.3f} ms  {mult['fused_tflops']:7.1f} TFLOPS"
          f"   -> {mult['speedup_fused_vs_bf16']:.2f}x bf16  (rel {mult['fused_rel']:.2%})")
    print(f"    fp8 w+acts, scaled   {mult['scaled_ms']:7.3f} ms  {mult['scaled_tflops']:7.1f} TFLOPS"
          f"   -> {mult['speedup_scaled_vs_bf16']:.2f}x bf16  (rel {mult['scaled_rel']:.2%})")

    # ---- the sweep. bf16 and the calibrated FP8 path get the full N sweep;
    #      the other two FP8 policies get a representative subset.
    series = [("bf16", "bf16", sweep.n_list),
              ("fp8_e4m3", "scaled", sweep.n_list),
              ("fp8_e4m3", "naive", (1, 8, 64)),
              ("fp8_e4m3", "fused", (1, 8, 64))]
    for prec, policy, nlist in series:
        stack = stacks[prec]
        nlist_small = [n for n in nlist if n <= 128]
        for S, nlist_s in ((cfg.ctx_weights, nlist),
                           (cfg.ctx_realistic, nlist_small)):
            print(f"\n--- {prec} [{policy}]  S={S}  "
                  f"(weights {stack.weight_bytes/1e9:.3f} GB) ---")
            for N in nlist_s:
                try:
                    r = bench_one(stack, N, S, sweep.reps, sweep.warmup, policy,
                                  sweep.min_window_s)
                except torch.cuda.OutOfMemoryError:
                    print(f"    N={N}: OOM -- stopping this series")
                    torch.cuda.empty_cache()
                    break
                results["runs"].append(r)
                print(f"    N={N:4d}  step {r['step_best_round_s']*1000:8.2f} ms  "
                      f"(median {r['step_median_s']*1000:7.2f})  "
                      f"items/s {r['items_per_s_window']:9.1f}  "
                      f"w-bw {r['weight_bw_gbs']:6.1f} GB/s "
                      f"({r['bw_vs_273_spec']:.2f}x spec)  "
                      f"clk {r['gpu_clock_mhz']:.0f}  "
                      f"cpu-issue {r['cpu_issue_median_s']*1000:6.2f} ms "
                      f"(launch-bound {r['launch_bound_ratio']:.2f})  "
                      f"J/item {r['joules_per_item_total']:7.4f}  {r['mean_w_total']:5.1f} W")
                torch.cuda.empty_cache()

    with open(os.path.join(OUT, "exp2_batched.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nwrote {OUT}/exp2_batched.json")


if __name__ == "__main__":
    with torch.no_grad():
        main()
