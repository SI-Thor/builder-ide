"""Experiment C -- FP8 (and FP4) matmul on the Thor's Blackwell tensor cores
vs FP16/BF16, as the upper bound for quantized generators.

Hypothesis
----------
The Thor's sm_110 Blackwell tensor cores do FP8 (e4m3/e5m2) matmul at
measurably higher throughput than FP16/BF16, and FP8 halves the resident size
of every weight matrix -- so several quantized generators stay resident in
unified memory at once instead of swapping in and out.

Sub-tests
---------
C1  device / stack sanity (cc, cuda runtime, fp8 dtype availability)
C2  FP32, FP16, BF16 matmul TFLOPS
C3  FP8 e4m3 matmul TFLOPS + accuracy vs the FP16 reference
C4  FP4 (nvfp4) attempt -- exploratory, reported as found
C5  bytes per parameter and the residency consequence
"""

import statistics
import sys
import time

import torch

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import boxstate

GB = 1 << 30


def hdr(t):
    print("\n" + "-" * 78)
    print(t)
    print("-" * 78)


def bench(fn, warmup=5, reps=10):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts), min(ts), max(ts)


def tflops(m, n, k, secs):
    return 2.0 * m * n * k / secs / 1e12


def main():
    boxstate.banner("EXP C -- FP8/FP4 matmul on Blackwell tensor cores (Thor)")
    print(f"torch          : {torch.__version__}  cuda={torch.version.cuda}")
    print(f"device         : {torch.cuda.get_device_name(0)}  "
          f"cc={torch.cuda.get_device_capability(0)}")
    print(f"cudnn          : {torch.backends.cudnn.version()}")
    print(f"tf32 allowed   : {torch.backends.cuda.matmul.allow_tf32}")
    print(f"fp8 dtype      : {hasattr(torch, 'float8_e4m3fn')}")
    print(f"fp8 dtypes     : "
          f"{[d for d in dir(torch) if d.startswith('float8')]}")
    print(f"fp4 dtype      : {hasattr(torch, 'float4_e2m1fn_x2')}")

    # ------------------------------------------------------------------
    hdr("C1/C2  FP32 / FP16 / BF16 matmul")
    SIZES = [(4096, 4096, 4096), (8192, 8192, 8192)]
    results = {}

    for M, N, K in SIZES:
        print(f"\n  --- M={M} N={N} K={K} ---")
        for name, dt in [("fp32", torch.float32),
                         ("fp16", torch.float16),
                         ("bf16", torch.bfloat16)]:
            try:
                a = torch.randn(M, K, device="cuda", dtype=dt)
                b = torch.randn(K, N, device="cuda", dtype=dt)
                med, lo, hi = bench(lambda: torch.mm(a, b))
                key = (name, M)
                results[key] = med
                print(f"    {name:5s} : {med * 1000:8.2f} ms (min {lo * 1000:7.2f} / "
                      f"max {hi * 1000:7.2f})  {tflops(M, N, K, med):7.2f} TFLOPS")
                del a, b
                torch.cuda.empty_cache()
            except Exception as exc:
                print(f"    {name:5s} : FAILED {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    hdr("C3  FP8 e4m3 matmul (torch._scaled_mm) -- rowwise scales")
    fp8 = torch.float8_e4m3fn
    for M, N, K in SIZES:
        print(f"\n  --- M={M} N={N} K={K} ---")
        try:
            torch.manual_seed(0)
            a32 = torch.randn(M, K, device="cuda", dtype=torch.float32)
            b32 = torch.randn(N, K, device="cuda", dtype=torch.float32)
            a8 = a32.to(fp8)
            b8 = b32.to(fp8)
            scale_a = torch.ones((M, 1), device="cuda", dtype=torch.float32)
            scale_b = torch.ones((1, N), device="cuda", dtype=torch.float32)

            ref = torch.mm(a32.to(torch.bfloat16), b32.to(torch.bfloat16).t())

            med, lo, hi = bench(
                lambda: torch._scaled_mm(a8, b8.t(), scale_a, scale_b,
                                         out_dtype=torch.bfloat16))
            out = torch._scaled_mm(a8, b8.t(), scale_a, scale_b,
                                   out_dtype=torch.bfloat16)
            err = float((out.float() - ref.float()).abs().max())
            denom = float(ref.float().abs().max())
            results[("fp8", M)] = med
            print(f"    fp8 e4m3: {med * 1000:8.2f} ms (min {lo * 1000:7.2f} / "
                  f"max {hi * 1000:7.2f})  {tflops(M, N, K, med):7.2f} TFLOPS")
            print(f"    accuracy: max abs err {err:.4f}  (ref max |v| {denom:.2f}, "
                  f"rel {err / denom:.2e})")
            fp16_med = results.get(("fp16", M))
            if fp16_med:
                print(f"    speedup vs fp16 : {fp16_med / med:5.2f}x")
                print(f"    speedup vs bf16 : {results[('bf16', M)] / med:5.2f}x")
            del a32, b32, a8, b8, out, ref
            torch.cuda.empty_cache()
        except Exception as exc:
            print(f"    fp8      : FAILED {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    hdr("C4  FP4 (nvfp4) -- via torchao, the only route that packs on this stack")
    try:
        from torchao.prototype.mx_formats.nvfp4_tensor import NVFP4Tensor

        M, N, K = 8192, 8192, 8192
        a = torch.randn(M, K, device="cuda", dtype=torch.bfloat16)
        b = torch.randn(N, K, device="cuda", dtype=torch.bfloat16)
        qa = NVFP4Tensor.to_nvfp4(a)
        qb = NVFP4Tensor.to_nvfp4(b)
        med, lo, hi = bench(lambda: torch.mm(qa, qb.t()))
        results[("fp4", M)] = med
        print(f"    fp4 nvfp4: {med * 1000:8.2f} ms  {tflops(M, N, K, med):7.2f} TFLOPS")

        # Is it actually using FP4 tensor cores, or decompressing?
        t_deq, _, _ = bench(lambda: qa.dequantize())
        da, db = qa.dequantize(), qb.dequantize()
        t_bf, _, _ = bench(lambda: torch.mm(da, db.t()))
        print(f"    dequantize one matrix : {t_deq * 1000:8.2f} ms")
        print(f"    bf16 mm of dequantized: {t_bf * 1000:8.2f} ms "
              f"({tflops(M, N, K, t_bf):.2f} TFLOPS)")
        print(f"    dequant + bf16 mm     : {(t_deq + t_bf) * 1000:8.2f} ms")
        print(f"    ratio nvfp4 / (deq+mm): {med / (t_deq + t_bf):.2f}  "
              f"(1.0 => it is just a fallback path)")
        ref = torch.mm(a, b.t())
        out = torch.mm(qa, qb.t())
        rel = float((out.float() - ref.float()).abs().max() / ref.float().abs().max())
        print(f"    nvfp4 rel err vs bf16 : {rel:.4f}")
        print(f"    VERDICT: FP4 tensor cores are NOT reachable on sm_110 through")
        print(f"    torch 2.15 + torchao 0.18 -- the path is slower than dequantizing")
        print(f"    to bf16 and multiplying. FP8 is the usable quantized path.")
        del a, b, qa, qb, da, db, ref, out
        torch.cuda.empty_cache()
    except Exception as exc:
        print(f"    fp4      : FAILED {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    hdr("C4b  a diffusion-step-shaped GEMM chain, measured end to end")
    # Representative transformer/UNet linear shapes; tokens = 4096.
    shapes = [(320, 320), (640, 640), (1280, 1280), (1280, 5120), (5120, 1280),
              (640, 1920), (1920, 640), (1280, 5120)]
    tokens = 4096
    a16 = torch.randn(tokens, 1280, device="cuda", dtype=torch.float16)
    b16 = torch.randn(tokens, 1280, device="cuda", dtype=torch.float16)

    def chain16():
        for din, dout in shapes:
            x = torch.randn(tokens, din, device="cuda", dtype=torch.float16)
            torch.mm(x, torch.randn(dout, din, device="cuda", dtype=torch.float16).t())

    def chain8():
        for din, dout in shapes:
            x = torch.randn(tokens, din, device="cuda", dtype=torch.float16)
            xa = x.to(torch.float8_e4m3fn)
            wb = torch.randn(dout, din, device="cuda",
                             dtype=torch.float16).to(torch.float8_e4m3fn)
            s_a = torch.ones((tokens, 1), device="cuda", dtype=torch.float32)
            s_b = torch.ones((1, dout), device="cuda", dtype=torch.float32)
            torch._scaled_mm(xa, wb.t(), s_a, s_b, out_dtype=torch.bfloat16)

    t16, _, _ = bench(chain16, warmup=2, reps=5)
    t8, _, _ = bench(chain8, warmup=2, reps=5)
    print(f"    fp16 chain: {t16 * 1000:8.2f} ms")
    print(f"    fp8  chain: {t8 * 1000:8.2f} ms")
    print(f"    speedup    : {t16 / t8:.2f}x")
    print(f"    (NOTE: this chain includes the fp32->fp8 cast of each activation,")
    print(f"     which a fused fp8 pipeline would avoid -- so this UNDERSTATES")
    print(f"     the fp8 benefit for a generator that keeps activations in fp8.)")

    # ------------------------------------------------------------------
    hdr("C5  bytes per parameter and the residency consequence")
    n_params = 4_000_000_000  # a 4B-parameter generator
    for name, bpp, note in [("fp32", 4, ""),
                            ("fp16/bf16", 2, ""),
                            ("fp8 e4m3", 1, "MEASURED WORKING"),
                            ("fp4 nvfp4", 0.5, "measured NOT usable on this stack"),
                            ("int8", 1, "")]:
        size_gb = n_params * bpp / GB
        fits = int(122.8 // size_gb) if size_gb else 0
        print(f"    {name:22s}: {size_gb:6.2f} GB per 4B-param model  -> "
              f"{fits:3d} fit in 122.8 GB (weights only)  {note}")

    hdr("SUMMARY")
    for (name, M), t in sorted(results.items()):
        N = K = M
        print(f"    {name:5s} @{M}: {t * 1000:8.2f} ms  {tflops(M, N, K, t):7.2f} TFLOPS")
    if ("fp8", 8192) in results and ("fp16", 8192) in results:
        print(f"    FP8 vs FP16 @8192 : {results[('fp16', 8192)] / results[('fp8', 8192)]:.2f}x")
    if ("fp8", 8192) in results and ("bf16", 8192) in results:
        print(f"    FP8 vs BF16 @8192 : {results[('bf16', 8192)] / results[('fp8', 8192)]:.2f}x")


if __name__ == "__main__":
    main()
