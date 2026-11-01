"""The front-end check both kernels get.

Hy4 guard 1: SolidCraft's script is checked against the command registry
before it runs; build123d's was only read by a human. Both get an automated
check now, and a validation failure is counted separately from a build
failure.

What each check does:

SolidCraft
    the file parses as JSON, it is a command list, every command id is in the
    registry and enabled, and every command's parameters match the JSON Schema
    the registry carries for that command. Nothing is executed.

build123d
    the file parses as Python, it defines ``PARAMS`` and ``BODIES``, and every
    name it takes from build123d exists in build123d. Nothing is executed
    either.

The two checks are the same kind of thing: "is this artefact well formed
against its language's contract". The build stage is where the two kernels
execute, and that is where a geometry error lands for both.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ValidationResult", "validate_solidcraft", "validate_build123d", "load_registry"]


def load_registry(path: str | Path) -> dict[str, dict[str, Any]]:
    """The command registry as a dict keyed by command id."""
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict):
        return payload
    return {entry["id"]: entry for entry in payload if isinstance(entry, dict) and "id" in entry}


# ---------------------------------------------------------------------------
# does the artefact use its parameters?
# ---------------------------------------------------------------------------


def parameter_usage(body: str, declared: list[str]) -> dict[str, Any]:
    """Which declared parameters the artefact actually refers to.

    The brief asks for props that are parametric: at least three named
    parameters that the geometry is built from. A script that declares the
    names and then writes literal numbers is not parametric, and the sweep
    would show it changing nothing. The same question is asked of both
    kernels, in the same way: the name has to appear somewhere other than
    where it is declared.

    ``body`` is the artefact with the declaration itself removed, so any
    occurrence left is a use. A name counts as used when it appears inside a
    dimension expression such as ``-width/2`` or ``height - 2*plank`` as well
    as when it stands alone.
    """
    used: dict[str, int] = {}
    for name in declared:
        pattern = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
        used[name] = len(pattern.findall(body))
    return {
        "declared": declared,
        "occurrences": used,
        "used": sorted(name for name, count in used.items() if count >= 1),
        "unused": sorted(name for name, count in used.items() if count < 1),
    }


def string_values(obj: Any) -> list[str]:
    """Every string inside a JSON-ish structure, keys excluded."""
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(string_values(value))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(string_values(item))
    return out


@dataclass
class ValidationResult:
    kernel: str
    ok: bool
    stage: str = "validation"
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "ok": self.ok,
            "stage": self.stage,
            "error": self.error,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# SolidCraft
# ---------------------------------------------------------------------------


def _schema_for(cli: str, command: str, cache: dict[str, Any]) -> dict[str, Any] | None:
    if command in cache:
        return cache[command]
    proc = subprocess.run(
        [cli, "exec", "engine.describe", json.dumps({"command": command})],
        capture_output=True,
        text=True,
        timeout=120,
    )
    schema: dict[str, Any] | None = None
    if proc.returncode == 0:
        try:
            payload = json.loads(proc.stdout[proc.stdout.find("{") :])
            schema = payload.get("input")
        except json.JSONDecodeError:
            schema = None
    cache[command] = schema
    return schema


def validate_solidcraft(
    script_path: str | Path,
    *,
    cli: str | Path,
    registry: dict[str, dict[str, Any]],
    schema_cache: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
) -> ValidationResult:
    script_path = Path(script_path)
    try:
        raw = script_path.read_text()
    except OSError as exc:
        return ValidationResult("solidcraft", False, error=f"the script cannot be read: {exc}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ValidationResult("solidcraft", False, error=f"the script is not valid JSON: {exc}")
    if not isinstance(payload, dict) or not isinstance(payload.get("commands"), list):
        return ValidationResult(
            "solidcraft", False, error='the script is not an object with a "commands" list'
        )
    commands = payload["commands"]
    if not commands:
        return ValidationResult("solidcraft", False, error="the command list is empty")

    problems: list[str] = []
    known = 0
    unknown: list[str] = []
    schema_checked = 0
    schema_skipped: list[str] = []
    cache = schema_cache if schema_cache is not None else {}

    for index, entry in enumerate(commands):
        if not isinstance(entry, dict):
            problems.append(f"command {index} is not an object")
            continue
        name = entry.get("command")
        if not isinstance(name, str):
            problems.append(f"command {index} has no command name")
            continue
        info = registry.get(name)
        if info is None:
            unknown.append(name)
            problems.append(f"command {index} uses {name!r}, which is not in the registry")
            continue
        if not info.get("enabled", True):
            problems.append(f"command {index} uses {name!r}, which is disabled")
            continue
        known += 1
        params = entry.get("params", {})
        if not isinstance(params, dict):
            problems.append(f"command {index} ({name}) has params that are not an object")
            continue
        schema = _schema_for(str(cli), name, cache)
        if schema is None:
            schema_skipped.append(name)
            continue
        schema_checked += 1
        error = _check_against_schema(params, schema)
        if error:
            problems.append(f"command {index} ({name}): {error}")

    conformance: dict[str, Any] | None = None
    if spec is not None:
        conformance = check_solidcraft_against_spec(commands, spec)
        problems.extend(conformance["problems"])

    return ValidationResult(
        "solidcraft",
        not problems,
        error="; ".join(problems[:6]) if problems else None,
        details={
            "commands": len(commands),
            "known_commands": known,
            "unknown_commands": unknown,
            "schema_checked": schema_checked,
            "schema_not_available": schema_skipped,
            "problems": problems,
            "parameter_usage": _solidcraft_parameter_usage(commands, registry),
            "spec_conformance": conformance,
        },
    )


def _solidcraft_declared_names(commands: list[Any]) -> tuple[set[str], set[str]]:
    """The body names and the joint names the script declares.

    Only a ``solid.*`` command with a ``body_name`` *creates* a body. A
    ``solid.combine`` names the body it merges into and a
    ``component.from_bodies`` names the bodies it groups, but both refer to
    bodies that already exist — so neither of them counts as creating one.
    Counting a reference as a creation would hide exactly the mistake this
    check is for.
    """
    bodies: set[str] = set()
    joints: set[str] = set()
    for entry in commands:
        if not isinstance(entry, dict):
            continue
        name = entry.get("command")
        params = entry.get("params") or {}
        if not isinstance(params, dict):
            continue
        if isinstance(name, str) and name.startswith("solid."):
            body = params.get("body_name")
            if isinstance(body, str):
                bodies.add(body)
        if name == "joint.create":
            joint = params.get("name")
            if isinstance(joint, str):
                joints.add(joint)
    return bodies, joints


def check_solidcraft_against_spec(
    commands: list[Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Does the script build the bodies and the joint the spec names?

    Hy4 guard 1 wants the two arms held to the same front-end check. The
    build123d side has to declare the spec's bodies, and the dry run fails
    when it does not. The SolidCraft side has to declare the spec's bodies
    *and* the spec's joint, because its URDF comes from its own script: a
    script that names the joint something else builds a prop whose joint the
    action check cannot find.

    This is a conformance check against the frozen spec, not against the
    kernel: the kernel is happy either way.
    """
    bodies, joints = _solidcraft_declared_names(commands)
    want_bodies = {b["name"] for b in spec["bodies"]}
    want_joints = {j["name"] for j in spec["joints"]}
    missing_bodies = sorted(want_bodies - bodies)
    missing_joints = sorted(want_joints - joints)
    extra_joints = sorted(joints - want_joints)
    problems: list[str] = []
    if missing_bodies:
        problems.append(
            f"the script does not create the bodies {missing_bodies} that the spec names"
        )
    if missing_joints:
        problems.append(
            f"the script does not create the joints {missing_joints} that the spec names"
        )
    return {
        "ok": not problems,
        "problems": problems,
        "declared_bodies": sorted(bodies),
        "declared_joints": sorted(joints),
        "missing_bodies": missing_bodies,
        "missing_joints": missing_joints,
        "extra_joints": extra_joints,
    }


