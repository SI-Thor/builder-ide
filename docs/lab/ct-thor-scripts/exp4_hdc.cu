/**
 * exp4_hdc.cu — ct-thor experiment 4
 *
 * flux-hdc on the Thor: batch Hamming matching of 1024-bit hypervectors
 * (16 × 64-bit words, XOR + popcount), SIMT kernel vs the repo's C baseline
 * shape run on the Thor's 14 Neoverse cores.
 *
 * The repo's C/AVX-512 baseline matches 128-bit FOLDED vectors (2 words).
 * Both are measured here: the full 1024-bit comparison (what "10^6 x 10^6
 * 1024-bit hypervectors" means) and the folded-128-bit path (the published
 * "5.5B/s" shape) for reference.
 *
 * Scale: database of 10^6 hypervectors (128 MB, resident in unified memory).
 * The full 10^6 x 10^6 product is 10^12 comparisons x 128 B = 128 TB of
 * DRAM traffic — about 148 h at this box's ~240 GB/s with no reuse, so we
 * measure a real slice (4096 queries x the full 10^6 database with 32-query
 * x 256-vector tiling = 4.1 x 10^9 real comparisons) and an L2-resident
 * configuration (database 2^18 vectors = 32 MB = the Thor's whole L2) that
 * exposes the pure compute rate, then extrapolate with the byte arithmetic
 * stated openly.
 *
 * Correctness: GPU best-match distances are checked against a CPU brute
 * force on a 2^16-vector prefix for 4 queries.
 */

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <chrono>
#include <omp.h>
#include <cuda_runtime.h>

#define HV_WORDS 16

