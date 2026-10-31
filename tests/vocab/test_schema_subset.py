"""The §1.5 param-schema subset: what a word may ask for, and what it may not.

Two halves:

* the **schema** half — a word's own schema must break no rule of the subset
  (a broken word is a core fault, and it is loud);
* the **params** half — a call's params must be inside the schema (this is the
  refusal that happens at the door).
"""

from __future__ import annotations

import pytest

from core.vocab.schema import (
    MAX_PARAMS_BYTES,
    MAX_PROPERTIES,
    ParamsError,
    SchemaError,
    param_schema_ok,
    validate_params,
    validate_schema,
)
from core.vocab.words import CRATES_PARAMS, RACKS_PARAMS, WEATHERING_PARAMS


# --- the schema half -----------------------------------------------------------


def test_the_slice_words_satisfy_the_subset():
    for schema in (CRATES_PARAMS, RACKS_PARAMS, WEATHERING_PARAMS):
        validate_schema(schema)


def test_a_schema_with_too_many_properties_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            f"p{index}": {"type": "integer", "minimum": 0, "maximum": 1}
            for index in range(MAX_PROPERTIES + 1)
        },
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "too_many_properties"


def test_a_string_without_an_enum_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "string_without_enum"


@pytest.mark.parametrize("ptype", ["integer", "number"])
def test_a_number_without_bounds_is_refused(ptype):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"size": {"type": ptype}},
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "bounds_missing"


def test_a_nested_object_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "crate": {
                "type": "object",
                "properties": {"lid": {"type": "boolean"}},
            }
        },
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "type_not_allowed"


def test_a_deeply_nested_object_is_refused_as_too_deep():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "crate": {
                "type": "object",
                "properties": {
                    "lid": {"type": "object", "properties": {"hinge": {"type": "boolean"}}}
                },
            }
        },
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "nesting_too_deep"


def test_additional_properties_must_be_false():
    schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 2}},
    }
    with pytest.raises(SchemaError) as error:
        validate_schema(schema)
    assert error.value.reason == "additional_properties_allowed"


def test_param_schema_ok_is_false_for_a_broken_schema():
    assert param_schema_ok(CRATES_PARAMS) is True
    assert param_schema_ok({"type": "object", "additionalProperties": False}) is False


# --- the params half -----------------------------------------------------------


def test_valid_params_pass():
    validate_params(
        CRATES_PARAMS,
        {"count": 12, "style": "weathered", "from_library": 6, "seed": 42},
    )


def test_an_unknown_property_is_refused():
    with pytest.raises(ParamsError) as error:
        validate_params(
            CRATES_PARAMS,
            {"count": 12, "style": "weathered", "from_library": 6, "lids": True},
        )
    assert error.value.reason == "unknown_property"


def test_a_missing_required_property_is_refused():
    with pytest.raises(ParamsError) as error:
        validate_params(CRATES_PARAMS, {"count": 12, "style": "weathered"})
    assert error.value.reason == "missing_property"


@pytest.mark.parametrize(
    "params, reason",
    [
        ({"count": "12", "style": "weathered", "from_library": 0}, "type_mismatch"),
        ({"count": 12.5, "style": "weathered", "from_library": 0}, "type_mismatch"),
        ({"count": 12, "style": "weathered", "from_library": True}, "type_mismatch"),
        ({"count": 0, "style": "weathered", "from_library": 0}, "out_of_range"),
        ({"count": 49, "style": "weathered", "from_library": 0}, "out_of_range"),
        ({"count": 12, "style": "polished", "from_library": 0}, "not_in_enum"),
        ({"count": 12, "style": "weathered", "from_library": 13}, "cross_field_violation"),
    ],
)
def test_out_of_schema_params_are_refused(params, reason):
    with pytest.raises(ParamsError) as error:
        validate_params(CRATES_PARAMS, params)
    assert error.value.reason == reason


def test_the_count_bound_on_from_library_is_enforced():
    # §6.1: "from_library 0–count" — the count-bound is the cross-field rule.
    validate_params(
        CRATES_PARAMS, {"count": 12, "style": "plain", "from_library": 12}
    )
    with pytest.raises(ParamsError):
        validate_params(
            CRATES_PARAMS, {"count": 12, "style": "plain", "from_library": 13}
        )


def test_an_oversized_param_blob_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "note": {"type": "string", "enum": ["x" * (MAX_PARAMS_BYTES + 10)]}
        },
    }
    with pytest.raises(ParamsError) as error:
        validate_params(schema, {"note": "x" * (MAX_PARAMS_BYTES + 10)})
    assert error.value.reason == "params_too_large"


def test_a_boolean_is_not_an_integer():
    # Python says bool is an int; the vocabulary does not.
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer", "minimum": 0, "maximum": 10}},
    }
    with pytest.raises(ParamsError) as error:
        validate_params(schema, {"count": True})
    assert error.value.reason == "type_mismatch"
