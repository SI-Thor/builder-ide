// The kernel contract: what every rule system supplies to the container.
//
// The five launches are the ones the design names (docs/design/batched-sim.md
// §1.2), and the rules that came with them from the Stratego port are not
// negotiable:
//
//   - the legal-action mask is written by the **rules engine**, never
//     re-derived by the policy;
//   - the observation is written from the acting player's point of view, so
//     the plane list does not depend on who is acting;
//   - the tensors the backend hands back are **cloned** by the binding,
//     because the backend reuses its buffers.
//
// A rule system registers itself here by name, and the binding asks for a
// backend by that name. Every system supplies two backends: the host (CPU)
// one and the CUDA one, over the same rules.

#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pysim {

// What a rule system tells the container about itself.
struct SystemSpec {
    std::string name;
    uint32_t num_actions = 0;   // A
    uint32_t obs_channels = 0;  // C
    uint32_t obs_width = 0;     // W
    uint32_t obs_height = 0;    // H
    bool obs_history = false;   // does the system keep the observation per row?
    uint32_t state_bytes = 0;         // the size of the POD
    uint32_t state_serial_bytes = 0;  // the canonical byte encoding
    uint32_t world_bytes = 0;
    uint32_t world_serial_bytes = 0;
};

// The parameters a system takes, by name. Every system applies its own
// defaults for the keys it does not find.
using ParamMap = std::map<std::string, double>;

// The kernel contract. One implementation per backend: the host (CPU) one
// and the CUDA one.
class Backend {
public:
    virtual ~Backend() = default;

    virtual const SystemSpec& spec() const = 0;

    // The initial state of every world, from its seed.
    virtual void reset(const uint64_t* seeds) = 0;

    // One ply for every world.
    virtual void apply_actions(const int32_t* actions) = 0;

    // The legal-action mask of the live row: num_envs * A booleans.
    virtual void legal_action_mask(bool* out) = 0;

    // The observation planes of the live row: num_envs * C * H * W floats.
    virtual void obs(float* out) = 0;

    // The reward and the terminated flag of the live row.
    virtual void reward_and_terminated(float* reward, int32_t* terminated) = 0;

    // The canonical byte encoding of every world and every state, for the
    // trajectory proof. The encoding is little-endian and fixed-width, so
    // two machines that agree on the state agree on the bytes.
    virtual void serialize_states(uint8_t* out) = 0;
    virtual void serialize_worlds(uint8_t* out) = 0;

    // The row the live state is in.
    virtual uint32_t row() const = 0;
};

// A backend factory: the system builds its backend for the given shape.
using BackendFactory =
    std::function<std::unique_ptr<Backend>(const ParamMap&, uint32_t num_envs, uint32_t rows)>;

// Register a system. Called once per system at module load.
void register_system(const SystemSpec& spec, BackendFactory host_factory,
                     BackendFactory cuda_factory);

// Every registered system, by name.
std::vector<SystemSpec> registered_systems();

// Build a backend by name. Throws when the name is unknown.
std::unique_ptr<Backend> make_backend(const std::string& name, const ParamMap& params,
                                       uint32_t num_envs, uint32_t rows, bool cuda);

}  // namespace pysim
