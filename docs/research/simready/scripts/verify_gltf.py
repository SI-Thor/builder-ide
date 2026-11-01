"""Check every converted GLB against the USD it came from.

Two independent reads of the same fact. The USD side is the loader's own
schema pass; the GLB side is **builder-ide's** reader
(``core.genbatch.glb.read_glb``), not this survey's, so the check is not
the writer agreeing with itself.

For each asset the bounding box of the first primitive is compared with the
world-space bounds the USD reported, and the triangle count is compared with
the USD's. A GLB that opens, has no NaN in its positions, and carries the
same box as its source has survived the conversion.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

#: builder-ide's reader, from the repository.
BUILDER_IDE = Path("/home/caseydigennaro/src/builder-ide")

#: glTF component types, for the independent reader below.
_FLOAT = 5126
_UINT32 = 5125
_VEC3 = 3


def read_glb_union(path: Path) -> tuple[list[float], list[float], int]:
    """The union box over every primitive in a GLB, read directly.

    This is a second, independent read of the file: it does not use the
    survey's writer and it does not use builder-ide's reader, so it agrees
    with the writer only if the file is right. builder-ide's reader opens
    the **first** primitive only (TRELLIS.2 writes one mesh, and that is
    the one the critic measures), so the union is checked separately.
    """
    import struct

    data = path.read_bytes()
    length = struct.unpack("<I", data[8:12])[0]
    offset = 12
    document: dict | None = None
    binary = b""
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack("<II", data[offset : offset + 8])
        body = data[offset + 8 : offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A and document is None:
            document = json.loads(body.decode("utf-8").rstrip("\x00 \t\r\n"))
        elif chunk_type == 0x004E4942:
            binary = body
        offset += 8 + chunk_length
    if document is None:
        raise ValueError("no JSON chunk")

    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []
    low = np.array([np.inf] * 3)
    high = np.array([-np.inf] * 3)
    triangles = 0
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            attributes = primitive.get("attributes") or {}
            index = attributes.get("POSITION")
            if index is None:
                continue
            accessor = accessors[index]
            view = views[accessor["bufferView"]]
            start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
            count = int(accessor["count"])
            positions = np.frombuffer(binary, dtype=np.float32, count=count * 3, offset=start)
            positions = positions.reshape(count, 3).astype(np.float64)
            low = np.minimum(low, positions.min(axis=0))
            high = np.maximum(high, positions.max(axis=0))
            indices = primitive.get("indices")
            if indices is not None:
                triangles += int(accessors[indices]["count"]) // 3
    if not np.isfinite(low).all():
        raise ValueError("no positioned geometry")
    return [float(v) for v in low], [float(v) for v in high], triangles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="the sample report JSON")
    parser.add_argument("--glb-dir", required=True, help="where the GLBs are")
    parser.add_argument("--out", help="where to write the verification JSON")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-3,
        help="the allowed box mismatch, in metres",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(BUILDER_IDE))
    from core.genbatch.glb import read_glb  # noqa: E402

    rows = json.loads(Path(args.report).read_text())
    results = []
    failures = 0
    for row in rows:
        asset = row["asset"]
        schema = row.get("schema")
        glb_path = Path(args.glb_dir) / f"{asset}.glb"
        record: dict = {"asset": asset, "opened": False}
        if not glb_path.exists():
            record["error"] = "no GLB"
            failures += 1
            results.append(record)
            continue
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                glb = read_glb(glb_path)
                mesh = glb.mesh
            record["opened"] = True
            record["warnings"] = [str(item.message) for item in caught]
            positions = np.asarray(mesh.positions, dtype=np.float64)
            record["vertices"] = int(mesh.vertices)
            record["triangles"] = int(mesh.triangles)
            record["nan_positions"] = bool(np.isnan(positions).any())
            record["bbox_min"] = [float(v) for v in positions.min(axis=0)]
            record["bbox_max"] = [float(v) for v in positions.max(axis=0)]
            record["generator"] = glb.generator
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            failures += 1
            results.append(record)
            continue

        if schema and schema.get("bbox_min"):
            # builder-ide's reader opens the first primitive, so it is
            # compared with the USD's first mesh, not with the whole asset.
            boxes = schema.get("mesh_boxes") or []
            if boxes:
                source_low = np.asarray(boxes[0]["bbox_min"], dtype=np.float64)
                source_high = np.asarray(boxes[0]["bbox_max"], dtype=np.float64)
                source_triangles = boxes[0]["triangles"]
            else:
                source_low = np.asarray(schema["bbox_min"], dtype=np.float64)
                source_high = np.asarray(schema["bbox_max"], dtype=np.float64)
                source_triangles = schema["triangles"]
            got_low = np.asarray(record["bbox_min"], dtype=np.float64)
            got_high = np.asarray(record["bbox_max"], dtype=np.float64)
            record["box_error_m"] = float(
                max(
                    np.abs(got_low - source_low).max(),
                    np.abs(got_high - source_high).max(),
                )
            )
            record["triangle_delta"] = int(mesh.triangles - source_triangles)

            # The independent union read: every primitive, against the
            # whole asset.
            union_low, union_high, union_triangles = read_glb_union(glb_path)
            union_source_low = np.asarray(schema["bbox_min"], dtype=np.float64)
            union_source_high = np.asarray(schema["bbox_max"], dtype=np.float64)
            record["union_box_error_m"] = float(
                max(
                    np.abs(np.asarray(union_low) - union_source_low).max(),
                    np.abs(np.asarray(union_high) - union_source_high).max(),
                )
            )
            record["union_triangle_delta"] = int(union_triangles - schema["triangles"])

            ok = (
                record["box_error_m"] <= args.tolerance
                and record["union_box_error_m"] <= args.tolerance
                and not record["nan_positions"]
                and not record["warnings"]
                and abs(record["triangle_delta"]) <= max(4, int(0.001 * source_triangles))
                and abs(record["union_triangle_delta"]) <= max(
                    4, int(0.001 * schema["triangles"])
                )
            )
            record["ok"] = bool(ok)
            if not ok:
                failures += 1
        results.append(record)

    summary = {
        "assets": len(results),
        "opened": sum(1 for r in results if r.get("opened")),
        "ok": sum(1 for r in results if r.get("ok")),
        "failures": failures,
        "max_box_error_m": max(
            (r.get("box_error_m", 0.0) for r in results), default=0.0
        ),
        "max_union_box_error_m": max(
            (r.get("union_box_error_m", 0.0) for r in results), default=0.0
        ),
        "tolerance_m": args.tolerance,
        "reader": "builder-ide core.genbatch.glb.read_glb",
    }
    print(json.dumps(summary, indent=2))
    for record in results:
        if not record.get("ok"):
            print("  FAIL", record["asset"], record.get("error", ""), record.get("box_error_m", ""), record.get("warnings", ""))
    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "assets": results}, indent=2) + "\n"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
