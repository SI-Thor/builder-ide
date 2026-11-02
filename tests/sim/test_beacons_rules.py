"""The Beacons rules, tested against the reference implementation.

These are the port's own rule tests. They are written from last-mile's Rust
tests (`crates/lm-core/src/rules/beacons.rs`, `world/los.rs`,
`world/gen.rs`, `rng.rs`, `hash.rs`), so a rule that drifts from the
original fails here and not only in the byte comparison.

The reference is the ground truth of the port: the GPU and the CPU are
checked against it in `test_beacons_equivalence.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.sim.systems.beacons import reference as ref  # noqa: E402
from core.sim.systems.beacons.reference import (  # noqa: E402
    CELL_COVER,
    CELL_FLOOR,
    CELL_WALL,
    Fnv64,
    Params,
    Round,
    SplitMix64,
    generate_world,
    rng_stream,
)


def small_world(**kwargs) -> ref.World:
    """A flat world with the given spawns and beacons."""
    params = Params(world_w=32, world_h=32, **kwargs)
    return generate_world(1, params)


# ---------------------------------------------------------------------------
# The hash and the RNG (last-mile's `hash.rs` and `rng.rs`).
# ---------------------------------------------------------------------------


def test_fnv_known_vector():
    h = Fnv64()
    h.write(b"a")
    assert h.finish() == 0xAF63DC4C8601EC8C


def test_fnv_empty_is_the_offset_basis():
    assert Fnv64().finish() == 0xCBF29CE484222325


def test_fnv_integers_are_little_endian():
    h = Fnv64()
    h.u16(0x0102)
    expect = Fnv64()
    expect.write(bytes([0x02, 0x01]))
    assert h.finish() == expect.finish()


def test_rng_streams_are_independent_and_stable():
    a = rng_stream(7, 1, 1).next_u64()
    assert a != rng_stream(7, 1, 2).next_u64()
    assert a == rng_stream(7, 1, 1).next_u64()
    assert a != rng_stream(7, 2, 1).next_u64()
    assert a != rng_stream(8, 1, 1).next_u64()


def test_below_is_in_range():
    r = rng_stream(1, 2, 0)
    for _ in range(1000):
        assert r.below(7) < 7
    assert SplitMix64(0).below(0) == 0


# ---------------------------------------------------------------------------
# The line of sight (last-mile's `world/los.rs`).
# ---------------------------------------------------------------------------


def test_los_blocked_by_wall_and_cover():
    world = small_world()
    a, b = (0, 0), (4, 0)

    def clear() -> bool:
        return ref.los_clear(world, *a, *b)

    assert clear(), "a flat corridor is in sight"
    ref.set_cell(world, 2, 0, CELL_WALL)
    assert not clear(), "a wall blocks the sight"
    ref.set_cell(world, 2, 0, CELL_COVER)
    assert not clear(), "cover blocks the sight"
    ref.set_cell(world, 2, 0, CELL_FLOOR)
    ref.set_cell(world, *b, CELL_COVER)
    assert clear(), "the endpoints are exempt: cover at the target does not blind it"


def test_los_is_symmetric():
    world = generate_world(3, Params(world_w=32, world_h=32))
    rng = rng_stream(3, 0, 1)
    for _ in range(200):
        a = (rng.below(world.w), rng.below(world.h))
        b = (rng.below(world.w), rng.below(world.h))
        assert ref.los_clear(world, *a, *b) == ref.los_clear(world, *b, *a)


def test_out_of_bounds_reads_as_wall():
    world = small_world()
    assert ref.cell_at(world, -1, 0) == CELL_WALL
    assert ref.cell_at(world, world.w, 0) == CELL_WALL


# ---------------------------------------------------------------------------
# The generator (last-mile's `world/gen.rs`).
# ---------------------------------------------------------------------------


def test_the_generator_is_deterministic_and_seed_dependent():
    params = Params(world_w=32, world_h=32)
    a = generate_world(42, params)
    b = generate_world(42, params)
    c = generate_world(43, params)
    assert ref.serialize_world(params, a) == ref.serialize_world(params, b)
    assert ref.serialize_world(params, a) != ref.serialize_world(params, c)


def test_the_world_is_point_symmetric():
    params = Params(world_w=32, world_h=32)
    world = generate_world(11, params)
    for y in range(world.h):
        for x in range(world.w):
            mx, my = ref.mirror_of(world, x, y)
            assert world.cells[y * world.w + x] == world.cells[my * world.w + mx]


def test_the_spawns_and_beacons_are_reachable_from_spawn_zero():
    params = Params(world_w=32, world_h=32)
    world = generate_world(5, params)
    reached = ref._flood_from(world, *world.spawns[0])
    for cell in list(world.spawns) + list(world.beacons):
        assert reached[cell[1] * world.w + cell[0]], f"{cell} is walled off"


def test_the_world_has_walls_cover_and_floor():
    params = Params(world_w=32, world_h=32)
    world = generate_world(7, params)
    kinds = set(world.cells)
    assert kinds == {CELL_FLOOR, CELL_WALL, CELL_COVER}


# ---------------------------------------------------------------------------
# The rules (last-mile's `rules/beacons.rs`).
# ---------------------------------------------------------------------------


def _order(round_: Round, tick: int = 0) -> list[int]:
    """The tick's acting order: agent (slot + tick % n + initiative) % n."""
    n = round_.state.num_agents
    return [
        ref.acting_index(tick, slot, round_.world.initiative, n) for slot in range(n)
    ]


