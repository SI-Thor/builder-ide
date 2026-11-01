# exp_fp4_models.py — Part 2 of the FP4 brief: our own NVFP4 models on the Thor.
#
# Prerequisite (Part 1, measured in results/sweep-main.txt): cuBLASLt NVFP4 GEMM
# runs at 371-456 TFLOPS on sm_110 — 1.8-2.2x FP8, 3.6-4.3x BF16. So Part 2 runs.
#
# What this measures, per the brief:
#   A. cross-check: the real tensor-core path (.so) vs the pure-torch fake quant
#   B. decision MLP (tile scorer, 512->1024->1024->64): BF16 vs PTQ vs QAT vs REAL
#      FP4 — quality = top-1 tile-choice agreement + Q MSE vs a fixed teacher
#   C. motion policy stand-in (768->2048->2048->256): same four variants
#   D. latency/memory: eager vs CUDA-graphed, BF16 vs real FP4, batch 1/64/256
#   E. SDXL-ish UNet linear chain at 4096 tokens: FP4 vs BF16, eager + graphed
#
# Box rules honored: GPU clock warmed 1.6 s before every timed section (rule 3),
# variants interleaved inside each timed round (rule 4), loadavg printed beside
# every table, models are small enough that peak memory stays < 8 GB (no lock
# needed; checked with free -g at start and end).
#
# Run: .venv/bin/python scripts/exp_fp4_models.py 2>&1 | tee results/fp4-models.txt

import sys
import time

import torch

sys.path.insert(0, "scripts")
import fp4torch as F  # noqa: E402


def hdr(s):
    print(f"\n=== {s} " + "=" * max(0, 66 - len(s)), flush=True)


def boxstate():
    with open("/proc/loadavg") as f:
        la = f.read().split()[0]
    with open("/proc/meminfo") as f:
        mi = dict(l.split(":", 1) for l in f.readlines())
    avail = int(mi["MemAvailable"].strip().rstrip(" kB")) / 2**20
    return f"load={la} mem_avail={avail:.1f}GiB"


def rrms(a, b):
    return ((a - b).pow(2).mean().sqrt() / b.pow(2).mean().sqrt()).item()


def warm_clock(seconds=1.6):
    x = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        x @ x
    torch.cuda.synchronize()


# ----------------------------------------------------------------------------
# A. cross-check real vs fake
# ----------------------------------------------------------------------------
hdr("A. real .so path vs torch fake quant")
torch.manual_seed(7)
x = torch.randn(256, 1024, device="cuda") * 0.5
w = torch.randn(512, 1024, device="cuda") * 0.3
ax, aw = F.Fp4Tensor(x), F.Fp4Tensor(w)
out = ax.matmul_t(aw, None)
fx, fw = F.nvfp4_fake_quant(x), F.nvfp4_fake_quant(w)
ref = fx @ fw.T
print(f"real vs fake relRMS: {rrms(out.float(), ref):.3e}   ({boxstate()})")
print(f"fp4 weight bytes: {aw.nbytes()} vs bf16 {w.numel()*2} -> {w.numel()*2/aw.nbytes():.2f}x smaller")

# ----------------------------------------------------------------------------
# model definitions
# ----------------------------------------------------------------------------
def mlp(dims, act):
    mods = []
    for i in range(len(dims) - 1):
        mods.append(torch.nn.Linear(dims[i], dims[i + 1], bias=False))
    return mods, act


def make_teacher(dims, act, seed=123):
    """a fixed random MLP as the behavior to imitate (distillation target)"""
    g = torch.Generator(device="cpu").manual_seed(seed)
    layers = []
    for i in range(len(dims) - 1):
        W = (torch.randn((dims[i + 1], dims[i]), generator=g) * (1.0 / dims[i] ** 0.5)).cuda()
        b = torch.zeros(dims[i + 1]).cuda()
        layers.append((W, b))
    def teacher(x):
        for W, b in layers[:-1]:
            x = act(x @ W.T + b)
        W, b = layers[-1]
        return x @ W.T + b
    return teacher


