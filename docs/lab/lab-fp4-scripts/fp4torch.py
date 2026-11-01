# fp4torch.py — NVFP4 for torch on the Thor, two halves:
#
#  1. a ctypes binding to build/libfp4ops.so: device-side NVFP4 quantization
#     (e2m1 codes + one UE4M3 scale per 16 elements in the tensor-core 128x4
#     block layout) and the cuBLASLt NVFP4 GEMM measured at 371-437 TFLOPS in
#     results/sweep-main.txt. This is the REAL tensor-core path, not a fake.
#  2. a pure-torch fake-quantizer for QAT (round-to-nearest e2m1 with STE) that
#     mirrors the .so's arithmetic, so |fake - real| isolates only GPU-vs-GPU
#     rounding, and QAT trains against the error the real path will commit.
#
# K of every FP4 linear must be a multiple of 64 (cuBLASLt constraint measured
# in results/lt-limits.txt: K=48 is rejected; multiples of 32 work, 64 is safe).

import ctypes
import os

import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = ctypes.CDLL(os.path.join(_HERE, "..", "build", "libfp4ops.so"))

c = ctypes.c_void_p
i64 = ctypes.c_int64
_LIB.fp4_init.argtypes = [ctypes.c_size_t]
_LIB.fp4_init.restype = ctypes.c_int
_LIB.fp4_from_f32.argtypes = [c, i64, i64, ctypes.POINTER(c), c]
_LIB.fp4_from_f32.restype = ctypes.c_int
_LIB.fp4_quant_prealloc.argtypes = [c, i64, i64, c, c, c]
_LIB.fp4_quant_prealloc.restype = ctypes.c_int
_LIB.fp4_gemm_raw.argtypes = [c, c, c, c, c, i64, i64, i64, c]
_LIB.fp4_gemm_raw.restype = ctypes.c_int
_LIB.fp4_gemm.argtypes = [c, c, c, i64, i64, i64, c]
_LIB.fp4_gemm.restype = ctypes.c_int
_LIB.fp4_handle_bytes.argtypes = [c]
_LIB.fp4_handle_bytes.restype = ctypes.c_size_t
_LIB.fp4_free.argtypes = [c]
_LIB.fp4_free.restype = ctypes.c_int
_LIB.fp4_cublaslt_version.restype = ctypes.c_size_t

_initialized = False


def fp4_init(ws_bytes: int = 256 << 20) -> None:
    global _initialized
    if not _initialized:
        rc = _LIB.fp4_init(ws_bytes)
        assert rc == 0, f"fp4_init rc={rc}"
        _initialized = True


