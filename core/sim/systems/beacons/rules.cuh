// The Beacons rules, written once for the host and the device.
//
// This header is the whole game: the hash, the RNG, the grid, the line of
// sight, the motor, the rules tick, the mask and the observation. It is
// compiled by g++ (for the CPU backend) and by nvcc (for the CUDA backend),
// so "the GPU agrees with the CPU" is a property of the *backend* and not of
// a second implementation that might drift.
//
// Ported from last-mile's `crates/lm-core` (read-only). The Rust is the
// reference; the comments here say where each rule comes from, because the
// port has to be checkable against it line by line.
//
// The rules, in the order they run inside one tick of the round:
//
//   1. **Respawn.** An agent whose stun has ended goes back to its squad's
//      spawn (`rules/beacons.rs`, the respawn loop).
//   2. **Tagging.** The agents act in the tick's rotating order. An agent
//      that is not stunned tags the *first* enemy that is not stunned, is
//      within `tag_range_units` and is in line of sight. The target is
//      stunned for `stun_ticks` ticks. A tag never comes back in the same
//      tick, so two agents that can see each other cannot trade tags.
//   3. **Holding.** A beacon is held by the squad that has a living agent
//      inside `beacon_radius_units` of it while no enemy is inside that
//      radius. A beacon two squads stand in is held by nobody. Every held
//      beacon is worth one point per tick.
//   4. **Ending.** The round ends when a squad reaches `win_score` or the
//      tick limit runs out. The higher score wins; a tie is a tie.

#pragma once

#include <cstdint>

#include "core/sim/systems/beacons/state.h"

#if defined(__CUDACC__)
#define BS_HD __host__ __device__
#else
#define BS_HD
#endif

namespace pysim {
namespace beacons {

// The direction of an action: the x and y step of the chosen neighbour.
BS_HD inline int32_t dir_x(uint32_t action) {
    switch (action) {
        case 2: case 3: case 4: return 1;    // north east, east, south east
        case 6: case 7: case 8: return -1;   // south west, west, north west
        default: return 0;                   // hold, north, south
    }
}

BS_HD inline int32_t dir_y(uint32_t action) {
    switch (action) {
        case 1: case 2: case 8: return -1;  // north, north east, north west
        case 4: case 5: case 6: return 1;    // south east, south, south west
        default: return 0;                   // hold, east, west
    }
}

// ---------------------------------------------------------------------------
// The canonical hash (last-mile's `hash.rs`): FNV-1a 64 over explicit
// little-endian encodings, so a hash never depends on the host's endianness.
// ---------------------------------------------------------------------------

struct Fnv64 {
    uint64_t state = 0xcbf29ce484222325ull;

    BS_HD void write_bytes(const uint8_t* bytes, uint32_t n) {
        for (uint32_t i = 0; i < n; ++i) {
            state ^= (uint64_t)bytes[i];
            state *= 0x100000001b3ull;
        }
    }
    BS_HD void u16(uint16_t v) {
        const uint8_t b[2] = {(uint8_t)v, (uint8_t)(v >> 8)};
        write_bytes(b, 2);
    }
    BS_HD void u32(uint32_t v) {
        const uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16),
                              (uint8_t)(v >> 24)};
        write_bytes(b, 4);
    }
    BS_HD void u64(uint64_t v) {
        uint8_t b[8];
        for (int i = 0; i < 8; ++i) b[i] = (uint8_t)(v >> (8 * i));
        write_bytes(b, 8);
    }
    BS_HD uint64_t finish() const { return state; }
};

// ---------------------------------------------------------------------------
// The deterministic RNG (last-mile's `rng.rs`): one SplitMix64 stream per
// (seed, domain, id). There is no thread RNG and no clock, so two machines
// that play the same round draw the same numbers in the same order.
// ---------------------------------------------------------------------------

constexpr uint8_t kDomainWorldgen = 0;

struct SplitMix64 {
    uint64_t state = 0;

