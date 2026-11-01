#!/usr/bin/env python3
"""The parameter sweep: 2 props, 20 variants each, programmatically generated.

Hy4 guard 5. The traps it names, and what this module does about each:

*the variants may be model-generated and therefore not independent*
    Every variant here comes from a Halton sequence over the prop's own
    parameter ranges. No model is asked for a variant, so the variants are
    independent of the model's taste and the same every time the sweep runs.

*validity may mean only "builds without error"*
    A variant counts as valid only when it builds, its geometry is not
    degenerate (every body has a positive volume, is a closed valid solid and
    is a single shell), and the action check passes.

*build ms is measured on a shared box, so the timing is confounded*
    Every build records the box state next to its time: the free memory, the
    load average and one line of tegrastats. Both kernels run in the same
    worker, one after the other, so they see the same contention.

*Rust CLI and Python/OCP have different runtimes*
    The same timeout, the same machine and the same repeats are used for
    both, and the median of the repeats is what is reported.

The sweep is run twice over the same variants, once per kernel, from the
artefacts the model wrote in the main run.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any

from core.cadbakeoff.build import build_build123d, build_solidcraft
from core.cadbakeoff.mujoco_check import check_action
from core.cadbakeoff.specs import PROPS, PROP_NAMES, expr
from core.cadbakeoff.stl import Mesh
from core.cadbakeoff.urdf import parse_urdf, write_build123d_urdf
from core.cadbakeoff.validate import load_registry

ROOT = pathlib.Path.home() / "lm-wt/cad-bakeoff"

#: The two props the sweep runs on. The crate is the prop the brief asks for
#: an analytic ground truth on, and the drawer unit is the one with two
#: sliding joints, so the sweep covers a turn and a slide.
SWEEP_PROPS = ("crate", "drawer_unit")

#: How many variants per prop. Variant 0 is the prop's own parameters, so the
#: sweep carries its own control; the rest are Halton samples.
VARIANTS = 20

#: How many times each variant is built. The median of the repeats is
#: reported.
REPEATS = 3

#: The range each parameter is swept over, in millimetres. The ranges are
#: wide enough to change the shape and narrow enough to stay a prop.
RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "crate": {
        "width": (280.0, 560.0),
        "depth": (210.0, 420.0),
        "height": (175.0, 350.0),
        "plank": (12.0, 28.0),
    },
    "drawer_unit": {
        "unit_width": (420.0, 840.0),
        "unit_depth": (350.0, 700.0),
        "unit_height": (560.0, 1120.0),
        "wall": (20.0, 45.0),
        "drawer_height": (231.0, 462.0),
    },
}
#: drawer_travel is not swept: it is the joint's range, and the action's
#: target is frozen at 300 mm, so moving it would change the action rather
#: than the geometry.


# ---------------------------------------------------------------------------
# the variants
# ---------------------------------------------------------------------------


def halton(index: int, base: int) -> float:
    """The Halton sequence: a deterministic, low-discrepancy sweep."""
    result = 0.0
    fraction = 1.0 / base
    n = index
    while n > 0:
        result += fraction * (n % base)
        n //= base
        fraction /= base
    return result


def make_variants(prop: str) -> list[dict[str, float]]:
    """The 20 variants of a prop, generated from its parameter ranges."""
    spec = PROPS[prop]
    ranges = RANGES[prop]
    names = list(ranges)
    variants: list[dict[str, float]] = [dict(spec["parameters"])]
    for i in range(1, VARIANTS):
        variant: dict[str, float] = {}
        for dim, name in enumerate(names):
            low, high = ranges[name]
            u = halton(i, [2, 3, 5, 7, 11][dim])
            value = low + u * (high - low)
            if name in ("rung_count",):
                value = float(round(value))
            variant[name] = round(value, 4)
        # The parameters the sweep does not touch keep their design value.
        for name, value in spec["parameters"].items():
            variant.setdefault(name, value)
        variants.append(variant)
    return variants


def spec_with(spec: dict[str, Any], overrides: dict[str, float]) -> dict[str, Any]:
    """The same spec with different parameter values."""
    out = json.loads(json.dumps(spec))
    out["parameters"] = dict(overrides)
    return out


# ---------------------------------------------------------------------------
# patching the model's artefact
# ---------------------------------------------------------------------------


def patch_solidcraft(text: str, values: dict[str, float]) -> tuple[str, list[str]]:
    """Set the declared parameter values in a SolidCraft script.

    The design of the script is left alone: only the ``parameters.add``
    expressions are rewritten, so whatever the script does with a parameter
    name still happens.
    """
    payload = json.loads(text)
    patched: list[str] = []
    for command in payload.get("commands", []):
        if not isinstance(command, dict) or command.get("command") != "parameters.add":
            continue
        params = command.get("params") or {}
        name = params.get("name")
        if name in values:
            params["expression"] = f"{values[name]:g}"
            patched.append(name)
    return json.dumps(payload, indent=1), patched


def patch_build123d(text: str, values: dict[str, float]) -> tuple[str, list[str]]:
    """Set the declared parameter values in a build123d module.

    The ``PARAMS`` dict is rewritten in place; the rest of the module, which
    is the design, is left alone.
    """
    match = re.search(r"(?m)^(\s*)PARAMS\s*=\s*", text)
    if not match:
        return text, []
    start = match.end()
    depth = 0
    end = None
    for index in range(start, len(text)):
        char = text[index]
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return text, []
    literal = text[start:end]
    patched: list[str] = []
    for name, value in values.items():
        pattern = re.compile(
            r"(['\"])" + re.escape(name) + r"\1(\s*:\s*)(-?\d+(?:\.\d+)?)"
        )
        if pattern.search(literal):
            literal = pattern.sub(lambda m: f"{m.group(1)}{name}{m.group(1)}{m.group(2)}{value:g}", literal)
            patched.append(name)
    return text[:start] + literal + text[end:], patched


# ---------------------------------------------------------------------------
# the box state
# ---------------------------------------------------------------------------


def box_state() -> dict[str, Any]:
    """What the machine looked like at this moment."""
    state: dict[str, Any] = {}
    try:
        info: dict[str, int] = {}
        for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0])
        state["mem_total_kb"] = info.get("MemTotal")
        state["mem_available_kb"] = info.get("MemAvailable")
        state["mem_free_kb"] = info.get("MemFree")
        state["swap_free_kb"] = info.get("SwapFree")
    except OSError:
        pass
    try:
        state["load_average"] = [
            float(v) for v in pathlib.Path("/proc/loadavg").read_text().split()[:3]
        ]
    except OSError:
        pass
    try:
        proc = subprocess.run(
            ["timeout", "1", "tegrastats", "--interval", "200"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first = (proc.stdout or "").strip().splitlines()
        if first:
            state["tegrastats"] = first[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return state


# ---------------------------------------------------------------------------
# one variant, one kernel, one repeat
# ---------------------------------------------------------------------------


def run_variant(
    prop: str,
    kernel: str,
    variant_index: int,
    values: dict[str, float],
    repeat: int,
    *,
    source: pathlib.Path,
    work: pathlib.Path,
    cli: str,
    registry: dict[str, Any],
    python: str,
    runner: str,
    timeout: int,
) -> dict[str, Any]:
    """Build one variant and measure it."""
    spec = spec_with(PROPS[prop], values)
    run_dir = work / prop / kernel / f"v{variant_index:02d}" / f"r{repeat}"
    run_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "prop": prop,
        "kernel": kernel,
        "variant": variant_index,
        "repeat": repeat,
        "parameters": values,
    }

    if kernel == "solidcraft":
        text, patched = patch_solidcraft(source.read_text(), values)
        script = run_dir / "script.json"
        script.write_text(text)
        record["parameters_patched"] = patched
        build = build_solidcraft(prop, script, run_dir, cli=cli, registry=registry, timeout=timeout)
    else:
        text, patched = patch_build123d(source.read_text(), values)
        script = run_dir / source.name
        script.write_text(text)
        record["parameters_patched"] = patched
        build = build_build123d(
            prop, script, run_dir, python=python, runner=runner, spec=spec, timeout=timeout
        )
    record["build_ok"] = build.ok
    record["build_error"] = build.error
    record["build_ms"] = build.build_ms
    record["process_ms"] = build.process_ms
    record["box_state"] = box_state()

    # A variant only counts as a variant if the parameters the sweep is
    # sweeping actually reached the artefact. A script that hard-codes its
    # numbers would otherwise be built twenty times and counted twenty
    # times, and the sweep would measure the same geometry every time.
    swept = set(RANGES[prop])
    missing = sorted(swept - set(patched))
    record["parameters_missing"] = missing
    if missing:
        record["valid"] = False
        record["stage"] = "patch"
        record["error"] = f"the artefact does not declare the swept parameters {missing}"
        return record

    if not build.ok:
        record["valid"] = False
        record["stage"] = "build"
        return record

    # The geometry has to be more than "did not crash".
    bodies = build.bodies or {}
    degenerate: list[str] = []
    for name, data in bodies.items():
        if name.startswith("__"):
            continue
        volume = data.get("volume_mm3")
        if volume is None or volume <= 0:
            degenerate.append(f"{name}: volume {volume}")
            continue
        if kernel == "solidcraft":
            if data.get("closed") is False:
                degenerate.append(f"{name}: the solid is not closed")
            shells = data.get("shells")
            if shells is not None and shells != 1:
                degenerate.append(f"{name}: {shells} shells")
        else:
            if data.get("is_valid") is False:
                degenerate.append(f"{name}: the shape is not a valid solid")
            solids = data.get("solids")
            if solids is not None and solids != 1:
                degenerate.append(f"{name}: {solids} solids")
    record["degenerate"] = degenerate
    record["non_degenerate"] = not degenerate

    # The URDF: SolidCraft's own export, or the deterministic generator on the
    # same spec with the kernel's own meshes and masses.
    urdf_path = run_dir / "robot.urdf"
    if kernel == "build123d":
        meshes = {
            name: Mesh(vertices=data["vertices"], triangles=data["triangles"])
            for name, data in (build.extra.get("meshes") or {}).items()
        }
        bodies_urdf = {
            name: {
                "mass_kg": data["mass_kg"],
                "center_of_mass_mm": data["center_of_mass_mm"],
                "inertia_kg_mm2": data["inertia_kg_mm2"],
            }
            for name, data in build.bodies.items()
        }
        if bodies_urdf and meshes:
            write_build123d_urdf(spec, bodies_urdf, meshes, urdf_path)

    if not urdf_path.exists():
        record["valid"] = False
        record["stage"] = "urdf"
        record["error"] = "no URDF was produced"
        return record

    # How far the joint ended up from where the spec puts it. On the
    # build123d side this is zero by construction; on the SolidCraft side it
    # is the distance the frozen number in the script drifted.
    record["joint_drift_mm"] = joint_drift(urdf_path, spec)

    check = check_action(urdf_path, spec, run_dir / "check")
    record["action_ok"] = check.ok
    record["action_error"] = check.error
    record["action"] = {
        "completed": check.completed,
        "stable": check.stable,
        "rest_stable": check.rest_stable,
        "max_penetration_mm": check.max_penetration,
        "penetration_eps_mm": check.penetration_eps,
        "settling_ms": check.settling_ms,
    }
    record["valid"] = bool(build.ok and not degenerate and check.ok)
    record["stage"] = "done"
    return record


def joint_drift(urdf_path: pathlib.Path, spec: dict[str, Any]) -> float | None:
    """How far the URDF's joint sits from where the spec puts it, in mm."""
    try:
        model = parse_urdf(urdf_path)
    except Exception:  # noqa: BLE001
        return None
    params = dict(spec["parameters"])
    for joint in spec["joints"]:
        found = model.joints.get(joint["name"])
        if found is None:
            return None
        parent = model.world_transform(found.parent)
        local = found.origin
        world = (
            parent[0][0] * local[0] + parent[0][1] * local[1] + parent[0][2] * local[2] + parent[0][3],
            parent[1][0] * local[0] + parent[1][1] * local[1] + parent[1][2] * local[2] + parent[1][3],
            parent[2][0] * local[0] + parent[2][1] * local[1] + parent[2][2] * local[2] + parent[2][3],
        )
        want = [expr(v, params) for v in joint["origin"]]
        # The URDF is in metres and the spec is in millimetres.
        return max(abs(world[i] * 1000.0 - want[i]) for i in range(3))
    return None


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------


