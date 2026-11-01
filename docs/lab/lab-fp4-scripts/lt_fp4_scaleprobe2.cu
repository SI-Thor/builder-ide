// lt_fp4_scaleprobe2.cu — recover cuBLASLt's expected scale-tensor position for
// each output row: give every A row a DISTINCT e4m3 scale (codes 1..127), B all
// scale 1.0, data one-hot code 7 at k=0. Then D(m,0)/36 = the scale value
// cuBLAS applied to row m = my scale code j, where j is the buffer position (in
// a plain row-major scale buffer) cuBLAS reads for row m. That table IS the
// library's layout. Print it.
//
// Build: nvcc -arch=sm_110 -O2 -std=c++17 -o build/lt_fp4_scaleprobe2 scripts/lt_fp4_scaleprobe2.cu -lcublasLt

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

int main(int argc, char** argv) {
    const int64_t M = argc > 1 ? atoll(argv[1]) : 128;
    const int64_t N = 128;
    const int64_t K = 128;
    int64_t S = K / 16;

    // A row m: scale = e4m3 code (m % 127)+1 (distinct), data: k=0 -> code 7 (value 6)
    // B row n: scale = 1.0 (code for 1.0), data: k=0 -> code 7
    std::vector<uint8_t> pa((size_t)M * K / 2, 0), pb((size_t)N * K / 2, 0);
    std::vector<uint8_t> sfa((size_t)M * S), sfb((size_t)N * S);
    std::vector<float> sfav((size_t)M * S, 1.f);
    for (int64_t m = 0; m < M; ++m) {
        uint8_t code = (uint8_t)((m % 127) + 1);
        sfa[(size_t)m * S + 0] = code;                 // k-block 0
        for (int64_t s = 1; s < S; ++s) sfa[(size_t)m * S + s] = e4m3_enc_pos(1.f);
        sfav[(size_t)m * S + 0] = e4m3_dec(code);
        pa[(size_t)m * K / 2] = 7;                     // k=0 code 7
    }
    uint8_t one = e4m3_enc_pos(1.f);
    for (int64_t n = 0; n < N; ++n) {
        for (int64_t s = 0; s < S; ++s) sfb[(size_t)n * S + s] = one;
        pb[(size_t)n * K / 2] = 7;
    }

    void *dA, *dB, *dD, *dsa, *dsb;
    CHECK(cudaMalloc(&dA, pa.size())); CHECK(cudaMalloc(&dB, pb.size()));
    CHECK(cudaMalloc(&dsa, sfa.size())); CHECK(cudaMalloc(&dsb, sfb.size()));
    CHECK(cudaMalloc(&dD, (size_t)M * N * 2));
    CHECK(cudaMemcpy(dA, pa.data(), pa.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dB, pb.data(), pb.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dsa, sfa.data(), sfa.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dsb, sfb.data(), sfb.size(), cudaMemcpyHostToDevice));

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

    // D(m, 0) = 6 * scale_used(m) * 6 * 1.0  ->  scale_used(m) = D / 36
    // my scale for row j had code (j%127)+1 -> invert
    printf("row m -> buffer position q(m) cuBLAS reads (plain row-major scale buffer):\n");
    for (int64_t m = 0; m < M; ++m) {
        double d = got[(size_t)m + 0 * M];
        double sc = d / 36.0;
        long j = -1;
        for (long cand = 0; cand < 127; ++cand) {
            float v = e4m3_dec((uint8_t)(cand + 1));
            if (fabs((double)v - sc) <= 1e-3 * fabs(v)) { j = cand; break; }
        }
        printf("m=%4zd scale=%10.6f -> q=%4zd   (m%%128=%4zd m/32=%3zd m%%32=%3zd m/128=%zd)\n",
               (size_t)m, sc, j, (size_t)(m % 128), (size_t)((m % 128) / 32), (size_t)(m % 32), (size_t)(m / 128));
    }
    return 0;
}
