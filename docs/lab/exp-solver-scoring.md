# EXP 5 — one Infinigen solver stage's scoring function: Python vs numba vs Warp vs a restructured CPU

**Date:** 2026-10-31 00:20 local (Alaska Daylight Time)
**Verdict: USEFUL — with a condition.** The GPU port of the scoring function is
**3,394× the current Python path** at a batch of 16,384 candidates
(47.95 M candidates/s), which clears the kill condition by a wide margin. But
**at the solver's actual call pattern — one candidate per annealing step — the
*restructured CPU* beats the GPU** (0.04 ms vs 0.30 ms). The GPU is the right
engine only if the solver is **restructured to propose a batch**; that
restructuring is the actual finding.

---

## 1. The idea

`IDEAS.md` idea #3 / Part C item #5: "Extract one solver stage's scoring
function; time Python vs numba vs Warp vs a restructured CPU version." Round 1's
Rule 1 says a GPU port must beat a **restructured** CPU, not the current one —
so the restructured CPU is a first-class implementation here, not an
afterthought.

## 2. Hypothesis

The solver's inner loop is a *scoring* loop: propose a candidate placement,
score it, accept or reject. The scoring is numeric and embarrassingly parallel,
so it should move to the GPU — **provided the solver is willing to score a
batch of candidates at once**. If the GPU only wins against the *current* Python
and loses to a restructured CPU, the idea is dead.

## 3. The function, extracted

From the Infinigen tree (read-only; nothing there was edited):

| what | where |
|---|---|
| the score term | `src/infinigen/core/constraints/constraint_language/geometry.py:56` — `class angle_alignment_cost(ScalarExpression)` |
| its implementation | `src/infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py:583` — `angle_alignment_cost_base(state, a, b, …)` |
| the edge search it calls | `src/infinigen/core/constraints/constraint_language/util.py:88` — `closest_edge_to_point_edge_list(edge_list, point)` |
| how it is bound | `evaluator/node_impl/impl_bindings.py:171` — `@register_node_impl(cl.angle_alignment_cost)` |

Its numeric core, per candidate object A:

```
1. axis      = A's front axis, XY components                    (get_axis, :80)
2. centroid  = A's XY centroid (projected polygon centroid)
3. closest   = the edge of B nearest to that centroid            (util.py:88)
4. n1        = normalize((dy, -dx)) of that edge, n2 = -n1        (:649-658)
5. score    += min(-dot(axis,n1)/2 + 0.5, -dot(axis,n2)/2 + 0.5) (:660-666)
```

The solver calls this on **every** proposal, **one candidate at a time**
(`SimulatedAnnealingSolver.step` → `evaluate_problem` → `evaluate_node` →
`angle_alignment_impl`). The GPU opportunity is that the *scoring* of a batch of
candidates need not be sequential — only the accept/reject decision does. So the
benchmark scores a **batch of candidate poses** at once.

**The scene**: a 6 m room with 48 placed objects, **E = 207 footprint edges**,
and candidates drawn as random (x, y, θ) poses of an object being placed. The
footprints are rectangles and chamfered rectangles — what Infinigen interiors
actually place. The *scoring function* is Infinigen's; the *geometry* is a
faithful stand-in (the real scene needs the asset library).

## 4. The five implementations

| | what it is |
|---|---|
| **python-shapely** | **what Infinigen does today** — `shapely.LineString.distance(point)` per edge, exactly `closest_edge_to_point_edge_list` |
| **python-pure** | the same arithmetic without shapely — a lower bound on "the Python" |
| **numba** | 14-core `prange` over candidates |
| **warp** | one GPU thread per candidate, float32 |
| **numpy-vec** | **restructured CPU #1** — same work, better layout (broadcast candidates × edges) |
| **grid** | **restructured CPU #2** — the same, plus a spatial broad phase (uniform grid over the edges, only nearby edges tested) |

**The box's state, beside the numbers:**

