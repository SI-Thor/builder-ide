// lt_heuristic_probe.cu — does cuBLASLt (CUDA 13.2) return ANY algorithm for
// block-scaled FP4 (NVFP4 / MXFP4) on this sm_110 Thor?
//
// Part 1, addendum: "query cublasLtMatmulAlgoGetHeuristic with the FP4
// block-scaled types and scale modes (VEC16_UE4M3 for NVFP4, VEC32_UE8M0 for
// MXFP4) to see whether any algorithm is returned for sm_110. An empty
// heuristic answers Part 1, step 1 in minutes."
//
// Build:  nvcc -arch=sm_110 -O2 -o build/lt_heuristic_probe scripts/lt_heuristic_probe.cu -lcublasLt
// Run:    ./build/lt_heuristic_probe [M N K]

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#define CHECK_CUBLAS(call)                                                     \
    do {                                                                       \
        cublasStatus_t s_ = (call);                                            \
        if (s_ != CUBLAS_STATUS_SUCCESS) {                                     \
            fprintf(stderr, "cublasLt error %d at %s:%d\n", s_, __FILE__, __LINE__); \
            exit(1);                                                           \
        }                                                                      \
    } while (0)

static const char* dtype_name(cudaDataType_t t) {
    switch (t) {
        case CUDA_R_16BF: return "BF16";
        case CUDA_R_16F:  return "FP16";
        case CUDA_R_32F:  return "FP32";
        case CUDA_R_8F_E4M3: return "FP8e4m3";
        case CUDA_R_8F_E5M2: return "FP8e5m2";
        case CUDA_R_4F_E2M1: return "FP4e2m1";
        default: return "?";
    }
}

static const char* scale_mode_name(cublasLtMatmulMatrixScale_t m) {
    switch (m) {
        case CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F: return "scalar32F";
        case CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3: return "VEC16_UE4M3";
        case CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0: return "VEC32_UE8M0";
        case CUBLASLT_MATMUL_MATRIX_SCALE_OUTER_VEC_32F: return "OUTER_VEC_32F";
        case CUBLASLT_MATMUL_MATRIX_SCALE_VEC128_32F: return "VEC128_32F";
        default: return "?";
    }
}

struct Combo {
    const char* label;
    cudaDataType_t a, b, cd;
    cublasLtMatmulMatrixScale_t a_mode, b_mode;
};

// One heuristic query for a given configuration. Returns #algos found.
static int query(cublasLtHandle_t lt, const Combo& c, int64_t M, int64_t N, int64_t K,
                 cublasOperation_t opA, cublasOperation_t opB,
                 cublasLtMatmulHeuristicResult_t* out) {
    cublasLtMatmulDesc_t op = nullptr;
    CHECK_CUBLAS(cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F));
    CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &opA, sizeof(opA)));
    CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &opB, sizeof(opB)));

    // cuBLASLt requires alpha==1, beta==0 for block-scaled paths; harmless elsewhere.
    int32_t a_mode = (int32_t)c.a_mode, b_mode = (int32_t)c.b_mode;
    if (c.a_mode != CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F)
        CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &a_mode, sizeof(a_mode)));
    if (c.b_mode != CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F)
        CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &b_mode, sizeof(b_mode)));

    // The heuristic dereferences nothing but uses pointer values for alignment:
    // hand it 256B-aligned dummies so alignment is never the reason for a miss.
    // (Scale pointers are only legal for scaled dtypes — FP8/FP4. Setting them on
    // BF16 returns INVALID_VALUE, which is a probe bug, not a library answer.)
    bool a_scaled = (c.a == CUDA_R_4F_E2M1 || c.a == CUDA_R_8F_E4M3 || c.a == CUDA_R_8F_E5M2);
    bool b_scaled = (c.b == CUDA_R_4F_E2M1 || c.b == CUDA_R_8F_E4M3 || c.b == CUDA_R_8F_E5M2);
    void* dummy = (void*)0x100000ull;
    if (a_scaled)
        CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dummy, sizeof(dummy)));
    if (b_scaled)
        CHECK_CUBLAS(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dummy, sizeof(dummy)));

    cublasLtMatrixLayout_t la = nullptr, lb = nullptr, lc = nullptr;
    // Strict cuBLAS col-major convention for D(m,n) = op(A)(m,k) * op(B)(k,n):
    //   opA=N: A stored (m,k) col-major, ld=m   |  opA=T: A stored (k,m) col-major, ld=k
    //   opB=N: B stored (k,n) col-major, ld=k   |  opB=T: B stored (n,k) col-major, ld=n
    // In row-major user terms TN is exactly torch._scaled_mm's requirement:
    // mat1 (m,k) ROW-major == (k,m) col-major, mat2 (k,n) COLUMN-major.
    int64_t la_r = (opA == CUBLAS_OP_N) ? M : K, la_c = (opA == CUBLAS_OP_N) ? K : M;
    int64_t lb_r = (opB == CUBLAS_OP_N) ? K : N, lb_c = (opB == CUBLAS_OP_N) ? N : K;
    CHECK_CUBLAS(cublasLtMatrixLayoutCreate(&la, c.a, la_r, la_c, la_r));
    CHECK_CUBLAS(cublasLtMatrixLayoutCreate(&lb, c.b, lb_r, lb_c, lb_r));
    CHECK_CUBLAS(cublasLtMatrixLayoutCreate(&lc, c.cd, M, N, M));  // D col-major

    cublasLtMatmulPreference_t pref = nullptr;
    CHECK_CUBLAS(cublasLtMatmulPreferenceCreate(&pref));
    size_t ws = 256ull * 1024 * 1024;
    CHECK_CUBLAS(cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &ws, sizeof(ws)));

    int found = 0;
    cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(lt, op, la, lb, lc, lc, pref, 8, out, &found);
    if (st != CUBLAS_STATUS_SUCCESS) found = -(int)st;

    cublasLtMatmulPreferenceDestroy(pref);
    cublasLtMatrixLayoutDestroy(la);
    cublasLtMatrixLayoutDestroy(lb);
    cublasLtMatrixLayoutDestroy(lc);
    cublasLtMatmulDescDestroy(op);
    return found;
}

