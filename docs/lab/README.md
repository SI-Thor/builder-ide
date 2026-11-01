# The lab

Small, fast experiments that mine ideas for Thor-native breakthroughs (CLAUDE.md, "Thor-native rewrites are welcome"). One file per experiment: the idea, the hypothesis, the setup, the numbers, how to reproduce, and the verdict (breakthrough / useful / no). Failures stay.

`IDEAS.md` is the index: the live candidates (Part A), the ones killed by fact (Part B), what to run next (Part C), and the cross-cutting traps (Part D). Everything else here is the evidence.

**The box is shared.** Every number in this directory records the load, the power mode and the GPU clock beside it. Where a result moved between runs, the range is given rather than the best number. **Publish ranges and re-run before publishing a conclusion.**

---

## Round 8 — the critic's shells (2026-11-01)

| file | what it measured | verdict |
|---|---|---|
| [`exp-critic-shells.md`](exp-critic-shells.md) | the plausibility prior's `fill_ratio` measured against the **NVIDIA SimReady** assets instead of a synthetic toy: three occupancy measures against known volumes, the fill ratios over 38 real objects, the prior refitted on the union of the approved assets and the sample, and the confusion table before and after | **the measure was wrong and the prior was empty of real objects — the ghost is still flagged (0.0385) and 1 of 38 real assets is flagged (2.6 %) against 38 of 38 before; leave-one-out is 3 of 38, and that floor is structural for a kind of 38** |

Scripts: [`critic-shells-scripts/`](critic-shells-scripts/) — the measures
against known volumes, the fill ratios over the sample, the reference set's
builder, and the confusion table.

---

## Round 7 — the decision models (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-judge-calibration.md`](exp-judge-calibration.md) | the judge's confidence under one definition, tracked against the Brier score on 1,470 recorded judgments: the per-cell Brier and ECE, the escalation sweeps under all three definitions, the recalibrations fitted on one split and read on another | **one definition is necessary and not sufficient — two cells' confidence is anti-correlated with being right (AUC 0.28, 0.29), one carries no signal (0.51), and the recalibration works where the signal is (10 of 11 cells improve their held-out Brier)** |
| [`exp-judge-calibration.md`](exp-judge-calibration.md) §7 | the same cell measured again with **the two named conditions swapped** (the reversed replay, on the Thor): 240 steps × 2 orders for d1-2B and d1-3B, the positional share, the real disagreement set, the two averages, the catch rate inside a sane escalation budget, and the latency of the two calls | **the both-order protocol's catch rate is 24.6 % on the 2B and 2.5 % on the 3B, not the 71.9 % and 38.5 % the assumption produced; the 2B answers by position (85.8 %) and the 3B by content (order-invariant); averaging the two vectors does not cancel the position (AUC 0.1332) — the protocol stays a diagnostic, not a gate** |

Scripts: [`judge-calibration-scripts/`](judge-calibration-scripts/) — the
replay of the recorded vectors, and what it reads; and
[`judge-reversed-scripts/`](judge-reversed-scripts/) — the reversed replay on
the Thor and its analysis.

---

## Round 6 — the core's doors (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-store-race.md`](exp-store-race.md) | the store race behind the doors' intermittent 500: one SQLite connection, two threadpool threads; lock vs per-thread read connections, measured | **useful — the lock won on the number and per-thread connections broke read-your-own-writes** |

---

## Round 6b — admission before spend (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-thor-admit.md`](exp-thor-admit.md) | the box's memory, measured: what the GPU exposes, what a resident admission daemon costs, and whether it stops a runaway before the kernel's OOM killer does | **useful — it works, and it is 2 MiB and 0.03% of a core** |

Round 7 of the same file adds the **presence scheduler**: the queue of the
box's own work, the pre-emption that gives it back to live work (0.28 s),
and the ledger that books the box's time by tier and names the cause of
every idle second.

