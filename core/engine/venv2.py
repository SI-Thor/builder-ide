"""The v2 engine through its own venv's CLI — the subprocess path that runs today.

The decision's engine is Infinigen 2.0 + procfunc (E §3, option C), and the
confirming experiment proved it renders on the Thor
(``docs/research/v2-thor-experiment.md``): a venv at Python 3.11 with
``bpy==4.2.0``, ``infinigen 2.0.0a3`` and ``procfunc 0.37.0`` runs the whole
pipeline — generation, modifier bake, a Cycles **CUDA** render — end to end.
That venv cannot import into this core (procfunc pins Python ``==3.11.*``;
this core is 3.12 — E §2), so the boundary is the venv's own CLI, driven as a
subprocess. The venv is used **read-only**: nothing in it is written or
reinstalled by this runtime.

What this runtime implements of :class:`~core.engine.infinigen2.ProcfuncRuntime`:

* ``trace`` — the CLI's ``--trace graph`` at ``RANDOM_CONTROL`` (the level at
  which ``choice`` nodes exist at all; the experiment §3.2), one chain per
  entry, **normalized** so the same request yields the same bytes (rule 3).
  The experiment §3.3 found exactly two run-to-run wobbles in the traced
  graph — a ``repr()`` pointer leak and the ``generator_times`` wall-clock
  constant — and :func:`normalize_graph` removes precisely those two; with
  them gone, two same-seed traces are byte-identical (verified on
  ``plant_pot_small_rand``, ``desk_rand`` and ``storage_cell_shelf_rand``).
* ``render`` — the CLI's render task (``render_cycles``, Cycles on the GPU)
  for the **subject** entry's generator chain, at the ladder's
  resolution/samples. The bytes are a real PNG, and byte-reproducibility is
  **not promised**: Cycles' GPU accumulation order can move 1–3 pixels by
  ±1 LSB between identical requests (experiment §5.4 measured this on a
  room scene; the first live run's object renders happened to come out
  byte-identical — luck, not a contract). Rule 3's byte-promise holds for
  **stages** (the normalized graph above); a preview's artifact hash is a
  plain content hash of that render. An exit-0 run that leaves no PNG
  behind is a **loud failure carrying the CLI's own last words** — the
  night-v3 run C lesson: an engine that silently does nothing must be
  diagnosable from its failure alone. The exporter chain is the v2 CLI's
  supported render path (the sweep's ``generate_nature --task render`` is
  the *nature pipeline's* equivalent, another repo and another venv, and
  cannot take a v2 generator chain — the seam stays here).

The three ops it refuses, each naming its missing piece: ``replace`` /
``execute`` (single-node re-execution needs the call-site instrumentation the
experiment built engine-side in its ``choice_tool.py``; upstream ships no CLI
for it) and ``export`` (v2 ships no exporter; E §1).

The **pin is interrogated, not asserted**: the venv is asked for its
resolved package set (infinigen, procfunc, bpy — versions *and* licence
expressions) and the clone's commit; the pin's ``config`` hash is over that
report, so a venv that changed under the seam is a different engine and every
stage key changes with it (RV patch 13's rule, the v2 way: there are no gin
bundles to hash — the resolved packages *are* the config).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import BaseModel

from core.canon import content_hash
from core.engine.errors import EngineFailed, EngineUnavailable
from core.engine.infinigen1 import CommandResult, CommandRunner, SubprocessRunner
from core.records import EnginePin

__all__ = [
    "RESOLUTION_DIMENSIONS",
    "PackageReport",
    "REPORT_CODE",
    "Venv2Runtime",
    "normalize_graph",
    "render_dimensions",
]

#: Resolution names (the ladder's, ``RUNG_LADDER``) → the CLI's ``-r W H``.
#: 16:9 throughout, and each width×18/height integral — the CLI's framing
#: code asserts the sensor width is a whole number (854×480, the nominal
#: "480p", fails it; 960×540 is the same ladder rung and passes).
RESOLUTION_DIMENSIONS: dict[str, tuple[int, int]] = {
    "180p": (320, 180),
    "480p": (960, 540),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}

#: The one-liner the venv runs to report what it is. Read-only
#: interrogation: versions, licence expressions, interpreter — no writes.
REPORT_CODE = (
    "import json, sys, importlib.metadata as md\n"
    "pkgs = {}\n"
    "for name in ('infinigen', 'procfunc', 'bpy'):\n"
    "    try:\n"
    "        d = md.distribution(name)\n"
    "        pkgs[name] = {'version': d.version,\n"
    "                      'licence': d.metadata.get('License-Expression')\n"
    "                                  or d.metadata.get('License') or 'unknown'}\n"
    "    except md.PackageNotFoundError:\n"
    "        pkgs[name] = None\n"
    "print(json.dumps({'python': '%d.%d.%d' % sys.version_info[:3],\n"
    "                  'packages': pkgs}))\n"
)

_ADDR_IN_REPR = re.compile(r" at 0x[0-9a-fA-F]+>")


class PackageReport(BaseModel):
    """What the venv said it is — the pin's raw material."""

    python: str
    packages: dict[str, dict | None]
    commit: str


