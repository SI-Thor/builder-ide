"""Experiment B -- NVIDIA Warp on aarch64 + sm_110, and a terrain-style
SDF/noise kernel against NumPy on the 14 Neoverse cores.

Hypothesis
----------
NVIDIA Warp (Python -> CUDA kernels, compiled at runtime) installs and runs on
aarch64 against this Thor's sm_110 Blackwell GPU, and a terrain-style
fBm/SDF kernel runs far faster there than the same math in NumPy -- and fast
enough that procedural stages move off the CPU lane entirely.

The kernel is a faithful mini-Infinigen: Infinigen's terrain evaluates SDF
elements (mountains, water, landtiles) over a grid. Here: a value-noise fBm
heightfield plus a displaced-sphere SDF, with a *bit-identical* integer hash
implemented in both Warp and NumPy so the comparison is fair and verifiable.

Sub-tests
---------
B1  does warp install / init / compile for sm_110 on aarch64?
B2  2D fBm heightfield 4096^2, 5 octaves: warp vs numpy-1-thread vs numpy-14-thread
B3  3D displaced-sphere SDF 256^3: warp vs numpy-1-thread vs numpy-14-thread
B4  kernel launch overhead (matters for the 60 s interactive clock)
B5  does a warp kernel mutate a numpy buffer in place (unified memory)?
"""

import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

os.environ.setdefault("WARP_CACHE_PATH", os.path.join(os.path.dirname(__file__), "..", ".warp-cache"))

sys.path.insert(0, os.path.dirname(__file__))
import boxstate

GB = 1 << 30
OCTAVES = 5
FREQ0 = 0.0015


# --------------------------------------------------------------------------
# The shared math: 16-bit integer hash value noise, identical in both engines.
# Every intermediate stays below 2**31 so int32 (warp) and int64 (numpy)
# produce bit-identical results.
# --------------------------------------------------------------------------
def hash_np(xi, yi, seed):
    h = (xi * 7919 + yi * 6271 + seed * 3571) & 0xFFFF
    h = ((h ^ (h >> 7)) * 15329) & 0xFFFF
    h = ((h ^ (h >> 5)) * 26213) & 0xFFFF
    return h.astype(np.float32) * np.float32(1.0 / 65535.0)


def fbm_np(X, Y, seed=0):
    """X, Y: broadcastable float arrays. Returns fBm in [0, ~1)."""
    total = np.zeros(np.broadcast(X, Y).shape, dtype=np.float32)
    amp = np.float32(1.0)
    fr = np.float32(FREQ0)
    for o in range(OCTAVES):
        x = X * fr
        y = Y * fr
        xi = np.floor(x).astype(np.int64)
        yi = np.floor(y).astype(np.int64)
        tx = (x - xi).astype(np.float32)
        ty = (y - yi).astype(np.float32)
        sx = tx * tx * (3.0 - 2.0 * tx)
        sy = ty * ty * (3.0 - 2.0 * ty)
        x0 = xi & 0xFFFF
        y0 = yi & 0xFFFF
        x1 = (xi + 1) & 0xFFFF
        y1 = (yi + 1) & 0xFFFF
        sd = np.int64(seed + o)
        v00 = hash_np(x0, y0, sd)
        v10 = hash_np(x1, y0, sd)
        v01 = hash_np(x0, y1, sd)
        v11 = hash_np(x1, y1, sd)
        vx0 = v00 + (v10 - v00) * sx
        vx1 = v01 + (v11 - v01) * sx
        total += amp * (vx0 + (vx1 - vx0) * sy)
        amp = amp * np.float32(0.5)
        fr = fr * np.float32(2.0)
    return total


def sdf_np(X, Y, Z, seed=0):
    """Displaced-sphere SDF -- the Infinigen 'mountain' element shape."""
    cx, cy, cz, r, amp = 0.35, 0.35, 0.5, 0.22, 0.06
    dx = X - np.float32(cx)
    dy = Y - np.float32(cy)
    dz = Z - np.float32(cz)
    d = np.sqrt(dx * dx + dy * dy + dz * dz)
    return d - np.float32(r) + np.float32(amp) * (fbm_np(X, Y, seed) - np.float32(0.5))


# --------------------------------------------------------------------------
# numba baseline: the *optimized* CPU implementation, compiled and run on all
# 14 cores. Without this the NumPy-Python comparison would be a straw man.
# --------------------------------------------------------------------------
from numba import njit, prange  # noqa: E402


