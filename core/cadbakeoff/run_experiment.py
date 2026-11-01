"""The experiment driver: validate, build, measure, check.

For every prop and every kernel:

1. the artefact is validated against its language's contract;
2. it is built in its kernel;
3. its mass properties are measured and compared with the analytic ground
   truth;
4. its URDF is checked against the frozen spec;
5. its action is executed in MuJoCo and scored.

A prop that fails at step 1 or 2 gets one repair round. The repair is asked
for with the same frozen brief and a kernel-agnostic error, and a repair that
moved the design is recorded and left out of the after-repair rate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import time
from typing import Any

from core.cadbakeoff.analytic import evaluate_prop
from core.cadbakeoff.build import build_build123d, build_solidcraft
from core.cadbakeoff.model import CloudModel, count_tokens, extract_json, extract_python
from core.cadbakeoff.repair import RepairRequest, build_repair_prompt, design_changed, spec_diff
from core.cadbakeoff.specs import PROPS, PROP_NAMES
from core.cadbakeoff.stl import Mesh
from core.cadbakeoff.urdf import (
    check_urdf_against_spec,
    compare_urdfs,
    parse_urdf,
    write_build123d_urdf,
)
from core.cadbakeoff.validate import (
    build123d_exports,
    load_registry,
    validate_build123d,
    validate_solidcraft,
)

KERNELS = ("solidcraft", "build123d")

#: How many times the repair round's model call may be re-asked when the
#: reply did not come back whole. This is the same transport flakiness the
#: generation retries, and it is not a second repair round: the design is
#: still frozen, and the budget and the backoff are the same on both sides.
REPAIR_RETRIES = 6
REPAIR_BACKOFF_SECONDS = (5, 10, 15, 25, 40, 60)


# ---------------------------------------------------------------------------
# one prop in one kernel
# ---------------------------------------------------------------------------


def run_one(
    prop: str,
    kernel: str,
    artifact: str | Path,
    work: pathlib.Path,
    *,
    cli: str,
    registry: dict[str, dict[str, Any]],
    python: str,
    runner: str,
    schema_cache: dict[str, Any],
    exports: set[str],
    do_action_check: bool = True,
) -> dict[str, Any]:
    spec = PROPS[prop]
    artifact = pathlib.Path(artifact)
    work.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"prop": prop, "kernel": kernel, "artifact": str(artifact)}

    # 1. the front-end check
    if kernel == "solidcraft":
        validation = validate_solidcraft(
            artifact,
            cli=cli,
            registry=registry,
            schema_cache=schema_cache,
            spec=spec,
        )
    else:
        validation = validate_build123d(
            artifact,
            spec=spec,
            build123d_names=exports,
            python=python,
            runner=runner,
        )
    record["validation"] = validation.as_dict()

    # 2. the build
    if kernel == "solidcraft":
        build = build_solidcraft(prop, artifact, work, cli=cli, registry=registry)
    else:
        build = build_build123d(
            prop, artifact, work, python=python, runner=runner, spec=spec
        )
    record["build"] = build.as_dict()
    record["build_ms"] = build.build_ms
    record["built_first_try"] = bool(validation.ok and build.ok)
    # Hy4 guard 5: a build time on a shared box means nothing without the box
    # state it was measured on. The same state is recorded for every prop and
    # every kernel, so the two columns can be compared.
    from core.cadbakeoff.sweep import box_state

    record["box_state"] = box_state()

    # 3. the URDF
    urdf_path = work / "robot.urdf"
    if kernel == "build123d" and build.ok:
        meshes = {
            name: Mesh(vertices=data["vertices"], triangles=data["triangles"])
            for name, data in (build.extra.get("meshes") or {}).items()
        }
        bodies = {
            name: {
                "mass_kg": data["mass_kg"],
                "center_of_mass_mm": data["center_of_mass_mm"],
                "inertia_kg_mm2": data["inertia_kg_mm2"],
            }
            for name, data in build.bodies.items()
        }
        write_build123d_urdf(spec, bodies, meshes, urdf_path)
    if urdf_path.exists():
        model = parse_urdf(urdf_path)
        record["urdf"] = check_urdf_against_spec(model, spec)
        record["urdf_path"] = str(urdf_path)
    else:
        record["urdf"] = {"ok": False, "problems": ["no URDF was produced"], "found": {}}

    # 4. the action
    if do_action_check and urdf_path.exists() and record["urdf"].get("ok"):
        from core.cadbakeoff.mujoco_check import check_action

        check = check_action(urdf_path, spec, work / "check")
        record["action"] = check.as_dict()
    else:
        record["action"] = {"ok": False, "error": "the action check was not run"}

    # 5. the analytic ground truth
    truth = evaluate_prop(spec)
    record["analytic"] = truth.as_dict()
    record["agreement_with_analytic"] = _compare_to_analytic(record, truth)
    return record


def _compare_to_analytic(record: dict[str, Any], truth: Any) -> dict[str, Any]:
    """How close the kernel's numbers are to the analytic ones."""
    bodies = record.get("build", {}).get("bodies") or {}
    out: dict[str, Any] = {}
    for body in truth.bodies:
        measured = bodies.get(body.name)
        if not measured or measured.get("volume_mm3") is None:
            out[body.name] = {"measured": False}
            continue
        volume = float(measured["volume_mm3"])
        rel = abs(volume - body.volume) / body.volume if body.volume else None
        entry: dict[str, Any] = {
            "measured": True,
            "volume_mm3_measured": volume,
            "volume_mm3_analytic": body.volume,
            "volume_rel_error": rel,
        }
        if measured.get("area_mm2") is not None:
            entry["area_mm2_measured"] = measured["area_mm2"]
            entry["area_mm2_analytic"] = body.area
            entry["area_rel_error"] = (
                abs(float(measured["area_mm2"]) - body.area) / body.area if body.area else None
            )
        if measured.get("center_of_mass_mm"):
            com = measured["center_of_mass_mm"]
            offset = max(abs(float(com[i]) - body.centre[i]) for i in range(3))
            entry["com_offset_mm"] = offset
        out[body.name] = entry
    return out