def normalize_graph(graph: dict) -> dict:
    """Remove exactly the two run-to-run wobbles the tracer leaves in
    ``graph.json`` (experiment §3.3), so a same-seed trace is byte-stable:

    1. the ``generator_times`` constants — wall-clock measurements the
       pipeline returns; every node referenced from
       ``outputs.generator_times`` becomes the placeholder
       ``"<generator_times>"`` (no wall-clock may reach the bytes, rule 3);
    2. pointer addresses inside ``$repr`` fallback strings —
       ``"<function f at 0xffff…>"`` becomes ``"<function f at 0xADDR>"``.

    Nothing else is touched: node ids, order, choices and parameters pass
    through as the engine wrote them.
    """
    timing_refs: set[str] = set()

    def collect_refs(node: object) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                timing_refs.add(node["$ref"])
            else:
                for value in node.values():
                    collect_refs(value)

    collect_refs(graph.get("outputs", {}).get("generator_times", {}))

    def strip(value: object) -> object:
        if isinstance(value, str):
            return _ADDR_IN_REPR.sub(" at 0xADDR>", value)
        if isinstance(value, list):
            return [strip(item) for item in value]
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items()}
        return value

    doc = strip(graph)
    for node in doc.get("nodes", []):
        if node.get("id") in timing_refs and node.get("type") == "Constant":
            node["value"] = "<generator_times>"
    return doc


def render_dimensions(resolution: str) -> tuple[int, int]:
    """The ladder's resolution name → the CLI's ``(width, height)``."""
    try:
        return RESOLUTION_DIMENSIONS[resolution]
    except KeyError:
        raise ValueError(
            f"unknown resolution {resolution!r}; the ladder's names are "
            f"{sorted(RESOLUTION_DIMENSIONS)}"
        ) from None