    BS_HD uint64_t next_u64() {
        state += 0x9E3779B97F4A7C15ull;
        uint64_t z = state;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    // A value in 0..n, without modulo bias (last-mile's `Rng::below`).
    BS_HD uint32_t below(uint32_t n) {
        if (n == 0) return 0;
        return (uint32_t)(((next_u64() >> 32) * (uint64_t)n) >> 32);
    }
};

BS_HD inline SplitMix64 rng_stream(uint64_t seed, uint8_t domain, uint64_t id) {
    Fnv64 h;
    h.u64(seed);
    h.write_bytes(&domain, 1);
    h.u64(id);
    SplitMix64 r;
    r.state = h.finish();
    return r;
}

// ---------------------------------------------------------------------------
// The grid (last-mile's `world/grid.rs`).
// ---------------------------------------------------------------------------

BS_HD inline bool in_bounds(const BeaconWorld& w, int32_t x, int32_t y) {
    return x >= 0 && y >= 0 && x < (int32_t)w.w && y < (int32_t)w.h;
}

// The cell's kind. Out-of-bounds cells read as a wall, so callers never need
// a bounds branch.
BS_HD inline uint8_t cell_at(const BeaconWorld& w, int32_t x, int32_t y) {
    if (!in_bounds(w, x, y)) return kWall;
    return w.cells[(size_t)y * (size_t)w.w + (size_t)x];
}

BS_HD inline void set_cell(BeaconWorld& w, int32_t x, int32_t y, uint8_t kind) {
    if (in_bounds(w, x, y)) w.cells[(size_t)y * (size_t)w.w + (size_t)x] = kind;
}

BS_HD inline bool walkable(const BeaconWorld& w, int32_t x, int32_t y) {
    return cell_at(w, x, y) != kWall;
}

// The 180 degree rotation about the grid centre.
BS_HD inline void mirror_of(const BeaconWorld& w, int32_t x, int32_t y, int32_t* mx,
                            int32_t* my) {
    *mx = (int32_t)w.w - 1 - x;
    *my = (int32_t)w.h - 1 - y;
}

// Floor division, the way Rust's `i64::div_euclid` does it.
BS_HD inline int64_t floor_div(int64_t a, int64_t b) {
    if (b <= 0) return 0;
    if (a >= 0) return a / b;
    return -((-a + b - 1) / b);
}

// The cell that holds a position, in units. Positions outside the grid
// saturate to the border cell.
BS_HD inline void cell_of(const BeaconWorld& w, int64_t px, int64_t py, int32_t* cx,
                          int32_t* cy) {
    int64_t cu = (int64_t)w.cell_units;
    if (cu < 1) cu = 1;
    int64_t qx = floor_div(px, cu);
    int64_t qy = floor_div(py, cu);
    int64_t max_x = (int64_t)w.w - 1;
    int64_t max_y = (int64_t)w.h - 1;
    if (qx < 0) qx = 0;
    if (qy < 0) qy = 0;
    if (qx > max_x) qx = max_x;
    if (qy > max_y) qy = max_y;
    *cx = (int32_t)qx;
    *cy = (int32_t)qy;
}

// The position at the centre of a cell.
BS_HD inline void cell_center(const BeaconWorld& w, int32_t cx, int32_t cy, int64_t* px,
                               int64_t* py) {
    int64_t cu = (int64_t)w.cell_units;
    *px = (int64_t)cx * cu + cu / 2;
    *py = (int64_t)cy * cu + cu / 2;
}

BS_HD inline int64_t dist2(int64_t ax, int64_t ay, int64_t bx, int64_t by) {
    const int64_t dx = ax - bx;
    const int64_t dy = ay - by;
    return dx * dx + dy * dy;
}

// ---------------------------------------------------------------------------
// The line of sight (last-mile's `world/los.rs`): Bresenham along the classic
// integer walk, always drawn from the lexicographically smaller endpoint, so
// the answer is a function of the unordered pair of cells alone. Walls and
// cover block; the two endpoints are exempt, so an agent standing in cover
// can still see and be seen through it.
// ---------------------------------------------------------------------------

BS_HD inline bool los_clear(const BeaconWorld& w, int32_t ax, int32_t ay, int32_t bx,
                             int32_t by) {
    int32_t x0 = ax, y0 = ay, x1 = bx, y1 = by;
    if (bx < ax || (bx == ax && by < ay)) {
        x0 = bx;
        y0 = by;
        x1 = ax;
        y1 = ay;
    }
    const int32_t dx = x1 > x0 ? (x1 - x0) : (x0 - x1);
    const int32_t ady = y1 > y0 ? (y1 - y0) : (y0 - y1);
    const int32_t dy = -ady;
    const int32_t sx = (x0 < x1) ? 1 : -1;
    const int32_t sy = (y0 < y1) ? 1 : -1;
    int32_t err = dx + dy;
    int32_t x = x0, y = y0;
    bool first = true;
    for (;;) {
        const bool last = (x == x1 && y == y1);
        if (!first && !last) {
            const uint8_t kind = cell_at(w, x, y);
            if (kind == kWall || kind == kCover) return false;
        }
        if (last) break;
        first = false;
        const int32_t e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y += sy;
        }
    }
    return true;
}

