// lt_fp4_scalemap.cu — full address map of cuBLASLt's VEC16_UE4M3 scale tensor.
// The scale buffer is (M, S) plain row-major on the host side; we tag one
// 128-byte window at a time with distinct e4m3 codes (all other bytes = 1.0),
// run the one-hot GEMM, and see which output rows pick up which code. The union
// over windows = address(row m, block s) for every m.
//
// Build: nvcc -arch=sm_110 -O2 -std=c++17 -o build/lt_fp4_scalemap scripts/lt_fp4_scalemap.cu -lcublasLt

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cuda_fp8.h>
#include <cstdio>
#include <cstdlib>
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
    const int64_t K = argc > 2 ? atoll(argv[2]) : 128;
    int64_t S = K / 16;
    size_t nsc = (size_t)M * S;
    int nwin = (int)((nsc + 127) / 128);

    std::vector<uint8_t> pa((size_t)M * K / 2, 0), pb((size_t)N * K / 2, 0);
    for (int64_t m = 0; m < M; ++m) pa[(size_t)m * K / 2] = 7;  // k=0 code 7
    for (int64_t n = 0; n < N; ++n) pb[(size_t)n * K / 2] = 7;
    uint8_t one = e4m3_enc_pos(1.f);
    std::vector<uint8_t> sfb((size_t)N * S, one);

    void *dA, *dB, *dD, *dsa, *dsb;
    CHECK(cudaMalloc(&dA, pa.size())); CHECK(cudaMalloc(&dB, pb.size()));
    CHECK(cudaMalloc(&dsa, nsc)); CHECK(cudaMalloc(&dsb, sfb.size()));
    CHECK(cudaMalloc(&dD, (size_t)M * N * 2));
    CHECK(cudaMemcpy(dA, pa.data(), pa.size(), cudaMemcpyHostToDevice));
    CHECK(cudaMemcpy(dB, pb.data(), pb.size(), cudaMemcpyHostToDevice));
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
    float alpha = 1.f, beta = 0.f;

    std::vector<int> addr((size_t)M, -1);       // buffer address for (row m, block 0)
    std::vector<__half> got((size_t)M * N);
    std::vector<uint8_t> buf(nsc, one);
    for (int w = 0; w < nwin; ++w) {
        std::fill(buf.begin(), buf.end(), one);
        int base = w * 128;
        for (int i = 0; i < 128 && base + i < (int)nsc; ++i)
            buf[base + i] = (uint8_t)(i + 1);
        CHECK(cudaMemcpy(dsa, buf.data(), nsc, cudaMemcpyHostToDevice));
        CHECKLT(cublasLtMatmul(lt, op, &alpha, dA, la, dB, lb, &beta, dD, lc, dD, lc, &res[0].algo, ws, wss, 0));
        CHECK(cudaMemcpy(got.data(), dD, got.size() * 2, cudaMemcpyDeviceToHost));
        for (int64_t m = 0; m < M; ++m) {
            double d = got[(size_t)m + 0 * M];
            double sc = d / 36.0;
            if (fabs(sc - 1.0) > 1e-3) {  // non-1.0 -> read from this window
                for (int i = 0; i < 128; ++i)
                    if (fabs(e4m3_dec((uint8_t)(i + 1)) - sc) <= 1e-3 * fabs(sc)) {
                        addr[m] = base + i;
                        break;
                    }
            }
        }
    }
    printf("# address(row m, block s=0) in a plain (M,S=%zd) row-major scale buffer\n", (size_t)S);
    for (int64_t m = 0; m < M; ++m) {
        int a = addr[(size_t)m];
        printf("m=%4zd addr=%5d  pos=(row %4d, s %2d)   m%%128=%4zd  m%%128/32=%3zd  m%%32=%3zd\n",
               (size_t)m, a, a >= 0 ? a / (int)S : -1, a >= 0 ? a % (int)S : -1,
               (size_t)(m % 128), (size_t)((m % 128) / 32), (size_t)(m % 32));
    }
    return 0;
}
