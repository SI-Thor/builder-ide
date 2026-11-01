// lt_fp4_bench.cu — the real NVFP4 GEMM path on the Thor's sm_110 tensor cores.
//
// The heuristic probe (lt_heuristic_probe.cu) showed cuBLASLt returns algorithms
// for CUDA_R_4F_E2M1 x CUDA_R_4F_E2M1 with VEC16_UE4M3 scales in TN layout.
// This harness runs that GEMM for real: quantizes host data to NVFP4 (e2m1 +
// one UE4M3 scale per 16 elements, packed in the tcgen05 128x4-tile block
// layout), executes, checks the result against an FP32 reference computed from
// the SAME quantized codes (so the comparison isolates the tensor-core
// arithmetic), and times it against FP8 / BF16 / dequantize-then-BF16 controls
// in the same layouts.
//
// Usage:
//   lt_fp4_bench sweep                       # the standard interleaved sweep
//   lt_fp4_bench one <mode> M N K [iters]    # one config (mode: nvfp4 fp8 bf16 nvfp4dq fp16)
//   lt_fp4_bench limits                      # where does the heuristic stop returning algos
//
// Build: nvcc -arch=sm_110 -O2 -Xcompiler -fopenmp -o build/lt_fp4_bench scripts/lt_fp4_bench.cu -lcublasLt -lcublas

#include <cublasLt.h>
#include <cublas_v2.h>
#include <cuda_runtime.h>
#include <cuda_bf16.h>
#include <cuda_fp8.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

// ----------------------------------------------------------------------------
// error helpers
// ----------------------------------------------------------------------------
#define CHECK_CUDA(x)                                                          \
    do { cudaError_t e_ = (x); if (e_ != cudaSuccess) {                        \
        fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e_), __FILE__, __LINE__); exit(1); } } while (0)

static void lt_check(cublasStatus_t s, const char* what, int line) {
    if (s != CUBLAS_STATUS_SUCCESS) {
        fprintf(stderr, "cublasLt %s -> status %d at line %d\n", what, (int)s, line);
        exit(1);
    }
}
#define CHECK_LT(x) lt_check((x), #x, __LINE__)

// ----------------------------------------------------------------------------
// box-state helpers (rule: the box's state goes beside every number)
// ----------------------------------------------------------------------------
static double read_loadavg() {
    FILE* f = fopen("/proc/loadavg", "r");
    if (!f) return -1;
    double l1 = -1; fscanf(f, "%lf", &l1); fclose(f);
    return l1;
}

static long read_gpu_freq_khz() {
    FILE* f = fopen("/sys/class/devfreq/gpu-gpc-0/cur_freq", "r");
    if (!f) return -1;
    long v = -1; if (fscanf(f, "%ld", &v) != 1) v = -1; fclose(f);
    return v;
}

// VDD_GPU rail: in1_input mV * curr1_input mA -> uW (hwmon6 = ina3221 on this box)
static double read_vdd_gpu_uw() {
    FILE* f1 = fopen("/sys/class/hwmon/hwmon6/in1_input", "r");
    FILE* f2 = fopen("/sys/class/hwmon/hwmon6/curr1_input", "r");
    if (!f1 || !f2) { if (f1) fclose(f1); if (f2) fclose(f2); return -1; }
    long mv = 0, ma = 0;
    if (fscanf(f1, "%ld", &mv) != 1) mv = 0;
    if (fscanf(f2, "%ld", &ma) != 1) ma = 0;
    fclose(f1); fclose(f2);
    return (double)mv * (double)ma;  // uW
}

struct EnergySampler {
    std::atomic<bool> run{false};
    double uj_acc = 0.0;  // written only by the sampler thread, read after join
    std::thread th;
    void start() {
        run = true;
        th = std::thread([this] {
            using clk = std::chrono::steady_clock;
            auto t0 = clk::now();
            double last = read_vdd_gpu_uw();
            while (run.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                auto t1 = clk::now();
                double p = read_vdd_gpu_uw();
                double dt = std::chrono::duration<double>(t1 - t0).count();
                uj_acc += ((last + p) / 2.0) * dt;  // uW * s = uJ
                last = p; t0 = t1;
            }
        });
    }
    double stop_j() {
        run = false;
        if (th.joinable()) th.join();
        return uj_acc / 1e6;  // J
    }
};

// ----------------------------------------------------------------------------
// NVFP4 quantization (host side, deterministic)
// ----------------------------------------------------------------------------
// e2m1 code -> value: codes 0..7 = 0, .5, 1, 1.5, 2, 3, 4, 6 ; bit 3 = sign
static const float kE2M1[8] = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f};

static uint8_t e2m1_encode(float v) {
    // round-to-nearest against {0,.5,1,1.5,2,3,4,6}; ties toward the even code
    uint8_t sign = v < 0 ? 8 : 0;
    float a = fabsf(v);
    // midpoints: .25 .75 1.25 1.75 2.5 3.5 5 ; above 6 clamps to 6 (saturated)
    static const float mid[7] = {0.25f, 0.75f, 1.25f, 1.75f, 2.5f, 3.5f, 5.0f};
    uint8_t code = 7;
    for (int i = 6; i >= 0; --i)
        if (a < mid[i]) code = (uint8_t)i;
    return sign | code;
}

static inline float e2m1_decode(uint8_t code) {
    float v = kE2M1[code & 7];
    return (code & 8) ? -v : v;
}