def sweep_prop(
    prop: str,
    *,
    gen: pathlib.Path,
    work: pathlib.Path,
    out: pathlib.Path,
    cli: str,
    registry: dict[str, Any],
    python: str,
    runner: str,
    timeout: int,
    repeats: int,
    repaired: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    variants = make_variants(prop)
    results: list[dict[str, Any]] = []
    for kernel in ("solidcraft", "build123d"):
        suffix = ".json" if kernel == "solidcraft" else ".py"
        source = gen / f"{prop}.{kernel}{suffix}"
        if (repaired or {}).get((prop, kernel)):
            source = pathlib.Path((repaired or {})[(prop, kernel)])
        if not source.exists():
            results.append({"prop": prop, "kernel": kernel, "error": "no artefact"})
            continue
        for index, values in enumerate(variants):
            for repeat in range(repeats):
                record = run_variant(
                    prop,
                    kernel,
                    index,
                    values,
                    repeat,
                    source=source,
                    work=work,
                    cli=cli,
                    registry=registry,
                    python=python,
                    runner=runner,
                    timeout=timeout,
                )
                results.append(record)
                out.write_text(json.dumps(results, indent=1))
            print(
                f"{prop}.{kernel} v{index:02d}: "
                + " ".join(
                    f"r{r}={'ok' if results[-1 - (repeats - 1 - r)].get('valid') else 'fail'}"
                    for r in range(repeats)
                )
                + f" ms={[results[-1 - (repeats - 1 - r)].get('build_ms') for r in range(repeats)]}",
                flush=True,
            )
    return {"prop": prop, "variants": variants, "results": results}


def summarise(sweep: dict[str, Any]) -> dict[str, Any]:
    """The validity rate and the median build time, per kernel."""
    by_kernel: dict[str, list[dict[str, Any]]] = {}
    for record in sweep.get("results", []):
        if "error" in record:
            continue
        by_kernel.setdefault(record["kernel"], []).append(record)
    out: dict[str, Any] = {}
    for kernel, records in by_kernel.items():
        variants: dict[int, list[dict[str, Any]]] = {}
        for record in records:
            variants.setdefault(record["variant"], []).append(record)
        valid_all = 0
        valid_majority = 0
        build_times: list[float] = []
        per_variant = []
        for index, group in sorted(variants.items()):
            oks = [bool(r.get("valid")) for r in group]
            times = [r["build_ms"] for r in group if r.get("build_ms") is not None]
            if oks and all(oks):
                valid_all += 1
            if oks and sum(oks) * 2 > len(oks):
                valid_majority += 1
            if times:
                build_times.extend(times)
            per_variant.append(
                {
                    "variant": index,
                    "valid": oks,
                    "build_ms": times,
                    "build_ms_median": statistics.median(times) if times else None,
                    "joint_drift_mm": group[0].get("joint_drift_mm"),
                    "degenerate": group[0].get("degenerate"),
                    "error": group[0].get("action_error") or group[0].get("build_error"),
                }
            )
        out[kernel] = {
            "variants": len(variants),
            "valid_all_repeats": valid_all,
            "valid_majority": valid_majority,
            "validity_rate_all": valid_all / len(variants) if variants else None,
            "validity_rate_majority": valid_majority / len(variants) if variants else None,
            "build_ms_median": statistics.median(build_times) if build_times else None,
            "build_ms_min": min(build_times) if build_times else None,
            "build_ms_max": max(build_times) if build_times else None,
            "build_ms_mean": statistics.fmean(build_times) if build_times else None,
            "per_variant": per_variant,
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", default=str(ROOT / "out/gen"))
    parser.add_argument("--work", default=str(ROOT / "work/sweep"))
    parser.add_argument("--out", default=str(ROOT / "out/sweep.json"))
    parser.add_argument("--cli", default=str(ROOT / "solidcraft/target/release/solidcraft-cli"))
    parser.add_argument("--registry", default=str(ROOT / "registry.json"))
    parser.add_argument("--python", default=str(ROOT / "b123d/bin/python"))
    parser.add_argument("--runner", default="core/cadbakeoff/b123d_runner.py")
    parser.add_argument("--props", nargs="*", default=list(SWEEP_PROPS))
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--result",
        default=str(ROOT / "out/result.json"),
        help=(
            "the main run's results. When an arm went through the repair "
            "round, the sweep uses the repaired artefact: the sweep measures "
            "the prop the pipeline produced, not the first attempt that the "
            "repair already replaced."
        ),
    )
    args = parser.parse_args()

    gen = pathlib.Path(args.gen)
    work = pathlib.Path(args.work)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registry(args.registry)
    runner = str(pathlib.Path(args.runner).resolve())
    repaired = _repaired_artefacts(pathlib.Path(args.result))

    sweeps = []
    for prop in args.props:
        sweep = sweep_prop(
            prop,
            gen=gen,
            work=work,
            out=out,
            cli=args.cli,
            registry=registry,
            python=args.python,
            runner=runner,
            timeout=args.timeout,
            repeats=args.repeats,
            repaired=repaired,
        )
        sweep["summary"] = summarise(sweep)
        sweeps.append(sweep)
        out.write_text(json.dumps(sweeps, indent=1))
    return 0


def _repaired_artefacts(result_path: pathlib.Path) -> dict[tuple[str, str], str]:
    """Where the repaired artefacts are, keyed by (prop, kernel)."""
    try:
        records = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[tuple[str, str], str] = {}
    for record in records:
        repair = (record or {}).get("repair") or {}
        artifact = repair.get("repaired_artifact")
        if artifact and pathlib.Path(artifact).exists():
            out[(record["prop"], record["kernel"])] = artifact
    return out


if __name__ == "__main__":
    sys.exit(main())
