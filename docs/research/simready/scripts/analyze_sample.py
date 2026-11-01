"""Read every asset in the sample: its schema, and its glTF conversion time.

One pass over the sample. For each package it opens the stage, reads the
schema (units, semantics, physics, colliders, materials, LOD, bounds) and
then writes a GLB, timing the conversion.

The output is one JSON file, so the priors and the timings can be read from
the same measurement rather than from two.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simready_loader import asset_dirs, convert_asset, load_stage, read_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="the directory holding the packages")
    parser.add_argument("--out", help="where to write the report JSON")
    parser.add_argument("--glb-dir", help="where to write the GLB files")
    args = parser.parse_args()

    rows = []
    for asset in asset_dirs(args.root):
        started = time.perf_counter()
        record = {"asset": asset.name}
        try:
            stage = load_stage(asset)
            schema = read_schema(stage, asset.name)
            record["schema"] = asdict(schema)
            record["open_seconds"] = round(time.perf_counter() - started, 3)
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            record["open_seconds"] = round(time.perf_counter() - started, 3)
            print(f"{asset.name}: {record['error']}", file=sys.stderr)
            rows.append(record)
            continue

        if args.glb_dir:
            try:
                stats = convert_asset(asset, Path(args.glb_dir) / f"{asset.name}.glb")
                record["glb"] = asdict(stats)
            except Exception as error:
                record["glb_error"] = f"{type(error).__name__}: {error}"
                print(f"{asset.name}: glb {record['glb_error']}", file=sys.stderr)
        rows.append(record)
        print(
            f"{asset.name}: {record['schema']['meshes']} meshes, "
            f"{record['schema']['triangles']} tris, "
            f"{record['schema'].get('mass_kg_total')} kg, "
            f"{record['schema'].get('size_m')} m",
            flush=True,
        )

    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
