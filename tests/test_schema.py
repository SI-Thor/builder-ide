"""The vocabulary param schema subset (core-spec v2 §1.5).

A character can never smuggle free text: anything outside the schema is
refused at the door.
"""

from __future__ import annotations

import pytest

from builder_recipe.schema import (
    SchemaDefinitionError,
    StaticSchemaRegistry,
    validate_params,
    validate_schema_definition,
)


def test_a_number_inside_its_bounds_is_accepted():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"length_m": {"type": "number", "minimum": 0.5, "maximum": 60.0}},
    }
    assert validate_params({"length_m": 14.0}, schema) == []


def test_a_number_outside_its_bounds_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"length_m": {"type": "number", "minimum": 0.5, "maximum": 60.0}},
    }
    violations = validate_params({"length_m": 61.0}, schema)
    assert len(violations) == 1
    assert "length_m" in violations[0].path
    assert "maximum" in violations[0].message


def test_a_number_without_minimum_or_maximum_is_not_a_valid_schema():
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition(
            {"type": "object", "properties": {"length_m": {"type": "number"}}}
        )


def test_an_integer_refuses_a_float():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"planks": {"type": "integer", "minimum": 1, "maximum": 64}},
    }
    violations = validate_params({"planks": 8.5}, schema)
    assert len(violations) == 1
    assert "integer" in violations[0].message


def test_an_integer_refuses_a_boolean():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"planks": {"type": "integer", "minimum": 1, "maximum": 64}},
    }
    violations = validate_params({"planks": True}, schema)
    assert len(violations) == 1


def test_a_string_must_be_one_of_the_enum():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"style": {"type": "string", "enum": ["plain", "weathered"]}},
    }
    assert validate_params({"style": "weathered"}, schema) == []
    violations = validate_params({"style": "gleaming"}, schema)
    assert len(violations) == 1
    assert "enum" in violations[0].message


def test_a_string_without_an_enum_is_not_a_valid_schema():
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition(
            {"type": "object", "properties": {"style": {"type": "string"}}}
        )


def test_a_boolean_accepts_only_true_or_false():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"lids": {"type": "boolean"}},
    }
    assert validate_params({"lids": True}, schema) == []
    assert len(validate_params({"lids": "true"}, schema)) == 1


def test_an_unknown_property_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 48}},
    }
    violations = validate_params({"count": 3, "secret": "free text"}, schema)
    assert len(violations) == 1
    assert "secret" in violations[0].path


def test_a_missing_property_is_fine():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 48}},
    }
    assert validate_params({}, schema) == []


def test_a_null_value_is_refused():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 48}},
    }
    assert len(validate_params({"count": None}, schema)) == 1


def test_more_than_eight_properties_is_not_a_valid_schema():
    properties = {f"p{i}": {"type": "boolean"} for i in range(9)}
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition({"type": "object", "properties": properties})


def test_nesting_deeper_than_two_is_not_a_valid_schema():
    deep = {
        "type": "object",
        "properties": {
            "a": {
                "type": "object",
                "properties": {
                    "b": {
                        "type": "object",
                        "properties": {"c": {"type": "boolean"}},
                    }
                },
            }
        },
    }
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition(deep)


def test_nesting_two_levels_deep_is_accepted():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "a": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"b": {"type": "boolean"}},
            }
        },
    }
    validate_schema_definition(schema)
    assert validate_params({"a": {"b": True}}, schema) == []
    assert len(validate_params({"a": {"b": "yes"}}, schema)) == 1


def test_params_beyond_512_canonical_bytes_are_refused():
    long_note = "x" * 600
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"note": {"type": "string", "enum": [long_note]}},
    }
    violations = validate_params({"note": long_note}, schema)
    assert len(violations) == 1
    assert "512" in violations[0].message


def test_registry_finds_a_schema_by_entry_path(schemas: StaticSchemaRegistry):
    assert schemas.schema_for("harbor.crates") is not None


def test_registry_matches_a_word_by_its_path_suffix(schemas: StaticSchemaRegistry):
    schema = schemas.schema_for("harbor.crates")
    assert schema is not None
    assert schema["properties"]["count"]["maximum"] == 48


def test_registry_returns_none_for_an_unknown_entry_path(schemas: StaticSchemaRegistry):
    assert schemas.schema_for("nowhere.at.all") is None


def test_registry_refuses_an_ambiguous_suffix_match():
    registry = StaticSchemaRegistry(
        {
            "props.harbor.crates": {"type": "object", "properties": {}},
            "material.harbor.crates": {"type": "object", "properties": {}},
        }
    )
    with pytest.raises(SchemaDefinitionError):
        registry.schema_for("harbor.crates")


def test_registry_refuses_a_schema_that_is_not_in_the_subset():
    with pytest.raises(SchemaDefinitionError):
        StaticSchemaRegistry({"harbor.crates": {"type": "object", "properties": {"x": {"type": "string"}}}})
