// cutlass_sm110_mxfp8xfp4.cu — the mixed-operand block-scaled GEMM cuBLASLt
// refuses on this box: MXFP8 activations x MXFP4 weights (kind::mxf8f6f4),
// which cute/arch/config.hpp enables for SM110A on the Thor.
//
// Motivation (BRIEF addendum): FP4 weights x FP8 activations sidesteps
// quantizing activations all the way to FP4. cuBLASLt 13.4.1 rejects every
// mixed FP8/FP4/BF16 x FP4 scale combination (measured in
// results/lt-heuristic-8192.txt); CUTLASS's mxf8f6f4 tcgen05 path may not.
//
// Layout follows example 72c (mixed mxfp8 x mxfp4):
//   A (M,K) row-major, e4m3 packed 1/byte, UE8M0 scale per 32 elements
//   B (N,K) row-major-as-colmajor(K,N), e2m1 packed 2/byte, UE8M0 scale per 32
//   D (M,N) row-major BF16
// Scale block layout: same 128x4 tile atom as NVFP4 (Blk_MN=128, Blk_SF=4 in
// sm100_blockscaled_layout.hpp) with S = K/32 columns — idx formula
// (a*(S/4)+d)*512 + 16*c + 4*b + e carries over with the vec-32 stride.
//
// Correctness: FP32 host reference computed from the SAME codes and UE8M0
// scales (so the check isolates tensor-core arithmetic, not quantization).
//
// Build: nvcc -arch=sm_110a -O2 -std=c++17 --expt-relaxed-constexpr \
//   -Ivendor/cutlass/include -Ivendor/cutlass/tools/util/include \
//   -o build/cutlass_sm110_mxfp8xfp4 scripts/cutlass_sm110_mxfp8xfp4.cu
//
// Usage: cutlass_sm110_mxfp8xfp4 [M N K] [iters]

#include <cuda_runtime.h>
#include <cuda_fp8.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
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
// packing: e4m3 (A) and e2m1 (B) with UE8M0 per-32 scales
// ----------------------------------------------------------------------------
static uint8_t e2m1_enc(float v) {
    uint8_t sign = v < 0 ? 8 : 0; float a = fabsf(v);
    if (a >= 5.0f) return sign | 7;
    if (a >= 3.5f) return sign | 6;
    if (a >= 2.5f) return sign | 5;
    if (a >= 1.75f) return sign | 4;
    if (a >= 1.25f) return sign | 3;
    if (a >= 0.75f) return sign | 2;
    if (a >= 0.25f) return sign | 1;
    return sign;
}
static float e2m1_dec(uint8_t c) {
    static const float t[8] = {0, .5f, 1, 1.5f, 2, 3, 4, 6};
    float v = t[c & 7]; return (c & 8) ? -v : v;
}
static uint8_t e4m3_enc(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)s;
}
static float e4m3_dec(uint8_t b) {
    __nv_fp8_storage_t s = (__nv_fp8_storage_t)b;
    return __half2float(__nv_cvt_fp8_to_halfraw(s, __NV_E4M3));
}
// UE8M0: value = 2^(code-127), round-to-nearest-power-of-2
static uint8_t ue8m0_enc(float v) {
    if (v <= 0) return 0;
    int e; frexpf(v, &e);           // v = m * 2^e, m in [0.5,1)
    float lo = ldexpf(1.f, e - 1);  // 2^(e-1) <= v < 2^e
    float hi = ldexpf(1.f, e);
    int code = (v - lo < hi - v) ? (e - 1) : e;
    if (code < -127) code = -127;
    if (code > 127) code = 127;
    return (uint8_t)(code + 127);
}
static float ue8m0_dec(uint8_t b) { return ldexpf(1.f, (int)b - 127); }

static void pack_scales_ue8m0(const std::vector<float>& plain, int64_t R, int64_t S,
                              std::vector<uint8_t>& out) {
    out.assign((size_t)R * S, 0);
    int64_t D = S / 4;
    for (int64_t r = 0; r < R; ++r)
        for (int64_t s = 0; s < S; ++s) {
            int64_t a = r / 128, b = (r % 128) / 32, c = r % 32;
            int64_t d = s / 4, e = s % 4;
            out[(a * D + d) * 512 + 16 * c + 4 * b + e] = ue8m0_enc(plain[(size_t)r * S + s]);
        }
}

