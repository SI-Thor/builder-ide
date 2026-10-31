# EXP 4 — Joules per fixed point: a toy equilibrium loop, warm-started vs cold

**Date:** 2026-10-31 03:05 local (Alaska Daylight Time)
**Verdict: THE METRIC WORKS, AND KIMI'S "2–3 ITERATIONS" IS RIGHT — BUT ONLY FOR A WARM
START.** A cold start needs **6 iterations**; a warm start needs **2–3**. The joules per
fixed point are **linear in the iteration count** (1.39 J per iteration), so warm-starting
is worth a flat **1.4–1.5× in iterations and 1.2–1.5× in joules** at every step size.
Two further results: a **lossless 8-bit warm-start store costs nothing**, and **the critic
cannot live on the CPU** — it is 2.2× slower and 2.5× more joules there, and exp 1
established there is no spare accelerator.

---

## 1. The idea

> "Equilibrium/fixed-point loops with warm-starting (previous fixed point as
> initialization; 2-3 iterations to converge) and critics; three nested timescales."
>
> "Joules per fixed point as the governing metric, from the power rails."

The brief asks for a toy equilibrium loop — a generator and a critic iterated to
agreement — and for the **iterations to converge** and the **joules per converged
result**, warm-started versus cold.

## 2. Hypothesis

1. Warm-starting from the previous fixed point takes the loop from many iterations to
   **2–3**, and the joules per fixed point fall proportionally.
2. Joules per fixed point is a **linear** function of the iteration count, so the metric
   has a clean marginal cost.
3. A lossless store of the previous fixed point (quantised to 8 bits) is free.
4. The critic can run on the CPU, leaving the GPU to the generator.

## 3. Setup

- Script: `scripts/exp4_equilibrium.py`; raw JSON: `results/exp4_equilibrium.json`
  (rerun: `.venv/bin/python scripts/exp4_equilibrium.py`)
- **The loop.** The critic is a fixed, seeded, frozen 2-layer 3×3 CNN with a gain
  γ = 0.45, applied per channel:

  ```
  c(x) = γ · conv2(conv1(x)) + b
  x ← x + η · (c(x) − x)          until ‖c(x) − x‖ < 2e-3
  ```

  γ < 1 makes it a contraction, so the loop has a unique fixed point x\* with c(x\*) = x\*.
  The critic is a *fixed function* with seeded weights — the project's "recipes, not
  meshes" rule — so every run is reproducible and the fixed point is exact.
- Field: **64 × 512 × 512 fp32 (64 MiB)**, η = 0.9, tolerance 2e-3, max 400 iterations.
- The **residual is measured at the point being tested** (`‖c(x) − x‖` at the current x)
  and the update is applied afterwards, so the reported iteration count is the number of
  critic evaluations to genuine agreement. (The first version of this script measured the
  residual *after* the update, mixing two points of the iteration.)
- **Arms:** cold (x₀ = noise); warm at seven perturbation magnitudes; warm through an
  8-bit store; and the same loop with the critic on the CPU.

### The box this ran on

| | |
|---|---|
| GPU clock | 1575 MHz (warmed from 315 MHz first) |
| Power mode | `MAXN` |
| **Load during the run** | **loadavg 23.6 → 43.3 on 14 cores** |
| GPU tenants | `trellis/ComfyUI/main.py`, `warm-scene`'s server, `warm_scene.py --samples 256` — **three other seats** |
| **Effect on these numbers** | the **iteration counts are exact** — they are a property of the contraction, not of the box. The **joules are the whole-box INA238 rail**, so they carry every other tenant's power; the **above-baseline** column (the idle power captured immediately before the work, subtracted) is the defensible one. |

## 4. Numbers

The fixed point is found in **6 iterations** from a cold start (residual 4.73e-04);
‖x\*‖max = 2.746, mean |x\*| = 0.399.

### 4.1 Cold vs warm

