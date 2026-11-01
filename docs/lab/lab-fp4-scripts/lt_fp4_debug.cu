// lt_fp4_debug.cu — isolate WHY the nvfp4 GEMM disagrees with the reference.
// Tests three suspects, one at a time, on a 128x128x128 GEMM with a host
// reference: (1) nibble order inside the packed byte, (2) layout ld units
// (elements vs bytes) for CUDA_R_4F_E2M1, (3) the blocked scale layout.
//
// Build: nvcc -arch=sm_110 -O2 -std=c++17 -o build/lt_fp4_debug scripts/lt_fp4_debug.cu -lcublasLt

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cuda_fp8.h>
#include <cstdio>
#include <cstring>
#include <vector>

#define CHECK(x) do { cudaError_t e=(x); if(e){printf("CUDA err %s @%d\n",cudaGetErrorString(e),__LINE__);exit(1);} } while(0)
#define CHECKLT(x) do { cublasStatus_t s=(x); if(s){printf("cublasLt status %d @%d\n",(int)s,__LINE__);exit(1);} } while(0)

static const float kE2M1[8] = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f};
static uint8_t e2m1_enc(float v) {
    uint8_t sign = v < 0 ? 8 : 0; float a = fabsf(v);
    static const float mid[7] = {0.25f, 0.75f, 1.25f, 1.75f, 2.5f, 3.5f, 5.0f};
    uint8_t code = 7;
    for (int i = 6; i >= 0; --i) if (a < mid[i]) code = (uint8_t)i;
    return sign | code;
}
static float e2m1_dec(uint8_t c) { float v = kE2M1[c & 7]; return (c & 8) ? -v : v; }
static uint8_t e4m3_enc_pos(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)(s & 0x7f);
}
static float e4m3_dec(uint8_t b) {
    return __half2float(__nv_cvt_fp8_to_halfraw((__nv_fp8_storage_t)b, __NV_E4M3));
}

// scale layout candidates
enum ScaleLayout { BLOCKED_TOORDER, PLAIN_ROWMAJOR };
static const char* scale_layout_name(ScaleLayout sl) {
    return sl == BLOCKED_TOORDER ? "torchao-blocked(128x4)" : "plain-rowmajor";
}

struct Op {
    int64_t R, K, S;
    std::vector<uint8_t> packed;     // R*K/2
    std::vector<uint8_t> scales;     // R*S bytes in the chosen layout
    std::vector<float> scales_f;     // decoded, plain (R,S) for the reference
};

static void quantize(const std::vector<float>& x, int64_t R, int64_t K, bool hi_first, Op& op, bool force_scale1 = false) {
    op.R = R; op.K = K; op.S = K / 16;
    op.packed.assign((size_t)R * K / 2, 0);
    op.scales_f.assign((size_t)R * op.S, 0.f);
    for (int64_t r = 0; r < R; ++r)
        for (int64_t s = 0; s < op.S; ++s) {
            const float* blk = &x[(size_t)r * K + s * 16];
            float amax = 0; for (int i = 0; i < 16; ++i) amax = fmaxf(amax, fabsf(blk[i]));
            uint8_t sc = e4m3_enc_pos(force_scale1 ? 1.0f : amax / 6.0f);
            float ds = e4m3_dec(sc);
            op.scales_f[(size_t)r * op.S + s] = ds;
            for (int i = 0; i < 16; i += 2) {
                uint8_t lo = e2m1_enc(blk[i] / ds), hi = e2m1_enc(blk[i + 1] / ds);
                uint8_t b = hi_first ? (uint8_t)(lo << 4 | hi) : (uint8_t)(lo | hi << 4);
                op.packed[(size_t)r * K / 2 + s * 8 + i / 2] = b;
            }
        }
}

