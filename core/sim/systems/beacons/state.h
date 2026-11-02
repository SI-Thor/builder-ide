// The Beacons state: the POD, the parameters and the traits.
//
// Ported from last-mile's `crates/lm-core` (read-only): `rules/beacons.rs`,
// `world/grid.rs`, `world/los.rs`, `world/gen.rs`, `rng.rs`, `hash.rs`,
// `agent.rs` (the motor) and `params.rs`.
//
// Everything here is an integer. No float ever enters the state, which is
// what lets the GPU and the CPU be compared byte for byte.

#pragma once

#include <cstdint>

namespace pysim {
namespace beacons {

// The world's own size: 8 chunks of 32 m at 2 m a cell is 128 x 128 cells.
constexpr uint32_t kMaxCells = 16384;
constexpr uint32_t kMaxBeacons = 8;
constexpr uint32_t kMaxSquads = 4;
constexpr uint32_t kMaxAgents = 16;

// What occupies a cell. The declaration order is the canonical hash order.
enum CellKind : uint8_t {
    kFloor = 0,  // blocks nothing
    kWall = 1,   // blocks movement and sight
    kCover = 2,  // blocks sight only
};

// The action space: hold, and the eight neighbours (north, north east, east,
// south east, south, south west, west, north west). y grows southwards.
//
// The directions are functions rather than a table: a namespace-scope
// constexpr array is not usable from device code, and a switch is.
constexpr uint32_t kNumActions = 9;

// The observation planes, in manifest order.
constexpr uint32_t kObsChannels = 6;
constexpr uint32_t kPlaneVisible = 0;
constexpr uint32_t kPlaneTerrain = 1;
constexpr uint32_t kPlaneBeacon = 2;
constexpr uint32_t kPlaneSelf = 3;
constexpr uint32_t kPlaneAlly = 4;
constexpr uint32_t kPlaneEnemy = 5;

// The parameters of a round. The defaults are last-mile's own.
struct BeaconParams {
    uint16_t world_w = 128;
    uint16_t world_h = 128;
    uint32_t cell_units = 2048;  // fixed-point units per cell edge (2 m)
    uint8_t squads = 2;
    uint8_t squad_size = 4;
    uint8_t num_beacons = 4;
    int32_t speed_upt = 136;  // movement speed in units per tick
    uint16_t view_range_cells = 20;
    int32_t tag_range_units = 2048;
    uint32_t stun_ticks = 90;
    int32_t beacon_radius_units = 4096;
    uint32_t win_score = 1800;
    uint32_t time_limit_ticks = 9000;
    uint16_t axis_swap_ticks = 1;
    uint8_t wall_density_pct = 18;
    uint8_t cover_density_pct = 6;
};

// A cell coordinate, packed so the world serialises canonically.
constexpr uint32_t pack_cell(uint16_t x, uint16_t y) {
    return (uint32_t)x | ((uint32_t)y << 16);
}
constexpr uint16_t cell_x(uint32_t c) { return (uint16_t)(c & 0xffffu); }
constexpr uint16_t cell_y(uint32_t c) { return (uint16_t)(c >> 16); }

// The static part of a world: the grid, the beacons, the spawns.
struct BeaconWorld {
    uint16_t w = 0;
    uint16_t h = 0;
    uint32_t cell_units = 0;
    uint32_t initiative = 0;  // the rotation the acting order starts from
    uint8_t cells[kMaxCells];
    uint32_t beacons[kMaxBeacons];
    uint32_t spawns[kMaxSquads];
    uint16_t beacon_count = 0;
    uint16_t spawn_count = 0;
};

// The dynamic part of a round: the agents, the score, the holders.
struct BeaconState {
    uint32_t tick = 0;   // the rules tick counter
    uint32_t turn = 0;   // the slot in the tick's acting order
    uint32_t num_agents = 0;
    uint8_t outcome = 0;  // 0 running, 1 over
    int8_t winner = -1;   // the squad with the strictly highest score
    int32_t last_reward = 0;
    int32_t scores[kMaxSquads];
    int8_t holders[kMaxBeacons];
    uint8_t agent_squad[kMaxAgents];
    uint8_t agent_id[kMaxAgents];
    uint8_t stunned[kMaxAgents];
    uint64_t stunned_until[kMaxAgents];
    int64_t pos_x[kMaxAgents];
    int64_t pos_y[kMaxAgents];
};

// What the container needs to know about this system.
struct BeaconsTraits {
    using State = BeaconState;
    using World = BeaconWorld;
    static constexpr uint32_t kNumActions = pysim::beacons::kNumActions;
    static constexpr uint32_t kObsChannels = pysim::beacons::kObsChannels;
    static constexpr bool kObsHistory = false;
};

}  // namespace beacons
}  // namespace pysim
