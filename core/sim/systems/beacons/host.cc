// The Beacons CPU backend.
//
// The same `rules.cuh` the CUDA backend compiles, called one world at a time.
// The point of the two backends is that they are the *same rules*: "the GPU
// agrees with the CPU" is then a statement about the backend, and the
// trajectory proof compares their bytes.

#include <algorithm>
#include <cstring>
#include <thread>
#include <vector>

#include "core/sim/systems/beacons/backend.h"
#include "core/sim/systems/beacons/rules.cuh"
#include "core/sim/systems/beacons/worldgen.cuh"

namespace pysim {
namespace beacons {
namespace {

template <class T>
void get_param(const ParamMap& m, const char* key, T* slot) {
    auto it = m.find(key);
    if (it != m.end()) *slot = static_cast<T>(it->second);
}

// Run `body(i)` for every i in 0..n, over the box's cores.
template <class F>
void parallel_for(uint32_t n, F body) {
    unsigned hw = std::thread::hardware_concurrency();
    if (hw == 0) hw = 1;
    const uint32_t threads = std::min<uint32_t>(hw, 14u);
    if (threads <= 1 || n < 2) {
        for (uint32_t i = 0; i < n; ++i) body(i);
        return;
    }
    std::vector<std::thread> pool;
    pool.reserve(threads);
    for (uint32_t t = 0; t < threads; ++t) {
        pool.emplace_back([&, t]() {
            for (uint32_t i = t; i < n; i += threads) body(i);
        });
    }
    for (auto& th : pool) th.join();
}

class HostBackend : public Backend {
public:
    HostBackend(const ParamMap& params, uint32_t num_envs, uint32_t rows)
        : params_(params_from(params)), num_envs_(num_envs), rows_(rows) {
        spec_ = spec_for(params_);
        states_.assign((size_t)num_envs_ * rows_, BeaconState{});
        worlds_.assign(num_envs_, BeaconWorld{});
        terminated_.assign((size_t)num_envs_ * rows_, 0);
        reward_.assign((size_t)num_envs_ * rows_, 0.0f);
        mask_.assign((size_t)num_envs_ * rows_ * spec_.num_actions, (uint8_t)0);
        obs_.assign((size_t)num_envs_ * spec_.obs_channels * spec_.obs_width *
                        spec_.obs_height,
                    0.0f);
    }

    const SystemSpec& spec() const override { return spec_; }

    void reset(const uint64_t* seeds) override {
        std::fill(states_.begin(), states_.end(), BeaconState{});
        std::fill(terminated_.begin(), terminated_.end(), 0);
        std::fill(reward_.begin(), reward_.end(), 0.0f);
        std::fill(mask_.begin(), mask_.end(), (uint8_t)0);
        row_ = 0;
        parallel_for(num_envs_, [&](uint32_t env) {
            generate_world(seeds[env], params_, &worlds_[env]);
            initial_state(worlds_[env], params_, &state_at(env, 0));
        });
    }

    void apply_actions(const int32_t* actions) override {
        const uint32_t next = (row_ + 1) % rows_;
        parallel_for(num_envs_, [&](uint32_t env) {
            BeaconState s = state_at(env, row_);
            env_step(worlds_[env], params_, &s, actions[env]);
            states_[(size_t)env * rows_ + next] = s;
            terminated_[(size_t)env * rows_ + next] = (s.outcome != 0) ? 1 : 0;
            reward_[(size_t)env * rows_ + next] = (float)s.last_reward;
        });
        row_ = next;
    }

    void legal_action_mask(bool* out) override {
        parallel_for(num_envs_, [&](uint32_t env) {
            bool bits[kNumActions];
            write_mask(worlds_[env], params_, state_at(env, row_), bits);
            const size_t base = (size_t)env * rows_ * kNumActions + (size_t)row_ * kNumActions;
            for (uint32_t a = 0; a < kNumActions; ++a) {
                mask_[base + a] = (uint8_t)bits[a];
                out[(size_t)env * kNumActions + a] = bits[a];
            }
        });
    }

    void obs(float* out) override {
        const size_t obs_len = (size_t)spec_.obs_channels * spec_.obs_width * spec_.obs_height;
        parallel_for(num_envs_, [&](uint32_t env) {
            const BeaconState& s = state_at(env, row_);
            const BeaconWorld& w = worlds_[env];
            uint32_t index = 0;
            if (s.num_agents > 0) {
                index = acting_index(s.tick, s.turn, w.initiative, s.num_agents);
            }
            int32_t ex = 0, ey = 0;
            if (s.num_agents > 0) {
                cell_of(w, s.pos_x[index], s.pos_y[index], &ex, &ey);
            }
            float* dst = out + (size_t)env * obs_len;
            for (uint32_t cy = 0; cy < spec_.obs_height; ++cy) {
                for (uint32_t cx = 0; cx < spec_.obs_width; ++cx) {
                    obs_cell(w, params_, s, index, ex, ey, (int32_t)cx, (int32_t)cy, dst);
                }
            }
        });
    }

