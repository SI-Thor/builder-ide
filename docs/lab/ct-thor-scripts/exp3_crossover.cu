/**
 * exp3_crossover.cu — ct-thor experiment 3
 *
 * The GPU-vs-AVX-512 crossover, re-run on the Thor.
 *
 * Workload (from avx512-constraint-checker / constraint-theory-llvm):
 * N values, each AND-checked against K=20 range constraints; a value passes
 * iff it lies in every window. This is the "20 constraints ANDed" shape
 * behind the repo's "35.9B checks/sec on AVX-512" claim.
 *
 * GPU path: one thread per value, the 20 (lo,hi) pairs in __device__
 * constants, per-value pass byte written out. The launch is captured once
 * into a CUDA Graph and re-launched — launch overhead without graphs is
 * exactly what made the GPU lose at small N in the corpus's own table.
 *
 * CPU path: the same loop ported to NEON (aarch64 has no AVX-512): 4×u32
 * lanes, 20 AND-reduced compare pairs, OpenMP across the Thor's 14
 * Neoverse cores. gcc auto-vectorises the same loop scalar too — both
 * variants are timed.
 *
 * Sizes: 20 / 1e3 / 1e6 / 1e8. The crossover is where graph-launched GPU
 * time crosses 14-thread NEON time.
 */

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <chrono>
#include <vector>
#include <omp.h>
#include <arm_neon.h>
#include <cuda_runtime.h>

#define K 20

static int cons_lo[K], cons_hi[K];

__device__ __constant__ int2 d_cons[K];   /* x = lo, y = hi */

__global__ void check20_kernel(const uint32_t* __restrict__ values,
                               uint8_t* __restrict__ pass,
                               int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    uint32_t v = values[i];
    uint32_t ok = 1;
    #pragma unroll
    for (int c = 0; c < K; c++) {
        ok &= (uint32_t)(v >= (uint32_t)d_cons[c].x && v <= (uint32_t)d_cons[c].y);
    }
    pass[i] = (uint8_t)ok;
}

/* CPU: NEON, 4 lanes per iteration, 20 AND-reduced constraint pairs */
static void cpu_neon(const uint32_t* values, uint8_t* pass, long n) {
    const long n4 = (n / 4) * 4;
    #pragma omp parallel for schedule(static)
    for (long b = 0; b < n4 / 4; b++) {
        const long i = b * 4;
        uint32x4_t ok = vdupq_n_u32(1);
        uint32x4_t v = vld1q_u32(&values[i]);
        for (int c = 0; c < K; c++) {
            uint32x4_t lo = vdupq_n_u32((uint32_t)cons_lo[c]);
            uint32x4_t hi = vdupq_n_u32((uint32_t)cons_hi[c]);
            uint32x4_t ge = vcgeq_u32(v, lo);
            uint32x4_t le = vcleq_u32(v, hi);
            ok = vandq_u32(ok, vandq_u32(ge, le));
        }
        uint32_t o[4];
        vst1q_u32(o, ok);
        pass[i]   = (uint8_t)o[0];
        pass[i+1] = (uint8_t)o[1];
        pass[i+2] = (uint8_t)o[2];
        pass[i+3] = (uint8_t)o[3];
    }
    for (long i = (n / 4) * 4; i < n; i++) {   /* tail */
        uint32_t v = values[i], ok = 1;
        for (int c = 0; c < K; c++) ok &= (v >= cons_lo[c] && v <= cons_hi[c]);
        pass[i] = (uint8_t)ok;
    }
}

/* CPU: plain scalar loop — gcc -O3 -march=native auto-vectorises this on
   aarch64; kept to test the corpus's "LLVM auto-vectorization is faster
   than explicit SIMD" finding on Neoverse V3 */
static void cpu_scalar(const uint32_t* values, uint8_t* pass, long n) {
    #pragma omp parallel for schedule(static)
    for (long i = 0; i < n; i++) {
        uint32_t v = values[i], ok = 1;
        for (int c = 0; c < K; c++) ok &= (v >= cons_lo[c] && v <= cons_hi[c]);
        pass[i] = (uint8_t)ok;
    }
}

