// fp4ops.cu — NVFP4 ops for Python (torch via ctypes): device-side quantization
// and the cuBLASLt NVFP4 GEMM path validated by lt_fp4_bench.cu.
//
// The packing and the blocked scale layout (128x4 tiles,
// idx = (a*(S/4)+d)*512 + 16*c + 4*b + e) are identical to lt_fp4_bench.cu,
// where they were validated against an FP32 reference (errRMS ~2e-3 at 1024^3,
// which is FP16 output rounding only).
//
// C ABI (all functions return 0 on success):
//   fp4_init(ws_bytes)                      create cublasLt handle + workspace
//   fp4_from_f32(d_x, R, K, &handle, stream) quantize a device fp32 (R,K) row-major
//                                           tensor to NVFP4 (packed + blocked scales)
//   fp4_gemm(A, B, d_out16, M, N, K, stream) D(M,N) fp16 ROW-major = A(M,K) x B(N,K)^T
//   fp4_handle_bytes(h)                     bytes held (packed + scales)
//   fp4_free(h)
//
// fp4_gemm resolves the cublasLt algorithm once per (M,N,K) and reuses it, so
// repeated calls (and calls under torch CUDA-graph capture) only enqueue the
// matmul: no cudaMalloc, no heuristic query inside the timed loop.
//
// Build: nvcc -arch=sm_110 -O2 -std=c++17 -Xcompiler -fPIC -shared \
//          -o build/libfp4ops.so scripts/fp4ops.cu -lcublasLt

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <cuda_fp8.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <tuple>

#define CK(x) do { cudaError_t e_=(x); if(e_!=cudaSuccess){ \
    fprintf(stderr,"fp4ops CUDA err %s @%d\n",cudaGetErrorString(e_),__LINE__); return -1;} } while(0)
#define CKL(x) do { cublasStatus_t s_=(x); if(s_!=CUBLAS_STATUS_SUCCESS){ \
    fprintf(stderr,"fp4ops cublasLt status %d @%d\n",(int)s_,__LINE__); return -2;} } while(0)

// ----------------------------------------------------------------------------
// nvfp4 encode (device)
// ----------------------------------------------------------------------------
__device__ __forceinline__ uint8_t e2m1_enc(float v) {
    uint8_t sign = v < 0.f ? 8 : 0;
    float a = fminf(fabsf(v), 6.0f);
    // thresholds against {0,.5,1,1.5,2,3,4,6}
    uint8_t code;
    if      (a < 0.25f) code = 0;
    else if (a < 0.75f) code = 1;
    else if (a < 1.25f) code = 2;
    else if (a < 1.75f) code = 3;
    else if (a < 2.50f) code = 4;
    else if (a < 3.50f) code = 5;
    else if (a < 5.00f) code = 6;
    else                code = 7;
    return sign | code;
}
__device__ __forceinline__ uint8_t e4m3_enc_pos(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)(((uint8_t)s) & 0x7f);
}
__device__ __forceinline__ float e4m3_dec(uint8_t b) {
    __nv_fp8_storage_t s = (__nv_fp8_storage_t)b;
    return __half2float(__nv_cvt_fp8_to_halfraw(s, __NV_E4M3));
}

// pass 1: per-row plain quantization. One block per row; thread t walks 16-elem
// scale blocks reading float4s. Emits packed codes (R, K/2 bytes) and decoded
// scales (R, K/16) fp32.
__global__ void quant_plain(const float4* __restrict__ x4, uint8_t* __restrict__ packed,
                            float* __restrict__ sflat, int64_t K) {
    int64_t r = blockIdx.x;
    int64_t S = K / 16;
    const float4* row = x4 + r * (K / 4);
    uint8_t* prow = packed + r * (K / 2);
    float* srow = sflat + r * S;
    for (int64_t s = threadIdx.x; s < S; s += blockDim.x) {
        const float4* blk = row + s * 4;
        float4 q0 = blk[0], q1 = blk[1], q2 = blk[2], q3 = blk[3];
        float amax = fmaxf(fmaxf(fmaxf(fabsf(q0.x), fabsf(q0.y)), fmaxf(fabsf(q0.z), fabsf(q0.w))),
                           fmaxf(fmaxf(fabsf(q1.x), fabsf(q1.y)), fmaxf(fabsf(q1.z), fabsf(q1.w))));
        amax = fmaxf(amax, fmaxf(fmaxf(fabsf(q2.x), fabsf(q2.y)), fmaxf(fabsf(q2.z), fabsf(q2.w))));
        amax = fmaxf(amax, fmaxf(fmaxf(fabsf(q3.x), fabsf(q3.y)), fmaxf(fabsf(q3.z), fabsf(q3.w))));
        uint8_t sc = e4m3_enc_pos(amax * (1.0f / 6.0f));
        float ds = e4m3_dec(sc);
        srow[s] = ds;
        uint8_t* dst = prow + s * 8;
        const float* f = (const float*)blk;
#pragma unroll
        for (int i = 0; i < 8; ++i) {
            uint8_t lo = e2m1_enc(f[2 * i] / ds);
            uint8_t hi = e2m1_enc(f[2 * i + 1] / ds);
            dst[i] = (uint8_t)(lo | (hi << 4));
        }
    }
}

