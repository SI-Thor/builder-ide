// cutlass_sm110_nvfp4.cu — CUTLASS block-scaled NVFP4 GEMM on sm_110.
//
// CUTLASS 4.4.1 has no sm_110 arch tag or builders, but cute/arch/config.hpp
// already enables the tcgen05 block-scaled MMA atoms (kind::mxf4nvf4,
// cta_group::1) for SM110A/SM110F. This file builds the sm_100 block-scaled
// collective with ArchTag = arch::Sm110 (tag + builder gate patched locally in
// this vendor copy) and runs the same NVFP4 GEMM the cuBLASLt harness measures,
// with a correctness check against the cuBLASLt result on identical packed
// inputs (both should agree to output rounding).
//
// Shape: D(M,N) = A(M,K) x B(K,N), A row-major (K-major), B column-major
// (K-major), D row-major BF16 — the TN convention, matching lt_fp4_bench.
//
// Build: nvcc -arch=sm_110a -O2 -std=c++17 --expt-relaxed-constexpr \
//   -Ivendor/cutlass/include -Ivendor/cutlass/tools/util/include \
//   -o build/cutlass_sm110_nvfp4 scripts/cutlass_sm110_nvfp4.cu -lcublasLt
//
// Usage: cutlass_sm110_nvfp4 [M N K] [iters]

#include <cublasLt.h>
#include <cuda_runtime.h>
#include <cuda_fp8.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "cutlass/cutlass.h"
#include "cutlass/version.h"
#include "cutlass/arch/arch.h"
#include "cutlass/gemm/collective/collective_builder.hpp"
#include "cutlass/epilogue/collective/collective_builder.hpp"
#include "cutlass/gemm/device/gemm_universal_adapter.h"
#include "cutlass/gemm/kernel/gemm_universal.hpp"
#include "cutlass/detail/sm100_blockscaled_layout.hpp"
#include "cutlass/util/packed_stride.hpp"

using namespace cute;

// ----------------------------------------------------------------------------
// NVFP4 packing (same conventions as lt_fp4_bench.cu — validated there)
// ----------------------------------------------------------------------------
static const float kE2M1[8] = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f};
static uint8_t e2m1_enc(float v) {
    uint8_t sign = v < 0 ? 8 : 0; float a = fabsf(v);
    static const float mid[7] = {0.25f, 0.75f, 1.25f, 1.75f, 2.5f, 3.5f, 5.0f};
    uint8_t code = 7;
    for (int i = 6; i >= 0; --i) if (a < mid[i]) code = (uint8_t)i;
    return sign | code;
}
static uint8_t e4m3_enc_pos(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)(s & 0x7f);
}

// pack scales in the layout the tensor cores read: tile (a*(S/4)+d)*512 +
// 16*c + 4*b + e, identical to CUTLASS SfKMajorAtom (validated vs cuBLASLt)
static void pack_scales(const std::vector<float>& plain, int64_t R, int64_t S,
                        std::vector<uint8_t>& out) {
    out.assign((size_t)R * S, 0);
    int64_t D = S / 4;
    for (int64_t r = 0; r < R; ++r)
        for (int64_t s = 0; s < S; ++s) {
            int64_t a = r / 128, b = (r % 128) / 32, c = r % 32;
            int64_t d = s / 4, e = s % 4;
            out[(a * D + d) * 512 + 16 * c + 4 * b + e] = e4m3_enc_pos(plain[(size_t)r * S + s]);
        }
}

// ----------------------------------------------------------------------------
// kernel configuration
// ----------------------------------------------------------------------------
using ElementA = cutlass::nv_float4_t<cutlass::float_e2m1_t>;
using ElementB = cutlass::nv_float4_t<cutlass::float_e2m1_t>;
using ElementD = cutlass::bfloat16_t;
using ElementC = cutlass::bfloat16_t;
using ElementAcc = float;
using ArchTag = cutlass::arch::Sm100;  // builders take Sm100; compiled for sm_110a (the tcgen05 block-scaled atoms are enabled for SM110A in cute/arch/config.hpp)
using OperatorClass = cutlass::arch::OpClassBlockScaledTensorOp;

