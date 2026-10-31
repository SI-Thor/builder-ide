#!/usr/bin/env python3
"""EXP 3 -- Skills as small adapters: N LoRA adapters on one shared base.

Kimi's claim (round 3 brief):
    "Skills as small adapters (LoRA-style, 10-50M params) on one shared base,
     switched per builder/craft."

The brief asks for: the cost of switching adapters per request versus a batch
that mixes adapters (e.g. via a multi-LoRA server or PEFT), and the memory per
adapter.

Base model: the real, local `dinov2-giant` ViT (1.4 B parameters, bf16) -- real
weights, a standard HF model, so the adapter machinery is exercised on the same
kind of model the project would actually serve. 40 layers, hidden 1536.

Serving modes compared, for N requests:
  same      : N sequential requests, one adapter, no switch      (the baseline)
  switch    : N sequential requests, N distinct adapters, switched per request
              (what a multi-LoRA server does: every adapter stays resident and
              the *name* changes)
  copy      : the naive "one LoRA slot, overwrite it" implementation: the
              adapter's A/B tensors are copied device->device into the active
              slot before each request
  mixed     : ONE forward with N rows and N distinct adapters (PEFT's mixed
              batch path), which computes the base layer once for the whole
              batch and then applies each adapter to its own rows

Corrections over the first run of this script:
  * the adapter must be created with `get_peft_model`, not `from_pretrained` on
    a directory that holds no adapter checkpoint;
  * the adapters must have *different* weights -- the first run zeroed lora_B,
    which makes every adapter a no-op and every "switch" indistinguishable;
  * the mixed-batch path is checked against N separate forwards, so the
    comparison is against a verified-equivalent baseline.
"""

from __future__ import annotations

import json
import os
import sys
import time

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boxstate import (PowerMeter, format_box_state, box_state,  # noqa: E402
                      gpu_clock_mhz, warm_gpu)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")
BASE = os.path.expanduser("~/models/dinov2-giant-local")
# transformers 5.x renamed DINOv2's attention projections from
# attention.attention.{query,key,value} / attention.output.dense to the modern
# q_proj / k_proj / v_proj / o_proj. PEFT matches on the *module* name, so the
# old names find nothing.
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]
LORA_R = 32
LORA_ALPHA = 64
N_ADAPTERS = 32
IMG = 224          # 224x224 -> 16x16 = 256 patches, light enough to sweep N
SLOT = "skill0"    # the "active slot" used by the naive copy implementation
# A *trained* adapter perturbs the base model's output by a few percent. The
# random factors below are scaled to that regime, so the experiment compares
# realistic deltas rather than adapters that overwrite the base model.
LORA_INIT_SCALE = 0.01


def lora_cfg(r: int = LORA_R) -> LoraConfig:
    return LoraConfig(r=r, lora_alpha=2 * r, lora_dropout=0.0,
                      target_modules=TARGET_MODULES, bias="none",
                      inference_mode=True)


def build_base() -> tuple[PeftModel, torch.nn.Module]:
    model = AutoModel.from_pretrained(BASE, dtype=torch.bfloat16).cuda().eval()
    peft_model = get_peft_model(model, lora_cfg())
    # get_peft_model names the first adapter "default"; the experiment wants
    # every adapter called skill<i> so that N skills are skill0..skillN-1.
    # PEFT 0.21 has delete_adapter but no rename_adapter.
    peft_model.delete_adapter("default")
    peft_model.add_adapter("skill0", lora_cfg())
    peft_model.set_adapter("skill0")
    peft_model.eval()          # PEFT's mixed-batch path refuses to run in train mode
    return peft_model, model


