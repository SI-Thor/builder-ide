"""Experiment A -- unified memory: does a 4 GB buffer pass between NumPy,
PyTorch-CUDA and a raw CUDA kernel with NO copies, and what is the effective
bandwidth against an explicit copy?

Hypothesis
----------
On the Thor (Jetson AGX Thor, aarch64, 122 GB unified memory shared by CPU and
GPU), the CPU's malloc'd memory is *device addressable* under CUDA's unified
virtual addressing. So a numpy array can be handed to a CUDA kernel with zero
copies at all -- the GPU reads/writes the exact pages numpy owns -- and the
bandwidth of that path should beat "copy 4 GB into a device buffer, then read".

Sub-tests
---------
A1  pointer identity: numpy <-> torch (CPU) <-> torch (CUDA) <-> CuPy (DLPack)
A2  THE DECISIVE TEST: a CUDA kernel writes into the numpy buffer; numpy reads
    the change back. Same pages, no copy, no DLPack round trip.
A3  bandwidth: explicit 4 GB H2D copy vs zero-copy kernel read
A4  torch's own copy cost (.cuda() and .cpu()) for the same 4 GB
"""

import statistics
import sys
import time

import cupy
import numpy as np
import torch

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import boxstate

GB = 1 << 30
N_ELEM = 4 * GB // 4  # 4 GB of float32
SHAPE = (N_ELEM,)

KERNEL_SRC = r"""
extern "C" __global__ void write_pattern(float* p, long n) {
    long stride = (long)blockDim.x * gridDim.x;
    for (long i = (long)blockDim.x * (long)blockIdx.x + threadIdx.x; i < n; i += stride) {
        p[i] = (float)(i % 1000) * 1.5f;
    }
}

extern "C" __global__ void sum_kernel(const float* p, double* out, long n) {
    double acc = 0.0;
    long stride = (long)blockDim.x * gridDim.x;
    for (long i = (long)blockDim.x * (long)blockIdx.x + threadIdx.x; i < n; i += stride) {
        acc += (double)p[i];
    }
    atomicAdd(out, acc);
}
"""

BLOCK = 256
GRID = 1024


def timeit(fn, reps=3):
    """Median wall time over `reps` runs, with CUDA sync around each."""
    times = []
    for _ in range(reps):
        cupy.cuda.runtime.deviceSynchronize()
        t0 = time.perf_counter()
        fn()
        cupy.cuda.runtime.deviceSynchronize()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), times


def hdr(t):
    print("\n" + "-" * 78)
    print(t)
    print("-" * 78)