// The visibility rule (last-mile's `view.rs`): within `view_range_cells` by
// the Chebyshev distance, the metric of the 8-connected grid, and in sight.
BS_HD inline bool visible(const BeaconWorld& w, int32_t ex, int32_t ey, int32_t tx,
                          int32_t ty, int32_t range) {
    int32_t dx = tx - ex;
    int32_t dy = ty - ey;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    if (dx > range || dy > range) return false;
    return los_clear(w, ex, ey, tx, ty);
}

// ---------------------------------------------------------------------------
// The motor (last-mile's `agent.rs`).
// ---------------------------------------------------------------------------

// Spend up to `budget` units closing the axis distance `d`.
BS_HD inline int64_t axis_step(int64_t d, int64_t* budget) {
    if (d == 0 || *budget <= 0) return 0;
    int64_t step = (d < 0) ? -d : d;
    if (step > *budget) step = *budget;
    *budget -= step;
    return (d < 0) ? -step : step;
}

// Whether the motor leads with y on this tick: the leading axis alternates
// every `axis_swap_ticks` ticks.
BS_HD inline bool leads_with_y(const BeaconParams& p, uint32_t now) {
    return p.axis_swap_ticks != 0 && ((now / (uint32_t)p.axis_swap_ticks) % 2) == 1;
}

// The acting order (last-mile's `sim.rs` `order`): agent
// `(slot + tick % n + initiative) % n` acts in slot `slot` of the tick.
BS_HD inline uint32_t acting_index(uint32_t tick, uint32_t slot, uint32_t initiative,
                                   uint32_t n) {
    if (n == 0) return 0;
    return (slot + tick % n + initiative) % n;
}

// Whether an agent is stunned at this tick: the stun runs from the tick of
// the tag up to (but not including) the tick it ends on.
BS_HD inline bool is_stunned(const BeaconState& s, uint32_t agent, uint32_t now) {
    return s.stunned[agent] != 0 && (uint64_t)now < s.stunned_until[agent];
}