def add_adapters(peft_model: PeftModel, n: int) -> None:
    """Add n-1 more adapters and give EVERY adapter distinct, non-zero weights.

    lora_B is initialised to zero by PEFT (so the adapter starts as a no-op).
    Leaving it that way would make every adapter identical and the whole
    measurement meaningless, so both factors are filled with distinct noise.
    """
    for i in range(1, n):
        peft_model.add_adapter(f"skill{i}", lora_cfg())
    g = torch.Generator(device="cuda").manual_seed(1234)
    for name, module in peft_model.named_modules():
        if not is_lora_layer(module):
            continue
        for ad in module.lora_A:
            for lay in (module.lora_A[ad], module.lora_B[ad]):
                w = lay.weight
                w.data.copy_(torch.randn(w.shape, generator=g,
                                        device="cuda") * LORA_INIT_SCALE)
    peft_model.eval()


def adapter_stats(peft_model: PeftModel) -> dict:
    per_adapter: dict[str, dict] = {}
    for name, module in peft_model.named_modules():
        if not is_lora_layer(module):
            continue
        for ad in module.lora_A:
            n_params = n_bytes = 0
            for lay in (module.lora_A[ad], module.lora_B[ad]):
                w = lay.weight
                n_params += w.numel()
                n_bytes += w.numel() * w.element_size()
            e = per_adapter.setdefault(ad, {"params": 0, "bytes": 0, "layers": 0})
            e["params"] += n_params
            e["bytes"] += n_bytes
            e["layers"] += 1
    one = next(iter(per_adapter.values())) if per_adapter else {"params": 0, "bytes": 0}
    n_ad = len(per_adapter)
    return {
        "n_adapters": n_ad,
        "per_adapter_params": one["params"],
        "per_adapter_mib": one["bytes"] / 1024 ** 2,
        "per_adapter_bytes": one["bytes"],
        "total_params": sum(v["params"] for v in per_adapter.values()),
        "total_bytes": sum(v["bytes"] for v in per_adapter.values()),
        "total_mib": sum(v["bytes"] for v in per_adapter.values()) / 1024 ** 2,
        "lora_r": LORA_R,
        "lora_alpha": LORA_ALPHA,
        "target_modules": TARGET_MODULES,
        "per_adapter_layers": one["layers"],
        "params_per_lora_r": 491520,   # measured for this model at r=1
    }


def lora_size_table(peft_model: PeftModel) -> list:
    """Params and bytes per adapter as a function of r -- Kimi's claim is
    '10-50M params', so the r that lands in that band has to be found."""
    named = [(n, m) for n, m in peft_model.named_modules() if is_lora_layer(m)]
    # ONE adapter's worth of factors, not all of them
    first = next(iter(named[0][1].lora_A.keys()))
    per_layer = 0
    for _, m in named:
        for lay in (m.lora_A[first], m.lora_B[first]):
            per_layer += lay.weight.numel()
    n_layers = len({n for n, _ in named})
    dtypes = sorted({str(m.lora_A[first].weight.dtype) for _, m in named})
    # per_layer above is the size of ONE adapter at the configured rank;
    # lora_A is [r, in] and lora_B is [out, r], so params scale linearly in r.
    per_r1 = per_layer // LORA_R
    rows = []
    for r in (8, 16, 32, 64, 128):
        p = per_r1 * r
        rows.append({"r": r, "params": p, "params_m": p / 1e6,
                     "mib_bf16": p * 2 / 1024 ** 2,
                     "mib_fp32": p * 4 / 1024 ** 2})
    return {"n_modules": len(named), "n_layers": n_layers,
            "params_at_r1": per_r1, "adapter_dtypes": dtypes,
            "table": rows}


