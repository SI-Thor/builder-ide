"""Service layer. Each service owns one spec lifecycle and speaks to the
store through audit events only — there is no other write path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..config import Settings
from ..ports import (
    BlindTelemetry,
    MergeGateEngine,
    NodeRegistry,
    Power,
    ProjectionNodeRegistry,
    RecipeStore,
    RecordOnlyPower,
    Telemetry,
    UnavailableMergeGateEngine,
    UnavailableRecipeStore,
)
from ..store import LedgerStore

if TYPE_CHECKING:  # pragma: no cover - the type is only for readers
    from .gc_bridge import GcBridge


def _build_gc_bridge(settings: Settings):
    """The gc bridge on this store, or None when gc is not here.

    The bridge owns gc's ledger, and that ledger lives next to builder-ide's
    own in the store's data directory (`$BUILDER_HOME/gc-ledger.jsonl`).
    Nothing here raises: a builder-ide without gc behaves exactly as a
    builder-ide without gc did before the bridge existed.
    """
    try:
        from .gc_bridge import GC_LEDGER_NAME, GcBridge
    except Exception:  # pragma: no cover - the bridge half may not be landed
        return None
    try:
        return GcBridge(ledger_path=settings.home / GC_LEDGER_NAME)
    except Exception:  # pragma: no cover - the bridge must never break the core
        return None


@dataclass
class Core:
    settings: Settings
    store: LedgerStore
    registry: NodeRegistry = field(init=False)
    recipes: RecipeStore = field(default_factory=UnavailableRecipeStore)
    gate_engine: MergeGateEngine = field(default_factory=UnavailableMergeGateEngine)
    telemetry: Telemetry = field(default_factory=BlindTelemetry)
    power: Power = field(default_factory=RecordOnlyPower)
    #: The window onto the general contractor (`core.svc.gc_bridge`). None
    #: when the bridge is not landed or could not be built — every caller
    #: reads it as "no gc here" and carries on.
    gc: "GcBridge | None" = None

    def __post_init__(self) -> None:
        if not hasattr(self, "registry") or self.registry is None:
            self.registry = ProjectionNodeRegistry(self.store)
        if self.gc is None:
            self.gc = _build_gc_bridge(self.settings)

    @classmethod
    def open(cls, settings: Settings, **ports) -> "Core":
        from ..artifacts import ArtifactStore

        store = LedgerStore(
            settings.db_path, ArtifactStore(settings.artifacts_dir),
            kid_actors=frozenset(settings.kid_actors),
        )
        return cls(settings=settings, store=store, **ports)
