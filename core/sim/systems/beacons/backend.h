// The Beacons backend: the parameters, the spec and the two factories.

#pragma once

#include <memory>

#include "core/sim/kernels.h"
#include "core/sim/systems/beacons/state.h"

namespace pysim {
namespace beacons {

// The parameters, read from the map by name. The defaults are last-mile's.
BeaconParams params_from(const ParamMap& params);

// The spec of the system for the given parameters.
SystemSpec spec_for(const BeaconParams& p);

// Register the Beacons system into the registry.
void register_beacons();

// The host (CPU) backend, over the same rules as the CUDA one.
std::unique_ptr<Backend> make_host_backend(const ParamMap& params, uint32_t num_envs,
                                            uint32_t rows);

// The CUDA backend, over the same rules.
std::unique_ptr<Backend> make_cuda_backend(const ParamMap& params, uint32_t num_envs,
                                            uint32_t rows);

}  // namespace beacons
}  // namespace pysim