static uint64_t splitmix64(uint64_t* s) {
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

/* ---------------- GPU kernel ----------------
 * Block: 256 threads = 8 warps. Shared tile: 256 db vectors (row-padded to
 * 17 words to avoid 32-way bank conflicts). Each warp takes one query per
 * pass: lanes stride the 256-vector tile (8 vectors/lane), popcount-distance,
 * warp-reduce the min, one shared atomicMin per warp. 4 passes cover the
 * 32-query tile. */

#define DB_TILE 256
#define Q_TILE  32
#define HV_PAD  17            /* padded row to kill bank conflicts */

__global__ void hdc_match_kernel(const uint64_t* __restrict__ db,      /* [DB][16] */
                                 const uint64_t* __restrict__ queries, /* [Q][16] */
                                 int* __restrict__ best,               /* [Q] */
                                 int db_n, int q_n) {
    __shared__ uint64_t s_db[DB_TILE][HV_PAD];
    __shared__ int s_best[Q_TILE];

    const int db0 = blockIdx.x * DB_TILE;
    const int q0  = blockIdx.y * Q_TILE;
    const int tid = threadIdx.x;
    const int lane = tid & 31, warp = tid >> 5, nwarp = blockDim.x >> 5;

    for (int i = tid; i < DB_TILE; i += blockDim.x) {
        #pragma unroll
        for (int w = 0; w < HV_WORDS; w++)
            s_db[i][w] = db[(long)(db0 + i) * HV_WORDS + w];
    }
    if (tid < Q_TILE) s_best[tid] = 0x7FFFFFFF;
    __syncthreads();

    const int q_per_pass = nwarp;             /* one query per warp per pass */
    for (int qp = 0; qp < Q_TILE / q_per_pass; qp++) {
        const int q = q0 + qp * q_per_pass + warp;
        if (q >= q_n) continue;
        const uint64_t* qv = queries + (long)q * HV_WORDS;
        int local_min = 0x7FFFFFFF;
        for (int i = lane; i < DB_TILE; i += 32) {
            int d = 0;
            #pragma unroll
            for (int w = 0; w < HV_WORDS; w++)
                d += __popcll(s_db[i][w] ^ qv[w]);
            if (d < local_min) local_min = d;
        }
        /* warp reduce min */
        for (int off = 16; off > 0; off >>= 1)
            local_min = min(local_min, __shfl_down_sync(0xFFFFFFFF, local_min, off));
        if (lane == 0) atomicMin(&s_best[qp * q_per_pass + warp], local_min);
    }
    __syncthreads();

    if (tid < Q_TILE) {
        int qq = q0 + tid;
        if (qq < q_n) atomicMin(&best[qq], s_best[tid]);
    }
}

/* ---------------- CPU baselines (OpenMP, 14 cores) ---------------- */

/* full 1024-bit XOR+popcount, best match per query */
static void cpu_hdc_full(const uint64_t* db, const uint64_t* queries,
                         int* best, int db_n, int q_n, int nthreads) {
    #pragma omp parallel for schedule(dynamic, 1) num_threads(nthreads)
    for (int q = 0; q < q_n; q++) {
        const uint64_t* qv = queries + (long)q * HV_WORDS;
        int b = 0x7FFFFFFF;
        for (int i = 0; i < db_n; i++) {
            const uint64_t* dv = db + (long)i * HV_WORDS;
            int d = 0;
            for (int w = 0; w < HV_WORDS; w++) d += __builtin_popcountll(dv[w] ^ qv[w]);
            if (d < b) b = d;
        }
        best[q] = b;
    }
}

/* the repo's published shape: 128-bit folded vectors (2 words) */
static void cpu_hdc_folded(const uint64_t* db, const uint64_t* queries,
                           int* best, int db_n, int q_n, int nthreads) {
    #pragma omp parallel for schedule(dynamic, 1) num_threads(nthreads)
    for (int q = 0; q < q_n; q++) {
        const uint64_t* qv = queries + (long)q * HV_WORDS;
        int b = 0x7FFFFFFF;
        for (int i = 0; i < db_n; i++) {
            const uint64_t* dv = db + (long)i * HV_WORDS;
            int d = __builtin_popcountll(dv[0] ^ qv[0]) + __builtin_popcountll(dv[1] ^ qv[1]);
            if (d < b) b = d;
        }
        best[q] = b;
    }
}

static double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    printf("=== exp4: flux-hdc 1024-bit hypervector matching on Thor ===\n");
    int dev; cudaGetDevice(&dev);
    cudaDeviceProp prop; cudaGetDeviceProperties(&prop, dev);
    printf("GPU %s sm_%d%d, L2 %.0f MB | CPU %d cores\n\n",
           prop.name, prop.major, prop.minor, prop.l2CacheSize / 1048576.0,
           omp_get_max_threads());

    const int DB_N = 1000000;
    const int Q_SLICE = 4096;

    /* --- allocation (unified, resident) --- */
    uint64_t* db;    cudaMallocManaged(&db, (size_t)DB_N * HV_WORDS * 8);
    uint64_t* query; cudaMallocManaged(&query, (size_t)Q_SLICE * HV_WORDS * 8);
    int* best_g;     cudaMallocManaged(&best_g, (size_t)Q_SLICE * 4);
    int* best_c;     cudaMallocManaged(&best_c, (size_t)Q_SLICE * 4);
    printf("database %.0f MB + queries %.1f MB (unified, resident)\n",
           (double)DB_N * HV_WORDS * 8 / 1e6, (double)Q_SLICE * HV_WORDS * 8 / 1e6);

    uint64_t seed = 0x1234567;
    for (long i = 0; i < (long)DB_N * HV_WORDS; i++) db[i] = splitmix64(&seed);
    for (long i = 0; i < (long)Q_SLICE * HV_WORDS; i++) query[i] = splitmix64(&seed);

    /* --- correctness: db prefix 2^16, 4 queries, GPU vs CPU --- */
    {
        const int P = 65536, Q4 = 4;
        for (int q = 0; q < Q4; q++) { best_g[q] = 0x7FFFFFFF; best_c[q] = 0x7FFFFFFF; }
        dim3 grid(P / DB_TILE, 1), block(DB_TILE);
        hdc_match_kernel<<<grid, block>>>(db, query, best_g, P, Q4);
        cudaDeviceSynchronize();
        cpu_hdc_full(db, query, best_c, P, Q4, 14);
        int ok = 1;
        for (int q = 0; q < Q4; q++) if (best_g[q] != best_c[q]) ok = 0;
        printf("correctness (2^16 db x 4 queries): GPU bests %d %d %d %d, CPU %d %d %d %d -> %s\n",
               best_g[0], best_g[1], best_g[2], best_g[3],
               best_c[0], best_c[1], best_c[2], best_c[3], ok ? "MATCH" : "MISMATCH");
    }

    /* --- GPU slice: 4096 queries x full 10^6 database --- */
    {
        for (int q = 0; q < Q_SLICE; q++) best_g[q] = 0x7FFFFFFF;
        dim3 grid(DB_N / DB_TILE, Q_SLICE / Q_TILE), block(DB_TILE);
        cudaEvent_t e0, e1; cudaEventCreate(&e0); cudaEventCreate(&e1);
        cudaDeviceSynchronize();
        double w0 = now_ms();
        cudaEventRecord(e0);
        hdc_match_kernel<<<grid, block>>>(db, query, best_g, DB_N, Q_SLICE);
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        double w1 = now_ms();
        float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
        double comps = (double)DB_N * Q_SLICE;
        printf("\n[GPU tiled kernel] %d x %d = %.2f G comparisons\n", Q_SLICE, DB_N, comps / 1e9);
        printf("  kernel %.1f ms -> %.3f G comparisons/s (%.0f GB/s effective)\n",
               ms, comps / (ms * 1e6), comps * 128.0 / (ms * 1e6));
        printf("  wall %.1f ms; best-hamming sample: %d %d %d\n",
               w1 - w0, best_g[0], best_g[1], best_g[2]);
        printf("  extrapolation to the full 10^6 x 10^6 product: %.1f h (DRAM-bound; %0.f TB to move)\n",
               ms / 1e3 * 1e6 / Q_SLICE / 3600.0, 128.0);
    }

    /* --- GPU L2-resident: db 2^18 (32 MB), 4096 queries --- */
    {
        const int P = 262144, Q = 4096;
        for (int q = 0; q < Q; q++) best_g[q] = 0x7FFFFFFF;
        dim3 grid(P / DB_TILE, Q / Q_TILE), block(DB_TILE);
        cudaEvent_t e0, e1; cudaEventCreate(&e0); cudaEventCreate(&e1);
        /* warm the L2 with one throwaway pass */
        hdc_match_kernel<<<grid, block>>>(db, query, best_g, P, Q);
        cudaDeviceSynchronize();
        for (int q = 0; q < Q; q++) best_g[q] = 0x7FFFFFFF;
        cudaEventRecord(e0);
        hdc_match_kernel<<<grid, block>>>(db, query, best_g, P, Q);
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
        double comps = (double)P * Q;
        printf("\n[GPU L2-resident db] %d x %d = %.2f G comparisons\n", Q, P, comps / 1e9);
        printf("  kernel %.1f ms -> %.3f G comparisons/s\n", ms, comps / (ms * 1e6));
    }

    /* --- CPU 14 cores, same slices --- */
    {
        double t0 = now_ms();
        cpu_hdc_full(db, query, best_c, DB_N, Q_SLICE, 14);
        double t1 = now_ms();
        double comps = (double)DB_N * Q_SLICE;
        printf("\n[C 14 cores, full 1024-bit] same %.2f G comparisons: %.1f ms -> %.3f G comparisons/s\n",
               comps / 1e9, t1 - t0, comps / ((t1 - t0) * 1e6));
        printf("  extrapolation to 10^6 x 10^6: %.1f h\n", (t1 - t0) / 1e3 * 1e6 / Q_SLICE / 3600.0);

        /* single-thread reference */
        t0 = now_ms();
        cpu_hdc_full(db, query, best_c, DB_N, 256, 1);
        t1 = now_ms();
        printf("  single-thread rate: %.3f G comparisons/s\n",
               (double)DB_N * 256 / ((t1 - t0) * 1e6));

        /* folded-128-bit (the repo's published shape) */
        t0 = now_ms();
        cpu_hdc_folded(db, query, best_c, DB_N, Q_SLICE, 14);
        t1 = now_ms();
        printf("[C 14 cores, folded 128-bit (repo's 5.5B/s shape)] %.3f G comparisons/s\n",
               (double)DB_N * Q_SLICE / ((t1 - t0) * 1e6));
    }

    cudaFree(db); cudaFree(query); cudaFree(best_g); cudaFree(best_c);
    printf("\nOK\n");
    return 0;
}