# ---------------------------------------------------------------------------
# the repair round
# ---------------------------------------------------------------------------


def repair_one(
    prop: str,
    kernel: str,
    artifact: str | Path,
    work: pathlib.Path,
    failure: dict[str, Any],
    *,
    model: CloudModel,
    cli: str,
    registry: dict[str, dict[str, Any]],
    python: str,
    runner: str,
    schema_cache: dict[str, Any],
    exports: set[str],
    system: str,
) -> dict[str, Any]:
    """One repair round, with the design frozen."""
    artifact = pathlib.Path(artifact)
    previous = artifact.read_text()
    request = RepairRequest(
        prop=prop,
        kernel=kernel,
        stage=failure.get("stage", "build"),
        message=failure.get("error") or "the script did not build",
        artifact=str(artifact),
    )
    prompt = build_repair_prompt(request, previous)
    # One repair *round*, but the round's model call may be retried when the
    # reply did not come back whole: that is the same transport flakiness the
    # generation retries, and it is not a second repair. The budget and the
    # backoff are the same on both sides.
    payload: str | None = None
    error: str | None = None
    reply = None
    attempts = 0
    for attempt in range(REPAIR_RETRIES):
        attempts += 1
        try:
            reply = model.call(prompt, system=system)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < REPAIR_RETRIES:
                time.sleep(REPAIR_BACKOFF_SECONDS[min(attempt, len(REPAIR_BACKOFF_SECONDS) - 1)])
            continue
        if kernel == "solidcraft":
            payload, error = extract_json(reply.text)
        else:
            payload, error = extract_python(reply.text)
        if payload is not None:
            break
        if attempt + 1 < REPAIR_RETRIES:
            time.sleep(REPAIR_BACKOFF_SECONDS[min(attempt, len(REPAIR_BACKOFF_SECONDS) - 1)])
    record: dict[str, Any] = {
        "prop": prop,
        "kernel": kernel,
        "request": request.as_dict(),
        "model": reply.model if reply is not None else None,
        "output_tokens": reply.output_tokens if reply is not None else 0,
        "duration_ms": reply.duration_ms if reply is not None else 0,
        "extract_error": error,
        "attempts": attempts,
    }
    if payload is None:
        record["ok"] = False
        record["error"] = error
        return record
    repaired = work / ("repaired." + ("json" if kernel == "solidcraft" else "py"))
    repaired.write_text(payload)
    record["repaired_artifact"] = str(repaired)
    record["script_tokens"] = count_tokens(payload)
    record["design_changed"] = design_changed(kernel, payload, prop)
    # Hy4 guard 2: the spec diff is logged whatever the verdict is, so a
    # repair that moved the design can be seen in the report, not only
    # inferred from the flag.
    record["spec_diff"] = spec_diff(kernel, payload, prop)
    result = run_one(
        prop,
        kernel,
        repaired,
        work / "repaired",
        cli=cli,
        registry=registry,
        python=python,
        runner=runner,
        schema_cache=schema_cache,
        exports=exports,
    )
    record["result"] = result
    record["ok"] = bool(result["built_first_try"])
    return record


# ---------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------


