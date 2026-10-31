# trellis-graph-scripts — the probe, and how it is run

The scripts for **IDEAS #5**: graph-capture the real generator's decode step
inside ComfyUI, and measure the fused-fp8 path's CPU-side per-layer scale
work. The write-up is
[docs/lab/exp-trellis-graph.md](../../exp-trellis-graph.md).

Everything here lives in the builder-ide worktree. **The TRELLIS.2
environment (`~/lm-wt/trellis`) is read, never modified** — the probe is a
monkeypatch loaded into the ComfyUI *process* from a base directory that
lives here.

The write-up is
[docs/lab/exp-trellis-graph.md](../../exp-trellis-graph.md). What it found,
in one paragraph: **both dense UNets capture, bit-identically** (max
|diff| = 0.0 over 42 paired steps), the CPU issue time collapses by two to
three orders of magnitude, **and the steps do not get faster** — they are
GPU-bound, so a graph frees the CPU without making the GPU do less work.
The sparse stages refuse capture, because a CUDA graph cannot contain the
host-to-device copy of a constant that TRELLIS.2's sparse path makes every
step; two of those copies are named and neutralised here, and the third is
inside the attention. A refused capture can **abort the ComfyUI process**,
so every arm runs in its own. And the fused fp8 path **never runs on this
box** — `fp8_linear` declines all 9,460 calls because the weight it is
handed is bf16, not fp8.

| file | what it is |
|---|---|
| `probe.py` | the probe: the capture, the paired eager/graphed measurement, the sparse-layout memo, the fp8 counters, the per-step timing |
| `comfy-base/custom_nodes/trg_probe/__init__.py` | the custom node ComfyUI loads; it installs the probe |
| `comfy-base/custom_nodes/fp8_real/__init__.py` | **the fp8 fix**: makes the weights fp8 when the fused path is asked for |
| `serve_probe.sh` | starts ComfyUI with the probe, from this worktree's base directory |
| `run_experiment.sh` | one arm at a time: start the service, run the prop, stop the service, report |
| `run_arms.sh` | the arms, **interleaved**, so a box that drifts drifts on every arm |
| `run_one_prop.py` | one real prop through a (possibly probed) ComfyUI; `--weight-dtype` says what the loader is asked for |
| `quality_gate.py` | the critic's score and the silhouette IoU of two arms' meshes, on the same seeds |
| `summarize_arms.py` | one round's run and probe JSONs → the numbers the lab note quotes |
| `boxstate.sh` | the box's state, beside the numbers |
| `one_prop.json` | one prop, one seed — the smallest run that exercises all three KSampler stages |

## The fp8 fix

`fp8_real` is the patch the last experiment's write-up asked for. It lives in
this worktree and is loaded into the ComfyUI *process*; the TRELLIS.2 checkout
is not touched.

**The bug.** ComfyUI's fused fp8 linear (`comfy.ops.fp8_linear`) only runs when
the module's weight is *already* fp8 — it reads `self.weight.dtype` and
returns `None` for anything else, which drops the call through to the
ordinary matmul. The weight arrives bf16, because ComfyUI's dynamic VRAM
loader **assigns** the checkpoint's tensors over the model's parameters:

```
comfy/model_base.py  load_model_weights -> load_state_dict(..., assign=True)
comfy/ops.py         disable_weight_init.Linear._lazy_load_from_state_dict
                       module.weight = torch.nn.Parameter(v)   # v: the checkpoint's bf16
```

The model was *built* for fp8 — `set_inference_dtype` put
`torch.float8_e4m3fn` in `unet_config['dtype']` — but the assignment throws
that away. Without the dynamic VRAM path the same checkpoint would be *copied
into* the fp8 parameter (torch's `copy_` casts) and the fused path would run.

**The fix.** At the point where the weight is assigned, cast the checkpoint's
tensor to the dtype the module was built for. It is paid once, at load —
measured at **13.0 s for the whole UNet** (832 tensors, 5.00 G elements), a
little over 1 GB/s of fp8 output, slower than the 6 GB/s first guessed. It
also *removes* work: the dynamic loader's staging geometry is already fp8, so
with a bf16 parameter the loader had to re-quantise every weight on its way
to the device, and the manual-cast path had to up-cast it again on every use.

**The trap the harness had to be taught.** `build_trellis_workflow` writes the
loader's `weight_dtype` outright (a request that asked for fp8 and silently
got bf16 would be a lie), so a driver that does not say the dtype asks for
`default` — and overrides the fp8 template's own `fp8_e4m3fn_fast`. The first
grid ran every arm, both fp8 arms included, as bf16 that way: all arms showed
0 `fp8_linear` calls and the fix saw 0 fp8 modules. `run_one_prop.py` takes
`--weight-dtype` and the arm runner passes it; the arms' fp8 counters are the
check that an arm ran the dtype its label says.

**The switch.** `FP8_REAL_FIX=0` turns the patch off (the control arm);
`FP8_REAL_STATS` names the file the counters are written to.

## The probe, in four parts

1. **The graph half.** The probe wraps the diffusion model's forward so that
   every step runs twice on *identical* inputs — once eagerly, once from a
   captured `torch.cuda.CUDAGraph`. The pair measures the GPU span and the
   host's **issue time** for the same step, so eager and graphed are
   comparable without being confounded by a different step or a different
   timestep. The graphed output is what the sampler keeps, so a run that
   completes is a run whose steps were graphed end to end.

   Two capture targets, because TRELLIS.2 has two kinds of step:

   | target | what is captured | why |
   |---|---|---|
   | `unet` | the whole `Trellis2.forward` | the honest "the KSampler step" |
   | `stage` | the per-stage sub-model (`structure_model`, `img2shape_512`, `img2shape`, `shape2txt`) | where the time is |