// float -> e4m3 bits (round-nearest, saturate), sign forced positive for UE4M3
static uint8_t e4m3_encode_pos(float v) {
    __nv_fp8_storage_t s = __nv_cvt_float_to_fp8(v, __NV_SATFINITE, __NV_E4M3);
    return (uint8_t)(s & 0x7f);
}
static float e4m3_decode(uint8_t b) {
    __nv_fp8_storage_t s = (__nv_fp8_storage_t)b;
    return __half2float(__nv_cvt_fp8_to_halfraw(s, __NV_E4M3));
}

// one operand, logical shape (R, K) ROW-major, quantized to NVFP4.
struct Nvfp4Operand {
    int64_t R, K;
    std::vector<uint8_t> packed;        // R * K/2 bytes, 2 codes per byte (low nibble = even k)
    std::vector<uint8_t> scale_blk;     // blocked (128x4 tiles) UE4M3, torchao to_blocked order
    std::vector<float> scale_plain;     // (R, K/16) decoded fp32, for the dequant kernel / reference
};

// The blocked scale layout cuBLASLt actually reads on sm_110, recovered
// empirically by lt_fp4_scalemap.cu (windowed one-hot probe): for logical
// scale entry (row r = a*128 + b*32 + c, sf column s = d*4 + e),
//   index = (a*(S/4) + d)*512 + 16*c + 4*b + e
// i.e. 128-row x 4-sf tiles, and inside a tile the row-within-32-group has
// stride 16, the 32-group has stride 4, the sf index stride 1.
static void block_scales(const std::vector<float>& plain, int64_t R, int64_t S,
                         std::vector<uint8_t>& out) {
    // pad rows to 128-row tensor-core tiles: the library's tail-tile scale
    // reads extend to the tile boundary even when R % 128 != 0 (measured:
    // unpadded buffers give garbage at M=64, padded ones are exact)
    int64_t Rp = (R + 127) / 128 * 128;
    out.assign((size_t)Rp * S, 0);
    int64_t D = S / 4;
    for (int64_t r = 0; r < R; ++r)
        for (int64_t s = 0; s < S; ++s) {
            int64_t a = r / 128, b = (r % 128) / 32, c = r % 32;
            int64_t d = s / 4, e = s % 4;
            int64_t idx = (a * D + d) * 512 + 16 * c + 4 * b + e;
            out[idx] = e4m3_encode_pos(plain[(size_t)r * S + s]);
        }
}

static void quantize_nvfp4(const std::vector<float>& x, int64_t R, int64_t K,
                           Nvfp4Operand& out, float amax_cap = 6.0f) {
    out.R = R; out.K = K;
    int64_t S = K / 16;
    // packed codes are ALSO read out to the 128-row tile boundary (measured:
    // unpadded packed gives garbage at M<=16 even with padded scales)
    int64_t Rp = (R + 127) / 128 * 128;
    out.scale_plain.assign((size_t)R * S, 0.f);
    out.packed.assign((size_t)Rp * K / 2, 0);
    for (int64_t r = 0; r < R; ++r) {
        for (int64_t s = 0; s < S; ++s) {
            const float* blk = &x[(size_t)r * K + s * 16];
            float amax = 0.f;
            for (int i = 0; i < 16; ++i) amax = std::max(amax, fabsf(blk[i]));
            float scale = amax / amax_cap;                 // so |q| <= 6
            uint8_t sc = e4m3_encode_pos(scale);
            float ds = e4m3_decode(sc);
            out.scale_plain[(size_t)r * S + s] = ds;
            for (int i = 0; i < 16; i += 2) {
                uint8_t lo = e2m1_encode(blk[i] / ds);
                uint8_t hi = e2m1_encode(blk[i + 1] / ds);
                out.packed[(size_t)r * K / 2 + s * 8 + i / 2] = (uint8_t)(lo | (hi << 4));
            }
        }
    }
    block_scales(out.scale_plain, R, S, out.scale_blk);
}

// ----------------------------------------------------------------------------
// device dequant kernels: packed nvfp4 (R,K) -> bf16/fp32 (R,K) row-major
// ----------------------------------------------------------------------------
__device__ __forceinline__ float kE2M1d(uint8_t c) {
    const float t[8] = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f};
    float v = t[c & 7];
    return (c & 8) ? -v : v;
}

__global__ void dequant_nvfp4_bf16(const uint8_t* __restrict__ packed,
                                   const float* __restrict__ scales,  // (R, K/16) fp32 (decoded)
                                   __nv_bfloat16* __restrict__ out,
                                   int64_t K) {
    int64_t r = blockIdx.x;
    const uint8_t* row = packed + (size_t)r * (K / 2);
    const float* sc = scales + (size_t)r * (K / 16);
    __nv_bfloat16* o = out + (size_t)r * K;
    for (int64_t k = threadIdx.x; k < K; k += blockDim.x) {
        uint8_t byte = row[k / 2];
        uint8_t code = (k % 2 == 0) ? (byte & 0xf) : (byte >> 4);
        float v = kE2M1d(code);
        o[k] = __float2bfloat16(v * sc[k / 16]);
    }
}

