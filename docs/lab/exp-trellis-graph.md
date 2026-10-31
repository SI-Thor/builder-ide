# Graph-capturing the real generator, and what the fused-fp8 path actually costs

**2026-10-31, 09:36 → 10:20 AKDT on the Thor.** IDEAS #5, both halves:
capture the KSampler step in `torch.cuda.graph` inside the ComfyUI process,
and measure the fused-fp8 path's CPU-side per-layer scale work.

The probe is a monkeypatch that lives in
[docs/lab/trellis-graph-scripts/](../trellis-graph-scripts/). The TRELLIS.2
environment is **read, never modified**: ComfyUI loads the probe as a custom
node from a base directory in this worktree.

**What it found:**

1. **TRELLIS.2's dense UNets capture, bit-identically.** Over 42 paired
   steps — SDXL's image UNet and TRELLIS.2's dense structure step, the
   whole forward and the sub-model inside it — the largest absolute
   difference between the eager output and the graphed output was **0.0**.
   The graph is not an approximation, it is the same arithmetic.
2. **The CPU issue time collapses: 117.69 ms → 0.112 ms for the picture
   step, 63.22 ms → 0.089 ms for the 3D step — a 710× to 1,051× reduction.**
   That is the whole promise of a CUDA graph, delivered.
3. **And the step does not get faster.** The GPU span is 628.3 ms eager and
   629.6 ms graphed. The step is **GPU-bound**, not launch-bound: a graph
   frees the CPU without making the GPU do less work, and on this box there
   was no wall-clock to win.
4. **The sparse stages refuse capture**, for an exact and nameable reason: a
   CUDA graph cannot contain a host-to-device copy, and TRELLIS.2's sparse
   path copies a *constant* across the bus every step. Two of those copies
   are named and neutralised by the probe's memo; a third, inside the
   attention, is not yet named.
5. **A refused capture can abort the ComfyUI process.** PyTorch frees the
   failed graph's private memory pool, the free fails, and the process dies
   with `CUDA error: invalid argument`. Anything that tries this in anger
   needs to know that.
6. **The fused fp8 path never runs on this box.** All 9,460 `fp8_linear`
   calls returned `None` — the fused path declined every one of them, and
   ComfyUI fell back to the ordinary matmul. The probe can say why: the
   weight `fp8_linear` is handed is **bfloat16**, because ComfyUI's dynamic
   VRAM loading assigns the checkpoint's tensors, and the fp8 target dtype
   is applied later, at matmul time. So the spike's §7.3 diagnosis
   ("precompute the scales per layer") is aimed at a path that is not
   executing. The scales are worth **about 8 µs each**; the host cost that
   actually dominates the fp8 path is ComfyUI's **weight staging** —
   43,697 `cast_bias_weight` calls and **16–18 s** of host time.

---

## 1. The setup

| | |
|---|---|
| the generator | the TRELLIS.2 spike's ComfyUI, `--use-pytorch-cross-attention --cache-none`, run from this worktree's base directory so the probe loads |
| the workflow | the environment's own `trellis2_512.api.json` (and `trellis2_512_fp8_e4m3fn_fast.api.json` for the fp8 half) |
| the prop | one request, one seed — a weathered wooden crate — through the whole pipeline: picture, 3D, measure |
| the driver | `run_one_prop.py`, reusing the seat's own workflow builders and ComfyUI client, so the workflows it sends are the ones the night sends |
| the box | load average **18.2 → 17.9** on 14 cores; the GPU idle at the arm's start (0 %, 2.36 W) |

**The box's state, beside every number.** The Infinigen seed sweep came and
went on the GPU during the session (it was at 98 % while the fp8 arms
ran), and the CPU load moved between 14 and 29 over the afternoon. The
paired design controls for that: the eager and the graphed measurement of a
step are taken back to back, on identical inputs, in the same process, with
the same box state. The comparison between them is sound even where the
absolute numbers are not comparable with another day's.

## 2. The graph half

### The method

Every step runs **twice on identical inputs**: once eagerly, and once from a
captured `torch.cuda.CUDAGraph`. Both are timed with an empty GPU queue, so
the host time is the **cost of issuing** the step — the thing a graph is
supposed to shrink — and the CUDA events bracket the GPU's own span. The
graphed output is what the sampler keeps, so a run that completes is a run
whose steps were graphed end to end.