def _round_with(**params_kwargs) -> Round:
    """A round on a flat 32x32 world with two squads and one beacon."""
    params = Params(world_w=32, world_h=32, **params_kwargs)
    round_ = Round(1, params)
    # Flatten the world: the rule tests are about the rules, not the terrain.
    for i in range(len(round_.world.cells)):
        round_.world.cells[i] = CELL_FLOOR
    return round_


def test_a_tag_stuns_the_target_and_the_stun_ends_in_a_respawn():
    round_ = _round_with()
    world, state = round_.world, round_.state
    # Squad 0's first agent next to squad 1's first agent.
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, 4, 4)
    state.pos_x[4], state.pos_y[4] = ref.cell_center(world, 5, 4)
    # The two agents act in the tick's rotating order, so the one that acts
    # first is the tagger.
    order = _order(round_)
    tagger, target = (0, 4) if order.index(0) < order.index(4) else (4, 0)
    before = (state.pos_x[target], state.pos_y[target])
    ref.rules_tick(world, round_.params, state, 0)
    assert state.stunned[target] == 1, "the target is stunned"
    assert state.stunned[tagger] == 0, "the tagger is not"
    assert state.stunned_until[target] == round_.params.stun_ticks

    # The stun holds the agent for stun_ticks ticks.
    ref.rules_tick(world, round_.params, state, round_.params.stun_ticks - 1)
    assert state.stunned[target] == 1
    # And at the tick it ends on, the agent is put back on its spawn.
    ref.rules_tick(world, round_.params, state, round_.params.stun_ticks)
    assert state.stunned[target] == 0
    assert (state.pos_x[target], state.pos_y[target]) == ref.cell_center(
        world, *world.spawns[state.agent_squad[target]]
    )
    assert (state.pos_x[target], state.pos_y[target]) != before


def test_a_tag_does_not_come_back_in_the_same_tick():
    round_ = _round_with()
    world, state = round_.world, round_.state
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, 4, 4)
    state.pos_x[4], state.pos_y[4] = ref.cell_center(world, 5, 4)
    order = _order(round_)
    tagger, target = (0, 4) if order.index(0) < order.index(4) else (4, 0)
    ref.rules_tick(world, round_.params, state, 0)
    # The tagger is not stunned, but the target is: no trade in the same tick.
    assert state.stunned[tagger] == 0
    assert state.stunned[target] == 1


def test_a_beacon_two_squads_stand_in_is_held_by_nobody():
    round_ = _round_with()
    world, state = round_.world, round_.state
    beacon = world.beacons[0]
    cx, cy = beacon
    # Squad 0's agent on the beacon, squad 1's agent two cells away: inside
    # the holding radius (4 m) but outside the tag range (2 m), so the two
    # do not tag each other on the way.
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, cx, cy)
    state.pos_x[4], state.pos_y[4] = ref.cell_center(world, cx + 2, cy)
    ref.rules_tick(world, round_.params, state, 0)
    assert state.holders[0] == -1, "two squads inside the radius hold nothing"

    # With the enemy gone, the beacon is held and scores.
    state.pos_x[4], state.pos_y[4] = ref.cell_center(world, 20, 20)
    before = state.scores[0]
    ref.rules_tick(world, round_.params, state, 1)
    assert state.holders[0] == 0
    assert state.scores[0] > before, "a held beacon is worth a point a tick"


def test_the_round_ends_on_the_score_and_a_tie_is_a_tie():
    round_ = _round_with(win_score=3)
    world, state = round_.world, round_.state
    beacon = world.beacons[0]
    cx, cy = beacon
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, cx, cy)
    for tick in range(3):
        ref.rules_tick(world, round_.params, state, tick)
    assert state.outcome == 1, "the round ends when the score is reached"
    assert state.winner == 0

    # A tie is a tie: nobody wins.
    round_ = _round_with(win_score=3)
    world, state = round_.world, round_.state
    # The agents stay on their spawns, far from every beacon, so the tick
    # scores nothing and the tie is the one that is decided.
    state.scores = [3, 3]
    ref.rules_tick(world, round_.params, state, 0)
    assert state.outcome == 1
    assert state.winner == -1, "a tie is a tie"


