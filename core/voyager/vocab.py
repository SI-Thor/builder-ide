"""The skill vocabulary — the closed, typed set of primitives a skill may use.

This is **not** the world's vocabulary (``core/vocab`` owns that one, and
it is about edits to the recipe). This is the vocabulary of *actions*:
what a skill is allowed to do to a world. Two doors stand in front of a
model-written body:

1. **the static door** (:func:`scan_primitives`) — the body's calls are
   read out of its text, and a name that is not a primitive of this world
   is a refusal, not a repair;
2. **the sandbox** — the body runs with only the primitives exposed, so a
   name the static door missed still cannot be reached at run time.

The vocabulary's schema subset is its own, and smaller than §1.5's,
because a primitive is a *call*, not an edit: strings may be free text
here, and the fields that matter are the bounds. The rules are written
down in :func:`validate_params` rather than inherited, because the two
vocabularies answer different questions.

A word's schema is::

    {name: {"type": "string"|"number"|"integer"|"boolean"|"array",
            "minimum": float, "maximum": float,     # numbers only
            "enum": [...],                            # any type
            "pattern": "regex",                       # strings only
            "maxItems": int,                          # arrays only
            "required": bool}}

``required`` on a property means the call must carry it; the property is
otherwise optional.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from core.tiles.models import TileStep

__all__ = [
    "SkillRefusal",
    "SkillVocabulary",
    "scan_primitives",
    "BODY_WORD",
    "BODY_SCHEMA",
    "body_step",
    "primitive_step",
]

#: The word that carries a skill's body into the tile's content address.
#: The body itself lives in the skill store; the tile keeps its hash, so
#: two different bodies are two different tiles even when they share a
#: title, a family and an author.
BODY_WORD = "voyager.skill_body"

#: The body's word schema: a content hash and a length.
BODY_SCHEMA: dict[str, Any] = {
    "sha256": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$", "required": True},
    "bytes": {"type": "integer", "minimum": 1, "maximum": 262144, "required": True},
}

_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class SkillRefusal(Exception):
    """A vocabulary refusal, with a closed reason code.

    The shape matches ``core.vocab.schema.ParamsError`` on purpose: the
    tile door reads ``.reason`` and ``.detail`` off whatever the
    vocabulary raises, so a refusal reads the same whichever vocabulary
    said it.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def scan_primitives(code: str, *, namespace: str = "mc") -> tuple[str, ...]:
    """The primitives a body calls, read out of its text.

    The scan is a **static door**, and it is deliberately simple: every
    ``<namespace>.<name>(`` in the body is a call. It cannot see through
    a computed name (``mc[name]()``) — the sandbox is what covers that
    case, and the two doors are stated as a pair for that reason.

    The result is sorted and de-duplicated, so the same body always
    produces the same list and the tile's content address is stable.
    """
    found: set[str] = set()
    for match in _CALL.finditer(code):
        head, tail = match.group(1), match.group(2)
        if head == namespace:
            found.add(f"{namespace}.{tail}")
    return tuple(sorted(found))