// Walk one motor command: toward the centre of the chosen neighbour cell, at
// most `speed_upt` units per tick, the leading axis first and the leftover
// budget along the other. A step whose destination cell is not walkable is
// refused outright -- the agent never enters a wall, whatever it was told.
//
// The routing (the Jump Point Search route of the real motor) is **not**
// ported: the policy picks the neighbour, so the action space is the
// neighbour move. The kinematics above are the real ones.
BS_HD inline void move_agent(const BeaconWorld& w, const BeaconParams& p, uint32_t now,
                              BeaconState* s, uint32_t agent, int32_t action) {
    if (action <= 0 || action >= (int32_t)kNumActions) return;  // hold
    int32_t cx, cy;
    cell_of(w, s->pos_x[agent], s->pos_y[agent], &cx, &cy);
    const int32_t nx = cx + dir_x((uint32_t)action);
    const int32_t ny = cy + dir_y((uint32_t)action);
    if (!in_bounds(w, nx, ny)) return;
    if (!walkable(w, nx, ny)) return;
    int64_t tx, ty;
    cell_center(w, nx, ny, &tx, &ty);
    int64_t budget = (p.speed_upt > 0) ? (int64_t)p.speed_upt : 0;
    const int64_t px = s->pos_x[agent];
    const int64_t py = s->pos_y[agent];
    const int64_t dx = tx - px;
    const int64_t dy = ty - py;
    int64_t nx_units = px;
    int64_t ny_units = py;
    if (leads_with_y(p, now)) {
        ny_units = py + axis_step(dy, &budget);
        nx_units = px + axis_step(dx, &budget);
    } else {
        nx_units = px + axis_step(dx, &budget);
        ny_units = py + axis_step(dy, &budget);
    }
    int32_t ncx, ncy;
    cell_of(w, nx_units, ny_units, &ncx, &ncy);
    if (!walkable(w, ncx, ncy)) return;
    s->pos_x[agent] = nx_units;
    s->pos_y[agent] = ny_units;
}

// ---------------------------------------------------------------------------
// The rules tick (last-mile's `rules/beacons.rs`).
// ---------------------------------------------------------------------------