def timeit(fn, warmup: int = 3, reps: int = 10) -> tuple[float, float]:
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    ts = []
    for _ in range(reps):
        s, e = torch.cuda.Event(True), torch.cuda.Event(True)
        s.record()
        fn()
        e.record()
        torch.cuda.synchronize()
        ts.append(s.elapsed_time(e))
    ts.sort()
    return ts[len(ts) // 2], ts[0]


def serve(peft_model: PeftModel, x: torch.Tensor, n_req: int, mode: str) -> float:
    """Time n_req requests. Returns the wall time in ms."""
    names = [f"skill{i}" for i in range(n_req)]
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    if mode == "mixed":
        # PEFT 0.21's set_adapter takes a single name; the mixed-batch path is
        # driven by the adapter_names argument on the forward, not by which
        # adapter is "active". The batch must have one row per adapter.
        xb = x.repeat(n_req, 1, 1, 1)
        peft_model(xb, adapter_names=names)
    elif mode == "switch":
        for nm in names:
            peft_model.set_adapter(nm)
            peft_model(x[:1])
    elif mode == "base":
        # the base model with every adapter disabled -- the floor that the
        # adapter modes are measured against
        peft_model.base_model.disable_adapter_layers()
        for _ in range(n_req):
            peft_model(x[:1])
        peft_model.base_model.enable_adapter_layers()
    elif mode == "same":
        peft_model.set_adapter(names[0])
        for _ in range(n_req):
            peft_model(x[:1])
    elif mode == "merge":
        # the "one merged model per skill" alternative: fold the adapter into
        # the base weights, run, then fold it back out.
        for nm in names:
            peft_model.set_adapter(nm)
            peft_model.base_model.merge_adapter()
            peft_model(x[:1])
            peft_model.base_model.unmerge_adapter()
    elif mode == "copy":
        # the naive implementation: one LoRA slot, overwritten per request.
        # The adapter weights are copied device->device into the active slot.
        for nm in names:
            copy_adapter(peft_model, nm, SLOT)
            peft_model.set_adapter(SLOT)
            peft_model(x[:1])
    else:
        raise ValueError(mode)
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) * 1000.0


def is_lora_layer(m) -> bool:
    """PEFT stores the per-adapter factors in a ModuleDict, which is NOT a
    dict subclass -- checking isinstance(..., dict) finds nothing."""
    return (hasattr(m, "lora_A") and hasattr(m, "lora_B")
            and isinstance(getattr(m, "lora_A", None), torch.nn.ModuleDict))


def lora_modules(peft_model: PeftModel):
    return [m for m in peft_model.modules() if is_lora_layer(m)]


def copy_adapter(peft_model: PeftModel, src: str, dst: str) -> None:
    """Copy adapter `src`'s weights into the `dst` slot (device->device)."""
    for m in lora_modules(peft_model):
        m.lora_A[dst].weight.data.copy_(m.lora_A[src].weight.data)
        m.lora_B[dst].weight.data.copy_(m.lora_B[src].weight.data)


def switch_overhead(peft_model: PeftModel, n: int) -> dict:
    """The cost of switching the active adapter, and of copying its weights in."""
    names = [f"skill{i}" for i in range(n)]

    def do_set():
        for nm in names:
            peft_model.set_adapter(nm)

    def do_copy():
        for nm in names:
            copy_adapter(peft_model, nm, SLOT)

    t_set, _ = timeit(do_set, warmup=2, reps=10)
    t_copy, _ = timeit(do_copy, warmup=2, reps=10)

    # PEFT's set_adapter is O(layers x adapters): it walks every LoRA layer and
    # rewrites requires_grad on every adapter it holds. The cost therefore
    # grows with the number of *resident* adapters, not with the number of
    # switches. Measured against the resident count, it is the number that
    # decides whether "switch per request" is viable at all.
    scaling = []
    for k in (1, 2, 4, 8, 16, 32):
        names_k = [f"skill{i}" for i in range(k)]

        def do_set_k():
            for nm in names_k:
                peft_model.set_adapter(nm)

        def do_set_k_infer():
            for nm in names_k:
                peft_model.set_adapter(nm, inference_mode=True)

        tk, _ = timeit(do_set_k, warmup=1, reps=5)
        tki, _ = timeit(do_set_k_infer, warmup=1, reps=5)
        scaling.append({"n_adapters_resident": k,
                        "set_adapter_per_switch_us": tk * 1000 / k,
                        "set_adapter_per_switch_us_inference_mode": tki * 1000 / k})
    return {"set_adapter_total_ms": t_set,
            "set_adapter_per_switch_us": t_set * 1000 / max(n, 1),
            "copy_total_ms": t_copy,
            "copy_per_switch_us": t_copy * 1000 / max(n, 1),
            "set_adapter_scaling": scaling}


