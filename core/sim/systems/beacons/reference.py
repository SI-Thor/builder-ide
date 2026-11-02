"""The Python reference implementation of the Beacons rules.

This is the **ground truth** of the port. The C++ and CUDA backends are
checked against it byte for byte, so a rule that is wrong here is wrong
everywhere and the check still passes -- which is why this file is written
from the Rust (`~/last-mile/crates/lm-core`, read-only) and not from the C++.

The ported rules are `rules/beacons.rs`, `world/{grid,los,gen}.rs`, `rng.rs`,
`hash.rs`, `agent.rs` (the motor) and `params.rs`. The comments say where each
rule comes from.

One round of Beacons, in the order it runs:

  1. **Respawn.** An agent whose stun has ended goes back to its squad's
     spawn.
  2. **Tagging.** The agents act in the tick's rotating order. An agent that
     is not stunned tags the *first* enemy that is not stunned, is within
     `tag_range_units` and is in line of sight. The target is stunned for
     `stun_ticks` ticks. A tag never comes back in the same tick.
  3. **Holding.** A beacon is held by the squad that has a living agent
     inside `beacon_radius_units` of it while no enemy is inside that radius.
     A beacon two squads stand in is held by nobody. Every held beacon is
     worth one point per tick.
  4. **Ending.** The round ends when a squad reaches `win_score` or the tick
     limit runs out. The higher score wins; a tie is a tie.

The env the batched simulator exposes is one **acting agent's** turn at a
time, so a round of n agents takes n steps per tick.
"""

from __future__ import annotations

import dataclasses
import struct
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "Params",
    "World",
    "State",
    "Round",
    "generate_world",
    "initial_state",
    "Fnv64",
    "SplitMix64",
    "rng_stream",
    "CELL_FLOOR",
    "CELL_WALL",
    "CELL_COVER",
    "DIRECTIONS",
    "NUM_ACTIONS",
    "OBS_CHANNELS",
]

MASK64 = 0xFFFFFFFFFFFFFFFF

CELL_FLOOR = 0
CELL_WALL = 1
CELL_COVER = 2