BS_HD inline void rules_tick(const BeaconWorld& w, const BeaconParams& p, BeaconState* s,
                              uint32_t now) {
    if (s->outcome != 0) return;  // the round is over
    const uint32_t n = s->num_agents;

    // 1. A stun that has ended puts its agent back on its spawn.
    for (uint32_t i = 0; i < n; ++i) {
        if (s->stunned[i] == 0) continue;
        if ((uint64_t)now < s->stunned_until[i]) continue;
        s->stunned[i] = 0;
        const uint32_t squad = s->agent_squad[i];
        if (squad < w.spawn_count) {
            int64_t px, py;
            cell_center(w, (int32_t)cell_x(w.spawns[squad]), (int32_t)cell_y(w.spawns[squad]),
                        &px, &py);
            s->pos_x[i] = px;
            s->pos_y[i] = py;
        }
    }

    // 2. Tagging, in the tick's rotating order. `tagged` holds the agents
    //    that were tagged during this tick: a tag never comes back in the
    //    same tick, so two agents that can see each other cannot trade tags.
    bool tagged[kMaxAgents];
    for (uint32_t i = 0; i < kMaxAgents; ++i) tagged[i] = false;
    const int64_t tag_range2 = (int64_t)p.tag_range_units * (int64_t)p.tag_range_units;
    for (uint32_t slot = 0; slot < n; ++slot) {
        const uint32_t index = acting_index(now, slot, w.initiative, n);
        if (is_stunned(*s, index, now)) continue;
        if (tagged[index]) continue;
        int32_t tcx, tcy;
        cell_of(w, s->pos_x[index], s->pos_y[index], &tcx, &tcy);
        int32_t target = -1;
        for (uint32_t j = 0; j < n; ++j) {
            if (j == index) continue;
            if (s->agent_squad[j] == s->agent_squad[index]) continue;
            if (is_stunned(*s, j, now)) continue;
            if (tagged[j]) continue;
            if (dist2(s->pos_x[index], s->pos_y[index], s->pos_x[j], s->pos_y[j]) > tag_range2) {
                continue;
            }
            int32_t ocx, ocy;
            cell_of(w, s->pos_x[j], s->pos_y[j], &ocx, &ocy);
            if (!los_clear(w, tcx, tcy, ocx, ocy)) continue;
            target = (int32_t)j;
            break;
        }
        if (target >= 0) {
            s->stunned[target] = 1;
            s->stunned_until[target] = (uint64_t)now + (uint64_t)p.stun_ticks;
            tagged[target] = true;
        }
    }

    // 3. Holding: a beacon belongs to the squad that has a living agent
    //    inside the radius while no enemy is inside it.
    const int64_t radius2 =
        (int64_t)p.beacon_radius_units * (int64_t)p.beacon_radius_units;
    for (uint32_t b = 0; b < w.beacon_count; ++b) {
        int64_t bpx, bpy;
        cell_center(w, (int32_t)cell_x(w.beacons[b]), (int32_t)cell_y(w.beacons[b]), &bpx,
                    &bpy);
        int8_t holder = -1;
        for (uint32_t squad = 0; squad < p.squads; ++squad) {
            bool ours = false;
            bool enemy_near = false;
            for (uint32_t i = 0; i < n; ++i) {
                if (is_stunned(*s, i, now)) continue;
                if (dist2(s->pos_x[i], s->pos_y[i], bpx, bpy) > radius2) continue;
                if (s->agent_squad[i] == squad) {
                    ours = true;
                } else {
                    enemy_near = true;
                }
            }
            if (!ours) continue;
            // At most one squad can get here: two squads inside the radius
            // would each see the other one as an enemy.
            if (!enemy_near) holder = (int8_t)squad;
        }
        s->holders[b] = holder;
        if (holder >= 0) s->scores[holder] += 1;
    }

    // 4. The round ends on the score or on the clock.
    bool reached_score = false;
    for (uint32_t squad = 0; squad < p.squads; ++squad) {
        if (s->scores[squad] >= (int32_t)p.win_score) reached_score = true;
    }
    const bool out_of_time = now >= p.time_limit_ticks;
    if (reached_score || out_of_time) {
        // The squad with the strictly highest score; none when they tie.
        int32_t best_index = -1;
        int32_t best = 0;
        bool tied = false;
        for (uint32_t squad = 0; squad < p.squads; ++squad) {
            const int32_t score = s->scores[squad];
            if (best_index < 0) {
                best_index = (int32_t)squad;
                best = score;
            } else if (score > best) {
                best_index = (int32_t)squad;
                best = score;
                tied = false;
            } else if (score == best) {
                tied = true;
            }
        }
        s->outcome = 1;
        s->winner = tied ? (int8_t)-1 : (int8_t)best_index;
    }
}

// ---------------------------------------------------------------------------
// The env step: one acting agent's turn.
//
// The real round's tick runs the agents in a rotating order and then the
// rules. This env is one *acting agent's* turn, so a round of n agents takes
// n steps per tick: the rules run when the rotation wraps, which is exactly
// where the real tick puts them (last-mile's `sim.rs`: the agents, then the
// rules).
// ---------------------------------------------------------------------------

BS_HD inline void env_step(const BeaconWorld& w, const BeaconParams& p, BeaconState* s,
                            int32_t action) {
    const uint32_t n = s->num_agents;
    if (n == 0) return;
    if (s->outcome != 0) {
        s->last_reward = 0;
        return;  // the round is over: nothing else happens
    }
    const uint32_t index = acting_index(s->tick, s->turn, w.initiative, n);
    if (!is_stunned(*s, index, s->tick)) {
        move_agent(w, p, s->tick, s, index, action);
    }
    s->turn += 1;
    if (s->turn >= n) {
        s->turn = 0;
        int32_t before[kMaxSquads];
        for (uint32_t squad = 0; squad < kMaxSquads; ++squad) before[squad] = s->scores[squad];
        rules_tick(w, p, s, s->tick);
        s->tick += 1;
        // The reward is what the acting agent's squad scored this step.
        const uint32_t squad = s->agent_squad[index];
        s->last_reward = (squad < kMaxSquads) ? (s->scores[squad] - before[squad]) : 0;
    } else {
        s->last_reward = 0;
    }
}