def scale_pad_bytes(R: int, K: int) -> int:
    """scale buffer rows padded to 128-row tensor-core tiles"""
    return ((R + 127) // 128 * 128) * (K // 16)


def packed_pad_bytes(R: int, K: int) -> int:
    """packed-code buffer rows padded to 128-row tiles (tail-tile reads)"""
    return ((R + 127) // 128 * 128) * K // 2


def fp4_quant_into(x: torch.Tensor, packed: torch.Tensor, scale_blk: torch.Tensor) -> None:
    """quantize x (R,K) fp32 into caller-owned uint8 buffers (capture-safe)."""
    fp4_init()
    R, K = x.shape
    assert packed.numel() >= packed_pad_bytes(R, K) and scale_blk.numel() >= scale_pad_bytes(R, K), \
        "buffers must be padded to 128-row tiles (see packed_pad_bytes)"
    rc = _LIB.fp4_quant_prealloc(x.data_ptr(), R, K, packed.data_ptr(),
                                 scale_blk.data_ptr(), torch.cuda.current_stream().cuda_stream)
    assert rc == 0, f"fp4_quant_prealloc rc={rc}"


def fp4_gemm_raw(packedA, scaleA, packedB, scaleB, out16, M, N, K) -> None:
    """out16 (M,N) fp16 row-major = A @ B^T, all operands raw device pointers."""
    rc = _LIB.fp4_gemm_raw(packedA.data_ptr() if torch.is_tensor(packedA) else packedA,
                           scaleA.data_ptr() if torch.is_tensor(scaleA) else scaleA,
                           packedB.data_ptr() if torch.is_tensor(packedB) else packedB,
                           scaleB.data_ptr() if torch.is_tensor(scaleB) else scaleB,
                           out16.data_ptr(), M, N, K,
                           torch.cuda.current_stream().cuda_stream)
    assert rc == 0, f"fp4_gemm_raw rc={rc}"


class Fp4Tensor:
    """A device tensor quantized to NVFP4 (real codes + blocked scales).

    cuBLASLt needs M to be a multiple of 8 (M=4/12: no algorithm; M=1 computes
    garbage), so rows are zero-padded to the next multiple of 8 at build time
    and matmul_t slices the output back to the logical rows."""

    def __init__(self, x: torch.Tensor):
        assert x.ndim == 2 and x.is_cuda and x.dtype == torch.float32 and x.is_contiguous()
        assert x.shape[1] % 64 == 0, f"K={x.shape[1]} not a multiple of 64"
        fp4_init()
        R, K = x.shape
        self.shape = (R, K)
        self._rows = max(8, (R + 7) // 8 * 8)
        if self._rows != R:
            xp = torch.zeros(self._rows, K, dtype=torch.float32, device=x.device)
            xp[:R] = x
            x = xp
        h = c()
        rc = _LIB.fp4_from_f32(x.data_ptr(), self._rows, K,
                               ctypes.byref(h), torch.cuda.current_stream().cuda_stream)
        assert rc == 0, f"fp4_from_f32 rc={rc}"
        self._h = h

    def matmul_t(self, w: "Fp4Tensor", out: torch.Tensor) -> torch.Tensor:
        """out(M,N) fp16 row-major = self(M,K) @ w(N,K)^T  (both NVFP4)."""
        M, K = self.shape
        N, K2 = w.shape
        assert K == K2
        Mp = self._rows
        buf = torch.empty(Mp, N, dtype=torch.float16, device="cuda")
        rc = _LIB.fp4_gemm(self._h.value, w._h.value, buf.data_ptr(), Mp, N, K,
                           torch.cuda.current_stream().cuda_stream)
        assert rc == 0, f"fp4_gemm rc={rc}"
        return buf[:M] if out is None else out.copy_(buf[:M])

    def nbytes(self) -> int:
        return int(_LIB.fp4_handle_bytes(self._h.value))

    def free(self) -> None:
        if getattr(self, "_h", None) is not None:
            _LIB.fp4_free(self._h.value)
            self._h = None

    def __del__(self):
        try:
            self.free()
        except Exception:
            pass


class Fp4Linear:
    """inference-only nn.Linear equivalent: weights resident in NVFP4.

    forward(x: fp32 (M, in_features)) -> fp16 (M, out_features); the activation
    is quantized to NVFP4 on the fly on the same stream, so a whole chain of
    these can be captured in a torch CUDA graph (no malloc/sync inside)."""

    def __init__(self, weight: torch.Tensor):
        assert weight.ndim == 2  # (out_features, in_features)
        self.w = Fp4Tensor(weight.detach().contiguous().float())
        self.in_features = weight.shape[1]
        self.out_features = weight.shape[0]

    def __call__(self, x: torch.Tensor, out: torch.Tensor = None) -> torch.Tensor:
        a = Fp4Tensor(x.detach().contiguous().float())
        return a.matmul_t(self.w, out)

    def weight_nbytes(self) -> int:
        return self.w.nbytes()


# ----------------------------------------------------------------------------
# fake quantization for QAT (torch only; mirrors fp4ops' device arithmetic)
# ----------------------------------------------------------------------------
_E2M1 = torch.tensor([0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0])
_E2M1_MID = torch.tensor([0.25, 0.75, 1.25, 1.75, 2.5, 3.5, 5.0])


def _e4m3_round(s: torch.Tensor) -> torch.Tensor:
    """round positive scales to e4m3 (round-to-nearest, saturating to 448)."""
    s = s.clamp_min(2**-9)  # e4m3 min subnormal; below this the block is ~zero anyway
    return s.to(torch.float8_e4m3fn).to(torch.float32)


def nvfp4_fake_quant(x: torch.Tensor, blk: int = 16, amax_cap: float = 6.0) -> torch.Tensor:
    """round-to-nearest NVFP4 fake quant: per-blk e4m3 scale (amax/6), e2m1 codes."""
    shp = x.shape
    xv = x.reshape(-1, blk)
    amax = xv.abs().amax(dim=1, keepdim=True)
    ds = _e4m3_round(amax / amax_cap).clamp_min(2**-9)
    q = xv / ds
    sign = q.sign()
    a = q.abs().clamp_max(amax_cap)
    idx = torch.bucketize(a, _E2M1_MID.to(x.device), right=True)
    codes = _E2M1.to(x.device, x.dtype)[idx]
    return (codes * sign * ds).reshape(shp)


class FakeQuantSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        return nvfp4_fake_quant(x)

    @staticmethod
    def backward(ctx, g):
        return g


def fq(x: torch.Tensor) -> torch.Tensor:
    return FakeQuantSTE.apply(x)


class QATLinear(torch.nn.Module):
    """linear whose weight AND input activations are NVFP4-fake-quantized (STE)."""

    def __init__(self, in_f: int, out_f: int):
        super().__init__()
        assert in_f % 64 == 0
        self.linear = torch.nn.Linear(in_f, out_f, bias=False, dtype=torch.float32)

    def forward(self, x):
        return torch.nn.functional.linear(fq(x), fq(self.linear.weight))


def loadavg() -> float:
    with open("/proc/loadavg") as f:
        return float(f.read().split()[0])