The crate is `tools/thor-admit/`; the design is `docs/design/thor-admit.md`.

---

## Round 4 — the real generator (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-fp8-real.md`](exp-fp8-real.md) | making the fused fp8 path actually run (the weights were bf16), then per-step time, memory and a quality gate against bf16 | **the fix works; fp8 is a measured no — slower per step, +14 GB host RSS, gate fails; bf16 stays the default** |
| [`exp-trellis-graph.md`](exp-trellis-graph.md) | graph-capturing the TRELLIS.2 KSampler step in ComfyUI; the fused-fp8 path's host cost | **useful — and it kills the fp8 scales diagnosis** |
| [`mini-night-2.md`](mini-night-2.md) | the night again, with the cost model pricing the slate and the mesh repair in the pipeline | **the repair makes solids; the prop band is priced wrong** |

Scripts: [`trellis-graph-scripts/`](trellis-graph-scripts/) — the probe, its
launcher, and the arm runner; and
[`mini-night-2-scripts/`](mini-night-2-scripts/) — the repair measured on
all nine of a night's props.

---

## Round 3 — Kimi's six claims (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-engines.md`](exp-engines.md) | the fact-check: does NVLA / PVA / NVDLA / AV1 exist on this Thor? | **kills four claims** |
| [`exp-batched-shared-model.md`](exp-batched-shared-model.md) | one shared model, N agents batched; the FP8 multiplier; the bandwidth | **half right, and the multiplier is 3×** |
| [`exp-adapters.md`](exp-adapters.md) | N LoRA skills on one shared base; switching vs mixing; memory per adapter | **half right — switching is the wrong mechanism** |
| [`exp-joules-per-fixed-point.md`](exp-joules-per-fixed-point.md) | a toy equilibrium loop, warm vs cold; joules per fixed point | **confirmed** |
| [`exp-cuda-graphs-nvenc.md`](exp-cuda-graphs-nvenc.md) | CUDA Graphs against launch overhead | **confirmed, and worth more as reproducibility** |
| [`exp-nvenc-roundtrip.md`](exp-nvenc-roundtrip.md) | a float field through NVENC/NVDEC, as a warm-start store | **kills the store, confirms the engine** |

Scripts: [`lab3-scripts/`](lab3-scripts/) — `boxstate.py` (the shared power/box-state meter, with the GPU-clock warm-up), then `exp2_batched.py`, `exp3_lora.py`, `exp4_equilibrium.py`, `exp5a_cudagraphs.py`, `exp5b_nvenc.py`.

## Round 2 — the residency tiers, the critic, the solver, the procedural port (2026-10-31)

| file | what it measured | verdict |
|---|---|---|
| [`exp-nvme-bandwidth.md`](exp-nvme-bandwidth.md) | NVMe → unified-memory load bandwidth, cold and warm | useful |
| [`exp-critic-png-roundtrip.md`](exp-critic-png-roundtrip.md) | the critic's PNG round trip vs zero-copy from the render buffer | useful |
| [`exp-solver-scoring.md`](exp-solver-scoring.md) | one Infinigen solver score term: Python vs numba vs Warp vs a restructured CPU | useful, with a condition |
| [`exp-warp-terrain-port.md`](exp-warp-terrain-port.md) | one Infinigen terrain element ported to Warp | **breakthrough** |

## Round 1 — the foundation (2026-10-30)

| file | what it measured | verdict |
|---|---|---|
| [`exp-unified-memory.md`](exp-unified-memory.md) | zero-copy vs copy, and the achievable bandwidth | useful |
| [`exp-warp-terrain.md`](exp-warp-terrain.md) | Warp on aarch64/sm_110 vs an optimised CPU | useful, with a condition |
| [`exp-fp8-tensorcores.md`](exp-fp8-tensorcores.md) | FP8 and FP4 tensor cores on this stack | useful — and FP4 is a measured no |

Scripts: [`lab1-scripts/`](lab1-scripts/).