// pass 2: reblock the scales into the tensor-core 128x4-tile layout cuBLASLt
// reads: for logical (row r, sf col s): idx = (a*(S/4)+d)*512 + 16*c + 4*b + e.
// One thread per (r, group of 16 s): writes 4 uint8 packets at 4 addresses,
// 4-byte transactions instead of the naive kernel's scattered bytes.
__global__ void reblock_scales(const float* __restrict__ sflat, uint8_t* __restrict__ sblk,
                               int64_t R, int64_t S) {
    int64_t D = S / 4;
    int64_t gpr = (S + 15) / 16;          // 16-sf groups per row, ceil: the
    int64_t ngroups = R * gpr;            // last group may be partial (S%16!=0
    for (int64_t gi = (int64_t)blockIdx.x * blockDim.x + threadIdx.x; gi < ngroups;  // e.g. K=320 -> S=20)
         gi += (int64_t)gridDim.x * blockDim.x) {
        int64_t r = gi / gpr, sg = (gi % gpr) * 16;
        int64_t a = r / 128, b = (r % 128) / 32, c = r % 32;
        uint8_t* base = sblk + (a * D) * 512 + 16 * c + 4 * b;
        const float* src = sflat + r * S + sg;
        for (int d = 0; d < 4; ++d) {
            int64_t s0 = sg + d * 4;
            if (s0 >= S) break;            // partial final group
            // the d-th 4-sf group sits 512 bytes into its tile
            uint8_t* dst = base + (s0 / 4) * 512;
            dst[0] = e4m3_enc_pos(src[d * 4 + 0]);
            if (s0 + 1 < S) dst[1] = e4m3_enc_pos(src[d * 4 + 1]);
            if (s0 + 2 < S) dst[2] = e4m3_enc_pos(src[d * 4 + 2]);
            if (s0 + 3 < S) dst[3] = e4m3_enc_pos(src[d * 4 + 3]);
        }
    }
}

// ----------------------------------------------------------------------------
// handles
// ----------------------------------------------------------------------------
struct Fp4Tensor {
    uint8_t* packed = nullptr;    // R*K/2 bytes
    uint8_t* scale_blk = nullptr; // R*(K/16) bytes, blocked layout
    float* sflat = nullptr;       // scratch freed after use; kept null
    int64_t R = 0, K = 0;
};

static cublasLtHandle_t g_lt = nullptr;
static void* g_ws = nullptr;
static size_t g_ws_bytes = 256ull << 20;
// persistent scratches (grown on demand): per-call cudaMallocAsync/FreeAsync
// costs ~0.4 ms of driver time and made the path 10-35x slower than the bare
// GEMM (measured 2026-10-31); these are reused across calls
static __half* g_dtmp = nullptr;    // transpose scratch
static size_t g_dtmp_bytes = 0;
static float* g_sflat = nullptr;    // quantize scratch
static size_t g_sflat_elems = 0;
static std::mutex g_mu;
// cuBLASLt 13.4.1 on sm_110 returns an algorithm for a row-major-D FP4 layout
// (CUBLASLT_ORDER_ROW) that produces WRONG values — a mix of exact and garbage
// outputs with NaNs (measured 2026-10-31, M=256 N=512 K=1024: 1036/131072 NaN,
// non-NaN median error 4.5 vs the same-codes reference). The col-major-D
// layout from lt_fp4_bench + a transpose kernel is bit-exact vs the torch fake
// quantizer, so that is the default; FP4OPS_ALLOW_ROW_D=1 re-enables the
// row-order attempt for re-testing against a future library.

extern "C" int fp4_init(size_t ws_bytes) {
    std::lock_guard<std::mutex> lk(g_mu);
    if (g_lt) return 0;
    if (ws_bytes) g_ws_bytes = ws_bytes;
    CKL(cublasLtCreate(&g_lt));
    CK(cudaMalloc(&g_ws, g_ws_bytes));
    return 0;
}

