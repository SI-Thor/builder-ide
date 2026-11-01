// lt_fp4_scaleprobe.cu — recover the exact scale-factor layout cuBLASLt expects
// for VEC16_UE4M3 on sm_110, by reading the permutation off a one-hot GEMM.
//
// A (M=128, K=128): A[m][0] = 6*2^-(m%7), all else 0  -> block (m, s=0) has
// amax = 6*2^-(m%7), scale = 2^-(m%7) exactly representable in e4m3, and
// e2m1(6) is exact, so dequant(A[m][0]) = 6*2^-(m%7) EXACTLY when the right
// scale reaches the right row. B likewise over N rows. All-zero blocks get
// scale 1 and code 0 (contribute nothing). D[m][n] = v_m * w_n exactly iff the
// scale layout is right; otherwise the powers of two expose the permutation.
//
// LAYOUT env selects the packing candidate; E expected layout prints as e(m).
// Build: nvcc -arch=sm_110 -O2 -std=c++17 -o build/lt_fp4_scaleprobe scripts/lt_fp4_scaleprobe.cu -lcublasLt

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cuda_fp8.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define CHECK(x) do { cudaError_t e=(x); if(e){printf("CUDA err %s @%d\n",cudaGetErrorString(e),__LINE__);exit(1);} } while(0)
#define CHECKLT(x) do { cublasStatus_t s=(x); if(s){printf("cublasLt status %d @%d\n",(int)s,__LINE__);exit(1);} } while(0)

static uint8_t e4m3_enc_pos(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)(s & 0x7f);
}
static float e4m3_dec(uint8_t b) {
    return __half2float(__nv_cvt_fp8_to_halfraw((__nv_fp8_storage_t)b, __NV_E4M3));
}

// candidate scale layouts for a logical (R, S) scale matrix, R%128==0, S%4==0
// returns the flat index for (r, s)
static long long sf_index(int layout, int64_t R, int64_t S, int64_t r, int64_t s) {
    int64_t a = r / 128, b = (r % 128) / 32, c = r % 32, d = s / 4, e = s % 4;
    int64_t A = R / 128, D = S / 4;
    switch (layout) {
        case 0:  // torchao to_blocked as I first coded it: (a, d, b, c, e)
            return (((a * D + d) * 4 + b) * 32 + c) * 4 + e;
        case 1:  // tile fully row-major: (a, d, (m%128), e)
            return ((a * D + d) * 128 + (b * 32 + c)) * 4 + e;
        case 2:  // e-major inside 32x4 subtile: (a, d, b, e, c)
            return (((a * D + d) * 4 + b) * 4 + e) * 32 + c;
        case 3:  // d outer over a: (d, a, b, c, e)
            return (((d * A + a) * 4 + b) * 32 + c) * 4 + e;
        case 4:  // (a, d, b, e, c) with c as the very outer: c*(A*D*16)...
            return c * (A * D * 16) + (((a * D + d) * 4 + b) * 4 + e);
        case 5:  // plain row-major (R, S)
            return r * S + s;
        default:
            return -1;
    }
}