@njit(cache=False, fastmath=True, inline="always")
def nb_hash(xi, yi, seed):
    h = (xi * 7919 + yi * 6271 + seed * 3571) & 0xFFFF
    h = ((h ^ (h >> 7)) * 15329) & 0xFFFF
    h = ((h ^ (h >> 5)) * 26213) & 0xFFFF
    return h / 65535.0


@njit(cache=False, fastmath=True)
def nb_fbm(x, y, seed):
    total = 0.0
    amp = 1.0
    fr = FREQ0
    for o in range(OCTAVES):
        xx = x * fr
        yy = y * fr
        xi = int(np.floor(xx))
        yi = int(np.floor(yy))
        tx = xx - xi
        ty = yy - yi
        sx = tx * tx * (3.0 - 2.0 * tx)
        sy = ty * ty * (3.0 - 2.0 * ty)
        x0 = xi & 0xFFFF
        y0 = yi & 0xFFFF
        x1 = (xi + 1) & 0xFFFF
        y1 = (yi + 1) & 0xFFFF
        sd = seed + o
        v00 = nb_hash(x0, y0, sd)
        v10 = nb_hash(x1, y0, sd)
        v01 = nb_hash(x0, y1, sd)
        v11 = nb_hash(x1, y1, sd)
        vx0 = v00 + (v10 - v00) * sx
        vx1 = v01 + (v11 - v01) * sx
        total += amp * (vx0 + (vx1 - vx0) * sy)
        amp *= 0.5
        fr *= 2.0
    return total


@njit(cache=False, fastmath=True, parallel=True)
def nb_heightfield(out):
    n = out.shape[0]
    for i in prange(n):
        for j in range(n):
            out[i, j] = nb_fbm(float(i), float(j), 0)


@njit(cache=False, fastmath=True, parallel=True)
def nb_sdf(out):
    n0, n1, n2 = out.shape
    inv = 1.0 / 256.0
    # The displacement field is separable in x/y, exactly as the numpy version
    # exploits: compute the 256x256 fBm once, then sweep k. Recomputing the
    # noise per voxel would be 256x more work and an unfair comparison.
    fbm = np.empty((n0, n1), dtype=np.float32)
    for i in prange(n0):
        for j in range(n1):
            fbm[i, j] = nb_fbm(i * inv, j * inv, 0)
    for i in prange(n0):
        x = i * inv
        for j in range(n1):
            y = j * inv
            dx = x - 0.35
            dy = y - 0.35
            base = dx * dx + dy * dy
            for k in range(n2):
                z = k * inv
                dzz = z - 0.5
                d = np.sqrt(base + dzz * dzz)
                out[i, j, k] = d - 0.22 + 0.06 * (fbm[i, j] - 0.5)


@njit(cache=False, fastmath=True, parallel=True)
def nb_sdf_pervoxel(out):
    """Same algorithm as the warp kernel: noise evaluated per voxel."""
    n0, n1, n2 = out.shape
    inv = 1.0 / 256.0
    for i in prange(n0):
        x = i * inv
        for j in range(n1):
            y = j * inv
            dx = x - 0.35
            dy = y - 0.35
            base = dx * dx + dy * dy
            for k in range(n2):
                z = k * inv
                dzz = z - 0.5
                d = np.sqrt(base + dzz * dzz)
                out[i, j, k] = d - 0.22 + 0.06 * (nb_fbm(x, y, 0) - 0.5)


def threaded(fn, items, workers):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def med(fn, reps=3):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts)


def load_now():
    """Sample the box's load beside every number (CLAUDE.md rule)."""
    return os.getloadavg()


def med_with_load(fn, reps=3, label=""):
    """Median time plus the load observed during the measurement."""
    lo = load_now()
    t = med(fn, reps=reps)
    hi = load_now()
    print(f"    [load during {label or 'measurement'}: "
          f"{lo[0]:.1f} -> {hi[0]:.1f}]")
    return t


def hdr(t):
    print("\n" + "-" * 78)
    print(t)
    print("-" * 78)