class Venv2Runtime:
    """The v2 engine, driven through its own venv's ``infinigen`` CLI.

    Configuration (the SPEC — this is the box's line, not code):

    * ``python`` — the venv's interpreter (must exist; v1-style refusal);
    * ``generators`` — the name resolution: our generator ``func`` name →
      the CLI's generator chain (e.g. ``"crates" → "storage_cell_shelf_rand"``,
      or a chained ``"weathering" → "wood_scratched_rand material_cube"``).
      Rule 1: a generator reference is a *name the adapter resolves*; an
      unresolved name is refused, never guessed;
    * ``output_dir`` — scratch for the CLI's own outputs, wiped per request;
      held **absolute**, because the subprocess's cwd is the clone and a
      relative scratch would be resolved twice, in two places;
    * ``repo`` / ``repo_name`` — the clone the venv's infinigen came from
      (the pin's commit; without a clone the dist version names it) and the
      pin's repo name;
    * ``runner`` — the injectable subprocess boundary (tests).
    """

    #: How :meth:`core.engine.infinigen2.Infinigen2Engine.describe` names
    #: this boundary.
    boundary = "venv-subprocess"

    def __init__(
        self,
        *,
        python: Path | str,
        generators: Mapping[str, str],
        output_dir: Path | str,
        repo: Path | str | None = None,
        repo_name: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._python = Path(python)
        self._cli = self._python.parent / "infinigen"
        self._repo = Path(repo) if repo is not None else None
        self._repo_name = repo_name
        self._generators = dict(generators)
        # Absolute, before any child sees it: the CLI runs with the clone as
        # its cwd, so a relative scratch is resolved twice — the render lands
        # where the seam never looks, and a healthy render is mourned as a
        # silent no-op (the run C lesson: its "missing" PNG sat in the clone
        # all along).
        self._output_dir = Path(output_dir).resolve()
        self._runner = runner if runner is not None else SubprocessRunner()
        self._report: PackageReport | None = None
        if not self._python.is_file():
            raise EngineUnavailable(
                f"the v2 venv interpreter {self._python} does not exist; the "
                "venv is the engine (bpy 4.2 / Python 3.11 — E §2), so "
                "without it there is no engine to drive",
                missing=str(self._python),
            )
        if not self._cli.is_file():
            raise EngineUnavailable(
                f"the v2 CLI {self._cli} does not exist next to the venv's "
                "python; the adapter drives the engine through it",
                missing=str(self._cli),
            )

    @property
    def resolutions(self) -> dict[str, str]:
        """The configured name resolution, for provenance rows and labels."""
        return dict(self._generators)

    # -- the pin ------------------------------------------------------------

    def report(self) -> PackageReport:
        """Interrogate the venv once: packages, licences, interpreter."""
        if self._report is None:
            result = self._runner.run([str(self._python), "-c", REPORT_CODE])
            if result.returncode != 0:
                raise EngineFailed(
                    "the v2 venv could not report its packages: "
                    f"{result.stderr.strip()[-300:] or result.stdout.strip()[-300:]}",
                    argv=result.argv, returncode=result.returncode,
                )
            try:
                raw = json.loads(result.stdout.strip().splitlines()[-1])
                packages = raw["packages"]
            except (ValueError, KeyError, IndexError) as e:
                raise EngineFailed(
                    f"the v2 venv's report is not the expected JSON: {e!r}",
                    argv=result.argv, returncode=result.returncode,
                ) from e
            missing = sorted(
                name for name, info in packages.items() if info is None)
            if missing:
                raise EngineUnavailable(
                    f"the venv at {self._python} is not the v2 engine: "
                    f"{', '.join(missing)} not installed",
                    missing=", ".join(missing),
                )
            self._report = PackageReport(
                python=raw["python"], packages=packages,
                commit=self._commit_of(raw),
            )
        return self._report

    def _commit_of(self, raw: dict) -> str:
        """The engine's commit: the clone's HEAD, or the dist version when
        no clone is configured (an honest name, never a guess)."""
        if self._repo is None:
            version = (raw["packages"].get("infinigen") or {}).get("version")
            return f"pypi:{version}"
        result = self._runner.run(
            ["git", "-C", str(self._repo), "rev-parse", "HEAD"])
        if result.returncode != 0 or not result.stdout.strip():
            raise EngineUnavailable(
                f"the pinned engine clone {self._repo} did not answer "
                "`git rev-parse HEAD`; the commit is load-bearing in the pin",
                missing=str(self._repo),
            )
        return result.stdout.strip()

    def engine_pin(self, pinned: EnginePin | None = None) -> EnginePin:
        """The pin this venv *is*: repo name, commit, and the config hash
        over the resolved package set. A ``pinned`` pin (from the SPEC) is
        verified against the computed one — drift is a refusal, because the
        stage-cache key would otherwise be a function of the wrong engine
        (RV patch 13, the v2 way)."""
        report = self.report()
        bpy_version = (report.packages.get("bpy") or {}).get("version", "")
        pin = EnginePin(
            repo=self._repo_name or "princeton-vl/infinigen",
            commit=report.commit,
            config=content_hash({
                "infinigen": report.packages.get("infinigen"),
                "procfunc": report.packages.get("procfunc"),
                "bpy": report.packages.get("bpy"),
                "python": report.python,
            }),
            blender=f"bpy {bpy_version}".strip(),
            python=report.python,
        )
        if pinned is not None and pinned != pin:
            raise EngineUnavailable(
                f"the SPEC pins {pinned.repo}@{pinned.commit} (config "
                f"{pinned.config}) but the venv at {self._python} is "
                f"{pin.repo}@{pin.commit} (config {pin.config}); refusing "
                "because the stage-cache key would not be a function of the "
                "engine that builds the stage (RV patch 13)",
                computed=pin.model_dump(mode="json"),
                pin=pinned.model_dump(mode="json"),
            )
        return pin

    # -- the licence row (the venv knows its own terms) ----------------------

    def licence_row(self) -> dict:
        """The complete licence row for a render this engine produced, from
        the venv's own metadata (§1.6: no asset without the row, dependency
        terms included)."""
        report = self.report()
        terms = []
        for name in ("infinigen", "procfunc"):
            info = report.packages.get(name) or {}
            terms.append(f"{name} {info.get('version', '?')}: "
                         f"{info.get('licence', 'unknown')}")
        bpy_info = report.packages.get("bpy") or {}
        terms.append(
            f"bpy {bpy_info.get('version', '?')} (Blender): "
            f"{bpy_info.get('licence', 'unknown')} — covers the program, "
            "not the images it renders"
        )
        infinigen_licence = (report.packages.get("infinigen") or {}).get(
            "licence", "")
        return {
            "spdx": infinigen_licence or "BSD-3-Clause",
            "dependency_terms": terms,
            "commercial_ok": True,
            "checked_by": "core-licence-registry (venv metadata)",
        }

    # -- name resolution (rule 1) ---------------------------------------------

    def chain_for(self, func: str) -> list[str]:
        """One generator name → the CLI's chain of generator words."""
        try:
            chain = self._generators[func]
        except KeyError:
            raise EngineUnavailable(
                f"generator {func!r} has no resolution in this engine's "
                "configuration; a generator reference is a name the adapter "
                "resolves — add it to the SPEC's `generators` rather than "
                "guessing one",
                missing=func,
            ) from None
        return chain.split()

    def chain_for_subject(self, calls, subject: str) -> list[str]:
        """The chain a render subject resolves to — the same resolution
        :meth:`render` uses, for provenance rows: the exact entry path if
        the subject names one, else the first entry in the recipe's order."""
        return self.chain_for(self._subject_call(calls, subject).name)

    # -- the procfunc operations (the two that cross the CLI) ------------------

    def trace(self, calls, seeds) -> dict:
        """Each entry's generator chain, traced at RANDOM_CONTROL and
        normalized — the stage's lower layer."""
        entries: dict[str, dict] = {}
        for call in calls:
            chain = self.chain_for(call.name)
            seed = call.seed if call.seed is not None else int(
                seeds.get(call.entry_path.split(".")[0], 0))
            out = self._scratch("trace", call.entry_path, seed)
            result = self._run([
                *chain, "--seed", str(seed),
                "--trace", "graph", "--trace_level", "RANDOM_CONTROL",
                "--output", str(out),
            ])
            graph_file = out / "graph.json"
            if not graph_file.is_file():
                last = self._last_words(result)
                raise EngineFailed(
                    f"the engine exited 0 but wrote no graph.json under {out} "
                    f"— a silent no-op trace is refused loudly; the CLI's "
                    f"last words: {last or '(none)'}",
                    missing=str(graph_file), last_words=last or None,
                    argv=result.argv, returncode=result.returncode,
                )
            try:
                graph = json.loads(graph_file.read_text("utf-8"))
            except ValueError as e:
                raise EngineFailed(
                    f"the traced graph at {graph_file} is not JSON: {e!r}",
                    missing=str(graph_file),
                ) from e
            entries[call.entry_path] = normalize_graph(graph)
        return {"engine": "venv-cli", "trace_level": "RANDOM_CONTROL",
                "entries": entries}

    def render(self, calls, seeds, *, subject: str, resolution: str,
               samples: int, seed: int) -> bytes:
        """The subject entry's chain through ``render_cycles`` — Cycles on
        the GPU, at the ladder's resolution and sample count."""
        call = self._subject_call(calls, subject)
        chain = self.chain_for(call.name)
        width, height = render_dimensions(resolution)
        out = self._scratch(
            "render", call.entry_path, seed,
            suffix=f"{width}x{height}-{samples}spp")
        result = self._run([
            *chain, "render_cycles",
            "--seed", str(seed),
            "-r", str(width), str(height),
            "-s", str(samples),
            "--output", str(out),
        ])
        png = out / "Camera" / "0000.png"
        if not png.is_file():
            found = sorted(out.rglob("*.png"))
            if not found:
                last = self._last_words(result)
                raise EngineFailed(
                    f"the engine exited 0 but wrote no PNG under {out} — a "
                    f"silent no-op render is refused loudly; the CLI's last "
                    f"words: {last or '(none)'}",
                    missing=str(out), last_words=last or None,
                    argv=result.argv, returncode=result.returncode,
                )
            png = found[0]
        return png.read_bytes()

    def replace(self, graph, edits):  # pragma: no cover — the honest refusal
        raise EngineUnavailable(
            "single-node re-execution needs the call-site instrumentation "
            "the confirming experiment built engine-side (choice forcing); "
            "upstream ships no CLI for it — the fork's half of this seam",
            missing="instrumented re-execution",
        )

    def execute(self, graph):  # pragma: no cover — see replace
        raise EngineUnavailable(
            "see replace(): the venv boundary cannot re-execute a graph; "
            "re-trace the stage instead",
            missing="instrumented re-execution",
        )

    def export(self, graph, *, format: str, profile: str):  # pragma: no cover
        raise EngineUnavailable(
            "v2 ships no exporter (E §1); builder_usd is its natural home",
            missing="v2 exporter",
        )

    # -- internals -----------------------------------------------------------

    def _subject_call(self, calls, subject: str):
        """The call a render subject names: the exact entry path, else the
        first call in the recipe's (sorted) order — never a fuzzy guess."""
        by_path = {call.entry_path: call for call in calls}
        if subject in by_path:
            return by_path[subject]
        if not calls:
            raise EngineUnavailable(
                f"the recipe has no generator entries to render {subject!r}",
                missing=subject,
            )
        return calls[0]

    def _scratch(self, kind: str, name: str, seed: int,
                 suffix: str = "trace") -> Path:
        """A per-request scratch dir, wiped first so a stale file from an
        earlier run can never be mistaken for this run's output."""
        slug = name.replace(".", "_")
        out = self._output_dir / kind / f"{slug}-{seed}-{suffix}"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        return out

    @staticmethod
    def _last_words(result: CommandResult, limit: int = 240) -> str:
        """The engine's own last words for a failure row: stderr first, then
        stdout — a silent no-op (exit 0, nothing written) is exactly when
        the words matter, because nothing else names what happened."""
        return (result.stderr.strip()[-limit:] or result.stdout.strip()[-limit:])

    def _run(self, argv: Sequence[str]):
        result = self._runner.run([str(self._cli), *argv], cwd=self._repo)
        if result.returncode != 0:
            raise EngineFailed(
                f"the engine exited {result.returncode}: "
                f"{result.stderr.strip()[-400:] or result.stdout.strip()[-400:]}",
                argv=result.argv, returncode=result.returncode,
            )
        return result

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"Venv2Runtime({self._python})"
