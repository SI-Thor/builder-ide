// The world generator: the seed-grown, mirrored, connectivity-guaranteed grid.
//
// Ported from last-mile's `world/gen.rs` (read-only).
//
// The map is point-symmetric under a 180 degree rotation, so neither squad
// can be dealt a luckier board. Walls and cover are grown in the top half
// from the worldgen RNG stream and mirrored onto the bottom half; spawns and
// beacons sit at pinned, symmetric positions; and a repair pass carves Floor
// corridors until every spawn and beacon is reachable from spawn 0, so no
// seed can wall the round off.
//
// The generator runs on the **host**, in both backends: it is a one-off cost
// per rollout, its connectivity repair is a serial flood fill that does not
// parallelise across the worlds, and one host implementation means the CPU
// and the GPU batch start from literally the same bytes. The Python
// reference grows its own world from the same seed, so the generator is
// still covered by the equality gate.

#pragma once

#include <algorithm>
#include <cstring>
#include <vector>

#include "core/sim/systems/beacons/rules.cuh"

namespace pysim {
namespace beacons {

// Squad 0 spawns this far from the top-left corner; the plan pins (2, 2).
constexpr uint16_t kSpawnEdge = 2;
// The smallest wall-block side, in cells; the sides span 2..=6.
constexpr uint32_t kWallSideMin = 2;
constexpr uint32_t kWallSideSpan = 5;

// The cells reachable from `start` through 4-connected walkable cells.
inline void flood_from(const BeaconWorld& world, uint32_t sx, uint32_t sy,
                       std::vector<uint8_t>& reached) {
    reached.assign((size_t)world.w * (size_t)world.h, 0);
    if (sx >= world.w || sy >= world.h) return;
    std::vector<uint32_t> stack;
    stack.push_back(sy * (uint32_t)world.w + sx);
    reached[sy * (size_t)world.w + sx] = 1;
    while (!stack.empty()) {
        const uint32_t c = stack.back();
        stack.pop_back();
        const int32_t cx = (int32_t)(c % world.w);
        const int32_t cy = (int32_t)(c / world.w);
        static const int32_t kStepX[4] = {-1, 1, 0, 0};
        static const int32_t kStepY[4] = {0, 0, -1, 1};
        for (int d = 0; d < 4; ++d) {
            const int32_t nx = cx + kStepX[d];
            const int32_t ny = cy + kStepY[d];
            if (!in_bounds(world, nx, ny)) continue;
            const size_t ni = (size_t)ny * world.w + (size_t)nx;
            if (reached[ni]) continue;
            if (!walkable(world, nx, ny)) continue;
            reached[ni] = 1;
            stack.push_back((uint32_t)ni);
        }
    }
}

// Floor a cell and its 180 degree mirror in one go, keeping the symmetry.
inline void carve_cell(BeaconWorld* world, int32_t x, int32_t y) {
    set_cell(*world, x, y, kFloor);
    int32_t mx, my;
    mirror_of(*world, x, y, &mx, &my);
    set_cell(*world, mx, my, kFloor);
}

// Carve a mirrored, L-shaped Floor corridor from `cell` to the nearest
// reached cell (Manhattan distance, ties to the lowest row-major cell): the
// x leg runs along `cell.y`, then the y leg at the target's x.
inline void carve_to_nearest(BeaconWorld* world, int32_t cx, int32_t cy,
                             const std::vector<uint8_t>& reached) {
    bool have = false;
    uint32_t best_d = 0;
    int32_t tx = 0, ty = 0;
    for (uint32_t y = 0; y < world->h; ++y) {
        for (uint32_t x = 0; x < world->w; ++x) {
            if (!reached[(size_t)y * world->w + x]) continue;
            const uint32_t d = (x > (uint32_t)cx ? x - (uint32_t)cx : (uint32_t)cx - x) +
                               (y > (uint32_t)cy ? y - (uint32_t)cy : (uint32_t)cy - y);
            if (!have || d < best_d) {
                have = true;
                best_d = d;
                tx = (int32_t)x;
                ty = (int32_t)y;
            }
        }
    }
    if (!have) return;
    const int32_t x0 = (cx <= tx) ? cx : tx;
    const int32_t x1 = (cx <= tx) ? tx : cx;
    for (int32_t x = x0; x <= x1; ++x) carve_cell(world, x, cy);
    const int32_t y0 = (cy <= ty) ? cy : ty;
    const int32_t y1 = (cy <= ty) ? ty : cy;
    for (int32_t y = y0; y <= y1; ++y) carve_cell(world, tx, y);
}

// Force a cell's 3x3 neighbourhood to Floor, clipped at the borders.
inline void clear_neighbourhood(BeaconWorld* world, int32_t cx, int32_t cy) {
    for (int32_t dy = -1; dy <= 1; ++dy) {
        for (int32_t dx = -1; dx <= 1; ++dx) {
            set_cell(*world, cx + dx, cy + dy, kFloor);
        }
    }
}

// Grow the round's world from `seed` under the shape and density `params`.
inline void generate_world(uint64_t seed, const BeaconParams& p, BeaconWorld* world) {
    // The whole world is zeroed first, so the entries the generator does not
    // use (an odd beacon count) are still canonical bytes. The memset comes
    // before the dimensions are set: zeroing afterwards would leave the world
    // with no cells at all.
    std::memset(world, 0, sizeof(*world));
    std::memset(world->cells, kFloor, sizeof(world->cells));
    world->w = p.world_w;
    world->h = p.world_h;
    world->cell_units = p.cell_units;
    world->beacon_count = 0;
    world->spawn_count = 0;
    if (p.world_w == 0 || p.world_h == 0) return;

    SplitMix64 rng = rng_stream(seed, kDomainWorldgen, 0);
    const uint32_t W = p.world_w;
    const uint32_t H = p.world_h;
    const uint32_t half = H / 2;
    const uint32_t half_cells = W * half;
    const uint32_t attempt_cap = W * H;

    // Walls: rectangular blocks of 2..=6 cells per side, placed in the top
    // half until it carries `wall_density_pct`.
    const uint32_t wall_target = (uint32_t)(((uint64_t)half_cells * p.wall_density_pct) / 100);
    uint32_t walls = 0;
    uint32_t attempts = 0;
    while (walls < wall_target && attempts < attempt_cap) {
        ++attempts;
        const uint32_t sx = kWallSideMin + rng.below(kWallSideSpan);
        const uint32_t sy = kWallSideMin + rng.below(kWallSideSpan);
        const uint32_t x0 = rng.below(W);
        const uint32_t y0 = rng.below(half);
        const uint32_t x1 = std::min(x0 + sx, W);
        const uint32_t y1 = std::min(y0 + sy, half);
        for (uint32_t y = y0; y < y1; ++y) {
            for (uint32_t x = x0; x < x1; ++x) {
                if (cell_at(*world, (int32_t)x, (int32_t)y) == kFloor) {
                    set_cell(*world, (int32_t)x, (int32_t)y, kWall);
                    ++walls;
                }
            }
        }
    }

    // Cover: single scattered cells on still-Floor ground.
    const uint32_t cover_target =
        (uint32_t)(((uint64_t)half_cells * p.cover_density_pct) / 100);
    uint32_t covers = 0;
    attempts = 0;
    while (covers < cover_target && attempts < attempt_cap) {
        ++attempts;
        const uint32_t x = rng.below(W);
        const uint32_t y = rng.below(half);
        if (cell_at(*world, (int32_t)x, (int32_t)y) == kFloor) {
            set_cell(*world, (int32_t)x, (int32_t)y, kCover);
            ++covers;
        }
    }

    // Mirror the top half onto the bottom half by 180 degree rotation.
    for (uint32_t y = half; y < H; ++y) {
        for (uint32_t x = 0; x < W; ++x) {
            int32_t mx, my;
            mirror_of(*world, (int32_t)x, (int32_t)y, &mx, &my);
            set_cell(*world, (int32_t)x, (int32_t)y, cell_at(*world, mx, my));
        }
    }

    // Spawns: squad 0 at (2, 2) and squad 1 at its 180 degree mirror.
    // Further squads stack in further mirrored pairs.
    const uint32_t top = (half > 0) ? (half - 1) : 0;
    for (uint32_t s = 0; s < p.squads && s < kMaxSquads; ++s) {
        const int32_t bx = (int32_t)std::min<uint32_t>(kSpawnEdge, W - 1);
        const int32_t by = (int32_t)std::min<uint32_t>(kSpawnEdge + (uint32_t)(s / 2), top);
        if (s % 2 == 0) {
            world->spawns[s] = pack_cell((uint16_t)bx, (uint16_t)by);
        } else {
            int32_t mx, my;
            mirror_of(*world, bx, by, &mx, &my);
            world->spawns[s] = pack_cell((uint16_t)mx, (uint16_t)my);
        }
        ++world->spawn_count;
    }

    // Beacons: every beacon comes with its 180 degree rotated partner, so
    // the beacon set is point-symmetric exactly like the grid. Pair 0
    // straddles the centre.
    const uint32_t pairs = (uint32_t)p.num_beacons / 2;
    const uint32_t cx = W / 2;
    const uint32_t cy = H / 2;
    for (uint32_t k = 0; k < pairs; ++k) {
        if (world->beacon_count + 2 > kMaxBeacons) break;
        const uint32_t x = (k == 0) ? cx : (W / 2) * k / pairs;
        const int32_t by = (int32_t)((cy > 0) ? (cy - 1) : 0);
        world->beacons[world->beacon_count++] = pack_cell((uint16_t)x, (uint16_t)by);
        int32_t mx, my;
        mirror_of(*world, (int32_t)x, by, &mx, &my);
        world->beacons[world->beacon_count++] = pack_cell((uint16_t)mx, (uint16_t)my);
    }

    // No spawn or beacon may start walled or blinded: force it and its 3x3
    // neighbourhood -- and each counterpart's -- to Floor.
    std::vector<uint32_t> required;
    for (uint32_t s = 0; s < world->spawn_count; ++s) required.push_back(world->spawns[s]);
    for (uint32_t b = 0; b < world->beacon_count; ++b) required.push_back(world->beacons[b]);
    for (size_t i = 0; i < required.size(); ++i) {
        const int32_t cxr = (int32_t)cell_x(required[i]);
        const int32_t cyr = (int32_t)cell_y(required[i]);
        int32_t mx, my;
        mirror_of(*world, cxr, cyr, &mx, &my);
        clear_neighbourhood(world, cxr, cyr);
        clear_neighbourhood(world, mx, my);
    }

    // Connectivity repair: flood from spawn 0, and while any required cell
    // is missing, carve a mirrored L-shaped Floor corridor from the first
    // missing cell to the nearest reached cell.
    if (world->spawn_count > 0) {
        const int32_t source_x = (int32_t)cell_x(world->spawns[0]);
        const int32_t source_y = (int32_t)cell_y(world->spawns[0]);
        std::vector<uint8_t> reached;
        for (;;) {
            flood_from(*world, (uint32_t)source_x, (uint32_t)source_y, reached);
            bool found = false;
            int32_t fx = 0, fy = 0;
            for (size_t i = 0; i < required.size(); ++i) {
                const int32_t rx = (int32_t)cell_x(required[i]);
                const int32_t ry = (int32_t)cell_y(required[i]);
                if (!reached[(size_t)ry * W + (size_t)rx]) {
                    found = true;
                    fx = rx;
                    fy = ry;
                    break;
                }
            }
            if (!found) break;
            carve_to_nearest(world, fx, fy, reached);
        }
    }

    // The rotation the acting order starts from: the seed is mixed through
    // the canonical hash, so the initiative spreads evenly over the phases.
    Fnv64 h;
    h.u64(seed);
    const uint32_t n = (uint32_t)p.squads * (uint32_t)p.squad_size;
    world->initiative = (n == 0) ? 0 : (uint32_t)((h.finish() >> 32) % (uint64_t)n);
}

// The initial state of a round: the agents on their spawns, the score at
// zero, no beacon held, the round running.
inline void initial_state(const BeaconWorld& world, const BeaconParams& p, BeaconState* s) {
    std::memset(s, 0, sizeof(*s));
    s->tick = 0;
    s->turn = 0;
    s->outcome = 0;
    s->winner = -1;
    s->num_agents = (uint32_t)p.squads * (uint32_t)p.squad_size;
    if (s->num_agents > kMaxAgents) s->num_agents = kMaxAgents;
    for (uint32_t squad = 0; squad < p.squads; ++squad) s->scores[squad] = 0;
    for (uint32_t b = 0; b < p.num_beacons; ++b) s->holders[b] = -1;
    uint32_t id = 0;
    for (uint32_t squad = 0; squad < p.squads; ++squad) {
        for (uint32_t k = 0; k < p.squad_size; ++k, ++id) {
            if (id >= kMaxAgents) break;
            s->agent_squad[id] = (uint8_t)squad;
            s->agent_id[id] = (uint8_t)id;
            s->stunned[id] = 0;
            s->stunned_until[id] = 0;
            int64_t px = 0, py = 0;
            if (squad < world.spawn_count) {
                cell_center(world, (int32_t)cell_x(world.spawns[squad]),
                            (int32_t)cell_y(world.spawns[squad]), &px, &py);
            }
            s->pos_x[id] = px;
            s->pos_y[id] = py;
        }
    }
}

}  // namespace beacons
}  // namespace pysim
