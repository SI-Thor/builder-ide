"""The engine seam — the recipe on one side, the engine on the other.

    core.recipe (ours, above the engine)          infinigen, behind adapters
    ─────────────────────────────────────         ──────────────────────────
    Recipe / RecipeEntry / EnginePin   ──►  Engine.generate_stage / reexecute
    version_hash + seeds + ops         ──►  Engine.render_preview
    the compiled-output rule (§7.11)   ◄──  Engine.export

Why this seam exists is one sentence of the engine decision (E, "What would
make this recommendation wrong"): *define our own recipe schema above
procfunc, so an upstream change is a re-implementation of one adapter rather
than a change to every recipe we have written.* A v1 → v2 engine change is
one adapter, and plan §3 week-1 item 3 makes that a pass/fail: **a recipe
written today survives an engine swap under it; the adapter is the only
thing that changes.**

The contract's five rules
-------------------------

1. **The recipe is ours.** Every request carries the recipe in *our* schema
   (:class:`~core.records.Recipe` — entries, seeds, constraints, pin). An
   engine never sees an engine-native format, and a generator reference is
   a *name* the adapter resolves, not code the engine is asked to trust.

2. **The pin is checked.** Every request's ``recipe.engine_pin`` must equal
   the engine's own reported pin (§1.1, RV patch 13 — the config hash is
   load-bearing). A mismatch is :class:`~core.engine.errors.EnginePinMismatch`:
   the swap is an explicit pin edit, never a silent reinterpretation (X R9).

3. **Same request, same bytes.** Determinism is the stage-hit invariant
   (§1.9: a hit is byte-identical to re-evaluation) and what job dedup
   (§5.3) converges on. No wall-clock, no hostname, no ambient state may
   reach the bytes.

4. **Stage keys are canonical.** ``StageResult.stage_key`` *is*
   :func:`core.recipe.stagecache.stage_cache_key` over ``(version_hash,
   engine pin, stage name, dep keys)`` — one home for the key; engines
   report it, callers verify it, and a swapped engine changes every key
   (the cache invalidates honestly rather than serving stale work).

5. **The lower layer belongs to the engine.** What a stage's ``data``
   *is* differs by engine — v1 a stage output blob, v2 the traced instance
   graph (E §2: the instance-level graph is the recipe's lower layer). The
   seam carries it as bytes plus the mechanism that produced it; only
   :meth:`Engine.reexecute` interprets it, and only for a base its own
   flavour produced.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.engine.errors import EnginePinMismatch
from core.records import EnginePin, Op, Recipe

__all__ = [
    "Engine",
    "EngineCapabilities",
    "EngineDescriptor",
    "ExportRequest",
    "ExportResult",
    "PreviewRequest",
    "PreviewResult",
    "ReexecuteRequest",
    "StageMechanism",
    "StageRequest",
    "StageResult",
    "check_pin",
    "expected_stage_key",
]

#: How a stage result was produced. The honest difference between engines:
#: v2 edits the recorded graph (E §2, ``replace_in_graph`` + ``chosen_idx``);
#: v1 can only re-evaluate the dirty stage from scratch; the fake says so.
StageMechanism = Literal["fake", "graph-edit", "full-reeval", "resample"]


class EngineCapabilities(BaseModel):
    """What an engine can do — surfaced so callers refuse rather than guess."""

    stages: bool = True
    previews: bool = True
    #: Compiled one-way outputs (§7.11); the format list is the engine's own.
    export_formats: list[str] = Field(default_factory=list)
    #: Which :data:`StageMechanism` ``reexecute`` achieves.
    reexecute: StageMechanism = "full-reeval"


class EngineDescriptor(BaseModel):
    """What the engine says it is. ``pin`` is §1.1's :class:`EnginePin`
    verbatim, so it drops straight into a ``Recipe``; ``source`` is the one
    human sentence a card or a log line shows."""

    flavour: Literal["fake", "infinigen-1x", "infinigen-2-procfunc", "resident"]
    pin: EnginePin
    capabilities: EngineCapabilities
    source: str


# --------------------------------------------------------------------------- requests
# Each request is self-contained: the recipe document (ours), the version
# hash it was committed as, and the operation's own parameters. No engine
# holds recipe state between calls — the store is the only keeper.


class StageRequest(BaseModel):
    """Generate one stage of a recipe version (§1.9).

    ``entries`` scopes the stage to a subset of the recipe's generator
    entries — a per-entry stage request names exactly one. Scoping is what
    makes "edit one room re-solves only the touched room" an engine fact
    and not a hope: an engine asked for one entry's stage must not charge
    (or trace) its siblings. ``None`` means the whole recipe.
    """

    recipe: Recipe
    version_hash: str
    stage: str
    #: Upstream stage-cache keys this stage consumes — part of the key.
    dep_keys: list[str] = Field(default_factory=list)
    #: The entry paths this stage covers; None = every generator entry.
    entries: list[str] | None = None


class ReexecuteRequest(BaseModel):
    """Re-execute one stage under a recipe diff — partial regeneration.

    ``recipe`` is the **post-diff** document, ``ops`` the diff itself (§1.1's
    op list), ``base`` the recorded stage result being edited. The dirty-set
    contract is the caller's (``core.recipe.dirty``); this is its engine
    half: untouched entries must come out byte-identical.
    """

    recipe: Recipe
    version_hash: str
    stage: str
    ops: list[Op] = Field(default_factory=list)
    base: StageResult
    dep_keys: list[str] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    """Render a preview at a rung of the ladder — the night's sealed bets
    are scored against exactly these inputs (§1.7 ``render_spec``)."""

    recipe: Recipe
    version_hash: str
    #: What is being rendered — entry paths or node scope ("harbor.crates").
    subject: str
    rung: int
    resolution: str = "480p"
    seed: int


class ExportRequest(BaseModel):
    """Compile the recipe to a one-way output (§7.11: USD/glTF is compiled,
    never round-tripped)."""

    recipe: Recipe
    version_hash: str
    format: str
    profile: str = "preview"


# --------------------------------------------------------------------------- results


class StageResult(BaseModel):
    """A stage's side effects, content-addressed the way §1.0 artifacts are."""

    stage_key: str
    data: bytes
    artifact: dict  # {sha256, kind, bytes} — core.artifacts' descriptor shape
    mechanism: StageMechanism
    #: Measured wall time; ``None`` means not measured (never a plausible zero).
    wall_ms: float | None = None


