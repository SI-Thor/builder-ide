/**
 * exp1_ce_resident.cu — ct-thor experiment 1
 *
 * cuda-constraint-engine rebuilt for sm_110 (Jetson AGX Thor, 122 GB unified).
 *
 * Part A — the engine's stock ce_check_i32 path at its published size (10M,
 *          the README's "8.5 ms / 1.17B/sec on RTX 4050" row). Per call this
 *          path H2D-copies the values, launches, counts, syncs, and D2H-copies
 *          the mask — the PCIe-coupled shape it shipped with.
 *
 * Part B — the Thor path the README was waiting for: 10^8 constraints, all
 *          buffers in unified memory (cudaMallocManaged; on this iGPU the
 *          device pointer IS the host pointer), resident across 100 calls.
 *          Uses the repo's own kernels (launch_bounds_check_i32 /
 *          launch_violation_count) with zero copies: no upload, no readback.
 *          Between calls the host rewrites a slice of the bounds in place —
 *          the next call sees the new bounds with no upload API involved.
 *
 * Data pattern matches the repo's examples/batch_check.cu exactly:
 * lo ~ U(-1000,1000), hi = lo + 100, values ~ U(-1000,1000).
 */

#include "kernels.cuh"
#include <cstdio>
#include <cstdlib>
#include <algorithm>
#include <random>
#include <vector>
#include <chrono>
#include <cuda_runtime.h>

#include "constraint_engine.h"

static void fill_pattern(std::mt19937& rng, int32_t* lo, int32_t* hi,
                         int32_t* values, long n) {
    std::uniform_int_distribution<int32_t> dist(-1000, 1000);
    for (long i = 0; i < n; i++) {
        lo[i] = dist(rng);
        hi[i] = lo[i] + 100;
        values[i] = dist(rng);
    }
}

