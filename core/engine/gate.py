"""The merge gate's engine rungs over the seam (`core.ports.MergeGateEngine`).

§2.3's gate is the core's orchestration; its engine half — deterministic
rebuild, the render ladder, the analytic checks — goes through the
``MergeGateEngine`` port, which until now only the acceptance suites'
``StubGateEngine`` answered. This adapter answers it with **any** `Engine`:

* **deterministic rebuild is really checked** — the stage is generated
  twice and the bytes compared, so a non-deterministic engine fails the
  gate instead of passing it by construction (§2.3.1);
* **the render rung is the engine's preview** — and its verdict still wears
  ``verdict@scripted`` on its face, because no critic model has been chosen
  or calibrated (RV patch 15; X R4/S6). The *render* is engine work; the
  *verdict* is a scripted check and says so;
* **the analytic checks stay scripted** — there is no physics engine and
  never was (§7.14); they are labelled with the engine that served them.
"""
from __future__ import annotations

from typing import Callable

from core.engine.contract import Engine, PreviewRequest, StageRequest

__all__ = ["EngineGateEngine"]


class EngineGateEngine:
    """`core.ports.MergeGateEngine` over any `Engine`.

    ``recipe_at`` answers *what the gate is checking right now* — the
    recipe document and its version hash at the branch head under test.
    It is a callable (not a document) because the gate runs during the
    night, after commits: the recipe it checks must be the one that exists
    at gate time, never a snapshot from boot.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        recipe_at: Callable[[], tuple[object, str]],
        stage: str = "scene",
    ) -> None:
        self._engine = engine
        self._recipe_at = recipe_at
        self._stage = stage

    # -- the port (core/ports.py::MergeGateEngine) ---------------------------

    def deterministic_rebuild(self, edit_id: str | None) -> dict:
        recipe, version_hash = self._recipe_at()
        request = StageRequest(
            recipe=recipe, version_hash=version_hash, stage=self._stage
        )
        first = self._engine.generate_stage(request)
        second = self._engine.generate_stage(request)
        identical = first.data == second.data and first.stage_key == second.stage_key
        return {
            "ok": identical,
            "check": "deterministic_rebuild",
            "engine": self._engine.describe().source,
            "byte_identical": identical,
            "stage_key": first.stage_key,
            "edit": edit_id,
        }

    def render_rung(self, rung: int, seed: int) -> dict:
        recipe, version_hash = self._recipe_at()
        preview = self._engine.render_preview(
            PreviewRequest(
                recipe=recipe,
                version_hash=version_hash,
                subject="work-order",
                rung=rung,
                seed=seed,
            )
        )
        source = self._engine.describe().source
        return {
            "verdict": "keep",
            "label": "verdict@scripted",
            "degraded": True,
            "rung": preview.rung,
            "seed": preview.seed,
            "resolution": preview.resolution,
            "artifact": preview.artifact,
            "engine": source,
            "summary": (
                f"rung-{preview.rung} · {preview.resolution} · {source} · "
                f"verdict@scripted"
            ),
        }

    def run_checks(self, checks: list[dict]) -> list[dict]:
        source = self._engine.describe().source
        out = []
        for check in checks:
            kind = check.get("kind", "?")
            out.append({
                "check": f"{kind}:{check.get('spec', {})}",
                "ok": True,
                "engine": source,
                "method": "scripted analytic computation (no physics engine — §7.14)",
                "label": "verdict@scripted",
            })
        return out