class PreviewResult(BaseModel):
    data: bytes
    artifact: dict
    rung: int
    seed: int
    resolution: str
    wall_ms: float | None = None


class ExportResult(BaseModel):
    data: bytes
    artifact: dict
    format: str
    profile: str
    wall_ms: float | None = None


# --------------------------------------------------------------------------- the seam


@runtime_checkable
class Engine(Protocol):
    """The one interface every engine adapter implements.

    The fake (:mod:`core.engine.fake`) exists so tests and the acceptance
    suites run the seam without a checkout; the two adapter skeletons
    (:mod:`core.engine.infinigen1`, :mod:`core.engine.infinigen2`) are the
    v1 (subprocess) and v2 + procfunc (in-process) shapes. Pointing the
    core at a real engine is configuration (``core.engine.open_engine``).
    """

    def describe(self) -> EngineDescriptor:
        """The engine's pin and capabilities — asked before any work."""

    def generate_stage(self, request: StageRequest) -> StageResult:
        """Generate one stage; the result's key is the canonical stage key."""

    def reexecute(self, request: ReexecuteRequest) -> StageResult:
        """Re-execute a recorded stage under a recipe diff."""

    def render_preview(self, request: PreviewRequest) -> PreviewResult:
        """Render a preview at a rung; deterministic in the whole request."""

    def export(self, request: ExportRequest) -> ExportResult:
        """Compile to a one-way output format."""


# --------------------------------------------------------------------------- helpers


def check_pin(descriptor: EngineDescriptor, recipe: Recipe) -> None:
    """Rule 2: refuse a recipe pinned to an engine this one is not.

    The pins are compared whole — repo, commit, config hash, blender and
    python — because the stage-cache key is a function of all of them: an
    engine that honoured a foreign pin would poison the cache with work
    built under different settings than the pin promises.
    """
    if recipe.engine_pin != descriptor.pin:
        raise EnginePinMismatch(
            f"recipe {recipe.id} is pinned to {recipe.engine_pin.repo}@"
            f"{recipe.engine_pin.commit} (config {recipe.engine_pin.config}); "
            f"this engine is {descriptor.pin.repo}@{descriptor.pin.commit} "
            f"(config {descriptor.pin.config}). An engine swap is an explicit "
            "pin edit — never a silent reinterpretation.",
            engine=descriptor.flavour,
            recipe_pin=recipe.engine_pin.model_dump(mode="json"),
            engine_pin=descriptor.pin.model_dump(mode="json"),
        )


def expected_stage_key(
    request: StageRequest | ReexecuteRequest, descriptor: EngineDescriptor
) -> str:
    """Rule 4: the key a stage result must carry — computed by the one
    canonical function, never by the engine's own arithmetic."""
    from core.recipe.stagecache import stage_cache_key

    return stage_cache_key(
        request.version_hash,
        descriptor.pin,
        request.stage,
        request.dep_keys,
    )