using MmaTileShape = Shape<_128, _128, _256>;
using ClusterShape = Shape<_1, _1, _1>;

using CollectiveEpilogue = typename cutlass::epilogue::collective::CollectiveBuilder<
    ArchTag, OperatorClass,
    MmaTileShape, ClusterShape,
    cutlass::epilogue::collective::EpilogueTileAuto,
    ElementAcc, ElementAcc,
    ElementC, cutlass::layout::RowMajor, 8,
    ElementD, cutlass::layout::RowMajor, 8,
    cutlass::epilogue::collective::EpilogueScheduleAuto
>::CollectiveOp;

using CollectiveMainloop = typename cutlass::gemm::collective::CollectiveBuilder<
    ArchTag, OperatorClass,
    ElementA, cutlass::layout::RowMajor, 32,
    ElementB, cutlass::layout::ColumnMajor, 32,
    ElementAcc,
    MmaTileShape, ClusterShape,
    cutlass::gemm::collective::StageCountAutoCarveout<static_cast<int>(sizeof(typename CollectiveEpilogue::SharedStorage))>,
    cutlass::gemm::collective::KernelScheduleAuto
>::CollectiveOp;

using GemmKernel = cutlass::gemm::kernel::GemmUniversal<
    Shape<int, int, int, int>,
    CollectiveMainloop,
    CollectiveEpilogue,
    void>;
using Gemm = cutlass::gemm::device::GemmUniversalAdapter<GemmKernel>;

using LayoutSFA = typename GemmKernel::CollectiveMainloop::LayoutSFA;
using LayoutSFB = typename GemmKernel::CollectiveMainloop::LayoutSFB;
using StrideA = typename Gemm::GemmKernel::StrideA;
using StrideB = typename Gemm::GemmKernel::StrideB;
using StrideD = typename Gemm::GemmKernel::StrideD;
using StrideC = typename Gemm::GemmKernel::StrideC;

// ----------------------------------------------------------------------------
// reference: same packed inputs through cuBLASLt (validated in lt_fp4_bench)
// ----------------------------------------------------------------------------
extern "C" cublasStatus_t lt_nvfp4_ref(const void* A, const void* B, const void* SA, const void* SB,
                                       void* D, int64_t M, int64_t N, int64_t K, void* ws, size_t wss);

static bool run_cublaslt_ref(const void* A, const void* B, const void* SA, const void* SB,
                             void* D, int64_t M, int64_t N, int64_t K) {
    cublasLtHandle_t lt;
    if (cublasLtCreate(&lt) != CUBLAS_STATUS_SUCCESS) return false;
    cublasLtMatmulDesc_t op;
    cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F);
    cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA));
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN));
    int32_t sm = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &sm, sizeof(sm));
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &sm, sizeof(sm));
    const void* pa = SA; const void* pb = SB;
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &pa, sizeof(pa));
    cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &pb, sizeof(pb));
    cublasLtMatrixLayout_t la, lb, lc;
    cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, K, M, K);
    cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, K, N, K);
    cublasLtMatrixLayoutCreate(&lc, CUDA_R_16BF, M, N, M);
    cublasLtMatmulPreference_t pref;
    cublasLtMatmulPreferenceCreate(&pref);
    size_t wss = 256ull << 20;
    cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &wss, sizeof(wss));
    cublasLtMatmulHeuristicResult_t res[8]; int found = 0;
    cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(lt, op, la, lb, lc, lc, pref, 8, res, &found);
    void* ws; cudaMalloc(&ws, wss);
    float alpha = 1.f, beta = 0.f;
    // our A/B here are already (M,K)/(K,N) K-major row-major-logical, exactly
    // the buffers cuBLASLt wants in TN
    if (st == CUBLAS_STATUS_SUCCESS && found > 0)
        st = cublasLtMatmul(lt, op, &alpha, A, la, B, lb, &beta, D, lc, D, lc, &res[0].algo, ws, wss, 0);
    cudaFree(ws);
    cublasLtMatmulPreferenceDestroy(pref);
    cublasLtMatrixLayoutDestroy(la); cublasLtMatrixLayoutDestroy(lb); cublasLtMatrixLayoutDestroy(lc);
    cublasLtMatmulDescDestroy(op);
    cublasLtDestroy(lt);
    return st == CUBLAS_STATUS_SUCCESS;
}