def compare_urdf_pair(
    prop: str, work_root: pathlib.Path, records: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """Compare the two arms' URDFs for one prop, in the world.

    The SolidCraft arm's URDF is exported by the kernel; the build123d arm's
    is written by the deterministic generator from the same spec. Guard 4
    asks for the two to be compared semantically, so this says whether they
    describe the same robot rather than whether their text matches.

    When an arm went through the repair round, its *repaired* artefact is the
    one that was built, so the repaired URDF is the one compared: comparing
    the first-try URDF against a repaired one would report a difference
    between two things that are not the prop.
    """
    spec = PROPS[prop]
    paths = {
        "solidcraft": work_root / f"{prop}.solidcraft" / "robot.urdf",
        "build123d": work_root / f"{prop}.build123d" / "robot.urdf",
    }
    for kernel, path in list(paths.items()):
        record = (records or {}).get(kernel)
        if not record:
            continue
        repair = record.get("repair") or {}
        inner = repair.get("result") or {}
        repaired = inner.get("urdf_path")
        if repaired and pathlib.Path(repaired).exists():
            paths[kernel] = pathlib.Path(repaired)
    if not all(path.exists() for path in paths.values()):
        return None
    models = {name: parse_urdf(path) for name, path in paths.items()}
    comparison = compare_urdfs(models["solidcraft"], models["build123d"], spec)
    comparison["compared"] = {name: str(path) for name, path in paths.items()}
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", default="~/lm-wt/cad-bakeoff/out/gen")
    parser.add_argument("--work", default="~/lm-wt/cad-bakeoff/work")
    parser.add_argument("--out", default="~/lm-wt/cad-bakeoff/out/result.json")
    parser.add_argument("--cli", default="~/lm-wt/cad-bakeoff/solidcraft/target/release/solidcraft-cli")
    parser.add_argument("--registry", default="~/lm-wt/cad-bakeoff/registry.json")
    parser.add_argument("--python", default="~/lm-wt/cad-bakeoff/b123d/bin/python")
    parser.add_argument("--runner", default="core/cadbakeoff/b123d_runner.py")
    parser.add_argument("--props", nargs="*", default=list(PROP_NAMES))
    parser.add_argument("--kernels", nargs="*", default=list(KERNELS))
    parser.add_argument("--repair", action="store_true", help="run the one repair round")
    parser.add_argument("--no-action-check", action="store_true")
    args = parser.parse_args()

    gen = pathlib.Path(args.gen).expanduser()
    work_root = pathlib.Path(args.work).expanduser()
    out_path = pathlib.Path(args.out).expanduser()
    cli = str(pathlib.Path(args.cli).expanduser())
    python = str(pathlib.Path(args.python).expanduser())
    runner = str(pathlib.Path(args.runner).resolve())
    registry = load_registry(pathlib.Path(args.registry).expanduser())

    schema_cache: dict[str, Any] = {}
    exports = build123d_exports(python)
    model = CloudModel(extra_args=[])
    from core.cadbakeoff.generate import SYSTEM

    results: list[dict[str, Any]] = []
    for prop in args.props:
        for kernel in args.kernels:
            suffix = ".json" if kernel == "solidcraft" else ".py"
            artifact = gen / f"{prop}.{kernel}{suffix}"
            if not artifact.exists():
                results.append({"prop": prop, "kernel": kernel, "error": "no artefact"})
                continue
            work = work_root / f"{prop}.{kernel}"
            if work.exists():
                shutil.rmtree(work)
            record = run_one(
                prop,
                kernel,
                artifact,
                work,
                cli=cli,
                registry=registry,
                python=python,
                runner=runner,
                schema_cache=schema_cache,
                exports=exports,
                do_action_check=not args.no_action_check,
            )
            if args.repair and not record["built_first_try"]:
                failure = record.get("validation") if not record["validation"]["ok"] else record["build"]
                record["repair"] = repair_one(
                    prop,
                    kernel,
                    artifact,
                    work,
                    failure,
                    model=model,
                    cli=cli,
                    registry=registry,
                    python=python,
                    runner=runner,
                    schema_cache=schema_cache,
                    exports=exports,
                    system=SYSTEM,
                )
            results.append(record)
            out_path.write_text(json.dumps(results, indent=1))
            print(
                f"{prop}.{kernel}: built_first_try={record.get('built_first_try')} "
                f"urdf_ok={record.get('urdf', {}).get('ok')} "
                f"action={record.get('action', {}).get('ok')}",
                flush=True,
            )
            if kernel == "build123d":
                # Guard 4: the two arms' URDFs are compared in the world, not
                # by text, so the action check measures the CAD and not
                # whoever wrote the robot description. The comparison uses
                # the repaired artefact where an arm went through a repair.
                comparison = compare_urdf_pair(
                    prop,
                    work_root,
                    {
                        r["kernel"]: r
                        for r in results
                        if r.get("prop") == prop and "kernel" in r
                    },
                )
                if comparison is not None:
                    record["urdf_comparison"] = comparison
                    print(
                        f"{prop}: the two URDFs are "
                        f"{'equal' if comparison['equal'] else 'different'}"
                        + ("" if comparison["equal"] else f": {comparison['diffs']}"),
                        flush=True,
                    )

    out_path.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