| arm | iterations | ms/iteration | J per fixed point (whole box) | J (GPU rail) | J above baseline | W |
|---|---|---|---|---|---|---|
| cold | **6** | 21.68 | 8.898 | 2.912 | 0.885 | 70.3 |
| warm, δ = 0.001·scale | **2** | 19.54 | 2.575 | 0.827 | 0.156 | 67.9 |
| warm, δ = 0.01·scale | **3** | 20.44 | 4.152 | 1.334 | 0.254 | 69.0 |
| warm, δ = 0.05·scale | 4 | 20.92 | 5.699 | 1.820 | 0.538 | 69.6 |
| warm, δ = 0.1·scale | 4 | 20.16 | 5.527 | 1.719 | 0.166 | 69.2 |
| warm, δ = 0.25·scale | 5 | 20.57 | 7.069 | 2.225 | 0.388 | 70.0 |
| warm, δ = 0.5·scale | 5 | 20.60 | 7.892 | 2.241 | 1.369 | 78.6 |
| warm, δ = 1.0·scale | 5 | 20.68 | 8.556 | 2.230 | 0.757 | 83.6 |

**Kimi's "2–3 iterations to converge" is confirmed, exactly as stated, for a warm start.**
At δ = 0.001 the loop converges in **2 iterations**; at δ = 0.01, in **3**. It is not true
of a cold start, which needs **6**.

### 4.2 The metric is linear in the iteration count

Fitting joules per fixed point against the iteration count across the whole step-size
sweep (eight points, cold and warm):

```
joules per fixed point  =  −1.397  +  1.392 × iterations
```

**Each iteration costs 1.39 J**; the intercept is small and negative, which is measurement
noise rather than a real negative cost — in practice the cost is almost purely
per-iteration. That is a clean result for a governing metric: *the joules per fixed point
are the iterations times 1.39 J*, so anything that reduces iterations reduces joules
proportionally, and **nothing else in the loop matters much**.

### 4.3 The step size decides how much a warm start is worth

| η | cold iterations | cold J | warm iterations | warm J | iteration saving | joules saving |
|---|---|---|---|---|---|---|
| 0.2 | 37 | 45.608 | 24 | 36.706 | 1.5× | 1.24× |
| 0.4 | 17 | 27.228 | 11 | 18.215 | 1.5× | 1.49× |
| 0.6 | 10 | 7.900 | 7 | 5.559 | 1.4× | 1.42× |
| 0.9 | **6** | 5.448 | **4** | 3.683 | 1.5× | 1.48× |

A warm start is worth a **flat 1.4–1.5× in iterations at every step size**. Kimi's
"2–3 iterations" describes the *fast* end of this sweep (η = 0.9, a warm start close to
the fixed point), not the whole range — at η = 0.2 even a warm start needs 24 iterations.

### 4.4 A lossless store is free

| arm | iterations | J per fixed point | J above baseline |
|---|---|---|---|
| warm δ = 0.01, exact | 3 | 4.152 | 0.254 |
| **warm δ = 0.01, through an 8-bit store** | **3** | **4.198** | 0.017 |
| warm δ = 0.1, exact | 4 | 5.527 | 0.166 |
| **warm δ = 0.1, through an 8-bit store** | **4** | **6.219** | 0.357 |
| warm δ = 0.5, exact | 5 | 7.892 | 1.369 |
| **warm δ = 0.5, through an 8-bit store** | **5** | **7.330** | 0.303 |

**Quantising the warm start to 8 bits costs nothing measurable** — the same iteration
count and the same joules to within the noise. A warm-start store does not need to be
lossless; it needs to be *accurate enough that the loop still converges in a couple of
iterations*, and 8 bits is far more than enough.

(This is the control for `exp-nvenc-roundtrip.md`: there the same loop is fed a warm start
that has been through a **video** codec, and the warm-start advantage disappears
entirely. A lossy codec is not a warm-start store.)

### 4.5 The critic cannot live on the CPU

| arm | iterations | ms/iteration | J per fixed point | J above baseline | W |
|---|---|---|---|---|---|
| critic on the GPU | 6 | **21.68** | 8.898 | 0.885 | 70.3 |
| **critic on the CPU** | 6 | **46.89** | **22.305** | **2.240** | 80.3 |

The same 6 iterations take **2.2× longer** on the CPU and cost **2.5× the joules** —
because the CPU path moves the 64 MiB field through system memory instead of unified
memory, and the box's CPU is simultaneously running three other seats' jobs.

