/**
 * exp2_flux_exact.cu — ct-thor experiment 2
 *
 * flux-gpu's exact_check_kernel (kernel pasted verbatim from the repo) on
 * 10^9 values, M=8 double-precision range constraints — the repo's own
 * benchmark shape, scaled past its 6 GB RTX 4050 table.
 *
 * Timed separately:
 *   (1) the kernel alone (CUDA events),
 *   (2) the host reading the 1-byte/value error mask IN PLACE out of unified
 *       memory (no cudaMemcpy — the Thor zero-copy path), single-thread and
 *       14-thread,
 *   (3) the old discrete-GPU shape: cudaMemcpy D2H of the same mask —
 *       what the copy used to add on the other side of PCIe.
 *
 * Buffers: values 8 GB + masks 1 GB in unified memory (device ptr == host
 * ptr on this iGPU). Total ~9 GB — well under the 60 GB cap.
 */

#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstdint>
#include <chrono>
#include <random>
#include <thread>
#include <vector>
#include <atomic>
#include <cuda_runtime.h>

// ── Constraint & Result (from flux-gpu/exact_check_kernel.cu) ───────
struct Constraint {
    double lo;
    double hi;
};

// ── Kernel (verbatim from flux-gpu/exact_check_kernel.cu) ───────────
__global__ void exact_check_kernel(
    const double* __restrict__ values,
    const Constraint* __restrict__ cons,
    uint8_t* __restrict__ error_masks,
    int N, int M
) {
    extern __shared__ Constraint s_cons[];

    for (int i = threadIdx.x; i < M; i += blockDim.x) {
        s_cons[i] = cons[i];
    }
    __syncthreads();

    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    double val = values[idx];
    uint8_t mask = 0;

    for (int c = 0; c < M; c++) {
        bool violated = (val < s_cons[c].lo) | (val > s_cons[c].hi) | isnan(val);
        mask |= (static_cast<uint8_t>(violated) << c);
    }

    error_masks[idx] = mask;
}

__global__ void count_violated_kernel(
    const uint8_t* __restrict__ masks,
    long N,
    unsigned long long* __restrict__ total_violated
) {
    long idx = (long)blockIdx.x * blockDim.x + threadIdx.x;
    int local = (idx < N && masks[idx] != 0) ? 1 : 0;
    unsigned m = __ballot_sync(0xFFFFFFFF, local);
    int warp_violated = __popc(m);
    if ((threadIdx.x & 31) == 0) atomicAdd(total_violated, (unsigned long long)warp_violated);
}

