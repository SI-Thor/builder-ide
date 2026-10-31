"""Partial regeneration — a recipe edit through the seam, minus the reuse.

The flow is the dirty-set contract (``core/engine/DIRTY.md``) made into
one call:

1. **entry granularity** — the dirty set between the two versions:
   ``core.recipe.dirty``'s §1.1 terms (touched, constraint-coupled,
   asset-coupled) **plus key drift** (an entry whose effective stage key
   changed is dirty whatever the ops looked like — content decides);
2. **stage granularity** — for every generator entry, the content key is
   looked up in the stage cache. A hit skips the engine entirely. A miss
   either re-executes (``Engine.reexecute`` with the entry's ops and the
   base stage — the graph-edit path, verdict ``partial``) or regenerates
   the one entry (a scoped ``StageRequest``, verdict ``miss``). The
   engine-reported stage key is verified against the canonical
   arithmetic (contract rule 4) and the result filed under the content
   key, with the request key kept beside it as provenance;
3. **subtree granularity** — when the stage carried a graph, it is
   recorded in the graph store and diffed against the base's, so the
   report says what re-executed *inside* the stage: the changed nodes and
   their consumers (round 2's desk measurement, made a standing report).

Mechanism honesty, per engine: a graph-edit engine that refuses (the venv
boundary refuses ``replace``/``execute``, naming its missing piece) falls
back to a scoped regeneration and the refusal's reason rides in the
outcome — a re-trace of the one entry is the honest mechanism there, and
the untouched siblings are still hits. The resident engine plugs in
unchanged: its misses and partials land on a warm process (``DIRTY.md``
§6), which is where the scene server helps.
"""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from core.engine.contract import (
    Engine,
    ReexecuteRequest,
    StageRequest,
    StageResult,
    expected_stage_key,
)
from core.engine.errors import EngineFailed, EngineUnavailable
from core.engine.graph import GraphStore, diff_graphs, graphs_of_stage
from core.engine.stagecache import StageCache
from core.recipe.dirty import compute_dirty_set
from core.recipe.edits import ops_by_entry
from core.recipe.errors import IntegrityError
from core.recipe.models import Recipe
from core.recipe.stagecache import DEFAULT_ENTRY_STAGE_NAME, entry_stage_key
from core.recipe.store import RecipeStore

__all__ = ["Regenerator", "RegenerationReport", "EntryOutcome"]

Verdict = Literal["hit", "miss", "partial"]


def _stage_name(entry_path: str) -> str:
    """The request stage name of one entry's stage — namespaced by the
    entry so two entries' requests are never the same rule-4 key for
    different bytes (``DIRTY.md`` §2)."""
    return f"{DEFAULT_ENTRY_STAGE_NAME}:{entry_path}"


class EntryOutcome(BaseModel):
    """What one entry's stage did under one regeneration."""

    entry: str
    stage: str
    verdict: Verdict
    #: the content key — the cache address, stable across versions
    key: str
    base_key: str | None = None
    #: the engine's reported (version-keyed) request key, when it ran
    request_key: str | None = None
    mechanism: str | None = None
    reasons: list[str] = Field(default_factory=list)
    reused_bytes: int = 0
    produced_bytes: int = 0
    wall_ms: float | None = None
    graph: dict | None = None
    graph_diff: dict | None = None


class RegenerationReport(BaseModel):
    """One regeneration, entry by entry, with the cache's counters."""

    base: str
    head: str
    engine: str
    pin: str
    entries: list[EntryOutcome]
    cache: dict
    wall_ms: float | None = None

    def verdicts(self) -> dict[str, int]:
        counts = {"hit": 0, "miss": 0, "partial": 0}
        for outcome in self.entries:
            counts[outcome.verdict] += 1
        return counts


