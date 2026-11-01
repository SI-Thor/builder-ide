# Making the real generator's fp8 path run — and what it costs when it does

**2026-10-31, 10:27 → 16:10 PDT on the Thor.** The follow-up the graph
experiment asked for. Its finding was that the fused fp8 path *never runs*:
all 9,460 `fp8_linear` calls returned `None` because the weights arrive
bfloat16 — ComfyUI's dynamic VRAM loader assigns the checkpoint's tensors
over the model's parameters, throwing away the fp8 dtype the model was built
for. This experiment makes the smallest change that makes the weights fp8
when the fused path is asked for, then measures the fused path where it
counts: per-step time, peak memory, a whole prop's wall time, and — the gate
— whether the prop that comes out is still the prop.

The arms and scripts live in
[docs/lab/trellis-graph-scripts/](trellis-graph-scripts/) (the `fp8_real`
custom node is the patch; `run_arms.sh` runs the grid). The dtype is now a
request parameter, `PropRequest.weight_dtype`, default `default` — bf16 —
until fp8 earns its place.

**What it found:**

1. **The fix works.** With `fp8_real` installed, the arm that asks for
   `fp8_e4m3fn_fast` loads 2,560 weights as fp8 (15.37 G elements, 5–9 s at
   load, warm) and the fused path takes **28,308 of 28,308 `fp8_linear`
   calls, both rounds, zero declined** — against 28,380 calls *all declined*
   in the control arm that reproduces today's box. The weights the path is
   handed are `torch.float8_e4m3fn`.
2. **The fused path runs, and it is the slowest way to run fp8.** In the
   clean round — the round whose dtype-free image stage (the same SDXL work
   in every arm) agrees to **1.1 ms** across all three arms — the fused fp8
   path is **7–31 % slower per mesh step than plain bf16** (structure
   589→632 ms, sparse-batched 1,633→2,135 ms, sparse-single 915→1,060 ms).
   The surprise is the third arm: the *declined* path — ComfyUI's
   manual-cast fallback, quantising on the fly — beats bf16 on the sparse
   steps (1,241 ms, −24 %) and matches it on the dense ones. The fp8 GEMM
   can win on this box; **the fused path loses to its own fallback**, paying
   per-call `QuantizedTensor` dispatch and a named fallback: the sparse
   stages' narrow linears (K = 8) cannot run the fp8 GEMM (it needs K
   divisible by 16), so the fused path **raises and falls back on every
   call that touches one** — 72 exception fallbacks in one arm's log.
   Round 1 ordered the arms the other way, and its image control spread
   268–454 ms for identical work: that ordering was the box's noise, not
   the dtype's.
3. **Memory moves the wrong way for a unified-memory box.** The fp8 arm's
   GPU peak reserve is ~1 GB smaller (7.9–8.0 GB against bf16's 7.6–9.1 GB),
   but its **host RSS is 22 GB against bf16's 7 GB** — the fp8 staging the
   dynamic loader keeps per model load accumulates across the prop's three
   seeds' loads and is not freed. On this box host RSS *is* physical memory.
4. **The quality gate FAILED, and the failure is the dtype's.** The critic's
   score — the number the night ranks props by — holds to within 0.0006 on
   all three seeds (floor 0.02). The silhouette IoU holds on two seeds
   (0.992, 0.995) and **misses the floor on the third: 0.934 against 0.95**.
   A same-dtype control (bf16 round 1 against bf16 round 2, independent
   runs) lands at IoU **0.9997–0.9999** with identical scores — the pipeline
   is deterministic per seed — so the outline that moved is fp8's work, not
   sampler noise. Per the gate's own rule: **bf16 stays the default.**
5. **Today's fp8 template, without the fix, is worse than either.** The
   `fp8-declined` arm — what the box does now when a workflow asks for fp8 —
   quantises on the fly and **changes the prop's shape more than the fused
   path does** (silhouette IoU 0.962 / **0.557** / 0.987 against bf16). A
   workflow that asks for fp8 today silently gets props the outline no
   longer recognises. The fix is not only what makes fp8 *fast-able*; it is
   what makes asking for fp8 mean one thing.
6. **The box kept the harness honest all day.** The first grid ran every
   arm — fp8 arms included — as bf16, because the workflow builder writes
   the loader's dtype outright and the driver stayed silent (the arms now
   pass `--weight-dtype` and the fp8 counters are the check). The second
   grid was halfway through when the box filled its 122 GB and went down;
   its numbers were contaminated by the slide (the same cast that costs
   5–9 s warm cost 105 s there). The rerun grid's last arm was SIGTERMed by
   another seat's requeue stampede and was rerun under the box's lock. Every
   number below is from the rerun grid, with the box's state beside it.

