"""The fake engine — the seam's test double, and the acceptance suites' engine.

It keeps exactly the properties every consumer depends on, and none of the
ones it cannot honestly have:

* **deterministic in the whole request plus the pin** — same request, same
  bytes (the stage-hit invariant, §1.9; job dedup, §5.3). The pin is in the
  bytes' input, so re-pinning a project changes the outputs honestly.
* **per-entry digests** — a stage's data is a canonical document of one
  digest per entry, so a diff that touches one entry changes exactly that
  entry's line: the dirty-set contract (§1.1) is *demonstrable* against the
  fake, not just asserted around it.
* **labelled bytes** — every artifact says `fake-engine` inside itself,
  the way the stub generator's bytes did: a fake that could pass for a
  render is a fabrication (D §2 02:07).
* **no invented measurements** — ``wall_ms`` stays ``None``; the fake
  measures nothing and says so by omitting it.
"""
from __future__ import annotations

from pydantic import BaseModel

from core.canon import bytes_hash, canonical_bytes, content_hash
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
from core.records import EnginePin, Recipe, RecipeEntry

__all__ = ["FakeEngine", "FAKE_PIN"]

#: The default pin — a name no real checkout can be confused with.
FAKE_PIN = EnginePin(
    repo="builder-ide/fake-engine",
    commit="f4ke0000",
    config="sha256:" + "0" * 64,
    blender="none",
    python="none",
)


class _Call(BaseModel):
    """One recorded call, for tests that assert what crossed the seam."""

    op: str
    stage: str | None = None
    subject: str | None = None
    rung: int | None = None
    seed: int | None = None
    version_hash: str | None = None
    format: str | None = None


class FakeEngine:
    """The whole contract, deterministically, with no engine behind it."""

    def __init__(self, pin: EnginePin | None = None) -> None:
        self._pin = pin or FAKE_PIN
        #: every call, in order — the seam's own record for tests
        self.calls: list[_Call] = []

    # -- the seam ------------------------------------------------------------

    def describe(self) -> EngineDescriptor:
        return EngineDescriptor(
            flavour="fake",
            pin=self._pin,
            capabilities=EngineCapabilities(
                stages=True,
                previews=True,
                export_formats=["usda", "glb"],
                reexecute="fake",
            ),
            source=f"fake-engine · {self._pin.repo}@{self._pin.commit} "
            f"(config {self._pin.config})",
        )

    def generate_stage(self, request: StageRequest) -> StageResult:
        self._check(request.recipe, "generate_stage", request.version_hash,
                    stage=request.stage)
        data = self._stage_data(request.recipe, request.stage, request.dep_keys)
        return self._stage_result(request, data, mechanism="fake")

    def reexecute(self, request: ReexecuteRequest) -> StageResult:
        self._check(request.recipe, "reexecute", request.version_hash,
                    stage=request.stage)
        # The base must be this fake's own work: re-executing another
        # flavour's stage bytes is not ours to interpret (rule 5).
        if self._engine_of(request.base.data) != "fake-engine":
            raise ValueError(
                "reexecute got a base stage this engine did not produce "
                f"(mechanism {request.base.mechanism!r}); each engine "
                "re-executes only its own lower layer"
            )
        data = self._stage_data(request.recipe, request.stage, request.dep_keys)
        return self._stage_result(request, data, mechanism="fake")

    def render_preview(self, request: PreviewRequest) -> PreviewResult:
        self._check(request.recipe, "render_preview", request.version_hash,
                    subject=request.subject, rung=request.rung, seed=request.seed)
        body = (
            f"fake-engine preview · {request.subject} · rung {request.rung} · "
            f"{request.resolution} · seed {request.seed} · "
            f"recipe {request.version_hash} · pin {self._pin.commit}"
        ).encode("utf-8")
        data = f"{body} · sha:{bytes_hash(body).removeprefix('sha256:')[:16]}".encode()
        return PreviewResult(
            data=data,
            artifact=self._artifact(data, "render"),
            rung=request.rung,
            seed=request.seed,
            resolution=request.resolution,
        )

    def export(self, request: ExportRequest) -> ExportResult:
        self._check(request.recipe, "export", request.version_hash,
                    format=request.format)
        data = (
            f"fake-engine export · {request.format} · {request.profile} · "
            f"recipe {request.version_hash} · pin {self._pin.commit}"
        ).encode("utf-8")
        return ExportResult(
            data=data,
            artifact=self._artifact(data, f"export:{request.format}"),
            format=request.format,
            profile=request.profile,
        )

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _engine_of(data: bytes) -> str | None:
        """Which engine's lower layer these stage bytes are (rule 5)."""
        import json

        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return doc.get("engine") if isinstance(doc, dict) else None

    def _check(self, recipe: Recipe, op: str, version_hash: str, **fields) -> None:
        check_pin(self.describe(), recipe)
        self.calls.append(_Call(op=op, version_hash=version_hash, **fields))

    def _stage_data(
        self, recipe: Recipe, stage: str, dep_keys: list[str]
    ) -> bytes:
        """One digest per entry — the dirty set made visible in the bytes."""
        doc = {
            "engine": "fake-engine",
            "pin": self._pin.model_dump(mode="json"),
            "stage": stage,
            "seeds": dict(sorted(recipe.seeds.items())),
            "dep_keys": sorted(dep_keys),
            "entries": {
                path: content_hash(entry.model_dump(mode="json"))
                for path, entry in sorted(recipe.entries.items())
            },
        }
        return canonical_bytes(doc)

    def _stage_result(
        self,
        request: StageRequest | ReexecuteRequest,
        data: bytes,
        *,
        mechanism: str,
    ) -> StageResult:
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact=self._artifact(data, "stage"),
            mechanism=mechanism,
        )

    def _artifact(self, data: bytes, kind: str) -> dict:
        return {"sha256": bytes_hash(data), "kind": kind, "bytes": len(data)}


def entry_digest(entry: RecipeEntry) -> str:
    """The per-entry content digest the fake's stage data carries — a test
    helper so the dirty-set assertions read the same bytes the seam does."""
    return content_hash(entry.model_dump(mode="json"))