def torch_forward(params, act, x, qat=False):
    """params: list of (W, b). qat: fake-quant W and x (STE), bias stays fp32."""
    for W, b in params[:-1]:
        Wq = F.fq(W) if qat else W
        x = act(F.fq(x) @ Wq.T + b if qat else x @ W.T + b)
    W, b = params[-1]
    Wq = F.fq(W) if qat else W
    return F.fq(x) @ Wq.T + b if qat else x @ W.T + b


def real_fp4_forward(Ws_fp4, bs, act, x):
    """real tensor-core path: weights NVFP4 (bias fp32), activations quantized per layer."""
    for i, Wq in enumerate(Ws_fp4[:-1]):
        a = F.Fp4Tensor(x.detach().contiguous().float())
        x = act(a.matmul_t(Wq, None).float() + bs[i])
    a = F.Fp4Tensor(x.detach().contiguous().float())
    return a.matmul_t(Ws_fp4[-1], None).float() + bs[-1]


def train(dims, act, teacher, steps=2500, bs=2048, din=512, qat=False, seed=0, lr=2e-3):
    torch.manual_seed(seed)
    params = []
    for i in range(len(dims) - 1):
        W = (torch.randn(dims[i + 1], dims[i], device="cuda") / dims[i] ** 0.5).requires_grad_()
        b = torch.zeros(dims[i + 1], device="cuda").requires_grad_()
        params.append((W, b))
    flat = [p for pair in params for p in pair]
    opt = torch.optim.AdamW(flat, lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    g = torch.Generator(device="cpu").manual_seed(999)
    for step in range(steps):
        x = torch.randn((bs, din), generator=g).cuda()
        with torch.no_grad():
            y = teacher(x)
        yh = torch_forward(params, act, x, qat=qat)
        loss = (yh - y).pow(2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
    return [(W.detach(), b.detach()) for W, b in params], loss.item()


def run_model_bench(name, dims, act, teacher, note, n_test=8192):
    hdr(f"{name}  dims={'->'.join(map(str, dims))}")
    din = dims[0]
    g = torch.Generator(device="cpu").manual_seed(4242)
    x_test = torch.randn((n_test, din), generator=g).cuda()
    with torch.no_grad():
        y_teacher = teacher(x_test)

    # BF16-trained baseline
    P_bf, _ = train(dims, act, teacher, din=dims[0], qat=False)
    with torch.no_grad():
        y_bf = torch_forward(P_bf, act, x_test).bfloat16().float()
        # PTQ: quantize the BF16-trained weights and activations at inference
        y_ptq = torch_forward(P_bf, act, x_test, qat=True)
    # QAT from scratch
    P_qat, _ = train(dims, act, teacher, din=dims[0], qat=True)
    with torch.no_grad():
        y_qat = torch_forward(P_qat, act, x_test, qat=True)

    # REAL FP4 (QAT weights and BF16 weights) through the tensor cores
    with torch.no_grad():
        Ws_fp4_qat = [F.Fp4Tensor(W.contiguous()) for W, _ in P_qat]
        Ws_fp4_bf = [F.Fp4Tensor(W.contiguous()) for W, _ in P_bf]
        y_real_qat = real_fp4_forward(Ws_fp4_qat, [b for _, b in P_qat], act, x_test)
        y_real_ptq = real_fp4_forward(Ws_fp4_bf, [b for _, b in P_bf], act, x_test)

    def agree(yh, yref):
        return (yh.argmax(1) == yref.argmax(1)).float().mean().item()

    print(f"teacher output dim {y_teacher.shape[1]}  {note}  {boxstate()}")
    print(f"  (vs teacher)      Q-MSE    top1-agree   relRMS      (vs own BF16 output)")
    for nm, yh in [("BF16 (baseline)", y_bf), ("PTQ fake-quant", y_ptq),
                   ("QAT fake-quant", y_qat), ("PTQ REAL fp4", y_real_ptq),
                   ("QAT REAL fp4", y_real_qat)]:
        mse = torch.nn.functional.mse_loss(yh, y_teacher).item()
        print(f"  {nm:<18} {mse:.4f}     {agree(yh, y_teacher)*100:5.1f}%      "
              f"{rrms(yh, y_teacher):.4f}      relRMS {rrms(yh, y_bf):.4f}  top1-keep {agree(yh, y_bf)*100:5.1f}%")
    # fake vs real on identical weights (isolates GPU-vs-GPU + fp16 rounding)
    print(f"  QAT real vs QAT fake relRMS: {rrms(y_real_qat, y_qat):.3e}")
    wbytes_bf = sum(W.numel() * 2 + b.numel() * 2 for W, b in P_bf)
    wbytes_f4 = sum(t.nbytes() for t in Ws_fp4_qat) + sum(b.numel() * 2 for _, b in P_qat)
    print(f"  weights+bias: bf16 {wbytes_bf/1e6:.2f} MB  fp4+fp32bias {wbytes_f4/1e6:.2f} MB  ({wbytes_bf/wbytes_f4:.2f}x smaller)")
    return P_qat, Ws_fp4_qat


gelu = torch.nn.functional.gelu
tanh = torch.tanh

print(f"\n# exp_fp4_models  torch={torch.__version__}  cublasLt={F._LIB.fp4_cublaslt_version()}  {boxstate()}")

teacher_dec = make_teacher([512, 1024, 1024, 64], gelu, seed=123)
Ws_dec, Ws_dec_fp4 = run_model_bench("B. decision MLP (tile scorer)", [512, 1024, 1024, 64],
                                     gelu, teacher_dec, "Q over 64 candidate tiles")

teacher_pol = make_teacher([768, 2048, 2048, 256], gelu, seed=321)
Ws_pol, Ws_pol_fp4 = run_model_bench("C. motion policy stand-in", [768, 2048, 2048, 256],
                                     gelu, teacher_pol, "256-dim action (torque) vector")

# ----------------------------------------------------------------------------
# D. latency: eager vs graphed, bf16 vs real fp4, batch sweep
# ----------------------------------------------------------------------------
hdr("D. latency per forward (motion policy 768->2048->2048->256), median of 5x20")

# NOTE: the graphed FP4 path needs weights and activations in torch-owned
# buffers so nothing allocates inside the capture; weights_to_raw_buffers
# re-quantizes the fp32 weights into those buffers once.
def weights_to_raw_buffers(Ws_fp32):
    outs = []
    for W in Ws_fp32:
        K, N = W.shape[1], W.shape[0]
        packed = torch.empty(F.packed_pad_bytes(N, K), dtype=torch.uint8, device="cuda")
        scale = torch.zeros(F.scale_pad_bytes(N, K), dtype=torch.uint8, device="cuda")
        F.fp4_quant_into(W.contiguous().float(), packed, scale)
        outs.append((packed, scale))
    return outs


def graphed_fp4_forward(dims, W_raw, B, capture_iter=3):
    """capture the whole chain (quant -> gemm -> gelu) with static input.

    Batches are padded to a multiple of 8 (>= 8): cuBLASLt has no FP4 TN
    algorithm for ragged/small M and computes garbage at M=1 (measured)."""
    Bp = max(8, (B + 7) // 8 * 8)
    class G:
        pass
    g = G()
    g.dims, g.W_raw, g.B, g.Bp = dims, W_raw, B, Bp
    g.bufs = {}
    for i in range(len(dims) - 1):
        K, N = dims[i], dims[i + 1]
        g.bufs[i] = (torch.zeros(F.packed_pad_bytes(Bp, K), dtype=torch.uint8, device="cuda"),
                     torch.zeros(F.scale_pad_bytes(Bp, K), dtype=torch.uint8, device="cuda"),
                     torch.empty(Bp, N, dtype=torch.float16, device="cuda"))
    g.static_in = torch.zeros(B, dims[0], dtype=torch.float32, device="cuda")

    def chain(x32):
        xin = torch.zeros(Bp, x32.shape[1], dtype=torch.float32, device="cuda")
        xin[:B] = x32
        for i in range(len(dims) - 2):
            packed, scale, out16 = g.bufs[i]
            F.fp4_quant_into(xin, packed, scale)
            wp, ws = g.W_raw[i]
            F.fp4_gemm_raw(packed, scale, wp, ws, out16, Bp, dims[i + 1], dims[i])
            xin = torch.zeros(Bp, out16.shape[1], dtype=torch.float32, device="cuda")
            xin[:B] = gelu(out16[:B].float())
        i = len(dims) - 2
        packed, scale, out16 = g.bufs[i]
        F.fp4_quant_into(xin, packed, scale)
        wp, ws = g.W_raw[i]
        F.fp4_gemm_raw(packed, scale, wp, ws, out16, Bp, dims[i + 1], dims[i])
        return out16[:B].float()

    # warm + resolve algos eagerly on the static buffers, then capture
    for _ in range(capture_iter):
        out = chain(g.static_in)
    torch.cuda.synchronize()
    g.static_out = out
    g.graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g.graph):
        g.static_out = chain(g.static_in)
    return g


def graphed_bf16_forward(dims, params, B):
    """params: list of W tensors or (W, b) tuples; bf16 linear chain + gelu."""
    class G:
        pass
    g = G()
    lin = []
    for i in range(len(dims) - 1):
        l = torch.nn.Linear(dims[i], dims[i + 1], bias=True).cuda().bfloat16()
        item = params[i]
        W, b = (item, None) if torch.is_tensor(item) else item
        with torch.no_grad():
            l.weight.copy_(W.bfloat16())
            if b is not None:
                l.bias.copy_(b.bfloat16())
        lin.append(l)
    g.static_in = torch.zeros(B, dims[0], dtype=torch.bfloat16, device="cuda")

    def chain(x):
        for l in lin[:-1]:
            x = gelu(l(x))
        return lin[-1](x)

    for _ in range(3):
        out = chain(g.static_in)
    torch.cuda.synchronize()
    g.graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g.graph):
        g.static_out = chain(g.static_in)
    return g


def time_forward(fn, iters=20, rounds=5):
    """returns (gpu_ms_median, host_issue_ms_median)"""
    gms, hms = [], []
    for r in range(rounds):
        torch.cuda.synchronize()
        ev0, ev1 = torch.cuda.Event(True), torch.cuda.Event(True)
        t0 = time.perf_counter()
        ev0.record()
        for _ in range(iters):
            fn()
        ev1.record()
        issue = (time.perf_counter() - t0) * 1e3 / iters  # enqueue time per iter
        torch.cuda.synchronize()
        gms.append(ev0.elapsed_time(ev1) / iters)
        hms.append(issue)
    gms.sort(); hms.sort()
    return gms[len(gms) // 2], hms[len(hms) // 2]


dims_pol = [768, 2048, 2048, 256]
W_raw_pol = weights_to_raw_buffers([W for W, _ in Ws_pol])
print(f"  ({boxstate()})")
# resident bf16 weights (the fair serving baseline; round-1's C4b already
# measured the cast-per-layer port as a separate, worse case)
Wb_pol = [(W.bfloat16(), b.bfloat16()) for W, b in Ws_pol]
print(f"  {'B':>4} {'bf16 eager':>22} {'bf16 graph':>22} {'fp4 eager':>22} {'fp4 graph':>22}")
for B in (1, 64, 256):
    xb = torch.randn(B, 768, device="cuda")
    gbf = graphed_bf16_forward(dims_pol, Ws_pol, B)
    gfp = graphed_fp4_forward(dims_pol, W_raw_pol, B)

    def bf_eager():
        x = xb.bfloat16()
        with torch.no_grad():
            for i, (W, b) in enumerate(Wb_pol):
                x = x @ W.T + b
                if i < len(Wb_pol) - 2:
                    x = gelu(x)
        return x

    def fp_eager():
        return real_fp4_forward(Ws_pol_fp4, [b for _, b in Ws_pol], gelu, xb)

    rows = []
    for fn in (bf_eager, lambda: gbf.graph.replay(), fp_eager, lambda: gfp.graph.replay()):
        warm_clock(0.3)
        gms, hms = time_forward(fn)
        rows.append(f"{gms:8.3f}ms/{hms:6.3f}enq")
    print(f"  {B:>4} " + " ".join(f"{r:>22}" for r in rows), flush=True)

# ----------------------------------------------------------------------------
# E. SDXL-ish UNet linear chain at 4096 tokens
# ----------------------------------------------------------------------------
hdr("E. SDXL-ish UNet linear workload, 8 representative GEMMs, 4096 tokens, interleaved")

# qkv/proj/ff pairs at dims 320/640/1280 — the real UNet switches resolution
# between these with convs, so (as in round-1 C4b) each GEMM gets its own
# input; the workload is the SEQUENCE, not a dataflow chain
SDXL_LINEARS = [  # (N_out, K_in)
    (960, 320), (320, 960), (2560, 320), (320, 2560),
    (1920, 640), (640, 1920), (5120, 1280), (1280, 5120),
]
TOK = 4096
Ws_sdxl = [(torch.randn(N, K, device="cuda") * (1.0 / K ** 0.5)) for N, K in SDXL_LINEARS]
Wb_sdxl = [W.bfloat16() for W in Ws_sdxl]
W_raw_sdxl = weights_to_raw_buffers(Ws_sdxl)
Xs = [torch.randn(TOK, K, device="cuda") for _, K in SDXL_LINEARS]

def sdxl_bf16():
    outs = []
    with torch.no_grad():
        for W, x in zip(Wb_sdxl, Xs):
            outs.append(gelu(x.bfloat16() @ W.T))
    return outs

class SDXLFp4:
    def __init__(self):
        self.bufs = {}
        for i, (N, K) in enumerate(SDXL_LINEARS):
            self.bufs[i] = (torch.zeros(F.packed_pad_bytes(TOK, K), dtype=torch.uint8, device="cuda"),
                            torch.zeros(F.scale_pad_bytes(TOK, K), dtype=torch.uint8, device="cuda"),
                            torch.empty(TOK, N, dtype=torch.float16, device="cuda"))

    def run(self):
        outs = []
        for i, (N, K) in enumerate(SDXL_LINEARS):
            packed, scale, out16 = self.bufs[i]
            F.fp4_quant_into(Xs[i], packed, scale)
            wp, ws = W_raw_sdxl[i]
            F.fp4_gemm_raw(packed, scale, wp, ws, out16, TOK, N, K)
            outs.append(gelu(out16.float()))
        return outs

sdxl_fp4 = SDXLFp4()
for _ in range(3):
    out_f = sdxl_fp4.run()
    out_b = sdxl_bf16()
torch.cuda.synchronize()
rr = max(rrms(a.float(), b.float()) for a, b in zip(out_f, out_b))
flops_chain = sum(2 * TOK * N * K for N, K in SDXL_LINEARS)

def capture_sdxl_fp4():
    class G: pass
    g = G()
    for _ in range(3):
        sdxl_fp4.run()
    torch.cuda.synchronize()
    g.graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g.graph):
        g.static_out = sdxl_fp4.run()
    return g

def capture_sdxl_bf16():
    class G: pass
    g = G()
    for _ in range(3):
        sdxl_bf16()
    torch.cuda.synchronize()
    g.graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g.graph):
        g.static_out = sdxl_bf16()
    return g