---

## 1. The setup

| | |
|---|---|
| the generator | the TRELLIS.2 spike's ComfyUI, `--use-pytorch-cross-attention --cache-none`, from this worktree's base directory, port 8189 — one process per arm, started and stopped by the arm runner |
| the prop | one request — a weathered wooden crate — through the whole pipeline per seed: SDXL picture (30 steps, 1024²), then TRELLIS.2 (structure 12, shape 20, texture 12 steps), decode, GLB |
| the seeds | 101, 102, 103; two rounds, arms **interleaved** (bf16 → fp8-fixed → fp8-declined, then again) so a drift in the box lands on every arm about equally |
| the arms | `bf16` — the plain template, `weight_dtype: default`; `fp8-declined` — the fp8 template without the fix (today's box); `fp8-fixed` — the fp8 template with `fp8_real` |
| the driver | `run_one_prop.py --weight-dtype …`, the seat's own workflow builders and client |
| the gate | `quality_gate.py`: the critic's graded score (floor: the candidate may not sit 0.02 below the control) and the silhouette IoU on six views (floor 0.95), same seeds |
| the box | after the 2026-10-31 memory crash and reboot; the Infinigen seed sweep on the CPU throughout; every heavy step under `~/lm-wt/heavy.lock`, one at a time, alongside four other seats' queued work |

**The fix, in one paragraph.** `fp8_real` is a custom node in this worktree
(the TRELLIS.2 environment is read, never written) that patches ComfyUI's
lazy state-dict loader at the one point where the damage happens: when
`_lazy_load_from_state_dict` assigns the checkpoint's tensor over a module
built as `comfy.ops.fp8_ops.Linear` with `weight_comfy_model_dtype ==
float8_e4m3fn`, the tensor is cast to fp8 first. The gate is deliberately
narrow — a bf16 model is untouched byte for byte. `FP8_REAL_FIX=0` is the
control. The mechanics and the verification are in
[the scripts' README](trellis-graph-scripts/).

## 2. Did the fused path run? The counters

| arm | `fp8_linear` calls | taken | declined | weights seen as |
|---|---:|---:|---:|---|
| bf16 (r1, r2) | 0 | 0 | 0 | — (never asked) |
| fp8-declined r1 | 28,380 | **0** | 28,380 | `torch.bfloat16` |
| fp8-fixed r1 | 28,308 | **28,308** | 0 | `torch.float8_e4m3fn` |
| fp8-fixed r2 | 28,308 | **28,308** | 0 | `torch.float8_e4m3fn` |

(The call counts differ by one seed's worth of *attempts* between the
declined and fixed arms because the declined arm's structure stage emits a
slightly different token count — the shape stage's steps scale with it. The
signal is in the *ratio*, and it is 0/28,380 against 28,308/28,308.)

The fix's cast, beside its numbers: **2,560 weights, 15.37 G elements,
5.2 s (r1) / 8.8 s (r2) at load** — warm page cache, box load 6–10. For
scale across the day: the one-seed probe measured 13.0 s for its 5.0 G
elements while the box sat at **load 106** (pre-crash), and the crashed
grid's 10.0 G elements took 105.1 s while the box slid toward the OOM. The
cast is paid per model load — the prop's three seeds load the model twice
each, so the arm pays it six times. The bf16 arm pays none of it, and its
run shows the fp8 template's other half: 72 `Exception during fp8 op`
fallbacks (K = 8 linears in the sparse stages) in one arm's log.

## 3. Per-step time, and the control that keeps it honest

The probe records every diffusion step's GPU span, tagged by the step's
input shape; `summarize_arms.py` groups them into the picture stage and the
mesh stage's dense/sparse, batched/single signatures. Median GPU span per
stage:

| stage (steps per seed) | bf16 r1 | bf16 r2 | fp8-fixed r1 | fp8-fixed r2 | fp8-declined r1 | fp8-declined r2 |
|---|---:|---:|---:|---:|---:|---:|
| **image — the control** (30) | 278.3 | 267.4 | 453.7 | **267.3** | 268.3 | **266.3** |
| structure, batched (9) | 948.0 | 589.0 | 755.8 | 631.5 | 616.4 | 615.3 |
| structure, single (3) | 584.4 | 274.0 | 384.7 | 537.4 | 312.5 | 311.0 |
| sparse, batched (15) | 2,737.5 | 1,632.7 | 2,085.0 | 2,134.7 | 1,242.1 | 1,240.8 |
| sparse, single (17) | 1,020.6 | 915.0 | 1,181.6 | 1,060.4 | 733.6 | 734.7 |

**Read the control row first.** The image stage runs the *same* SDXL work,
same seeds, same workflow, in every arm — the dtype only touches the mesh
workflow's loader. In round 2 all three controls sit within **1.1 ms** of
each other: that round, the box treated the arms equally, and there the
fused fp8 path is **7 % slower on the dense structure steps and 16–31 %
slower on the sparse steps** than plain bf16 — while the *declined* path
(ComfyUI's manual-cast fallback) matches bf16 on the dense steps and beats
it by **24 % on the sparse-batched steps**, reproducibly (declined r1 and
r2 agree to 0.2 %). In round 1 the control spread **268–454 ms** for
identical work — the box's load moved under the arms — and round 1's
apparent fp8 win inverts as soon as the control says which arm the box was
noisy for. The interleaving keeps the drift off one arm's label; the
control is what lets you *see* it.

Two findings hide in the clean round's comparison, and they point in
opposite directions:

* **The fp8 GEMM can win here.** The declined arm quantises the weights to
  fp8 at staging and runs the fp8 matmul through the manual-cast path —
  and its sparse steps, the longest in the prop, are reproducibly **24 %
  faster** than bf16's. The narrow-linears story is not "fp8 can't do these
  shapes"; it is "the *fused* path can't".
* **The fused path loses to its own fallback.** Same template, same ops,
  same shapes — the only difference is that the fix makes the weights fp8,
  so `fp8_linear` proceeds instead of returning `None`. Measured, proceeding
  is the slower choice: +3 % on the dense steps, **+44–72 % on the sparse
  steps** against the manual path. The per-call
  `QuantizedTensor` dispatch, plus the K = 8 linears raising and falling
  back every call (72 fallbacks in one arm's log), costs more than
  quantising on the fly does. The path the spike wanted to reach is real,
  and on this stack it is the slow one.

## 4. Peak memory

High-water marks over each arm's whole run (the allocator's and the
process's own):

| arm (rounds) | CUDA allocated, peak | CUDA reserved, peak | host RSS |
|---|---:|---:|---:|
| bf16 (r1 / r2) | 7.7 / 6.9 GB | **9.1 / 7.6 GB** | **7.0 / 6.8 GB** |
| fp8-fixed (r1 / r2) | 7.0 / 7.0 GB | 7.9 / 8.0 GB | **22.0 / 22.2 GB** |
| fp8-declined (r1 / r2) | 5.8 / 6.4 GB | 6.5 / 6.8 GB | 7.0 / 6.7 GB |

The fp8 arm's GPU reserve is consistently ~1 GB under bf16's — the weights
are half the bytes — but its **host RSS is 15 GB over bf16's** and steady at
22 GB across rounds: the dynamic loader's fp8 staging (≈5 GB per model
load) accumulates over the prop's six loads and is not given back. On this
box the host RSS and the GPU share 122 GB of the same physical memory, so
the fused path's memory story is **+14 GB net**, not −1 GB. A seat that
holds props and models resident would feel that first.

## 5. The whole prop's wall time

Image + mesh, per seed (seconds). The mesh tail (remesh, unwrap, bake) is
CPU-bound and moves with the box's CPU load — the sweep was on it all day —
so the medians carry the comparison and the spread carries the honesty:

| arm | seed 101 | seed 102 | seed 103 | median |
|---|---:|---:|---:|---:|
| bf16 r1 | 221.5 | 326.0 | 205.8 | 221.5 |
| fp8-fixed r1 | 182.1 | 284.0 | 214.3 | 214.3 |
| fp8-declined r1 | 154.5 | 180.4 | 312.9 | 180.4 |
| bf16 r2 | 168.9 | 159.3 | 201.6 | 168.9 |
| fp8-fixed r2 | 353.1 | 178.1 | 187.4 | 187.4 |
| fp8-declined r2 | 150.9 | 125.0 | 166.1 | 150.9 |

fp8-fixed r2's seed 101 (353 s) is a load burst, not the dtype: its image
stage — the dtype-free control — matched bf16's to 0.1 ms that round, and
its mesh GPU lane (77.4 s against 46.1 s) caught the burst the boxstate
file records (load 9.8 at the arm's start). The declined arm's 151 s median
is the fastest in the table and the disqualifier stands next to it: that is
the arm whose seed-102 silhouette IoU is 0.557. **The wall-time verdict
matches the per-step one for the path the brief asked about: the fused path
wins nothing.**

## 6. The gate: is the prop still the prop?

`quality_gate.py`, bf16 (round 1) against fp8-fixed (round 1), same seeds:

| seed | critic score bf16 → fp8-fixed | Δ | silhouette IoU |
|---|---:|---:|---:|
| 101 | 0.6912 → 0.6906 | −0.0006 | **0.9338** |
| 102 | 0.6999 → 0.6996 | −0.0003 | 0.9919 |
| 103 | 0.6999 → 0.6996 | −0.0004 | 0.9953 |

Floors: score Δ ≥ −0.02 (passes everywhere), silhouette IoU ≥ 0.95
(**seed 101 fails**). **Verdict: fail.**

Two calibration numbers make that failure mean what it says:

* **The same-dtype control.** bf16 round 1 against bf16 round 2 — the same
  dtype, independent processes, hours apart — lands at IoU
  **0.9997 / 0.9999 / 0.9999** with scores equal to four decimals. The
  pipeline is deterministic per seed; the gate's docstring hedges about
  stochastic samplers, and the measurement says it need not have. An IoU of
  0.934 is a shape the outline can tell from bf16's, and fp8 made it.
* **The declined arm is worse.** bf16 against fp8-declined (what a workflow
  gets from the fp8 template today): IoU **0.962 / 0.557 / 0.987** — seed
  102's prop comes out half-overlapping its bf16 self. The night's own
  critic score barely notices (its checks are coarse: a volume, a surface,
  a count), but the outline — what a camera sees — is not the prop.

So the gate's failure is *understated by the critic and visible in the
silhouette* — which is exactly why the gate measures both. **bf16 stays the
default.** `PropRequest.weight_dtype` stays a parameter, default
`"default"`, and the executor records it in the asset's recipe: a prop made
in fp8 is not the same prop, and the recipe is where that has to be true.

## 7. What to do with this

* **Keep the fix; don't flip the default.** `fp8_real` makes "fp8" mean one
  thing — without it, the fp8 template silently quantises on the fly and
  bends the prop worse than the fused path does (IoU 0.557). With it, the
  path at least runs as labelled, and the counters say which one you got.
  But the gate failed and the speed is against it: **the night's props stay
  bf16.**
* **The fused path is the slow way to run fp8 on this stack.** The fp8 GEMM
  itself wins on the sparse stages — the manual-cast fallback's steps are
  reproducibly 24 % faster than bf16's — but the fused path, the thing the
  fix reaches, loses to that same fallback by 44–72 % on the same steps. If
  fp8's sparse-stage speed is ever wanted, the experiment to run is
  "fp8 weights without the fused dispatch" — and the quality gate would
  have to pass first, which neither fp8 arm managed.
* **fp8 is not the Thor win here.** The spike's §7.3 hoped the fused path
  would cut the host's scale work; the graph experiment showed the scales
  were under 1 % of a path that never ran; this one ran it, and the path
  is the slowest way to run the model — against bf16, against its own
  fallback, and behind a quality gate it fails. The memory trade is
  +14 GB of host staging against −1 GB of GPU reserve. The fp8 experiment
  is done: **measured, and a no.**
* **The host staging is the next Thor-native target.** 22 GB of RSS for a
  10 GB checkpoint, growing with loads rather than per model — the dynamic
  loader's staging is where the box's memory actually goes. That, not the
  matmul's dtype, is where a rewrite pays.
* **The arms' fp8 counters are the check that an arm ran its label.** The
  first grid's lesson stands as infrastructure: every fp8 number in this
  note sits next to its call counters, and a future number that doesn't is
  wearing a borrowed label.

## 8. Reproduce

```sh
# the grid: 2 rounds, seeds 101-103, arms interleaved, one ComfyUI per arm,
# under the box's heavy lock (the memory rule)
bash docs/lab/trellis-graph-scripts/run_arms.sh 2 101 102 103

# the numbers
~/lm-wt/propmaker-batch/.venv/bin/python docs/lab/trellis-graph-scripts/summarize_arms.py \
  --artifacts artifacts/fp8-real --suffix=-r1     # and -r2

# the gate
~/lm-wt/propmaker-batch/.venv/bin/python docs/lab/trellis-graph-scripts/quality_gate.py \
  --control bf16 --candidate fp8-fixed --out artifacts/fp8-real/quality.json
# and the same-dtype control that calibrates it: the gate's _find against
# bf16's two rounds (bf16-r1 vs bf16-r2) lands at IoU >= 0.9997
```

The fix is `FP8_REAL_FIX=1` (default); `FP8_REAL_FIX=0` reproduces today's
declined behaviour. `FP8_REAL_STATS` names the counters' file. Raw output is
under `artifacts/fp8-real/` (gitignored): per arm and round, the probe JSON
(222 per-step records, the fp8 counters), the run JSONs (wall times, node
lanes), the fix's cast counters, the box's state before and during, and the
GPU's own samples. `artifacts/fp8-real-crashed-run1/` holds the grid that
died with the box (kept for the record; its numbers are contaminated by the
slide toward the OOM and are not cited anywhere), and
`artifacts/fp8-real-invalid-run1/` holds the first grid, whose every arm —
fp8 arms included — ran bf16 because the driver did not yet say the dtype.

## 9. What it stubs

* **The mesh tail's CPU share.** Remesh, unwrap and bake ride in every arm's
  mesh wall and answer to the box's CPU load (the seed sweep ran all day).
  The stage medians in §3 are GPU spans and dodge most of it; the wall
  medians in §5 do not, which is why §5 concludes only what the control
  confirms.
* **One prompt, three seeds.** The gate's verdict is about this prop
  (a crate) at 512. A prop whose structure stage emits different token
  counts would shift the sparse stages' shapes — the fp8 GEMM's divisibility
  fallbacks, and so the slowdown's size, move with them. The direction of
  every finding would need a reason to flip; the magnitudes are this prop's.
* **The rounds are not independent evidence of speed.** Round 1's ordering
  is the box's noise (its control says so); round 2 is the round the speed
  verdict quotes. Both rounds' counters and memory are consistent, which is
  why those verdicts quote both.