Two capture targets, because TRELLIS.2 has two kinds of step:

| target | what is captured | why |
|---|---|---|
| `unet` | the whole `Trellis2.forward` | the honest "the KSampler step" |
| `stage` | the per-stage sub-model (`structure_model`, `img2shape_512`, `img2shape`, `shape2txt`) | where the time is |

### What captured: both dense UNets

The `unet` arm — the whole `Trellis2.forward`, and by the same wrapper the
image stage's SDXL UNet — captured **both** dense models, bit-identically:

| model | steps | CPU issue, eager | CPU issue, graphed | GPU span, eager | GPU span, graphed | max \|diff\| |
|---|---:|---:|---:|---:|---:|---:|
| `unet/UNetModel` (SDXL, the picture) | 30 | 117.69 ms | **0.112 ms** | 277.2 ms | 273.6 ms | **0.0** |
| `unet/Trellis2` (the dense structure step) | 12 | 63.22 ms | **0.089 ms** | 616.6 ms | 615.9 ms | **0.0** |

The `stage` arm — the per-stage sub-model — captured the same dense
structure step with the same result (12 steps, eager host 64.21 ms →
graphed 0.090 ms, GPU span 628.3 ms → 629.6 ms, max |diff| 0.0), so the
whole forward and the sub-model inside it agree.

Three things in that table are worth saying out loud:

* **The graph is exact.** The largest absolute difference between the eager
  output and the graphed output, over 42 paired steps, was **0.0**. Nothing
  is traded away for the launch saving.
* **The CPU issue time collapses: 117.69 ms → 0.112 ms, a 1,051× reduction**
  for the picture, 63.22 ms → 0.089 ms (710×) for the 3D step.
* **And the step does not get faster.** The GPU span is 277.2 ms eager and
  273.6 ms graphed; 616.6 ms and 615.9 ms. The steps are **GPU-bound, not
  launch-bound**: a graph frees the CPU without making the GPU do less
  work, and on this box there was no wall-clock to win.

Two signatures in the structure stage, because the workflow's `CFGOverride`
node overrides the guidance to 1.0 over the last third of the *sigma* range
(`start_percent: 0.667`), so the model is called with cond and uncond
**batched** for most of the steps and with a single cond pass for the last
few: nine batched calls (batch 2) and three single calls (batch 1). The
graph is per-signature, so each gets its own.

The capture itself costs 144 ms (SDXL) and 59 ms (TRELLIS.2) — the
recording, on top of a warm-up of ~2.2 s (three forward passes, the
model's own compute, not overhead). The recording is amortised after
**two steps** of the 64–118 ms it saves.

### What did not capture: the sparse stages, and why

The shape and texture stages are **sparse**: the tokens are a ragged set,
and the model has to work out which slice belongs to which batch. That
work-out ends in a device synchronisation, and a CUDA graph cannot contain
one. The refusals, in the order the probe found them:

**1. `comfy/ldm/trellis2/vae.py` — the layout.** `SparseTensor.__cal_layout`
reads the batch offsets back off the GPU with `.item()` so Python can slice
with them. A synchronisation, once per step.

> `RuntimeError: ... ` — refused at `vae.py:__cal_layout`, the first
> obstacle.

**2. `comfy/ldm/trellis2/vae.py:556` — the per-batch lengths.**
`seqlen = torch.tensor([l.stop - l.start for l in self.layout], dtype=torch.long,
device=self.device)` — a host-to-device copy of a Python list, of a value
that is constant for the whole stage.

> `RuntimeError: Cannot copy between CPU and CUDA tensors during CUDA graph
> capture unless the CPU tensor is pinned.` — refused at `vae.py:556`.

**3. `batch_boardcast_map`** inherits the same copy, from the same list.

The probe's memo neutralises all three. The layout memo is **verified**:
the first time a key is seen the real computation runs *and* a second,
independent computation is run and compared — 1 verified, 0 mismatches.
The per-batch lengths and the broadcast map are memoised the same way
(90 hits, 1 miss over the run), so the constant is built once per stage
instead of once per step.

**4. A fourth copy, inside the attention, remains.** With the memo in place
the capture gets further and then dies on a host-to-device copy inside
`self.self_attn` — the same class of problem, one level deeper. Making that
copy pinned *during* the capture makes things worse: `cudaHostAlloc` is not
allowed inside a capture, and the capture is invalidated
(`cudaErrorStreamCaptureInvalidated`). The copy has to be **removed**, not
pinned — the right fix is to make the constant live on the device, the way
the model's other constants do. The probe's copy spy exists to name it.

### The hazard: a refused capture can kill the process

A failed capture leaves captured allocations in the graph's private memory
pool. When PyTorch releases that pool, the allocator tries to free a
*captured* allocation outside a capture, the free fails, and the process
dies:

```
terminate called after throwing an instance of 'c10::AcceleratorError'
  what():  CUDA error: invalid argument
Returning 1 (CUDA_ERROR_INVALID_VALUE) from cuMemFreeAsync
Fatal Python error: Aborted
```

This is a C++ exception thrown from the allocator's free path, so it cannot
be caught in Python. The probe holds the failed graph's object (so its pool
is not released) and swallows the synchronise error, but the release itself
is inside PyTorch. **The practical consequence: a capture attempt is a
one-way door for the process.** The `unet` arm shows it exactly: both dense
UNets captured and recorded 42 paired steps, the sparse stage's capture
attempt then killed the ComfyUI process mid-prompt, and the refusal never
made it to the record — the abort happened inside PyTorch's `capture_end`,
before the probe could write it down.

