from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from .store import PrecedentStore, Precedent


class VerdictType(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_HUMAN = "ask_human"


@dataclass(frozen=True, kw_only=True)
class Verdict:
    type: VerdictType
    reason: str
    matched_precedents: List[str]
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


class Validator:
    def __init__(self, store: PrecedentStore, rules: Optional[Dict[str, str]] = None):
        self.store = store
        self.rules = rules or {}

    def validate(self, proposal: str, proposal_keys: List[str]) -> Verdict:
        matched_rules = []
        precedent_matches = self.store.match(proposal_keys)

        for rule_key, rule_text in self.rules.items():
            if rule_key in proposal_keys:
                matched_rules.append(rule_key)

        overridden = set()
        allow_from_precedent = []
        deny_from_precedent = []

        for p in precedent_matches:
            if p.rule_override:
                overridden.add(p.rule_override)
            if p.decision.strip().lower() == "allow":
                allow_from_precedent.append(p.id)
            elif p.decision.strip().lower() == "deny":
                deny_from_precedent.append(p.id)

        active_rules = [k for k in matched_rules if k not in overridden]

        if deny_from_precedent:
            return Verdict(
                type=VerdictType.DENY,
                reason=f"Denied by precedent: {deny_from_precedent[0]}",
                matched_precedents=deny_from_precedent,
                rule_matches=active_rules,
            )

        if allow_from_precedent:
            return Verdict(
                type=VerdictType.ALLOW,
                reason=f"Allowed by precedent: {allow_from_precedent[0]}",
                matched_precedents=allow_from_precedent,
                rule_matches=active_rules,
            )

        if active_rules:
            return Verdict(
                type=VerdictType.ALLOW,
                reason=f"Allowed by default rule: {active_rules[0]}",
                matched_precedents=[],
                rule_matches=active_rules,
            )

        return Verdict(
            type=VerdictType.ASK_HUMAN,
            reason="No matching rule or precedent exists for this proposal.",
            matched_precedents=[],
            rule_matches=[],
        )