# The action space: hold, and the eight neighbours (north, north east, east,
# south east, south, south west, west, north west). y grows southwards.
DIRECTIONS = ((0, 0), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
NUM_ACTIONS = len(DIRECTIONS)

OBS_CHANNELS = 6
PLANE_VISIBLE, PLANE_TERRAIN, PLANE_BEACON, PLANE_SELF, PLANE_ALLY, PLANE_ENEMY = range(6)

DOMAIN_WORLDGEN = 0

MAX_CELLS = 16384
MAX_BEACONS = 8
MAX_SQUADS = 4
MAX_AGENTS = 16


# ---------------------------------------------------------------------------
# The canonical hash (last-mile's `hash.rs`): FNV-1a 64 over explicit
# little-endian encodings, so a hash never depends on the host's endianness.
# ---------------------------------------------------------------------------


class Fnv64:
    """FNV-1a 64, little-endian."""

    def __init__(self) -> None:
        self.state = 0xCBF29CE484222325

    def write(self, data: bytes) -> None:
        state = self.state
        for byte in data:
            state ^= byte
            state = (state * 0x100000001B3) & MASK64
        self.state = state

    def u16(self, value: int) -> None:
        self.write(struct.pack("<H", value & 0xFFFF))

    def u32(self, value: int) -> None:
        self.write(struct.pack("<I", value & MASK64))

    def u64(self, value: int) -> None:
        self.write(struct.pack("<Q", value & MASK64))

    def finish(self) -> int:
        return self.state


# ---------------------------------------------------------------------------
# The deterministic RNG (last-mile's `rng.rs`): one SplitMix64 stream per
# (seed, domain, id). No thread RNG, no clock.
# ---------------------------------------------------------------------------


class SplitMix64:
    """The SplitMix64 generator, seeded for one named stream."""

    def __init__(self, state: int) -> None:
        self.state = state & MASK64

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """A value in ``0..n``, without modulo bias."""
        if n == 0:
            return 0
        return ((self.next_u64() >> 32) * n) >> 32


def rng_stream(seed: int, domain: int, ident: int) -> SplitMix64:
    """The stream for ``(seed, domain, id)``."""
    h = Fnv64()
    h.u64(seed)
    h.write(bytes([domain]))
    h.u64(ident)
    return SplitMix64(h.finish())


# ---------------------------------------------------------------------------
# The parameters of a round (last-mile's `params.rs`). The defaults are
# last-mile's own.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Params:
    world_w: int = 128
    world_h: int = 128
    cell_units: int = 2048
    squads: int = 2
    squad_size: int = 4
    num_beacons: int = 4
    speed_upt: int = 136
    view_range_cells: int = 20
    tag_range_units: int = 2048
    stun_ticks: int = 90
    beacon_radius_units: int = 4096
    win_score: int = 1800
    time_limit_ticks: int = 9000
    axis_swap_ticks: int = 1
    wall_density_pct: int = 18
    cover_density_pct: int = 6

    def __post_init__(self) -> None:
        self.squads = min(max(int(self.squads), 1), MAX_SQUADS)
        self.squad_size = min(max(int(self.squad_size), 1), MAX_AGENTS)
        while self.squads * self.squad_size > MAX_AGENTS and self.squad_size > 1:
            self.squad_size -= 1
        self.num_beacons = min(max(int(self.num_beacons), 0), MAX_BEACONS)
        self.world_w = max(int(self.world_w), 1)
        self.world_h = max(int(self.world_h), 1)
        if self.world_w * self.world_h > MAX_CELLS:
            self.world_w = MAX_CELLS
            self.world_h = 1
        self.cell_units = max(int(self.cell_units), 1)


@dataclasses.dataclass
class World:
    """The static part of a world: the grid, the beacons, the spawns."""

    w: int
    h: int
    cell_units: int
    initiative: int
    cells: bytearray
    beacons: List[Tuple[int, int]]
    spawns: List[Tuple[int, int]]


@dataclasses.dataclass
class State:
    """The dynamic part of a round: the agents, the score, the holders."""

    tick: int = 0
    turn: int = 0
    num_agents: int = 0
    outcome: int = 0
    winner: int = -1
    last_reward: int = 0
    scores: List[int] = dataclasses.field(default_factory=list)
    holders: List[int] = dataclasses.field(default_factory=list)
    agent_squad: List[int] = dataclasses.field(default_factory=list)
    agent_id: List[int] = dataclasses.field(default_factory=list)
    stunned: List[int] = dataclasses.field(default_factory=list)
    stunned_until: List[int] = dataclasses.field(default_factory=list)
    pos_x: List[int] = dataclasses.field(default_factory=list)
    pos_y: List[int] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# The grid (last-mile's `world/grid.rs`).
# ---------------------------------------------------------------------------


def in_bounds(world: World, x: int, y: int) -> bool:
    return 0 <= x < world.w and 0 <= y < world.h


def cell_at(world: World, x: int, y: int) -> int:
    """The cell's kind. Out-of-bounds cells read as a wall."""
    if not in_bounds(world, x, y):
        return CELL_WALL
    return world.cells[y * world.w + x]


def set_cell(world: World, x: int, y: int, kind: int) -> None:
    if in_bounds(world, x, y):
        world.cells[y * world.w + x] = kind


def mirror_of(world: World, x: int, y: int) -> Tuple[int, int]:
    """The 180 degree rotation about the grid centre."""
    return world.w - 1 - x, world.h - 1 - y


def cell_of(world: World, px: int, py: int) -> Tuple[int, int]:
    """The cell that holds a position, in units."""
    cu = max(world.cell_units, 1)
    qx = min(max(px // cu, 0), world.w - 1)
    qy = min(max(py // cu, 0), world.h - 1)
    return qx, qy


def cell_center(world: World, cx: int, cy: int) -> Tuple[int, int]:
    """The position at the centre of a cell."""
    cu = world.cell_units
    return cx * cu + cu // 2, cy * cu + cu // 2


def dist2(ax: int, ay: int, bx: int, by: int) -> int:
    dx = ax - bx
    dy = ay - by
    return dx * dx + dy * dy


# ---------------------------------------------------------------------------
# The line of sight (last-mile's `world/los.rs`).
# ---------------------------------------------------------------------------


def los_clear(world: World, ax: int, ay: int, bx: int, by: int) -> bool:
    """Whether the straight line from a to b is unobstructed.

    The walk is drawn from the lexicographically smaller endpoint, so the
    answer is a function of the unordered pair of cells alone. Walls and
    cover block; the two endpoints are exempt.
    """
    if (bx, by) < (ax, ay):
        ax, ay, bx, by = bx, by, ax, ay
    x0, y0, x1, y1 = ax, ay, bx, by
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    first = True
    while True:
        last = x == x1 and y == y1
        if not first and not last:
            kind = cell_at(world, x, y)
            if kind == CELL_WALL or kind == CELL_COVER:
                return False
        if last:
            break
        first = False
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return True


def visible(world: World, ex: int, ey: int, tx: int, ty: int, rng: int) -> bool:
    """The visibility rule (last-mile's `view.rs`)."""
    if abs(tx - ex) > rng or abs(ty - ey) > rng:
        return False
    return los_clear(world, ex, ey, tx, ty)


# ---------------------------------------------------------------------------
# The motor (last-mile's `agent.rs`).
# ---------------------------------------------------------------------------


def axis_step(d: int, budget: int) -> Tuple[int, int]:
    """Spend up to ``budget`` units closing the axis distance ``d``."""
    if d == 0 or budget <= 0:
        return 0, budget
    step = min(abs(d), budget)
    budget -= step
    return (-step if d < 0 else step), budget


def leads_with_y(params: Params, now: int) -> bool:
    """Whether the motor leads with y on this tick."""
    return params.axis_swap_ticks != 0 and (now // params.axis_swap_ticks) % 2 == 1


def acting_index(tick: int, slot: int, initiative: int, n: int) -> int:
    """The acting order: agent ``(slot + tick % n + initiative) % n``."""
    if n == 0:
        return 0
    return (slot + tick % n + initiative) % n


def move_agent(world: World, params: Params, now: int, state: State, agent: int,
               action: int) -> None:
    """Walk one motor command: toward the centre of the chosen neighbour cell.

    The routing (the Jump Point Search route of the real motor) is not
    ported: the policy picks the neighbour. The kinematics -- the speed
    budget, the axis order and the refusal to enter a wall -- are the real
    ones.
    """
    if action <= 0 or action >= NUM_ACTIONS:
        return
    cx, cy = cell_of(world, state.pos_x[agent], state.pos_y[agent])
    dx, dy = DIRECTIONS[action]
    nx, ny = cx + dx, cy + dy
    if not in_bounds(world, nx, ny):
        return
    if cell_at(world, nx, ny) == CELL_WALL:
        return
    tx, ty = cell_center(world, nx, ny)
    px, py = state.pos_x[agent], state.pos_y[agent]
    budget = max(params.speed_upt, 0)
    ddx, ddy = tx - px, ty - py
    if leads_with_y(params, now):
        step_y, budget = axis_step(ddy, budget)
        step_x, budget = axis_step(ddx, budget)
    else:
        step_x, budget = axis_step(ddx, budget)
        step_y, budget = axis_step(ddy, budget)
    newx, newy = px + step_x, py + step_y
    ncx, ncy = cell_of(world, newx, newy)
    if cell_at(world, ncx, ncy) == CELL_WALL:
        return
    state.pos_x[agent] = newx
    state.pos_y[agent] = newy


# ---------------------------------------------------------------------------
# The rules tick (last-mile's `rules/beacons.rs`).
# ---------------------------------------------------------------------------


def is_stunned(state: State, agent: int, now: int) -> bool:
    """The stun runs from the tick of the tag up to the tick it ends on."""
    return bool(state.stunned[agent]) and now < state.stunned_until[agent]


def rules_tick(world: World, params: Params, state: State, now: int) -> None:
    """One tick of the ruleset."""
    if state.outcome:
        return
    n = state.num_agents

    # 1. A stun that has ended puts its agent back on its spawn.
    for i in range(n):
        if not state.stunned[i]:
            continue
        if now < state.stunned_until[i]:
            continue
        state.stunned[i] = 0
        squad = state.agent_squad[i]
        if squad < len(world.spawns):
            state.pos_x[i], state.pos_y[i] = cell_center(world, *world.spawns[squad])

    # 2. Tagging, in the tick's rotating order.
    tagged = set()
    tag_range2 = params.tag_range_units * params.tag_range_units
    for slot in range(n):
        index = acting_index(now, slot, world.initiative, n)
        if is_stunned(state, index, now) or index in tagged:
            continue
        tcx, tcy = cell_of(world, state.pos_x[index], state.pos_y[index])
        target = None
        for j in range(n):
            if j == index or state.agent_squad[j] == state.agent_squad[index]:
                continue
            if is_stunned(state, j, now) or j in tagged:
                continue
            if dist2(state.pos_x[index], state.pos_y[index], state.pos_x[j],
                     state.pos_y[j]) > tag_range2:
                continue
            ocx, ocy = cell_of(world, state.pos_x[j], state.pos_y[j])
            if not los_clear(world, tcx, tcy, ocx, ocy):
                continue
            target = j
            break
        if target is not None:
            state.stunned[target] = 1
            state.stunned_until[target] = now + params.stun_ticks
            tagged.add(target)

    # 3. Holding.
    radius2 = params.beacon_radius_units * params.beacon_radius_units
    for b, beacon in enumerate(world.beacons):
        bpx, bpy = cell_center(world, *beacon)
        holder = -1
        for squad in range(params.squads):
            ours = False
            enemy_near = False
            for i in range(n):
                if is_stunned(state, i, now):
                    continue
                if dist2(state.pos_x[i], state.pos_y[i], bpx, bpy) > radius2:
                    continue
                if state.agent_squad[i] == squad:
                    ours = True
                else:
                    enemy_near = True
            if not ours:
                continue
            if not enemy_near:
                holder = squad
        state.holders[b] = holder
        if holder >= 0:
            state.scores[holder] += 1

    # 4. The round ends on the score or on the clock.
    reached = any(score >= params.win_score for score in state.scores[:params.squads])
    out_of_time = now >= params.time_limit_ticks
    if reached or out_of_time:
        best_index = -1
        best = 0
        tied = False
        for squad in range(params.squads):
            score = state.scores[squad]
            if best_index < 0:
                best_index, best = squad, score
            elif score > best:
                best_index, best = squad, score
                tied = False
            elif score == best:
                tied = True
        state.outcome = 1
        state.winner = -1 if tied else best_index


# ---------------------------------------------------------------------------
# The world generator (last-mile's `world/gen.rs`).
# ---------------------------------------------------------------------------

SPAWN_EDGE = 2
WALL_SIDE_MIN = 2
WALL_SIDE_SPAN = 5


def _flood_from(world: World, sx: int, sy: int) -> bytearray:
    reached = bytearray(world.w * world.h)
    if not in_bounds(world, sx, sy):
        return reached
    stack = [(sx, sy)]
    reached[sy * world.w + sx] = 1
    while stack:
        cx, cy = stack.pop()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if not in_bounds(world, nx, ny):
                continue
            idx = ny * world.w + nx
            if reached[idx] or cell_at(world, nx, ny) == CELL_WALL:
                continue
            reached[idx] = 1
            stack.append((nx, ny))
    return reached


def _carve_cell(world: World, x: int, y: int) -> None:
    set_cell(world, x, y, CELL_FLOOR)
    mx, my = mirror_of(world, x, y)
    set_cell(world, mx, my, CELL_FLOOR)


def _carve_to_nearest(world: World, cx: int, cy: int, reached: bytearray) -> None:
    best = None
    best_d = 0
    for y in range(world.h):
        for x in range(world.w):
            if not reached[y * world.w + x]:
                continue
            d = abs(x - cx) + abs(y - cy)
            if best is None or d < best_d:
                best = (x, y)
                best_d = d
    if best is None:
        return
    tx, ty = best
    for x in range(min(cx, tx), max(cx, tx) + 1):
        _carve_cell(world, x, cy)
    for y in range(min(cy, ty), max(cy, ty) + 1):
        _carve_cell(world, tx, y)


def _clear_neighbourhood(world: World, cx: int, cy: int) -> None:
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            set_cell(world, cx + dx, cy + dy, CELL_FLOOR)


def generate_world(seed: int, params: Params) -> World:
    """Grow the round's world from ``seed``."""
    rng = rng_stream(seed, DOMAIN_WORLDGEN, 0)
    w, h = params.world_w, params.world_h
    cells = bytearray([CELL_FLOOR]) * (w * h)
    world = World(w=w, h=h, cell_units=params.cell_units, initiative=0, cells=cells,
                  beacons=[], spawns=[])
    if w == 0 or h == 0:
        return world

    half = h // 2
    half_cells = w * half
    attempt_cap = w * h

    # Walls: rectangular blocks of 2..=6 cells per side, in the top half.
    wall_target = half_cells * params.wall_density_pct // 100
    walls = 0
    attempts = 0
    while walls < wall_target and attempts < attempt_cap:
        attempts += 1
        sx = WALL_SIDE_MIN + rng.below(WALL_SIDE_SPAN)
        sy = WALL_SIDE_MIN + rng.below(WALL_SIDE_SPAN)
        x0 = rng.below(w)
        y0 = rng.below(half)
        x1 = min(x0 + sx, w)
        y1 = min(y0 + sy, half)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if cell_at(world, x, y) == CELL_FLOOR:
                    set_cell(world, x, y, CELL_WALL)
                    walls += 1

    # Cover: single scattered cells on still-Floor ground.
    cover_target = half_cells * params.cover_density_pct // 100
    covers = 0
    attempts = 0
    while covers < cover_target and attempts < attempt_cap:
        attempts += 1
        x = rng.below(w)
        y = rng.below(half)
        if cell_at(world, x, y) == CELL_FLOOR:
            set_cell(world, x, y, CELL_COVER)
            covers += 1

    # Mirror the top half onto the bottom half by 180 degree rotation.
    for y in range(half, h):
        for x in range(w):
            mx, my = mirror_of(world, x, y)
            set_cell(world, x, y, cell_at(world, mx, my))

    # Spawns: squad 0 at (2, 2) and squad 1 at its 180 degree mirror.
    top = max(half - 1, 0)
    for s in range(params.squads):
        bx = min(SPAWN_EDGE, w - 1)
        by = min(SPAWN_EDGE + s // 2, top)
        world.spawns.append((bx, by) if s % 2 == 0 else mirror_of(world, bx, by))

    # Beacons: every beacon comes with its 180 degree rotated partner.
    pairs = params.num_beacons // 2
    cx, cy = w // 2, h // 2
    for k in range(pairs):
        x = cx if k == 0 else (w // 2) * k // pairs
        a = (x, max(cy - 1, 0))
        world.beacons.append(a)
        world.beacons.append(mirror_of(world, *a))
    while len(world.beacons) < params.num_beacons:
        world.beacons.append((0, 0))

    # No spawn or beacon may start walled or blinded.
    required = list(world.spawns) + list(world.beacons)
    for cell in required:
        _clear_neighbourhood(world, *cell)
        _clear_neighbourhood(world, *mirror_of(world, *cell))

    # Connectivity repair: flood from spawn 0 and carve a mirrored corridor
    # to every required cell until they are all reachable.
    if world.spawns:
        source = world.spawns[0]
        while True:
            reached = _flood_from(world, *source)
            missing = None
            for cell in required:
                if not reached[cell[1] * world.w + cell[0]]:
                    missing = cell
                    break
            if missing is None:
                break
            _carve_to_nearest(world, missing[0], missing[1], reached)

    # The rotation the acting order starts from.
    h64 = Fnv64()
    h64.u64(seed)
    n = params.squads * params.squad_size
    world.initiative = 0 if n == 0 else (h64.finish() >> 32) % n
    return world


def initial_state(world: World, params: Params) -> State:
    """A fresh round: the agents on their spawns, the score at zero."""
    state = State()
    state.num_agents = params.squads * params.squad_size
    state.scores = [0] * params.squads
    state.holders = [-1] * params.num_beacons
    state.agent_squad = []
    state.agent_id = []
    state.stunned = []
    state.stunned_until = []
    state.pos_x = []
    state.pos_y = []
    ident = 0
    for squad in range(params.squads):
        for _ in range(params.squad_size):
            state.agent_squad.append(squad)
            state.agent_id.append(ident)
            state.stunned.append(0)
            state.stunned_until.append(0)
            if squad < len(world.spawns):
                px, py = cell_center(world, *world.spawns[squad])
            else:
                px, py = 0, 0
            state.pos_x.append(px)
            state.pos_y.append(py)
            ident += 1
    return state


# ---------------------------------------------------------------------------
# The env: one acting agent's turn at a time.
# ---------------------------------------------------------------------------


def env_step(world: World, params: Params, state: State, action: int) -> None:
    """One acting agent's turn; the rules run when the rotation wraps."""
    n = state.num_agents
    if n == 0:
        return
    if state.outcome:
        state.last_reward = 0
        return
    index = acting_index(state.tick, state.turn, world.initiative, n)
    if not is_stunned(state, index, state.tick):
        move_agent(world, params, state.tick, state, index, action)
    state.turn += 1
    if state.turn >= n:
        state.turn = 0
        before = list(state.scores)
        rules_tick(world, params, state, state.tick)
        state.tick += 1
        squad = state.agent_squad[index]
        state.last_reward = state.scores[squad] - before[squad]
    else:
        state.last_reward = 0


def write_mask(world: World, params: Params, state: State) -> List[bool]:
    """The legal actions of the acting agent."""
    n = state.num_agents
    if n == 0:
        return [False] * NUM_ACTIONS
    index = acting_index(state.tick, state.turn, world.initiative, n)
    stunned = is_stunned(state, index, state.tick)
    out = [True] * NUM_ACTIONS
    cx, cy = cell_of(world, state.pos_x[index], state.pos_y[index])
    for action in range(1, NUM_ACTIONS):
        if stunned:
            out[action] = False
            continue
        dx, dy = DIRECTIONS[action]
        nx, ny = cx + dx, cy + dy
        out[action] = in_bounds(world, nx, ny) and cell_at(world, nx, ny) != CELL_WALL
    return out


def obs_cell(world: World, params: Params, state: State, index: int, ex: int, ey: int,
             cx: int, cy: int, out: List[float]) -> None:
    """The six plane values of one cell."""
    plane = world.w * world.h
    cell = cy * world.w + cx
    rng = min(params.view_range_cells, max(world.w, world.h))
    vis = visible(world, ex, ey, cx, cy, rng)
    out[PLANE_VISIBLE * plane + cell] = 1.0 if vis else 0.0
    terrain = 0.0
    if vis:
        kind = cell_at(world, cx, cy)
        terrain = 2.0 if kind == CELL_WALL else (3.0 if kind == CELL_COVER else 1.0)
    out[PLANE_TERRAIN * plane + cell] = terrain
    beacon = 0.0
    for b, bcell in enumerate(world.beacons):
        if bcell == (cx, cy):
            beacon = 1.0 if state.holders[b] < 0 else 2.0 + float(state.holders[b])
            break
    out[PLANE_BEACON * plane + cell] = beacon if vis else 0.0
    self_v = ally = enemy = 0.0
    if vis:
        for i in range(state.num_agents):
            ax, ay = cell_of(world, state.pos_x[i], state.pos_y[i])
            if (ax, ay) != (cx, cy):
                continue
            if i == index:
                self_v = 1.0
            elif state.agent_squad[i] == state.agent_squad[index]:
                ally = 1.0
            else:
                enemy = 1.0
    out[PLANE_SELF * plane + cell] = self_v
    out[PLANE_ALLY * plane + cell] = ally
    out[PLANE_ENEMY * plane + cell] = enemy


def write_obs(world: World, params: Params, state: State) -> List[float]:
    """The observation planes of the acting agent, as one flat list."""
    out = [0.0] * (OBS_CHANNELS * world.w * world.h)
    n = state.num_agents
    index = 0
    if n:
        index = acting_index(state.tick, state.turn, world.initiative, n)
    ex, ey = (0, 0)
    if n:
        ex, ey = cell_of(world, state.pos_x[index], state.pos_y[index])
    for cy in range(world.h):
        for cx in range(world.w):
            obs_cell(world, params, state, index, ex, ey, cx, cy, out)
    return out


# ---------------------------------------------------------------------------
# The canonical byte encoding, for the trajectory proof. It matches the C++
# byte for byte: little-endian, fixed width, no padding.
# ---------------------------------------------------------------------------


def serialize_state(params: Params, state: State) -> bytes:
    out = bytearray()
    out += struct.pack("<I", state.tick)
    out += struct.pack("<I", state.turn)
    out += struct.pack("<I", state.num_agents)
    out += struct.pack("<B", state.outcome)
    out += struct.pack("<b", state.winner)
    out += struct.pack("<i", state.last_reward)
    for squad in range(params.squads):
        out += struct.pack("<i", state.scores[squad])
    for b in range(params.num_beacons):
        out += struct.pack("<b", state.holders[b])
    for i in range(state.num_agents):
        out += struct.pack("<B", state.agent_squad[i])
        out += struct.pack("<B", state.agent_id[i])
        out += struct.pack("<B", state.stunned[i])
        out += struct.pack("<Q", state.stunned_until[i])
        out += struct.pack("<q", state.pos_x[i])
        out += struct.pack("<q", state.pos_y[i])
    return bytes(out)


def serialize_world(params: Params, world: World) -> bytes:
    out = bytearray()
    out += struct.pack("<H", world.w)
    out += struct.pack("<H", world.h)
    out += struct.pack("<I", world.cell_units)
    out += struct.pack("<I", world.initiative)
    out += struct.pack("<H", len(world.beacons))
    out += struct.pack("<H", len(world.spawns))
    for b in range(params.num_beacons):
        bx, by = world.beacons[b] if b < len(world.beacons) else (0, 0)
        out += struct.pack("<I", (bx & 0xFFFF) | ((by & 0xFFFF) << 16))
    for squad in range(params.squads):
        sx, sy = world.spawns[squad] if squad < len(world.spawns) else (0, 0)
        out += struct.pack("<I", (sx & 0xFFFF) | ((sy & 0xFFFF) << 16))
    for i in range(world.w * world.h):
        out += struct.pack("<B", world.cells[i])
    return bytes(out)


class Round:
    """One round of Beacons, with the same surface the batched simulator has.

    The reference's job is to be *right*, not fast: it is the ground truth the
    GPU and the CPU are compared with.
    """

    def __init__(self, seed: int, params: Optional[Params] = None) -> None:
        self.params = params if params is not None else Params()
        self.world = generate_world(seed, self.params)
        self.state = initial_state(self.world, self.params)

    def acting_index(self) -> int:
        return acting_index(self.state.tick, self.state.turn, self.world.initiative,
                            self.state.num_agents)

    def step(self, action: int) -> None:
        env_step(self.world, self.params, self.state, action)

    def mask(self) -> List[bool]:
        return write_mask(self.world, self.params, self.state)

    def obs(self) -> List[float]:
        return write_obs(self.world, self.params, self.state)

    def reward(self) -> int:
        return self.state.last_reward

    def terminated(self) -> bool:
        return self.state.outcome != 0

    def state_bytes(self) -> bytes:
        return serialize_state(self.params, self.state)

    def world_bytes(self) -> bytes:
        return serialize_world(self.params, self.world)