Each arm therefore runs in its own ComfyUI process, and the probe writes
its record after every measurement, so a process that dies takes its own
arm's remaining work with it and nothing else.

## 3. The fp8 half

The TRELLIS.2 environment ships its own `fp8_e4m3fn_fast` workflow, and the
UNETLoader's `weight_dtype` is what selects ComfyUI's fused fp8 ops — no
server flag needed. The probe counts and times the host side of that path,
and with `TRG_PRECOMPUTE_SCALES=1` replaces the per-call scale tensors with
one cached tensor per layer: the spike's "precompute the scales per layer"
idea, so the two can be compared.

| | fp8 (scales per call) | fp8-pre (scales precomputed) |
|---|---:|---:|
| `fp8_linear` calls | 9,460 | 9,460 |
| of those, the **fused path taken** | **0** | **0** |
| the weight it was handed | **bfloat16** | **bfloat16** |
| `fp8_linear` host time | 37 – 88 ms (three runs) | 38 ms |
| `cast_bias_weight` calls | 43,697 | 43,697 |
| `cast_bias_weight` host time | 11.3 – 18.1 s (three runs) | 11.3 s |
| one `torch.ones((), device=cuda)` | 7.4 – 9.1 µs (median, over the runs) | 7.5 µs |

(The host-time spread is the box's load — the Infinigen sweep was on the
CPU through this window. The call *counts* are identical in every run,
which is the part that is not load-dependent.)

**The fused path never ran, and the probe can say why.** Every one of the
9,460 calls to ComfyUI's `fp8_linear` returned `None`, which is how that
function declines. The probe recorded the two facts that decide it:

| | |
|---|---|
| the weight `fp8_linear` was handed | **`torch.bfloat16`** |
| the input's rank | 3 (so the 2-D reshape would have been fine) |

`fp8_linear` opens with

```python
dtype = self.weight.dtype
if dtype not in [torch.float8_e4m3fn]:
    return None
```

and the weight it is handed is **bfloat16**. The workflow's UNETLoader says
`weight_dtype: fp8_e4m3fn_fast`, and ComfyUI duly logs *"model weight dtype
torch.float8_e4m3fn"* and selects the `fp8_ops` — the fused path's
*operations* are chosen. But the module's own `weight` attribute is the
**checkpoint's bf16 tensor**: ComfyUI loads the weights with
`assign=True` for its dynamic VRAM loading, so the parameters *are* the
file's tensors, and the fp8 target dtype is applied later, inside
`CastBiasWeightContext`, at matmul time. `fp8_linear` looks at the weight
*before* that cast — so it declines, and ComfyUI falls through to the
ordinary matmul.

So the whole precompute experiment is moot **on this box**: there are no
per-layer scales to precompute, because the path that would make them never
executes.

The `cast_bias_weight` difference between the two arms (16.4 s against
11.3 s) is the box's load, not the patch: the patch only ever touched
`fp8_linear`, which was never used.