int main(int argc, char** argv) {
    int64_t M = argc > 3 ? atoll(argv[1]) : 8192;
    int64_t N = argc > 4 ? atoll(argv[2]) : 8192;
    int64_t K = argc > 5 ? atoll(argv[3]) : 8192;

    int dev = 0;
    cudaDeviceProp prop;
    cudaGetDevice(&dev);
    cudaGetDeviceProperties(&prop, dev);
    printf("device=%s cc=%d.%d SMPs=%d CUDA=%d.%d.%d\n", prop.name,
           prop.major, prop.minor, prop.multiProcessorCount,
           CUBLAS_VERSION / 10000, (CUBLAS_VERSION / 100) % 100, CUBLAS_VERSION % 100);
    printf("query size M=%ld N=%ld K=%ld (FP8/FP4 dims are kept identical so the numbers are comparable)\n\n",
           (long)M, (long)N, (long)K);

    cublasLtHandle_t lt;
    CHECK_CUBLAS(cublasLtCreate(&lt));

    std::vector<Combo> combos = {
        // ---- the two FP4 block-scaled formats the brief names ----
        {"NVFP4  FP4xFP4 -> FP16 (VEC16_UE4M3)", CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"NVFP4  FP4xFP4 -> BF16 (VEC16_UE4M3)", CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"NVFP4  FP4xFP4 -> FP32 (VEC16_UE4M3)", CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_32F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"MXFP4  FP4xFP4 -> FP16 (VEC32_UE8M0)", CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0, CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0},
        {"MXFP4  FP4xFP4 -> BF16 (VEC32_UE8M0)", CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0, CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0},
        // ---- addendum: mixed operands (A = activations, B = weights) ----
        {"MIXED  FP8xFP4 -> FP16 (vec16 / vec16)", CUDA_R_8F_E4M3, CUDA_R_4F_E2M1, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"MIXED  FP8xFP4 -> FP16 (scalar / vec16)", CUDA_R_8F_E4M3, CUDA_R_4F_E2M1, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"MIXED  FP8xFP4 -> FP16 (vec32 / vec32)", CUDA_R_8F_E4M3, CUDA_R_4F_E2M1, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0, CUBLASLT_MATMUL_MATRIX_SCALE_VEC32_UE8M0},
        {"MIXED  FP4xFP8 -> FP16 (vec16 / scalar)", CUDA_R_4F_E2M1, CUDA_R_8F_E4M3, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F},
        {"MIXED  BF16xFP4 -> BF16 (none / vec16)", CUDA_R_16BF, CUDA_R_4F_E2M1, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        {"MIXED  FP4xBF16 -> BF16 (vec16 / none)", CUDA_R_4F_E2M1, CUDA_R_16BF, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F},
        // ---- FP8 block-scaled (the nvfp8 analog) ----
        {"FP8bs  FP8xFP8 -> FP16 (vec16/vec16)", CUDA_R_8F_E4M3, CUDA_R_8F_E4M3, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3, CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3},
        // ---- controls: paths known to work (FP8 via torch._scaled_mm; BF16 plain) ----
        {"FP8    FP8xFP8 -> FP16 (scalar32F)", CUDA_R_8F_E4M3, CUDA_R_8F_E4M3, CUDA_R_16F,
         CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F, CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F},
        {"FP8    FP8xFP8 -> BF16 (scalar32F)", CUDA_R_8F_E4M3, CUDA_R_8F_E4M3, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F, CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F},
        {"BF16   BF16xBF16 -> BF16", CUDA_R_16BF, CUDA_R_16BF, CUDA_R_16BF,
         CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F, CUBLASLT_MATMUL_MATRIX_SCALE_SCALAR_32F},
    };

    // cuBLASLt FP4/FP8 tensor-core paths are documented as TN (A col-major with
    // opA=T i.e. logically row-major A, B likewise). We probe both TN and NN.
    struct { const char* name; cublasOperation_t opA, opB; } layouts[] = {
        {"TN", CUBLAS_OP_T, CUBLAS_OP_N},
        {"NN", CUBLAS_OP_N, CUBLAS_OP_N},
        {"TT", CUBLAS_OP_T, CUBLAS_OP_T},
    };

    printf("%-46s %-4s %-8s %s\n", "config", "lay", "algos", "detail");
    for (auto& c : combos) {
        for (auto& lay : layouts) {
            cublasLtMatmulHeuristicResult_t res[8];
            memset(res, 0, sizeof(res));
            int found = query(lt, c, M, N, K, lay.opA, lay.opB, res);
            char detail[128] = "";
            if (found > 0) {
                snprintf(detail, sizeof(detail), "waves=%0.2f ws=%zuMB",
                         res[0].wavesCount, res[0].workspaceSize / (1024 * 1024));
            } else if (found < 0) {
                snprintf(detail, sizeof(detail), "status=%d", -found);
            }
            printf("%-46s %-4s %-8d %s\n", c.label, lay.name, found, detail);
        }
    }

    cublasLtDestroy(lt);
    printf("\n(result rows: algos>0 = at least one cuBLASLt algorithm exists for that exact config on this GPU;\n"
           " 0 = empty heuristic = no algorithm; status<0 = the query itself was rejected)\n");
    return 0;
}
