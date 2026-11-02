// The Beacons CUDA backend.
//
// The same `rules.cuh` the CPU backend compiles, launched one world per
// thread. The five launches are the ones the contract names:
//
//   ResetKernel     one thread per world: the initial state
//   StepKernel      one thread per world: the acting agent's turn
//   MaskKernel      one thread per world: the nine legal actions
//   ObsKernel       one block per world, one thread per cell: the six planes
//   TerminateKernel one thread per world: the reward and the terminated flag
//
// The world is grown on the **host** (`worldgen.cuh`): the connectivity
// repair is a serial flood fill that does not parallelise across the
// worlds, and one host generator means both backends start from the same
// bytes. The rules themselves -- the expensive part, the part that repeats
// for every step of every world -- run on the GPU.

#include <cuda_runtime.h>

#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#include "core/sim/systems/beacons/backend.h"
#include "core/sim/systems/beacons/rules.cuh"
#include "core/sim/systems/beacons/worldgen.cuh"

namespace pysim {
namespace beacons {
namespace {

#define BS_CUDA_CHECK(what)                                                    \
    do {                                                                       \
        cudaError_t err_ = (what);                                             \
        if (err_ != cudaSuccess) {                                             \
            throw std::runtime_error(std::string("pysim: ") +                  \
                                     cudaGetErrorString(err_) + " at " #what);  \
        }                                                                      \
    } while (0)

constexpr int kObsThreads = 128;

// One thread per world: the acting agent's turn.
__global__ void StepKernel(BeaconState* states, const BeaconWorld* worlds,
                           const BeaconParams params, uint32_t num_envs, uint32_t row_stride,
                           uint32_t row, uint32_t next_row, const int32_t* actions) {
    const uint32_t env = blockIdx.x * blockDim.x + threadIdx.x;
    if (env >= num_envs) return;
    BeaconState s = states[(size_t)env * row_stride + row];
    env_step(worlds[env], params, &s, actions[env]);
    states[(size_t)env * row_stride + next_row] = s;
}

// One thread per world: the nine legal actions.
__global__ void MaskKernel(const BeaconState* states, const BeaconWorld* worlds,
                           const BeaconParams params, uint32_t num_envs, uint32_t row_stride,
                           uint32_t row, bool* out) {
    const uint32_t env = blockIdx.x * blockDim.x + threadIdx.x;
    if (env >= num_envs) return;
    bool bits[kNumActions];
    write_mask(worlds[env], params, states[(size_t)env * row_stride + row], bits);
    bool* dst = out + (size_t)env * kNumActions;
    for (uint32_t a = 0; a < kNumActions; ++a) dst[a] = bits[a];
}

// One block per world, one thread per cell: the six planes.
__global__ void ObsKernel(const BeaconState* states, const BeaconWorld* worlds,
                          const BeaconParams params, uint32_t num_envs, uint32_t row_stride,
                          uint32_t row, uint32_t width, uint32_t height, float* out) {
    const uint32_t env = blockIdx.x;
    if (env >= num_envs) return;
    const BeaconState& s = states[(size_t)env * row_stride + row];
    const BeaconWorld& w = worlds[env];
    uint32_t index = 0;
    if (s.num_agents > 0) index = acting_index(s.tick, s.turn, w.initiative, s.num_agents);
    int32_t ex = 0, ey = 0;
    if (s.num_agents > 0) cell_of(w, s.pos_x[index], s.pos_y[index], &ex, &ey);
    const size_t obs_len = (size_t)kObsChannels * width * height;
    float* dst = out + (size_t)env * obs_len;
    const uint32_t cells = width * height;
    for (uint32_t cell = threadIdx.x; cell < cells; cell += blockDim.x) {
        const uint32_t cx = cell % width;
        const uint32_t cy = cell / width;
        obs_cell(w, params, s, index, ex, ey, (int32_t)cx, (int32_t)cy, dst);
    }
}

// One thread per world: the reward and the terminated flag.
__global__ void TerminateKernel(const BeaconState* states, uint32_t num_envs,
                                uint32_t row_stride, uint32_t row, float* reward,
                                int32_t* terminated) {
    const uint32_t env = blockIdx.x * blockDim.x + threadIdx.x;
    if (env >= num_envs) return;
    const BeaconState& s = states[(size_t)env * row_stride + row];
    reward[env] = (float)s.last_reward;
    terminated[env] = (s.outcome != 0) ? 1 : 0;
}

class CudaBackend : public Backend {
public:
    CudaBackend(const ParamMap& params, uint32_t num_envs, uint32_t rows)
        : params_(params_from(params)), num_envs_(num_envs), rows_(rows) {
        spec_ = spec_for(params_);
        const size_t obs_len =
            (size_t)spec_.obs_channels * spec_.obs_width * spec_.obs_height;
        BS_CUDA_CHECK(cudaMalloc(&d_states_, (size_t)num_envs_ * rows_ * sizeof(BeaconState)));
        BS_CUDA_CHECK(cudaMalloc(&d_worlds_, (size_t)num_envs_ * sizeof(BeaconWorld)));
        BS_CUDA_CHECK(cudaMalloc(&d_terminated_,
                                 (size_t)num_envs_ * rows_ * sizeof(int32_t)));
        BS_CUDA_CHECK(cudaMalloc(&d_reward_, (size_t)num_envs_ * rows_ * sizeof(float)));
        BS_CUDA_CHECK(cudaMalloc(&d_mask_, (size_t)num_envs_ * rows_ * kNumActions));
        BS_CUDA_CHECK(cudaMalloc(&d_obs_, (size_t)num_envs_ * obs_len * sizeof(float)));
        BS_CUDA_CHECK(cudaMalloc(&d_actions_, (size_t)num_envs_ * sizeof(int32_t)));
        BS_CUDA_CHECK(cudaMalloc(&d_seeds_, (size_t)num_envs_ * sizeof(uint64_t)));
        h_states_.assign((size_t)num_envs_ * rows_, BeaconState{});
        h_worlds_.assign(num_envs_, BeaconWorld{});
        h_obs_.assign((size_t)num_envs_ * obs_len, 0.0f);
        h_mask_.assign((size_t)num_envs_ * kNumActions, 0);
    }

    ~CudaBackend() override {
        if (d_states_) cudaFree(d_states_);
        if (d_worlds_) cudaFree(d_worlds_);
        if (d_terminated_) cudaFree(d_terminated_);
        if (d_reward_) cudaFree(d_reward_);
        if (d_mask_) cudaFree(d_mask_);
        if (d_obs_) cudaFree(d_obs_);
        if (d_actions_) cudaFree(d_actions_);
        if (d_seeds_) cudaFree(d_seeds_);
    }

    const SystemSpec& spec() const override { return spec_; }

    void reset(const uint64_t* seeds) override {
        std::memset(h_states_.data(), 0, h_states_.size() * sizeof(BeaconState));
        for (uint32_t env = 0; env < num_envs_; ++env) {
            generate_world(seeds[env], params_, &h_worlds_[env]);
            initial_state(h_worlds_[env], params_, &h_states_[(size_t)env * rows_]);
        }
        BS_CUDA_CHECK(cudaMemcpy(d_states_, h_states_.data(),
                                 h_states_.size() * sizeof(BeaconState),
                                 cudaMemcpyHostToDevice));
        BS_CUDA_CHECK(cudaMemcpy(d_worlds_, h_worlds_.data(),
                                 h_worlds_.size() * sizeof(BeaconWorld),
                                 cudaMemcpyHostToDevice));
        BS_CUDA_CHECK(cudaMemset(d_terminated_, 0, (size_t)num_envs_ * rows_ * sizeof(int32_t)));
        BS_CUDA_CHECK(cudaMemset(d_reward_, 0, (size_t)num_envs_ * rows_ * sizeof(float)));
        row_ = 0;
    }

    void apply_actions(const int32_t* actions) override {
        BS_CUDA_CHECK(cudaMemcpy(d_actions_, actions, (size_t)num_envs_ * sizeof(int32_t),
                                 cudaMemcpyHostToDevice));
        const uint32_t next = (row_ + 1) % rows_;
        const uint32_t threads = 128;
        const uint32_t blocks = (num_envs_ + threads - 1) / threads;
        StepKernel<<<blocks, threads>>>(d_states_, d_worlds_, params_, num_envs_, rows_, row_,
                                         next, d_actions_);
        BS_CUDA_CHECK(cudaGetLastError());
        BS_CUDA_CHECK(cudaDeviceSynchronize());
        row_ = next;
    }

    void legal_action_mask(bool* out) override {
        const uint32_t threads = 128;
        const uint32_t blocks = (num_envs_ + threads - 1) / threads;
        MaskKernel<<<blocks, threads>>>(d_states_, d_worlds_, params_, num_envs_, rows_, row_,
                                        d_mask_);
        BS_CUDA_CHECK(cudaGetLastError());
        BS_CUDA_CHECK(cudaDeviceSynchronize());
        BS_CUDA_CHECK(cudaMemcpy(out, d_mask_, (size_t)num_envs_ * kNumActions,
                                 cudaMemcpyDeviceToHost));
    }

    void obs(float* out) override {
        ObsKernel<<<num_envs_, kObsThreads>>>(d_states_, d_worlds_, params_, num_envs_, rows_,
                                              row_, spec_.obs_width, spec_.obs_height, d_obs_);
        BS_CUDA_CHECK(cudaGetLastError());
        BS_CUDA_CHECK(cudaDeviceSynchronize());
        BS_CUDA_CHECK(cudaMemcpy(out, d_obs_, h_obs_.size() * sizeof(float),
                                 cudaMemcpyDeviceToHost));
    }

    void reward_and_terminated(float* reward, int32_t* terminated) override {
        TerminateKernel<<<(num_envs_ + 127) / 128, 128>>>(d_states_, num_envs_, rows_, row_,
                                                          d_reward_, d_terminated_);
        BS_CUDA_CHECK(cudaGetLastError());
        BS_CUDA_CHECK(cudaDeviceSynchronize());
        BS_CUDA_CHECK(cudaMemcpy(reward, d_reward_, (size_t)num_envs_ * sizeof(float),
                                 cudaMemcpyDeviceToHost));
        BS_CUDA_CHECK(cudaMemcpy(terminated, d_terminated_, (size_t)num_envs_ * sizeof(int32_t),
                                 cudaMemcpyDeviceToHost));
    }

    void serialize_states(uint8_t* out) override {
        BS_CUDA_CHECK(cudaMemcpy(h_states_.data(), d_states_,
                                 h_states_.size() * sizeof(BeaconState),
                                 cudaMemcpyDeviceToHost));
        for (uint32_t env = 0; env < num_envs_; ++env) {
            serialize_state(params_, h_states_[(size_t)env * rows_ + row_],
                            out + (size_t)env * spec_.state_serial_bytes);
        }
    }

    void serialize_worlds(uint8_t* out) override {
        BS_CUDA_CHECK(cudaMemcpy(h_worlds_.data(), d_worlds_,
                                 h_worlds_.size() * sizeof(BeaconWorld),
                                 cudaMemcpyDeviceToHost));
        for (uint32_t env = 0; env < num_envs_; ++env) {
            serialize_world(params_, h_worlds_[env], out + (size_t)env * spec_.world_serial_bytes);
        }
    }

    uint32_t row() const override { return row_; }

private:
    BeaconParams params_;
    SystemSpec spec_;
    uint32_t num_envs_ = 0;
    uint32_t rows_ = 1;
    uint32_t row_ = 0;
    std::vector<BeaconState> h_states_;
    std::vector<BeaconWorld> h_worlds_;
    std::vector<float> h_obs_;
    std::vector<uint8_t> h_mask_;
    BeaconState* d_states_ = nullptr;
    BeaconWorld* d_worlds_ = nullptr;
    int32_t* d_terminated_ = nullptr;
    float* d_reward_ = nullptr;
    bool* d_mask_ = nullptr;
    float* d_obs_ = nullptr;
    int32_t* d_actions_ = nullptr;
    uint64_t* d_seeds_ = nullptr;
};

}  // namespace

std::unique_ptr<Backend> make_cuda_backend(const ParamMap& params, uint32_t num_envs,
                                            uint32_t rows) {
    return std::unique_ptr<Backend>(new CudaBackend(params, num_envs, rows));
}

}  // namespace beacons
}  // namespace pysim