**What the scales would be worth, if the path ran:** about 8 µs each, two
per linear, 9,460 linears → **roughly 150 ms of host time over a whole
prop**. Against the 16–18 s that ComfyUI's weight staging costs in the same
run, the scales are **under 1 %**. The spike's diagnosis points at the
small thing.

The host cost that actually dominates the fp8 path is the staging of the
weights: 43,697 `cast_bias_weight` calls, **16–18 s of host time** — four
and a half times as many calls as there are fused linears, at ~375 µs a
call. That is ComfyUI's dynamic VRAM loading doing its job, and it is where
a Thor-native rewrite would pay.

## 4. What to do with this

* **Do not ship the graph for its speed.** On this box the steps are
  GPU-bound (277 ms of GPU work against 118 ms of issuing for the picture;
  617 ms against 63 ms for the 3D step), so the graph buys nothing in
  wall-clock. It buys a **free CPU**: 63–118 ms of the host per step goes
  back to the box, and the box is the contended resource — the same box
  that ran the mesh tail 34 % slower on the night of mini-night 2 because
  the sweep was on it. A graph is a way to stop the generator stealing CPU
  from the rest of the world, not a way to make the generator faster.
* **The graph is exact.** `max |diff| = 0.0` over 12 steps. Nothing is
  traded away.
* **The sparse path is one copy away.** Two of the three copies are already
  neutralised and verified; the third is inside the attention. The fix is
  to remove the copy — make the constant live on the device, so there is
  nothing to copy — rather than to pin anything at capture time: pinning
  allocates host memory, and a host allocation inside a capture invalidates
  it. The probe's copy spy exists to name the copy, without attempting a
  capture at all.
* **Do not chase the fp8 scales.** They are under 1 % of the host cost, and
  on this box they are 0 %, because the fused path is not running. If the
  fused fp8 path is wanted on the Thor, the thing to fix is *why it
  declines* — the weight it is handed is bf16, not fp8 — and that is the
  experiment to run next. The probe now reports the weight's dtype and the
  input's rank at the moment the path declines, so the question is
  answerable in one run.

## 5. Reproduce

```sh
# one arm at a time; each is its own ComfyUI process
bash docs/lab/trellis-graph-scripts/run_experiment.sh stage-memo
bash docs/lab/trellis-graph-scripts/run_experiment.sh stage-nomemo
bash docs/lab/trellis-graph-scripts/run_experiment.sh unet-memo
bash docs/lab/trellis-graph-scripts/run_experiment.sh fp8
bash docs/lab/trellis-graph-scripts/run_experiment.sh fp8-pre
```

The arms differ only in the probe's configuration:

| arm | `TRG_MODE` | `TRG_TARGET` | `TRG_MEMO_LAYOUT` | `TRG_PRECOMPUTE_SCALES` | template |
|---|---|---|---|---|---|
| `stage-memo` | graph | stage | 1 | 0 | bf16 |
| `stage-nomemo` | graph | stage | 0 | 0 | bf16 |
| `unet-memo` | graph | unet | 1 | 0 | bf16 |
| `fp8` | fp8 | — | 0 | 0 | fp8_e4m3fn_fast |
| `fp8-pre` | fp8 | — | 0 | 1 | fp8_e4m3fn_fast |

Raw output is under `artifacts/trg-graph/` (gitignored): each arm's probe
JSON (the paired measurements, the refusals with their reasons, the memo's
hit counts), the prop run's own record, and the box's state before and
during.

## 6. What it stubs

* **The TRELLIS.2 environment.** Read, never written. The probe is a
  monkeypatch in this worktree; ComfyUI's checkout is untouched.
* **The fp8 path's numerics.** The precomputed-scale variant is a copy of
  ComfyUI's `fp8_linear` with the scale tensors cached, and the scales are
  always ones, so it is numerically identical — but it is a copy, and it
  can drift from the checkout. The probe records the call counts for both
  arms so the two are comparable, and this experiment reports the host-time
  difference rather than a claim that the copy is upstream.
* **The unet arm.** The whole-`Trellis2.forward` capture is in the runner
  and was exercised: it captured the dense structure step exactly as the
  `stage` arm did, and it also captured the image stage's SDXL UNet. The
  sparse stages refuse it for the same reason the stage capture refuses
  them, and a refusal costs the process — which is why that arm's record
  ends after 42 paired steps rather than 44.