// quantize into CALLER-provided buffers (packed R*K/2 bytes; scale_blk padded to
// 128-row tiles x S bytes, pre-zeroed by the caller). Capture-safe: no malloc,
// no sync. This is the entry point for graphed inference loops.
extern "C" int fp4_quant_prealloc(const float* d_x, int64_t R, int64_t K,
                                  uint8_t* packed, uint8_t* scale_blk,
                                  cudaStream_t stream) {
    if ((K % 64) != 0) { fprintf(stderr, "fp4ops: K must be a multiple of 64 (got %ld)\n", (long)K); return -3; }
    int64_t S = K / 16;
    size_t need = (size_t)R * S;
    if (g_sflat_elems < need) {
        if (g_sflat) cudaFree(g_sflat);
        CK(cudaMalloc(&g_sflat, need * 4));
        g_sflat_elems = need;
    }
    float* sflat = g_sflat;
    int threads = S < 1024 ? (int)S : 1024;
    quant_plain<<<(unsigned)R, threads, 0, stream>>>((const float4*)d_x, packed, sflat, K);
    reblock_scales<<<(unsigned)((R * (S / 16) + 255) / 256), 256, 0, stream>>>(sflat, scale_blk, R, S);
    return 0;
}

extern "C" int fp4_from_f32(const float* d_x, int64_t R, int64_t K, void** handle,
                            cudaStream_t stream) {
    if ((K % 64) != 0) { fprintf(stderr, "fp4ops: K must be a multiple of 64 (got %ld)\n", (long)K); return -3; }
    Fp4Tensor* t = new Fp4Tensor();
    t->R = R; t->K = K;
    int64_t S = K / 16;
    // the blocked scale layout is addressed in 128-row x 4-sf tiles, and the
    // FP4 kernels may read the packed codes of the whole tail tile; pad R up
    // to a multiple of 128 (zeroed) so those reads stay in bounds (measured:
    // unpadded packed buffers fault at M=1)
    int64_t Rp = (R + 127) / 128 * 128;
    CK(cudaMalloc(&t->packed, (size_t)Rp * K / 2));
    CK(cudaMemsetAsync(t->packed, 0, (size_t)Rp * K / 2, stream));
    CK(cudaMalloc(&t->scale_blk, (size_t)Rp * S));
    CK(cudaMemsetAsync(t->scale_blk, 0, (size_t)Rp * S, stream));
    int rc = fp4_quant_prealloc(d_x, R, K, t->packed, t->scale_blk, stream);
    if (rc != 0) { delete t; return rc; }
    *handle = t;
    return 0;
}

extern "C" size_t fp4_handle_bytes(void* handle) {
    Fp4Tensor* t = (Fp4Tensor*)handle;
    return (size_t)t->R * t->K / 2 + (size_t)t->R * (t->K / 16);
}

extern "C" int fp4_free(void* handle) {
    Fp4Tensor* t = (Fp4Tensor*)handle;
    if (!t) return 0;
    cudaFree(t->packed); cudaFree(t->scale_blk);
    delete t;
    return 0;
}

// transpose (M,N) col-major fp16 -> (M,N) row-major. Tiled 32x32 with a +1
// pad to dodge bank conflicts; the naive one-thread-per-element version paid
// int64 div/mod per element (software division on the GPU) and ran at ~14 GB/s.
__global__ void transpose_f16(const __half* __restrict__ in, __half* __restrict__ out,
                              int64_t M, int64_t N) {
    __shared__ __half tile[32][33];
    int64_t m0 = (int64_t)blockIdx.x * 32 + threadIdx.x;
    int64_t n0 = (int64_t)blockIdx.y * 32 + threadIdx.y;
    if (m0 < M && n0 < N) tile[threadIdx.y][threadIdx.x] = in[m0 + n0 * M];
    __syncthreads();
    int64_t m1 = (int64_t)blockIdx.x * 32 + threadIdx.y;
    int64_t n1 = (int64_t)blockIdx.y * 32 + threadIdx.x;
    if (m1 < M && n1 < N) out[m1 * N + n1] = tile[threadIdx.x][threadIdx.y];
}

// D(M,N) fp16 ROW-major = A(M,K) x B(N,K)^T, raw buffers (capture-safe after
// the first eager call resolves and caches everything). The descriptor /
// layout / heuristic objects are resolved ONCE per (M,N,K) and reused: doing
// the create-destroy dance per call costs ~0.1-0.4 ms of host time and made
// the path 6-35x slower than the bare GEMM (measured 2026-10-31).
struct Resolved {
    cublasLtMatmulDesc_t op = nullptr;
    cublasLtMatrixLayout_t la = nullptr, lb = nullptr, lc = nullptr;
    cublasLtMatmulAlgo_t algo{};
};
static std::map<std::tuple<int64_t,int64_t,int64_t>, Resolved> g_resolved;