int main() {
    printf("=== exp2: flux-gpu exact_check_kernel on Thor, N=10^9, M=8 ===\n");
    const long N = 1000000000L;
    const int M = 8;

    double* values; Constraint* cons; uint8_t* masks;
    cudaMallocManaged(&values, (size_t)N * sizeof(double));
    cudaMallocManaged(&masks, (size_t)N);
    cudaMallocManaged(&cons, (size_t)M * sizeof(Constraint));
    printf("buffers: %.2f GB values + %.2f GB mask (unified)\n",
           (double)N * 8 / 1e9, (double)N / 1e9);

    /* same init shape as the repo's run_benchmark: values in [-10,10],
       8 constraints, 0.1% NaNs */
    std::mt19937 rng(42);
    std::uniform_real_distribution<double> u(-10.0, 10.0);
    for (long i = 0; i < N; i++) values[i] = u(rng);
    for (int c = 0; c < M; c++) { cons[c].lo = -5.0 + c * 0.5; cons[c].hi = 5.0 - c * 0.3; }
    for (long i = 0; i < N / 1000; i++) values[rng() % N] = NAN;

    const int BLOCK = 256;
    long grid = (N + BLOCK - 1) / BLOCK;   /* 3.9M blocks */
    size_t shared = M * sizeof(Constraint);

    /* warmup + correctness sample (first 1M values on CPU) */
    exact_check_kernel<<<(int)grid, BLOCK, shared>>>(values, cons, masks, (int)N, M);
    cudaDeviceSynchronize();
    long mism = 0;
    for (long i = 0; i < 1000000; i++) {
        uint8_t expect = 0;
        for (int c = 0; c < M; c++) {
            bool v = (values[i] < cons[c].lo) | (values[i] > cons[c].hi) | std::isnan(values[i]);
            expect |= (uint8_t)v << c;
        }
        if (expect != masks[i]) mism++;
    }
    printf("correctness sample first 1M: %ld mismatches\n", mism);

    /* (1) kernel alone — best of 5 */
    cudaEvent_t e0, e1;
    cudaEventCreate(&e0); cudaEventCreate(&e1);
    double kbest = 1e9;
    for (int r = 0; r < 5; r++) {
        cudaEventRecord(e0);
        exact_check_kernel<<<(int)grid, BLOCK, shared>>>(values, cons, masks, (int)N, M);
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
        if (ms < kbest) kbest = ms;
    }
    printf("[1] kernel:                %8.2f ms   (%.1f G checks/s, %.0f GB/s effective)\n",
           kbest, (double)N * M / (kbest * 1e6), (N * 9.0 / 1e9) / (kbest / 1e3));

    /* violation count on GPU for reference */
    unsigned long long* d_viol; cudaMallocManaged(&d_viol, 8); *d_viol = 0;
    count_violated_kernel<<<(int)grid, BLOCK>>>(masks, N, d_viol);
    cudaDeviceSynchronize();
    printf("    violated (GPU count): %llu of %ld\n", *d_viol, N);

    /* (2) host reads the mask in place — single thread */
    auto t0 = std::chrono::high_resolution_clock::now();
    unsigned long long acc = 0;
    for (long i = 0; i < N; i++) acc += masks[i];
    auto t1 = std::chrono::high_resolution_clock::now();
    double r1 = std::chrono::duration<double, std::milli>(t1 - t0).count();
    printf("[2] host read in place:    %8.2f ms   1 thread (%.1f GB/s, sum=%llu checksum)\n",
           r1, (double)N / (r1 * 1e6), acc);

    /* 14 threads */
    for (int rep = 0; rep < 3; rep++) {
        std::atomic<unsigned long long> acc2{0};
        auto t2 = std::chrono::high_resolution_clock::now();
        std::vector<std::thread> ths;
        for (int t = 0; t < 14; t++) {
            ths.emplace_back([&, t]() {
                unsigned long long a = 0;
                long lo = N * t / 14, hi = N * (t + 1) / 14;
                for (long i = lo; i < hi; i++) a += masks[i];
                acc2 += a;
            });
        }
        for (auto& th : ths) th.join();
        auto t3 = std::chrono::high_resolution_clock::now();
        double r14 = std::chrono::duration<double, std::milli>(t3 - t2).count();
        if (rep == 2)
            printf("    host read in place:    %8.2f ms  14 threads (%.1f GB/s, sum=%llu)\n",
                   r14, (double)N / (r14 * 1e6), acc2.load());
    }

    /* (3) the old shape: cudaMemcpy D2H of the mask to a separate buffer */
    uint8_t* host_copy = (uint8_t*)malloc((size_t)N);
    double cbest = 1e9;
    for (int r = 0; r < 3; r++) {
        auto t4 = std::chrono::high_resolution_clock::now();
        cudaMemcpy(host_copy, masks, (size_t)N, cudaMemcpyDeviceToHost);
        auto t5 = std::chrono::high_resolution_clock::now();
        double ms = std::chrono::duration<double, std::milli>(t5 - t4).count();
        if (ms < cbest) cbest = ms;
    }
    printf("[3] cudaMemcpy D2H 1 GB:   %8.2f ms   (the copy the 4050 needed; %.1f GB/s)\n",
           cbest, 1.0 / (cbest / 1e3) / 1.024);

    printf("\nend-to-end Thor path (kernel + in-place read, 1 thread): %.2f ms\n",
           kbest + r1);
    printf("end-to-end discrete shape would be (kernel + D2H copy):  %.2f ms\n",
           kbest + cbest);

    cudaFree(values); cudaFree(masks); cudaFree(cons); cudaFree(d_viol); free(host_copy);
    printf("OK\n");
    return 0;
}
