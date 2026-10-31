"""The closed event set carries the daytime group — and every seat agrees.

§1.8's set is closed, so the daytime world's four types are a schema change.
The pin here is the whole point of the commit: a new group must land in the
one set *and* in both seats that mirror it, or the log's readers drift.
"""

from __future__ import annotations


def test_the_daytime_group_is_named_and_small():
    from core.daytime.events import DAYTIME_EVENT_TYPES

    assert DAYTIME_EVENT_TYPES == frozenset(
        {"day.world.opened", "day.tick", "day.change", "day.yielded"}
    )


def test_the_daytime_group_is_in_the_one_closed_set():
    from core.daytime.events import DAYTIME_EVENT_TYPES
    from core.records import EVENT_TYPES

    assert DAYTIME_EVENT_TYPES <= EVENT_TYPES


def test_every_seat_mirrors_the_same_closed_set():
    from core.night.events import EVENT_TYPES as night_types
    from core.recipe.events import EVENT_TYPES as recipe_types
    from core.records import EVENT_TYPES

    assert night_types == EVENT_TYPES
    assert recipe_types == EVENT_TYPES


def test_the_small_changes_have_a_closed_vocabulary():
    from core.daytime.events import CHANGE_KINDS

    assert CHANGE_KINDS == frozenset({"light", "tidy", "grow"})


def test_a_recipe_entry_kind_maps_to_one_behaviour():
    from core.daytime.events import ENTRY_BEHAVIOURS

    assert ENTRY_BEHAVIOURS == {"prop_set": "tidy", "terrain": "grow"}
    # a kind with no behaviour is simply not in the map — no free text.
    assert "structure" not in ENTRY_BEHAVIOURS