int main() {
    printf("=== exp3: 20-constraint AND chain — CUDA Graph GPU vs 14-core NEON CPU ===\n");
    int dev; cudaGetDevice(&dev);
    cudaDeviceProp prop; cudaGetDeviceProperties(&prop, dev);
    printf("GPU %s sm_%d%d | CPU %d cores (Neoverse, NEON/128-bit)\n\n",
           prop.name, prop.major, prop.minor, omp_get_max_threads());

    {
        int2 tmp[K];
        for (int c = 0; c < K; c++) {
            cons_lo[c] = c * 10; cons_hi[c] = c * 10 + 9;
            tmp[c].x = cons_lo[c]; tmp[c].y = cons_hi[c];
        }
        cudaMemcpyToSymbol(d_cons, tmp, sizeof(tmp));
    }

    const long sizes[] = {20, 1000, 1000000, 100000000};
    const int BLOCK = 256;

    printf("| %10s | %12s | %12s | %12s | %14s | %14s |\n",
           "N", "GPU graph", "GPU Gchks/s", "CPU NEON 14T", "CPU Mchks/s", "CPU scalar 14T");
    printf("|------------|--------------|--------------|--------------|----------------|----------------|\n");

    for (long ni = 0; ni < 4; ni++) {
        long n = sizes[ni];
        size_t vb = (size_t)n * 4, pb = (size_t)n;
        uint32_t* values; uint8_t* pass;
        cudaMallocManaged(&values, vb);
        cudaMallocManaged(&pass, pb);
        for (long i = 0; i < n; i++) values[i] = (uint32_t)(i * 2654435761u % 200u);
        memset(pass, 0, pb);

        /* --- GPU: capture once, launch graph --- */
        long grid = (n + BLOCK - 1) / BLOCK;
        cudaGraph_t g; cudaGraphExec_t ge;
        cudaStream_t s; cudaStreamCreate(&s);
        cudaStreamBeginCapture(s, cudaStreamCaptureModeGlobal);
        check20_kernel<<<(int)grid, BLOCK, 0, s>>>(values, pass, (int)n);
        cudaStreamEndCapture(s, &g);
        cudaGraphInstantiate(&ge, g, nullptr, nullptr, 0);

        /* warm */
        cudaGraphLaunch(ge, s); cudaStreamSynchronize(s);

        double gpu_best = 1e9;
        for (int r = 0; r < (n <= 1000 ? 2000 : 20); r++) {
            cudaEvent_t e0, e1;
            cudaEventCreate(&e0); cudaEventCreate(&e1);
            cudaEventRecord(e0);
            cudaGraphLaunch(ge, s);
            cudaEventRecord(e1);
            cudaEventSynchronize(e1);
            float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
            if (ms < gpu_best) gpu_best = ms;
            cudaEventDestroy(e0); cudaEventDestroy(e1);
        }

        /* sanity: sample pass bytes */
        long ones = 0; for (long i = 0; i < n && i < 4096; i++) ones += pass[i];

        int reps = n <= 1000 ? 200 : 5;

        /* --- CPU NEON 1 thread (the crossover reference the corpus
               actually published: single-threaded AVX-512) --- */
        omp_set_dynamic(0);
        omp_set_num_threads(1);
        double cpu1_best = 1e9;
        for (int r = 0; r < reps; r++) {
            auto t0 = std::chrono::steady_clock::now();
            cpu_neon(values, pass, n);
            auto t1 = std::chrono::steady_clock::now();
            double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            if (ms < cpu1_best) cpu1_best = ms;
        }

        /* --- CPU NEON 14 threads --- */
        omp_set_num_threads(14);
        double cpu_best = 1e9;
        for (int r = 0; r < reps; r++) {
            auto t0 = std::chrono::steady_clock::now();
            cpu_neon(values, pass, n);
            auto t1 = std::chrono::steady_clock::now();
            double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            if (ms < cpu_best) cpu_best = ms;
        }
        long ones2 = 0; for (long i = 0; i < n && i < 4096; i++) ones2 += pass[i];

        /* --- CPU scalar auto-vec --- */
        double scal_best = 1e9;
        for (int r = 0; r < reps; r++) {
            auto t0 = std::chrono::steady_clock::now();
            cpu_scalar(values, pass, n);
            auto t1 = std::chrono::steady_clock::now();
            double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            if (ms < scal_best) scal_best = ms;
        }

        printf("| %10ld | %10.4f ms | %12.3f | %10.4f ms | %14.3f | %12.4f ms |\n",
               n, gpu_best, (double)n * K / (gpu_best * 1e6) / 1e3,
               cpu_best, (double)n * K / (cpu_best * 1e6) / 1e3, scal_best);
        printf("| %10s | %10s | %12s | %10.4f ms | %14.3f | %12s |\n",
               "CPU 1T:", "", "", cpu1_best,
               (double)n * K / (cpu1_best * 1e6) / 1e3, "");
        if (ones != ones2) printf("    WARNING pass-count mismatch GPU=%ld CPU=%ld (first 4096)\n", ones, ones2);

        cudaGraphDestroy(g); cudaGraphExecDestroy(ge); cudaStreamDestroy(s);
        cudaFree(values); cudaFree(pass);
    }

    printf("\n(checks/s = values x 20 AND-ed constraint checks, the corpus's own metric)\n");
    return 0;
}
