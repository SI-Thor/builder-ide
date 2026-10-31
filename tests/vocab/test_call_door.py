"""The door: a character's call, and every way it can be refused.

Spec §1.5: "Anything outside the schema is refused at the door — that
refusal, said in character, is the 'I can't do rope yet' moment."

And §1.8: refused calls are audited too — "the edges are the story".
"""

from __future__ import annotations

import pytest

from core.vocab import Actor, CallRefusal, RecipeEdit, VocabularyService
from core.vocab.call import REFUSAL_REASONS
from core.vocab.schema import validate_schema


@pytest.fixture
def service(world):
    return VocabularyService(
        registry=world.registry,
        ledger=world.ledger,
        clock=world.clock,
        recipes=world.recipes,
    )


def _call(service, **overrides):
    params = {"count": 12, "style": "weathered", "from_library": 6, "seed": 42}
    params.update(overrides.pop("params", {}))
    arguments = {
        "word": "props.harbor.crates",
        "params": params,
        "actor": Actor(kind="character", id="prop-maker", via="word"),
        "node": "crates_0001",
        "base": overrides.pop("base", None),
    }
    arguments.update(overrides)
    if arguments["base"] is None:
        arguments["base"] = service._recipes.head("br_main")
    return service.call(**arguments)


# --- the happy path ------------------------------------------------------------


def test_a_valid_call_produces_a_typed_edit(service):
    result = _call(service)
    assert isinstance(result, RecipeEdit)
    assert result.author == Actor(kind="character", id="prop-maker", via="word")
    assert {op.path for op in result.ops} == {
        "harbor.crates.params.count",
        "harbor.crates.params.style",
        "harbor.crates.params.from_library",
        "harbor.crates.params.seed",
    }
    assert all(op.op == "set" for op in result.ops)
    assert len(result.message) <= 80
    assert "\n" not in result.message


def test_a_successful_call_is_audited(service, world):
    _call(service)
    events = world.ledger.events(types=["vocab.call"])
    assert len(events) == 1
    assert events[0].payload["word"] == "props.harbor.crates"
    assert events[0].payload["refused"] is False
    assert events[0].payload["edit_id"]


# --- the negative cases --------------------------------------------------------


@pytest.mark.parametrize(
    "params, reason",
    [
        ({"count": 99}, "out_of_range"),
        ({"count": 0}, "out_of_range"),
        ({"style": "polished"}, "not_in_enum"),
        ({"lids": True}, "unknown_property"),
        ({"from_library": 40}, "cross_field_violation"),
        ({"count": "twelve"}, "type_mismatch"),
    ],
)
def test_out_of_schema_params_are_refused_at_the_door(service, params, reason):
    result = _call(service, params=params)
    assert isinstance(result, CallRefusal)
    assert result.reason == reason
    assert result.reason in REFUSAL_REASONS
    assert result.line  # said in character


def test_an_unknown_word_is_refused(service):
    result = _call(service, word="props.harbor.barrels")
    assert isinstance(result, CallRefusal)
    assert result.reason == "unknown_word"
    assert "barrels" in result.line


def test_a_coming_soon_word_is_refused(service, world):
    world.registry.set_status("props.harbor.racks", "coming-soon")
    result = _call(
        service, word="props.harbor.racks", params={"count": 2, "length_m": 1.0}
    )
    assert isinstance(result, CallRefusal)
    assert result.reason == "word_not_active"


def test_a_call_without_a_referent_is_refused(service):
    result = _call(service, node=None)
    assert isinstance(result, CallRefusal)
    assert result.reason == "no_referent"


def test_a_refused_call_is_audited_with_its_reason(service, world):
    _call(service, params={"count": 99})
    events = world.ledger.events(types=["vocab.call"])
    assert len(events) == 1
    assert events[0].payload["refused"] is True
    assert events[0].payload["reason"] == "out_of_range"
    assert events[0].payload["detail"]


def test_a_refusal_produces_no_edit(service, world):
    _call(service, params={"count": 99})
    assert not world.ledger.events(types=["edit.proposed"])


def test_the_words_own_schemas_are_valid(world):
    for entry in world.registry.words():
        validate_schema(entry.params)
