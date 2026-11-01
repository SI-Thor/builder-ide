// probe.cu — Thor GPU capability probe for the ct-thor experiments.
#include <cstdio>
#include <cuda_runtime.h>

__global__ void triad(double* __restrict__ c, const double* __restrict__ a,
                      const double* __restrict__ b, size_t n) {
    size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) c[i] = a[i] + 3.0 * b[i];
}

int main() {
    int dev = 0;
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, dev);
    printf("name                 %s\n", prop.name);
    printf("cc                   %d.%d\n", prop.major, prop.minor);
    printf("SMs                  %d\n", prop.multiProcessorCount);
    printf("l2Cache MB           %.1f\n", prop.l2CacheSize / 1048576.0);
    printf("persistingL2 Max     %.1f MB\n", prop.persistingL2CacheMaxSize / 1048576.0);
    printf("globalMem GB         %.1f\n", prop.totalGlobalMem / 1073741824.0);
    printf("managedMemory        %d\n", prop.managedMemory);
    printf("concurrentManagedAccess %d\n", prop.concurrentManagedAccess);
    printf("hostNativeAtomic     %d\n", prop.hostNativeAtomicSupported);
    printf("pageableMemoryAccess %d\n", prop.pageableMemoryAccess);
    printf("directManagedMemAccessFromHost %d\n", prop.directManagedMemAccessFromHost);
    printf("memoryBusWidth bit   %d\n", prop.memoryBusWidth);
    printf("memPitch             %zu\n", prop.memPitch);
    printf("warpSize             %d\n", prop.warpSize);
    printf("sharedMemPerBlock KB %.1f\n", prop.sharedMemPerBlock / 1024.0);
    printf("maxGridDimX          %d\n", prop.maxGridSize[0]);

    // Unified memory: is the device pointer the same as the host pointer?
    void *mp = nullptr;
    cudaError_t e = cudaMallocManaged(&mp, 4096);
    printf("cudaMallocManaged    %s ptr=%p\n", cudaGetErrorString(e), mp);
    int *ip = (int*)mp;
    ip[0] = 42;                       // host write
    printf("host write visible   %s\n", ip[0] == 42 ? "yes" : "no");

    // Triad bandwidth on managed memory, device pointer == host pointer.
    size_t n = 64ULL * 1024 * 1024;   // 64M float64 = 512 MB per array
    double *a, *b, *c;
    cudaMallocManaged(&a, n * 8);
    cudaMallocManaged(&b, n * 8);
    cudaMallocManaged(&c, n * 8);
    for (size_t i = 0; i < n; i++) { a[i] = 1.0; b[i] = 2.0; }
    cudaEvent_t t0, t1;
    cudaEventCreate(&t0); cudaEventCreate(&t1);
    // warmup
    for (int r = 0; r < 3; r++) {
        cudaEventRecord(t0);
        triad<<<n / 256, 256>>>(c, a, b, n);
        cudaEventRecord(t1);
        cudaEventSynchronize(t1);
    }
    float best = 1e9;
    for (int r = 0; r < 10; r++) {
        cudaEventRecord(t0);
        triad<<<n / 256, 256>>>(c, a, b, n);
        cudaEventRecord(t1);
        cudaEventSynchronize(t1);
        float ms = 0; cudaEventElapsedTime(&ms, t0, t1);
        if (ms < best) best = ms;
    }
    printf("triad BW             %.1f GB/s (%.3f ms, 1.5 GB moved)\n",
           1.5 * 1024 / (best / 1e3) / 1.024, best);
    return 0;
}