    void reward_and_terminated(float* reward, int32_t* terminated) override {
        for (uint32_t env = 0; env < num_envs_; ++env) {
            reward[env] = reward_[(size_t)env * rows_ + row_];
            terminated[env] = terminated_[(size_t)env * rows_ + row_];
        }
    }

    void serialize_states(uint8_t* out) override {
        parallel_for(num_envs_, [&](uint32_t env) {
            serialize_state(params_, state_at(env, row_),
                            out + (size_t)env * spec_.state_serial_bytes);
        });
    }

    void serialize_worlds(uint8_t* out) override {
        parallel_for(num_envs_, [&](uint32_t env) {
            serialize_world(params_, worlds_[env], out + (size_t)env * spec_.world_serial_bytes);
        });
    }

    uint32_t row() const override { return row_; }

private:
    BeaconState& state_at(uint32_t env, uint32_t r) {
        return states_[(size_t)env * rows_ + r];
    }
    const BeaconState& state_at(uint32_t env, uint32_t r) const {
        return states_[(size_t)env * rows_ + r];
    }

    BeaconParams params_;
    SystemSpec spec_;
    uint32_t num_envs_ = 0;
    uint32_t rows_ = 1;
    uint32_t row_ = 0;
    std::vector<BeaconState> states_;
    std::vector<BeaconWorld> worlds_;
    std::vector<int32_t> terminated_;
    std::vector<float> reward_;
    std::vector<uint8_t> mask_;  // a byte per action: std::vector<bool> would be a bitset
    std::vector<float> obs_;
};

}  // namespace

// The parameters, read from the map by name.
BeaconParams params_from(const ParamMap& params) {
    BeaconParams p;
    get_param(params, "world_w", &p.world_w);
    get_param(params, "world_h", &p.world_h);
    get_param(params, "cell_units", &p.cell_units);
    get_param(params, "squads", &p.squads);
    get_param(params, "squad_size", &p.squad_size);
    get_param(params, "num_beacons", &p.num_beacons);
    get_param(params, "speed_upt", &p.speed_upt);
    get_param(params, "view_range_cells", &p.view_range_cells);
    get_param(params, "tag_range_units", &p.tag_range_units);
    get_param(params, "stun_ticks", &p.stun_ticks);
    get_param(params, "beacon_radius_units", &p.beacon_radius_units);
    get_param(params, "win_score", &p.win_score);
    get_param(params, "time_limit_ticks", &p.time_limit_ticks);
    get_param(params, "axis_swap_ticks", &p.axis_swap_ticks);
    get_param(params, "wall_density_pct", &p.wall_density_pct);
    get_param(params, "cover_density_pct", &p.cover_density_pct);
    // The roster has to fit the POD.
    if (p.squads > kMaxSquads) p.squads = kMaxSquads;
    if (p.squad_size > kMaxAgents) p.squad_size = kMaxAgents;
    while ((uint32_t)p.squads * (uint32_t)p.squad_size > kMaxAgents && p.squad_size > 1) {
        p.squad_size = (uint8_t)(p.squad_size - 1);
    }
    if (p.num_beacons > kMaxBeacons) p.num_beacons = kMaxBeacons;
    if (p.world_w == 0) p.world_w = 1;
    if (p.world_h == 0) p.world_h = 1;
    if ((uint32_t)p.world_w * (uint32_t)p.world_h > kMaxCells) {
        p.world_w = (uint16_t)kMaxCells;
        p.world_h = 1;
    }
    if (p.cell_units == 0) p.cell_units = 1;
    return p;
}

// The spec of the system for the given parameters.
SystemSpec spec_for(const BeaconParams& p) {
    SystemSpec s;
    s.name = "beacons";
    s.num_actions = kNumActions;
    s.obs_channels = kObsChannels;
    s.obs_width = p.world_w;
    s.obs_height = p.world_h;
    s.obs_history = false;
    s.state_bytes = (uint32_t)sizeof(BeaconState);
    s.state_serial_bytes = state_serial_size(p);
    s.world_bytes = (uint32_t)sizeof(BeaconWorld);
    s.world_serial_bytes = world_serial_size(p);
    return s;
}

std::unique_ptr<Backend> make_host_backend(const ParamMap& params, uint32_t num_envs,
                                            uint32_t rows) {
    return std::unique_ptr<Backend>(new HostBackend(params, num_envs, rows));
}

}  // namespace beacons
}  // namespace pysim
