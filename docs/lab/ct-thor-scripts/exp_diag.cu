/**
 * exp_diag.cu — diagnostics for the surprising exp1/exp2 results.
 *
 * exp1 Part B anomaly: the repo's bounds_check kernel on 10^8 managed-memory
 * constraints ran 4897 ms/call while the same kernel on the engine's
 * cudaMalloc pool at 10^7 ran 3.0 ms/call. Variants here isolate:
 *   D1  managed, repo kernel (atomicOr mask), ~95% violations  [re-measure]
 *   D2  device cudaMalloc, repo kernel, uploaded once, resident [isolates managed]
 *   D3  managed, non-atomic per-element byte mask kernel        [isolates atomics]
 *   D4  managed, repo kernel, wide bounds (~5% violations)      [isolates atomic rate]
 *
 * exp2 anomaly: exact_check_kernel (double) ran 453 ms for 9 GB of traffic
 * — ~20 GB/s, far under DRAM. If the FP64 pipe is the wall (Thor iGPU cuts
 * FP64 hard), float/int32 variants of the same loop should be much faster:
 *   D5  double / float / int32 element loops at N=2e8, M=8
 *   D6  pure stream (read values, write mask, no compare loop) = memory floor
 *   D7  host in-place mask read, word-wise XOR, 1 and 14 threads (proper BW)
 */

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cmath>
#include <atomic>
#include <chrono>
#include <random>
#include <thread>
#include <vector>
#include <cuda_runtime.h>

/* repo kernel shape (bounds_check_kernel templated inner loop) */
__global__ void bounds_atomic(const int32_t* __restrict__ v, const int32_t* __restrict__ lo,
                              const int32_t* __restrict__ hi, uint64_t* __restrict__ mask,
                              int count) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < count) {
        int32_t x = v[idx];
        bool bad = (x < lo[idx]) || (x > hi[idx]);
        int word = idx / 64, bit = idx % 64;
        if (bad) atomicOr(reinterpret_cast<unsigned long long*>(mask) + word, 1ULL << bit);
    }
}

/* diagnostic: same walk, non-atomic byte result */
__global__ void bounds_bytes(const int32_t* __restrict__ v, const int32_t* __restrict__ lo,
                             const int32_t* __restrict__ hi, uint8_t* __restrict__ bad,
                             int count) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < count) {
        int32_t x = v[idx];
        bad[idx] = (uint8_t)((x < lo[idx]) || (x > hi[idx]));
    }
}

/* diagnostic: pure stream — touch values, write one byte per element */
__global__ void pure_stream(const int32_t* __restrict__ v, uint8_t* __restrict__ out, int count) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < count) out[idx] = (uint8_t)v[idx];
}

/* exp2's exact_check loop, templated on element type */
template <typename T>
__global__ void exact_loop(const T* __restrict__ values, const T* __restrict__ lo,
                           const T* __restrict__ hi, uint8_t* __restrict__ masks,
                           int N, int M) {
    extern __shared__ char s_raw[];
    T* s_cons = reinterpret_cast<T*>(s_raw);
    for (int i = threadIdx.x; i < 2 * M; i += blockDim.x)
        s_cons[i] = (i % 2 == 0) ? reinterpret_cast<const T*>(&lo[0])[i / 2]
                                 : reinterpret_cast<const T*>(&hi[0])[i / 2];
    __syncthreads();
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;
    T val = values[idx];
    uint8_t mask = 0;
    for (int c = 0; c < M; c++) {
        bool violated = (val < s_cons[2 * c]) | (val > s_cons[2 * c + 1]) | (val != val);
        mask |= (static_cast<uint8_t>(violated) << c);
    }
    masks[idx] = mask;
}

static double time_kernel_calls(const char* name, int calls, long n, int block,
                                void (*launch)(void*), void* ctx) {
    /* generic timed loop via callback */
    cudaEvent_t e0, e1;
    cudaEventCreate(&e0); cudaEventCreate(&e1);
    float best = 1e9;
    for (int r = 0; r < calls; r++) {
        cudaEventRecord(e0);
        launch(ctx);
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
        if (ms < best) best = ms;
    }
    (void)name; (void)n; (void)block;
    cudaEventDestroy(e0); cudaEventDestroy(e1);
    return best;
}

struct CtxA { const int32_t *v, *lo, *hi; uint64_t* mask; int n, block; long grid; };
struct CtxB { const int32_t *v, *lo, *hi; uint8_t* bad; int n; long grid; };
struct CtxC { const int32_t* v; uint8_t* out; int n; long grid; };