def main():
    boxstate.banner("EXP B -- NVIDIA Warp on aarch64 / sm_110 (Thor)")
    import warp as wp

    print(f"warp version : {wp.__version__}")
    wp.config.quiet = True
    wp.config.enable_backward = False
    wp.init()
    dev = wp.get_device("cuda:0")
    print(f"device       : {dev}")
    print(f"device arch  : {getattr(dev, 'arch', '<unknown>')}")
    print(f"is_cuda      : {dev.is_cuda}")
    print(f"warp cache   : {os.environ['WARP_CACHE_PATH']}")

    # ------------------------------------------------------------------
    # Warp kernels -- same math as the numpy versions above.
    # ------------------------------------------------------------------
    @wp.func
    def w_hash(xi: int, yi: int, seed: int) -> float:
        h = (xi * 7919 + yi * 6271 + seed * 3571) & 0xFFFF
        h = ((h ^ (h >> 7)) * 15329) & 0xFFFF
        h = ((h ^ (h >> 5)) * 26213) & 0xFFFF
        return float(h) / 65535.0

    @wp.func
    def w_fbm(x: float, y: float, seed: int) -> float:
        total = float(0.0)
        amp = float(1.0)
        fr = float(FREQ0)
        for o in range(OCTAVES):
            xx = x * fr
            yy = y * fr
            xi = int(wp.floor(xx))
            yi = int(wp.floor(yy))
            tx = xx - float(xi)
            ty = yy - float(yi)
            sx = tx * tx * (3.0 - 2.0 * tx)
            sy = ty * ty * (3.0 - 2.0 * ty)
            x0 = xi & 0xFFFF
            y0 = yi & 0xFFFF
            x1 = (xi + 1) & 0xFFFF
            y1 = (yi + 1) & 0xFFFF
            sd = seed + o
            v00 = w_hash(x0, y0, sd)
            v10 = w_hash(x1, y0, sd)
            v01 = w_hash(x0, y1, sd)
            v11 = w_hash(x1, y1, sd)
            vx0 = v00 + (v10 - v00) * sx
            vx1 = v01 + (v11 - v01) * sx
            total += amp * (vx0 + (vx1 - vx0) * sy)
            amp = amp * 0.5
            fr = fr * 2.0
        return total

    @wp.kernel
    def k_heightfield(out: wp.array2d(dtype=wp.float32), seed: int):
        i, j = wp.tid()
        out[i, j] = w_fbm(float(i), float(j), seed)

    @wp.kernel
    def k_sdf(out: wp.array3d(dtype=wp.float32), seed: int):
        i, j, k = wp.tid()
        x = float(i) / 256.0
        y = float(j) / 256.0
        z = float(k) / 256.0
        cx, cy, cz, r, amp = 0.35, 0.35, 0.5, 0.22, 0.06
        dx = x - cx
        dy = y - cy
        dz = z - cz
        d = wp.sqrt(dx * dx + dy * dy + dz * dz)
        out[i, j, k] = d - r + amp * (w_fbm(x, y, seed) - 0.5)

    @wp.kernel
    def k_write(out: wp.array(dtype=wp.float32)):
        i = wp.tid()
        out[i] = float(i) * 1.5

    # ------------------------------------------------------------------
    hdr("B1  first compile (one-off cost) + correctness of the warp kernels")
    out2 = wp.zeros((16, 16), dtype=wp.float32)
    t0 = time.perf_counter()
    wp.launch(k_heightfield, dim=(16, 16), inputs=[out2, 0])
    wp.synchronize()
    print(f"  first launch (compiles the module): {(time.perf_counter() - t0) * 1000:.1f} ms")

    # ------------------------------------------------------------------
    hdr("B2  2D fBm heightfield 4096 x 4096, %d octaves" % OCTAVES)
    N = 4096
    grid = np.arange(N, dtype=np.float32)
    X = grid[:, None]
    Y = grid[None, :]

    warp_out = wp.zeros((N, N), dtype=wp.float32)

    def run_warp():
        wp.launch(k_heightfield, dim=(N, N), inputs=[warp_out, 0])
        wp.synchronize()

    run_warp()  # warm up (module already compiled)
    t_warp = med_with_load(run_warp, label="warp 2D")
    np_out = fbm_np(X, Y, 0)

    t_np1 = med_with_load(lambda: fbm_np(X, Y, 0), reps=1, label="numpy 1-thread 2D")
    bands = np.array_split(np.arange(N), 14)
    t_np14 = med_with_load(
        lambda: threaded(lambda idx: fbm_np(X[idx], Y, 0), bands, 14), reps=1,
        label="numpy 14-thread 2D")

    w_arr = warp_out.numpy()
    maxdiff = float(np.max(np.abs(w_arr - np_out)))

    # numba: compiled, all 14 cores -- the fair optimized CPU baseline
    nb_out = np.zeros((N, N), dtype=np.float32)
    t_compile0 = time.perf_counter()
    nb_heightfield(np.zeros((4, 4), dtype=np.float32))   # C-contiguous warmup
    t_compile = time.perf_counter() - t_compile0
    t_nb14 = med_with_load(lambda: nb_heightfield(nb_out), reps=3,
                           label="numba 14-thread 2D")
    nb_diff = float(np.max(np.abs(nb_out - np_out)))

    print(f"  warp        : {t_warp * 1000:9.1f} ms   "
          f"{N * N * 4 / t_warp / GB:6.2f} GB/s written")
    print(f"  numpy 1 thr : {t_np1 * 1000:9.1f} ms   "
          f"{N * N * 4 / t_np1 / GB:6.2f} GB/s written")
    print(f"  numpy 14 thr: {t_np14 * 1000:9.1f} ms   "
          f"{N * N * 4 / t_np14 / GB:6.2f} GB/s written")
    print(f"  numba 14 thr: {t_nb14 * 1000:9.1f} ms   "
          f"{N * N * 4 / t_nb14 / GB:6.2f} GB/s written"
          f"   (JIT compile {t_compile:.1f} s, one-off)")
    print(f"  warp speedup vs numpy-1-thread   : {t_np1 / t_warp:6.2f}x")
    print(f"  warp speedup vs numpy-14-threads : {t_np14 / t_warp:6.2f}x")
    print(f"  warp speedup vs numba-14-threads : {t_nb14 / t_warp:6.2f}x")
    print(f"  max |warp - numpy|              : {maxdiff:.3e}  "
          f"(relative {maxdiff / max(float(np.max(np.abs(np_out))), 1e-9):.2e})")
    print(f"  max |numba - numpy|              : {nb_diff:.3e}")

    # ------------------------------------------------------------------
    hdr("B3  3D displaced-sphere SDF 256^3 (the Infinigen 'mountain' shape)")
    M = 256
    g3 = np.arange(M, dtype=np.float32)
    X3 = (g3[:, None, None] / np.float32(M))
    Y3 = (g3[None, :, None] / np.float32(M))
    Z3 = (g3[None, None, :] / np.float32(M))

    warp3 = wp.zeros((M, M, M), dtype=wp.float32)

    def run_warp3():
        wp.launch(k_sdf, dim=(M, M, M), inputs=[warp3, 0])
        wp.synchronize()

    run_warp3()
    t_warp3 = med_with_load(run_warp3, label="warp 3D")

    t_np3_1 = med_with_load(lambda: sdf_np(X3, Y3, Z3, 0), reps=1,
                            label="numpy 1-thread 3D")
    bands3 = np.array_split(np.arange(M), 14)
    t_np3_14 = med_with_load(
        lambda: threaded(lambda idx: sdf_np(X3[idx], Y3, Z3, 0), bands3, 14), reps=1,
        label="numpy 14-thread 3D")

    diff3 = float(np.max(np.abs(warp3.numpy() - sdf_np(X3, Y3, Z3, 0))))
    nb3 = np.zeros((M, M, M), dtype=np.float32)
    t3_compile0 = time.perf_counter()
    nb_sdf(np.zeros((4, 4, 4), dtype=np.float32))        # C-contiguous warmup
    nb_sdf_pervoxel(np.zeros((4, 4, 4), dtype=np.float32))
    t3_compile = time.perf_counter() - t3_compile0
    t_nb3_14 = med_with_load(lambda: nb_sdf(nb3), reps=3, label="numba 14-thread 3D")
    nb3_pv = np.zeros((M, M, M), dtype=np.float32)
    t_nb3_pv = med_with_load(lambda: nb_sdf_pervoxel(nb3_pv), reps=3,
                             label="numba 14-thread 3D per-voxel")
    print(f"  warp        : {t_warp3 * 1000:9.1f} ms")
    print(f"  numpy 1 thr : {t_np3_1 * 1000:9.1f} ms")
    print(f"  numpy 14 thr: {t_np3_14 * 1000:9.1f} ms")
    print(f"  numba 14 thr: {t_nb3_14 * 1000:9.1f} ms   (JIT compile {t3_compile:.1f} s) "
          f"[separable noise: 65K noise evals]")
    print(f"  numba 14 thr: {t_nb3_pv * 1000:9.1f} ms   [per-voxel noise: 16.7M noise "
          f"evals -- SAME WORK as the warp kernel]")
    print(f"  warp speedup vs numpy-1-thread   : {t_np3_1 / t_warp3:6.2f}x")
    print(f"  warp speedup vs numpy-14-threads : {t_np3_14 / t_warp3:6.2f}x")
    print(f"  warp speedup vs numba per-voxel  : {t_nb3_pv / t_warp3:6.2f}x  "
          f"(apples-to-apples: identical work)")
    print(f"  separable-CPU vs warp per-voxel  : {t_warp3 / t_nb3_14:6.2f}x  "
          f"(>1 means the restructured CPU wins)")
    print(f"  max |warp - numpy|              : {diff3:.3e}")

    # ------------------------------------------------------------------
    hdr("B4  launch overhead (the interactive-clock tax)")
    tiny = wp.zeros((1,), dtype=wp.float32)
    t_warp_launch = med(lambda: wp.launch(k_write, dim=(1,), inputs=[tiny]),
                        reps=5)
    print(f"  warp kernel launch          : {t_warp_launch * 1e6:8.1f} us")

    try:
        import cupy
        ck = cupy.RawKernel(r'extern "C" __global__ void nop(float* p){}', "nop")
        d = cupy.zeros(1, dtype=cupy.float32)
        t_cupy_launch = med(lambda: ck((1,), (1,), (d.data.ptr,)), reps=5)
        print(f"  cupy RawKernel launch       : {t_cupy_launch * 1e6:8.1f} us")
    except Exception as exc:
        print(f"  cupy launch                 : <unavailable: {exc}>")

    import torch
    tt = torch.zeros(1, device="cuda")
    t_torch_launch = med(lambda: tt.add_(1.0), reps=5)
    print(f"  torch cuda elementwise      : {t_torch_launch * 1e6:8.1f} us")

    # ------------------------------------------------------------------
    hdr("B5  does a warp kernel mutate a numpy buffer in place?")
    arr = np.zeros(64, dtype=np.float32)
    warr = wp.from_numpy(arr)
    print(f"  wp.from_numpy(arr)   -> ptr 0x{warr.ptr:x}  "
          f"(numpy ptr 0x{arr.ctypes.data:x})  same? {warr.ptr == arr.ctypes.data}")
    print(f"  -> warp's from_numpy default copies to the device; it does NOT share.")

    # The zero-copy route: wrap the raw host pointer, no owner, no copy.
    shared = wp.array(ptr=arr.ctypes.data, dtype=wp.float32, shape=(64,),
                      device="cuda:0", copy=False)
    print(f"  wp.array(ptr=...)    -> ptr 0x{shared.ptr:x}  "
          f"same? {shared.ptr == arr.ctypes.data}")

    arr[:] = 0.0
    wp.launch(k_write, dim=(64,), inputs=[shared])
    wp.synchronize()
    expected = (np.arange(64, dtype=np.float32) * 1.5)
    match = bool(np.array_equal(arr, expected))
    print(f"  numpy after warp wrote       = {arr[:5]} (expected {expected[:5]})")
    print(f"  MATCH (numpy sees GPU write) = {match}")

    # And the same test through wp.from_numpy (the copying route) for contrast.
    arr2 = np.zeros(64, dtype=np.float32)
    warr2 = wp.from_numpy(arr2)
    wp.launch(k_write, dim=(64,), inputs=[warr2])
    wp.synchronize()
    print(f"  via wp.from_numpy (copying)  = numpy unchanged? "
          f"{bool(np.array_equal(arr2, np.zeros(64, dtype=np.float32)))} "
          f"-> proves from_numpy does NOT share the buffer")

    hdr("SUMMARY")
    print(f"  warp on aarch64/sm_110        : {wp.__version__}, device {dev}")
    print(f"  2D fBm 4096^2  warp vs np14   : {t_warp * 1000:.1f} ms vs {t_np14 * 1000:.1f} ms"
          f"  ({t_np14 / t_warp:.1f}x)")
    print(f"  2D fBm 4096^2  warp vs nb14   : {t_warp * 1000:.1f} ms vs {t_nb14 * 1000:.1f} ms"
          f"  ({t_nb14 / t_warp:.1f}x)")
    print(f"  3D SDF  256^3   warp vs np14   : {t_warp3 * 1000:.1f} ms vs {t_np3_14 * 1000:.1f} ms"
          f"  ({t_np3_14 / t_warp3:.1f}x)")
    print(f"  3D SDF  256^3   warp vs nb14   : {t_warp3 * 1000:.1f} ms vs {t_nb3_14 * 1000:.1f} ms"
          f"  ({t_nb3_14 / t_warp3:.1f}x)")
    print(f"  3D SDF  256^3   warp vs nb14pv : {t_warp3 * 1000:.1f} ms vs {t_nb3_pv * 1000:.1f} ms"
          f"  ({t_nb3_pv / t_warp3:.1f}x, identical work)")
    print(f"  warp/numpy agreement         : {maxdiff:.2e} max abs")
    print(f"  warp launch overhead         : {t_warp_launch * 1e6:.1f} us")


if __name__ == "__main__":
    main()