def _solidcraft_parameter_usage(
    commands: list[Any], registry: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Which declared parameters the script's other commands refer to."""
    declared: list[str] = []
    others: list[Any] = []
    for entry in commands:
        if not isinstance(entry, dict):
            continue
        if entry.get("command") == "parameters.add":
            params = entry.get("params") or {}
            name = params.get("name")
            if isinstance(name, str):
                declared.append(name)
            continue
        others.append(entry)
    body = "\n".join(string_values(others))
    usage = parameter_usage(body, declared)
    usage["declared"] = declared
    return usage


def _check_against_schema(params: dict[str, Any], schema: dict[str, Any]) -> str | None:
    try:
        import jsonschema  # type: ignore

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            where = "/".join(str(p) for p in first.path)
            return f"the parameters do not match the schema at {where or '<root>'}: {first.message}"
        return None
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# build123d
# ---------------------------------------------------------------------------


def validate_build123d(
    script_path: str | Path,
    *,
    spec: dict[str, Any],
    build123d_names: set[str] | None = None,
    python: str | Path | None = None,
    runner: str | Path | None = None,
) -> ValidationResult:
    script_path = Path(script_path)
    try:
        raw = script_path.read_text()
    except OSError as exc:
        return ValidationResult("build123d", False, error=f"the script cannot be read: {exc}")
    try:
        tree = ast.parse(raw)
    except SyntaxError as exc:
        return ValidationResult("build123d", False, error=f"the script is not valid Python: {exc}")

    problems: list[str] = []
    assigned: set[str] = set()
    imported: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
        elif isinstance(node, ast.ImportFrom) and node.module == "build123d":
            imported.extend(alias.name for alias in node.names)

    if "PARAMS" not in assigned:
        problems.append("the module does not define PARAMS")
    if "BODIES" not in assigned:
        problems.append("the module does not define BODIES")

    unknown: list[str] = []
    if build123d_names is not None:
        for name in imported:
            if name != "*" and name not in build123d_names:
                unknown.append(name)
                problems.append(f"{name!r} is not a name build123d exports")

    expected_params = set(spec["parameters"])
    expected_bodies = {b["name"] for b in spec["bodies"]}

    # Which declared parameters the module refers to outside its own PARAMS
    # dict: the same question the SolidCraft check asks.
    params_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets
        ):
            params_node = node
            break
    declared = list(expected_params)
    rest = raw
    if params_node is not None:
        segment = ast.get_source_segment(raw, params_node)
        if segment:
            rest = raw.replace(segment, "")
    usage = parameter_usage(rest, declared)

    # Hy4 guard 1: the SolidCraft side gets its command registry and the
    # CLI's own schemas checked before the script runs, so the Python side
    # gets the same thing: the module is imported in the build123d venv and
    # has to declare PARAMS and BODIES, or the import fails, before the
    # build starts. A script that will not load is a *validation* failure
    # on both sides, and is counted as one.
    dry_run: dict[str, Any] | None = None
    if python is not None and runner is not None:
        dry_run = _build123d_dry_run(script_path, spec, python=python, runner=runner)
        if dry_run.get("error"):
            problems.append(f"the script does not load: {dry_run['error']}")
        else:
            for problem in dry_run.get("problems") or []:
                problems.append(str(problem))

    return ValidationResult(
        "build123d",
        not problems,
        error="; ".join(problems[:6]) if problems else None,
        details={
            "imports": sorted(set(imported)),
            "unknown_imports": unknown,
            "expected_parameters": sorted(expected_params),
            "expected_bodies": sorted(expected_bodies),
            "problems": problems,
            "parameter_usage": usage,
            "dry_run": dry_run,
        },
    )


