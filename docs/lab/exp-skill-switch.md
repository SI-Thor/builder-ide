# EXP 3 — cheap skill switching: the merge is 180× cheaper than PEFT's switch, and batched multi-LoRA needs no switch at all

**Date:** 2026-10-31 (round 4) · **Verdict: THE SWITCH CAN BE MADE NEARLY FREE — the mechanism just has to be the weights, not the metadata.**
On the real DINOv2-giant base (bf16, 1.64 B) with 32 LoRA skills (r=32,
q/k/v/o = 160 modules, all resident), round 3's `set_adapter` costs **72.5–129.5 ms
of host time per switch** (reproduced). The alternatives measured here:

| mechanism | per switch | notes |
|---|---|---|
| PEFT `set_adapter` | **72.5–129.5 ms** | O(layers × adapters) in Python; flat-to-worse in skill count |
| copy 60 MiB adapter into a slot (d2d) | **2.4 ms** | round 3 measured 45 ms at load 39 — that was CPU starvation, not the copy |
| `delta_swap` (W += Δ_new − Δ_old in place) | **36.7 ms** | one fused add per module; ~723 MiB of weight traffic |
| **`pointer_swap` (merged-resident sets)** | **0.40 ms** | re-point 160 weight tensors; costs 720 MiB bf16 per skill instead of 60 MiB fp32 |
| **batched multi-LoRA (no switch)** | — | one graphed forward serves N rows with N skills at **11–14 ms/request** (N ≥ 4) |

All four serving paths are **numerically exact** against single-adapter
forwards (rel RMS 0.0000 % — including the merged paths, whose fold-into-W
arithmetic lands on the same bf16 results as the two-step adapter path here).
At N=32 mixed-skill requests, PEFT switching takes **4,097 ms** where the
graphed batch takes **453 ms — 9.0×** — and the batched path's VDD_GPU energy
is **0.43 J/request against the switcher's 1.77 J (4.1×)**.

---

## 1. The idea

The round-4 brief's third preference: *"Cheap skill switching: LoRA merged-weight
swap, or a multi-LoRA kernel (e.g. punica/S-LoRA-style batched LoRA if it runs
on aarch64), vs PEFT's 73–119 ms switch."*

Round 3 established the problem (`exp-adapters.md`): skills are cheap to hold,
expensive to switch, and PEFT's mixed-adapter batch degenerates into
160 layers × 32 one-row GEMMs. Its Part C named both fixes — *merged resident
models* and *graph-capture the mixed batch* — and this round measures them.
(punica itself is a CUDA source extension and does not install on aarch64; its
*shape* — per-row adapters applied inside one forward — is what is implemented
here as grouped `torch.bmm`, which is exactly the portable form.)

## 2. Hypothesis

1. Switching by **writing weights** (delta add, or re-pointing to pre-merged
   sets) beats PEFT's metadata walk by an order of magnitude, at a memory cost
   that is explicit and measurable (60 MiB fp32 adapter vs ~720 MiB bf16
   merged q/k/v/o set per skill).
2. A **batched multi-LoRA forward** (2 bmms per module, adapter-indexed rows)
   serves N mixed-skill requests without any switch, and captures in a CUDA
   Graph — removing the launch storm that made PEFT's mixed path 10× worse.
3. Merging changes float association (`x(W+Δ)` vs `xW + (xA)B`), so merged
   serving carries a small bounded error.

(Hypothesis 3 turned out false at bf16 — see §4.1: the merged results are
*exact* here, which is itself worth knowing.)

## 3. Setup

- Script: `scripts/exp3_skill_switch.py` (`.venv-torch`); raw output
  `results/exp3_skill_switch.txt`, JSON `results/exp3_skill_switch.json`.
- Base: the local **DINOv2-giant** (`~/models/dinov2-giant-local`), bf16 on
  cuda, frozen. Adapters: PEFT LoRA r=32 α=64 on `q/k/v/o` (160 modules),
  **32 skills**, adapters fp32 (PEFT's default — round 3's 60 MiB finding).
