"""Attaching the vendored WHY kernel (``core.why``) to builder-ide's records.

Every asset, vocabulary entry, recipe branch and work order carries a
justification chain — who or what it serves — rooted in plan goals (spec
§1.9 Tasks) and owner-kept branches (spec §1.2). When a root dies, its
dependents become **questionable, not deleted** (kernel status ``unknown``);
only certified lifecycle facts (rejected branches, reverted goals, terminally
failed orders) give death with certainty, and even then nothing is deleted.

- ``graph``      records -> kernel inputs, and the root mapping (ADR-0002)
- ``lifecycle``  the borrowed behaviours: labels, weights, the one gate
- ``service``    statuses, because-chains, the morning-report view
"""

from core.justification.graph import (
    GOAL_ALIVE_STATES,
    GOAL_DEAD_STATES,
    GOAL_WITHDRAWN_STATES,
    ProjectRecords,
    build_graph,
)
from core.justification.lifecycle import (
    LABELS,
    WEIGHTS,
    label,
    may_enter_new_work,
    weight,
)
from core.justification.service import (
    KINDS,
    ChainStep,
    Justification,
    JustificationService,
    MorningReport,
)

__all__ = [
    "GOAL_ALIVE_STATES", "GOAL_DEAD_STATES", "GOAL_WITHDRAWN_STATES",
    "ProjectRecords", "build_graph",
    "LABELS", "WEIGHTS", "label", "may_enter_new_work", "weight",
    "KINDS", "ChainStep", "Justification", "JustificationService",
    "MorningReport",
]
