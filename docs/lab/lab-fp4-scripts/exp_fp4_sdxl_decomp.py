# exp_fp4_sdxl_decomp.py — per-GEMM decomposition of the SDXL-ish UNet workload:
# for each of the 8 representative linears at 4,096 tokens, time BF16 torch mm
# vs the real FP4 path (activation quantize + cuBLASLt NVFP4 GEMM + transpose),
# and the quantize kernels alone. Explains exp-fp4-models.md section E.
#
# Run: .venv/bin/python scripts/exp_fp4_sdxl_decomp.py | tee results/fp4-sdxl-decomp.txt

import sys
import time

import torch

sys.path.insert(0, "scripts")
import fp4torch as F  # noqa: E402

torch.manual_seed(11)
SHAPES = [(960, 320), (320, 960), (2560, 320), (320, 2560),
          (1920, 640), (640, 1920), (5120, 1280), (1280, 5120)]
TOK = 4096


def timeit(fn, iters=30, rounds=5):
    gms = []
    for _ in range(rounds):
        torch.cuda.synchronize()
        e0, e1 = torch.cuda.Event(True), torch.cuda.Event(True)
        e0.record()
        for _ in range(iters):
            fn()
        e1.record()
        torch.cuda.synchronize()
        gms.append(e0.elapsed_time(e1) / iters)
    gms.sort()
    return gms[len(gms) // 2]


# clock warm (rule 3)
x = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
t0 = time.perf_counter()
while time.perf_counter() - t0 < 1.6:
    x @ x
torch.cuda.synchronize()

with open("/proc/loadavg") as f:
    la = f.read().split()[0]
print(f"# decomposition per GEMM (TOK=4096), final .so  load={la}")
print(f"{'shape N,K':>12} {'bf16 mm':>9} {'fp4 .so':>9} {'quant':>9} {'fp4-quant':>9} {'TF fp4':>7} {'TF bf16':>8}")
for N, K in SHAPES:
    W = torch.randn(N, K, device="cuda") / K ** 0.5
    X = torch.randn(TOK, K, device="cuda")
    Wb, Xb = W.bfloat16(), X.bfloat16()
    packed = torch.zeros(F.packed_pad_bytes(TOK, K), dtype=torch.uint8, device="cuda")
    scale = torch.zeros(F.scale_pad_bytes(TOK, K), dtype=torch.uint8, device="cuda")
    wp = torch.zeros(F.packed_pad_bytes(N, K), dtype=torch.uint8, device="cuda")
    ws = torch.zeros(F.scale_pad_bytes(N, K), dtype=torch.uint8, device="cuda")
    F.fp4_quant_into(W, wp, ws)
    F.fp4_quant_into(X, packed, scale)
    out16 = torch.empty(TOK, N, dtype=torch.float16, device="cuda")

    def fp4_path():
        F.fp4_quant_into(X, packed, scale)
        F.fp4_gemm_raw(packed, scale, wp, ws, out16, TOK, N, K)

    t_bf = timeit(lambda: Xb @ Wb.T)
    t_all = timeit(fp4_path)
    t_q = timeit(lambda: F.fp4_quant_into(X, packed, scale))
    fl = 2 * TOK * N * K
    tag = f"{N},{K}"
    print(f"{tag:>12} {t_bf:9.3f} {t_all:9.3f} {t_q:9.3f} {t_all - t_q:9.3f} "
          f"{fl / (t_all * 1e-3) / 1e12:7.1f} {fl / (t_bf * 1e-3) / 1e12:8.1f}", flush=True)