| | |
|---|---|
| Timestamp | 2026-10-31T00:20 local |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / 115.32 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` | 0 % GPU util at start, 2.36 W, 36 °C, 315 MHz |
| `tegrastats` RAM | 47,637–59,728 / 125,749 MB |
| loadavg (1/5/15) | **39.86 / 44.54 / 26.62** (another seat's build; load 32–38 during the measurements) |
| `jetson_clocks` | present, **not** locked |

This experiment was run **three times** at loads of ≈ 14, ≈ 62 and ≈ 38. The
GPU numbers are **stable across all three** (0.19–0.36 ms at every batch size);
the CPU numbers move by up to 5× with the load (numba's thread start-up at
batch size 1 is the worst case: 0.26 ms at load 38, 4.75 ms at load 62). The
numbers below are from the load ≈ 38 run, which is the canonical one saved in
`results/exp-solver-scoring.txt`.

## 5. The numbers

### 5.1 — wall time per batch (ms, median of 3 after a warm-up)

| N candidates | python | **shapely (today)** | numba (14 cores) | **warp (GPU)** | numpy-vec | grid |
|---|---|---|---|---|---|---|
| 1 | 0.21 | **0.93** | 0.26 | 0.30 | **0.04** | 0.14 |
| 8 | 1.64 | **1.42** | 0.66 | 0.20 | **0.05** | 0.16 |
| 64 | 13.08 | **5.39** | 0.70 | 0.19 | 0.16 | 0.38 |
| 256 | 52.28 | **19.01** | 0.78 | 0.20 | 0.53 | 2.36 |
| 1,024 | 209.05 | **73.35** | 1.20 | 0.25 | 2.11 | 9.26 |
| 4,096 | 840.22 | **291.08** | 3.22 | 0.25 | 8.20 | 29.81 |
| 16,384 | 3390.68 | **1159.77** | 9.12 | **0.34** | 33.02 | 99.25 |

Load beside each row: 37.63 → 35.58 → 32.88.

### 5.2 — throughput (candidates scored per second)

| N | python | **shapely (today)** | numba | **warp** | numpy-vec | grid |
|---|---|---|---|---|---|---|
| 1 | 4,826 | **1,074** | 3,921 | 3,338 | 24,675 | 7,258 |
| 8 | 4,887 | **5,643** | 12,097 | 40,657 | 166,476 | 49,052 |
| 64 | 4,894 | **11,879** | 91,554 | 328,486 | **406,133** | 169,458 |
| 256 | 4,897 | **13,467** | 326,162 | **1,250,366** | 484,433 | 108,503 |
| 1,024 | 4,898 | **13,960** | 850,455 | **4,167,633** | 485,148 | 110,602 |
| 4,096 | 4,875 | **14,072** | 1,273,606 | **16,690,640** | 499,227 | 137,414 |
| 16,384 | 4,832 | **14,127** | 1,796,002 | **47,953,405** | 496,136 | 165,072 |

**Warp vs the current Python at N = 16,384: 47,953,405 / 14,127 = 3,394×.**
The kill condition ("kill it if the GPU is not ≥ 5× faster than the current
Python") is cleared by a factor of 680.

**But against the *restructured* CPU (Rule 1's actual bar):** Warp is 97× the
vectorised numpy at N = 16,384, and **1.2× *slower* at N = 64** (328,486 vs
406,133 candidates/s).

### 5.3 — the crossover, and the solver's real call pattern

| N | shapely | numba | warp | grid |
|---|---|---|---|---|
| 1 | 0.931 ms/cand | 0.255 | **0.300** | **0.138** |
| 8 | 0.177 | 0.083 | 0.025 | **0.020** |
| 64 | 0.084 | 0.011 | 0.003 | 0.006 |
| 256 | 0.074 | 0.003 | **0.001** | 0.009 |
| 1,024 | 0.072 | 0.001 | **0.000** | 0.009 |
| 16,384 | 0.071 | 0.001 | **0.000** | 0.006 |

- **Batch size 1 (what the solver does today):** the restructured CPU
  (numpy-vec, 0.04 ms) is **7.5× faster than the GPU** and **23× faster than
  the current Python**. The GPU's kernel launch (~0.25 ms) dominates.
- **The crossover is between 64 and 256 candidates.** Below it the CPU wins;
  above it the GPU pulls away (2.6× at 256, 8.6× at 1,024, 97× at 16,384).
- **numba is the best CPU at large batches** (1.8 M cand/s, 4× the vectorised
  numpy) but never close to the GPU, and at batch size 1 its thread start-up
  makes it worse than shapely's steady state.

### 5.4 — correctness

```
N=16384   numba 1.665e-16   warp 4.978e-01   numpy-vec 0.000e+00   grid 4.993e-01
          ambiguous closest edges: 2774/16384 (16.9%)
          warp disagrees with the reference on 90 candidates, of which 87 are ambiguous
          grid finds the same closest edge for 99.89% of candidates
