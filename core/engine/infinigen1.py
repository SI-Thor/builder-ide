"""The Infinigen 1.x adapter — a subprocess per stage, as the spike runs it.

v1's shape is the batch architecture (E §1): a Python process per task, gin
configs, state handed between tasks as ``scene.blend``. This adapter does
not fight that — it *is* that, wrapped in the seam:

* the **pinned config bundle is verified at construction**: the adapter
  hashes the config files the pin names and refuses to start if they hash
  to anything else, because the stage-cache key would otherwise lie (RV
  patch 13 — config drift defeating §5.3 is the one failure the pin exists
  to prevent);
* the **recipe crosses as data, never as code** (§2.2's rule): the canonical
  document is written beside the outputs, and the subprocess is asked to run
  a *stage* of it;
* the **stage output is content-addressed** at ``stages/<key2>/<key>`` by
  the canonical stage key, so a re-run that produces identical bytes is a
  no-op on disk and a cache hit for the caller;
* **one engine-side counterpart is named, not assumed**: the subprocess runs
  ``python -m infinigen_thor.stage_runner`` — our fork's stage runner (the
  repo the pin names). The runner is the engine repo's half of the seam; it
  does not exist yet, and this adapter refuses loudly rather than guessing
  an upstream entrypoint's flags.

The subprocess boundary is one injectable callable (:class:`CommandRunner`)
so the contract tests drive the adapter's argv without a checkout.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Protocol, Sequence

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
from core.engine.errors import EngineFailed, EngineUnavailable
from core.records import EnginePin

__all__ = [
    "CommandResult",
    "CommandRunner",
    "Infinigen1xEngine",
    "RUNG_LADDER",
    "STAGE_TASKS",
    "config_bundle_hash",
    "subprocess_runner",
]

#: The v1 pipeline's stages, as the spike ran them (SP §3–4), and the task
#: name our fork's stage runner gives each. An unknown stage is refused with
#: this table's keys, never guessed.
STAGE_TASKS: dict[str, str] = {
    "coarse": "coarse",
    "populate": "populate",
    "fine_terrain": "fine_terrain",
    "scene": "scene",
}

#: The preview ladder (P §2.1: "16-spp 480p is a config knob"): rung →
#: (resolution, samples). The sealed ``render_spec`` names the rung; the
#: adapter resolves it here so the same rung is always the same ask.
RUNG_LADDER: dict[int, tuple[str, int]] = {
    1: ("180p", 4),
    2: ("480p", 16),
    3: ("720p", 64),
    4: ("1080p", 256),
}

#: Our fork's stage runner — the engine repo's half of this seam.
_STAGE_RUNNER_MODULE = "infinigen_thor.stage_runner"


class CommandResult(BaseModel):
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """One subprocess boundary, injectable so tests drive argv, not Blender."""

    def run(self, argv: Sequence[str], *, cwd: Path | None = None) -> CommandResult: ...


def subprocess_runner(argv: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
    """The real runner: v1 is a subprocess engine, so this is the seam's
    actual workhorse (capture, no shell, the venv's own python as argv[0])."""
    proc = subprocess.run(
        list(argv), cwd=None if cwd is None else str(cwd),
        capture_output=True, text=True, check=False,
    )
    return CommandResult(
        argv=list(argv), returncode=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def config_bundle_hash(config_files: Sequence[Path | str]) -> str:
    """The pinned config bundle's hash: canonical JSON of ``{name → content
    hash}`` over the files, in the order the pin listed them."""
    files = [Path(f) for f in config_files]
    return content_hash([
        {"name": f.name, "sha256": bytes_hash(f.read_bytes())} for f in files
    ])


class Infinigen1xEngine:
    """v1 behind the seam: one pinned checkout, one subprocess per stage."""

    def __init__(
        self,
        *,
        pin: EnginePin,
        repo: Path | str,
        python: Path | str,
        config_files: Sequence[Path | str],
        output_dir: Path | str,
        runner: CommandRunner = subprocess_runner,
    ) -> None:
        self._pin = pin
        self._repo = Path(repo)
        self._python = Path(python)
        self._config_files = [Path(f) for f in config_files]
        self._output_dir = Path(output_dir)
        self._runner = runner
        self.calls: list[CommandResult] = []
        # The one construction-time check that guards the cache: the local
        # checkout must *be* the pinned engine, config included.
        for f in self._config_files:
            if not f.is_file():
                raise EngineUnavailable(
                    f"the pinned config file {f} does not exist; the engine "
                    f"checkout at {self._repo} is not the pinned engine",
                    missing=str(f),
                )
        got = config_bundle_hash(self._config_files)
        if got != pin.config:
            raise EngineUnavailable(
                f"the config bundle at {self._repo} hashes to {got} but the "
                f"pin says {pin.config}; refusing because the stage-cache "
                "key would not be a function of the engine that built the "
                "stage (RV patch 13)",
                computed=got, pin=pin.config,
            )

    # -- the seam ------------------------------------------------------------

    def describe(self) -> EngineDescriptor:
        return EngineDescriptor(
            flavour="infinigen-1x",
            pin=self._pin,
            capabilities=EngineCapabilities(
                stages=True,
                previews=True,
                export_formats=["fbx", "obj", "usdc", "usda", "stl", "ply"],
                reexecute="full-reeval",
            ),
            source=(
                f"infinigen 1.x · {self._pin.repo}@{self._pin.commit} · "
                f"subprocess ({self._python}) · config {self._pin.config}"
            ),
        )

    def generate_stage(self, request: StageRequest) -> StageResult:
        check_pin(self.describe(), request.recipe)
        task = self._task_for(request.stage)
        out = self._stage_path(request)
        recipe_path = self._write_recipe(request)
        self._run_stage(task, request, recipe_path, out)
        data = self._read(out)
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage",
                      "bytes": len(data)},
            mechanism="full-reeval",
        )

    def reexecute(self, request: ReexecuteRequest) -> StageResult:
        """v1 has no graph to edit: the honest mechanism is a full
        re-evaluation of the dirty stage from the post-diff recipe (E §3's
        table — v1's only cheaper path, ``resample_scene``, re-noises
        materials in place and is not a general diff mechanism). The
        per-entry stage keys are what make that cheap: untouched entries
        keep their keys, so the caller's cache absorbs them."""
        check_pin(self.describe(), request.recipe)
        task = self._task_for(request.stage)
        out = self._stage_path(request)
        recipe_path = self._write_recipe(request)
        self._run_stage(task, request, recipe_path, out, base=request.base)
        data = self._read(out)
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage",
                      "bytes": len(data)},
            mechanism="full-reeval",
        )

    def render_preview(self, request: PreviewRequest) -> PreviewResult:
        check_pin(self.describe(), request.recipe)
        if request.rung not in RUNG_LADDER:
            ladder = {r: RUNG_LADDER[r] for r in sorted(RUNG_LADDER)}
            raise ValueError(
                f"unknown rung {request.rung}; the ladder is {ladder}"
            )
        resolution, samples = RUNG_LADDER[request.rung]
        out = self._output_dir / "previews" / f"r{request.rung}-{request.seed}.png"
        argv = self._base_argv("render") + [
            "--resolution", resolution,
            "--samples", str(samples),
            "--seed", str(request.seed),
            "--subject", request.subject,
            "--output", str(out),
        ]
        started = time.monotonic()
        self._run(argv)
        data = self._read(out)
        return PreviewResult(
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "render",
                      "bytes": len(data)},
            rung=request.rung,
            seed=request.seed,
            resolution=resolution,
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    def export(self, request: ExportRequest) -> ExportResult:
        """v1 keeps ``tools/export.py`` (E §1: fbx, obj, usdc, usda, stl,
        ply) — the one export surface this fork does not have to write."""
        check_pin(self.describe(), request.recipe)
        formats = self.describe().capabilities.export_formats
        if request.format not in formats:
            raise ValueError(
                f"infinigen 1.x exports {formats}, not {request.format!r}"
            )
        out = (self._output_dir / "exports"
               / f"{request.version_hash[:14]}.{request.format}")
        argv = [
            str(self._python), "-m", "infinigen.tools.export",
            "--formats", request.format,
            "--input", str(self._scene_blend(request)),
            "--output", str(out),
        ]
        started = time.monotonic()
        self._run(argv)
        data = self._read(out)
        return ExportResult(
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": f"export:{request.format}",
                      "bytes": len(data)},
            format=request.format,
            profile=request.profile,
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    # -- the subprocess contract ----------------------------------------------

    def _base_argv(self, task: str) -> list[str]:
        self._must_exist()
        return [
            str(self._python), "-m", _STAGE_RUNNER_MODULE,
            "--task", task,
            "-g", *[str(f) for f in self._config_files],
        ]

    def _run_stage(
        self,
        task: str,
        request: StageRequest | ReexecuteRequest,
        recipe_path: Path,
        out: Path,
        *,
        base: StageResult | None = None,
    ) -> None:
        argv = self._base_argv(task) + [
            "--recipe", str(recipe_path),
            "--stage", request.stage,
            "--version-hash", request.version_hash,
            "--output", str(out),
        ]
        if base is not None:
            argv += ["--base-stage", base.stage_key]
        self._run(argv)

    def _write_recipe(self, request: StageRequest | ReexecuteRequest) -> Path:
        """The recipe crosses as data (§2.2): canonical JSON beside the
        outputs, content-addressed by the version hash."""
        path = (self._output_dir / "recipes"
                / f"{request.version_hash.removeprefix('sha256:')}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        body = canonical_bytes(request.recipe.model_dump(mode="json"))
        if not path.exists() or path.read_bytes() != body:
            path.write_bytes(body)
        return path

    def _stage_path(self, request: StageRequest | ReexecuteRequest) -> Path:
        key = expected_stage_key(request, self.describe())
        hexpart = key.removeprefix("sha256:")
        return self._output_dir / hexpart[:2] / hexpart

    def _scene_blend(self, request: ExportRequest) -> Path:
        """The export's input: the scene stage's output at this version (the
        stage the runner was asked for; its key is the cache key)."""
        scene = StageRequest(
            recipe=request.recipe, version_hash=request.version_hash,
            stage="scene",
        )
        return self._stage_path(scene)

    def _task_for(self, stage: str) -> str:
        if stage not in STAGE_TASKS:
            raise ValueError(
                f"unknown stage {stage!r}; the v1 stages are "
                f"{sorted(STAGE_TASKS)}"
            )
        return STAGE_TASKS[stage]

    def _must_exist(self) -> None:
        if not self._repo.is_dir():
            raise EngineUnavailable(
                f"the pinned engine checkout {self._repo} does not exist on "
                "this box; the adapter is complete but the engine is not "
                "present",
                missing=str(self._repo),
            )
        if not self._python.exists():
            raise EngineUnavailable(
                f"the pinned engine interpreter {self._python} does not exist; "
                "v1 needs its own venv (bpy 4.2 / Python 3.11, SP §1)",
                missing=str(self._python),
            )

    def _run(self, argv: list[str]) -> CommandResult:
        result = self._runner.run(argv, cwd=self._repo)
        self.calls.append(result)
        if result.returncode != 0:
            raise EngineFailed(
                f"the engine exited {result.returncode}: "
                f"{result.stderr.strip()[-400:] or result.stdout.strip()[-400:]}",
                argv=result.argv,
                returncode=result.returncode,
            )
        return result

    def _read(self, path: Path) -> bytes:
        if not path.is_file():
            raise EngineFailed(
                f"the engine reported success but wrote no stage output at "
                f"{path}; the stage runner's output contract is the missing "
                "piece (engine repo)",
                missing=str(path),
            )
        return path.read_bytes()
