"""The selection language — "rewind to here, keep these" as one line.

A selection is an expression over the rows of a ledger. It says which of the
ledger's events the human wants to keep; the rest are dropped with a reason,
and the ones that cannot be replayed onto the fork are parked with a reason.
Nothing is guessed and nothing is deleted: the ledger keeps every row it had.

The language is small on purpose. One expression, seven fields, eight
operators, three ways to combine:

    actor = Kite and kind in (tile.played, tile.authored)
    at >= 2026-11-01T05:00:00Z and at < 2026-11-01T07:00:00Z
    not (kind = judge.verdict) or verdict = accept
    id = tile_wall_01

The fields are the ones the design note names for the selection (by actor,
time range, event kind, tile/skill id, verdict), plus ``agent`` — the actor a
row is *about*, which is not the actor that wrote it — and ``seq``, the
ledger's own row number.

    =    equal (a list on the right means "one of")
    !=   not equal
    in   one of a list
    contains   the text contains
    >= > <= <   numeric comparison (only on ``at`` and ``seq``)

    and  or  not  ( )   combine expressions

The time field carries the ledger's own unit: **ticks** for a round log
(the Bevy world), **epoch seconds** for a timestamped ledger (the world's
SQLite ledger). An ISO-8601 literal is epoch seconds, so a timestamped
expression is refused against a tick ledger rather than silently comparing
nonsense.

Parsing is strict: every failure names the place it happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

__all__ = [
    "SelectionError",
    "Selection",
    "SelectionResult",
    "Row",
    "select",
    "parse",
    "FIELDS",
    "NUMERIC_FIELDS",
    "EPOCH",
    "TICK",
]

#: The time unit of a timestamped ledger: seconds since the epoch.
EPOCH = "epoch"

#: The time unit of a round log: the simulation's tick.
TICK = "tick"


class SelectionError(ValueError):
    """A selection that does not parse, or that cannot be evaluated.

    The message names the place: the character offset, the line, or the
    field that does not take that operator.
    """

    def __init__(self, message: str, *, text: str = "", position: int = -1) -> None:
        self.text = text
        self.position = position
        if text and position >= 0:
            caret = " " * position + "^"
            message = f"{message}\n  {text}\n  {caret}"
        super().__init__(message)


#: The fields a selection may read.
FIELDS: tuple[str, ...] = ("actor", "agent", "kind", "id", "verdict", "at", "seq")

#: The fields that hold a number.
NUMERIC_FIELDS: frozenset[str] = frozenset({"at", "seq"})

#: How a row's field maps to the row's attribute.
_FIELD_ATTRS: dict[str, str] = {
    "actor": "actor",
    "agent": "agent",
    "kind": "kind",
    "id": "entity_id",
    "verdict": "verdict",
    "at": "at",
    "seq": "seq",
}


class Row(Protocol):
    """One row of a ledger, as the selection reads it."""

    seq: int
    at: float
    actor: str
    agent: str
    kind: str
    entity_id: str
    verdict: str


# ==================================================================== values


@dataclass(frozen=True)
class Literal:
    """One value in an expression.

    ``kind`` is one of ``text``, ``number``, ``timestamp`` or ``list``.
    A list holds other literals.
    """

    kind: str
    text: str = ""
    number: float = 0.0
    items: tuple["Literal", ...] = ()

    def as_text(self) -> str:
        return self.text

    def as_number(self) -> float:
        return self.number

    def render(self) -> str:
        if self.kind == "list":
            return "(" + ", ".join(item.render() for item in self.items) + ")"
        if self.kind == "timestamp":
            return self.text
        return self.text


# ==================================================================== nodes


@dataclass(frozen=True)
class Compare:
    """One field compared with one value."""

    field: str
    op: str
    literal: Literal

    def evaluate(self, row: Row, unit: str) -> tuple[bool, str]:
        actual = _field_value(row, self.field)
        return _compare(self.field, self.op, actual, self.literal, unit)


@dataclass(frozen=True)
class And:
    children: tuple[Any, ...]

    def evaluate(self, row: Row, unit: str) -> tuple[bool, str]:
        reasons: list[str] = []
        for child in self.children:
            ok, reason = child.evaluate(row, unit)
            if not ok:
                reasons.append(reason)
        if reasons:
            return False, " and ".join(reasons)
        return True, ""


@dataclass(frozen=True)
class Or:
    children: tuple[Any, ...]

    def evaluate(self, row: Row, unit: str) -> tuple[bool, str]:
        reasons: list[str] = []
        for child in self.children:
            ok, reason = child.evaluate(row, unit)
            if ok:
                return True, ""
            reasons.append(reason)
        return False, " or ".join(reasons)


@dataclass(frozen=True)
class Not:
    child: Any

    def evaluate(self, row: Row, unit: str) -> tuple[bool, str]:
        ok, reason = self.child.evaluate(row, unit)
        if ok:
            return False, f"not ({reason})" if reason else "not ()"
        return True, ""


# ==================================================================== parsing

_WORD = re.compile(r"[A-Za-z0-9_.:/@#%+\-*]+")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_KEYWORDS = {"and", "or", "not"}


@dataclass(frozen=True)
class _Token:
    kind: str  # "word", "string", "op", "punct", "end"
    text: str
    position: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "(),":
            tokens.append(_Token("punct", char, index))
            index += 1
            continue
        if char in "=<>!":
            two = text[index : index + 2]
            if two in ("!=", ">=", "<="):
                tokens.append(_Token("op", two, index))
                index += 2
                continue
            if char in "=<>":
                tokens.append(_Token("op", char, index))
                index += 1
                continue
            raise SelectionError(f"unexpected {char!r}", text=text, position=index)
        if char in "\"'":
            close = text.find(char, index + 1)
            if close < 0:
                raise SelectionError("a quoted value is not closed", text=text, position=index)
            tokens.append(_Token("string", text[index + 1 : close], index))
            index = close + 1
            continue
        match = _WORD.match(text, index)
        if not match:
            raise SelectionError(
                f"unexpected {char!r}", text=text, position=index
            )
        tokens.append(_Token("word", match.group(0), index))
        index = match.end()
    tokens.append(_Token("end", "", length))
    return tokens


class _Parser:
    """A recursive-descent parser over the selection grammar.

    expression := or_expr
    or_expr    := and_expr ("or" and_expr)*
    and_expr   := unary ("and" unary)*
    unary      := "not" unary | "(" expression ")" | comparison
    comparison := FIELD OPERATOR VALUE
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _tokenize(text)
        self.index = 0

    # -- token helpers -----------------------------------------------------

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def take(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def at_keyword(self, word: str) -> bool:
        token = self.current
        return token.kind == "word" and token.text == word

    def fail(self, message: str) -> SelectionError:
        return SelectionError(message, text=self.text, position=self.current.position)

    # -- grammar -----------------------------------------------------------

    def parse(self) -> Any:
        node = self.parse_or()
        if self.current.kind != "end":
            raise self.fail(f"unexpected {self.current.text!r}")
        return node

    def parse_or(self) -> Any:
        children = [self.parse_and()]
        while self.at_keyword("or"):
            self.take()
            children.append(self.parse_and())
        if len(children) == 1:
            return children[0]
        return Or(tuple(children))

    def parse_and(self) -> Any:
        children = [self.parse_unary()]
        while self.at_keyword("and"):
            self.take()
            children.append(self.parse_unary())
        if len(children) == 1:
            return children[0]
        return And(tuple(children))

    def parse_unary(self) -> Any:
        if self.at_keyword("not"):
            self.take()
            return Not(self.parse_unary())
        if self.current.kind == "punct" and self.current.text == "(":
            self.take()
            node = self.parse_or()
            if not (self.current.kind == "punct" and self.current.text == ")"):
                raise self.fail("a group is not closed")
            self.take()
            return node
        return self.parse_comparison()

    def parse_comparison(self) -> Compare:
        token = self.current
        if token.kind != "word":
            raise self.fail(f"expected a field, found {token.text!r}")
        if token.text in _KEYWORDS:
            raise self.fail(f"{token.text!r} is not a field")
        field = token.text
        if field not in FIELDS:
            raise SelectionError(
                f"unknown field {field!r}; the fields are {', '.join(FIELDS)}",
                text=self.text,
                position=token.position,
            )
        self.take()
        op_token = self.current
        if op_token.kind == "word" and op_token.text in ("in", "contains"):
            op = op_token.text
            self.take()
        elif op_token.kind == "op":
            op = op_token.text
            self.take()
        else:
            raise self.fail(f"expected an operator after {field!r}")
        literal = self.parse_value()
        _check_types(field, op, literal, self.text, op_token.position)
        return Compare(field, op, literal)

    def parse_value(self) -> Literal:
        token = self.current
        if token.kind == "punct" and token.text == "(":
            self.take()
            items: list[Literal] = []
            if not (self.current.kind == "punct" and self.current.text == ")"):
                while True:
                    items.append(self.parse_value())
                    if self.current.kind == "punct" and self.current.text == ",":
                        self.take()
                        continue
                    break
            if not (self.current.kind == "punct" and self.current.text == ")"):
                raise self.fail("a list is not closed")
            self.take()
            if not items:
                raise self.fail("a list is empty")
            return Literal("list", "", 0.0, tuple(items))
        if token.kind == "string":
            self.take()
            return Literal("text", token.text)
        if token.kind == "word":
            self.take()
            return _literal_from_word(token.text)
        raise self.fail(f"expected a value, found {token.text!r}")


def _literal_from_word(word: str) -> Literal:
    if _TIMESTAMP.match(word):
        return Literal("timestamp", word, _epoch_of(word))
    try:
        return Literal("number", word, float(word))
    except ValueError:
        return Literal("text", word)


def _epoch_of(text: str) -> float:
    """An ISO-8601 timestamp as epoch seconds.

    A date without a time is midnight UTC. A ``Z`` is UTC; an offset is
    honoured. A naive timestamp is read as UTC: the ledgers this reads are
    UTC throughout.
    """
    value = text.strip()
    if value.endswith("Z") or value.endswith("z"):
        value = value[:-1] + "+00:00"
    value = value.replace(" ", "T", 1) if " " in value and "T" not in value else value
    if "T" not in value:
        value = value + "T00:00:00+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _check_types(field: str, op: str, literal: Literal, text: str, position: int) -> None:
    """Refuse a comparison that cannot mean anything."""
    numeric = field in NUMERIC_FIELDS
    if op in (">", ">=", "<", "<="):
        if not numeric:
            raise SelectionError(
                f"field {field!r} is not a number; {op!r} needs a number field",
                text=text,
                position=position,
            )
        if literal.kind not in ("number", "timestamp"):
            raise SelectionError(
                f"{op!r} needs a number, found {literal.render()!r}",
                text=text,
                position=position,
            )
    if op == "in" and literal.kind != "list":
        raise SelectionError(
            f"'in' needs a list, found {literal.render()!r}", text=text, position=position
        )
    if op == "=" and literal.kind == "list":
        for item in literal.items:
            if item.kind == "timestamp" and not numeric:
                raise SelectionError(
                    f"field {field!r} is not a number; a timestamp cannot be compared with it",
                    text=text,
                    position=position,
                )
    if op == "=" and literal.kind == "timestamp" and not numeric:
        raise SelectionError(
            f"field {field!r} is not a number; a timestamp cannot be compared with it",
            text=text,
            position=position,
        )
    if op in ("=", "!=") and literal.kind == "number" and not numeric:
        raise SelectionError(
            f"field {field!r} is not a number; {literal.render()!r} is one",
            text=text,
            position=position,
        )


# ==================================================================== compare


def _field_value(row: Row, field: str) -> Any:
    if field == "id":
        return row.entity_id
    return getattr(row, _FIELD_ATTRS[field])


def _compare(
    field: str, op: str, actual: Any, literal: Literal, unit: str
) -> tuple[bool, str]:
    """Compare one field with one literal. Returns (matched, reason-if-not)."""
    if op in (">", ">=", "<", "<="):
        left = float(actual)
        right = literal.as_number()
        ok = {
            ">": left > right,
            ">=": left >= right,
            "<": left < right,
            "<=": left <= right,
        }[op]
        if ok:
            return True, ""
        word = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below"}[op]
        return False, f"{field} ({_number_text(left)}) is not {word} {_number_text(right)}"

    if op == "in" or (op == "=" and literal.kind == "list"):
        options = literal.items if literal.kind == "list" else (literal,)
        for option in options:
            if _equal(actual, option, field, unit):
                return True, ""
        names = ", ".join(option.render() for option in options)
        return False, f"{field} ({_text(actual)!r}) is not one of ({names})"

    if op == "=":
        if _equal(actual, literal, field, unit):
            return True, ""
        return False, f"{field} ({_text(actual)!r}) is not {literal.render()!r}"

    if op == "!=":
        if not _equal(actual, literal, field, unit):
            return True, ""
        return False, f"{field} ({_text(actual)!r}) is {literal.render()!r}"

    if op == "contains":
        needle = literal.as_text()
        if needle in str(actual):
            return True, ""
        return False, f"{field} ({_text(actual)!r}) does not contain {needle!r}"

    raise SelectionError(f"unknown operator {op!r}")


def _equal(actual: Any, literal: Literal, field: str, unit: str) -> bool:
    if literal.kind == "timestamp":
        if unit == "tick":
            # A tick ledger has no dates: the comparison cannot mean
            # anything, so it does not match.
            return False
        return float(actual) == literal.as_number()
    if literal.kind == "number":
        try:
            return float(actual) == literal.as_number()
        except (TypeError, ValueError):
            return False
    return str(actual) == literal.as_text()


def _text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number_text(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


# ==================================================================== selection


@dataclass(frozen=True)
class Selection:
    """A parsed selection: the expression and the tree it parsed to."""

    text: str
    tree: Any
    time_unit: str = "epoch"

    def matches(self, row: Row, *, time_unit: str | None = None) -> bool:
        unit = time_unit or self.time_unit
        return self.tree.evaluate(row, unit)[0]

    def explain(self, row: Row, *, time_unit: str | None = None) -> str:
        """Why the row was not kept. Empty when it was kept."""
        unit = time_unit or self.time_unit
        matched, reason = self.tree.evaluate(row, unit)
        return "" if matched else reason

    def fields(self) -> set[str]:
        """The fields the expression reads."""
        found: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, Compare):
                found.add(node.field)
            elif isinstance(node, (And, Or)):
                for child in node.children:
                    walk(child)
            elif isinstance(node, Not):
                walk(node.child)

        walk(self.tree)
        return found

    def has_timestamp(self) -> bool:
        """Whether the expression carries an ISO-8601 literal."""
        found = [False]

        def walk(node: Any) -> None:
            if isinstance(node, Compare):
                if node.literal.kind == "timestamp":
                    found[0] = True
                for item in node.literal.items:
                    if item.kind == "timestamp":
                        found[0] = True
            elif isinstance(node, (And, Or)):
                for child in node.children:
                    walk(child)
            elif isinstance(node, Not):
                walk(node.child)

        walk(self.tree)
        return found[0]


def parse(text: str) -> Selection:
    """Parse a selection expression.

    Raises :class:`SelectionError` when the expression does not parse.
    """
    stripped = text.strip()
    if not stripped:
        raise SelectionError("a selection is empty", text=text, position=0)
    parser = _Parser(stripped)
    tree = parser.parse()
    return Selection(text=stripped, tree=tree)


# ==================================================================== select


@dataclass(frozen=True)
class SelectionResult:
    """What a selection kept, and what it dropped and why."""

    kept: tuple[Any, ...]
    dropped: tuple[tuple[Any, str], ...]
    selection: Selection
    time_unit: str = EPOCH

    @property
    def kept_seqs(self) -> list[int]:
        return [int(row.seq) for row in self.kept]

    @property
    def dropped_seqs(self) -> list[int]:
        return [int(row.seq) for row, _ in self.dropped]

    def reason_for(self, seq: int) -> str:
        """Why a row was dropped. Empty when it was kept."""
        for row, reason in self.dropped:
            if int(row.seq) == int(seq):
                return reason
        return ""


def select(ledger: Any, selection: Selection) -> SelectionResult:
    """Apply a selection to a ledger's rows.

    The ledger is anything with ``rows`` and a ``time_unit`` — the readers in
    :mod:`core.rewind.ledger` make two. A selection that carries a date is
    refused against a ledger whose time is ticks: the two cannot be compared,
    and a comparison that cannot mean anything must not be made.
    """
    unit = getattr(ledger, "time_unit", EPOCH)
    if unit == TICK and selection.has_timestamp():
        raise SelectionError(
            "a timestamp cannot be compared with a ledger whose time is ticks"
        )
    kept: list[Any] = []
    dropped: list[tuple[Any, str]] = []
    for row in ledger.rows:
        if selection.matches(row, time_unit=unit):
            kept.append(row)
        else:
            dropped.append((row, selection.explain(row, time_unit=unit)))
    return SelectionResult(
        kept=tuple(kept),
        dropped=tuple(dropped),
        selection=selection,
        time_unit=unit,
    )
