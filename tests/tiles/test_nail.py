"""The ``.nail`` export: a tile library plus its chooser, portable and addressed.

The rules under test:

* the export is **content addressed** — the same library and the same chooser
  state give the same bundle hash, and a changed tile changes it;
* the bundle carries the **chooser's state**, not just the tiles: a library
  without the chooser is half the answer;
* every entry keeps its **provenance** — who wrote the tile, which model,
  which prompt hash;
* the format is **``.nail``-shaped**: the fields quilt-pincher's bundle
  has (``version``, ``reflexes``, ``vetoRules``, ``compileHistory``,
  ``metadata``) are here under the same names, so the two are comparable;
* the export **round-trips**: what is written reads back the same.
"""

from __future__ import annotations

import json

import pytest

from core.tiles.nail import (
    NAIL_FORMAT,
    NailBundle,
    export_nail,
    read_nail,
    write_nail,
)


@pytest.fixture
def library(registry, ledger):
    from core.tiles.library import TileLibrary

    lib = TileLibrary(registry=registry, ledger=ledger)
    lib.add(
        _tile("weathered crates", style="weathered"),
    )
    lib.add(
        _tile("stained crates", style="stained"),
    )
    return lib


def _tile(title: str, *, style: str):
    from core.tiles.models import TileAuthor, TileStep, build_tile

    return build_tile(
        family="harbor.crates.style",
        kind="recipe_edit",
        title=title,
        steps=(
            TileStep(
                word="props.harbor.crates",
                path="harbor.crates",
                params={"count": 12, "style": style, "from_library": 0},
            ),
        ),
        author=TileAuthor(
            model="fake/scripted-v1",
            provider="fake",
            prompt_hash="sha256:" + "0" * 64,
            cost_cents=0,
        ),
    )


def test_the_export_is_content_addressed(library):
    """The same library gives the same bundle hash."""
    first = export_nail(library=library, name="m1-slice")
    second = export_nail(library=library, name="m1-slice")
    assert first.content_hash == second.content_hash


def test_a_different_name_is_a_different_bundle(library):
    """The name is part of the bundle, so two bundles are two bundles."""
    first = export_nail(library=library, name="m1-slice")
    second = export_nail(library=library, name="other-slice")
    assert first.content_hash != second.content_hash


def test_the_bundle_has_the_nail_shape(library):
    """The fields quilt-pincher's bundle has, under the same names."""
    bundle = export_nail(library=library, name="m1-slice")
    assert bundle.format == NAIL_FORMAT
    assert bundle.version
    assert bundle.reflexes
    assert bundle.metadata["name"] == "m1-slice"
    assert "createdAt" in bundle.metadata
    assert "updatedAt" in bundle.metadata
    assert "tier" in bundle.metadata
    assert isinstance(bundle.vetoRules, list)
    assert isinstance(bundle.compileHistory, list)


def test_each_reflex_carries_its_embedding_and_provenance(library):
    """A reflex without its vector is not a reflex; without provenance, not ours."""
    bundle = export_nail(library=library, name="m1-slice")
    reflex = bundle.reflexes[0]
    assert reflex["embedding"]
    assert reflex["intent"]
    assert reflex["action"]
    assert reflex["id"].startswith("sha256:")
    assert reflex["provenance"]["compiledBy"]


def test_the_reflex_count_is_the_library_count(library):
    bundle = export_nail(library=library, name="m1-slice")
    assert len(bundle.reflexes) == len(library.tiles())


def test_the_export_carries_the_choosers_state(library):
    """A library without the chooser is half the answer."""
    from core.tiles.chooser import ContextualBandit

    chooser = ContextualBandit(feature_keys=("wanted_style",), epsilon=0.25, seed=7)
    bundle = export_nail(library=library, chooser=chooser, name="m1-slice")
    assert bundle.chooser["name"] == "bandit/ctx-v1"
    assert bundle.chooser["featureKeys"] == ["wanted_style"]
    assert "epsilon" in bundle.chooser
    assert "arms" in bundle.chooser


def test_the_export_is_written_as_json(library, tmp_path):
    """The bundle is a file on disk, and it reads back the same."""
    bundle = export_nail(library=library, name="m1-slice")
    path = tmp_path / "m1-slice.nail"
    write_nail(path, bundle)

    payload = json.loads(path.read_text())
    assert payload["format"] == NAIL_FORMAT

    read_back = read_nail(path)
    assert read_back.content_hash == bundle.content_hash


def test_the_content_hash_covers_the_body(library, tmp_path):
    """Changing a tile changes the bundle's hash: it is a promise about content."""
    bundle = export_nail(library=library, name="m1-slice")
    path = tmp_path / "m1-slice.nail"
    write_nail(path, bundle)

    payload = json.loads(path.read_text())
    payload["reflexes"][0]["intent"] = "something else"
    path.write_text(json.dumps(payload))

    assert read_nail(path).content_hash != bundle.content_hash


def test_the_bundle_can_be_written_without_a_chooser(library):
    """The chooser is optional; a library alone is still exportable."""
    bundle = export_nail(library=library, name="m1-slice")
    assert bundle.chooser is None or bundle.chooser == {}


def test_an_empty_library_exports(library):
    """An empty bundle is a bundle; it is not an error."""
    from core.tiles.library import TileLibrary
    from core.vocab.registry import VocabularyRegistry
    from core.vocab.words import default_entries

    empty = TileLibrary(registry=VocabularyRegistry(default_entries()))
    bundle = export_nail(library=empty, name="empty")
    assert bundle.reflexes == []
    assert bundle.content_hash.startswith("sha256:")


def test_a_retired_tile_is_not_exported_as_an_option(library, registry):
    """A retired tile is history, not an option."""
    from core.tiles.library import TileLibrary
    from core.vocab.registry import VocabularyRegistry
    from core.vocab.words import default_entries

    lib = TileLibrary(registry=VocabularyRegistry(default_entries()))
    tile = _tile("weathered crates", style="weathered")
    lib.add(tile)
    lib.retire(tile.id, reason="superseded")

    bundle = export_nail(library=lib, name="m1-slice")
    assert bundle.reflexes == []
    assert bundle.metadata["retired"] == 1