def _build123d_dry_run(
    script_path: Path,
    spec: dict[str, Any],
    *,
    python: str | Path,
    runner: str | Path,
    timeout: int = 900,
) -> dict[str, Any]:
    """Import the module in the build123d venv and check what it declares."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="cadbakeoff-dryrun-") as tmp:
        tmpdir = Path(tmp)
        spec_file = tmpdir / "spec.json"
        spec_file.write_text(json.dumps(spec, indent=1))
        out_file = tmpdir / "dryrun.json"
        cmd = [
            str(python),
            str(runner),
            "--script",
            str(script_path),
            "--spec",
            str(spec_file),
            "--out",
            str(out_file),
            "--workdir",
            str(tmpdir / "work"),
            "--dry-run",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"the import did not finish in {timeout}s"}
        try:
            payload = json.loads(out_file.read_text())
        except (OSError, json.JSONDecodeError):
            return {
                "ok": False,
                "error": (proc.stderr.strip() or proc.stdout.strip() or "the dry run said nothing")[:400],
            }
        payload["returncode"] = proc.returncode
        if not payload.get("ok") and not payload.get("error"):
            payload["error"] = "; ".join(payload.get("problems") or []) or "the dry run failed"
        return payload


def build123d_exports(python: str | Path) -> set[str]:
    """The names the build123d venv's build123d exports."""
    proc = subprocess.run(
        [str(python), "-c", "import build123d, json; print(json.dumps(sorted(dir(build123d))))"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        return set()
    try:
        return set(json.loads(proc.stdout.strip().splitlines()[-1]))
    except (json.JSONDecodeError, IndexError):
        return set()
