"""core.precedent: gaps -> precedent store -> validator -> BoardManifest.

The stable interface community-loop calls (keep it stable):

- ``PrecedentStore`` / ``Precedent`` / ``PrecedentStatus`` — the
  append-only store, and its human-editable markdown round-trip
  (``save_markdown`` / ``load_markdown`` / ``save_files`` /
  ``load_files``, ``Precedent.as_markdown`` / ``from_markdown``);
- ``Validator`` / ``Verdict`` / ``VerdictType`` — ``validate(proposal,
  proposal_keys)``; when nothing applies the verdict is ``ASK_HUMAN``;
- ``Rule`` / ``RuleEffect`` — rules as data, and the seed content
  (``seed_rules``, ``seed_precedents``, ``seed_store``,
  ``seed_validator``): the permission ladder, agent-world's no-grief
  rules, and the hard rules;
- ``BoardManifest`` — the ratified scope projection (``from_store``,
  ``save`` / ``load``, ``fingerprint``, ``ratified_keys``), read by
  ``core/drift``'s build-drift signal.
"""

from .store import PrecedentStore, Precedent, PrecedentStatus, parse_precedents
from .rules import Rule, RuleEffect
from .validator import Validator, Verdict, VerdictType
from .manifest import BoardManifest, parse_manifest
from .seeds import (
    HARD_RULES,
    NO_GRIEF_RULES,
    PERMISSION_LADDER_RULES,
    seed_precedents,
    seed_rules,
    seed_store,
    seed_validator,
)

__all__ = [
    "PrecedentStore",
    "Precedent",
    "PrecedentStatus",
    "parse_precedents",
    "Rule",
    "RuleEffect",
    "Validator",
    "Verdict",
    "VerdictType",
    "BoardManifest",
    "parse_manifest",
    "PERMISSION_LADDER_RULES",
    "NO_GRIEF_RULES",
    "HARD_RULES",
    "seed_rules",
    "seed_precedents",
    "seed_store",
    "seed_validator",
]