```

- **numba** and **numpy-vec** agree with the float64 reference to 1.7e-16 and
  exactly 0.0 respectively ✓.
- **Warp** (float32) agrees to 1.0e-07 where the answer is unambiguous.
- The larger differences are **not errors**: the scoring function takes an
  **argmin over edges**, and **16.9 % of candidates have two edges at exactly
  the same distance** — at a polygon corner, the two adjacent edges are
  equidistant over a whole angular cone, so the argmin is genuinely ambiguous.
  87 of Warp's 90 differing candidates are exactly such ties; the grid's
  differences are **all** ties.
  *(`scripts/exp5_tie_diagnostic.py` measures this; it is a property of the
  function, not of any port.)*

## 6. How to reproduce

```bash
cd ~/lm-wt/lab2
.venv/bin/pip install numba shapely "warp-lang==1.18.0" "numpy<2.6"
.venv/bin/python scripts/exp_solver_scoring.py        # ~3 min
.venv/bin/python scripts/exp5_tie_diagnostic.py        # the tie analysis
```

Raw output: `results/exp-solver-scoring.txt`.

## 7. Verdict

**USEFUL — with a condition that is itself the finding.**

1. **The GPU port works and is enormously faster than the current code**
   (3,394× at N = 16,384; the kill condition is cleared by a factor of 680).
2. **But it is only the right engine if the solver batches its proposals.**
   The solver scores **one** candidate per annealing step; at that size the
   *restructured CPU* is 7.5× faster than the GPU, because the GPU's
   per-launch cost (~0.25 ms) is the whole cost.
3. **The cheaper win is available today.** Vectorising the scoring in numpy is
   a **23× improvement at batch size 1** and a **35× improvement at batch size
   16,384**, with no GPU and no restructuring of the solver. If the plan wants
   the solver faster *this week*, that is the change.
4. **Spatial pruning (the grid) is the wrong restructuring for this problem.**
   A furnished room's edges are dense: the broad phase filters almost nothing
   (99.89 % of candidates find the same closest edge with or without it) while
   the gather costs more than the arithmetic it avoids — 165 k cand/s against
   the plain vectorised version's 496 k. *Restructuring for layout, not for
   pruning.*

### What this changes for the plan

- **"The solver becomes a daytime character" needs a solver change, not just a
  kernel change.** The GPU can score 48 million candidates per second; the
  solver currently asks for one. The proposal step is where the batch has to
  come from — and that is a legal change to the annealing loop: *score N
  proposed poses, accept the best* (or sample from them) while the decision
  stays sequential.
- **Until that change exists, the honest speed-up for the solver's scoring is
  ~23× (numpy), not ~3,394× (GPU).** This is Round 1's Rule 1 paying off
  again: a GPU port must beat the restructured CPU, and here it only does
  above a batch size the solver never reaches.
- **The ambiguity in the scoring function is worth knowing about separately.**
  ~17 % of candidates have a tied closest edge, so the solver's score is not a
  well-defined function of the geometry at those points. It does not matter
  for the timing, but a GPU port that breaks ties differently from the CPU
  would change the solver's *decisions*, not just its speed — and the solver is
  a random process, so a different tie-break changes the generated scene. That
  is a correctness question for any port, and it is now measured rather than
  assumed.

### The next step this suggests

Batch the proposal step and re-measure. The whole GPU case rests on whether
`propose_continous`/`propose_discrete` can emit N candidate poses per step
without changing the solver's output distribution. That is a small,
measurable question — and it is the difference between a 23× and a 3,394×.

### What is still missing

**I could not attribute this stage's share of the 38-minute solve.** The
Infinigen spike has `thor/run-timed.sh` (which records wall time, peak RSS and
Jetson counters per stage) but **no `outputs/logs/` yet**, so there is no
per-stage breakdown to check the "is that stage ≥ 30 s of the ~38 min"
condition against. Until that exists, the honest statement is a *rate*: the
current path scores **14,127 candidates/s**; at that rate a solver making 10⁵
scoring calls per scene spends ~7 s in this function, and 10⁶ calls would
spend ~71 s. The first pipeline run that produces `pipeline_coarse.csv` will
settle it.

## 8. Failures that stayed

- **My synthetic geometry created a flood of exact ties.** The first version
  put the extra vertex of a "chamfered" footprint *on* the top edge, which
  produced two overlapping collinear edges and ~18 % exact distance ties.
  The correctness check then showed differences of up to 0.5 and looked like a
  port bug. It was not: the ties were an artefact of the scene, and after
  fixing the geometry the remaining differences are the *real* ties (corners),
  which the diagnostic now counts and attributes.
- **A "failure" that was not one:** the difference between the port and the
  reference is *not* a precision problem at 16.9 % ambiguous candidates, but
  the code gave no hint of that. The fix was to measure the ambiguity
  explicitly (`scripts/exp5_tie_diagnostic.py`) and make the correctness report
  tie-aware — "every candidate where an implementation disagrees must be an
  ambiguous one" — which turned a scary-looking 0.5 error into a sentence.
- **numba's numbers are the most load-sensitive of the five** (0.26 ms at
  batch 1 and load 38, 4.75 ms at load 62): the parallel region is dominated by
  thread start-up when there is one candidate. Any claim about numba on this
  box needs the load beside it.