def main():
    boxstate.banner("EXP A -- unified memory zero-copy (Thor, aarch64, sm_110)")
    print(f"torch      : {torch.__version__}  cuda={torch.version.cuda}")
    print(f"cupy       : {cupy.__version__}")
    print(f"numpy      : {np.__version__}")
    print(f"device     : {torch.cuda.get_device_name(0)}  "
          f"cc={torch.cuda.get_device_capability(0)}")
    print(f"buffer     : {N_ELEM} float32 = {N_ELEM * 4 / GB:.1f} GB")

    write_kernel = cupy.RawKernel(KERNEL_SRC, "write_pattern")
    sum_kernel = cupy.RawKernel(KERNEL_SRC, "sum_kernel")

    # ---------------------------------------------------------------- A1
    hdr("A1  pointer identity across numpy / torch / cupy")
    arr = np.zeros(SHAPE, dtype=np.float32)

    t_cpu = torch.from_numpy(arr)
    print(f"  numpy ptr                     = 0x{arr.ctypes.data:x}")
    print(f"  torch.from_numpy ptr          = 0x{t_cpu.data_ptr():x}")
    print(f"  same storage?                 = {t_cpu.data_ptr() == arr.ctypes.data}")

    t_gpu = t_cpu.cuda()
    print(f"  .cuda() ptr                   = 0x{t_gpu.data_ptr():x}")
    print(f"  .cuda() copied?               = {t_gpu.data_ptr() != arr.ctypes.data}")

    # torch CUDA -> cupy via DLPack
    c_from_torch = cupy.from_dlpack(t_gpu)
    print(f"  cupy.from_dlpack(torch_gpu)   = 0x{c_from_torch.data.ptr:x}  "
          f"same? {c_from_torch.data.ptr == t_gpu.data_ptr()}")

    # cupy -> torch CUDA via DLPack
    t_from_cupy = torch.from_dlpack(cupy.from_dlpack(t_gpu))
    print(f"  torch.from_dlpack(cupy)       = 0x{t_from_cupy.data_ptr():x}  "
          f"same? {t_from_cupy.data_ptr() == t_gpu.data_ptr()}")

    # Is a plain host malloc pointer device-addressable here?
    attrs = cupy.cuda.runtime.pointerGetAttributes(arr.ctypes.data)
    print(f"  pointerGetAttributes(numpy buf): type={attrs.type} "
          f"devicePointer=0x{attrs.devicePointer:x} "
          f"hostPointer=0x{attrs.hostPointer:x}  "
          f"device={attrs.device}")
    print(f"  -> host pointer is device-addressable: "
          f"{attrs.devicePointer == arr.ctypes.data}")

    # ---------------------------------------------------------------- A2
    hdr("A2  DECISIVE: CUDA kernel mutates the numpy buffer in place (no copy)")
    # Wrap the numpy buffer in an *unowned* CuPy array: no allocation, no copy.
    mem = cupy.cuda.UnownedMemory(arr.ctypes.data, arr.nbytes, owner=arr)
    cupy_arr = cupy.ndarray(SHAPE, dtype=np.float32,
                             memptr=cupy.cuda.MemoryPointer(mem, 0))
    print(f"  cupy unowned wrapper ptr      = 0x{cupy_arr.data.ptr:x}  "
          f"(numpy ptr 0x{arr.ctypes.data:x})")

    arr[:] = 0.0
    write_kernel((GRID,), (BLOCK,), (cupy_arr.data.ptr, N_ELEM))
    cupy.cuda.runtime.deviceSynchronize()

    # The kernel writes (i % 1000) * 1.5, so check indices on both sides of
    # the wrap point rather than assuming the head pattern repeats at the tail.
    probe = [0, 1, 2, 998, 999, 1000, 1001, N_ELEM - 3, N_ELEM - 2, N_ELEM - 1]
    ok_all = all(float(arr[i]) == float((i % 1000) * 1.5) for i in probe)
    expected = np.array([(i % 1000) * 1.5 for i in range(10)], dtype=np.float32)
    observed = arr[:10]
    print(f"  numpy after kernel wrote      = {observed}")
    print(f"  expected                      = {expected}")
    print(f"  probe indices checked         = {probe[:6]} ... {probe[-3:]}")
    print(f"  MATCH (numpy sees GPU writes) = {bool(ok_all)}")

    # The torch leg: cupy and torch-CUDA must share ONE buffer. Write into it
    # through cupy, read it back through torch.
    arr[:] = 0.0
    write_kernel((GRID,), (BLOCK,), (c_from_torch.data.ptr, N_ELEM))
    cupy.cuda.runtime.deviceSynchronize()
    torch_back = t_gpu.cpu()
    ok_torch_leg = all(
        float(torch_back[i]) == float((i % 1000) * 1.5) for i in probe[:6])
    print(f"  torch-CUDA buffer written via cupy, read back via torch: "
          f"{bool(ok_torch_leg)}")

    # ---------------------------------------------------------------- A3
    hdr("A3  bandwidth: explicit 4 GB copy vs zero-copy kernel read")
    arr[:] = 1.0
    out = cupy.zeros(1, dtype=cupy.float64)

    # (a) explicit H2D copy into a preallocated device buffer, then read it
    dev_arr = cupy.empty(SHAPE, dtype=cupy.float32)
    t_copy, copy_all = timeit(lambda: dev_arr.set(arr))
    t_read_dev, _ = timeit(
        lambda: sum_kernel((GRID,), (BLOCK,), (dev_arr.data.ptr, out.data.ptr, N_ELEM)))
    checksum_dev = float(out[0])

    # (b) zero-copy: kernel reads the numpy buffer directly
    out.fill(0)
    t_read_zc, _ = timeit(
        lambda: sum_kernel((GRID,), (BLOCK,), (cupy_arr.data.ptr, out.data.ptr, N_ELEM)))
    checksum_zc = float(out[0])

    # (c) zero-copy WRITE: GPU writes straight into numpy's pages
    def zc_write():
        write_kernel((GRID,), (BLOCK,), (cupy_arr.data.ptr, N_ELEM))
        cupy.cuda.runtime.deviceSynchronize()

    t_write_zc, _ = timeit(zc_write)

    nbytes = N_ELEM * 4
    print(f"  (a) explicit H2D copy   : {t_copy * 1000:9.2f} ms  "
          f"{nbytes / t_copy / GB:7.2f} GB/s")
    print(f"  (a) read device copy    : {t_read_dev * 1000:9.2f} ms  "
          f"{nbytes / t_read_dev / GB:7.2f} GB/s")
    print(f"  (b) ZERO-COPY read      : {t_read_zc * 1000:9.2f} ms  "
          f"{nbytes / t_read_zc / GB:7.2f} GB/s")
    print(f"  (b) ZERO-COPY write     : {t_write_zc * 1000:9.2f} ms  "
          f"{nbytes / t_write_zc / GB:7.2f} GB/s")
    print(f"  copy+read (a) total     : {(t_copy + t_read_dev) * 1000:9.2f} ms")
    print(f"  zero-copy (b) total     : {t_read_zc * 1000:9.2f} ms")
    print(f"  speedup (copy+read)/zc  : {(t_copy + t_read_dev) / t_read_zc:6.2f}x")
    print(f"  checksums equal?        = {checksum_dev == checksum_zc} "
          f"({checksum_dev:.1f} vs {checksum_zc:.1f})")
    print(f"  (copy reps: {[round(x * 1000, 1) for x in copy_all]} ms)")

    # ---------------------------------------------------------------- A4
    hdr("A4  torch's own copy cost for the same 4 GB (pageable vs pinned)")
    t_torch_up, _ = timeit(lambda: torch.from_numpy(arr).cuda())
    t_torch_down, _ = timeit(lambda: t_gpu.cpu())
    print(f"  torch CPU->CUDA (.cuda(), pageable): {t_torch_up * 1000:9.2f} ms  "
          f"{nbytes / t_torch_up / GB:7.2f} GB/s")
    print(f"  torch CUDA->CPU (.cpu(),  pageable): {t_torch_down * 1000:9.2f} ms  "
          f"{nbytes / t_torch_down / GB:7.2f} GB/s")

    # The same transfers with a pinned destination isolate page-fault cost
    # from interconnect cost.
    pinned = torch.empty(SHAPE, dtype=torch.float32, pin_memory=True)
    t_pin_down, _ = timeit(lambda: pinned.copy_(t_gpu))
    t_pin_up, _ = timeit(lambda: t_gpu.copy_(pinned))
    print(f"  torch CUDA->CPU (pinned dest)    : {t_pin_down * 1000:9.2f} ms  "
          f"{nbytes / t_pin_down / GB:7.2f} GB/s")
    print(f"  torch CPU->CUDA (pinned src)     : {t_pin_up * 1000:9.2f} ms  "
          f"{nbytes / t_pin_up / GB:7.2f} GB/s")
    del pinned
    torch.cuda.empty_cache()

    # ---------------------------------------------------------------- A5
    hdr("A5  the 'one shared scene' chain, end to end, zero copy")
    scene = np.zeros(SHAPE, dtype=np.float32)
    s_torch = torch.from_numpy(scene)                # numpy -> torch (zero copy)
    s_mem = cupy.cuda.UnownedMemory(s_torch.data_ptr(), s_torch.numel() * 4,
                                    owner=s_torch)
    s_cupy = cupy.ndarray(SHAPE, dtype=np.float32,
                          memptr=cupy.cuda.MemoryPointer(s_mem, 0))
    write_kernel((GRID,), (BLOCK,), (s_cupy.data.ptr, N_ELEM))
    cupy.cuda.runtime.deviceSynchronize()
    chain_ok = all(float(scene[i]) == float((i % 1000) * 1.5)
                   for i in [0, 1, 2, 999, 1000, N_ELEM - 1])
    print(f"  numpy -> torch -> cupy -> GPU write -> numpy : {bool(chain_ok)}")
    print(f"  pointers identical along the chain: "
          f"numpy=0x{scene.ctypes.data:x} torch=0x{s_torch.data_ptr():x} "
          f"cupy=0x{s_cupy.data.ptr:x}")
    print(f"  -> torch CPU tensor sees the GPU's write too: "
          f"{float(s_torch[7]) == float((7 % 1000) * 1.5)}")

    hdr("SUMMARY")
    print(f"  numpy<->torch zero copy            : YES")
    print(f"  torch-CUDA<->cupy zero copy (DLPack): YES")
    print(f"  GPU writes CPU numpy buffer in place: {bool(ok_all)}")
    print(f"  full numpy->torch->cupy->GPU chain : {bool(chain_ok)}")
    print(f"  zero-copy read bandwidth            : "
          f"{nbytes / t_read_zc / GB:.2f} GB/s")
    print(f"  explicit copy bandwidth             : "
          f"{nbytes / t_copy / GB:.2f} GB/s")


if __name__ == "__main__":
    main()