class SkillVocabulary:
    """The closed set of primitives, with their parameter schemas.

    It satisfies ``core.tiles.ports.VocabularyPort``, so the tile library
    can take it as its registry unchanged: ``require`` raises
    ``KeyError`` for an unknown word, and ``validate_params`` raises the
    vocabulary's own refusal when a call's parameters break the schema.
    """

    def __init__(self, words: Mapping[str, Mapping[str, Any]]) -> None:
        self._words: dict[str, Mapping[str, Any]] = {}
        for word, schema in words.items():
            self.add(word, schema)

    # -- the words -------------------------------------------------------------

    def add(self, word: str, schema: Mapping[str, Any]) -> None:
        """Add a primitive. The schema is checked on the way in.

        An empty schema is a **parameterless** primitive — a read that
        takes no arguments (``mc.achievements()``) — and it is a word
        like any other: ``validate_params`` refuses every parameter such
        a word is handed. The Crafter adapter's vocabulary is what
        asked for this; refusing the empty schema outright meant that
        world could not be built at all.
        """
        if not isinstance(schema, Mapping):
            raise SkillRefusal("schema_not_an_object", f"{word!r} has no schema")
        for name, prop in schema.items():
            if not isinstance(prop, Mapping):
                raise SkillRefusal("property_not_an_object", f"{word}.{name}")
            if prop.get("type") not in ("string", "number", "integer", "boolean", "array"):
                raise SkillRefusal("type_not_allowed", f"{word}.{name}")
        if word in self._words:
            raise SkillRefusal("word_known", f"{word!r} is already a primitive")
        self._words[word] = dict(schema)

    def require(self, word: str) -> Mapping[str, Any]:
        """The primitive's schema, or ``KeyError``."""
        try:
            return self._words[word]
        except KeyError:
            raise KeyError(f"unknown skill primitive {word!r}") from None

    def validate_params(self, word: str, params: Mapping[str, Any]) -> None:
        """Check a call's parameters against the primitive's schema.

        Raises :class:`SkillRefusal`. Nothing outside the schema survives
        this call: an unknown property, a missing required one, a wrong
        type, a number out of bounds, a value outside an enum, a string
        that does not match its pattern and an over-long array are all
        refused.
        """
        schema = self.require(word)
        if not isinstance(params, Mapping):
            raise SkillRefusal("params_not_an_object", f"{word}: params is not an object")
        for name in params:
            if name not in schema:
                raise SkillRefusal(
                    "unknown_property", f"{word}: {name!r} is not a parameter of this primitive"
                )
        for name, prop in schema.items():
            if prop.get("required") and name not in params:
                raise SkillRefusal("missing_property", f"{word}: {name!r} is required")
        for name, value in params.items():
            _check_value(word, name, value, schema[name])

    # -- the reads -------------------------------------------------------------

    def words(self) -> tuple[str, ...]:
        """Every primitive, sorted."""
        return tuple(sorted(self._words))

    def has(self, word: str) -> bool:
        return word in self._words

    def schema(self, word: str) -> Mapping[str, Any]:
        return self.require(word)

    def schema_map(self) -> Mapping[str, Mapping[str, Any]]:
        """Every primitive and its schema, by word.

        The coder prompt reads this. The ``hint`` on a property is the
        short human description of it — a prompt that carries sixteen
        hundred vanilla item ids is a prompt nobody reads, so the ids
        stay in the schema and the prompt carries the hint.
        """
        return {word: dict(schema) for word, schema in self._words.items()}


def _check_value(word: str, name: str, value: Any, prop: Mapping[str, Any]) -> None:
    """One parameter against one property schema."""
    kind = prop.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise SkillRefusal("type_mismatch", f"{word}.{name} must be a string")
        pattern: str | None = prop.get("pattern")
        if pattern is not None and not re.fullmatch(pattern, value):
            raise SkillRefusal("pattern_mismatch", f"{word}.{name} does not match {pattern!r}")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise SkillRefusal("type_mismatch", f"{word}.{name} must be a boolean")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SkillRefusal("type_mismatch", f"{word}.{name} must be an integer")
        _check_bounds(word, name, value, prop)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SkillRefusal("type_mismatch", f"{word}.{name} must be a number")
        _check_bounds(word, name, float(value), prop)
    elif kind == "array":
        if not isinstance(value, (list, tuple)):
            raise SkillRefusal("type_mismatch", f"{word}.{name} must be an array")
        limit = prop.get("maxItems")
        if limit is not None and len(value) > int(limit):
            raise SkillRefusal("too_many_items", f"{word}.{name} holds {len(value)} items")
    enum: Iterable[Any] | None = prop.get("enum")
    if enum is not None and value not in list(enum):
        raise SkillRefusal("not_in_enum", f"{word}.{name} is not one of the allowed values")


def _check_bounds(word: str, name: str, value: float, prop: Mapping[str, Any]) -> None:
    low = prop.get("minimum")
    high = prop.get("maximum")
    if low is not None and value < float(low):
        raise SkillRefusal("out_of_range", f"{word}.{name} is below {low}")
    if high is not None and value > float(high):
        raise SkillRefusal("out_of_range", f"{word}.{name} is above {high}")


# --- the tile steps ----------------------------------------------------------


def body_step(sha256: str, nbytes: int) -> TileStep:
    """The step that carries a body into a tile's content address."""
    return TileStep(
        word=BODY_WORD,
        path="skill.body",
        op="set",
        params={"sha256": sha256, "bytes": int(nbytes)},
    )


def primitive_step(word: str) -> TileStep:
    """The step that records a primitive the body calls.

    The step's path is ``skill.uses.<short>`` — the recipe's own path
    rule allows three dotted segments, and the short name keeps the
    primitive's namespace out of the path.
    """
    short = word.split(".")[-1]
    return TileStep(
        word=word,
        path=f"skill.uses.{short}",
        op="set",
        params={},
    )
