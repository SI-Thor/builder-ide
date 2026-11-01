"""The runner that executes a build123d script inside the build123d venv.

The model writes the module; this file imports it, measures it and writes the
meshes the URDF needs. It is run by the build123d venv's own interpreter, so
the model's code only ever runs there.

Usage:
    b123d_runner.py --script prop.py --spec spec.json --out result.json \\
                    --workdir DIR
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import time
import traceback

MM_TO_M = 0.001

#: The chord tolerance the mesh is tessellated at, in millimetres.
#:
#: It only affects the mesh that goes into the URDF as the visual and the
#: collision geometry. The volume, the area, the centre of mass and the
#: inertia are read from the solid itself (``shape.volume`` and friends),
#: which OCCT integrates exactly, so they do not depend on this number. It is
#: logged anyway, because the mesh is what the physics engine collides with.
TESSELLATION_TOLERANCE_MM = 0.05


def _tessellate(shape, tolerance: float = TESSELLATION_TOLERANCE_MM):
    points, triangles = shape.tessellate(tolerance)
    vertices = [(p.X, p.Y, p.Z) for p in points]
    return vertices, [tuple(t) for t in triangles]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--density", type=float, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "import the module and check that it declares PARAMS and BODIES, "
            "then stop. No measuring, no exporting. This is the front-end "
            "check the SolidCraft side gets from the command registry, run "
            "the same way for the Python side."
        ),
    )
    args = parser.parse_args()

    workdir = pathlib.Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    spec = json.loads(pathlib.Path(args.spec).read_text())
    density = args.density if args.density is not None else spec["density_kg_m3"]
    density_scale = density * 1e-9  # kg per mm^3

    result: dict = {"script": args.script, "ok": False}

    t_start = time.perf_counter()
    import build123d
    from build123d import Compound, export_step

    t_lib = time.perf_counter()

    script_path = pathlib.Path(args.script).resolve()
    sys.path.insert(0, str(script_path.parent))
    module_name = f"cadbakeoff_{script_path.stem}"
    spec_mod = importlib.util.spec_from_file_location(module_name, script_path)
    if spec_mod is None or spec_mod.loader is None:
        result["error"] = "the script could not be loaded as a module"
        pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
        return 1
    module = importlib.util.module_from_spec(spec_mod)

    t_before = time.perf_counter()
    try:
        spec_mod.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        result["build_ms"] = int((time.perf_counter() - t_before) * 1000)
        pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
        print(result["error"], file=sys.stderr)
        return 1
    t_after = time.perf_counter()

    bodies = getattr(module, "BODIES", None)
    params = getattr(module, "PARAMS", None)
    result["build_ms"] = int((t_after - t_before) * 1000)
    result["library_ms"] = int((t_lib - t_start) * 1000)
    result["process_ms"] = int((time.perf_counter() - t_start) * 1000)
    result["has_bodies"] = isinstance(bodies, dict)
    result["has_params"] = isinstance(params, dict)
    result["params"] = params if isinstance(params, dict) else None
    result["tessellation_tolerance_mm"] = TESSELLATION_TOLERANCE_MM
    result["mass_properties_source"] = "the solid (exact), not the mesh"

    if args.dry_run:
        # The dry run stops here: the module loaded, so the import is good.
        # What it declares is what the build would need.
        problems: list[str] = []
        if not isinstance(params, dict):
            problems.append("the module does not define PARAMS as a dict")
        if not isinstance(bodies, dict):
            problems.append("the module does not define BODIES as a dict")
        else:
            expected = [b["name"] for b in spec["bodies"]]
            missing = [name for name in expected if name not in bodies]
            if missing:
                problems.append(f"BODIES is missing {missing}")
        result["dry_run"] = True
        result["problems"] = problems
        result["ok"] = not problems
        pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1

    if not isinstance(bodies, dict):
        result["error"] = "the module does not define BODIES as a dict"
        pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
        return 1

    expected = [b["name"] for b in spec["bodies"]]
    missing = [name for name in expected if name not in bodies]
    result["missing_bodies"] = missing
    if missing:
        result["error"] = f"BODIES is missing {missing}"

    measured: dict[str, dict] = {}
    for name in expected:
        if name not in bodies:
            continue
        shape = bodies[name]
        try:
            volume = float(shape.volume)
            area = float(shape.area)
            centre = shape.center()
            inertia = shape.matrix_of_inertia
            vertices, triangles = _tessellate(shape)
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"body {name!r} could not be measured: {type(exc).__name__}: {exc}"
            result["traceback"] = traceback.format_exc()
            pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
            return 1
        measured[name] = {
            "volume_mm3": volume,
            "area_mm2": area,
            "center_of_mass_mm": [centre.X, centre.Y, centre.Z],
            "mass_kg": volume * density_scale,
            "inertia_kg_mm2": [
                [inertia[r][c] * density_scale for c in range(3)] for r in range(3)
            ],
            # The non-degeneracy facts the sweep's validity rule needs: the
            # shape has to be a valid solid with a positive volume.
            "is_valid": bool(shape.is_valid),
            "solids": len(shape.solids()),
            "vertices": vertices,
            "triangles": triangles,
        }

    result["bodies"] = {
        name: {k: v for k, v in data.items() if k not in ("vertices", "triangles")}
        for name, data in measured.items()
    }
    result["meshes"] = {
        name: {"vertices": data["vertices"], "triangles": data["triangles"]}
        for name, data in measured.items()
    }
    try:
        export_step(Compound(list(bodies.values())), str(workdir / "prop_from_bodies.step"))
        result["step_written"] = True
    except Exception as exc:  # noqa: BLE001
        result["step_written"] = False
        result["step_error"] = f"{type(exc).__name__}: {exc}"

    result["ok"] = True
    pathlib.Path(args.out).write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
