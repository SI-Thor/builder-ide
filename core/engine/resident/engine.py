"""The resident scene engine — a warm scene behind the engine seam.

The brief this implements is plan item 15 (draft 2, week 3): *"the measured
numbers say the win is builder wait and crash recovery, not edit→preview
latency — so the server's job is defined as holding the scene and surviving a
kill."*

So this class does two things, and refuses to pretend to do a third:

**Builder wait.** A builder's request goes to a process that is already
holding the scene. The tax the warm server removes is the *launch* — on this
box a cold Blender is ~0.25 s of imports (WS §4.2) and the v2 experiment
measured ~2.4 s per scene of process start-up (E §5.2). Warm pays it once;
batch pays it per request. What it does **not** remove is the render: the
research is explicit that on a real scene the render is 80–90 % of the wait
(WS §4.1), and this class never claims otherwise.

**Crash recovery.** The scene is a pure function of the recipe, so recovery
is a *replay*: the durable recipe is replayed onto a fresh resident and the
resulting state digest is compared with the checkpoint's. The spike measured
that replay at 0.50 s for 26 typed ops, with no ``.blend`` file anywhere in
the path (WS §4.4).

Around those two sit the four dials the brief names — health checks, a
restart policy, a checkpoint cadence and memory-growth guards — and the
durable recipe that makes the replay possible: an append-only journal, a
periodic snapshot and a checkpoint (WS §5.3: the journal is the truth, the
snapshot is periodic, and the whole-file rewrite per edit is *gone*).

Honest limits, stated here because they are the design:

* the resident is **single-tenant and serial** — one request at a time, on
  the resident's main thread, because ``bpy`` is not thread-safe (WS §5.1);
* the resident is a **derived cache, never a writer** (core-spec §1.9,
  decision 17): the *adapter* owns the journal, the resident owns only the
  scene in memory;
* a resident that dies mid-request loses that request, not the history: the
  journal is written **before** the scene is touched, so the replay always
  lands on the state the recipe describes.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from core.canon import bytes_hash, content_hash
from core.engine.contract import (
    EngineCapabilities,
    EngineDescriptor,
    ExportRequest,
    ExportResult,
    PreviewRequest,
    PreviewResult,
    ReexecuteRequest,
    StageRequest,
    StageResult,
    check_pin,
    expected_stage_key,
)
from core.engine.errors import EngineFailed, EnginePinMismatch
from core.engine.resident.journal import SceneJournal
from core.engine.resident.policy import ResidentPolicy
from core.engine.resident.transport import (
    ResidentCrashed,
    ResidentError,
    ResidentProcess,
    ResidentRefused,
    ResidentTimeout,
)
from core.recipe.edits import apply_ops, diff_recipes
from core.records import EnginePin, Op, Recipe

__all__ = ["ResidentEngine"]


class ResidentEngine:
    """A warm scene behind the seam: one resident process, kept warm."""

    def __init__(
        self,
        *,
        pin: EnginePin,
        root: Path | str,
        backend: str = "fake",
        python: str | None = None,
        policy: ResidentPolicy | None = None,
        worker: Path | str | None = None,
        env: dict[str, str] | None = None,
        log_name: str = "resident.log",
    ) -> None:
        self._pin = pin
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend
        self._python = python or "python3"
        self._env = env
        self._policy = policy or ResidentPolicy()
        self._log_path = self.root / log_name
        self._journal = SceneJournal(self.root).open()
        self._process: ResidentProcess | None = None
        #: the recipe the resident is currently at
        self._resident_recipe: Recipe | None = None
        self._capabilities = EngineCapabilities(
            stages=True, previews=True, export_formats=[], reexecute="graph-edit"
        )
        self._engine_label = "resident"
        self._restarts = 0
        self._starts = 0
        self._start_streak = 0
        self._resident_served = False
        self._recoveries = 0
        self._checkpoints = 0
        self._guard_recycles = 0
        self._ops_since_checkpoint = 0
        self._ops_since_growth_check = 0
        self._last_checkpoint_at = time.monotonic()
        self._last_health_check = 0.0
        self._baseline_rss_mb: float | None = None
        self._last_state_digest: str | None = None
        self._last_document_digest: str | None = None
        self._last_sync_applied_ops = False
        self._resident_started_at: float | None = None
        #: every request's wall time, in milliseconds — the builder wait
        self.requests: list[dict[str, Any]] = []

    # -- the seam ------------------------------------------------------------

    def describe(self) -> EngineDescriptor:
        return EngineDescriptor(
            flavour="resident",
            pin=self._pin,
            capabilities=self._capabilities,
            source=(
                f"resident scene · {self.backend} · {self.root} · "
                f"journal {self._journal.journal_path.name} · "
                f"restart budget {self._policy.max_restarts}"
            ),
        )

    def generate_stage(self, request: StageRequest) -> StageResult:
        check_pin(self.describe(), request.recipe)
        started = time.monotonic()
        self._ensure_resident()
        self._sync(request.recipe)
        data = self._call(
            "stage",
            {
                "stage": request.stage,
                "dep_keys": list(request.dep_keys),
                "version_hash": request.version_hash,
            },
        )
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage", "bytes": len(data)},
            mechanism=self._mechanism(),
            wall_ms=self._elapsed(started, "generate_stage"),
        )

    def reexecute(self, request: ReexecuteRequest) -> StageResult:
        check_pin(self.describe(), request.recipe)
        started = time.monotonic()
        self._ensure_resident()
        # rule 5 is checked once the resident has said which engine it is —
        # the label lives in the backend's describe, not in this adapter
        self._refuse_foreign_base(request.base)
        self._sync(request.recipe)
        data = self._call(
            "stage",
            {
                "stage": request.stage,
                "dep_keys": list(request.dep_keys),
                "version_hash": request.version_hash,
            },
        )
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage", "bytes": len(data)},
            mechanism=self._mechanism(),
            wall_ms=self._elapsed(started, "reexecute"),
        )

    def render_preview(self, request: PreviewRequest) -> PreviewResult:
        check_pin(self.describe(), request.recipe)
        started = time.monotonic()
        self._ensure_resident()
        self._sync(request.recipe)
        data = self._call(
            "preview",
            {
                "subject": request.subject,
                "rung": request.rung,
                "resolution": request.resolution,
                "seed": request.seed,
            },
        )
        return PreviewResult(
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "render", "bytes": len(data)},
            rung=request.rung,
            seed=request.seed,
            resolution=request.resolution,
            wall_ms=self._elapsed(started, "render_preview"),
        )

    def export(self, request: ExportRequest) -> ExportResult:
        check_pin(self.describe(), request.recipe)
        started = time.monotonic()
        # the resident reports its formats, so it has to be up before the
        # refusal can be the right one — a cold engine must not refuse what
        # it simply has not asked its backend for yet
        self._ensure_resident()
        formats = self.describe().capabilities.export_formats
        if request.format not in formats:
            raise ValueError(
                f"this engine exports {formats}, not {request.format!r}"
            )
        self._sync(request.recipe)
        data = self._call(
            "export", {"format": request.format, "profile": request.profile}
        )
        return ExportResult(
            data=data,
            artifact={
                "sha256": bytes_hash(data),
                "kind": f"export:{request.format}",
                "bytes": len(data),
            },
            format=request.format,
            profile=request.profile,
            wall_ms=self._elapsed(started, "export"),
        )

    # -- the resident's own surface -----------------------------------------

    def resident_state(self) -> dict:
        """The resident's scene state, and the digest the core computes from it.

        The digest is taken **here**, in the core, so the arithmetic has one
        home — and it is taken only when asked, because it is O(scene size)
        (WS §5.4).
        """
        result = self._call("state", {})
        state = result.get("state") or {}
        return {"state": state, "digest": content_hash(state)}

    def state_digest(self) -> str | None:
        """The digest of the last checkpointed state."""
        return self._last_state_digest

    def checkpoint(self) -> dict:
        """Write a checkpoint now: the document, the journal position, the
        scene's state digest."""
        if self._process is None or not self._process.alive():
            raise EngineFailed(
                "there is no resident to checkpoint; start one first"
            )
        state = self.resident_state()
        document = (
            self._resident_recipe.model_dump(mode="json")
            if self._resident_recipe is not None
            else {"entries": {}}
        )
        payload = self._journal.write_checkpoint(
            document=document, state_digest=state["digest"]
        )
        self._last_state_digest = state["digest"]
        self._ops_since_checkpoint = 0
        self._last_checkpoint_at = time.monotonic()
        self._checkpoints += 1
        return payload

    def restart(self) -> None:
        """Recycle the resident: stop it, start a new one, replay onto it.

        This is the path a crash takes and the path the memory guard takes.
        """
        self._restart_and_recover(reason="restart")

    def stop(self) -> None:
        """Shut the resident down and close the journal."""
        if self._process is not None:
            self._process.stop()
            self._process = None
        self._journal.close()

    close = stop

    def __enter__(self) -> "ResidentEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def stats(self) -> dict:
        """The engine's own counters — what the morning report would quote."""
        rss = self._process.rss_mb() if self._process is not None else None
        return {
            "pid": self._process.pid if self._process is not None else None,
            "restarts": self._restarts,
            "recoveries": self._recoveries,
            "checkpoints": self._checkpoints,
            "guard_recycles": self._guard_recycles,
            "requests": len(self.requests),
            "rss_mb": rss,
            "baseline_rss_mb": self._baseline_rss_mb,
            "peak_rss_mb": (
                self._process.peak_rss_mb() if self._process is not None else None
            ),
            "resident_alive": bool(self._process and self._process.alive()),
            "journal": self._journal.write_stats(),
        }

    # -- the resident's lifecycle -------------------------------------------

    def _ensure_resident(self) -> None:
        """Make sure there is a resident, and that it is healthy."""
        if self._process is None or not self._process.alive():
            self._start_resident()
            return
        self._maybe_health_check()
        self._maybe_recycle_for_uptime()

    def _start_resident(self) -> None:
        """Start a resident and put the recipe back on it.

        The restart budget is checked here rather than at the call site, so
        that a resident which dies on its own — not through the adapter's
        restart path — is counted too. A crash loop ends in an honest error,
        never in an infinite rebuild.
        """
        if self._starts > self._policy.max_restarts:
            raise EngineFailed(
                f"the resident has been started {self._starts} times, which is "
                f"past the policy's budget of {self._policy.max_restarts} "
                "restarts; refusing to rebuild it again",
                starts=self._starts,
                budget=self._policy.max_restarts,
            )
        if self._process is not None:
            self._process.stop()
        if self._starts >= 1 and not self._resident_served:
            # A crash loop must not become a spin loop: a resident that
            # died before serving anything is restarted after a wait that
            # doubles with each such death, up to the policy's cap. A
            # resident that *served* and then died is rebuilt at once —
            # its death was not a start-up failure, and the builder is
            # already waiting.
            self._start_streak += 1
            time.sleep(self._policy.backoff_for(self._start_streak))
        else:
            self._start_streak = 0
        self._resident_served = False
        self._starts += 1
        self._restarts = self._starts - 1
        self._process = ResidentProcess(
            python=self._python,
            backend=self.backend,
            root=self.root,
            log_path=self._log_path,
            pin=self._pin.model_dump(mode="json"),
            env=self._env,
        )
        self._process.start(timeout_s=self._policy.start_timeout_s)
        self._resident_started_at = time.monotonic()
        self._last_health_check = time.monotonic()
        # describe is part of coming up, not a request: it sits under the
        # start timeout, so a tight request deadline cannot kill a resident
        # that is still introducing itself
        described = self._process.call(
            "describe", {}, timeout_s=self._policy.start_timeout_s
        )
        self._check_reported_pin(described)
        capabilities = described.get("capabilities") or {}
        self._capabilities = EngineCapabilities(
            stages=bool(capabilities.get("stages", True)),
            previews=bool(capabilities.get("previews", True)),
            export_formats=list(capabilities.get("export_formats") or []),
            reexecute=capabilities.get("reexecute", "graph-edit"),
        )
        self._engine_label = str(described.get("engine", "resident"))
        self._recover_into(self._process)

    def _check_reported_pin(self, described: dict) -> None:
        """The resident must be the engine the recipe is pinned to.

        The same rule every flavour obeys (contract rule 2): a resident that
        silently reinterpreted a foreign pin would poison the stage cache.
        """
        reported = described.get("pin")
        if not isinstance(reported, dict):
            return
        try:
            resident_pin = EnginePin.model_validate(reported)
        except Exception:  # the pin the resident reports is not ours to fix
            return
        if resident_pin != self._pin:
            raise EnginePinMismatch(
                f"the resident reports {resident_pin.repo}@{resident_pin.commit} "
                f"(config {resident_pin.config}) but this engine is "
                f"{self._pin.repo}@{self._pin.commit} (config {self._pin.config}); "
                "an engine swap is an explicit pin edit — never a silent "
                "reinterpretation",
                engine="resident",
                recipe_pin=self._pin.model_dump(mode="json"),
                engine_pin=resident_pin.model_dump(mode="json"),
            )

    def _maybe_health_check(self) -> None:
        """Ask the resident whether it is alive — periodically, and always
        before trusting it with work."""
        if self._process is None:
            return
        now = time.monotonic()
        if now - self._last_health_check < self._policy.health_check_interval_s:
            return
        self._last_health_check = now
        try:
            self._process.ping(timeout_s=min(self._policy.request_timeout_s, 5.0))
        except ResidentError as exc:
            self._restart_and_recover(reason=f"health check failed: {exc}")

    def _maybe_recycle_for_uptime(self) -> None:
        limit = self._policy.max_uptime_s
        if limit is None or self._resident_started_at is None:
            return
        if time.monotonic() - self._resident_started_at >= limit:
            self._restart_and_recover(reason="uptime limit")

    # -- keeping the scene in sync ------------------------------------------

    def _sync(self, recipe: Recipe) -> None:
        """Bring the resident to a recipe.

        The order is the crash-safe one: **journal first, then apply**. If
        the resident dies between the two, the replay finds the ops in the
        journal and lands on the state the recipe describes — the request is
        lost, the history is not.
        """
        document = recipe.model_dump(mode="json")
        if self._resident_recipe is None:
            self._journal.record_replace(document)
            self._apply_to_resident(
                {"replace": True, "document": document, "ops": []}, document
            )
            self._resident_recipe = recipe
            self._last_sync_applied_ops = False
            self._after_sync(0)
            return

        ops = diff_recipes(self._resident_recipe, recipe)
        if not ops:
            self._last_sync_applied_ops = False  # the scene did not move
            self._after_sync(0)
            return
        wire_ops = [op.model_dump(mode="json") for op in ops]
        self._journal.record_ops(wire_ops)
        self._apply_to_resident(
            {"replace": False, "document": document, "ops": wire_ops}, document
        )
        self._resident_recipe = recipe
        self._last_sync_applied_ops = True
        self._after_sync(len(ops))

    def _apply_to_resident(self, params: dict, expected: dict) -> None:
        """Send one sync to the resident and check what came back.

        The resident answers with the digest of the document it arrived at.
        The core compares it with the digest of the document the core
        computed — two independent implementations of the op semantics, and
        a disagreement is a refusal, not a shrug.

        If the resident dies mid-sync, the ops are already in the journal, so
        the rebuild replays them onto the fresh resident: the sync is then
        *already done*, and the retry must not apply the ops a second time.
        """
        try:
            result = self._call_once("sync", params)
        except (ResidentCrashed, ResidentTimeout):
            self._restart_and_recover(reason="the resident died during a sync")
            result = self._call_once("sync", {"replace": False, "ops": []})
        except ResidentRefused as exc:
            # the core applied these ops and the resident would not: the two
            # implementations of the op grammar disagree, and that is a
            # failure to report, not an answer to pass up
            raise EngineFailed(
                f"the resident refused a sync the core computed "
                f"({exc.code}: {exc}); the two implementations of the op "
                "grammar have drifted apart",
                code=exc.code,
                detail=exc.detail,
            ) from exc
        reported = result.get("document_digest")
        wanted = content_hash(expected)
        if reported and reported != wanted:
            raise EngineFailed(
                f"the resident's recipe document ({reported}) does not match "
                f"the one the core computed ({wanted}); the two "
                "implementations of the op grammar have drifted apart",
                reported=reported,
                expected=wanted,
            )
        self._last_document_digest = reported

    def _resident_document(self) -> dict:
        return (
            self._resident_recipe.model_dump(mode="json")
            if self._resident_recipe is not None
            else {"entries": {}}
        )

    def _after_sync(self, ops: int) -> None:
        """The cadence and the guard: what happens after the scene moved."""
        self._ops_since_checkpoint += ops
        self._ops_since_growth_check += ops

        if self._ops_since_checkpoint >= self._policy.checkpoint_every_ops or (
            time.monotonic() - self._last_checkpoint_at
            >= self._policy.checkpoint_every_s
        ):
            self.checkpoint()

        if self._ops_since_growth_check >= self._policy.growth_check_every_ops:
            self._ops_since_growth_check = 0
            self._check_growth()

    def _check_growth(self) -> None:
        """The memory-growth guard.

        A resident accumulates orphan datablocks that a batch run never has
        to think about (WS §5.2: 209 meshes and 209 materials after 1000
        edits, for 12 objects). The bound is measured against the baseline
        taken **after the scene was loaded**, so a big scene is not mistaken
        for a leak.
        """
        if self._process is None:
            return
        rss = self._process.rss_mb()
        if rss is None:
            return
        if self._baseline_rss_mb is None:
            self._baseline_rss_mb = rss
            return
        growth = rss - self._baseline_rss_mb
        if growth > self._policy.max_growth_mb:
            self._guard_recycles += 1
            self._restart_and_recover(
                reason=(
                    f"the resident grew {growth:.1f} MiB above its baseline "
                    f"({self._baseline_rss_mb:.1f} → {rss:.1f} MiB), past the "
                    f"{self._policy.max_growth_mb:.0f} MiB bound"
                )
            )

    # -- recovery ------------------------------------------------------------

    def _restart_and_recover(self, *, reason: str) -> None:
        """Stop the resident, start a new one, and replay the recipe onto it.

        The restart is counted by :meth:`_start_resident`, so the budget is
        the same whether the resident was rebuilt on purpose or found dead.
        """
        if self._process is not None:
            self._process.stop()
            self._process = None
        self._baseline_rss_mb = None
        self._resident_started_at = None
        self._start_resident()

    def _recover_into(self, process: ResidentProcess) -> None:
        """Replay the durable recipe onto a fresh resident.

        The replay is the checkpoint's document plus the journal's tail. The
        core computes the document it expects with **its own** op applier and
        compares it with the one the resident arrived at — so "the recovery
        is exact" is a checked claim, not an assertion.
        """
        entries = self._journal.read_entries()
        if not entries:
            self._resident_recipe = None
            self._last_document_digest = None
            return

        checkpoint = self._journal.read_checkpoint()
        start = 0
        recipe: Recipe | None = None
        if checkpoint is not None:
            start = int(checkpoint.get("journal_entries", 0))
            document = checkpoint.get("document")
            if isinstance(document, dict) and document:
                recipe = Recipe.model_validate(document)

        replayed = 0
        for entry in entries[start:]:
            kind = entry.get("kind")
            if kind == "replace":
                document = entry.get("recipe")
                if not isinstance(document, dict):
                    raise EngineFailed(
                        "the journal's replace entry carries no document; the "
                        "replay cannot start",
                        entry=entry.get("seq"),
                    )
                recipe = Recipe.model_validate(document)
                process.call(
                    "sync", {"replace": True, "document": document, "ops": []},
                    timeout_s=self._policy.request_timeout_s,
                )
            elif kind == "ops":
                ops = entry.get("ops") or []
                if recipe is None:
                    raise EngineFailed(
                        "the journal holds ops but no base document; the "
                        "replay has nothing to apply them to",
                        entry=entry.get("seq"),
                    )
                recipe = apply_ops(recipe, [Op.model_validate(o) for o in ops])
                process.call(
                    "sync", {"replace": False, "ops": ops},
                    timeout_s=self._policy.request_timeout_s,
                )
            else:
                raise EngineFailed(
                    f"unknown journal entry kind {kind!r}; the journal is ours "
                    "and must be readable",
                    entry=entry.get("seq"),
                )
            replayed += 1

        self._resident_recipe = recipe
        expected = content_hash(
            recipe.model_dump(mode="json") if recipe is not None else {"entries": {}}
        )
        reported = process.call(
            "sync", {"replace": False, "ops": []},
            timeout_s=self._policy.request_timeout_s,
        ).get("document_digest")
        if reported and reported != expected:
            raise EngineFailed(
                f"the replayed scene's document ({reported}) does not match "
                f"the one the core replayed ({expected}); the recovery is not "
                "exact and the resident is not trusted",
                reported=reported,
                expected=expected,
            )
        self._last_document_digest = reported
        self._recoveries += 1
        self._ops_since_checkpoint = 0
        self._last_checkpoint_at = time.monotonic()
        self.checkpoint()

    # -- the RPC -------------------------------------------------------------

    def _call(self, method: str, params: dict) -> Any:
        """One call to the resident, with one honest retry.

        A refusal from the backend is the backend's answer and is passed
        straight up. A crash or a hang is not an answer: the resident is
        rebuilt, the recipe is replayed onto it, and the call is made again.
        """
        raw = self._call_raw(method, params)
        if method in ("stage", "preview", "export"):
            return base64.b64decode(raw.get("data", ""))
        return raw

    def _call_raw(self, method: str, params: dict) -> dict:
        """A call whose answer is data, not bytes — with the same one retry.

        A refusal crosses the seam as :class:`EngineFailed` carrying the
        backend's own words: the seam's other engines fail that way, and the
        caller should not have to know a resident exists to read one.
        """
        try:
            return self._call_once(method, params)
        except (ResidentCrashed, ResidentTimeout):
            self._restart_and_recover(reason=f"the resident died during {method}")
        except ResidentRefused as exc:
            raise EngineFailed(
                f"the resident refused {method} ({exc.code}: {exc})",
                code=exc.code,
                detail=exc.detail,
            ) from exc
        try:
            return self._call_once(method, params)
        except ResidentRefused as exc:
            raise EngineFailed(
                f"the resident refused {method} ({exc.code}: {exc})",
                code=exc.code,
                detail=exc.detail,
            ) from exc

    def _call_once(self, method: str, params: dict) -> dict:
        if self._process is None:
            raise ResidentCrashed("there is no resident")
        return self._process.call(
            method, params, timeout_s=self._policy.request_timeout_s
        )

    # -- helpers -------------------------------------------------------------

    def _mechanism(self) -> str:
        """How the stage's result was produced.

        ``graph-edit`` when the resident's scene was moved in place by typed
        ops, ``full-reeval`` when the scene was already where it needed to
        be and the stage was simply evaluated against it. The label
        describes how the *scene* reached the requested state; the stage's
        own bytes are always evaluated afresh.
        """
        return "graph-edit" if self._last_sync_applied_ops else "full-reeval"

    def _refuse_foreign_base(self, base: StageResult) -> None:
        """Rule 5: each engine re-executes only its own lower layer."""
        try:
            document = json.loads(base.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(document, dict):
            return
        label = document.get("engine")
        if label is not None and label != self._engine_label:
            raise ValueError(
                f"reexecute got a base stage this engine did not produce "
                f"(engine {label!r}, this resident is {self._engine_label!r}); "
                "each engine re-executes only its own lower layer"
            )

    def _elapsed(self, started: float, op: str) -> float:
        """The builder wait: the time from the request to the result."""
        ms = (time.monotonic() - started) * 1000.0
        self.requests.append({"op": op, "ms": ms})
        self._resident_served = True
        return ms
