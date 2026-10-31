"""Provenance — the record that has to survive the round trip.

The brief's pass/fail: *provenance (prompt, model, weights revision, seed,
licence) round-trips in ``customData``*. These tests check the round trip
twice over: the dataclass in and out of a dictionary, and the dictionary in
and out of the compiled stage.
"""

from __future__ import annotations

from pathlib import Path

from builder_usd.canonical import hash_bytes
from builder_usd.provenance import (
    ASSET_KEY,
    PART_KEY,
    PROVENANCE_KEY,
    Provenance,
)
from builder_usd.verify import open_stage, read_assets, read_custom_data, read_provenance


def test_the_dataclass_round_trips_through_a_dictionary():
    original = Provenance(
        source="cad_script",
        prompt="hinge_bracket(length=0.12)",
        model="build123d",
        seed=11,
        version="0.13.0",
        licence={"spdx": "Apache-2.0"},  # type: ignore[arg-type]
        weights_repo="gumyr/build123d",
        weights_revision="abc123",
        library_versions={"build123d": "0.13.0"},
        recipe_version_hash="sha256:" + "0" * 64,
        engine_pin={"repo": "SI-Thor/infinigen-thor"},
    )
    from builder_usd.provenance import Licence

    original = Provenance(
        source=original.source,
        prompt=original.prompt,
        model=original.model,
        seed=original.seed,
        version=original.version,
        licence=Licence("Apache-2.0", ("OCCT LGPL-2.1-with-exception",), True, None),
        weights_repo=original.weights_repo,
        weights_revision=original.weights_revision,
        library_versions=original.library_versions,
        recipe_version_hash=original.recipe_version_hash,
        engine_pin=original.engine_pin,
    )
    assert Provenance.from_dict(original.to_dict()) == original


def _without_nulls(value):
    """USD has no null, so a ``None`` in the record is dropped on the way in."""
    if isinstance(value, dict):
        return {
            key: _without_nulls(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, (list, tuple)):
        return [_without_nulls(item) for item in value]
    return value


def test_the_record_in_the_stage_is_the_record_that_went_in(demo_stage, demo_source_and_records):
    _source, records = demo_source_and_records
    stage = open_stage(demo_stage / "root.usda")
    found = read_provenance(stage)

    for entry_path, record in records.items():
        prim_path = "/World/" + entry_path.replace(".", "/")
        assert prim_path in found, f"{prim_path} carries no provenance"
        written = found[prim_path]
        expected = _without_nulls(record.to_dict())
        for key, value in expected.items():
            assert key in written, f"{prim_path} lost {key!r} on the way in"
            assert written[key] == value, f"{prim_path}.{key} came back changed"


def test_the_five_fields_the_brief_names_are_present(demo_stage):
    stage = open_stage(demo_stage / "root.usda")
    for prim_path, record in read_provenance(stage).items():
        for field in ("prompt", "model", "seed", "version", "licence"):
            assert field in record, f"{prim_path} has no {field!r}"
        assert "spdx" in record["licence"]
        assert "weights" in record


def test_the_asset_files_are_pinned_by_hash(demo_stage):
    stage = open_stage(demo_stage / "root.usda")
    found = read_assets(stage)
    assert found, "no asset was pinned"
    for prim_path, assets in found.items():
        for role, record in assets.items():
            path = demo_stage / record["path"]
            assert path.is_file(), f"{prim_path} points at a missing file {record['path']}"
            data = path.read_bytes()
            assert hash_bytes(data) == record["sha256"], f"{record['path']} does not match its hash"
            assert len(data) == record["bytes"], f"{record['path']} does not match its size"
            assert record["role"] == role


def test_the_glb_and_the_step_are_both_pinned(demo_stage):
    stage = open_stage(demo_stage / "root.usda")
    for prim_path, assets in read_assets(stage).items():
        assert "glb" in assets, f"{prim_path} pins no GLB"
        assert "master" in assets, f"{prim_path} pins no STEP master"
        assert "usd" in assets, f"{prim_path} pins no USD asset layer"
        assert assets["glb"]["role"] == "glb"
        assert assets["master"]["role"] == "master"


def test_the_part_layer_carries_its_own_record(demo_stage):
    """The asset's history travels with the asset, not only with the placement."""
    from pxr import Usd

    for path in sorted((demo_stage / "assets").glob("*.usda")):
        layer = Usd.Stage.Open(str(path))
        part = layer.GetPrimAtPath("/Part")
        data = read_custom_data(part)
        assert PART_KEY in data, f"{path.name} carries no record of its own"
        record = data[PART_KEY]
        assert record["model"] == "build123d"
        assert record["licence"]["spdx"] == "Apache-2.0"
        assert record["source"] == "cad_script"
        assert record["prompt"].startswith(path.stem), "the prompt is not the part script"
        assert ASSET_KEY in data
        assert "glb" in data[ASSET_KEY]
        assert "master" in data[ASSET_KEY]


def test_the_placement_record_and_the_part_record_do_not_collide(demo_stage):
    """USD merges customData dictionaries — so the two records use own keys."""
    stage = open_stage(demo_stage / "root.usda")
    prim = stage.GetPrimAtPath("/World/harbor/crate_stack")
    data = read_custom_data(prim)
    assert "provenance" in data, "the placement has no provenance"
    assert "part" in data, "the part's own record did not survive the composition"
    assert data["provenance"] != data["part"]


def test_the_provenance_layer_is_the_only_writer_of_custom_data(demo_stage):
    """``customData`` has one writer per prim — the composition depends on it."""
    for concern in ("geometry", "materials", "physics", "semantics"):
        text = (demo_stage / f"{concern}.usda").read_text(encoding="utf-8")
        assert "customData" not in text, f"{concern}.usda also writes customData"


def test_a_recipe_without_provenance_still_gets_a_record(tmp_path, demo_source_and_records):
    """The compiler stamps what it knows when the scheduler stamped nothing."""
    from builder_usd.compile import compile_recipe

    source, _records = demo_source_and_records
    out_dir = tmp_path / "stage"
    compile_recipe(source, out_dir, None)
    stage = open_stage(out_dir / "root.usda")
    found = read_provenance(stage)
    assert found
    record = found["/World/harbor/crate_stack"]
    assert record["model"] == "build123d"
    assert record["version"]
    assert record["licence"]["spdx"] == "Apache-2.0"
    assert record["seed"] == 11
    assert record["recipe_version_hash"].startswith("sha256:")