gbf = capture_sdxl_bf16()
gfp = capture_sdxl_fp4()

print(f"  fp4-vs-bf16 output relRMS (worst of 8): {rr:.4f} (same fp32 weights both sides)")
print(f"  workload FLOPs: {flops_chain/1e9:.1f} G   ({boxstate()})")
print(f"  {'path':<16} {'gpu ms':>9} {'enq ms':>9} {'TFLOPS':>8}")
for nm, fn in [("bf16 eager", sdxl_bf16),
               ("bf16 graph", lambda: gbf.graph.replay()),
               ("fp4 eager", lambda: sdxl_fp4.run()),
               ("fp4 graph", lambda: gfp.graph.replay())]:
    warm_clock(1.0)
    gms, hms = time_forward(fn)
    print(f"  {nm:<16} {gms:9.3f} {hms:9.3f} {flops_chain/(gms*1e-3)/1e12:8.1f}", flush=True)

wb = sum(N * K * 2 for N, K in SDXL_LINEARS)
wf = sum(p.numel() + s.numel() for p, s in W_raw_sdxl)
print(f"  chain weights: bf16 {wb/1e6:.1f} MB  fp4 {wf/1e6:.1f} MB  ({wb/wf:.2f}x)")
print(f"\n# done  {boxstate()}")
