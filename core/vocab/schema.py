"""The §1.5 param-schema subset: what a word's params may be, and how a call is checked.

Spec §1.5, verbatim:

    The **param schema subset** (bounded so a word is always validatable and
    diffable, and a character can never smuggle free text):

    - allowed types: `integer`, `number` (both require `minimum`/`maximum`),
      `string` only as `enum`, `boolean`, `integer` seed;
    - ≤ 8 properties, `additionalProperties: false`, no nesting deeper than 2;
    - canonical params JSON ≤ 512 bytes.

Two distinct failures, kept distinct on purpose:

* `SchemaError` — the *word* is broken (its own schema breaks the subset).
  That is a core fault, not a caller's, and it is loud.
* `ParamsError` — the *caller* broke the schema. This is the refusal that
  happens "at the door" (§1.5: "Anything outside the schema is refused at the
  door"), and it carries a closed reason code so the refusal can be audited
  and said in character.

One extension beyond the spec's subset is documented in `README.md`: the
`x-cross-field` keyword. The spec's own slice words need it — §6.1 defines
`props.harbor.crates` with `from_library 0–count`, a bound that cannot be
expressed as a static `maximum`.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .hashing import canonical_json

__all__ = [
    "ALLOWED_PARAM_TYPES",
    "MAX_PROPERTIES",
    "MAX_PARAMS_BYTES",
    "MAX_DEPTH",
    "SchemaError",
    "ParamsError",
    "validate_schema",
    "validate_params",
    "param_schema_ok",
]

#: §1.5 — the allowed property types.
ALLOWED_PARAM_TYPES: tuple[str, ...] = ("integer", "number", "string", "boolean")

#: §1.5 — "≤ 8 properties".
MAX_PROPERTIES = 8

#: §1.5 — "canonical params JSON ≤ 512 bytes".
MAX_PARAMS_BYTES = 512

#: §1.5 — "no nesting deeper than 2" (depth 0 is the params object itself).
MAX_DEPTH = 2

#: The only comparison operators the `x-cross-field` extension understands.
CROSS_FIELD_OPS: tuple[str, ...] = ("<=", ">=", "==", "<", ">")


class SchemaError(Exception):
    """The word's own schema breaks the §1.5 subset. A core fault, not a caller's."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class ParamsError(Exception):
    """The caller's params break the schema. Refused at the door."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def validate_schema(schema: Mapping[str, Any]) -> None:
    """Check a word's param schema against the §1.5 subset.

    Raises `SchemaError` on the first violation. The order of the checks is
    deliberate: depth first, so a schema that nests is told it nests rather
    than being told its type is wrong.
    """
    if not isinstance(schema, Mapping):
        raise SchemaError("schema_not_an_object", "params schema is an object")
    if schema.get("type") != "object":
        raise SchemaError("schema_not_an_object", "params schema has type 'object'")
    if schema.get("additionalProperties") is not False:
        raise SchemaError("additional_properties_allowed", "additionalProperties is false")

    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise SchemaError("no_properties", "schema has at least one property")
    if len(properties) > MAX_PROPERTIES:
        raise SchemaError(
            "too_many_properties",
            f"{len(properties)} properties, the subset allows {MAX_PROPERTIES}",
        )

    for name, prop in properties.items():
        _validate_property_schema(name, prop)

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise SchemaError("required_not_a_list", "required is a list")
    for name in required:
        if name not in properties:
            raise SchemaError(
                "required_property_unknown", f"required names unknown property {name!r}"
            )

    for rule in schema.get("x-cross-field", []):
        _validate_cross_field_rule(rule, properties)


def validate_params(schema: Mapping[str, Any], params: Mapping[str, Any]) -> None:
    """Check a call's params against a word's schema.

    Raises `ParamsError` with a closed reason code. Nothing outside the schema
    survives this call: unknown properties, wrong types, out-of-range numbers,
    values outside an enum, missing required properties, violated cross-field
    bounds and oversized param blobs are all refused.
    """
    if not isinstance(params, Mapping):
        raise ParamsError("params_not_an_object", "params is an object")

    properties: Mapping[str, Any] = schema.get("properties", {})
    required = schema.get("required", [])

    for name in params:
        if name not in properties:
            raise ParamsError("unknown_property", f"{name!r} is not a parameter of this word")

    for name in required:
        if name not in params:
            raise ParamsError("missing_property", f"{name!r} is required")

    for name, value in params.items():
        _validate_value(name, value, properties[name])

    for rule in schema.get("x-cross-field", []):
        _check_cross_field(rule, params)

    encoded = canonical_json(params).encode("utf-8")
    if len(encoded) > MAX_PARAMS_BYTES:
        raise ParamsError(
            "params_too_large",
            f"{len(encoded)} bytes, the subset allows {MAX_PARAMS_BYTES}",
        )


def param_schema_ok(schema: Mapping[str, Any]) -> bool:
    """True when the schema breaks no rule of the subset."""
    try:
        validate_schema(schema)
    except SchemaError:
        return False
    return True


# --- internals -----------------------------------------------------------------


def _validate_property_schema(name: str, prop: Any) -> None:
    if not isinstance(prop, Mapping):
        raise SchemaError("property_not_an_object", f"property {name!r} is an object")
    if _schema_depth(prop) > MAX_DEPTH:
        raise SchemaError(
            "nesting_too_deep", f"property {name!r} nests deeper than {MAX_DEPTH}"
        )

    ptype = prop.get("type")
    if ptype not in ALLOWED_PARAM_TYPES:
        raise SchemaError(
            "type_not_allowed",
            f"property {name!r} has type {ptype!r}, the subset allows {list(ALLOWED_PARAM_TYPES)}",
        )

    if ptype in ("integer", "number"):
        low, high = prop.get("minimum"), prop.get("maximum")
        if low is None or high is None:
            raise SchemaError(
                "bounds_missing", f"property {name!r} of type {ptype!r} needs minimum and maximum"
            )
        if not isinstance(low, (int, float)) or isinstance(low, bool):
            raise SchemaError("bound_not_a_number", f"property {name!r} has a non-numeric minimum")
        if not isinstance(high, (int, float)) or isinstance(high, bool):
            raise SchemaError("bound_not_a_number", f"property {name!r} has a non-numeric maximum")
        if low > high:
            raise SchemaError("bounds_inverted", f"property {name!r} has minimum above maximum")

    if ptype == "string":
        enum = prop.get("enum")
        if not isinstance(enum, list) or not enum:
            raise SchemaError(
                "string_without_enum", f"property {name!r} is a string and needs an enum"
            )
        if not all(isinstance(value, str) for value in enum):
            raise SchemaError("enum_not_strings", f"property {name!r} has a non-string enum")

    if ptype == "boolean" and ({"minimum", "maximum"} & set(prop)):
        raise SchemaError(
            "bounds_on_boolean", f"property {name!r} is a boolean and takes no bounds"
        )


def _schema_depth(prop: Mapping[str, Any]) -> int:
    """Depth of a property schema: a leaf is 1, an object of properties is 2."""
    if prop.get("type") == "object" or "properties" in prop:
        nested = prop.get("properties")
        if isinstance(nested, Mapping):
            deepest = max((_schema_depth(child) for child in nested.values()), default=0)
            return 1 + deepest
        return 2
    return 1


def _validate_cross_field_rule(rule: Any, properties: Mapping[str, Any]) -> None:
    if not isinstance(rule, Mapping):
        raise SchemaError("cross_field_not_an_object", "x-cross-field entry is an object")
    left, right, op = rule.get("left"), rule.get("right"), rule.get("op")
    if op not in CROSS_FIELD_OPS:
        raise SchemaError("cross_field_op_unknown", f"operator {op!r} is not supported")
    for side in (left, right):
        if side not in properties:
            raise SchemaError(
                "cross_field_property_unknown", f"x-cross-field names unknown property {side!r}"
            )


def _validate_value(name: str, value: Any, prop: Mapping[str, Any]) -> None:
    ptype = prop.get("type")

    if ptype == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParamsError("type_mismatch", f"{name!r} is an integer")
        _check_range(name, value, prop)
    elif ptype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParamsError("type_mismatch", f"{name!r} is a number")
        _check_range(name, value, prop)
    elif ptype == "string":
        if not isinstance(value, str):
            raise ParamsError("type_mismatch", f"{name!r} is a string")
        if value not in prop.get("enum", []):
            raise ParamsError(
                "not_in_enum", f"{name!r} is one of {list(prop.get('enum', []))}"
            )
    elif ptype == "boolean":
        if not isinstance(value, bool):
            raise ParamsError("type_mismatch", f"{name!r} is a boolean")


def _check_range(name: str, value: float, prop: Mapping[str, Any]) -> None:
    low, high = prop.get("minimum"), prop.get("maximum")
    if low is not None and value < low:
        raise ParamsError("out_of_range", f"{name!r} is at least {low}")
    if high is not None and value > high:
        raise ParamsError("out_of_range", f"{name!r} is at most {high}")


def _check_cross_field(rule: Mapping[str, Any], params: Mapping[str, Any]) -> None:
    left, right, op = rule["left"], rule["right"], rule["op"]
    if left not in params or right not in params:
        return  # a missing side is a required-property matter, not a bound
    lhs, rhs = params[left], params[right]
    if not isinstance(lhs, (int, float)) or not isinstance(rhs, (int, float)):
        return  # non-numeric sides cannot be compared; their own types are checked above
    ok = {
        "<=": lhs <= rhs,
        ">=": lhs >= rhs,
        "==": lhs == rhs,
        "<": lhs < rhs,
        ">": lhs > rhs,
    }[op]
    if not ok:
        raise ParamsError(
            "cross_field_violation", f"{left!r} {op} {right!r} is required"
        )


def _iter_properties(schema: Mapping[str, Any]) -> Iterable[str]:
    return schema.get("properties", {}).keys()