// reference path on device: dequant both operands to fp32 and run cublas SGEMM
__global__ void dequant_nvfp4_f32(const uint8_t* __restrict__ packed,
                                  const float* __restrict__ scales,
                                  float* __restrict__ out, int64_t K) {
    int64_t r = blockIdx.x;
    const uint8_t* row = packed + (size_t)r * (K / 2);
    const float* sc = scales + (size_t)r * (K / 16);
    float* o = out + (size_t)r * K;
    for (int64_t k = threadIdx.x; k < K; k += blockDim.x) {
        uint8_t byte = row[k / 2];
        uint8_t code = (k % 2 == 0) ? (byte & 0xf) : (byte >> 4);
        float v = kE2M1d(code);
        o[k] = v * sc[k / 16];
    }
}

// ----------------------------------------------------------------------------
// cuBLASLt context
// ----------------------------------------------------------------------------
struct LtCtx {
    cublasLtHandle_t lt;
    void* workspace = nullptr;
    size_t ws_size = 256ull << 20;
    LtCtx() {
        CHECK_LT(cublasLtCreate(&lt));
        CHECK_CUDA(cudaMalloc(&workspace, ws_size));
    }
    ~LtCtx() { cublasLtDestroy(lt); cudaFree(workspace); }
};

struct TimingResult {
    double ms_median;
    double tflops;
    double gbps;       // bytes of A+B+D moved per second (weights+acts+out)
    double joules;     // VDD_GPU rail energy per iteration
    double idle_w;
    long freq_khz;
};

// Describe one GEMM problem: D(M,N) col-major = op(A)(M,K) * op(B)(K,N), TN layout:
//   A stored (K,M) col-major ld=K  == activations (M,K) ROW-major
//   B stored (K,N) col-major ld=K  == weights    (N,K) ROW-major viewed as (K,N) col-major
struct GemmCfg {
    int64_t M, N, K;
    cudaDataType_t a, b, cd;
    cublasComputeType_t compute = CUBLAS_COMPUTE_32F;
    cudaDataType_t scale_type = CUDA_R_32F;
    int32_t a_scale_mode = 0, b_scale_mode = 0;
    const void* a_scale_ptr = nullptr;
    const void* b_scale_ptr = nullptr;
};

static bool lt_run(const LtCtx& ctx, const GemmCfg& g, const void* A, const void* B, void* D,
                   cublasLtMatmulAlgo_t* algo_out = nullptr, int* algo_count = nullptr) {
    cublasLtMatmulDesc_t op;
    CHECK_LT(cublasLtMatmulDescCreate(&op, g.compute, g.scale_type));
    cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
    CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA)));
    CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN)));
    if (g.a_scale_ptr) CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &g.a_scale_mode, sizeof(g.a_scale_mode)));
    if (g.b_scale_ptr) CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &g.b_scale_mode, sizeof(g.b_scale_mode)));
    if (g.a_scale_ptr) CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &g.a_scale_ptr, sizeof(g.a_scale_ptr)));
    if (g.b_scale_ptr) CHECK_LT(cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &g.b_scale_ptr, sizeof(g.b_scale_ptr)));

    cublasLtMatrixLayout_t la, lb, lc;
    CHECK_LT(cublasLtMatrixLayoutCreate(&la, g.a, g.K, g.M, g.K));  // ld in ELEMENTS for packed fp4? see fallback
    CHECK_LT(cublasLtMatrixLayoutCreate(&lb, g.b, g.K, g.N, g.K));
    CHECK_LT(cublasLtMatrixLayoutCreate(&lc, g.cd, g.M, g.N, g.M));

    cublasLtMatmulPreference_t pref;
    CHECK_LT(cublasLtMatmulPreferenceCreate(&pref));
    CHECK_LT(cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &ctx.ws_size, sizeof(ctx.ws_size)));

    cublasLtMatmulHeuristicResult_t res[8];
    int found = 0;
    cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(ctx.lt, op, la, lb, lc, lc, pref, 8, res, &found);
    cublasLtMatmulPreferenceDestroy(pref);
    if (st != CUBLAS_STATUS_SUCCESS || found == 0) {
        cublasLtMatrixLayoutDestroy(la); cublasLtMatrixLayoutDestroy(lb);
        cublasLtMatrixLayoutDestroy(lc); cublasLtMatmulDescDestroy(op);
        if (algo_count) *algo_count = found;
        return false;
    }
    if (algo_count) *algo_count = found;

    float alpha = 1.0f, beta = 0.0f;
    st = cublasLtMatmul(ctx.lt, op, &alpha, A, la, B, lb, &beta, D, lc, D, lc,
                        &res[0].algo, ctx.workspace, ctx.ws_size, 0);
    cublasLtMatrixLayoutDestroy(la); cublasLtMatrixLayoutDestroy(lb);
    cublasLtMatrixLayoutDestroy(lc); cublasLtMatmulDescDestroy(op);
    if (st != CUBLAS_STATUS_SUCCESS) {
        fprintf(stderr, "cublasLtMatmul failed with %d\n", (int)st);
        return false;
    }
    if (algo_out) *algo_out = res[0].algo;
    return true;
}

// A version that pre-resolves the algo so the timed loop is just the matmul.
struct ResolvedGemm {
    cublasLtMatmulDesc_t op = nullptr;
    cublasLtMatrixLayout_t la = nullptr, lb = nullptr, lc = nullptr;
    cublasLtMatmulAlgo_t algo{};
    bool ok = false;
    const void* a_scale_ptr = nullptr;  // keep alive: desc holds the pointer value
    const void* b_scale_ptr = nullptr;
};

