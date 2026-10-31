"""The three words of the M1 slice.

Spec §6.1 names them; the brief asks for each of them to be a **typed,
bounded entry with taste notes and provenance**. Those three properties are
what this file checks, plus the fact that the words are the ones the slice
names — not three of our own invention.
"""

from __future__ import annotations

import pytest

from core.vocab import VocabularyRegistry, default_entries, entry_path_for
from core.vocab.schema import validate_schema
from core.vocab.seed import ENGINE_PIN
from core.vocab.taste import aggregate_taste_notes
from core.vocab.words import seed_taste_rows


def test_the_slice_ships_exactly_three_words():
    words = {entry.word for entry in default_entries()}
    assert words == {
        "props.harbor.crates",
        "props.harbor.racks",
        "material.wood.weathering",
    }


@pytest.mark.parametrize("entry", default_entries(), ids=lambda entry: entry.word)
def test_a_word_is_typed_and_bounded(entry):
    validate_schema(entry.params)
    assert entry.params["additionalProperties"] is False
    assert entry.params["type"] == "object"
    assert len(entry.params["properties"]) <= 8
    assert entry.kind in {"prop", "material"}
    assert entry.owner_character == "prop-maker"


@pytest.mark.parametrize("entry", default_entries(), ids=lambda entry: entry.word)
def test_a_word_carries_taste_notes_with_denominators(entry):
    assert entry.taste_notes
    for note in entry.taste_notes:
        assert note.code in ("keep", "avoid")
        assert "/" in note.basis and "kept" in note.basis
        assert "%" not in note.basis
        assert len(note.note.split()) <= 6


@pytest.mark.parametrize("entry", default_entries(), ids=lambda entry: entry.word)
def test_a_word_carries_provenance(entry):
    assert entry.provenance["origin"] in ("builtin", "wo_14")
    assert "at" in entry.provenance
    assert entry.provenance["engine_pin"] == ENGINE_PIN["commit"]


@pytest.mark.parametrize("entry", default_entries(), ids=lambda entry: entry.word)
def test_a_word_binds_an_acceptance_template(entry):
    assert entry.acceptance_template is not None
    assert "{node}" in str(entry.acceptance_template.spec)


def test_the_taste_notes_are_folded_from_the_owners_rows():
    entry = VocabularyRegistry(default_entries()).require("props.harbor.crates")
    folded = aggregate_taste_notes(
        seed_taste_rows(), author="casey", subject_prefix="harbor.crates"
    )
    assert [note.reason_code for note in folded] == [
        note.reason_code for note in entry.taste_notes
    ]
    by_code = {note.reason_code: note for note in folded}
    assert by_code["too_busy"].basis == "4/4 kept"
    assert by_code["too_busy"].code == "keep"
    assert by_code["too_empty"].basis == "0/2 kept"
    assert by_code["too_empty"].code == "avoid"


def test_a_word_maps_to_its_recipe_entry_path():
    assert entry_path_for("props.harbor.crates") == "harbor.crates"
    assert entry_path_for("props.harbor.racks") == "harbor.racks"
    assert entry_path_for("material.wood.weathering") == "wood.weathering"
    # The spec's own example carries no namespace segment and is its own path.
    assert entry_path_for("bridge.rope") == "bridge.rope"


def test_the_registry_finds_the_word_that_owns_an_entry_path():
    registry = VocabularyRegistry(default_entries())
    entry = registry.word_for_entry_path("harbor.crates")
    assert entry is not None
    assert entry.word == "props.harbor.crates"
    assert registry.word_for_entry_path("nowhere") is None


def test_a_word_keeps_its_own_schema():
    registry = VocabularyRegistry()
    with pytest.raises(Exception):
        registry.add(
            registry.require("props.harbor.crates").model_copy(
                update={"params": {"type": "object", "additionalProperties": True}}
            )
        )
