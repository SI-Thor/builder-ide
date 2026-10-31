"""The stage cache key — core-spec v2 §1.9.

Key = ``sha256(canonical(recipe_version_hash ⊕ engine_pin ⊕ stage_name ⊕
dep_keys))``, where ``engine_pin`` includes the pinned config hash. The key
must be a function of the recipe version alone: no wall-clock, no hostname,
no ambient config (RV patch 13).
"""

from __future__ import annotations

from core.recipe.models import EnginePin, RecipeEntry
from core.recipe.stagecache import entry_stage_key, stage_cache_key


def _pin() -> EnginePin:
    return EnginePin(
        repo="SI-Thor/infinigen-thor",
        commit="9f31c0e",
        config="sha256:cf90cafe",
        blender="4.2",
        python="3.12",
    )


def _entry(count: int = 12) -> RecipeEntry:
    return RecipeEntry(path="harbor.crates", kind="prop_set", params={"count": count})


def test_the_stage_key_is_a_content_hash():
    key = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["dep-1"])
    assert key.startswith("sha256:")
    assert len(key) == len("sha256:") + 64


def test_the_stage_key_is_stable_across_runs():
    first = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["dep-1"])
    second = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["dep-1"])
    assert first == second


def test_a_different_recipe_version_hash_gives_a_different_key():
    one = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", [])
    other = stage_cache_key("sha256:" + "b" * 64, _pin(), "compile", [])
    assert one != other


def test_a_different_stage_name_gives_a_different_key():
    one = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", [])
    other = stage_cache_key("sha256:" + "a" * 64, _pin(), "assemble", [])
    assert one != other


def test_the_pinned_config_hash_is_part_of_the_key():
    """RV patch 13: without the config hash, config drift defeats the cache."""
    pin = _pin()
    other = pin.model_copy(update={"config": "sha256:deadbeef"})
    assert stage_cache_key("sha256:" + "a" * 64, pin, "compile", []) != stage_cache_key(
        "sha256:" + "a" * 64, other, "compile", []
    )


def test_the_dependency_keys_do_not_depend_on_their_order():
    one = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["a", "b"])
    other = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["b", "a"])
    assert one == other


def test_a_different_dependency_set_gives_a_different_key():
    one = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["a"])
    other = stage_cache_key("sha256:" + "a" * 64, _pin(), "compile", ["b"])
    assert one != other


def test_an_entry_stage_key_does_not_depend_on_the_version():
    """The dirty-set contract: an untouched entry keeps its stage key."""
    assert entry_stage_key("harbor.crates", _entry(), _pin()) == entry_stage_key(
        "harbor.crates", _entry(), _pin()
    )


def test_an_entry_stage_key_changes_when_the_entry_changes():
    assert entry_stage_key("harbor.crates", _entry(), _pin()) != entry_stage_key(
        "harbor.crates", _entry(count=20), _pin()
    )


def test_an_entry_stage_key_changes_when_the_engine_pin_changes():
    pin = _pin()
    other = pin.model_copy(update={"config": "sha256:deadbeef"})
    assert entry_stage_key("harbor.crates", _entry(), pin) != entry_stage_key(
        "harbor.crates", _entry(), other
    )


def test_the_store_keys_a_stage_on_the_version_hash(store, fjellvik, actor):
    from core.recipe.models import Op

    store.create_recipe(fjellvik, actor)
    version = store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    key = store.stage_key(version.id, "compile", ["dep-1"])
    assert key == stage_cache_key(
        version.root_hash, fjellvik.engine_pin, "compile", ["dep-1"]
    )


def test_the_store_reports_the_dirty_set_between_two_versions(store, fjellvik, actor):
    from core.recipe.models import Op

    store.create_recipe(fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    dirty = store.dirty_set("ver_0001", "ver_0002")
    assert dirty.entries == {"harbor.crates"}