static bool lt_resolve(const LtCtx& ctx, GemmCfg g, const void* A, const void* B, void* D,
                       ResolvedGemm& rg) {
    cublasLtMatmulDescCreate(&rg.op, g.compute, g.scale_type);
    cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
    cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA));
    cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN));
    if (g.a_scale_ptr) cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &g.a_scale_mode, sizeof(int32_t));
    if (g.b_scale_ptr) cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &g.b_scale_mode, sizeof(int32_t));
    if (g.a_scale_ptr) cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &g.a_scale_ptr, sizeof(void*));
    if (g.b_scale_ptr) cublasLtMatmulDescSetAttribute(rg.op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &g.b_scale_ptr, sizeof(void*));

    cublasLtMatrixLayoutCreate(&rg.la, g.a, g.K, g.M, g.K);
    cublasLtMatrixLayoutCreate(&rg.lb, g.b, g.K, g.N, g.K);
    cublasLtMatrixLayoutCreate(&rg.lc, g.cd, g.M, g.N, g.M);

    cublasLtMatmulPreference_t pref;
    cublasLtMatmulPreferenceCreate(&pref);
    cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &ctx.ws_size, sizeof(size_t));
    cublasLtMatmulHeuristicResult_t res[8];
    int found = 0;
    cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(ctx.lt, rg.op, rg.la, rg.lb, rg.lc, rg.lc, pref, 8, res, &found);
    cublasLtMatmulPreferenceDestroy(pref);
    if (st != CUBLAS_STATUS_SUCCESS || found == 0) return false;
    rg.algo = res[0].algo;

    float alpha = 1.0f, beta = 0.0f;
    st = cublasLtMatmul(ctx.lt, rg.op, &alpha, A, rg.la, B, rg.lb, &beta, D, rg.lc, D, rg.lc,
                        &rg.algo, ctx.workspace, ctx.ws_size, 0);
    if (st != CUBLAS_STATUS_SUCCESS) { fprintf(stderr, "matmul resolve-run failed %d\n", (int)st); return false; }
    rg.ok = true;
    return true;
}

static void lt_exec(const LtCtx& ctx, const ResolvedGemm& rg, const void* A, const void* B, void* D) {
    float alpha = 1.0f, beta = 0.0f;
    CHECK_LT(cublasLtMatmul(ctx.lt, rg.op, &alpha, A, rg.la, B, rg.lb, &beta, D, rg.lc, D, rg.lc,
                            &rg.algo, ctx.workspace, ctx.ws_size, 0));
}

// timed loop: warm >=1.6s (clock ramp rule), then R rounds of I iters, median
static TimingResult time_gemm(const LtCtx& ctx, const ResolvedGemm& rg, const void* A, const void* B, void* D,
                              int64_t M, int64_t N, int64_t K, size_t bytes_moved,
                              int rounds = 5, int iters = 10, void (*pre)(void*) = nullptr, void* pre_arg = nullptr) {
    // clock warm: spin the same GEMM ~1.6 s
    auto warm_until = std::chrono::steady_clock::now() + std::chrono::milliseconds(1600);
    while (std::chrono::steady_clock::now() < warm_until) lt_exec(ctx, rg, A, B, D);
    CHECK_CUDA(cudaDeviceSynchronize());

    double idle_w = read_vdd_gpu_uw() / 1e6;
    EnergySampler es; es.start();

    std::vector<double> ms_list;
    cudaEvent_t e0, e1;
    cudaEventCreate(&e0); cudaEventCreate(&e1);
    for (int r = 0; r < rounds; ++r) {
        CHECK_CUDA(cudaDeviceSynchronize());
        cudaEventRecord(e0);
        for (int i = 0; i < iters; ++i) {
            if (pre) pre(pre_arg);
            lt_exec(ctx, rg, A, B, D);
        }
        cudaEventRecord(e1);
        cudaEventSynchronize(e1);
        float ms = 0; cudaEventElapsedTime(&ms, e0, e1);
        ms_list.push_back(ms / iters);
    }
    cudaEventDestroy(e0); cudaEventDestroy(e1);
    double joules = es.stop_j();

    std::sort(ms_list.begin(), ms_list.end());
    double t_ms = ms_list[ms_list.size() / 2];
    TimingResult tr;
    tr.ms_median = t_ms;
    tr.tflops = 2.0 * M * N * K / (t_ms * 1e-3) / 1e12;
    tr.gbps = bytes_moved / (t_ms * 1e-3) / 1e9;
    tr.joules = joules / ((double)rounds * iters);
    tr.idle_w = idle_w;
    tr.freq_khz = read_gpu_freq_khz();
    return tr;
}

// ----------------------------------------------------------------------------
// one configuration end to end
// ----------------------------------------------------------------------------
struct RunOut {
    bool ok = false;
    std::string why;
    TimingResult tr{};
    double err_rms = -1, err_max = -1;  // vs FP32 reference of the SAME codes
    double fmt_err_rms = -1;            // quantized-vs-original (the format's error)
};