int main(int argc, char** argv) {
    int64_t M = argc > 3 ? atoll(argv[1]) : 8192;
    int64_t N = argc > 4 ? atoll(argv[2]) : 8192;
    int64_t K = argc > 5 ? atoll(argv[3]) : 8192;
    int iters = argc > 6 ? atoi(argv[6 - 1]) : 10;
    if (argc > 6) iters = atoi(argv[6]);

    printf("CUTLASS %d.%d.%d  arch=Sm110  M=%ld N=%ld K=%ld\n",
           CUTLASS_MAJOR, CUTLASS_MINOR, CUTLASS_PATCH, (long)M, (long)N, (long)K);

    // host data
    srand(1234);
    std::vector<uint8_t> hA((size_t)M * K / 2), hB((size_t)N * K / 2);
    std::vector<float> sA((size_t)M * K / 16), sB((size_t)N * K / 16);
    for (size_t i = 0; i < hA.size(); ++i) {
        float lo = (rand() % 2000 - 1000) / 1000.f, hi = (rand() % 2000 - 1000) / 1000.f;
        hA[i] = (uint8_t)(e2m1_enc(lo * 6) | (e2m1_enc(hi * 6) << 4));
    }
    for (size_t i = 0; i < hB.size(); ++i) {
        float lo = (rand() % 2000 - 1000) / 1000.f, hi = (rand() % 2000 - 1000) / 1000.f;
        hB[i] = (uint8_t)(e2m1_enc(lo * 6) | (e2m1_enc(hi * 6) << 4));
    }
    for (size_t i = 0; i < sA.size(); ++i) sA[i] = 0.25f * (1.f + (rand() % 8) / 8.f);
    for (size_t i = 0; i < sB.size(); ++i) sB[i] = 0.25f * (1.f + (rand() % 8) / 8.f);
    std::vector<uint8_t> bSA, bSB;
    pack_scales(sA, M, K / 16, bSA);
    pack_scales(sB, N, K / 16, bSB);

    // device buffers
    uint8_t *dA, *dB, *dSA, *dSB;
    cutlass::bfloat16_t* dD;
    cudaMalloc(&dA, hA.size()); cudaMalloc(&dB, hB.size());
    cudaMalloc(&dSA, bSA.size()); cudaMalloc(&dSB, bSB.size());
    cudaMalloc(&dD, (size_t)M * N * 2);
    cudaMemcpy(dA, hA.data(), hA.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dB, hB.data(), hB.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dSA, bSA.data(), bSA.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dSB, bSB.data(), bSB.size(), cudaMemcpyHostToDevice);
    cudaMemset(dD, 0, (size_t)M * N * 2);

    StrideA dA_ = cutlass::make_cute_packed_stride(StrideA{}, {int(M), int(K), 1});
    StrideB dB_ = cutlass::make_cute_packed_stride(StrideB{}, {int(N), int(K), 1});
    StrideC dC_ = cutlass::make_cute_packed_stride(StrideC{}, {int(M), int(N), 1});
    StrideD dD_ = cutlass::make_cute_packed_stride(StrideD{}, {int(M), int(N), 1});
    LayoutSFA lSFA = GemmKernel::CollectiveMainloop::Sm1xxBlkScaledConfig::tile_atom_to_shape_SFA(cute::make_shape(int(M), int(N), int(K), 1));
    LayoutSFB lSFB = GemmKernel::CollectiveMainloop::Sm1xxBlkScaledConfig::tile_atom_to_shape_SFB(cute::make_shape(int(M), int(N), int(K), 1));

    typename Gemm::Arguments args{
        cutlass::gemm::GemmUniversalMode::kGemm,
        {int(M), int(N), int(K), 1},
        { // mainloop
            reinterpret_cast<const cutlass::float_e2m1_t*>(dA), dA_,
            reinterpret_cast<const cutlass::float_e2m1_t*>(dB), dB_,
            reinterpret_cast<const cutlass::float_ue4m3_t*>(dSA), lSFA,
            reinterpret_cast<const cutlass::float_ue4m3_t*>(dSB), lSFB
        },
        { // epilogue
            {1.0f, 0.0f},
            nullptr, dC_,
            dD, dD_
        }
    };

    Gemm gemm;
    size_t ws_size = Gemm::get_workspace_size(args);
    void* d_ws = nullptr;
    if (ws_size) { cudaMalloc(&d_ws, ws_size); }
    cutlass::Status st = gemm.can_implement(args);
    if (st != cutlass::Status::kSuccess) {
        printf("can_implement FAILED: %s\n", cutlassGetStatusString(st));
        return 1;
    }
    st = gemm.initialize(args, d_ws);
    if (st != cutlass::Status::kSuccess) { printf("initialize FAILED: %s\n", cutlassGetStatusString(st)); return 1; }
    st = gemm.run();
    if (st != cutlass::Status::kSuccess) { printf("run FAILED: %s\n", cutlassGetStatusString(st)); return 1; }
    cudaError_t err = cudaDeviceSynchronize();
    if (err != cudaSuccess) { printf("kernel error: %s\n", cudaGetErrorString(err)); return 1; }
    printf("kernel ran\n");

    // correctness: same inputs through cuBLASLt. cuBLASLt's D is col-major
    // (M,N); CUTLASS's is row-major, so index the reference accordingly
    // (row m0 of the output = dRef[m0 + n*M] for n in 0..N)
    cutlass::bfloat16_t* dRef;
    cudaMalloc(&dRef, (size_t)M * N * 2);
    if (!run_cublaslt_ref(dA, dB, dSA, dSB, dRef, M, N, K)) {
        printf("cuBLASLt reference failed\n"); return 1;
    }
    {
        std::vector<cutlass::bfloat16_t> got(2048), refcol(2048);
        int64_t m0 = M / 2, n0 = N / 4;
        cudaMemcpy(got.data(), dD + (size_t)m0 * N + n0, 2048 * 2, cudaMemcpyDeviceToHost);
        // gather D(m0, n0+i) from the col-major reference
        cudaMemcpy2D(refcol.data(), 2, dRef + m0, M * 2, 2, 2048, cudaMemcpyDeviceToHost);
        double sse = 0, maxe = 0, nrm = 0;
        for (int i = 0; i < 2048; ++i) {
            int64_t n = n0 + i;  if (n >= N) break;
            double a = float(got[i]), b = float(refcol[i]);
            double e = fabs(a - b); sse += e * e; maxe = fmax(maxe, e); nrm += b * b;
        }
        printf("vs cuBLASLt (row m=%ld, 2048 cols): relRMS=%.3e maxAbs=%.4e (refRMS=%.3f)\n",
               (long)m0, sqrt(sse / 2048) / (sqrt(nrm / 2048) + 1e-30), maxe, sqrt(nrm / 2048));
    }

    // timing: warm 1.6s then median of rounds
    auto spin = [&](double sec) {
        auto t0 = std::chrono::steady_clock::now();
        while (std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() < sec) gemm.run();
        cudaDeviceSynchronize();
    };
    spin(1.6);
    cudaEvent_t e0, e1; cudaEventCreate(&e0); cudaEventCreate(&e1);
    std::vector<float> ms_list;
    for (int r = 0; r < 5; ++r) {
        cudaDeviceSynchronize();
        cudaEventRecord(e0);
        for (int i = 0; i < iters; ++i) gemm.run();
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        float ms; cudaEventElapsedTime(&ms, e0, e1);
        ms_list.push_back(ms / iters);
    }
    std::sort(ms_list.begin(), ms_list.end());
    double ms = ms_list[ms_list.size() / 2];
    printf("CUTLASS RESULT ms=%.3f tflops=%.1f (M=%ld N=%ld K=%ld)\n",
           ms, 2.0 * M * N * K / (ms * 1e-3) / 1e12, (long)M, (long)N, (long)K);
    return 0;
}
