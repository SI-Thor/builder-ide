"""The validator: a pure function from a proposal to a verdict.

One question, answered the same way every time: *given what the board
has decided (the precedents) and what the standing constraints say (the
rules), what does this proposal get?* Three answers — ``allow``,
``deny``, ``ask_human`` — and the last one is a real answer, not a
failure: when nothing applies, the honest verdict is to ask a human.

**The order of resolution** (deny beats ask beats allow; a hard rule
beats everything; a case that overrides a rule removes that rule):

1. a **hard rule** that denies → ``DENY`` (never bent, not even by a
   precedent's ``rule_override``);
2. a **precedent** that denies → ``DENY``;
3. a **rule** that denies → ``DENY`` (unless the meeting precedent
   overrides its key);
4. a **precedent** that says ask → ``ASK_HUMAN``;
5. a **rule** that says ask → ``ASK_HUMAN``;
6. a **precedent** that allows → ``ALLOW``;
7. a **rule** that allows → ``ALLOW``;
8. nothing matched at all → ``ASK_HUMAN``.

A *soft* rule whose key a meeting precedent names in ``rule_override``
is removed in every step: that is what "this case decided the general
question" means. A hard rule is never removed.

**Determinism is a property, not a hope.** The verdict's content does
not depend on the order the keys arrived in, on dict order, or on which
process computes it: all lists in a verdict are sorted, the reason cites
the first item of a sorted list, and ``Verdict.canonical()`` is one
UTF-8 payload that two runs, two stores or two machines reproduce
exactly (``tests/precedent/test_determinism.py`` proves it, including
across processes).
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .rules import Rule, RuleEffect
from .store import PrecedentStore, Precedent


class VerdictType(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_HUMAN = "ask_human"


@dataclass(frozen=True, kw_only=True)
class Verdict:
    """What the validator said, and why."""

    type: VerdictType
    reason: str
    #: The ids of the precedents the verdict rests on, sorted.
    matched_precedents: List[str]
    #: The keys of the rules in force after any override, sorted.
    rule_matches: List[str]

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Verdict):
            return False
        return (
            self.type == other.type
            and self.reason == other.reason
            and sorted(self.matched_precedents) == sorted(other.matched_precedents)
            and sorted(self.rule_matches) == sorted(other.rule_matches)
        )

    def canonical(self) -> str:
        """The verdict as one deterministic UTF-8 payload, ready to hash."""
        return json.dumps(
            {
                "matched_precedents": sorted(self.matched_precedents),
                "reason": self.reason,
                "rule_matches": sorted(self.rule_matches),
                "type": self.type.value,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def digest(self) -> str:
        """``sha256:`` of ``canonical()``: the same verdict, the same digest."""
        return f"sha256:{hashlib.sha256(self.canonical().encode('utf-8')).hexdigest()}"


def _decision_of(precedent: Precedent) -> Optional[RuleEffect]:
    word = precedent.decision.strip().lower()
    if word == "allow":
        return RuleEffect.ALLOW
    if word == "deny":
        return RuleEffect.DENY
    if word in ("ask", "ask human", "ask_human", "askhuman"):
        return RuleEffect.ASK_HUMAN
    return None


class Validator:
    """A pure function over one store and one rule set."""

    def __init__(
        self,
        store: PrecedentStore,
        rules: Optional[Mapping[str, Union[str, Rule]]] = None,
    ):
        self.store = store
        #: key -> Rule. A v1 ``{key: text}`` value is an allow rule.
        self.rules: Dict[str, Rule] = {
            key: Rule.coerce(key, spec) for key, spec in (rules or {}).items()
        }

    def validate(self, proposal: str, proposal_keys: Sequence[str]) -> Verdict:
        """``proposal`` is the prose for a human; ``proposal_keys`` is
        what the rules and precedents match against.
        """
        keys = sorted(set(proposal_keys))
        key_set = set(keys)

        matched_rules = sorted(
            (rule for key, rule in self.rules.items() if key in key_set),
            key=lambda rule: rule.key,
        )
        precedents = self.store.match(list(keys))

        overrides = {p.rule_override for p in precedents if p.rule_override}
        # A hard rule bends for nothing: a rule_override naming its key
        # is a mistake in the precedent, not a licence.
        active_rules = [
            rule
            for rule in matched_rules
            if rule.hard or rule.key not in overrides
        ]

        hard_denies = [
            r for r in active_rules if r.hard and r.effect is RuleEffect.DENY
        ]
        deny_rules = [
            r for r in active_rules if not r.hard and r.effect is RuleEffect.DENY
        ]
        ask_rules = [
            r for r in active_rules if not r.hard and r.effect is RuleEffect.ASK_HUMAN
        ]
        allow_rules = [
            r for r in active_rules if not r.hard and r.effect is RuleEffect.ALLOW
        ]

        deny_cases: List[str] = []
        ask_cases: List[str] = []
        allow_cases: List[str] = []
        for p in precedents:
            effect = _decision_of(p)
            if effect is RuleEffect.DENY:
                deny_cases.append(p.id)
            elif effect is RuleEffect.ASK_HUMAN:
                ask_cases.append(p.id)
            elif effect is RuleEffect.ALLOW:
                allow_cases.append(p.id)

        rule_keys_in_force = sorted(r.key for r in active_rules)

        def verdict(kind: VerdictType, reason: str, matched: List[str]) -> Verdict:
            return Verdict(
                type=kind,
                reason=reason,
                matched_precedents=sorted(matched),
                rule_matches=rule_keys_in_force,
            )

        if hard_denies:
            rule = hard_denies[0]
            return verdict(
                VerdictType.DENY,
                f"Denied by hard rule: {rule.key} — {rule.text}",
                deny_cases,
            )
        if deny_cases:
            return verdict(
                VerdictType.DENY,
                f"Denied by precedent: {deny_cases[0]}",
                deny_cases,
            )
        if deny_rules:
            rule = deny_rules[0]
            return verdict(VerdictType.DENY, f"Denied by rule: {rule.key}", deny_cases)
        if ask_cases:
            return verdict(
                VerdictType.ASK_HUMAN,
                f"Ask a human: precedent {ask_cases[0]} says so.",
                ask_cases,
            )
        if ask_rules:
            rule = ask_rules[0]
            return verdict(
                VerdictType.ASK_HUMAN,
                f"Ask a human: rule {rule.key} says so.",
                ask_cases,
            )
        if allow_cases:
            return verdict(
                VerdictType.ALLOW,
                f"Allowed by precedent: {allow_cases[0]}",
                allow_cases,
            )
        if allow_rules:
            rule = allow_rules[0]
            return verdict(VerdictType.ALLOW, f"Allowed by rule: {rule.key}", [])

        return verdict(
            VerdictType.ASK_HUMAN,
            "No matching rule or precedent exists for this proposal.",
            [],
        )
