// A tiny CUDA program: it takes a real GPU context and holds a real
// allocation, so the daemon's per-process GPU figure has something to
// attribute to a lease.
//
//   nvcc -O2 -o cuda_probe cuda_probe.cu
//   thor-admit run --peak 1G --label cuda.probe -- ./cuda_probe --mib 512 --hold 12
//   thor-admit peaks --json
//
// The hogs the integration test drives are CPU only, so they have no GPU
// context and the driver says nothing about them (`peak_gpu_bytes: null`).
// This is the probe that shows the GPU's column working: on this box the
// driver reported 614 MiB for the process, and the daemon wrote
// 643 825 664 B — the same number, attributed to the lease.
//
// It is a probe, not a benchmark: it does no compute worth the name. The
// point is the context and the allocation, which is what the NVIDIA
// driver's per-process accounting reports.

#include <cuda_runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    size_t mib = 512;
    int hold = 10;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--mib") && i + 1 < argc) mib = (size_t)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--hold") && i + 1 < argc) hold = atoi(argv[++i]);
    }
    size_t bytes = mib * 1024 * 1024;
    void *buffer = NULL;
    cudaError_t error = cudaMalloc(&buffer, bytes);
    if (error != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed: %s\n", cudaGetErrorString(error));
        return 1;
    }
    // Fault it in, so the driver really accounts for it.
    cudaMemset(buffer, 1, bytes);
    cudaDeviceSynchronize();
    printf("cuda probe: holding %zu MiB on the GPU, pid %d\n", mib, (int)getpid());
    fflush(stdout);
    for (int second = 0; second < hold; second++) sleep(1);
    cudaFree(buffer);
    printf("cuda probe: done\n");
    return 0;
}