def out_tensor(o):
    """DINOv2's forward returns a dataclass; the tensor we compare is the
    last hidden state."""
    if hasattr(o, "last_hidden_state"):
        return o.last_hidden_state
    if hasattr(o, "pooler_output"):
        return o.pooler_output
    return o


def correctness(peft_model: PeftModel, x: torch.Tensor) -> dict:
    """Do the adapters actually differ, and does the mixed path agree with
    N separate forwards?  Without this the timings compare nothing."""
    out = {}
    names = [f"skill{i}" for i in range(4)]

    # (a) each adapter must give a different answer
    singles = []
    for nm in names:
        peft_model.set_adapter(nm)
        singles.append(out_tensor(peft_model(x[:1])).float())
    # The RMS difference is the meaningful statistic here: the output tensor
    # has elements up to ~16 against an RMS of ~1.4, so a single outlier can
    # move the max-abs statistic by 10x without anything real changing.
    diffs, diffs_rms = [], []
    ref_rms = float(torch.sqrt((singles[0] ** 2).mean()))
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = (singles[i] - singles[j]).abs()
            diffs.append(float(d.max()))
            diffs_rms.append(float(torch.sqrt((d ** 2).mean())))
    out["max_output_diff_between_adapters"] = max(diffs)
    out["rms_output_diff_between_adapters"] = max(diffs_rms)
    out["output_rms"] = ref_rms
    out["adapters_are_distinct"] = max(diffs_rms) / ref_rms > 1e-3

    # (b) the mixed batch path must equal N separate forwards
    xb = x.repeat(len(names), 1, 1, 1)
    mixed = out_tensor(peft_model(xb, adapter_names=names)).float()
    # (i) permutation test: for every mixed row, the matching single must be
    #     the closest of the four -- otherwise the mixed path is mixing up rows
    diag, off, diag_rms, off_rms = [], [], [], []
    for i in range(len(names)):
        ds, dsr = [], []
        for j in range(len(names)):
            d = (mixed[i] - singles[j]).abs()
            ds.append(float(d.max()))
            dsr.append(float(torch.sqrt((d ** 2).mean())))
        diag.append(ds[i]); off.extend(v for j, v in enumerate(ds) if j != i)
        diag_rms.append(dsr[i]); off_rms.extend(v for j, v in enumerate(dsr) if j != i)
    out["mixed_diag_max_abs"] = max(diag)
    out["mixed_offdiag_min_abs"] = min(off)
    out["mixed_row_mapping_is_correct"] = max(diag_rms) <= min(off_rms)
    # (ii) how close the mixed path is to N separate forwards, relatively
    ref = max(float(singles[i].abs().max()) for i in range(len(names)))
    out["mixed_vs_separate_max_abs"] = max(diag)
    out["mixed_vs_separate_ref_max"] = ref
    out["mixed_vs_separate_rel_rms"] = max(diag_rms) / ref_rms if ref_rms else float("nan")
    out["mixed_vs_separate_rel"] = out["mixed_vs_separate_rel_rms"]
    # bf16 carries ~8 mantissa bits and the mixed path adds the LoRA delta to
    # the base output *outside* the layer while the switch path adds it
    # inside, so the two accumulate in a different order.
    out["mixed_matches_separate"] = out["mixed_vs_separate_rel_rms"] < 0.02

    # (c) the naive copy slot must reproduce the source adapter
    copy_adapter(peft_model, names[2], SLOT)
    peft_model.set_adapter(SLOT)
    cp = out_tensor(peft_model(x[:1])).float()
    out["copy_slot_matches_source"] = float((cp[0] - singles[2]).abs().max())
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    torch.backends.cuda.matmul.allow_tf32 = False

    print("=" * 78)
    print("EXP 3 -- skills as small adapters: N LoRA adapters on one shared base")
    print("=" * 78)
    st = box_state()
    print(format_box_state(st))
    w = warm_gpu(seconds=2.5)
    print(f"  gpu clock warmed: {w['clock_before_mhz']:.0f} -> {w['clock_after_mhz']:.0f} MHz")

    peft_model, base = build_base()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    alloc_one_adapter = torch.cuda.memory_allocated()
    add_adapters(peft_model, N_ADAPTERS)
    stats = adapter_stats(peft_model)
    size_table = lora_size_table(peft_model)
    results = {"adapter_stats": stats, "runs": []}
    results["lora_size_table"] = size_table
    print(f"\n  base: dinov2-giant (bf16), "
          f"{sum(p.numel() for p in base.parameters())/1e6:.1f} M params")
    print(f"  adapters: {stats['n_adapters']} x r={LORA_R} on {stats['target_modules']}")
    print(f"    per adapter: {stats['per_adapter_params']/1e6:.2f} M params, "
          f"{stats['per_adapter_mib']:.2f} MiB, {stats['per_adapter_layers']} modules")
    print(f"    all {stats['n_adapters']} resident: {stats['total_mib']:.1f} MiB "
          f"({stats['total_bytes']/1024**3:.3f} GiB)")
    print("    adapter size vs rank (Kimi's '10-50M params' band):")
    for row in size_table["table"]:
        flag = "  <- in the 10-50M band" if 10e6 <= row["params"] <= 50e6 else ""
        print(f"      r={row['r']:4d}: {row['params_m']:7.2f} M params, "
              f"{row['mib_bf16']:7.2f} MiB as bf16, "
              f"{row['mib_fp32']:7.2f} MiB as fp32{flag}")
    print(f"    adapter weight dtype as PEFT created it: {size_table['adapter_dtypes']}")

    x = torch.randn(1, 3, IMG, IMG, device="cuda", dtype=torch.bfloat16)

    # ---- correctness first: are we timing anything real?
    chk = correctness(peft_model, x)
    results["correctness"] = chk
    print(f"\n  correctness: adapters distinct: {chk['adapters_are_distinct']} "
          f"({chk['rms_output_diff_between_adapters']:.4g} rms, "
          f"{chk['rms_output_diff_between_adapters']/chk['output_rms']:.2%} of the output rms); "
          f"mixed == separate: {chk['mixed_matches_separate']} "
          f"(rel rms {chk['mixed_vs_separate_rel_rms']:.2%}, "
          f"row mapping ok: {chk['mixed_row_mapping_is_correct']}); "
          f"copy slot == source: {chk['copy_slot_matches_source']:.4g}")

    # ---- the switch cost, on its own
    sc = switch_overhead(peft_model, N_ADAPTERS)
    results["switch_cost"] = sc
    print(f"\n  set_adapter (name swap, all adapters resident): "
          f"{sc['set_adapter_per_switch_us']:.1f} us per switch")
    print(f"  copy weights into the active slot:                "
          f"{sc['copy_per_switch_us']:.1f} us per switch")
    print("  set_adapter cost vs the number of RESIDENT adapters:")
    for row in sc["set_adapter_scaling"]:
        print(f"      {row['n_adapters_resident']:3d} resident: "
              f"{row['set_adapter_per_switch_us']:9.1f} us per switch  "
              f"(inference_mode=True: {row['set_adapter_per_switch_us_inference_mode']:9.1f} us)")

    # ---- serving modes
    print("\n--- serving modes (N requests) ---")
    for n_req in (1, 2, 4, 8, 16, 32):
        row = {"n_req": n_req}
        for mode in ("base", "same", "switch", "copy", "merge", "mixed"):
            ms = serve(peft_model, x, n_req, mode)
            row[mode + "_ms"] = ms
            row[mode + "_per_req_ms"] = ms / n_req
        results["runs"].append(row)
        print(f"    N={n_req:3d}  base {row['base_ms']:8.1f} ms ({row['base_per_req_ms']:6.2f}/req) | "
              f"same {row['same_ms']:8.1f} ms ({row['same_per_req_ms']:6.2f}/req) | "
              f"switch {row['switch_ms']:8.1f} ms ({row['switch_per_req_ms']:6.2f}/req) | "
              f"copy {row['copy_ms']:8.1f} ms ({row['copy_per_req_ms']:6.2f}/req) | "
              f"merge {row['merge_ms']:8.1f} ms ({row['merge_per_req_ms']:6.2f}/req) | "
              f"mixed {row['mixed_ms']:8.1f} ms ({row['mixed_per_req_ms']:6.2f}/req) | "
              f"mixed vs switch {row['switch_ms']/row['mixed_ms']:.2f}x")

    # ---- joules for the two interesting modes
    print("\n--- joules (whole-box INA238 VIN) ---")
    for mode in ("switch", "mixed"):
        with PowerMeter() as pm:
            torch.cuda.synchronize()
            t0 = pm.mark()
            reps = 0
            deadline = time.perf_counter() + 3.0
            n_req = 4
            while time.perf_counter() < deadline or reps < 3:
                serve(peft_model, x, n_req, mode)
                reps += 1
            torch.cuda.synchronize()
            t1 = pm.mark()
            j = pm.joules_between("VIN_total", t0, t1)
            j_bl = pm.joules_above_baseline("VIN_total", t0, t1)
            w_tot = pm.watts_between("VIN_total", t0, t1)
        jpr = j / (reps * n_req)
        jpr_bl = j_bl / (reps * n_req)
        results[f"joules_{mode}"] = {
            "n_req": n_req, "reps": reps,
            "joules_total": j, "joules_per_request": jpr,
            "joules_per_request_above_baseline": jpr_bl,
            "mean_w_total": w_tot,
            "requests_per_s": reps * n_req / (t1 - t0),
        }
        print(f"    {mode:7s}: {jpr:8.4f} J per request  ({jpr_bl:7.4f} above baseline)  "
              f"({w_tot:5.1f} W, {reps*n_req/(t1-t0):7.1f} req/s)")

    # ---- memory: what do the resident adapters cost on the device?
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    base_alloc = alloc_one_adapter
    torch.cuda.reset_peak_memory_stats()
    tot = 0
    for name, module in peft_model.named_modules():
        if is_lora_layer(module):
            for ad in module.lora_A:
                tot += module.lora_A[ad].weight.numel()
                tot += module.lora_B[ad].weight.numel()
    now_alloc = torch.cuda.memory_allocated()
    mem = {
        "base_model_allocated_mib": base_alloc / 1024 ** 2,
        "allocated_with_adapters_mib": now_alloc / 1024 ** 2,
        "adapters_allocated_mib": (now_alloc - base_alloc) / 1024 ** 2,
        "adapters_allocated_per_adapter_mib":
            (now_alloc - base_alloc) / 1024 ** 2 / (N_ADAPTERS - 1),
        "adapter_params_seen": tot,
        "adapter_bytes_measured": sum(
            module.lora_A[ad].weight.numel() * module.lora_A[ad].weight.element_size()
            + module.lora_B[ad].weight.numel() * module.lora_B[ad].weight.element_size()
            for name, module in peft_model.named_modules() if is_lora_layer(module)
            for ad in module.lora_A),
        "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024 ** 2,
    }
    results["memory"] = mem
    print(f"\n  device memory: base model {mem['base_model_allocated_mib']:.1f} MiB, "
          f"{N_ADAPTERS} adapters {mem['adapters_allocated_mib']:.1f} MiB "
          f"({mem['adapters_allocated_per_adapter_mib']:.2f} MiB each), "
          f"peak {mem['peak_allocated_mib']:.1f} MiB")
    results["gpu_clock_mhz"] = gpu_clock_mhz()

    with open(os.path.join(OUT, "exp3_lora.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nwrote {OUT}/exp3_lora.json")


if __name__ == "__main__":
    with torch.no_grad():
        main()