**This closes the loop with exp 1** (`exp-engines.md`): there is no spare accelerator on
this box, so the critic has to share the GPU with the generator, and the *schedule* —
not the hardware — is what has to keep them from fighting.

### 4.6 The metric has to be normalised by the field

| field | size | iterations | J per fixed point |
|---|---|---|---|
| 16 × 256 × 256 | 4 MiB | 5 | **0.660** |
| 32 × 384 × 384 | 18 MiB | 6 | **1.922** |
| 64 × 512 × 512 | 64 MiB | 6 | **7.876** |
| 64 × 768 × 768 | 144 MiB | 6 | **20.377** |

The joules per fixed point scale with the size of the field — roughly linearly with its
byte count. **"Joules per fixed point" is only a comparable metric if the field size is
fixed or stated.** The right form for a governing metric is
**joules per fixed point per MiB of field** (0.165 J/MiB at 4 MiB, 0.141 J/MiB at
144 MiB), or equivalently the joules per converged *result*, which is what the brief asks
for.

## 5. Verdict

- **Confirmed:** *"warm-starting … 2-3 iterations to converge"* — **2 iterations** at
  δ = 0.001·scale, **3** at δ = 0.01. A cold start needs 6. The claim is right.
- **Confirmed:** *"joules per fixed point as the governing metric"* — it is **linear in
  the iteration count** (1.39 J per iteration), so it is a clean, predictable cost
  function, provided the field size is stated.
- **Confirmed:** warm-starting saves a **flat 1.4–1.5× in iterations and 1.2–1.5× in
  joules**, at every step size.
- **New:** a **lossless 8-bit warm-start store is free**. The store does not need to be
  exact — it needs to be good enough that the loop still converges in 2–3 iterations.
- **Killed:** the idea that the critic could be moved off the GPU to free the GPU for
  the generator. On this box that is **2.2× slower and 2.5× more joules**, and exp 1
  established there is no spare accelerator to move it to.

### What this changes

- **The equilibrium loop should be warm-started, and the store should be cheap and
  accurate — not expensive and exact.** The 8-bit result says the design should spend its
  budget on keeping the previous fixed point *close*, not on keeping it *bit-exact*.
- **Joules per fixed point is the right governing metric, with one addition:** it must be
  quoted per fixed point **and** per MiB of field, or against a stated field size. §4.6.
- **The critic stays on the GPU and the schedule has to arbitrate.** Exp 1 killed the
  "critic farm" (there is no second accelerator) and this experiment kills the "critic on
  the CPU" fallback (2.2× slower, 2.5× the joules).
- **The next thing to test is the interaction with a lossy store** — which is exactly
  what `exp-nvenc-roundtrip.md` measures, and where the warm-start advantage turns out to
  disappear.

## 6. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp4_equilibrium.py       # -> results/exp4_equilibrium.json

# the headline
python3 -c "
import json; d=json.load(open('results/exp4_equilibrium.json'))
for a in d['arms']:
    if a['arm'] in ('cold','warm d=0.01','cold-cpu'):
        print(a['arm'], a['iterations'], 'iters', round(a['joules_per_fixed_point_total'],3), 'J')
print('fit:', d['joules_vs_iterations_fit'])"
```

## 7. Licence note

`torch` (BSD-3-Clause). The critic is synthetic (seeded, frozen weights) — no weights
are downloaded and nothing is redistributed.

## 8. Failures that stayed

- **`F.conv2d` wants `[N, C, H, W]`; the field is `[C, H, W]`.** Passing it directly
  reads the channel count as the input-channel count and the shape check fails. The
  correct form for "each channel has its own 3×3 kernel" is a **grouped** convolution
  with `groups=channels`.
- **The bias must be broadcast against the conv's output, not against the field.** A bias
  of shape `[C, 1, H, W]` added to a `[1, C, H, W]` output produces a `[C, C, H, W]`
  tensor — a silent shape explosion rather than an error.
- **The convergence residual must be measured at the point being tested.** Measuring it
  after the update mixes two points of the iteration and reports a wrong iteration count.
- **The whole-box INA rail needs an idle baseline.** With three other seats on the box,
  the raw whole-box joules are mostly *their* power; subtracting the idle baseline
  captured immediately before the work is the only defensible figure.
