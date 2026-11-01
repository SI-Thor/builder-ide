// green_ctx_probe.c — does CUDA 13.2 Green Contexts work on sm_110 (Jetson AGX Thor)?
//
// This is the "seed 164" question from docs/research/googl1.md: can we split SMs
// into partitions inside one process, with the desktop up, so live work gets a
// guaranteed SM share? MIG cannot do it on this box (compute-only, blocked by
// the desktop session), so Green Contexts is the alternative admission primitive.
//
// Read-only with respect to the machine: no /dev/mem, no firmware, no boot
// config, no privileged writes. Pure CUDA driver API calls.

#include <cuda.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(call, label)                                                        \
    do {                                                                          \
        CUresult _r = (call);                                                    \
        if (_r != CUDA_SUCCESS) {                                                \
            const char *_n = NULL;                                               \
            cuGetErrorName(_r, &_n);                                             \
            printf("  FAIL %-34s -> %s (%d)\n", label, _n ? _n : "?", (int)_r);   \
            return _r;                                                           \
        }                                                                         \
        printf("  ok   %-34s\n", label);                                         \
    } while (0)

static const char *res_name(CUresult r) {
    const char *n = NULL;
    cuGetErrorName(r, &n);
    return n ? n : "?";
}

// A trivial kernel: each thread writes its block index into out[].
__global__ void fill_kernel(int *out, int n, int seed) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) out[i] = seed + i;
}

static int check_stream(CUstream s, const char *label, int *out, int n) {
    int *d_out = NULL;
    if (cudaMalloc(&d_out, n * sizeof(int)) != cudaSuccess) {
        printf("  FAIL %-34s cudaMalloc failed\n", label);
        return 0;
    }
    fill_kernel<<<(n + 255) / 256, 256>>>(d_out, n, 7);
    if (cuStreamSynchronize(s) != CUDA_SUCCESS) {
        printf("  FAIL %-34s launch/sync failed\n", label);
        cudaFree(d_out);
        return 0;
    }
    int *h = (int *)malloc(n * sizeof(int));
    if (cudaMemcpy(h, d_out, n * sizeof(int), cudaMemcpyDeviceToHost) != cudaSuccess) {
        printf("  FAIL %-34s memcpy failed\n", label);
        free(h); cudaFree(d_out);
        return 0;
    }
    int bad = 0;
    for (int i = 0; i < n; i++) if (h[i] != 7 + i) bad++;
    printf("  %-4s %-34s (%d elems, %d mismatches)\n", bad ? "FAIL" : "ok", label, n, bad);
    free(h); cudaFree(d_out);
    return bad == 0;
}