static void layout_scales(const Op& op, ScaleLayout sl, std::vector<uint8_t>& out) {
    int64_t R = op.R, S = op.S;
    if (sl == PLAIN_ROWMAJOR) {
        out.assign((size_t)R * S, 0);
        for (int64_t r = 0; r < R; ++r)
            for (int64_t s = 0; s < S; ++s)
                out[(size_t)r * S + s] = e4m3_enc_pos(op.scales_f[(size_t)r * S + s]);
    } else {
        out.assign((size_t)R * S, 0);
        for (int64_t r = 0; r < R; ++r)
            for (int64_t s = 0; s < S; ++s) {
                int64_t a = r / 128, b = (r % 128) / 32, c = r % 32, d = s / 4, e = s % 4;
                int64_t idx = (((a * (S / 4) + d) * 4 + b) * 32 + c) * 4 + e;
                out[idx] = e4m3_enc_pos(op.scales_f[(size_t)r * S + s]);
            }
    }
}

int main(int argc, char** argv) {
    const int64_t M = 128, N = 128, K = 128;
    bool hi_first_default = false;
    int variant = argc > 1 ? atoi(argv[1]) : 0;  // 0=elements-ld, 1=bytes-ld

    // data: random in [-1,1]
    std::vector<float> hA((size_t)M * K), hB((size_t)N * K);
    srand(7);
    for (auto& v : hA) v = (rand() % 2000 - 1000) / 1000.f;
    for (auto& v : hB) v = (rand() % 2000 - 1000) / 1000.f;

    bool nib_opts[2] = {false, true};
    ScaleLayout sl_opts[2] = {BLOCKED_TOORDER, PLAIN_ROWMAJOR};
    bool scale1 = getenv("SCALE1") != nullptr;

    cublasLtHandle_t lt; CHECKLT(cublasLtCreate(&lt));
    void* ws; size_t wss = 256ull << 20; CHECK(cudaMalloc(&ws, wss));

    for (int nibi = 0; nibi < 2; ++nibi)
    for (int sli = 0; sli < 2; ++sli) {
        bool hi_first = nib_opts[nibi];
        ScaleLayout sl = sl_opts[sli];
        Op qa, qb;
        quantize(hA, M, K, hi_first, qa, scale1);
        quantize(hB, N, K, hi_first, qb, scale1);
        std::vector<uint8_t> sa, sb;
        layout_scales(qa, sl, sa);
        layout_scales(qb, sl, sb);

        // host reference from the SAME codes
        std::vector<float> dqA((size_t)M * K), dqB((size_t)N * K);
        std::vector<float> ref((size_t)M * N, 0.f);
        for (int64_t r = 0; r < M; ++r)
            for (int64_t k = 0; k < K; ++k) {
                uint8_t byte = qa.packed[(size_t)r * K / 2 + k / 2];
                uint8_t code = hi_first ? ((k % 2) ? (byte & 0xf) : (byte >> 4)) : ((k % 2) ? (byte >> 4) : (byte & 0xf));
                dqA[(size_t)r * K + k] = e2m1_dec(code) * qa.scales_f[(size_t)r * (K / 16) + k / 16];
            }
        for (int64_t r = 0; r < N; ++r)
            for (int64_t k = 0; k < K; ++k) {
                uint8_t byte = qb.packed[(size_t)r * K / 2 + k / 2];
                uint8_t code = hi_first ? ((k % 2) ? (byte & 0xf) : (byte >> 4)) : ((k % 2) ? (byte >> 4) : (byte & 0xf));
                dqB[(size_t)r * K + k] = e2m1_dec(code) * qb.scales_f[(size_t)r * (K / 16) + k / 16];
            }
        for (int64_t m = 0; m < M; ++m)
            for (int64_t n = 0; n < N; ++n) {
                float acc = 0;
                for (int64_t k = 0; k < K; ++k) acc += dqA[(size_t)m * K + k] * dqB[(size_t)n * K + k];
                ref[(size_t)m * N + n] = acc;
            }

        // upload & run cublasLt
        void *dA, *dB, *dD, *dSa, *dSb;
        CHECK(cudaMalloc(&dA, qa.packed.size())); CHECK(cudaMalloc(&dB, qb.packed.size()));
        CHECK(cudaMalloc(&dSa, sa.size())); CHECK(cudaMalloc(&dSb, sb.size()));
        CHECK(cudaMalloc(&dD, (size_t)M * N * 2));
        CHECK(cudaMemcpy(dA, qa.packed.data(), qa.packed.size(), cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(dB, qb.packed.data(), qb.packed.size(), cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(dSa, sa.data(), sa.size(), cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(dSb, sb.data(), sb.size(), cudaMemcpyHostToDevice));

        cublasLtMatmulDesc_t op; CHECKLT(cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F));
        cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA)));
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN)));
        int32_t sm = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &sm, sizeof(sm)));
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &sm, sizeof(sm)));
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dSa, sizeof(dSa)));
        CHECKLT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dSb, sizeof(dSb)));

        cublasLtMatrixLayout_t la, lb, lc;
        if (variant == 0) {
            // ld in ELEMENTS
            CHECKLT(cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, K, M, K));
            CHECKLT(cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, K, N, K));
        } else {
            // ld in BYTES
            CHECKLT(cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, K, M, K / 2));
            CHECKLT(cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, K, N, K / 2));
        }
        CHECKLT(cublasLtMatrixLayoutCreate(&lc, CUDA_R_16F, M, N, M));

        cublasLtMatmulPreference_t pref; CHECKLT(cublasLtMatmulPreferenceCreate(&pref));
        CHECKLT(cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &wss, sizeof(wss)));
        cublasLtMatmulHeuristicResult_t res[8]; int found = 0;
        cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(lt, op, la, lb, lc, lc, pref, 8, res, &found);
        if (st != CUBLAS_STATUS_SUCCESS || found == 0) {
            printf("ld=%s nibble=%s scales=%s : NO ALGO (status %d)\n",
                   variant == 0 ? "elements" : "bytes", hi_first ? "hi-first" : "lo-first",
                   scale_layout_name(sl), (int)st);
            continue;
        }
        float alpha = 1.f, beta = 0.f;
        st = cublasLtMatmul(lt, op, &alpha, dA, la, dB, lb, &beta, dD, lc, dD, lc, &res[0].algo, ws, wss, 0);
        if (st != CUBLAS_STATUS_SUCCESS) {
            printf("ld=%s nibble=%s : MATMUL FAILED %d\n", variant == 0 ? "elements" : "bytes", hi_first ? "hi-first" : "lo-first", (int)st);
            continue;
        }
        std::vector<__half> got((size_t)M * N);
        CHECK(cudaMemcpy(got.data(), dD, got.size() * 2, cudaMemcpyDeviceToHost));
        double sse = 0, maxe = 0; double sse2 = 0;
        for (int64_t m = 0; m < M; ++m)
            for (int64_t n = 0; n < N; ++n) {
                double r = ref[(size_t)m * N + n];
                double g = got[(size_t)m + (size_t)n * M];
                double e = fabs(g - r); sse += e * e; maxe = fmax(maxe, e);
            }
        printf("ld=%-8s nibble=%-9s scales=%-24s s1=%d : errRMS=%8.4e errMax=%8.4f  D[0,0]=%.4f ref=%.4f  D[0,1]=%.4f ref=%.4f\n",
               variant == 0 ? "elements" : "bytes", hi_first ? "hi-first" : "lo-first",
               scale_layout_name(sl), scale1, sqrt(sse / (M * N)), maxe,
               got[0], ref[0], got[(size_t)0 + 1 * M], ref[1]);
        if (getenv("ROW")) {
            printf("  row m=0, n=0..15:\n   got:");
            for (int n = 0; n < 16; ++n) printf(" %7.3f", (double)got[(size_t)0 + (size_t)n * M]);
            printf("\n   ref:");
            for (int n = 0; n < 16; ++n) printf(" %7.3f", ref[(size_t)0 * N + n]);
            printf("\n");
        }
        cudaFree(dA); cudaFree(dB); cudaFree(dD); cudaFree(dSa); cudaFree(dSb);
        cublasLtMatrixLayoutDestroy(la); cublasLtMatrixLayoutDestroy(lb); cublasLtMatrixLayoutDestroy(lc);
        cublasLtMatmulPreferenceDestroy(pref); cublasLtMatmulDescDestroy(op);
    }
    return 0;
}