static RunOut run_config(LtCtx& ctx, const char* mode, int64_t M, int64_t N, int64_t K,
                         int rounds = 5, int iters = 10, bool with_ref = true) {
    RunOut out;
    // host data
    std::vector<float> hA((size_t)M * K), hB((size_t)N * K);
    srand(1234);
    auto rf = []() { return (rand() % 2000 - 1000) / 1000.0f; };  // [-1,1]
    for (auto& v : hA) v = rf();
    for (auto& v : hB) v = rf();

    // device buffers
    void *dA = nullptr, *dB = nullptr, *dD = nullptr, *dAs = nullptr, *dBs = nullptr;
    size_t bytes_A = 0, bytes_B = 0, elem_D = (size_t)M * N;

    GemmCfg g; g.M = M; g.N = N; g.K = K;

    if (strcmp(mode, "nvfp4") == 0 || strcmp(mode, "nvfp4dq") == 0) {
        Nvfp4Operand qa, qb;
        quantize_nvfp4(hA, M, K, qa);
        quantize_nvfp4(hB, N, K, qb);
        bytes_A = qa.packed.size(); bytes_B = qb.packed.size();
        CHECK_CUDA(cudaMalloc(&dA, bytes_A)); CHECK_CUDA(cudaMalloc(&dB, bytes_B));
        CHECK_CUDA(cudaMalloc(&dAs, qa.scale_blk.size())); CHECK_CUDA(cudaMalloc(&dBs, qb.scale_blk.size()));
        CHECK_CUDA(cudaMemcpy(dA, qa.packed.data(), bytes_A, cudaMemcpyHostToDevice));
        CHECK_CUDA(cudaMemcpy(dB, qb.packed.data(), bytes_B, cudaMemcpyHostToDevice));
        CHECK_CUDA(cudaMemcpy(dAs, qa.scale_blk.data(), qa.scale_blk.size(), cudaMemcpyHostToDevice));
        CHECK_CUDA(cudaMemcpy(dBs, qb.scale_blk.data(), qb.scale_blk.size(), cudaMemcpyHostToDevice));
        // scale bytes count toward the FP4 path's byte bill
        bytes_A += qa.scale_blk.size(); bytes_B += qb.scale_blk.size();

        g.a = CUDA_R_4F_E2M1; g.b = CUDA_R_4F_E2M1;
        g.a_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
        g.b_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
        g.a_scale_ptr = dAs; g.b_scale_ptr = dBs;

        if (strcmp(mode, "nvfp4") == 0) {
            g.cd = CUDA_R_16F;
            CHECK_CUDA(cudaMalloc(&dD, elem_D * 2));
            ResolvedGemm rg;
            if (!lt_resolve(ctx, g, dA, dB, dD, rg)) { out.why = "no algo / matmul failed"; return out; }
            size_t bytes = bytes_A + bytes_B + elem_D * 2;
            out.tr = time_gemm(ctx, rg, dA, dB, dD, M, N, K, bytes, rounds, iters);
            out.ok = true;
            if (with_ref) {
                // FP32 reference from the same codes
                float *dAf = nullptr, *dBf = nullptr, *dDref = nullptr;
                void *dAp = nullptr, *dBp = nullptr;
                CHECK_CUDA(cudaMalloc(&dAf, (size_t)M * K * 4));
                CHECK_CUDA(cudaMalloc(&dBf, (size_t)N * K * 4));
                CHECK_CUDA(cudaMalloc(&dDref, (size_t)M * N * 4));
                CHECK_CUDA(cudaMalloc(&dAp, (size_t)M * K * 4));
                CHECK_CUDA(cudaMalloc(&dBp, (size_t)N * K * 4));
                CHECK_CUDA(cudaMemcpy(dAp, qa.packed.data(), bytes_A - qa.scale_blk.size(), cudaMemcpyHostToDevice));
                CHECK_CUDA(cudaMemcpy(dBp, qb.packed.data(), bytes_B - qb.scale_blk.size(), cudaMemcpyHostToDevice));
                std::vector<float> scp;  // plain fp32 scales to device
                // reuse qa.scale_plain — copy through a temp device buffer
                float* dAsp; CHECK_CUDA(cudaMalloc(&dAsp, qa.scale_plain.size() * 4));
                float* dBsp; CHECK_CUDA(cudaMalloc(&dBsp, qb.scale_plain.size() * 4));
                CHECK_CUDA(cudaMemcpy(dAsp, qa.scale_plain.data(), qa.scale_plain.size() * 4, cudaMemcpyHostToDevice));
                CHECK_CUDA(cudaMemcpy(dBsp, qb.scale_plain.data(), qb.scale_plain.size() * 4, cudaMemcpyHostToDevice));
                dequant_nvfp4_f32<<<(unsigned)M, 256>>>((const uint8_t*)dAp, dAsp, dAf, K);
                dequant_nvfp4_f32<<<(unsigned)N, 256>>>((const uint8_t*)dBp, dBsp, dBf, K);
                // sgemm: row-major C(M,N) = A(M,K) B(N,K)^T via col-major trick
                cublasHandle_t cb; cublasCreate(&cb);
                float al = 1.f, be = 0.f;
                // col-major: C'(N,M) = B'(N,K) * A'(K,M) with all buffers row-major originals
                cublasSgemm(cb, CUBLAS_OP_T, CUBLAS_OP_N, (int)N, (int)M, (int)K,
                            &al, dBf, (int)K, dAf, (int)K, &be, dDref, (int)N);
                CHECK_CUDA(cudaDeviceSynchronize());
                std::vector<float> ref((size_t)M * N), got((size_t)M * N);
                // dDref is (N,M) col-major = (M,N) row-major ref
                CHECK_CUDA(cudaMemcpy(ref.data(), dDref, ref.size() * 4, cudaMemcpyDeviceToHost));
                std::vector<__half> dh(elem_D);
                CHECK_CUDA(cudaMemcpy(dh.data(), dD, dh.size() * 2, cudaMemcpyDeviceToHost));
                // dD is (M,N) col-major: dD[m + n*M] = out(m,n)
                double sse = 0; double maxe = 0; double sse_fmt = 0;
                for (int64_t n = 0; n < N; ++n)
                    for (int64_t m = 0; m < M; ++m) {
                        double r = ref[(size_t)m * N + n];
                        double gv = __half2float(dh[(size_t)m + (size_t)n * M]);
                        double e = fabs(gv - r); sse += e * e; maxe = std::max(maxe, e);
                    }
                double nn = 0;
                for (auto& v : ref) nn += (double)v * v;
                out.err_rms = sqrt(sse / (double)(M * N));
                out.err_max = maxe;
                out.fmt_err_rms = -2;  // filled by caller against originals if wanted
                cublasDestroy(cb);
                cudaFree(dAf); cudaFree(dBf); cudaFree(dDref); cudaFree(dAp); cudaFree(dBp); cudaFree(dAsp); cudaFree(dBsp);
            }
        } else {
            // nvfp4dq: dequantize both operands to bf16 then a bf16 GEMM, end to end
            g.cd = CUDA_R_16BF;
            g.a = CUDA_R_16BF; g.b = CUDA_R_16BF; g.a_scale_ptr = nullptr; g.b_scale_ptr = nullptr;
            __nv_bfloat16 *dAb = nullptr, *dBb = nullptr;
            CHECK_CUDA(cudaMalloc(&dAb, (size_t)M * K * 2));
            CHECK_CUDA(cudaMalloc(&dBb, (size_t)N * K * 2));
            CHECK_CUDA(cudaMalloc(&dD, elem_D * 2));
            float *dAsp = nullptr, *dBsp = nullptr;
            void *dAp = nullptr, *dBp = nullptr;
            CHECK_CUDA(cudaMalloc(&dAsp, qa.scale_plain.size() * 4));
            CHECK_CUDA(cudaMalloc(&dBsp, qb.scale_plain.size() * 4));
            CHECK_CUDA(cudaMalloc(&dAp, (size_t)M * K / 2));
            CHECK_CUDA(cudaMalloc(&dBp, (size_t)N * K / 2));
            CHECK_CUDA(cudaMemcpy(dAp, qa.packed.data(), qa.packed.size(), cudaMemcpyHostToDevice));
            CHECK_CUDA(cudaMemcpy(dBp, qb.packed.data(), qb.packed.size(), cudaMemcpyHostToDevice));
            CHECK_CUDA(cudaMemcpy(dAsp, qa.scale_plain.data(), qa.scale_plain.size() * 4, cudaMemcpyHostToDevice));
            CHECK_CUDA(cudaMemcpy(dBsp, qb.scale_plain.data(), qb.scale_plain.size() * 4, cudaMemcpyHostToDevice));
            ResolvedGemm rg;
            if (!lt_resolve(ctx, g, dAb, dBb, dD, rg)) { out.why = "no algo (bf16)"; return out; }
            struct Pre { const uint8_t *pa, *pb; const float *sa, *sb; __nv_bfloat16 *ab, *bb; int64_t M, N, K; } pre{
                (const uint8_t*)dAp, (const uint8_t*)dBp, dAsp, dBsp, dAb, dBb, M, N, K};
            auto pre_fn = [](void* p) {
                Pre* q = (Pre*)p;
                dequant_nvfp4_bf16<<<(unsigned)q->M, 256>>>(q->pa, q->sa, q->ab, q->K);
                dequant_nvfp4_bf16<<<(unsigned)q->N, 256>>>(q->pb, q->sb, q->bb, q->K);
            };
            size_t bytes = bytes_A + bytes_B + (size_t)(M + N) * K * 2 + elem_D * 2;
            out.tr = time_gemm(ctx, rg, dAb, dBb, dD, M, N, K, bytes, rounds, iters, pre_fn, &pre);
            out.ok = true;
            cudaFree(dAb); cudaFree(dBb); cudaFree(dAsp); cudaFree(dBsp); cudaFree(dAp); cudaFree(dBp);
        }
    } else if (strcmp(mode, "fp8") == 0) {
        std::vector<uint8_t> eA((size_t)M * K), eB((size_t)N * K);
        for (size_t i = 0; i < eA.size(); ++i) eA[i] = __nv_cvt_float_to_fp8(hA[i], __NV_SATFINITE, __NV_E4M3);
        for (size_t i = 0; i < eB.size(); ++i) eB[i] = __nv_cvt_float_to_fp8(hB[i], __NV_SATFINITE, __NV_E4M3);
        bytes_A = eA.size(); bytes_B = eB.size();
        float one = 1.0f; float* d_one; CHECK_CUDA(cudaMalloc(&d_one, 4)); CHECK_CUDA(cudaMemcpy(d_one, &one, 4, cudaMemcpyHostToDevice));
        CHECK_CUDA(cudaMalloc(&dA, bytes_A)); CHECK_CUDA(cudaMalloc(&dB, bytes_B));
        CHECK_CUDA(cudaMalloc(&dD, elem_D * 2));
        CHECK_CUDA(cudaMemcpy(dA, eA.data(), bytes_A, cudaMemcpyHostToDevice));
        CHECK_CUDA(cudaMemcpy(dB, eB.data(), bytes_B, cudaMemcpyHostToDevice));
        g.a = CUDA_R_8F_E4M3; g.b = CUDA_R_8F_E4M3; g.cd = CUDA_R_16F;
        g.a_scale_ptr = d_one; g.b_scale_ptr = d_one;  // scalar 32F scales (mode 0 default)
        ResolvedGemm rg;
        if (!lt_resolve(ctx, g, dA, dB, dD, rg)) { out.why = "no algo"; return out; }
        size_t bytes = bytes_A + bytes_B + elem_D * 2;
        out.tr = time_gemm(ctx, rg, dA, dB, dD, M, N, K, bytes, rounds, iters);
        out.ok = true;
        cudaFree(d_one);
    } else if (strcmp(mode, "bf16") == 0 || strcmp(mode, "fp16") == 0) {
        bool isbf = strcmp(mode, "bf16") == 0;
        if (isbf) {
            std::vector<__nv_bfloat16> eA((size_t)M * K), eB((size_t)N * K);
            for (size_t i = 0; i < eA.size(); ++i) eA[i] = __float2bfloat16(hA[i]);
            for (size_t i = 0; i < eB.size(); ++i) eB[i] = __float2bfloat16(hB[i]);
            bytes_A = eA.size() * 2; bytes_B = eB.size() * 2;
            CHECK_CUDA(cudaMalloc(&dA, bytes_A)); CHECK_CUDA(cudaMalloc(&dB, bytes_B));
            CHECK_CUDA(cudaMalloc(&dD, elem_D * 2));
            CHECK_CUDA(cudaMemcpy(dA, eA.data(), bytes_A, cudaMemcpyHostToDevice));
            CHECK_CUDA(cudaMemcpy(dB, eB.data(), bytes_B, cudaMemcpyHostToDevice));
            g.a = CUDA_R_16BF; g.b = CUDA_R_16BF; g.cd = CUDA_R_16BF;
        } else {
            std::vector<__half> eA((size_t)M * K), eB((size_t)N * K);
            for (size_t i = 0; i < eA.size(); ++i) eA[i] = __float2half(hA[i]);
            for (size_t i = 0; i < eB.size(); ++i) eB[i] = __float2half(hB[i]);
            bytes_A = eA.size() * 2; bytes_B = eB.size() * 2;
            CHECK_CUDA(cudaMalloc(&dA, bytes_A)); CHECK_CUDA(cudaMalloc(&dB, bytes_B));
            CHECK_CUDA(cudaMalloc(&dD, elem_D * 2));
            CHECK_CUDA(cudaMemcpy(dA, eA.data(), bytes_A, cudaMemcpyHostToDevice));
            CHECK_CUDA(cudaMemcpy(dB, eB.data(), bytes_B, cudaMemcpyHostToDevice));
            g.a = CUDA_R_16F; g.b = CUDA_R_16F; g.cd = CUDA_R_16F;
        }
        ResolvedGemm rg;
        if (!lt_resolve(ctx, g, dA, dB, dD, rg)) { out.why = "no algo"; return out; }
        size_t bytes = bytes_A + bytes_B + elem_D * 2;
        out.tr = time_gemm(ctx, rg, dA, dB, dD, M, N, K, bytes, rounds, iters);
        out.ok = true;
    } else {
        out.why = "unknown mode";
        return out;
    }

    if (dA) cudaFree(dA);
    if (dB) cudaFree(dB);
    if (dD) cudaFree(dD);
    if (dAs) cudaFree(dAs);
    if (dBs) cudaFree(dBs);
    return out;
}

