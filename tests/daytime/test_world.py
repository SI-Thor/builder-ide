"""The world: one room, one clock, and nothing but the recipe behind it.

The daytime world's promise is that it is reproducible — the same recipe and
the same tick reconstruct the same world exactly. These tests hold that
promise against the arithmetic, before any ledger is involved.
"""

from __future__ import annotations


def test_the_room_holds_the_recipe_s_entries_that_do_something(fjellvik):
    from core.daytime.world import world_at

    world = world_at(fjellvik, "ver_0192", 0)
    # the crates get tidied, the terrain grows; the bridge has no behaviour
    assert [obj.path for obj in world.room.objects] == ["harbor.crates", "terrain.harbor"]
    assert world.room.objects[0].changes == {"tidy": 0}
    assert world.room.objects[1].changes == {"grow": 0}


def test_the_light_moves_through_the_day(fjellvik):
    from core.daytime.world import LIGHT_CYCLE, world_at

    midnight = world_at(fjellvik, "ver_0192", 0)
    assert midnight.room.light == 0
    assert midnight.room.phase == "night"

    noon = world_at(fjellvik, "ver_0192", LIGHT_CYCLE // 2)
    assert noon.room.light == 100
    assert noon.room.phase == "day"

    # and the day turns over
    assert world_at(fjellvik, "ver_0192", LIGHT_CYCLE).room.light == 0


def test_a_builder_tidies_and_the_plants_grow_by_a_step(fjellvik):
    from core.daytime.world import world_at

    world = world_at(fjellvik, "ver_0192", 12)
    crates = next(o for o in world.room.objects if o.path == "harbor.crates")
    terrain = next(o for o in world.room.objects if o.path == "terrain.harbor")
    assert crates.changes == {"tidy": 3}
    assert terrain.changes == {"grow": 4}


def test_the_same_recipe_and_tick_reconstruct_the_same_world(fjellvik):
    from core.daytime.world import world_at

    assert world_at(fjellvik, "ver_0192", 9) == world_at(fjellvik, "ver_0192", 9)


def test_a_different_recipe_gives_a_different_world(fjellvik):
    from core.daytime.world import world_at

    other = fjellvik.model_copy(deep=True)
    other.entries["harbor.crates"].seed = 4473
    assert world_at(other, "ver_0192", 12) != world_at(fjellvik, "ver_0192", 12)


def test_the_recipe_s_light_entry_says_when_the_day_starts(fjellvik):
    from core.daytime.world import world_at
    from core.records import RecipeEntry

    lit = fjellvik.model_copy(deep=True)
    lit.entries["lights.north"] = RecipeEntry(path="lights.north", kind="light", seed=3)

    assert world_at(fjellvik, "ver_0192", 0).room.phase == "night"
    assert world_at(lit, "ver_0192", 0).room.phase == "dawn"
