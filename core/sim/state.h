// The batch container: one contiguous array of fixed-size states, rows of
// time.
//
// The shape is deliberately the one Stratego uses (`StrategoRolloutBuffer`,
// src/env/stratego.h:66), because that shape is the one that works:
//
//   - a game's whole state is a fixed-size POD, so a batch of N worlds is one
//     contiguous allocation and a kernel reaches world *i* by pointer
//     arithmetic;
//   - the batch is `rows × num_envs` states, row-major, the row stride is
//     `num_envs`;
//   - no per-world allocation, no dispatch, no virtual call in the step path.
//
// The container knows nothing about the rule system behind it: the traits
// say how big a state is and how the observation is shaped, and the system
// fills the buffers.

#pragma once

#include <cstddef>
#include <cstdint>

namespace pysim {

template <class Traits>
struct Batch {
    using State = typename Traits::State;
    using World = typename Traits::World;

    // The batch is one contiguous array of fixed-size states, rows of time.
    State* d_states = nullptr;      // num_envs * rows
    int32_t* d_terminated = nullptr;  // num_envs * rows
    float* d_reward = nullptr;      // num_envs * rows
    bool* d_legal_mask = nullptr;   // num_envs * rows * A
    float* d_obs = nullptr;         // num_envs * obs_rows * obs_len

    // The static part of a world: the grid, the beacons, the spawns. It is
    // not in the state because the rules never change it, and a 128x128
    // grid would otherwise be copied into every row of the rollout.
    World* d_worlds = nullptr;      // num_envs

    uint32_t num_envs = 0;
    uint32_t rows = 0;
    uint32_t A = 0;         // the action count
    uint32_t obs_len = 0;   // C * H * W
    uint32_t obs_rows = 0;  // rows when the system keeps the history, else 1

    // The row the live state is in. `apply_actions` reads it, writes the
    // next row and moves the pointer on.
    uint32_t row = 0;

    uint32_t state_index(uint32_t env, uint32_t r) const {
        return env * rows + r;
    }
    uint32_t mask_index(uint32_t env, uint32_t r) const {
        return (env * rows + r) * A;
    }
    uint32_t obs_index(uint32_t env, uint32_t r) const {
        const uint32_t rr = Traits::kObsHistory ? r : 0u;
        return (env * obs_rows + rr) * obs_len;
    }
};

}  // namespace pysim
