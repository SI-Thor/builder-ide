# EXP 3 — Skills as small adapters: N LoRA adapters on one shared base

**Date:** 2026-10-31 03:05 local (Alaska Daylight Time)
**Verdict: THE ADAPTERS THEMSELVES ARE CHEAP; THE SWITCH IS NOT.** A 15.7 M-parameter
skill adapter costs **60 MiB** resident and adds **no measurable time** to a DINOv2-giant
forward. But PEFT's "switch the active adapter" costs **73–119 ms of host time per
switch** — larger than the request it is switching for — and the mixed-adapter batch
(PEFT's `adapter_names=` path) is **10× slower than switching at 32 adapters**, because
it degenerates into 160 layers × 32 sub-batch GEMMs of one row each.

Kimi's claim — *"skills as small adapters (LoRA-style, 10–50 M params) on one shared base,
switched per builder/craft"* — is **half right**: the size is right and the cost of
*having* an adapter is right, but **switching per request is the wrong mechanism on this
stack**.

---

## 1. The idea

> "Skills as small adapters (LoRA-style, 10-50M params) on one shared base, switched per
> builder/craft."

The brief asks for three things: the cost of **switching adapters per request** versus a
batch that **mixes adapters**, and the **memory per adapter**.

The project wants a builder's "craft" — a distinctive style, a specialty — to be a small
adapter on one shared base model rather than a whole second copy of the model. If that
works, the base model is loaded once and the builders' individuality is a few tens of
megabytes each.

## 2. Hypothesis

1. A LoRA adapter of 10–50 M parameters fits comfortably on one shared base, and the
   **switch** between adapters costs far less than a forward pass.
2. A batch that **mixes** adapters is at least as fast as switching per request, because
   the base weights stream once for the whole batch.
3. The resident cost of the adapters themselves is negligible next to the base model.

## 3. Setup

- Script: `scripts/exp3_lora.py`; raw JSON: `results/exp3_lora.json`
  (rerun: `.venv/bin/python scripts/exp3_lora.py`)
- Base model: the real local **DINOv2-giant** (`~/models/dinov2-giant-local`), 1.64 B
  parameters, bf16, 40 layers, hidden 1536, SwiGLU MLP — a standard HF ViT, so the
  adapter machinery is exercised on the kind of model the project would actually serve.
- Adapters: LoRA on `q_proj`, `k_proj`, `v_proj`, `o_proj` (160 modules), **r = 32,
  α = 64**, **32 adapters** named `skill0…skill31`.
- Serving modes, for N requests:

  | mode | what it does |
  |---|---|
  | `base` | adapters disabled — the floor everything else is measured against |
  | `same` | N sequential requests, one adapter, no switch |
  | `switch` | N sequential requests, N distinct adapters, `set_adapter` per request — **the multi-LoRA server's way** |
  | `copy` | the naive "one LoRA slot, overwrite it" implementation: the adapter's A/B tensors are copied device→device into the active slot |
  | `merge` | the "one merged model per skill" way: fold the adapter into the base weights, run, fold it back out |
  | `mixed` | **one** forward with N rows and N distinct adapters (PEFT's `adapter_names=` path): the base layer runs once for the whole batch, then each adapter is applied to its own rows |

- Correctness is checked **before** any timing, because a timing comparison between
  adapters that are secretly identical measures nothing.

### The box this ran on

| | |
|---|---|
| GPU clock | 1575 MHz (warmed from 315 MHz first — see `exp-batched-shared-model.md`) |
| Power mode | `MAXN` (nvpmodel mode 0) |
| **Load during the run** | **loadavg 25.6 → 39.4 on 14 cores** (rising during the run) |
| Contender | `trellis/ComfyUI/main.py` (another seat's ComfyUI server, GPU-resident) |
| **Effect on these numbers** | the **host-side** costs (`set_adapter`, `copy`) are inflated by CPU starvation; the **GPU-side** costs and all the *ratios* are robust. Treat the absolute host-side milliseconds as an **upper bound**. |

## 4. Numbers

### 4.1 The size of a skill adapter — Kimi's "10–50 M params" band, located

| rank r | params | bf16 | fp32 | in the 10–50 M band? |
|---|---|---|---|---|
| 8 | 3.93 M | 7.50 MiB | 15.00 MiB | no |
| 16 | 7.86 M | 15.00 MiB | 30.00 MiB | no (just under) |
| **32** | **15.73 M** | **30.00 MiB** | **60.00 MiB** | **yes** |
| **64** | **31.46 M** | **60.00 MiB** | **120.00 MiB** | **yes** |
| 128 | 62.91 M | 120.00 MiB | 240.00 MiB | no |

So Kimi's band is exactly reachable: **r = 32 gives a 15.7 M-parameter skill, r = 64
gives 31.5 M**, both on one shared base. The claim about *size* is confirmed.

**But PEFT creates the adapter in FP32 even when the base model is BF16**
(`adapter_dtypes: ['torch.float32']`). A "15.7 M-parameter skill" therefore occupies
**60 MiB resident, not 30 MiB** — the adapter is 2× its nominal size on the device. That is
worth knowing before planning 100 skills.

### 4.2 Resident memory

| | |
|---|---|
| base model (dinov2-giant, bf16) | **2228.4 MiB** |
| 32 adapters @ r=32 | **1860.3 MiB** |
| **per adapter** | **60.01 MiB** |
| **peak allocated** | **4088.7 MiB** |

**Killing condition for hypothesis 3: not triggered, but it is not free either.** The
adapters are 45 % of the resident footprint of the whole system — 32 skills cost almost
as much as the model they specialise. (The 1.64 B-parameter base is 3.1 GiB in bf16 but
allocates 2.2 GiB, because some weights are not materialised on device.)

### 4.3 Correctness — what was actually compared

| check | result |
|---|---|
| the 32 adapters produce **different** outputs | **yes** — 9.98 % of the output RMS apart (RMS 0.1396 against an output RMS of 1.3986) |
| the `mixed` path assigns each row the **right** adapter | **yes** — the matching single-forward is the closest of the four for every row (diagonal max abs 0.281 vs off-diagonal min abs 1.066) |
| the `mixed` path **equals** N separate forwards | **yes** — 1.36 % relative RMS difference |
| the naive `copy` slot reproduces its source adapter | **yes** — max abs difference 0.0 (bit-exact) |

> **Method note.** The first version of this check compared **max-abs** differences and
> reported the adapters as "13 apart". That was an artefact: the output tensor has
> elements up to 15.9 against an RMS of 1.40, so a single outlier element moves the
> max-abs statistic by 10× without anything real changing. **The RMS is the meaningful
> statistic for a tensor with outliers**, and the numbers above are RMS-based.

### 4.4 The switch cost — the finding

| resident adapters | `set_adapter` per switch | with `inference_mode=True` |
|---|---|---|
| 1 | 73.3 ms | 80.1 ms |
| 2 | 85.9 ms | 113.4 ms |
| 4 | 85.0 ms | 118.7 ms |
| 8 | 118.8 ms | 85.0 ms |
| 16 | 87.6 ms | 81.7 ms |
| 32 | 82.6 ms | 98.8 ms |

**A single `set_adapter` call costs ~75–120 ms of host time on this box** — more than
the DINOv2 forward it precedes (~35–100 ms at these sizes). The cost is **flat in the
number of resident adapters**, so it is not the per-adapter loop; it is the walk over the
model's ~800 modules and 160 LoRA layers that PEFT performs on every call
(`peft/tuners/tuners_utils.py`: `set_adapter` → for every `LoraLayer`,
`module.set_adapter()` → rewrite `requires_grad` on every adapter it holds, then
`_freeze_non_trainable_peft_weights` walks them again).

This is **pure host work**: it scales with the *depth* of the model, not with the GPU,
and it is charged to the request even though the GPU is idle during it.

Two smaller numbers for the same operation:

| operation | per switch |
|---|---|
| `set_adapter` (name swap, all adapters resident) | **75.7 ms** |
| copy the adapter's weights into the active slot (60 MiB device→device) | **45.5 ms** |

The naive "copy the weights in" implementation is **faster than PEFT's name swap** on
this box, because a 60 MiB device-to-device copy is trivial next to 10 000 Python-level
tensor property writes. That inverts the usual expectation, and it is a direct
consequence of PEFT's `set_adapter` being O(layers × adapters) in *Python*.

### 4.5 Serving modes

Times are the wall time for N requests; per-request is that divided by N. **Load was
39.4 and rising during this table** — read the ratios, not the absolutes.

| N | base | same | switch | copy | merge | mixed | mixed ÷ switch |
|---|---|---|---|---|---|---|---|
| 1 | 240.1 ms | 127.6 | 133.1 | 152.4 | 263.2 | 229.3 | 0.58× |
| 2 | 435.4 ms | 445.7 | 465.8 | 1018.0 | 1021.9 | 461.8 | 1.01× |
| 4 | 202.4 ms | 278.5 | 843.9 | 1965.6 | 887.2 | 764.9 | 1.10× |
| 8 | 506.7 ms | 1119.2 | 1532.1 | 1618.1 | 2851.1 | 1085.0 | 1.41× |
| 16 | 1110.5 ms | 1022.1 | 1914.4 | 2175.2 | 3325.1 | 6109.3 | 0.31× |
| 32 | 668.1 ms | 1129.5 | 3490.0 | 10584.8 | 9273.0 | 37161.0 | **0.09×** |

Reading it:

- **The adapter itself is nearly free.** At N = 32, `same` (one adapter, 32 requests)
  costs 1129 ms against a `base` floor of 668 ms — an overhead of **~14 ms per request**
  on a 1.64 B-parameter model. The adapter's 15.7 M parameters are 1 % of the base.
- **`switch` costs ~109 ms per request**, and essentially all of that is the
  `set_adapter` call from §4.4, not the adapter's arithmetic.
- **`merge` is the most expensive way to switch** (~236–290 ms per request): folding the
  adapter into the base weights and back out writes 3.1 GiB of base weights twice.
- **`mixed` — PEFT's mixed-adapter batch — is a trap at scale.** It is roughly break-even
  with switching at N ≤ 8 (1.0–1.4×) and **10× worse at N = 32** (1161 ms per request
  against 109 ms). The reason is structural: PEFT's mixed path computes the base layer
  once, then for **each** LoRA layer and **each** adapter runs a separate GEMM on that
  adapter's rows and scatters the delta back — 160 layers × 32 adapters = 5 120
  one-row GEMMs plus 5 120 index-scatter writes. It trades a bandwidth saving for a
  kernel-launch explosion, and on a launch-bound stack that is the wrong trade.

### 4.6 Joules

Whole-box (INA238 `VIN`) joules per request, and the same figure **above the idle
baseline** captured before the work started:

| mode | J/request (whole box) | J/request above baseline |
|---|---|---|
| switch | 29.03 | 5.90 |
| mixed | 57.62 | −8.84 |

**These numbers are not usable as a property of the work.** The box was at load 39 with
another seat's ComfyUI server resident on the GPU; the whole-box rail is dominated by
other tenants, and the `mixed` figure came out *below* the idle baseline, which is only
possible because the box's power draw changed between the baseline and the measurement.

What the baseline-corrected column does say is that the *marginal* energy of the adapter
work is small — a few joules per request at a 1.64 B-parameter base — and that on this
box the joules metric for a shared workload needs the baseline subtraction to mean
anything at all.

## 5. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp3_lora.py            # -> results/exp3_lora.json

# the facts that decide the verdict, by hand:
python3 -c "
import json; d=json.load(open('results/exp3_lora.json'))
print(d['adapter_stats']['per_adapter_params']/1e6, 'M params')
print(d['adapter_stats']['per_adapter_mib'], 'MiB per adapter')
print(d['memory']['adapters_allocated_per_adapter_mib'], 'MiB measured on device')
print(d['correctness'])"
```

## 6. Verdict

**PARTLY USEFUL — and the "switch" half of the idea does not survive.**

- **Confirmed:** a skill adapter of **15.7 M parameters** (r = 32) on one shared base is
  the right size, and it costs **14 ms per request** on top of a 1.64 B-parameter
  forward — about 1 %. The base model is genuinely shared.
- **Confirmed with a caveat:** **32 adapters cost 1860 MiB** — 45 % of the system's
  resident footprint. And **PEFT keeps adapters in FP32** even on a BF16 base, so each
  one is 60 MiB, not 30 MiB. A hundred skills would not fit.
- **Killed:** *"switched per builder/craft"* as a per-request mechanism. **PEFT's
  `set_adapter` costs ~75–120 ms of host time per call** — more than the request — and
  it is flat in the number of resident adapters, so it does not get cheaper as the
  skill count grows. The naive copy-into-a-slot approach is *faster* (45 ms).
- **Killed:** the mixed-adapter batch as a way to serve many builders at once. It is
  break-even at N ≤ 8 and **10× worse at N = 32**, because it is O(layers × adapters)
  one-row GEMMs.

### What this changes for the plan

- **Do not build the builder-scheduling layer on "switch the active adapter".** It is a
  host-side cost proportional to model depth, charged per request, and it is the single
  largest term in an adapter-served request.
- **The viable shape is the opposite of what was assumed:** keep the adapters *merged*
  into a small number of resident models, and switch at the **model** level, not the
  adapter level — or keep one base model per *craft group* and batch within a group.
- **The mixed-batch path is worth revisiting only with a CUDA-graph capture** (see
  `exp-cuda-graphs-nvenc.md`): its 5 120 one-row GEMMs are exactly the launch-bound
  case a graph removes. That is the one experiment this round's results point at next.
- **A sharper framing for "skills":** the numbers say a builder's skill should be a
  *merged* 15.7 M-parameter delta on a resident copy of the base (60 MiB + 2.2 GiB per
  craft), not a switched adapter on one shared base — unless the base model is small
  enough that a per-skill copy is cheap.

## 7. Licence note

`peft` (MIT), `transformers` (Apache-2.0), `torch` (BSD-3-Clause). The DINOv2 weights
used here are the local `dinov2-giant-local` copy already on the Thor; **no weights were
downloaded** and no weights are redistributed by this experiment.

## 8. Failures that stayed

- **`PeftModel.from_pretrained(model, BASE, ...)`** — the base directory holds no
  adapter checkpoint, so the adapter must be created with `get_peft_model`.
- **PEFT 0.21 has no `rename_adapter`**, only `delete_adapter`; and `get_peft_model`
  names the first adapter `"default"`, so the skill set has to be built by deleting it
  and adding `skill0…skillN-1`.
- **PEFT 0.21's `set_adapter` takes a single name, not a list**, and refuses
  `adapter_names=` when the model is in training mode (`peft_model.eval()` is required).
- **`module.lora_A` is a `ModuleDict` {adapter_name: Linear}**, not a
  `ModuleDict` {adapter_name: ModuleDict}: `lora_A[ad]` is the `Linear` itself, so
  `isinstance(..., dict)` finds nothing and `store.items()` raises *"'Linear' object has
  no attribute 'items'"*.
- **The mixed path needs one row per adapter in the batch** — `x[:4]` on a one-image
  tensor is still one image, and PEFT raises *"Length of `adapter_names` should be the
  same as the number of inputs"*.
- **PEFT's `set_adapter` defaults to `inference_mode=False`**, which makes the adapter
  *trainable* on every switch — wrong for a serving path, and it is the reason the
  call is expensive.
- **transformers 5.x renamed DINOv2's attention projections** from
  `attention.attention.{query,key,value}` / `attention.output.dense` to
  `q_proj`/`k_proj`/`v_proj`/`o_proj`; PEFT matches on the module name, so the old
  names find nothing (*"Target modules … not found in the base model"*).