class Regenerator:
    """Dirty set in, engine work out, cache and graphs kept honest."""

    def __init__(
        self,
        *,
        engine: Engine,
        store: RecipeStore,
        cache: StageCache,
        graphs: GraphStore | None = None,
    ) -> None:
        self._engine = engine
        self._store = store
        self._cache = cache
        #: optional — without a graph store the contract stands at stage
        #: granularity and the report says so by carrying no graph rows
        self._graphs = graphs

    @property
    def cache(self) -> StageCache:
        """The cache, for session accounting: a caller that wants a clean
        per-session hit-rate denominator resets the counters here."""
        return self._cache

    # -- the one call ---------------------------------------------------------

    def regenerate(self, base: str, head: str) -> RegenerationReport:
        started = time.monotonic()
        base_document = self._store.get_document(base)
        head_document = self._store.get_document(head)
        head_version = self._store.get_version(head)
        descriptor = self._engine.describe()

        ops = self._store.diff(base, head)
        dirty = compute_dirty_set(base_document, head_document)
        grouped = ops_by_entry(head_document, ops)
        touched = {
            path
            for path, reasons in dirty.reasons.items()
            if "touched" in reasons
        }
        # the entries the §1.1 couplers pulled in (constraint- or
        # asset-coupled) — the only ones whose keys carry coupling
        # dep-keys. An untouched, uncoupled entry keeps its plain key,
        # and that is exactly what makes it a hit.
        coupled_entries = set(dirty.constraints) | set(dirty.assets)

        outcomes: list[EntryOutcome] = []
        for path, entry in sorted(head_document.entries.items()):
            if entry.generator is None:
                continue  # no generator, no stage (asset_ref and its kind)
            outcomes.append(
                self._regenerate_entry(
                    path,
                    base_document,
                    head_document,
                    head_version.root_hash,
                    ops=grouped.get(path, []),
                    coupled=(touched - {path}) if path in coupled_entries else set(),
                )
            )

        return RegenerationReport(
            base=base,
            head=head,
            engine=descriptor.source,
            pin=f"{descriptor.pin.repo}@{descriptor.pin.commit}",
            entries=outcomes,
            cache=self._cache.stats(),
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    # -- one entry -------------------------------------------------------------

    def _regenerate_entry(
        self,
        path: str,
        base_document: Recipe,
        head_document: Recipe,
        head_root_hash: str,
        *,
        ops: list,
        coupled: set[str],
    ) -> EntryOutcome:
        entry = head_document.entries[path]
        stage = _stage_name(path)
        descriptor = self._engine.describe()

        # dep-keys: the coupled stage keys. Conservative on purpose — every
        # touched entry's key, until the constraint coupler can name its
        # exact referent; over-keying costs a miss, never a stale serve.
        coupled_keys = sorted(
            coupled_path
            for coupled_path in (
                entry_stage_key(
                    other,
                    head_document.entries[other],
                    head_document.engine_pin,
                    seeds=head_document.seeds,
                )
                for other in sorted(coupled)
                if other in head_document.entries
            )
        )
        key = entry_stage_key(
            path, entry, head_document.engine_pin,
            seeds=head_document.seeds, dep_keys=coupled_keys,
        )

        cached = self._cache.get(key)
        if cached is not None:
            return EntryOutcome(
                entry=path, stage=stage, verdict="hit", key=key,
                reasons=["cached"],
                reused_bytes=len(cached.data),
                graph=(dict(self._graphs.ref_for(key)) if self._graphs else None),
            )

        base_entry = base_document.entries.get(path)
        base_key = (
            entry_stage_key(
                path, base_entry, base_document.engine_pin,
                seeds=base_document.seeds, dep_keys=coupled_keys,
            )
            if base_entry is not None
            else None
        )
        # peek, not get: consulting the base is bookkeeping, not a verdict
        base_stage = self._cache.peek(base_key) if base_key else None

        reasons: list[str] = []
        result: StageResult | None = None
        mechanism: str | None = None
        request: ReexecuteRequest | StageRequest | None = None
        did_reexecute = False

        if base_stage is not None and ops:
            reexecute = descriptor.capabilities.reexecute
            splicable = _param_shaped(ops)
            if reexecute == "graph-edit" and splicable:
                request = ReexecuteRequest(
                    recipe=head_document,
                    version_hash=head_root_hash,
                    stage=stage,
                    ops=ops,
                    base=StageResult(
                        stage_key=base_stage.request_key or base_key or "",
                        data=base_stage.data,
                        artifact=base_stage.artifact,
                        mechanism=base_stage.mechanism or "graph-edit",
                    ),
                )
                try:
                    result = self._engine.reexecute(request)
                    mechanism = result.mechanism
                    did_reexecute = True
                except (EngineUnavailable, EngineFailed) as refusal:
                    # the engine named its missing piece (the venv boundary
                    # refuses replace/execute): re-trace the one entry
                    reasons.append(f"reexecute refused: {refusal}")
            elif reexecute != "graph-edit":
                reasons.append(f"engine mechanism is {reexecute!r}")
            elif not splicable:
                reasons.append("ops are not param-shaped: a graph re-trace")

        if result is None:
            request = StageRequest(
                recipe=head_document,
                version_hash=head_root_hash,
                stage=stage,
                dep_keys=coupled_keys,
                entries=[path],
            )
            result = self._engine.generate_stage(request)
            mechanism = result.mechanism

        expected = expected_stage_key(request, descriptor)
        if result.stage_key != expected:
            raise IntegrityError(
                f"engine reported stage key {result.stage_key} where the "
                f"canonical arithmetic says {expected} (contract rule 4); "
                "the engine's keys are not ours to invent"
            )

        self._cache.put(
            key, result.data,
            artifact=result.artifact, mechanism=result.mechanism,
            request_key=result.stage_key,
        )
        graph_diff = None
        graph_row = None
        if self._graphs is not None:
            graph = graphs_of_stage(result.data).for_entry(path)
            if graph is not None:
                graph_row = dict(self._graphs.record(key, graph))
                base_graph = (
                    self._graphs.get(base_key)
                    if base_key and base_key in self._graphs
                    else None
                )
                if base_graph is not None:
                    graph_diff = diff_graphs(base_graph, graph).as_dict()

        return EntryOutcome(
            entry=path, stage=stage,
            # the verdict names the path that ran, not the engine's own
            # mechanism label (a re-tracing engine may label everything
            # graph-edit; only a real reexecute is a partial)
            verdict="partial" if did_reexecute else "miss",
            key=key, base_key=base_key,
            request_key=result.stage_key, mechanism=mechanism,
            reasons=reasons or (["generated"] if not ops else ["re-executed"]),
            produced_bytes=len(result.data),
            wall_ms=result.wall_ms,
            graph=graph_row, graph_diff=graph_diff,
        )


def _param_shaped(ops: list) -> bool:
    """Whether every op is a param edit an engine can splice into a graph
    (``graph_edits``' grammar). Structure edits — a seed, a generator swap,
    a constraint — re-trace; guessing what they mean in a graph is how a
    cache goes quietly stale."""
    from core.engine.infinigen2 import graph_edits

    try:
        graph_edits(ops)
    except ValueError:
        return False
    return True