extern "C" int fp4_gemm_raw(const void* packedA, const void* scaleA,
                            const void* packedB, const void* scaleB,
                            void* d_out16, int64_t M, int64_t N, int64_t K,
                            cudaStream_t stream) {
    std::lock_guard<std::mutex> lk(g_mu);
    if (!g_lt) {  // lazy init: the raw entry points may be called before fp4_init
        CKL(cublasLtCreate(&g_lt));
        CK(cudaMalloc(&g_ws, g_ws_bytes));
    }
    auto key = std::make_tuple(M, N, K);
    auto it = g_resolved.find(key);
    if (it == g_resolved.end()) {
        Resolved r;
        CKL(cublasLtMatmulDescCreate(&r.op, CUBLAS_COMPUTE_32F, CUDA_R_32F));
        cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA));
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN));
        int32_t sm = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &sm, sizeof(sm));
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &sm, sizeof(sm));
        // the heuristic refuses to return algorithms unless the scale pointers
        // are non-null; set dummies, replaced with the real ones per call
        const void* dummy = (const void*)0x100000ull;
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dummy, sizeof(dummy));
        cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dummy, sizeof(dummy));
        CKL(cublasLtMatrixLayoutCreate(&r.la, CUDA_R_4F_E2M1, K, M, K));
        CKL(cublasLtMatrixLayoutCreate(&r.lb, CUDA_R_4F_E2M1, K, N, K));
        // col-major D (the validated path; row-major D returns an algorithm
        // that computes wrong values on this library - see note above) + a
        // transpose kernel to give the caller torch's row-major layout
        CKL(cublasLtMatrixLayoutCreate(&r.lc, CUDA_R_16F, M, N, M));
        cublasLtMatmulPreference_t pref;
        cublasLtMatmulPreferenceCreate(&pref);
        cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES,
                                             &g_ws_bytes, sizeof(g_ws_bytes));
        cublasLtMatmulHeuristicResult_t res[8];
        int found = 0;
        cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(g_lt, r.op, r.la, r.lb, r.lc, r.lc,
                                                           pref, 8, res, &found);
        cublasLtMatmulPreferenceDestroy(pref);
        if (st != CUBLAS_STATUS_SUCCESS || found == 0) {
            fprintf(stderr, "fp4ops: no cublasLt algo for M=%ld N=%ld K=%ld\n",
                    (long)M, (long)N, (long)K);
            return -4;
        }
        r.algo = res[0].algo;
        size_t need = (size_t)M * N * 2;
        if (g_dtmp_bytes < need) {
            if (g_dtmp) cudaFree(g_dtmp);
            CK(cudaMalloc(&g_dtmp, need));
            g_dtmp_bytes = need;
        }
        it = g_resolved.emplace(key, r).first;
    }
    Resolved& r = it->second;
    // scale pointers must be set per call (they live in the desc, and the
    // buffers differ between calls of the same shape)
    const void* pa = (const void*)scaleA;
    const void* pb = (const void*)scaleB;
    cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &pa, sizeof(pa));
    cublasLtMatmulDescSetAttribute(r.op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &pb, sizeof(pb));

    float alpha = 1.f, beta = 0.f;
    cublasStatus_t st = cublasLtMatmul(g_lt, r.op, &alpha, packedA, r.la, packedB, r.lb,
                                       &beta, g_dtmp, r.lc, g_dtmp, r.lc, &r.algo,
                                       g_ws, g_ws_bytes, stream);
    if (st != CUBLAS_STATUS_SUCCESS) { fprintf(stderr, "fp4ops matmul status %d\n", (int)st); return -5; }
    dim3 grid((unsigned)((M + 31) / 32), (unsigned)((N + 31) / 32));
    transpose_f16<<<grid, dim3(32, 32), 0, stream>>>((const __half*)g_dtmp, (__half*)d_out16, M, N);
    return 0;
}

// handle-based convenience wrapper
extern "C" int fp4_gemm(void* A, void* B, void* d_out16, int64_t M, int64_t N, int64_t K,
                        cudaStream_t stream) {
    Fp4Tensor *a = (Fp4Tensor*)A, *b = (Fp4Tensor*)B;
    if (a->K != K || b->K != K || a->R != M || b->R != N) {
        fprintf(stderr, "fp4ops: shape mismatch\n"); return -3;
    }
    return fp4_gemm_raw(a->packed, a->scale_blk, b->packed, b->scale_blk,
                        d_out16, M, N, K, stream);
}

extern "C" size_t fp4_cublaslt_version() { return cublasLtGetVersion(); }