2. **The sparse layout memo.** TRELLIS.2's sparse stages resolve a per-batch
   *layout* through `SparseTensor.layout`, and that resolution ends in
   `.item()` — a device synchronisation, once per step. A CUDA graph cannot
   contain a synchronisation. The layout is a pure function of the token
   count and the batch count, and it does not change for the whole stage, so
   the probe can memoise it: one synchronisation per stage instead of one per
   step. The first time a key is seen, the real computation runs and is
   checked against a second, independent computation — the memo is
   *verified*, not assumed.

3. **The fp8 half.** The fused fp8 path builds a `QuantizedTensor` per
   linear and dispatches through `__torch_dispatch__`. The probe counts the
   calls and times the host side, and with `TRG_PRECOMPUTE_SCALES=1` it
   replaces the per-call `torch.ones` scale tensors with one cached tensor
   per (device, dtype) — the spike's "precompute the scales per layer"
   idea — so the two are directly comparable. It also counts how many calls
   the fused path **declined** (`fp8_linear_none`) and how many it took
   (`fp8_linear_used`): a per-step time means nothing without saying whether
   the fused path ran at all.

4. **The per-step half** (`TRG_MODE=steps`). The graph half runs every step
   twice — once eagerly, once from a captured graph — so the two can be
   compared on the same input. This half runs every step once and records
   what it cost: the GPU span (CUDA events around the forward) and the host
   time, with the box's memory beside it. It is how two dtypes are put on
   the same clock.

## Running it

```sh
# 1. the service, with the probe, on its own port
TRG_MODE=graph TRG_OUT=$PWD/artifacts/trg-graph.json \
  docs/lab/trellis-graph-scripts/serve_probe.sh start --port 8189

# 2. one real prop through it (the whole pipeline: image, 3D, measure)
PYTHONPATH=. python -m core.genbatch \
  --requests docs/lab/trellis-graph-scripts/one_prop.json \
  --out artifacts/trg-graph --night-id trg-graph \
  --comfy-url http://127.0.0.1:8189

# 3. stop it
docs/lab/trellis-graph-scripts/serve_probe.sh stop
```

Or, the way the experiment was actually run, one arm at a time — each arm
in its own ComfyUI process, because a refused capture can abort the
process:

```sh
bash docs/lab/trellis-graph-scripts/run_experiment.sh stage-memo
bash docs/lab/trellis-graph-scripts/run_experiment.sh unet-memo
bash docs/lab/trellis-graph-scripts/run_experiment.sh fp8
bash docs/lab/trellis-graph-scripts/run_experiment.sh fp8-pre
```

### The dtype arms

The fp8 experiment's arms are `bf16` (the control), `fp8-declined` (the fp8
template without the fix: the fused path declines, which is what the box
does today) and `fp8-fixed` (the fp8 template with the fix: the weights are
fp8 and the fused path runs). They are run **interleaved**, because the box
is shared and a drift in its load lands on whichever arm happens to be
running:

```sh
bash docs/lab/trellis-graph-scripts/run_arms.sh 2 101 102 103
```

Each round writes its own files (`$ARM-r1-...`), and the arms' meshes land
under `~/lm-wt/trellis/out/fp8real/$ARM-r<n>/s<seed>/`. The quality gate
reads them:

```sh
python docs/lab/trellis-graph-scripts/quality_gate.py \
  --control bf16 --candidate fp8-fixed \
  --out artifacts/fp8-real/quality.json
```

The probe writes its results to `$TRG_OUT` as JSON: `records` (the paired
eager/graphed measurements, or the per-step timings), `refusals` (every capture that was refused, with
the reason and a traceback), `layout_stats` (the memo's hit/miss counts
and how many of its answers were verified) and `fp8_stats` (the fused
path's call counts, and how many of them it took).

### The environment variables

| variable | default | what it does |
|---|---|---|
| `TRG_MODE` | `off` | `graph`, `fp8`, `steps` or `both` |
| `TRG_OUT` | `/tmp/trg-probe.json` | where the results are written |
| `TRG_TARGET` | `both` | `unet`, `stage` or `both` |
| `TRG_WARMUP` | `3` | the warm-up iterations before a capture |
| `TRG_MEMO_LAYOUT` | `1` | memoise the sparse layout (the sync that stops a graph) |
| `TRG_PRECOMPUTE_SCALES` | `0` | precompute the fp8 per-layer scales |
| `TRG_SPY` | `0` | watch the host-to-device copies, without attempting a capture |
| `TRG_PORT` | `8189` | the port the probe's service listens on |
| `TRG_SUFFIX` | *(empty)* | a suffix for this round's output files |
| `FP8_REAL_FIX` | `1` | install the fp8 fix (`0` reproduces today's behaviour) |
| `FP8_REAL_STATS` | `/tmp/fp8-real-stats.json` | where the fix's counters are written |

## What it stubs

* **The service.** The probe's own ComfyUI is the TRELLIS.2 spike's service
  with a different base directory and port. The plain service (port 8188) is
  a separate process and is not touched.
* **The fp8 path's numerics.** The precomputed-scale variant is numerically
  identical — the scales are always ones — but it is ComfyUI's code copied
  into this worktree, so it can drift from the checkout. The probe records
  the call counts for both, and the experiment reports the host-time
  difference, not a claim that the copy is upstream.