// ---------------------------------------------------------------------------
// The legal-action mask, written by the rules engine.
//
// Hold is always legal; a move is legal when the neighbour cell is in bounds
// and walkable. A stunned agent may only hold, because the real motor holds
// while stunned (`agent.rs` `choose_cmd`).
// ---------------------------------------------------------------------------

BS_HD inline void write_mask(const BeaconWorld& w, const BeaconParams& p,
                              const BeaconState& s, bool* out) {
    const uint32_t n = s.num_agents;
    if (n == 0) {
        for (uint32_t a = 0; a < kNumActions; ++a) out[a] = false;
        return;
    }
    const uint32_t index = acting_index(s.tick, s.turn, w.initiative, n);
    const bool stunned = is_stunned(s, index, s.tick);
    out[0] = true;  // hold
    int32_t cx, cy;
    cell_of(w, s.pos_x[index], s.pos_y[index], &cx, &cy);
    for (uint32_t a = 1; a < kNumActions; ++a) {
        if (stunned) {
            out[a] = false;
            continue;
        }
        const int32_t nx = cx + dir_x(a);
        const int32_t ny = cy + dir_y(a);
        out[a] = in_bounds(w, nx, ny) && walkable(w, nx, ny);
    }
}

// ---------------------------------------------------------------------------
// The observation, from the acting agent's own eyes.
//
// The planes, in manifest order:
//
//   0 visible       1 where the cell is in sight, 0 elsewhere
//   1 terrain       0 unknown, 1 floor, 2 wall, 3 cover
//   2 beacon        0 no beacon, 1 a beacon nobody holds, 2 + squad held it
//   3 self          1 where the acting agent stands
//   4 ally          1 where a visible squadmate stands
//   5 enemy         1 where a visible enemy stands
//
// The agent planes are masked by the visibility, so an enemy in an unseen
// cell is not leaked by its own plane.
// ---------------------------------------------------------------------------

BS_HD inline void obs_cell(const BeaconWorld& w, const BeaconParams& p, const BeaconState& s,
                            uint32_t index, int32_t ex, int32_t ey, int32_t cx, int32_t cy,
                            float* out) {
    const uint32_t W = w.w;
    const uint32_t H = w.h;
    const size_t plane = (size_t)H * (size_t)W;
    const size_t cell = (size_t)cy * (size_t)W + (size_t)cx;
    int32_t range = (int32_t)p.view_range_cells;
    const int32_t widest = (int32_t)(W > H ? W : H);
    if (range > widest) range = widest;

    const bool vis = visible(w, ex, ey, cx, cy, range);
    out[(size_t)kPlaneVisible * plane + cell] = vis ? 1.0f : 0.0f;
    float terrain = 0.0f;
    if (vis) {
        const uint8_t kind = cell_at(w, cx, cy);
        terrain = (kind == kWall) ? 2.0f : ((kind == kCover) ? 3.0f : 1.0f);
    }
    out[(size_t)kPlaneTerrain * plane + cell] = terrain;

    float beacon = 0.0f;
    for (uint32_t b = 0; b < w.beacon_count; ++b) {
        if ((int32_t)cell_x(w.beacons[b]) != cx) continue;
        if ((int32_t)cell_y(w.beacons[b]) != cy) continue;
        beacon = (s.holders[b] < 0) ? 1.0f : (2.0f + (float)s.holders[b]);
        break;
    }
    out[(size_t)kPlaneBeacon * plane + cell] = vis ? beacon : 0.0f;

    float self = 0.0f;
    float ally = 0.0f;
    float enemy = 0.0f;
    if (vis) {
        for (uint32_t i = 0; i < s.num_agents; ++i) {
            int32_t ax, ay;
            cell_of(w, s.pos_x[i], s.pos_y[i], &ax, &ay);
            if (ax != cx || ay != cy) continue;
            if (i == index) {
                self = 1.0f;
            } else if (s.agent_squad[i] == s.agent_squad[index]) {
                ally = 1.0f;
            } else {
                enemy = 1.0f;
            }
        }
    }
    out[(size_t)kPlaneSelf * plane + cell] = self;
    out[(size_t)kPlaneAlly * plane + cell] = ally;
    out[(size_t)kPlaneEnemy * plane + cell] = enemy;
}