static void l_atomic(void* p) { CtxA* c = (CtxA*)p; bounds_atomic<<<(int)c->grid, 256>>>(c->v, c->lo, c->hi, c->mask, c->n); }
static void l_bytes(void* p)  { CtxB* c = (CtxB*)p; bounds_bytes<<<(int)c->grid, 256>>>(c->v, c->lo, c->hi, c->bad, c->n); }
static void l_stream(void* p) { CtxC* c = (CtxC*)p; pure_stream<<<(int)c->grid, 256>>>(c->v, c->out, c->n); }

int main() {
    printf("=== exp_diag: isolate exp1 managed-memory and exp2 FP64 effects ===\n");
    const long N = 100000000L;
    const int BLOCK = 256;
    const long grid = (N + BLOCK - 1) / BLOCK;

    int32_t *v, *lo, *hi;
    cudaMallocManaged(&v, (size_t)N * 4);
    cudaMallocManaged(&lo, (size_t)N * 4);
    cudaMallocManaged(&hi, (size_t)N * 4);
    std::mt19937 rng(42);
    std::uniform_int_distribution<int32_t> dist(-1000, 1000);
    for (long i = 0; i < N; i++) {
        lo[i] = dist(rng); hi[i] = lo[i] + 100; v[i] = dist(rng);   /* ~95% violate */
    }

    /* D1: managed + atomic mask (re-measure) */
    {
        uint64_t* mask; cudaMallocManaged(&mask, ((N + 63) / 64) * 8);
        CtxA c{v, lo, hi, mask, (int)N, BLOCK, grid};
        double best = time_kernel_calls("D1", 3, N, BLOCK, l_atomic, &c);
        printf("D1 managed + atomicOr mask, 95%% violate:  %8.2f ms/call  (%.2f G checks/s)\n",
               best, N / (best * 1e6));
        cudaFree(mask);
    }

    /* D2: device cudaMalloc, upload once, resident */
    {
        int32_t *dv, *dlo, *dhi; uint64_t* dmask;
        cudaMalloc(&dv, (size_t)N * 4); cudaMalloc(&dlo, (size_t)N * 4);
        cudaMalloc(&dhi, (size_t)N * 4); cudaMalloc(&dmask, ((N + 63) / 64) * 8);
        cudaMemcpy(dv, v, (size_t)N * 4, cudaMemcpyHostToDevice);
        cudaMemcpy(dlo, lo, (size_t)N * 4, cudaMemcpyHostToDevice);
        cudaMemcpy(dhi, hi, (size_t)N * 4, cudaMemcpyHostToDevice);
        CtxA c{dv, dlo, dhi, dmask, (int)N, BLOCK, grid};
        double best = time_kernel_calls("D2", 5, N, BLOCK, l_atomic, &c);
        printf("D2 device malloc + atomicOr mask:          %8.2f ms/call  (%.2f G checks/s)\n",
               best, N / (best * 1e6));
        cudaFree(dv); cudaFree(dlo); cudaFree(dhi); cudaFree(dmask);
    }

    /* D3: managed + non-atomic byte mask */
    {
        uint8_t* bad; cudaMallocManaged(&bad, (size_t)N);
        CtxB c{v, lo, hi, bad, (int)N, grid};
        double best = time_kernel_calls("D3", 5, N, BLOCK, l_bytes, &c);
        printf("D3 managed + non-atomic byte mask:         %8.2f ms/call  (%.2f G checks/s)\n",
               best, N / (best * 1e6));
        cudaFree(bad);
    }

    /* D4: managed + atomic, constant bounds with ~5% violation rate
       (v ~ U(-1000,1000); v violates iff v < -950 or v > 950) */
    {
        for (long i = 0; i < N; i++) { lo[i] = -950; hi[i] = 950; }
        uint64_t* mask; cudaMallocManaged(&mask, ((N + 63) / 64) * 8);
        CtxA c{v, lo, hi, mask, (int)N, BLOCK, grid};
        double best = time_kernel_calls("D4", 5, N, BLOCK, l_atomic, &c);
        printf("D4 managed + atomicOr, ~5%% violate:        %8.2f ms/call  (%.2f G checks/s)\n",
               best, N / (best * 1e6));
        for (long i = 0; i < N; i++) { lo[i] = dist(rng); hi[i] = lo[i] + 100; }  /* restore */
        cudaFree(mask);
    }

    /* D5/D6: element-type sweep + pure stream at N=2e8 */
    {
        const long n2 = 200000000L;
        const int M = 8;
        long grid2 = (n2 + BLOCK - 1) / BLOCK;
        double *fv, *flo, *fhi; uint8_t* mk;
        cudaMallocManaged(&fv, (size_t)n2 * 8);
        cudaMallocManaged(&flo, (size_t)n2 * 8);
        cudaMallocManaged(&fhi, (size_t)n2 * 8);
        cudaMallocManaged(&mk, (size_t)n2);
        std::uniform_real_distribution<double> du(-10, 10);
        for (long i = 0; i < n2; i++) {
            fv[i] = du(rng); flo[i] = -5 + (i % 8) * 0.5; fhi[i] = 5 - (i % 8) * 0.3;
        }
        cudaEvent_t e0, e1; cudaEventCreate(&e0); cudaEventCreate(&e1);
        auto t1 = [&]() {
            exact_loop<double><<<(int)grid2, BLOCK, 2 * M * 8>>>(fv, flo, fhi, mk, (int)n2, M);
        };
        t1(); cudaDeviceSynchronize();
        double bd = 1e9;
        for (int r = 0; r < 3; r++) {
            cudaEventRecord(e0); t1(); cudaEventRecord(e1); cudaEventSynchronize(e1);
            float ms = 0; cudaEventElapsedTime(&ms, e0, e1); if (ms < bd) bd = ms;
        }
        printf("D5a exact loop double, N=2e8 M=8:          %8.2f ms  (%.1f G checks/s)\n",
               bd, (double)n2 * M / (bd * 1e6));

        /* float view of the same data */
        float* fv32 = (float*)fv; float* flo32 = (float*)flo; float* fhi32 = (float*)fhi;
        auto t2 = [&]() {
            exact_loop<float><<<(int)grid2, BLOCK, 2 * M * 4>>>(fv32, flo32, fhi32, mk, (int)n2, M);
        };
        t2(); cudaDeviceSynchronize();
        double bf = 1e9;
        for (int r = 0; r < 5; r++) {
            cudaEventRecord(e0); t2(); cudaEventRecord(e1); cudaEventSynchronize(e1);
            float ms = 0; cudaEventElapsedTime(&ms, e0, e1); if (ms < bf) bf = ms;
        }
        printf("D5b exact loop float,  N=2e8 M=8:          %8.2f ms  (%.1f G checks/s)\n",
               bf, (double)n2 * M / (bf * 1e6));

        CtxC cs{(int32_t*)fv, mk, (int)n2, grid2};
        double bs = time_kernel_calls("D6", 5, n2, BLOCK, l_stream, &cs);
        printf("D6  pure stream int32+byte (memory floor): %8.2f ms  (%.0f GB/s)\n",
               bs, (double)n2 * 5 / (bs * 1e6));

        cudaFree(fv); cudaFree(flo); cudaFree(fhi); cudaFree(mk);
    }

    /* D7: proper host in-place read of a 1 GB mask (word-wise XOR, 4 accum) */
    {
        const long nb = 1000000000L;
        uint8_t* mk; cudaMallocManaged(&mk, (size_t)nb);
        cudaMemset(mk, 7, (size_t)nb);
        auto t0 = std::chrono::high_resolution_clock::now();
        uint64_t a0 = 0, a1 = 0, a2 = 0, a3 = 0;
        const uint64_t* w = (const uint64_t*)mk;
        long nw = nb / 8;
        for (long i = 0; i < nw; i += 4) {
            a0 ^= w[i]; a1 ^= w[i + 1]; a2 ^= w[i + 2]; a3 ^= w[i + 3];
        }
        uint64_t acc = a0 ^ a1 ^ a2 ^ a3;
        auto t1 = std::chrono::high_resolution_clock::now();
        double ms1 = std::chrono::duration<double, std::milli>(t1 - t0).count();
        printf("D7 host in-place 1 GB read, 1 thread:      %8.2f ms  (%.1f GB/s, xor=%llx)\n",
               ms1, (double)nb / (ms1 * 1e6), (unsigned long long)acc);

        for (int rep = 0; rep < 3; rep++) {
            std::atomic<uint64_t> total{0};
            auto t2 = std::chrono::high_resolution_clock::now();
            std::vector<std::thread> ths;
            for (int t = 0; t < 14; t++) {
                ths.emplace_back([&, t]() {
                    uint64_t x = 0;
                    long l = nw * t / 14, h = nw * (t + 1) / 14;
                    for (long i = l; i < h; i++) x ^= w[i];
                    total += x;
                });
            }
            for (auto& th : ths) th.join();
            auto t3 = std::chrono::high_resolution_clock::now();
            double ms = std::chrono::duration<double, std::milli>(t3 - t2).count();
            if (rep == 2)
                printf("D7 host in-place 1 GB read, 14 threads:    %8.2f ms  (%.1f GB/s, xor=%llx)\n",
                       ms, (double)nb / (ms * 1e6), (unsigned long long)total.load());
        }
        cudaFree(mk);
    }

    printf("\nOK\n");
    return 0;
}