def test_the_round_ends_on_the_clock():
    round_ = _round_with(time_limit_ticks=4)
    ref.rules_tick(round_.world, round_.params, round_.state, 4)
    assert round_.state.outcome == 1


# ---------------------------------------------------------------------------
# The motor (last-mile's `agent.rs`).
# ---------------------------------------------------------------------------


def test_the_motor_never_enters_a_wall():
    round_ = _round_with()
    world, state = round_.world, round_.state
    ref.set_cell(world, 3, 2, CELL_WALL)
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, 2, 2)
    ref.move_agent(world, round_.params, 0, state, 0, 3)  # east
    assert (state.pos_x[0], state.pos_y[0]) == ref.cell_center(world, 2, 2)


def test_the_motor_leads_with_the_alternating_axis():
    round_ = _round_with()
    world, state = round_.world, round_.state
    start = ref.cell_center(world, 2, 2)
    # North east: the target is one cell east and one cell north, so both
    # axes have work to do and the leading axis takes the budget.
    state.pos_x[0], state.pos_y[0] = start
    ref.move_agent(world, round_.params, 0, state, 0, 2)
    # On an even tick the x axis leads.
    assert state.pos_x[0] == start[0] + round_.params.speed_upt
    assert state.pos_y[0] == start[1]
    # On an odd tick the y axis leads.
    state.pos_x[0], state.pos_y[0] = start
    ref.move_agent(world, round_.params, 1, state, 0, 2)
    assert state.pos_y[0] == start[1] - round_.params.speed_upt
    assert state.pos_x[0] == start[0]


def test_the_motor_budget_is_one_tick_worth():
    round_ = _round_with()
    world, state = round_.world, round_.state
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, 2, 2)
    ref.move_agent(world, round_.params, 0, state, 0, 3)  # east
    # It moved speed_upt units, not the whole cell.
    assert state.pos_x[0] == ref.cell_center(world, 2, 2)[0] + round_.params.speed_upt


def test_a_stunned_agent_holds():
    round_ = _round_with()
    world, state = round_.world, round_.state
    acting = round_.acting_index()
    start = ref.cell_center(world, 2, 2)
    state.pos_x[acting], state.pos_y[acting] = start
    state.stunned[acting] = 1
    state.stunned_until[acting] = 10
    # The env holds the stunned agent: it does not walk.
    round_.step(3)
    assert (state.pos_x[acting], state.pos_y[acting]) == start


# ---------------------------------------------------------------------------
# The env's own surface.
# ---------------------------------------------------------------------------


def test_the_mask_holds_for_a_stunned_agent():
    round_ = _round_with()
    state = round_.state
    acting = round_.acting_index()
    state.stunned[acting] = 1
    state.stunned_until[acting] = 100
    mask = round_.mask()
    assert mask[0] is True, "hold is always legal"
    assert not any(mask[1:]), "a stunned agent may only hold"


def test_the_mask_refuses_a_wall():
    round_ = _round_with()
    world, state = round_.world, round_.state
    state.pos_x[0], state.pos_y[0] = ref.cell_center(world, 2, 2)
    ref.set_cell(world, 3, 2, CELL_WALL)
    mask = round_.mask()
    assert mask[3] is False, "east is into a wall"
    assert mask[1] is True, "north is open"


def test_the_obs_has_six_planes_and_marks_the_acting_agent():
    round_ = _round_with()
    obs = round_.obs()
    assert len(obs) == 6 * round_.world.w * round_.world.h
    index = round_.acting_index()
    ex, ey = ref.cell_of(round_.world, round_.state.pos_x[index], round_.state.pos_y[index])
    plane = round_.world.w * round_.world.h
    assert obs[ref.PLANE_SELF * plane + ey * round_.world.w + ex] == 1.0
    assert obs[ref.PLANE_VISIBLE * plane + ey * round_.world.w + ex] == 1.0


def test_the_obs_does_not_leak_an_enemy_in_an_unseen_cell():
    round_ = _round_with()
    world, state = round_.world, round_.state
    # Put the enemy far away, behind a wall the sight cannot pass.
    state.pos_x[4], state.pos_y[4] = ref.cell_center(world, 30, 30)
    for x in range(20, 30):
        ref.set_cell(world, x, 30, CELL_WALL)
    obs = round_.obs()
    plane = world.w * world.h
    assert obs[ref.PLANE_ENEMY * plane + 30 * world.w + 30] == 0.0
    assert obs[ref.PLANE_VISIBLE * plane + 30 * world.w + 30] == 0.0
