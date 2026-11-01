"""The build stage: run the artefact in its kernel and measure it.

Both kernels are measured the same way: the wall clock of the build, the
per-body volume, area and centre of mass, and the files the kernel wrote.

Two things the harness adds to a SolidCraft script, and says so in the log:
a read-only ``assembly.mass_properties`` call (the measurement) and, when the
model did not write one, a URDF export. Neither changes the design.

The build123d side runs in the build123d venv, through
:mod:`core.cadbakeoff.b123d_runner`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: SolidCraft's ``file.export`` mesh qualities, and the chord tolerance each
#: one means. The tolerance is relative: it is a fraction of each body's own
#: size, so a bigger prop gets a coarser mesh in millimetres.
SOLIDCRAFT_CHORD_TOLERANCE = {
    "standard": 2e-4,
    "fine": 5e-5,
    "finest": 1e-5,
}

__all__ = ["BuildResult", "build_solidcraft", "build_build123d"]


@dataclass
class BuildResult:
    kernel: str
    prop: str
    ok: bool
    stage: str = "build"
    error: str | None = None
    build_ms: float | None = None
    process_ms: float | None = None
    bodies: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "prop": self.prop,
            "ok": self.ok,
            "stage": self.stage,
            "error": self.error,
            "build_ms": self.build_ms,
            "process_ms": self.process_ms,
            "bodies": self.bodies,
            "files": self.files,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# SolidCraft
# ---------------------------------------------------------------------------


def build_solidcraft(
    prop: str,
    script_path: str | Path,
    workdir: str | Path,
    *,
    cli: str | Path,
    registry: dict[str, dict[str, Any]],
    timeout: int = 600,
) -> BuildResult:
    script_path = Path(script_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "script.json"

    script = json.loads(script_path.read_text())
    commands = list(script.get("commands", []))
    wrote_urdf = any(
        c.get("command") == "file.export"
        and str(c.get("params", {}).get("path", "")).endswith(".urdf")
        for c in commands
        if isinstance(c, dict)
    )
    # The measurement, and the export when the model did not write one.
    commands.append({"command": "inspect.measure", "params": {}})
    commands.append({"command": "assembly.mass_properties", "params": {}})
    if not wrote_urdf:
        commands.append({"command": "file.export", "params": {"path": "robot.urdf", "format": "urdf"}})
    target.write_text(json.dumps({"commands": commands}, indent=1))

    cmd = [
        str(cli),
        "run",
        str(target),
        "--out",
        "prop.step",
        "--results",
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return BuildResult(
            "solidcraft", prop, False, error=f"the build did not finish in {timeout}s",
            process_ms=timeout * 1000,
        )
    process_ms = (time.perf_counter() - started) * 1000
    (workdir / "stdout.txt").write_text(proc.stdout)
    (workdir / "stderr.txt").write_text(proc.stderr)

    if proc.returncode != 0:
        return BuildResult(
            "solidcraft",
            prop,
            False,
            error=(proc.stderr.strip() or proc.stdout.strip() or "the build failed")[:800],
            process_ms=process_ms,
            logs={"stderr": proc.stderr[-2000:]},
        )

    try:
        steps = json.loads(proc.stdout[proc.stdout.find("[") :])
    except json.JSONDecodeError as exc:
        return BuildResult(
            "solidcraft", prop, False, error=f"the build results do not parse: {exc}",
            process_ms=process_ms,
        )

    # The build time is the sum of the steps' own times: the kernel's work,
    # without the CLI's start-up and without the harness's measurement calls.
    measurement_at = len(steps)
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if "total" in step and isinstance(step.get("bodies"), list):
            measurement_at = index
            break
        if "groups" in step and "occurrences" in step:
            measurement_at = index
            break
    build_ms = sum(
        float(s.get("ms", 0.0)) for s in steps[:measurement_at] if isinstance(s, dict) and "ms" in s
    )

    bodies: dict[str, dict[str, Any]] = {}
    for step in steps:
        if not isinstance(step, dict) or "bodies" not in step:
            continue
        if not isinstance(step.get("bodies"), list):
            continue
        if not any("area_mm2" in b for b in step["bodies"] if isinstance(b, dict)):
            continue
        for body in step["bodies"]:
            bodies[body["name"]] = {
                "volume_mm3": body.get("volume_mm3"),
                "area_mm2": body.get("area_mm2"),
                "center_of_mass_mm": body.get("center_of_mass"),
                "mass_kg": (body.get("mass_g") or 0.0) / 1000.0,
                "density_g_cm3": body.get("density_g_cm3"),
                "closed": body.get("closed"),
                "shells": (body.get("kernel") or {}).get("shells"),
                "faces": body.get("faces"),
            }
        total = step.get("total") or {}
        bodies["__assembly__"] = {
            "volume_mm3": total.get("volume_mm3"),
            "area_mm2": total.get("area_mm2"),
            "mass_kg": (total.get("mass_g") or 0.0) / 1000.0,
            "open_bodies_skipped": total.get("open_bodies_skipped"),
        }
    # The per-group mass properties carry the inertia tensor, and the groups
    # are the occurrences, so the bodies can be matched to them.
    occurrence_bodies = {
        o.get("occurrence"): [b["name"] for b in o.get("bodies", [])]
        for o in next(
            (s.get("occurrences") for s in steps if isinstance(s, dict) and "occurrences" in s),
            [],
        )
        or []
    }
    for step in steps:
        if not isinstance(step, dict) or "groups" not in step:
            continue
        for group in step.get("groups", []):
            mass = group.get("mass") or {}
            if not mass:
                continue
            bodies.setdefault("__assembly__", {}).update(
                {
                    "mass_kg": mass.get("mass_kg"),
                    "center_of_mass_mm": mass.get("center_of_mass_mm"),
                }
            )
            for occurrence in group.get("occurrences", []):
                for body_name in occurrence_bodies.get(occurrence, []):
                    if body_name in bodies:
                        bodies[body_name].setdefault(
                            "inertia_kg_mm2", mass.get("inertia_world_kg_mm2")
                        )

    files: dict[str, str] = {}
    for name in ("robot.urdf", "prop.step", "robot-floor.stl", "robot-lid.stl"):
        candidate = workdir / name
        if candidate.exists():
            files[name] = str(candidate)
    for candidate in sorted(workdir.glob("robot-*.stl")):
        files[candidate.name] = str(candidate)

    # The mesh quality the script asked for, if it asked for one at all.
    export_quality = "standard"
    try:
        payload = json.loads(Path(script_path).read_text())
        for command in payload.get("commands", []):
            if not isinstance(command, dict) or command.get("command") != "file.export":
                continue
            params = command.get("params") or {}
            if params.get("format") == "urdf":
                export_quality = str(params.get("quality") or "standard")
    except (OSError, json.JSONDecodeError):
        pass

    return BuildResult(
        "solidcraft",
        prop,
        True,
        build_ms=build_ms,
        process_ms=process_ms,
        bodies=bodies,
        files=files,
        extra={
            "model_wrote_urdf_export": wrote_urdf,
            "steps": len(steps),
            "harness_added_mass_properties": True,
            # Hy4 guard 3: the tessellation tolerance is logged. SolidCraft's
            # ``file.export`` takes a ``quality``: standard, fine or finest,
            # which is a chord tolerance of 2e-4, 5e-5 or 1e-5 *of each
            # body's size*. The model is not asked to set it, so it is
            # SolidCraft's default, standard, for every prop. The mass
            # properties do not depend on it: they are integrated on the
            # solid, not on the mesh.
            "mesh_export_quality": export_quality,
            "mesh_chord_tolerance_relative": SOLIDCRAFT_CHORD_TOLERANCE[export_quality],
            "mass_properties_source": "the solid (exact), not the mesh",
        },
    )


# ---------------------------------------------------------------------------
# build123d
# ---------------------------------------------------------------------------


def build_build123d(
    prop: str,
    script_path: str | Path,
    workdir: str | Path,
    *,
    python: str | Path,
    runner: str | Path,
    spec: dict[str, Any],
    timeout: int = 900,
) -> BuildResult:
    script_path = Path(script_path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    local_script = workdir / script_path.name
    if local_script.resolve() != script_path.resolve():
        shutil.copyfile(script_path, local_script)
    spec_file = workdir / "spec.json"
    spec_file.write_text(json.dumps(spec, indent=1))
    out_file = workdir / "runner_result.json"

    cmd = [
        str(python),
        str(runner),
        "--script",
        str(local_script),
        "--spec",
        str(spec_file),
        "--out",
        str(out_file),
        "--workdir",
        str(workdir),
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return BuildResult(
            "build123d", prop, False, error=f"the build did not finish in {timeout}s",
            process_ms=timeout * 1000,
        )
    process_ms = (time.perf_counter() - started) * 1000
    (workdir / "stdout.txt").write_text(proc.stdout)
    (workdir / "stderr.txt").write_text(proc.stderr)

    if not out_file.exists():
        return BuildResult(
            "build123d",
            prop,
            False,
            error=(proc.stderr.strip() or "the runner wrote no result")[-800:],
            process_ms=process_ms,
        )
    payload = json.loads(out_file.read_text())
    if not payload.get("ok"):
        return BuildResult(
            "build123d",
            prop,
            False,
            error=payload.get("error", "the build failed")[:800],
            process_ms=process_ms,
            build_ms=payload.get("build_ms"),
            logs={"traceback": payload.get("traceback", "")[-2000:]},
        )

    bodies = payload.get("bodies", {})
    files: dict[str, str] = {}
    for candidate in sorted(workdir.glob("*")):
        if candidate.suffix in (".step", ".stl", ".urdf"):
            files[candidate.name] = str(candidate)

    return BuildResult(
        "build123d",
        prop,
        True,
        build_ms=payload.get("build_ms"),
        process_ms=process_ms,
        bodies=bodies,
        files=files,
        extra={
            "library_ms": payload.get("library_ms"),
            "params": payload.get("params"),
            "missing_bodies": payload.get("missing_bodies", []),
            "step_written": payload.get("step_written"),
            "meshes": payload.get("meshes", {}),
        },
    )
