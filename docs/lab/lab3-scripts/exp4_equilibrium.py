#!/usr/bin/env python3
"""EXP 4 -- Joules per fixed point: a toy equilibrium loop, warm-started vs cold.

Kimi's claims (round 3 brief):
    "Equilibrium/fixed-point loops with warm-starting (previous fixed point as
     initialization; 2-3 iterations to converge) and critics; three nested
     timescales."
    "Joules per fixed point as the governing metric, from the power rails."

and the brief's experiment 4:
    "Joules per fixed point on a toy equilibrium loop (a generator + a critic
     iterated to agreement, warm-started vs cold): iterations to converge and
     joules per converged result."

The loop modelled here is the shape the project actually wants:

    critic replies with its own reading  c(x) = gamma * conv(x) + b
    generator folds the reply in:        x <- x + eta * (c(x) - x)
    loop until the two agree:            ||c(x) - x|| < tol

c is a fixed 2-layer 3x3 CNN with a gain gamma < 1, so it is a contraction and
the loop has a unique fixed point x* with c(x*) = x*. The bias b makes x* a
non-trivial field rather than a constant. The weights are seeded and frozen --
the critic is a fixed function -- so every run is reproducible, which is the
project's "recipes, not meshes" rule.

Arms:
    cold        x0 = noise -- no previous fixed point available
    warm        x0 = x* + delta, for a ladder of delta magnitudes
    warm8       x0 = x* + delta, then quantised to 8 bits -- what a lossy
                warm-start store hands back (the video-codec arm is exp 5b)
    cold-cpu    the same loop with the critic on the CPU instead of the GPU --
                the "critic farm" has no accelerator of its own on this box
                (exp 1), so the critic either shares the GPU or runs on the CPU

Correction over the first run of this script: the convergence residual was
computed *after* the update, mixing two different points of the iteration.
The residual here is measured at the point being tested, so the reported
iteration count is the true number of critic evaluations to agreement.
"""

from __future__ import annotations

import json
import os
import sys
import time

import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boxstate import (PowerMeter, format_box_state, box_state,  # noqa: E402
                      gpu_clock_mhz, warm_gpu)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")


class Critic:
    """A fixed, deterministic critic: 2 conv3x3 layers + a bias field.

    The weights are seeded and frozen -- the critic is a fixed function, so
    the loop has a well-defined fixed point and every run is reproducible.
    """

    def __init__(self, channels: int, hw: int, gamma: float = 0.45, seed: int = 11):
        g = torch.Generator(device="cuda").manual_seed(seed)
        self.w1 = torch.randn(channels, 1, 3, 3, device="cuda", generator=g) * (1.0 / 9.0)
        self.w2 = torch.randn(channels, 1, 3, 3, device="cuda", generator=g) * (1.0 / 9.0)
        # stored as [C, H, W]; it is broadcast against the conv's [1, C, H, W]
        self.b = torch.randn(channels, hw, hw, device="cuda", generator=g) * 0.5
        self.gamma = gamma
        self.on_cpu = False

    def to_cpu(self):
        self.w1 = self.w1.cpu()
        self.w2 = self.w2.cpu()
        self.b = self.b.cpu()
        self.on_cpu = True

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        if self.on_cpu:
            x = x.cpu()
        # x is [C, H, W] and each channel has its own 3x3 kernel, so this is a
        # grouped convolution over the channel axis. (conv2d wants
        # [N, C, H, W]; without the grouping the channel count is read as the
        # input-channel count and the shape check fails.)
        c = self.w1.shape[0]
        y = F.conv2d(x.unsqueeze(0), self.w1, padding=1, groups=c)
        y = F.conv2d(y, self.w2, padding=1, groups=c)
        out = self.gamma * y + self.b.unsqueeze(0)
        return out.squeeze(0)


