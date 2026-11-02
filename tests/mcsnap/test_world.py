"""What a snapshot copies, and what it leaves behind."""

from __future__ import annotations

from pathlib import Path

from mcsnap.world import SECTION_LABELS, classify, copy_tree, plan_tree


def test_the_regions_are_copied() -> None:
    section, include, _ = classify("dimensions/minecraft/overworld/region/r.0.0.mca")
    assert (section, include) == ("region", True)


def test_the_entities_and_the_points_of_interest_are_copied() -> None:
    entities = classify("dimensions/minecraft/overworld/entities/r.0.0.mca")[0]
    points = classify("dimensions/minecraft/overworld/poi/r.0.0.mca")[0]
    assert entities == "entities"
    assert points == "poi"


def test_the_world_data_outside_the_regions_is_copied() -> None:
    """The scoreboard and the clocks live outside the region files."""
    section, include, _ = classify("data/minecraft/scoreboard.dat")
    assert (section, include) == ("world-data", True)
    clocks = classify("data/minecraft/world_clocks.dat")[0]
    raids = classify("dimensions/minecraft/the_end/data/raids.dat")[0]
    assert clocks == "world-data"
    assert raids == "dimension-data"


def test_the_players_data_is_copied() -> None:
    data = classify("players/data/0e891f7e.dat")[0]
    advancements = classify("players/advancements/0e891f7e.json")[0]
    statistics = classify("players/stats/0e891f7e.json")[0]
    assert data == "players"
    assert advancements == "players"
    assert statistics == "players"


def test_the_datapacks_and_the_settings_are_copied() -> None:
    datapacks = classify("datapacks/bukkit/pack.mcmeta")[0]
    settings = classify("dimensions/minecraft/overworld/paper-world.yml")[0]
    assert datapacks == "datapacks"
    assert settings == "config"


def test_the_servers_own_lock_is_left_behind_with_a_reason() -> None:
    section, include, reason = classify("session.lock")
    assert section == "skipped"
    assert include is False
    assert reason


def test_the_previous_level_dat_is_left_behind() -> None:
    section, include, reason = classify("level.dat_old")
    assert (section, include) == ("skipped", False)
    assert "superseded" in reason


def test_a_file_the_tool_does_not_know_is_copied_and_listed() -> None:
    """A Paper version that keeps state somewhere new must not lose it."""
    section, include, _ = classify("dimensions/minecraft/overworld/something-new.dat")
    assert (section, include) == ("unclassified", True)
    assert section in SECTION_LABELS


def test_the_plan_sees_the_whole_world(fake_world: Path) -> None:
    plans = plan_tree(fake_world)
    by_path = {plan.relpath: plan for plan in plans}
    assert "level.dat" in by_path
    assert by_path["level.dat"].include is True
    assert by_path["session.lock"].include is False
    assert by_path["session.lock"].reason


def test_the_copy_takes_the_included_files_only(fake_world: Path, tmp_path: Path) -> None:
    destination = tmp_path / "copied"
    files, total = copy_tree(fake_world, destination)
    assert files > 0
    assert total > 0
    assert (destination / "level.dat").is_file()
    assert (destination / "dimensions/minecraft/overworld/region/r.0.0.mca").is_file()
    assert not (destination / "session.lock").exists()
    assert not (destination / "level.dat_old").exists()


def test_the_copy_and_the_world_are_separate_files(fake_world: Path, tmp_path: Path) -> None:
    """The world that was copied is a separate file from the world it came from."""
    destination = tmp_path / "copied"
    copy_tree(fake_world, destination)
    original = fake_world / "level.dat"
    copied = destination / "level.dat"
    before = original.read_bytes()
    copied.write_bytes(b"a different world")
    assert original.read_bytes() == before