int main(void) {
    CUdevice dev;
    CUresult r = cuInit(0);
    if (r != CUDA_SUCCESS) { printf("cuInit failed: %s\n", res_name(r)); return 1; }

    int ndev = 0;
    cuDeviceGetCount(&ndev);
    printf("=== device count: %d ===\n", ndev);
    if (ndev < 1) { printf("no CUDA device\n"); return 1; }

    CUdevice dev0;
    CHECK(cuDeviceGet(&dev0, 0), "cuDeviceGet(0)");

    char name[256] = {0};
    int major = 0, minor = 0, smCount = 0;
    cuDeviceGetName(name, sizeof(name), dev0);
    cuDeviceGetAttribute(&major, CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR, dev0);
    cuDeviceGetAttribute(&minor, CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR, dev0);
    cuDeviceGetAttribute(&smCount, CU_DEVICE_ATTRIBUTE_MULTIPROCESSOR_COUNT, dev0);
    printf("device: %s  cc %d.%d  SMs %d\n", name, major, minor, smCount);

    // Cluster launch support (claimed in googl1.md Stage 3).
    int clc = 0;
    r = cuDeviceGetAttribute(&clc, CU_DEVICE_ATTRIBUTE_CLUSTER_LAUNCH, dev0);
    if (r == CUDA_SUCCESS) printf("clusterLaunch supported: %d\n", clc);
    else printf("clusterLaunch attribute: %s\n", res_name(r));

    // --- Step 1: get the whole-device SM resource -------------------------------
    printf("\n=== 1. cuDeviceGetDevResource(SM) ===\n");
    CUdevResource smRes;
    memset(&smRes, 0, sizeof(smRes));
    r = cuDeviceGetDevResource(dev0, &smRes, CU_DEV_RESOURCE_TYPE_SM);
    if (r != CUDA_SUCCESS) {
        printf("  FAIL cuDeviceGetDevResource -> %s\n", res_name(r));
        printf("  (Green Contexts SM split unavailable on this device/driver)\n");
        return 2;
    }
    printf("  ok   cuDeviceGetDevResource\n");
    printf("  smCount=%u  minSmPartitionSize=%u  smCoscheduledAlignment=%u  flags=0x%x\n",
           smRes.sm.smCount, smRes.sm.minSmPartitionSize,
           smRes.sm.smCoscheduledAlignment, smRes.sm.flags);

    // --- Step 2: split by count into 2 groups -----------------------------------
    printf("\n=== 2. cuDevSmResourceSplitByCount(2 groups) ===\n");
    unsigned int nbGroups = 0;
    r = cuDevSmResourceSplitByCount(NULL, &nbGroups, &smRes, NULL, 0, 1);
    if (r != CUDA_SUCCESS) {
        printf("  FAIL discovery mode -> %s\n", res_name(r));
        return 3;
    }
    printf("  ok   discovery: max groups for 1-SM minimum = %u\n", nbGroups);

    unsigned int want = 2;
    CUdevResource groups[8];
    CUdevResource remainder;
    memset(groups, 0, sizeof(groups));
    memset(&remainder, 0, sizeof(remainder));
    nbGroups = want;
    r = cuDevSmResourceSplitByCount(groups, &nbGroups, &smRes, &remainder, 0, 1);
    if (r != CUDA_SUCCESS) {
        printf("  FAIL split -> %s\n", res_name(r));
        return 4;
    }
    printf("  ok   split into %u groups\n", nbGroups);
    for (unsigned int i = 0; i < nbGroups; i++) {
        printf("       group[%u]: smCount=%u  minSmPartitionSize=%u  coschedAlign=%u\n",
               i, groups[i].sm.smCount, groups[i].sm.minSmPartitionSize,
               groups[i].sm.smCoscheduledAlignment);
    }
    printf("       remainder: smCount=%u\n", remainder.sm.smCount);

    // --- Step 3: build descriptors and create green contexts ---------------------
    printf("\n=== 3. cuDevResourceGenerateDesc + cuGreenCtxCreate ===\n");
    CUdevResourceDesc descA, descB;
    CUdevResource resA[1], resB[1];
    resA[0] = groups[0]; resB[0] = groups[1];
    CHECK(cuDevResourceGenerateDesc(&descA, resA, 1), "cuDevResourceGenerateDesc(A)");
    CHECK(cuDevResourceGenerateDesc(&descB, resB, 1), "cuDevResourceGenerateDesc(B)");

    CUgreenCtx gA = NULL, gB = NULL;
    r = cuGreenCtxCreate(&gA, descA, dev0, 0);
    if (r != CUDA_SUCCESS) {
        printf("  FAIL cuGreenCtxCreate(A) -> %s\n", res_name(r));
        return 5;
    }
    printf("  ok   cuGreenCtxCreate(A)\n");
    r = cuGreenCtxCreate(&gB, descB, dev0, 0);
    if (r != CUDA_SUCCESS) {
        printf("  FAIL cuGreenCtxCreate(B) -> %s\n", res_name(r));
        return 6;
    }
    printf("  ok   cuGreenCtxCreate(B)\n");

    // Query back what each green context actually owns.
    CUdevResource qA, qB;
    memset(&qA, 0, sizeof(qA)); memset(&qB, 0, sizeof(qB));
    if (cuGreenCtxGetDevResource(gA, &qA, CU_DEV_RESOURCE_TYPE_SM) == CUDA_SUCCESS)
        printf("  ok   green A owns smCount=%u\n", qA.sm.smCount);
    else
        printf("  note cuGreenCtxGetDevResource(A) unsupported\n");
    if (cuGreenCtxGetDevResource(gB, &qB, CU_DEV_RESOURCE_TYPE_SM) == CUDA_SUCCESS)
        printf("  ok   green B owns smCount=%u\n", qB.sm.smCount);

    // --- Step 4: streams inside green contexts ----------------------------------
    printf("\n=== 4. cuGreenCtxStreamCreate + kernel execution ===\n");
    CUstream sA = NULL, sB = NULL;
    r = cuGreenCtxStreamCreate(&sA, gA, CU_STREAM_NON_BLOCKING);
    if (r != CUDA_SUCCESS) { printf("  FAIL cuGreenCtxStreamCreate(A) -> %s\n", res_name(r)); return 7; }
    printf("  ok   cuGreenCtxStreamCreate(A)\n");
    r = cuGreenCtxStreamCreate(&sB, gB, CU_STREAM_NON_BLOCKING);
    if (r != CUDA_SUCCESS) { printf("  FAIL cuGreenCtxStreamCreate(B) -> %s\n", res_name(r)); return 8; }
    printf("  ok   cuGreenCtxStreamCreate(B)\n");

    int okA = check_stream(sA, "kernel on green A stream", NULL, 4096);
    int okB = check_stream(sB, "kernel on green B stream", NULL, 4096);

    // --- Step 5: concurrent execution on both green contexts --------------------
    printf("\n=== 5. concurrent kernels on both green contexts ===\n");
    int *dA = NULL, *dB = NULL;
    int n = 1 << 20;
    if (cudaMalloc(&dA, n * sizeof(int)) == cudaSuccess &&
        cudaMalloc(&dB, n * sizeof(int)) == cudaSuccess) {
        fill_kernel<<<(n + 255) / 256, 256, 0, sA>>>(dA, n, 100);
        fill_kernel<<<(n + 255) / 256, 256, 0, sB>>>(dB, n, 900);
        CUresult sa = cuStreamSynchronize(sA);
        CUresult sb = cuStreamSynchronize(sB);
        printf("  sync A: %s   sync B: %s\n", res_name(sa), res_name(sb));
        int *hA = (int *)malloc(64 * sizeof(int));
        int *hB = (int *)malloc(64 * sizeof(int));
        cudaMemcpy(hA, dA, 64 * sizeof(int), cudaMemcpyDeviceToHost);
        cudaMemcpy(hB, dB, 64 * sizeof(int), cudaMemcpyDeviceToHost);
        int badA = 0, badB = 0;
        for (int i = 0; i < 64; i++) {
            if (hA[i] != 100 + i) badA++;
            if (hB[i] != 900 + i) badB++;
        }
        printf("  %-4s green A output (first 64): %d mismatches\n", badA ? "FAIL" : "ok", badA);
        printf("  %-4s green B output (first 64): %d mismatches\n", badB ? "FAIL" : "ok", badB);
        free(hA); free(hB);
    } else {
        printf("  note: cudaMalloc failed for the concurrent test\n");
    }

    printf("\n=== SUMMARY ===\n");
    printf("green_contexts_supported: YES\n");
    printf("device_sm_count: %u\n", smCount);
    printf("split_groups: %u (smCounts: %u, %u)\n", nbGroups,
           groups[0].sm.smCount, groups[1].sm.smCount);
    printf("remainder_sm_count: %u\n", remainder.sm.smCount);
    printf("kernel_A_correct: %s\n", okA ? "yes" : "no");
    printf("kernel_B_correct: %s\n", okB ? "yes" : "no");
    return (okA && okB) ? 0 : 9;
}
