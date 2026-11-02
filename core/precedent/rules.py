"""Rules as data: the standing constraints, in one shape a human can read.

A **rule** is a standing constraint with a key, an effect and a text.
The shape lives here; the content lives in ``core/precedent/seeds.py``,
as data — so the standing constraints can be read, diffed, edited and
reviewed like any other document, instead of being buried in validator
code. "Hard rules as data" is the point: the rules that never bend are
rows in a table, not branches in a function.

Three things a rule carries beyond v1's ``{key: text}`` mapping:

- **an effect.** ``allow``, ``deny`` or ``ask_human``. A v1 plain-string
  rule stays legal and means an ``allow`` rule (that was the only kind
  v1 had).
- **a ``hard`` flag.** A hard rule never bends: no precedent's
  ``rule_override`` removes it. Only a rule that denies may be hard — a
  permission that cannot be taken away is not a hard rule, it is just a
  permission.
- **a source.** Where the text came from, so a reader can check the row
  against the document that made it.

Matching is by key: a rule answers a proposal when its key is one of the
proposal's keys. A key is a dotted identifier and may not contain a
comma (the markdown format renders a precedent's keys comma-separated).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Union


class RuleEffect(Enum):
    """What a rule does to a proposal that carries its key."""

    ALLOW = "allow"
    DENY = "deny"
    ASK_HUMAN = "ask_human"


@dataclass(frozen=True, kw_only=True)
class Rule:
    """One standing constraint."""

    #: The proposal key this rule answers to.
    key: str
    #: What it does to the proposal.
    effect: RuleEffect = RuleEffect.ALLOW
    #: The rule, in a sentence a human can read.
    text: str
    #: True when the rule never bends. Only a ``deny`` may be hard.
    hard: bool = False
    #: Where the text comes from (a document, a file, a conversation).
    source: str = ""

    def __post_init__(self) -> None:
        if "," in self.key:
            raise ValueError(f"a rule key may not contain a comma: {self.key!r}")
        if self.hard and self.effect is not RuleEffect.DENY:
            raise ValueError(
                f"only a denying rule may be hard: {self.key!r} is "
                f"{self.effect.value}"
            )

    @classmethod
    def coerce(cls, key: str, spec: Union[str, "Rule"]) -> "Rule":
        """Accept a v1 ``{key: text}`` value: a string is an allow rule."""
        if isinstance(spec, Rule):
            return spec
        return cls(key=key, text=spec, effect=RuleEffect.ALLOW)
