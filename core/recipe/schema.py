"""The vocabulary param schema subset — core-spec v2 §1.5.

A word is always validatable and diffable, and a character can never smuggle
free text. The subset is deliberately small, so it is enforced here in code
rather than delegated to a general JSON-Schema engine:

* allowed types: ``integer``, ``number`` (both require ``minimum``/``maximum``),
  ``string`` only as ``enum``, ``boolean``;
* at most 8 properties, ``additionalProperties: false``, no nesting deeper
  than 2;
* canonical params JSON at most 512 bytes.

Anything outside the schema is refused at the door — that refusal is the
"I can't do rope yet" moment (D §21:08).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.recipe.canonical import canonical_json
from core.recipe.errors import SchemaDefinitionError

__all__ = [
    "ParamViolation",
    "MAX_PROPERTIES",
    "MAX_PARAMS_BYTES",
    "MAX_NESTING_DEPTH",
    "validate_schema_definition",
    "validate_params",
    "StaticSchemaRegistry",
]

MAX_PROPERTIES = 8
MAX_PARAMS_BYTES = 512
MAX_NESTING_DEPTH = 2

_SCALAR_TYPES = {"integer", "number", "string", "boolean"}


@dataclass(frozen=True)
class ParamViolation:
    """One refusal, addressed by the path inside the params."""

    path: str
    message: str
    code: str = "schema"

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message, "code": self.code}


def validate_schema_definition(schema: dict[str, Any], depth: int = 1) -> None:
    """Check a schema against the §1.5 subset. Raises on any breach."""
    if not isinstance(schema, dict):
        raise SchemaDefinitionError("a param schema is an object")
    if schema.get("type") != "object":
        raise SchemaDefinitionError("a param schema describes an object")
    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        raise SchemaDefinitionError("additionalProperties must be false")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise SchemaDefinitionError("properties must be an object")
    if len(properties) > MAX_PROPERTIES:
        raise SchemaDefinitionError(
            f"a param schema carries at most {MAX_PROPERTIES} properties"
        )

    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise SchemaDefinitionError(f"property {name!r} must have a schema")
        kind = prop.get("type")
        if kind not in _SCALAR_TYPES and kind != "object":
            raise SchemaDefinitionError(
                f"property {name!r} has type {kind!r}; the subset allows "
                f"{sorted(_SCALAR_TYPES | {'object'})}"
            )
        if kind in {"integer", "number"}:
            for bound in ("minimum", "maximum"):
                if not isinstance(prop.get(bound), (int, float)) or isinstance(
                    prop.get(bound), bool
                ):
                    raise SchemaDefinitionError(
                        f"property {name!r} of type {kind} requires a numeric {bound}"
                    )
            if prop["minimum"] > prop["maximum"]:
                raise SchemaDefinitionError(
                    f"property {name!r} has minimum above maximum"
                )
        if kind == "string":
            enum = prop.get("enum")
            if not isinstance(enum, list) or not enum:
                raise SchemaDefinitionError(
                    f"property {name!r} of type string requires a non-empty enum"
                )
            if not all(isinstance(v, str) for v in enum):
                raise SchemaDefinitionError(
                    f"property {name!r} of type string has a non-string enum member"
                )
        if kind == "object":
            if depth + 1 > MAX_NESTING_DEPTH:
                raise SchemaDefinitionError(
                    f"property {name!r} nests deeper than {MAX_NESTING_DEPTH}"
                )
            validate_schema_definition(prop, depth=depth + 1)


def _check_value(path: str, value: Any, prop: dict[str, Any], depth: int) -> list[ParamViolation]:
    kind = prop.get("type")
    violations: list[ParamViolation] = []

    if value is None:
        return [
            ParamViolation(path, "null is not a valid value", code="type")
        ]

    if kind == "boolean":
        if not isinstance(value, bool):
            violations.append(ParamViolation(path, "expected a boolean", code="type"))
        return violations

    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            violations.append(
                ParamViolation(path, "expected an integer", code="type")
            )
            return violations
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            violations.append(ParamViolation(path, "expected a number", code="type"))
            return violations
    elif kind == "string":
        if not isinstance(value, str):
            violations.append(ParamViolation(path, "expected a string", code="type"))
            return violations
        if value not in prop.get("enum", []):
            violations.append(
                ParamViolation(
                    path,
                    f"value is not one of the enum {prop.get('enum')}",
                    code="enum",
                )
            )
            return violations
    elif kind == "object":
        if not isinstance(value, dict):
            violations.append(ParamViolation(path, "expected an object", code="type"))
            return violations
        if depth + 1 > MAX_NESTING_DEPTH:
            violations.append(
                ParamViolation(path, "nests deeper than the subset allows", code="depth")
            )
            return violations
        return validate_params(value, prop, depth=depth + 1)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = prop.get("minimum")
        maximum = prop.get("maximum")
        if minimum is not None and value < minimum:
            violations.append(
                ParamViolation(path, f"value is below the minimum {minimum}", code="minimum")
            )
        if maximum is not None and value > maximum:
            violations.append(
                ParamViolation(path, f"value is above the maximum {maximum}", code="maximum")
            )
    return violations


def validate_params(
    params: dict[str, Any], schema: dict[str, Any], depth: int = 1
) -> list[ParamViolation]:
    """Validate params against a schema. Returns the refusals (empty = fine)."""
    if not isinstance(params, dict):
        return [ParamViolation("", "params must be an object", code="type")]

    violations: list[ParamViolation] = []

    encoded = canonical_json(params)
    if len(encoded.encode("utf-8")) > MAX_PARAMS_BYTES:
        violations.append(
            ParamViolation(
                "",
                f"params exceed {MAX_PARAMS_BYTES} canonical bytes",
                code="size",
            )
        )

    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    for name, value in sorted(params.items()):
        prop = properties.get(name)
        if prop is None:
            violations.append(
                ParamViolation(name, "property is not in the vocabulary schema", code="unknown")
            )
            continue
        violations.extend(_check_value(name, value, prop, depth))
    return violations


class StaticSchemaRegistry:
    """Param schemas by entry path, with a suffix fallback for vocabulary words.

    A word is ``props.harbor.crates`` while an entry path is
    ``harbor.crates``; the registry resolves the word to the path by suffix
    when the path is not registered directly. An ambiguous suffix is an
    error, never a guess.
    """

    def __init__(self, schemas: dict[str, dict[str, Any]] | None = None) -> None:
        self._schemas: dict[str, dict[str, Any]] = {}
        for word, schema in (schemas or {}).items():
            validate_schema_definition(schema)
            self._schemas[word] = schema

    def register(self, word: str, schema: dict[str, Any]) -> None:
        validate_schema_definition(schema)
        self._schemas[word] = schema

    def words(self) -> list[str]:
        return sorted(self._schemas)

    def schema_for(self, entry_path: str) -> dict[str, Any] | None:
        exact = self._schemas.get(entry_path)
        if exact is not None:
            return exact
        suffix = "." + entry_path
        matches = [
            word
            for word in sorted(self._schemas)
            if word.endswith(suffix) and word != entry_path
        ]
        if len(matches) == 1:
            return self._schemas[matches[0]]
        if len(matches) > 1:
            raise SchemaDefinitionError(
                f"entry path {entry_path!r} matches several vocabulary words: {matches}"
            )
        return None
