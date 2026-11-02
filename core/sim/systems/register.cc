// The rule systems, registered.

#include "core/sim/systems/register.h"

#include "core/sim/systems/beacons/backend.h"

namespace pysim {
namespace systems {

void register_all_systems() {
    beacons::register_beacons();
}

}  // namespace systems
}  // namespace pysim
