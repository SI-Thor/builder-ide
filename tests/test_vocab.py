"""The closed vocabulary (§1.5).

A word is a typed parameter schema, never a prompt. The bounds are the
point: a character can call a word and cannot smuggle free text through
it, because the schema is closed, the properties are few, the types are
enumerated, and anything outside is refused *at the door* and audited.
"""
from __future__ import annotations

import pytest

from core.errors import Refused
from core.events import character_actor, core_actor
from core.svc.vocab import VocabService

from tests.conftest import seed_branch, seed_nodes


def schema(**props) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props}


def add_rope(core, **overrides):
    entry = {
        "word": "bridge.rope", "kind": "prop", "status": "active",
        "owner_character": "prop-maker",
        "params": schema(material={"type": "string", "enum": ["tarred", "new"]},
                         diameter_m={"type": "number", "minimum": 0.1, "maximum": 0.4}),
    }
    entry.update(overrides)
    return VocabService(core).add_word(entry, core_actor())


# ------------------------------------------------------------- the schema subset

def test_a_word_must_be_an_object_schema(core):
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": {"material": {"type": "string"}}}, core_actor())
    assert "type object" in e.value.message


def test_a_schema_must_forbid_additional_properties(core):
    """Otherwise free text rides in on an extra property."""
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": {"type": "object", "properties": {}}}, core_actor())
    assert "additionalProperties" in e.value.message


def test_a_schema_may_have_at_most_eight_properties(core):
    props = {f"p{i}": {"type": "boolean"} for i in range(9)}
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": schema(**props)}, core_actor())
    assert "8 properties" in e.value.message


def test_a_string_property_must_be_an_enum(core):
    """A free-text string is exactly what the vocabulary forbids."""
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": schema(material={"type": "string"})}, core_actor())
    assert "enum" in e.value.message


def test_a_number_needs_a_minimum_and_a_maximum(core):
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": schema(diameter_m={"type": "number"})}, core_actor())
    assert "minimum" in e.value.message


def test_a_property_type_outside_the_subset_is_refused(core):
    with pytest.raises(Refused) as e:
        VocabService(core).add_word({
            "word": "bridge.rope", "kind": "prop", "owner_character": "prop-maker",
            "params": schema(thing={"type": "object"})}, core_actor())
    assert "type must be one of" in e.value.message


def test_the_params_must_fit_in_512_bytes(core):
    """§1.5: canonical params ≤ 512 bytes."""
    add_rope(core, params=schema(pad={"type": "string", "enum": ["x" * 600]}))
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"pad": "x" * 600})
    assert "512" in e.value.message


# ------------------------------------------------------------- calling a word

def test_a_valid_call_returns_a_validated_edit(core):
    add_rope(core)
    seed_branch(core, "br_main")
    seed_nodes(core, "br_main", [{"node_id": "span_south", "entry_path": "bridge.rope",
                                  "kind": "structure"}])
    out = VocabService(core).call("prop-maker", "bridge.rope",
                                  {"material": "tarred", "diameter_m": 0.2},
                                  node="span_south")
    assert out["edit"]["ops"]


def test_an_unknown_word_is_refused_and_audited(core):
    """The refusal is the "I can't do that yet" moment — and it is audited."""
    from core.errors import NotFound

    with pytest.raises(NotFound):
        VocabService(core).call("prop-maker", "nope.nothing", {})
    refused = core.store.events_since(0, types=["vocab.call"])
    assert len(refused) == 1
    assert refused[0].refused is True
    assert refused[0].payload["refusal_reason"] == "unknown word"


def test_a_param_outside_the_schema_is_refused_at_the_door(core):
    add_rope(core)
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"colour": "red"})
    assert "outside the word's schema" in e.value.message
    refused = core.store.events_since(0, types=["vocab.call"])
    assert refused[0].refused is True


def test_a_free_text_value_for_an_enum_property_is_refused(core):
    add_rope(core)
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"material": "purple"})
    assert "enum" in e.value.message
    assert core.store.events_since(0, types=["vocab.call"])[0].refused is True


def test_a_value_below_the_minimum_is_refused(core):
    add_rope(core)
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"diameter_m": 0.01})
    assert "minimum" in e.value.message


def test_a_word_that_is_not_active_is_refused(core):
    add_rope(core, status="coming-soon")
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"material": "tarred"})
    assert "coming-soon" in e.value.message
    assert core.store.events_since(0, types=["vocab.call"])[0].refused is True


def test_another_characters_word_is_refused(core):
    add_rope(core)
    with pytest.raises(Refused) as e:
        VocabService(core).call("companion", "bridge.rope", {"material": "tarred"})
    assert "belongs to prop-maker" in e.value.message


def test_a_call_needs_a_target_that_exists(core):
    """Once the registry has been published, a call may not name a node
    that is not in it."""
    add_rope(core)
    seed_branch(core, "br_main")
    seed_nodes(core, "br_main", [{"node_id": "span_south", "entry_path": "bridge.rope",
                                  "kind": "structure"}])
    with pytest.raises(Refused) as e:
        VocabService(core).call("prop-maker", "bridge.rope", {"material": "tarred"},
                                node="span_nowhere")
    assert "node registry" in e.value.message
    # the refusal is audited too
    assert core.store.events_since(0, types=["vocab.call"])[0].refused is True


def test_a_call_without_a_published_registry_is_a_proposal(core):
    """Before the recipe half publishes a registry, a call is not blocked —
    it is simply a proposal."""
    add_rope(core)
    out = VocabService(core).call("prop-maker", "bridge.rope", {"material": "tarred"},
                                  node="span_south")
    assert out["committed"] is False  # the recipe half is not here
    assert out["edit"]["ops"]


# ------------------------------------------------------------- the word list

def test_the_word_list_carries_the_status_and_the_owner(core):
    add_rope(core)
    words = VocabService(core).list()
    assert len(words) == 1
    assert words[0].word == "bridge.rope"
    assert words[0].status == "active"
    assert words[0].owner_character == "prop-maker"


def test_a_word_can_be_retired(core):
    svc = VocabService(core)
    add_rope(core)
    svc.set_status("bridge.rope", "retired", core_actor())
    assert svc.get("bridge.rope").status == "retired"


def test_an_unknown_status_is_refused(core):
    svc = VocabService(core)
    add_rope(core)
    with pytest.raises(Refused):
        svc.set_status("bridge.rope", "maybe", core_actor())


def test_calling_a_retired_word_is_refused(core):
    svc = VocabService(core)
    add_rope(core)
    svc.set_status("bridge.rope", "retired", core_actor())
    with pytest.raises(Refused) as e:
        svc.call("prop-maker", "bridge.rope", {"material": "tarred"})
    assert "retired" in e.value.message