def run_loop(critic: Critic, x0: torch.Tensor, eta: float, tol: float,
             max_iter: int) -> tuple[int, torch.Tensor, list[float]]:
    """Iterate to agreement.

    The residual is measured at the point being tested (||c(x) - x|| at the
    current x), and the update is applied afterwards, so the returned field is
    the converged one and the iteration count is the number of critic calls.
    """
    x = x0.clone()
    hist = []
    for i in range(1, max_iter + 1):
        c = critic(x)
        r = float((c - x).abs().max())
        hist.append(r)
        if r < tol:
            return i, x, hist
        x = x + eta * (c - x)
    return max_iter, x, hist


def measure(critic: Critic, x0: torch.Tensor, eta: float, tol: float,
            max_iter: int, reps: int, min_window_s: float = 1.5) -> dict:
    """Run the loop `reps` times and integrate the rails over the whole window."""
    # untimed: iterations to converge, and the converged field
    iters, x_star, hist = run_loop(critic, x0, eta, tol, max_iter)

    with PowerMeter() as pm:
        torch.cuda.synchronize()
        t0 = pm.mark()
        done = 0
        deadline = time.perf_counter() + min_window_s
        while time.perf_counter() < deadline or done < 2:
            run_loop(critic, x0, eta, tol, max_iter)
            done += 1
        torch.cuda.synchronize()
        t1 = pm.mark()
        j_total = pm.joules_between("VIN_total", t0, t1)
        j_gpu = pm.joules_between("VDD_GPU", t0, t1)
        j_cpu = pm.joules_between("VDD_CPU_SOC_MSS", t0, t1)
        j_total_bl = pm.joules_above_baseline("VIN_total", t0, t1)
        j_gpu_bl = pm.joules_above_baseline("VDD_GPU", t0, t1)
        baseline = dict(pm.baseline_w)
        w_total = pm.watts_between("VIN_total", t0, t1)
        w_gpu = pm.watts_between("VDD_GPU", t0, t1)
        w_cpu = pm.watts_between("VDD_CPU_SOC_MSS", t0, t1)

    per_run_s = (t1 - t0) / done
    return {
        "iterations": iters,
        "final_residual": hist[-1] if hist else float("nan"),
        "residual_first": hist[0] if hist else float("nan"),
        "runs_measured": done,
        "seconds_per_run": per_run_s,
        "ms_per_iteration": per_run_s * 1000 / max(iters, 1),
        "joules_per_fixed_point_total": j_total / done,
        "joules_per_fixed_point_gpu": j_gpu / done,
        "joules_per_fixed_point_cpu_soc": j_cpu / done,
        "joules_per_iteration_total": j_total / done / max(iters, 1),
        "joules_per_fixed_point_total_above_baseline": j_total_bl / done,
        "joules_per_fixed_point_gpu_above_baseline": j_gpu_bl / done,
        "baseline_w": baseline,
        "mean_w_total": w_total,
        "mean_w_gpu": w_gpu,
        "mean_w_cpu_soc": w_cpu,
        "gpu_clock_mhz": gpu_clock_mhz(),
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    torch.backends.cuda.matmul.allow_tf32 = False

    CH, HW = 64, 512
    ETA = 0.9
    TOL = 2e-3
    MAX_ITER = 400

    print("=" * 78)
    print("EXP 4 -- joules per fixed point: equilibrium loop, warm vs cold")
    print("=" * 78)
    st = box_state()
    print(format_box_state(st))
    w = warm_gpu(seconds=2.0)
    print(f"  gpu clock warmed: {w['clock_before_mhz']:.0f} -> {w['clock_after_mhz']:.0f} MHz")

    critic = Critic(CH, HW)
    gen = torch.Generator(device="cuda").manual_seed(3)

    # the fixed point, found once (untimed)
    x_guess = torch.randn(CH, HW, HW, device="cuda", generator=gen) * 0.5
    it, x_star, _ = run_loop(critic, x_guess, ETA, TOL, 4000)
    print(f"\n  field {CH}x{HW}x{HW} fp32 ({CH*HW*HW*4/1024**2:.0f} MiB), eta={ETA}, tol={TOL}")
    print(f"  fixed point found in {it} iterations; "
          f"residual {float((critic(x_star)-x_star).abs().max()):.2e}")
    scale = float(x_star.abs().max())
    print(f"  |x*| max {scale:.4f}, mean |x*| {float(x_star.abs().mean()):.4f}")

    results = {"config": {"channels": CH, "hw": HW, "eta": ETA, "tol": TOL,
                          "max_iter": MAX_ITER, "fixed_point_iters": it},
               "arms": []}

    def arm(name: str, x0: torch.Tensor, note: str, cr: Critic | None = None) -> dict:
        r = measure(cr or critic, x0, ETA, TOL, MAX_ITER, reps=8)
        r["arm"] = name
        r["note"] = note
        results["arms"].append(r)
        print(f"    {name:16s} iters {r['iterations']:4d}  res {r['final_residual']:.2e}  "
              f"{r['ms_per_iteration']:7.2f} ms/iter  "
              f"J/fixed-point {r['joules_per_fixed_point_total']:8.3f}  "
              f"(GPU {r['joules_per_fixed_point_gpu']:7.3f})  "
              f"above-baseline {r['joules_per_fixed_point_total_above_baseline']:7.3f}  "
              f"{r['mean_w_total']:5.1f} W")
        return r

    print("\n--- arms ---")
    cold0 = torch.randn(CH, HW, HW, device="cuda", generator=gen) * 0.5
    arm("cold", cold0, "x0 = noise, no previous fixed point")

    warm_rows = []
    for rel in (0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0):
        d = torch.randn(CH, HW, HW, device="cuda", generator=gen)
        d = d / d.abs().max() * (rel * scale)
        r = arm(f"warm d={rel:g}", x_star + d, f"x0 = x* + {rel:g}*scale perturbation")
        warm_rows.append((rel, r))

    # a lossy warm-start store: 8-bit quantisation of the field
    print("\n--- warm start through a lossy store (8-bit) ---")
    for rel in (0.01, 0.1, 0.5):
        d = torch.randn(CH, HW, HW, device="cuda", generator=gen)
        d = d / d.abs().max() * (rel * scale)
        q = torch.round((x_star + d) / scale * 127.0) / 127.0 * scale
        arm(f"warm8 d={rel:g}", q, f"x0 = 8-bit-quantised (x* + {rel:g}*scale)")

    # the critic on the CPU: the "critic farm" has no accelerator of its own
    print("\n--- the critic on the CPU (no spare accelerator exists: exp 1) ---")
    cpu_critic = Critic(CH, HW)
    cpu_critic.to_cpu()
    arm("cold-cpu", cold0.cpu(), "cold start, critic on the CPU", cr=cpu_critic)

    # the headline comparison: cold vs a realistic warm start
    print("\n--- headline ---")
    cold = next(a for a in results["arms"] if a["arm"] == "cold")
    warm01 = next(a for a in results["arms"] if a["arm"] == "warm d=0.1")
    print(f"    cold      : {cold['iterations']:4d} iterations, "
          f"{cold['joules_per_fixed_point_total']:8.3f} J per fixed point")
    print(f"    warm d=0.1: {warm01['iterations']:4d} iterations, "
          f"{warm01['joules_per_fixed_point_total']:8.3f} J per fixed point")
    print(f"    -> warm start saves {cold['iterations']/max(warm01['iterations'],1):.1f}x the "
          f"iterations and {cold['joules_per_fixed_point_total']/max(warm01['joules_per_fixed_point_total'],1e-9):.1f}x the joules")

    # ---- the step size decides how much a warm start is worth. eta is the
    #      generator's trust in the critic; a small eta converges slowly and is
    #      where warm-starting pays. Kimi's "2-3 iterations" is a statement
    #      about the fast end of this sweep, not about all of it.
    print("\n--- step size (eta) vs cold and warm convergence ---")
    eta_sweep = []
    for eta in (0.2, 0.4, 0.6, 0.9):
        xc = torch.randn(CH, HW, HW, device="cuda", generator=gen) * 0.5
        d = torch.randn(CH, HW, HW, device="cuda", generator=gen)
        d = d / d.abs().max() * (0.1 * scale)
        rc = measure(critic, xc, eta, TOL, MAX_ITER, reps=6)
        rw = measure(critic, x_star + d, eta, TOL, MAX_ITER, reps=6)
        row = {"eta": eta,
               "cold_iters": rc["iterations"], "warm_iters": rw["iterations"],
               "cold_joules": rc["joules_per_fixed_point_total"],
               "warm_joules": rw["joules_per_fixed_point_total"],
               "iteration_saving": rc["iterations"] / max(rw["iterations"], 1),
               "joules_saving": rc["joules_per_fixed_point_total"]
               / max(rw["joules_per_fixed_point_total"], 1e-9)}
        eta_sweep.append(row)
        print(f"    eta={eta:4.1f}: cold {rc['iterations']:4d} iters / "
              f"{rc['joules_per_fixed_point_total']:7.3f} J   "
              f"warm {rw['iterations']:4d} iters / {rw['joules_per_fixed_point_total']:7.3f} J"
              f"   -> {row['iteration_saving']:4.1f}x fewer iters, "
              f"{row['joules_saving']:4.2f}x fewer joules")
        del xc, d
        torch.cuda.empty_cache()
    results["eta_sweep"] = eta_sweep

    # ---- is the cost per iteration, or a fixed overhead? Regress joules per
    #      fixed point on the iteration count across the eta sweep.
    pts = [(r["cold_iters"], r["cold_joules"]) for r in eta_sweep]
    pts += [(r["warm_iters"], r["warm_joules"]) for r in eta_sweep]
    if len(pts) >= 2:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        slope = (sum((x - mx) * (y - my) for x, y in pts) / den) if den else float("nan")
        intercept = my - slope * mx
        results["joules_vs_iterations_fit"] = {
            "joules_per_iteration": slope, "fixed_overhead_joules": intercept,
            "points": pts}
        print(f"\n  joules per fixed point = {intercept:.3f} + {slope:.3f} x iterations"
              f"   (the fixed part is the first iteration: kernel + allocator warm-up)")

    # how the joules scale with the field size -- the metric has to be per
    # result, and the field size is a free parameter of the design
    print("\n--- joules per fixed point vs field size ---")
    scaling = []
    for ch, hw in ((16, 256), (32, 384), (64, 512), (64, 768)):
        c2 = Critic(ch, hw)
        g2 = torch.Generator(device="cuda").manual_seed(3)
        xg = torch.randn(ch, hw, hw, device="cuda", generator=g2) * 0.5
        it2, xs2, _ = run_loop(c2, xg, ETA, TOL, 4000)
        xc = torch.randn(ch, hw, hw, device="cuda", generator=g2) * 0.5
        r2 = measure(c2, xc, ETA, TOL, MAX_ITER, reps=6)
        scaling.append({"channels": ch, "hw": hw,
                        "field_mib": ch * hw * hw * 4 / 1024 ** 2,
                        "fixed_point_iters": it2,
                        "cold_iters": r2["iterations"],
                        "joules_per_fixed_point": r2["joules_per_fixed_point_total"]})
        print(f"    {ch}x{hw}x{hw} ({ch*hw*hw*4/1024**2:6.0f} MiB): "
              f"{r2['iterations']:3d} iters, "
              f"{r2['joules_per_fixed_point_total']:8.3f} J per fixed point")
        del c2, xg, xs2, xc
        torch.cuda.empty_cache()
    results["size_scaling"] = scaling

    with open(os.path.join(OUT, "exp4_equilibrium.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nwrote {OUT}/exp4_equilibrium.json")


if __name__ == "__main__":
    main()