int main() {
    const int64_t M = 128, N = 128, K = 128;
    int layout = getenv("LAYOUT") ? atoi(getenv("LAYOUT")) : 0;
    int64_t S = K / 16;

    // v_m = 6*2^-(m%7); w_n likewise
    std::vector<float> v(M), w(N);
    for (int64_t i = 0; i < M; ++i) v[i] = 6.0f * powf(2.0f, -(float)(i % 7));
    for (int64_t i = 0; i < N; ++i) w[i] = 6.0f * powf(2.0f, -(float)(i % 5));

    // build packed operands + scale matrices
    std::vector<uint8_t> pa((size_t)M * K / 2, 0), pb((size_t)N * K / 2, 0);
    std::vector<float> sfa((size_t)M * S, 1.0f), sfb((size_t)N * S, 1.0f);
    // row m of A: k=0 -> v[m] (block s=0), others 0 (scale 1)
    for (int64_t m = 0; m < M; ++m) {
        sfa[(size_t)m * S + 0] = e4m3_dec(e4m3_enc_pos(powf(2.0f, -(float)(m % 7))));
        // codes: k=0 -> e2m1(v/scale) = e2m1(6) = 7 (+); all others 0
        pa[(size_t)m * K / 2 + 0] = 7;  // k=0 low nibble = 7
    }
    for (int64_t n = 0; n < N; ++n) {
        sfb[(size_t)n * S + 0] = e4m3_dec(e4m3_enc_pos(powf(2.0f, -(float)(n % 5))));
        pb[(size_t)n * K / 2 + 0] = 7;
    }
    // dequant check values
    std::vector<float> dqv(M), dqw(N);
    for (int64_t m = 0; m < M; ++m) dqv[m] = 6.0f * sfa[(size_t)m * S + 0];
    for (int64_t n = 0; n < N; ++n) dqw[n] = 6.0f * sfb[(size_t)n * S + 0];

    // pack scales per layout
    std::vector<uint8_t> bsa((size_t)M * S, 0), bsb((size_t)N * S, 0);
    for (int64_t r = 0; r < M; ++r)
        for (int64_t s = 0; s < S; ++s)
            bsa[sf_index(layout, M, S, r, s)] = e4m3_enc_pos(sfa[(size_t)r * S + s]);
    for (int64_t r = 0; r < N; ++r)
        for (int64_t s = 0; s < S; ++s)
            bsb[sf_index(layout, N, S, r, s)] = e4m3_enc_pos(sfb[(size_t)r * S + s]);

    void *dA, *dB, *dD, *dsa, *dsb;
    CHECK(cudaMalloc(&dA, pa.size())); CHECK(cudaMalloc(&dB, pb.size()));
    CHECK(cudaMalloc(&dsa, bsa.size())); CHECK(cudaMalloc(&dsb, bsb.size()));
    CHECK(cudaMalloc(&dD, (size_t)M * N * 2));
    CHECK(cudaMemcpy(dA, pa.data(), pa.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dB, pb.data(), pb.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dsa, bsa.data(), bsa.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dsb, bsb.data(), bsb.size(), cudaMemcpyHostToDevice));

    cublasLtHandle_t lt; CHECKLT(cublasLtCreate(&lt));
    void* ws; size_t wss = 256ull << 20; CHECK(cudaMalloc(&ws, wss));

    cublasLtMatmulDesc_t op; CHECKLT(cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F));
    cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA)));
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN)));
    int32_t sm = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &sm, sizeof(sm)));
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &sm, sizeof(sm)));
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dsa, sizeof(dsa)));
    CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dsb, sizeof(dsb)));
    cublasLtMatrixLayout_t la, lb, lc;
    CHECKLT(cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, K, M, K));
    CHECKLT(cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, K, N, K));
    CHECKLT(cublasLtMatrixLayoutCreate(&lc, CUDA_R_16F, M, N, M));
    cublasLtMatmulPreference_t pref; CHECKLT(cublasLtMatmulPreferenceCreate(&pref));
    CHECKLT(cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &wss, sizeof(wss)));
    cublasLtMatmulHeuristicResult_t res[8]; int found = 0;
    CHECKLT(cublasLtMatmulAlgoGetHeuristic(lt, op, la, lb, lc, lc, pref, 8, res, &found));
    if (!found) { printf("no algo\n"); return 1; }
    float alpha = 1.f, beta = 0.f;
    CHECKLT(cublasLtMatmul(lt, op, &alpha, dA, la, dB, lb, &beta, dD, lc, dD, lc, &res[0].algo, ws, wss, 0));
    std::vector<__half> got((size_t)M * N);
    CHECK(cudaMemcpy(got.data(), dD, got.size() * 2, cudaMemcpyDeviceToHost));

    // expected D(m,n) = dqv[m]*dqw[n]. Report the implied scale exponent cuBLAS
    // used for each A row: D(m,0)/dqw[0] vs dqv[m].
    printf("LAYOUT=%d  scale exponent cuBLAS used per A row (0 = correct):\n", layout);
    int wrong = 0;
    printf("  m: e_exp_used - e_expected\n");
    for (int64_t m = 0; m < 24; ++m) {
        double d00 = got[(size_t)m + 0 * M];          // D(m, 0) = dqv[m]*dqw[0]
        double expect = (double)dqv[m] * dqw[0];
        double ratio = expect != 0 ? d00 / expect : 0;
        double lg = ratio > 0 ? log2(ratio) : -99;
        if (fabs(lg) > 0.01) ++wrong;
        printf("  m=%3zd D=%10.5f expect=%10.5f ratio=%8.4f lg2=%6.2f\n",
               (size_t)m, d00, expect, ratio, lg);
    }
    int total_wrong = 0;
    for (int64_t m = 0; m < M; ++m) {
        double d00 = got[(size_t)m + 0 * M];
        double expect = (double)dqv[m] * dqw[0];
        if (fabs(d00 - expect) > 1e-3 * fabs(expect)) ++total_wrong;
    }
    printf("  wrong A rows: %d/%d\n", total_wrong, (int)M);
    return 0;
}