int main() {
    printf("=== exp1: cuda-constraint-engine on Thor (sm_110) ===\n");
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);
    printf("device %s sm_%d%d, %d SMs, %.1f GB\n\n", prop.name, prop.major,
           prop.minor, prop.multiProcessorCount,
           prop.totalGlobalMem / 1073741824.0);

    /* ---------------- Part A: stock ce_check_i32 at 10M ---------------- */
    {
        const int N = 10'000'000;
        CEConfig config;
        ce_config_default(&config);
        config.max_constraints = N;
        config.precision = CE_INT32;
        config.stream_count = 0;           /* synchronous, like the README row */

        CEEngine* engine = ce_create_configured(&config);
        if (!engine) { fprintf(stderr, "engine create failed: %s\n", ""); return 1; }

        std::mt19937 rng(42);
        std::vector<int32_t> lo(N), hi(N), values(N);
        fill_pattern(rng, lo.data(), hi.data(), values.data(), N);

        ce_upload_bounds_i32(engine, lo.data(), hi.data(), N);

        /* first call = the published scenario shape (includes copies) */
        auto w0 = std::chrono::high_resolution_clock::now();
        CEResult* r = ce_check_i32(engine, values.data(), N);
        auto w1 = std::chrono::high_resolution_clock::now();
        double first_ms = std::chrono::duration<double, std::milli>(w1 - w0).count();
        printf("[A] stock ce_check_i32, N=10^7 (published size)\n");
        printf("    violations %d/%d  latency %.3f ms  throughput %.2fB checks/s\n",
               ce_result_violation_count(r), N, ce_result_latency_ms(r),
               ce_result_throughput(r) / 1e9);
        ce_result_destroy(r);

        /* steady state: 20 more calls, report best/median */
        std::vector<double> lat;
        int viol = 0;
        for (int i = 0; i < 20; i++) {
            CEResult* ri = ce_check_i32(engine, values.data(), N);
            lat.push_back(ce_result_latency_ms(ri));
            viol = ce_result_violation_count(ri);
            ce_result_destroy(ri);
        }
        double sum = 0; for (double v : lat) sum += v;
        printf("    steady-state over 20 calls: mean %.3f ms  best %.3f ms"
               "  -> %.2fB checks/s (wall incl. copies %.3f ms first call)\n",
               sum / lat.size(), *std::min_element(lat.begin(), lat.end()),
               N / ((*std::min_element(lat.begin(), lat.end())) / 1e3) / 1e9,
               first_ms);
        ce_destroy(engine);
    }

    /* -------- Part B: resident unified memory, 10^8, 100 calls -------- */
    {
        const long N = 100'000'000L;
        size_t bytes = (size_t)N * sizeof(int32_t);
        size_t mask_bytes = ((N + 63) / 64) * sizeof(uint64_t);
        printf("\n[B] resident unified memory, N=10^8, 100 calls\n");
        printf("    buffers: values+lo+hi = %.2f GB, mask = %.1f MB\n",
               3.0 * bytes / 1e9, mask_bytes / 1e6);

        int32_t *lo, *hi, *values;
        uint64_t* mask;
        int* count_out;
        cudaMallocManaged(&lo, bytes);
        cudaMallocManaged(&hi, bytes);
        cudaMallocManaged(&values, bytes);
        cudaMallocManaged(&mask, mask_bytes);
        cudaMallocManaged(&count_out, sizeof(int));
        printf("    managed ptr lo=%p values=%p (device ptr == host ptr)\n",
               (void*)lo, (void*)values);

        std::mt19937 rng(42);
        fill_pattern(rng, lo, hi, values, N);
        cudaMemset(mask, 0, mask_bytes);

        const int BLOCK = 256;
        long blocks = (N + BLOCK - 1) / BLOCK;
        int mw = (int)((N + 63) / 64);

        /* correctness sample: CPU recount of first 32 mask words after call 1 */
        auto cpu_sample = [&](int words) {
            int mism = 0;
            for (int w = 0; w < words; w++) {
                uint64_t expect = 0;
                for (int b = 0; b < 64; b++) {
                    long i = (long)w * 64 + b;
                    if (values[i] < lo[i] || values[i] > hi[i])
                        expect |= 1ULL << b;
                }
                if (expect != mask[w]) mism++;
            }
            return mism;
        };

        cudaEvent_t e0, e1;
        cudaEventCreate(&e0); cudaEventCreate(&e1);
        double ev_best = 1e9, ev_sum = 0;
        auto wstart = std::chrono::high_resolution_clock::now();
        const int CALLS = 100;
        for (int c = 0; c < CALLS; c++) {
            /* host rewrites 1000 bounds in place — no upload API, the GPU
               reads them directly on the next launch */
            if (c == 50) {
                std::uniform_int_distribution<int32_t> d2(-1000, 1000);
                for (int k = 0; k < 1000; k++) lo[k] = d2(rng);
            }
            cudaEventRecord(e0);
            cudaMemsetAsync(mask, 0, mask_bytes);
            launch_bounds_check_i32(values, lo, hi, mask, (int)N, 0);
            launch_violation_count(mask, mw, count_out, 0);
            cudaEventRecord(e1);
            cudaEventSynchronize(e1);
            float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
            ev_sum += ms; if (ms < ev_best) ev_best = ms;
        }
        auto wend = std::chrono::high_resolution_clock::now();
        double wall_s = std::chrono::duration<double>(wend - wstart).count();
        int host_count = 0;
        cudaMemcpy(&host_count, count_out, sizeof(int), cudaMemcpyDeviceToHost);

        int mism = cpu_sample(32);
        printf("    100 calls: mean %.3f ms/call, best %.3f ms/call\n",
               ev_sum / CALLS, ev_best);
        printf("    -> %.2fB checks/s per call (best), %.2fB steady mean\n",
               N / (ev_best / 1e3) / 1e9, N / (ev_sum / CALLS / 1e3) / 1e9);
        printf("    wall for 100 calls incl. host mutation: %.2f s (%.2f ms/call)\n",
               wall_s, wall_s * 1e3 / CALLS);
        printf("    violation count (GPU reduction): %d; mask sample mismatches %d/32 words\n",
               host_count, mism);

        /* per-call byte traffic: 3×4 B in + ~0.156 B out per element */
        double gbytes = 3.0 * bytes / 1e9 + (double)mask_bytes / 1e9;
        printf("    effective DRAM traffic %.3f GB/call -> %.0f GB/s at best call\n",
               gbytes, gbytes / (ev_best / 1e3));

        cudaFree(lo); cudaFree(hi); cudaFree(values);
        cudaFree(mask); cudaFree(count_out);
    }
    printf("\nOK\n");
    return 0;
}
