"""Service layer. Each service owns one spec lifecycle and speaks to the
store through audit events only — there is no other write path."""
from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class Core:
    settings: Settings
    store: LedgerStore
    registry: NodeRegistry = field(init=False)
    recipes: RecipeStore = field(default_factory=UnavailableRecipeStore)
    gate_engine: MergeGateEngine = field(default_factory=UnavailableMergeGateEngine)
    telemetry: Telemetry = field(default_factory=BlindTelemetry)
    power: Power = field(default_factory=RecordOnlyPower)

    def __post_init__(self) -> None:
        if not hasattr(self, "registry") or self.registry is None:
            self.registry = ProjectionNodeRegistry(self.store)

    @classmethod
    def open(cls, settings: Settings, **ports) -> "Core":
        from ..artifacts import ArtifactStore

        store = LedgerStore(
            settings.db_path, ArtifactStore(settings.artifacts_dir),
            kid_actors=frozenset(settings.kid_actors),
        )
        return cls(settings=settings, store=store, **ports)
