// Every rule system's registration, in one place.

#pragma once

namespace pysim {
namespace systems {

// Register every rule system into the registry. Called once, at module load.
void register_all_systems();

}  // namespace systems
}  // namespace pysim