// ----------------------------------------------------------------------------
// kernel config (mirrors examples/72c, cluster shrunk to 1x1 for the first
// sm_110a bring-up)
// ----------------------------------------------------------------------------
using ElementA = cutlass::mx_float8_t<cutlass::float_e4m3_t>;
using ElementB = cutlass::mx_float4_t<cutlass::float_e2m1_t>;
using ElementD = cutlass::bfloat16_t;
using ElementC = cutlass::bfloat16_t;
using ElementAcc = float;
using ArchTag = cutlass::arch::Sm100;   // compiled for sm_110a; see config.hpp gates
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
    ElementA, cutlass::layout::RowMajor, 16,
    ElementB, cutlass::layout::ColumnMajor, 128,
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

int main(int argc, char** argv) {
    int64_t M = argc > 3 ? atoll(argv[1]) : 8192;
    int64_t N = argc > 4 ? atoll(argv[2]) : 8192;
    int64_t K = argc > 5 ? atoll(argv[3]) : 8192;
    int iters = argc > 6 ? atoi(argv[6]) : 10;

    printf("CUTLASS %d.%d.%d mixed mxfp8 x mxfp4  M=%ld N=%ld K=%ld\n",
           CUTLASS_MAJOR, CUTLASS_MINOR, CUTLASS_PATCH, (long)M, (long)N, (long)K);

    srand(1234);
    // A: fp8 codes + per-32 scales; B: fp4 codes + per-32 scales
    std::vector<uint8_t> hA((size_t)M * K), hB((size_t)N * K / 2);
    std::vector<float> sAv((size_t)M * (K / 32)), sBv((size_t)N * (K / 32));
    // FP32 dequantized copies for the host reference
    std::vector<float> dA((size_t)M * K), dB((size_t)N * K);

    for (int64_t r = 0; r < M; ++r) {
        for (int64_t s = 0; s < K / 32; ++s) {
            float sc = ldexpf(1.f, (rand() % 17) - 8);        // 2^-8..2^8
            uint8_t scb = ue8m0_enc(sc);
            sAv[(size_t)r * (K / 32) + s] = ue8m0_dec(scb);
            for (int i = 0; i < 32; ++i) {
                float v = (rand() % 2000 - 1000) / 1000.f;    // in [-1,1]
                uint8_t code = e4m3_enc(v * 448.f / 448.f);   // e4m3 covers [-1,1] well
                hA[(size_t)r * K + s * 32 + i] = code;
                dA[(size_t)r * K + s * 32 + i] = e4m3_dec(code) * ue8m0_dec(scb);
            }
        }
    }
    for (int64_t r = 0; r < N; ++r) {
        for (int64_t s = 0; s < K / 32; ++s) {
            float sc = ldexpf(1.f, (rand() % 17) - 8);
            uint8_t scb = ue8m0_enc(sc);
            sBv[(size_t)r * (K / 32) + s] = ue8m0_dec(scb);
            for (int i = 0; i < 32; i += 2) {
                float lo = (rand() % 2000 - 1000) / 1000.f;
                float hi = (rand() % 2000 - 1000) / 1000.f;
                // data in [-1,1]: e2m1 codes 0..4; the block magnitude rides the
                // UE8M0 scale (this is how MX quantizers use the format)
                uint8_t clo = e2m1_enc(lo), chi = e2m1_enc(hi);
                hB[(size_t)r * (K / 2) + s * 16 + i / 2] = (uint8_t)(clo | (chi << 4));
                dB[(size_t)r * K + s * 32 + i] = e2m1_dec(clo) * ue8m0_dec(scb);
                dB[(size_t)r * K + s * 32 + i + 1] = e2m1_dec(chi) * ue8m0_dec(scb);
            }
        }
    }
    std::vector<uint8_t> bSA, bSB;
    pack_scales_ue8m0(sAv, M, K / 32, bSA);
    pack_scales_ue8m0(sBv, N, K / 32, bSB);

    uint8_t *dA_, *dB_, *dSA, *dSB;
    cutlass::bfloat16_t* dD;
    cudaMalloc(&dA_, hA.size()); cudaMalloc(&dB_, hB.size());
    cudaMalloc(&dSA, bSA.size()); cudaMalloc(&dSB, bSB.size());
    cudaMalloc(&dD, (size_t)M * N * 2);
    cudaMemcpy(dA_, hA.data(), hA.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dB_, hB.data(), hB.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dSA, bSA.data(), bSA.size(), cudaMemcpyHostToDevice);
    cudaMemcpy(dSB, bSB.data(), bSB.size(), cudaMemcpyHostToDevice);
    cudaMemset(dD, 0, (size_t)M * N * 2);

    StrideA stA = cutlass::make_cute_packed_stride(StrideA{}, {int(M), int(K), 1});
    StrideB stB = cutlass::make_cute_packed_stride(StrideB{}, {int(N), int(K), 1});
    StrideC stC = cutlass::make_cute_packed_stride(StrideC{}, {int(M), int(N), 1});
    StrideD stD = cutlass::make_cute_packed_stride(StrideD{}, {int(M), int(N), 1});
    LayoutSFA lSFA = GemmKernel::CollectiveMainloop::Sm1xxBlkScaledConfig::tile_atom_to_shape_SFA(cute::make_shape(int(M), int(N), int(K), 1));
    LayoutSFB lSFB = GemmKernel::CollectiveMainloop::Sm1xxBlkScaledConfig::tile_atom_to_shape_SFB(cute::make_shape(int(M), int(N), int(K), 1));

    typename Gemm::Arguments args{
        cutlass::gemm::GemmUniversalMode::kGemm,
        {int(M), int(N), int(K), 1},
        {
            reinterpret_cast<const cutlass::float_e4m3_t*>(dA_), stA,
            reinterpret_cast<const cutlass::float_e2m1_t*>(dB_), stB,
            reinterpret_cast<const cutlass::float_ue8m0_t*>(dSA), lSFA,
            reinterpret_cast<const cutlass::float_ue8m0_t*>(dSB), lSFB
        },
        {
            {1.0f, 0.0f},
            nullptr, stC,
            dD, stD
        }
    };

    Gemm gemm;
    size_t ws_size = Gemm::get_workspace_size(args);
    void* d_ws = nullptr;
    if (ws_size) cudaMalloc(&d_ws, ws_size);
    cutlass::Status st = gemm.can_implement(args);
    if (st != cutlass::Status::kSuccess) {
        printf("can_implement FAILED: %s\n", cutlassGetStatusString(st)); return 1;
    }
    st = gemm.initialize(args, d_ws);
    if (st != cutlass::Status::kSuccess) { printf("initialize FAILED: %s\n", cutlassGetStatusString(st)); return 1; }
    st = gemm.run();
    if (st != cutlass::Status::kSuccess) { printf("run FAILED: %s\n", cutlassGetStatusString(st)); return 1; }
    cudaError_t err = cudaDeviceSynchronize();
    if (err != cudaSuccess) { printf("kernel error: %s\n", cudaGetErrorString(err)); return 1; }
    printf("kernel ran\n");

    // host FP32 reference from the same codes + scales: D(m,n) = sum_k dA*B
    // (spot-check a window of rows to keep host time sane at 8192^2)
    {
        std::vector<cutlass::bfloat16_t> got(2048);
        int64_t m0 = M / 2, n0 = N / 4;
        cudaMemcpy(got.data(), dD + (size_t)m0 * N + n0, 2048 * 2, cudaMemcpyDeviceToHost);
        double sse = 0, maxe = 0, nrm = 0;
        for (int i = 0; i < 2048; ++i) {
            int64_t n = n0 + i;  if (n >= N) break;
            double acc = 0;
            const float* arow = &dA[(size_t)m0 * K];
            const float* brow = &dB[(size_t)n * K];
            for (int64_t k = 0; k < K; ++k) acc += (double)arow[k] * brow[k];
            double ref = acc, g = float(got[i]);
            double e = fabs(ref - g); sse += e * e; maxe = fmax(maxe, e); nrm += ref * ref;
        }
        printf("vs same-codes FP32 host ref (2048 cols of row m=%ld): relRMS=%.3e maxAbs=%.4e refRMS=%.3f\n",
               (long)m0, sqrt(sse / 2048) / (sqrt(nrm / 2048) + 1e-30), maxe, sqrt(nrm / 2048));
    }

    // timing
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