static void print_run(const char* mode, int64_t M, int64_t N, int64_t K, const RunOut& r) {
    if (!r.ok) {
        printf("RESULT mode=%-8s M=%-6ld N=%-6ld K=%-6ld FAILED (%s)\n", mode, (long)M, (long)N, (long)K, r.why.c_str());
        return;
    }
    printf("RESULT mode=%-8s M=%-6ld N=%-6ld K=%-6ld ms=%8.3f tflops=%7.1f gbps=%7.1f J=%7.4f idleW=%5.2f kHz=%ld errRMS=%9.2e errMax=%9.2e load=%.1f\n",
           mode, (long)M, (long)N, (long)K, r.tr.ms_median, r.tr.tflops, r.tr.gbps, r.tr.joules,
           r.tr.idle_w, r.tr.freq_khz, r.err_rms, r.err_max, read_loadavg());
}

int main(int argc, char** argv) {
    srand(1234);
    int dev = 0; cudaDeviceProp prop;
    cudaGetDevice(&dev); cudaGetDeviceProperties(&prop, dev);
    size_t ltver = cublasLtGetVersion();
    printf("# device=%s cc=%d.%d SMPs=%d cublasLt=%zu load=%.1f\n",
           prop.name, prop.major, prop.minor, prop.multiProcessorCount, ltver, read_loadavg());

    LtCtx ctx;
    std::string cmd = argc > 1 ? argv[1] : "sweep";

    if (cmd == "one") {
        const char* mode = argv[2];
        int64_t M = atoll(argv[3]), N = atoll(argv[4]), K = atoll(argv[5]);
        int iters = argc > 6 ? atoi(argv[6]) : 10;
        RunOut r = run_config(ctx, mode, M, N, K, 5, iters, M * N <= 4096ull * 4096);
        print_run(mode, M, N, K, r);
        return 0;
    }

    if (cmd == "limits") {
        // where does the NVFP4 heuristic stop returning algorithms?
        printf("# nvfp4 TN heuristic coverage (algos>0 = usable)\n");
        int64_t Ks[] = {32, 48, 64, 96, 128, 192, 256, 384};
        printf("## vary K (M=N=256)\n");
        for (int64_t K : Ks) {
            GemmCfg g{256, 256, K, CUDA_R_4F_E2M1, CUDA_R_4F_E2M1, CUDA_R_16F};
            g.a_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
            g.b_scale_mode = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
            void* dummy = (void*)0x100000ull; g.a_scale_ptr = dummy; g.b_scale_ptr = dummy;
            ResolvedGemm rg;
            // heuristic-only query (no real buffers): reuse lt_run without executing
            cublasLtMatmulDesc_t op; cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F);
            cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &g.a_scale_mode, sizeof(int32_t));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &g.b_scale_mode, sizeof(int32_t));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dummy, sizeof(void*));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dummy, sizeof(void*));
            cublasLtMatrixLayout_t la, lb, lc;
            cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, K, 256, K);
            cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, K, 256, K);
            cublasLtMatrixLayoutCreate(&lc, CUDA_R_16F, 256, 256, 256);
            cublasLtMatmulPreference_t pref; cublasLtMatmulPreferenceCreate(&pref);
            size_t ws = ctx.ws_size;
            cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &ws, sizeof(ws));
            cublasLtMatmulHeuristicResult_t res[8]; int found = 0;
            cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(ctx.lt, op, la, lb, lc, lc, pref, 8, res, &found);
            printf("K=%-5ld algos=%-3d status=%d\n", (long)K, st == CUBLAS_STATUS_SUCCESS ? found : 0, (int)st);
            cublasLtMatmulPreferenceDestroy(pref); cublasLtMatrixLayoutDestroy(la);
            cublasLtMatrixLayoutDestroy(lb); cublasLtMatrixLayoutDestroy(lc); cublasLtMatmulDescDestroy(op);
        }
        int64_t Ms[] = {16, 32, 64, 96, 128, 192, 256, 384, 512, 1000, 1032};
        printf("## vary M=N (K=256)\n");
        for (int64_t X : Ms) {
            cublasLtMatmulDesc_t op; cublasLtMatmulDescCreate(&op, CUBLAS_COMPUTE_32F, CUDA_R_32F);
            cublasOperation_t tA = CUBLAS_OP_T, tN = CUBLAS_OP_N;
            int32_t sm = (int32_t)CUBLASLT_MATMUL_MATRIX_SCALE_VEC16_UE4M3;
            void* dummy = (void*)0x100000ull;
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSA, &tA, sizeof(tA));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_TRANSB, &tN, sizeof(tN));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_MODE, &sm, sizeof(int32_t));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_MODE, &sm, sizeof(int32_t));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_A_SCALE_POINTER, &dummy, sizeof(void*));
            cublasLtMatmulDescSetAttribute(op, CUBLASLT_MATMUL_DESC_B_SCALE_POINTER, &dummy, sizeof(void*));
            cublasLtMatrixLayout_t la, lb, lc;
            cublasLtMatrixLayoutCreate(&la, CUDA_R_4F_E2M1, 256, X, 256);
            cublasLtMatrixLayoutCreate(&lb, CUDA_R_4F_E2M1, 256, X, 256);
            cublasLtMatrixLayoutCreate(&lc, CUDA_R_16F, X, X, X);
            cublasLtMatmulPreference_t pref; cublasLtMatmulPreferenceCreate(&pref);
            size_t ws = ctx.ws_size;
            cublasLtMatmulPreferenceSetAttribute(pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &ws, sizeof(ws));
            cublasLtMatmulHeuristicResult_t res[8]; int found = 0;
            cublasStatus_t st = cublasLtMatmulAlgoGetHeuristic(ctx.lt, op, la, lb, lc, lc, pref, 8, res, &found);
            printf("M=N=%-5ld algos=%-3d status=%d\n", (long)X, st == CUBLAS_STATUS_SUCCESS ? found : 0, (int)st);
            cublasLtMatmulPreferenceDestroy(pref); cublasLtMatrixLayoutDestroy(la);
            cublasLtMatrixLayoutDestroy(lb); cublasLtMatrixLayoutDestroy(lc); cublasLtMatmulDescDestroy(op);
        }
        return 0;
    }

    // sweep: sizes x modes, interleaved rounds so ratios survive a shared box
    struct Size { int64_t M, N, K; const char* tag; };
    std::vector<Size> sizes = {
        {8192, 8192, 8192, "anchor (matches exp-fp8-tensorcores)"},
        {4096, 4096, 4096, "mid"},
        {16384, 16384, 16384, "big"},
        {2048, 2048, 2048, "small"},
        {4096, 5120, 5120, "sdxl-ish 320/640/1280->5120"},
        {1024, 8192, 8192, "decision-model-ish batch"},
    };
    const char* modes[] = {"bf16", "fp8", "nvfp4", "nvfp4dq"};
    printf("# interleaved sweep: 3 rounds; within a round every mode runs back to back\n");
    for (int rd = 0; rd < 3; ++rd) {
        printf("# round %d (load %.1f)\n", rd, read_loadavg());
        for (auto& s : sizes) {
            for (const char* m : modes) {
                bool ref = (rd == 0) && (s.M * s.N <= 4096ull * 4096) && (strcmp(m, "nvfp4") == 0);
                RunOut r = run_config(ctx, m, s.M, s.N, s.K, 3, 10, ref);
                print_run(m, s.M, s.N, s.K, r);
            }
        }
    }
    return 0;
}