// ---------------------------------------------------------------------------
// The canonical byte encoding, for the trajectory proof.
//
// Little-endian, fixed width, no padding: two machines that agree on the
// state agree on the bytes, and the Python reference can be compared with
// the GPU byte for byte.
// ---------------------------------------------------------------------------

struct ByteWriter {
    uint8_t* p;
    BS_HD void u8(uint8_t v) { *p++ = v; }
    BS_HD void u16(uint16_t v) {
        *p++ = (uint8_t)v;
        *p++ = (uint8_t)(v >> 8);
    }
    BS_HD void u32(uint32_t v) {
        for (int i = 0; i < 4; ++i) *p++ = (uint8_t)(v >> (8 * i));
    }
    BS_HD void u64(uint64_t v) {
        for (int i = 0; i < 8; ++i) *p++ = (uint8_t)(v >> (8 * i));
    }
    BS_HD void i32(int32_t v) { u32((uint32_t)v); }
    BS_HD void i64(int64_t v) { u64((uint64_t)v); }
};

BS_HD inline uint32_t state_serial_size(const BeaconParams& p) {
    // The header (tick, turn, num_agents, outcome, winner, last_reward: 18
    // bytes), the scores, the holders, and 27 bytes an agent (squad, id,
    // stunned, stunned_until, pos_x, pos_y).
    return 18 + 4 * (uint32_t)p.squads + (uint32_t)p.num_beacons +
           27 * (uint32_t)(p.squads * p.squad_size);
}

BS_HD inline uint32_t world_serial_size(const BeaconParams& p) {
    return 2 + 2 + 4 + 4 + 2 + 2 + 4 * (uint32_t)p.num_beacons +
           4 * (uint32_t)p.squads + (uint32_t)p.world_w * (uint32_t)p.world_h;
}

BS_HD inline void serialize_state(const BeaconParams& p, const BeaconState& s, uint8_t* out) {
    ByteWriter w{out};
    w.u32(s.tick);
    w.u32(s.turn);
    w.u32(s.num_agents);
    w.u8(s.outcome);
    w.u8((uint8_t)(int8_t)s.winner);
    w.i32(s.last_reward);
    for (uint32_t squad = 0; squad < p.squads; ++squad) w.i32(s.scores[squad]);
    for (uint32_t b = 0; b < p.num_beacons; ++b) w.u8((uint8_t)(int8_t)s.holders[b]);
    for (uint32_t i = 0; i < s.num_agents; ++i) {
        w.u8(s.agent_squad[i]);
        w.u8(s.agent_id[i]);
        w.u8(s.stunned[i]);
        w.u64(s.stunned_until[i]);
        w.i64(s.pos_x[i]);
        w.i64(s.pos_y[i]);
    }
}

BS_HD inline void serialize_world(const BeaconParams& p, const BeaconWorld& world,
                                  uint8_t* out) {
    ByteWriter w{out};
    w.u16(world.w);
    w.u16(world.h);
    w.u32(world.cell_units);
    w.u32(world.initiative);
    w.u16(world.beacon_count);
    w.u16(world.spawn_count);
    for (uint32_t b = 0; b < p.num_beacons; ++b) w.u32(world.beacons[b]);
    for (uint32_t squad = 0; squad < p.squads; ++squad) w.u32(world.spawns[squad]);
    for (uint32_t i = 0; i < (uint32_t)world.w * (uint32_t)world.h; ++i) w.u8(world.cells[i]);
}

}  // namespace beacons
}  // namespace pysim