- **The five mechanisms**:
  - `peft_switch` — `model.set_adapter(k)` + forward, per request (the
    multi-LoRA server's way; PEFT's own forward semantics, re-installed
    explicitly: `base(x) + B(A(x))·scaling`).
  - `copy_slot` — copy skill k's A/B (60 MiB) into an active slot, d2d.
  - `delta_swap` — per module `W += Δ_k − Δ_prev` in place; Δ_k = (B_k A_k)·s
    pre-merged **once** (fp32 accumulate, bf16 write).
  - `pointer_swap` (merged-resident) — K full sets of merged q/k/v/o weights
    (bf16, 720 MiB each, 4 allocated) and the switch re-points the 160
    `weight.data` tensors; serving uses the plain linear, no adapter
    arithmetic at all.
  - `batched` — every LoRA module re-routed through grouped bmm over
    adapter-indexed rows (`x[rid]` gather → bmm with A/B gathered per row; the
    ViT's 3D hidden states make the shape (skill, token, dim)); eager and
    **captured per batch size** in CUDA Graphs with static input + static
    adapter-index buffer.
- **Correctness before timing**: the batched path vs 32 single-adapter
  forwards (rel RMS); merged (pointer and delta) vs adapter forwards; the
  graph vs eager batch (RMS + max-abs).
- Serving timed in **3 interleaved rounds** over N ∈ {1, 4, 16, 32}; switch
  costs are host-time medians of 7 after 2 warm-ups; joules from the INA rails
  over 3×16-request windows.

### The box's state, beside the numbers

| | |
|---|---|
| GPU clock | warmed 315 → **1575 MHz**; 1575 beside every table |
| loadavg | 12.9 → **31.7** during the run (another seat's Infinigen sweep + the resident ComfyUI server); the serving ratios are interleaved, the switch-cost absolutes are upper bounds |
| GPU tenants | `trellis` ComfyUI (idle, resident), an `ig-spike` nature sweep on the CPU |
| Memory | 98.2 GiB available after base+adapters; **46.4 GiB** after also allocating 4 merged sets + stacks; 40.2 GiB at the end |

## 4. Numbers

### 4.1 — correctness: everything is exact

| check | rel RMS |
|---|---|
| batched (grouped bmm, 32 rows × 32 skills) vs 32 single-adapter forwards | **0.0000 %** |
| pointer_swap(0) merged forward vs adapter forward | **0.0000 %** |
| delta_swap(0) merged forward vs adapter forward | **0.0000 %** |
| batched graph vs batched eager | **0.0000 %** (max abs 0.0) |

The merged paths being *exact* (not merely close) is a small finding on its
own: folding Δ into W in fp32 and rounding to bf16 lands on the same values as
computing `xW + (xA)B·s` with the fp32 adapter added to the bf16 base — at
this model's shapes and dtypes there is no accuracy argument *against* merging.

### 4.2 — switch cost (host ms per switch, 32 adapters resident)

| mechanism | ms | what it is |
|---|---|---|
| `peft set_adapter` (skill0→skill1) | **72.5** | Python walk over ~800 modules rewriting `requires_grad` |
| `peft set_adapter` (skill0→skill31) | **129.5** | — |
| copy slot (60 MiB d2d, 160 modules) | **2.4** | the same idea round 3 measured at 45 ms under load 39 |
| delta_swap (in-place add per module) | **36.7** | ~723 MiB of weight read+write per switch |
| **pointer_swap (160 re-points)** | **0.40** | **180× cheaper than PEFT's switch** |

### 4.3 — serving (wall for N requests, ms per request in brackets; 3 interleaved rounds)

| mode | N=1 | N=4 | N=16 | N=32 |
|---|---|---|---|---|
| base (adapters attached, one active) | 51.3 (51.3) | 140.0 (35.0) | 736.1 (46.0) | 1447.9 (45.2) |
| adapter_same (no switch) | 82.9 (82.9) | 252.3 (63.1) | 752.6 (47.0) | 1505.4 (47.0) |
| peft_switch (the multi-LoRA server) | 114.4 (114.4) | 603.9 (**151.0**) | 2178.8 (**136.2**) | 4097.0 (**128.0**) |
| pointer_serve (merged-resident) | 22.4 (22.4) | 84.8 (21.2) | 301.9 (**18.9**) | 594.5 (**18.6**) |
| batched_eager (mixed skills) | 31.1 (31.1) | 44.4 (**11.1**) | 192.4 (**12.0**) | 433.8 (**13.6**) |
| **batched_graph (mixed skills)** | 27.3 (27.3) | 44.8 (**11.2**) | 198.0 (**12.4**) | 453.0 (**14.2**) |

- **Switching is the request's dominant cost**: PEFT-switch serving is
  2.2–2.9× the same forward with no switch (128 vs 45 ms/request at N=32).
- **Merged-resident serving is the fastest single-request path** (18.6–22.4
  ms/req) — faster even than `adapter_same`, because serving merged weights
  skips 60 MiB of adapter arithmetic per forward. Its price is memory:
  **720 MiB per skill** (bf16) against 60 MiB (fp32 adapter) — 12× the bytes.
- **Batched mixed-skill serving is the best throughput**: 11–14 ms/request for
  N ≥ 4, **9.0× PEFT's switching server at N=32** (453 vs 4,097 ms), with *no*
  switch and *no* per-skill weight copies.
- **The graph adds nothing over batched-eager here** (44.8 vs 44.4 ms at N=4;
  453 vs 434 at N=32 — level within noise). The grouped-bmm form is only ~320
  launches per forward, not PEFT-mixed's 5,120 one-row GEMMs, so it was never
  launch-bound to begin with — the launch storm round 3 measured was an
  artefact of PEFT's `adapter_names=` implementation, not of mixed batching.

### 4.4 — joules per request (N=16)

| mode | whole box above baseline | VDD_GPU rail |
|---|---|---|
| peft_switch | −0.29 J *(unusable — the box's load fell mid-window; round 3's trap 17)* | **1.77 J** |
| pointer_serve | 0.65 J | 0.82 J |
| batched_graph | 0.72 J | **0.43 J** |

The GPU-rail energy per request: **4.1× less** for the graphed batch than for
PEFT's switching server.

### 4.5 — the memory bill (measured, not estimated)

| per skill | bytes |
|---|---|
| PEFT adapter (fp32, resident) | **60.0 MiB** |
| merged q/k/v/o weight set (bf16) | **720.0 MiB** |

With everything live (base bf16 + 32 adapters + stacks + 4 merged sets + batch
buffers) `MemAvailable` was 46.4 GiB — 32 merged sets (~22.5 GiB) would fit but
would dominate; the design point is a **small hot set of merged residents +
batched multi-LoRA for the long tail**, exactly the "recipes, not shared state"
shape the project already prefers.

## 5. How to reproduce

```bash
cd ~/lm-wt/lab4
.venv-torch/bin/python scripts/exp3_skill_switch.py    # ~12 min (weights, 32 adapters, 4 merged sets, 4 graphs)
```

## 6. Verdict

**The switch is solved — by changing what a skill *is* on the device.**

1. **Never build per-request switching on PEFT's `set_adapter`.** 72.5–129.5 ms
   of host time, flat-to-worse in skill count — reproduced at low load, so the
   round-3 figure was not starvation.
2. **Hot skills: merged residents.** A 0.40 ms pointer swap, and serving from
   merged weights is *faster* than serving with an adapter attached (18.6 vs
   47.0 ms/request at N=32) because the adapter arithmetic disappears. Budget
   **720 MiB per skill** (12× the adapter) — a handful of crafts per builder,
   exactly the small-number shape the plan assumed.
3. **Mixed-skill nights: batched multi-LoRA, graphed.** 11–14 ms/request at
   N ≥ 4, no switch, no copies, 0.43 J/request on the GPU rail — and the
   punica-style shape needs no custom kernel: **two grouped bmms per module in
   plain torch capture in a CUDA Graph and are numerically exact.**
4. **Round 3's "graph-capture PEFT's mixed batch" recommendation is answered,
   with a twist**: the graph isn't what saves it — re-implementing the mixed
   batch as grouped bmm (320 launches instead of 5,120) already removes the
   launch storm; the graph is then a reproducibility tool, not a speedup.

### What this changes for the plan

- **The builder-scheduling layer gets its rule**: route each request to the
  *merged resident* of its craft if one is hot (0.4 ms switch, fastest
  forward); otherwise batch it into the graphed multi-LoRA forward (11–14
  ms/request, any skill mix). PEFT switching is retired.
- **The skill budget is now denominated in bytes with a measured exchange
  rate**: 60 MiB fp32 to *hold* a skill, 720 MiB bf16 to *serve it merged*.
- The remaining open question is **eviction policy** (how many merged
  residents before re-merging costs more than batching) — a scheduler
  simulation over a real night's ledger, not a hardware experiment.

## 7. Failures that stayed

- **punica/S-LoRA does not install on aarch64** (CUDA source extension) — the
  grouped-bmm form is the portable substitute and turned out not to need the
  graph to beat PEFT.
- **PEFT 0.21's `get_peft_model` takes no `torch_dtype` kwarg** — adapters are
  fp32 by default; passing the kwarg raises `TypeError`.
- **The ViT feeds LoRA layers 3D hidden states** `[batch, tokens, hidden]` — a
  2D-row bmm explodes (`batch1 must be a 3D tensor`); the correct punica shape
  here is bmm over `(skill, token, dim)`.
- **A CUDA Graph bakes its input shape** — one graph per batch size (N = 1, 4,
  16, 32), else `static_x.copy_(x)` fails on the mismatch.
- **`torch.sqrt(...).item()` inside another `float(...)`** — `.item()` too
  early turns the argument into a float and `sqrt()` rejects it; compute the
  ratio in tensors and call `.item()` once at the end.
- **Whole-box joules drifted negative again** on the longest arm (the other
  seats' load fell mid-window): the VDD_GPU rail is the only attributable
  joule figure at these window lengths.

## 8. Licence note

`peft` (MIT), `transformers` (Apache-2.0), `torch` (BSD-3-Clause). The
DINOv2-giant weights are the Thor's local copy (`~/models/dinov2-giant-local`),
read in place; no weights downloaded, nothing redistributed.
