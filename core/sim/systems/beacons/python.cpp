// The Beacons system's registration into `pysim`.

#include "core/sim/systems/beacons/backend.h"

namespace pysim {
namespace beacons {

void register_beacons() {
    // The registry's spec is the default shape; a batch built with other
    // parameters carries its own spec, which the handle reports.
    register_system(spec_for(params_from(ParamMap{})), &make_host_backend,
                    &make_cuda_backend);
}

}  // namespace beacons
}  // namespace pysim
