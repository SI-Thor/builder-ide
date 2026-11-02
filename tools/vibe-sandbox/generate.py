"""The room generator: a spec JSON -> build123d parts (one STL per named
object) + scene.json (the authoritative collision/manifest model).

The spec is the room's *recipe* (the repo's rule: store recipes, not meshes).
Everything downstream — Blender assembly, the critic's probe, the viewer's
collision model, the playtest — reads scene.json, so the QA agent and the
critic judge the same numbers the mesh was built from.

Coordinates are metres, Blender frame (z up, origin at a floor corner), the
room interior exactly [0, W] x [0, D]. Walls sit outside the interior so the
walkable area is exactly the spec's room. Room shell objects are named
``Terrain.*`` so the critic treats them as infrastructure, not props.

Repairs (the gate's retry path): ``--qa``/``--critic`` name the previous
attempt's reports; findings are turned back into spec edits deterministically
(no model in the loop), and every edit is written to ``repair_log.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from build123d import Box, Compound, Cylinder, Pos, export_stl

WALL_T = 0.2
DOOR_TOP = 2.1  # lintel above the door gap


def _shell(room: dict) -> list[tuple[str, object]]:
    """Floor + four walls + the door's lintel. The door gap is a hole in the
    north wall (y=0); the staging strip outside it is where the playtest
    spawns."""
    w, d, h = room["width"], room["depth"], room["height"]
    door = room.get("door", {"wall": "north", "offset": w / 2 - 0.7, "width": 1.4})
    dx, dw = float(door["offset"]), float(door["width"])
    parts: list[tuple[str, object]] = [
        ("Terrain.floor", Pos(w / 2, d / 2, -0.1) * Box(w + 2 * WALL_T, d + 2 * WALL_T, 0.2))
    ]
    # north wall (y=0), split around the door gap, plus the lintel
    if dx > 0:
        parts.append(
            (
                "Terrain.wall_n_west",
                Pos(-WALL_T / 2 + dx / 2 - 0, WALL_T / 2 - WALL_T, h / 2)
                * Box(dx + WALL_T, WALL_T, h),
            )
        )
    parts.append(
        (
            "Terrain.wall_n_east",
            Pos(dx + dw + (w - dx - dw + WALL_T) / 2, WALL_T / 2 - WALL_T, h / 2)
            * Box(w - dx - dw + WALL_T, WALL_T, h),
        )
    )
    parts.append(
        (
            "Terrain.lintel",
            Pos(dx + dw / 2, WALL_T / 2 - WALL_T, (h + DOOR_TOP) / 2)
            * Box(dw, WALL_T, h - DOOR_TOP),
        )
    )
    parts += [
        (
            "Terrain.wall_s",
            Pos(w / 2, d + WALL_T / 2, h / 2) * Box(w + 2 * WALL_T, WALL_T, h),
        ),
        (
            "Terrain.wall_w",
            Pos(-WALL_T / 2, d / 2, h / 2) * Box(WALL_T, d, h),
        ),
        (
            "Terrain.wall_e",
            Pos(w + WALL_T / 2, d / 2, h / 2) * Box(WALL_T, d, h),
        ),
    ]
    for i, seg in enumerate(room.get("interior_walls", [])):
        x0, y0 = float(seg["x0"]), float(seg["y0"])
        x1, y1 = float(seg["x1"]), float(seg["y1"])
        if x0 == x1:  # vertical segment
            cx, cw, cd = x0, WALL_T, abs(y1 - y0)
            cy = (y0 + y1) / 2
        else:
            cy, cw, cd = y0, abs(x1 - x0), WALL_T
            cx = (x0 + x1) / 2
        parts.append((f"Terrain.iwall_{i}", Pos(cx, cy, h / 2) * Box(cw, cd, h)))
    return parts


def _prop(p: dict) -> tuple[object, dict]:
    """One prop: its build123d shape (positioned in world) and its bbox."""
    kind = p["kind"]
    x, y, z = float(p["x"]), float(p["y"]), float(p.get("z", 0.0))
    if kind == "crate":
        w, d, h = float(p["w"]), float(p["d"]), float(p["h"])
        shape = Pos(x, y, z + h / 2) * Box(w, d, h)
    elif kind == "barrel":
        r, h = float(p["r"]), float(p["h"])
        w = d = 2 * r
        shape = Pos(x, y, z + h / 2) * Cylinder(radius=r, height=h)
    elif kind == "table":
        w, d, h = float(p["w"]), float(p["d"]), float(p["h"])
        top_t, leg_r = 0.08, 0.04
        # legs run the full height and are *unioned* into the top: a compound
        # of merely touching solids is not one manifold, and Open3D's
        # self-intersection check (rightly) flags touching shells
        shape = Pos(x, y, z + h - top_t / 2) * Box(w, d, top_t)
        for sx in (-1, 1):
            for sy in (-1, 1):
                shape = shape + (
                    Pos(
                        x + sx * (w / 2 - leg_r - 0.03),
                        y + sy * (d / 2 - leg_r - 0.03),
                        z + h / 2,
                    )
                    * Cylinder(radius=leg_r, height=h)
                )
    elif kind == "twin":
        # Two overlapping solids in one object, deliberately *not* unioned:
        # a closed, watertight mesh whose shells pass through each other —
        # the defect only Open3D's self-intersection test can see.
        w, d, h = float(p["w"]), float(p["d"]), float(p["h"])
        ov = float(p.get("overlap", 0.3))
        shape = Compound(
            children=[
                Pos(x, y, z + h / 2) * Box(w, d, h),
                Pos(x + ov, y + ov, z + h / 2 + 0.6 * h) * Box(w, d, h),
            ]
        )
        w = d = w + ov
        h = h + 0.6 * h
    else:
        raise ValueError(f"unknown prop kind {kind!r}")
    bbox = {
        "name": p["name"],
        "kind": kind,
        "x0": x - w / 2, "x1": x + w / 2,
        "y0": y - d / 2, "y1": y + d / 2,
        "z0": z, "z1": z + h,
    }
    return shape, bbox


def build(spec: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(exist_ok=True)
    for stale in parts_dir.glob("*.stl"):
        stale.unlink()

    room = spec["room"]
    parts = _shell(room)
    prop_boxes = []
    for p in spec.get("props", []):
        shape, bbox = _prop(p)
        parts.append((p["name"], shape))
        prop_boxes.append(bbox)

    for name, shape in parts:
        export_stl(shape, str(parts_dir / f"{name}.stl"))

    scene = {
        "room_id": spec["room_id"],
        "frame": "blender-z-up-metres",
        "room": {
            "width": room["width"],
            "depth": room["depth"],
            "height": room["height"],
            "door": room.get("door", {"wall": "north", "offset": room["width"] / 2 - 0.7, "width": 1.4}),
            "interior_walls": room.get("interior_walls", []),
        },
        "props": prop_boxes,
        "shell": [n for n, _ in parts if n.startswith("Terrain.")],
    }
    (out_dir / "scene.json").write_text(json.dumps(scene, indent=1, sort_keys=True))
    return scene


# -- the retry path: findings become spec edits -------------------------------


def _family_median(spec: dict, kind: str, skip: str) -> float:
    diag = []
    for p in spec.get("props", []):
        if p["kind"] != kind or p["name"] == skip:
            continue
        dims = [p.get(k, 0) for k in ("w", "d", "h", "r")]
        dims = [d for d in dims if d]
        if len(dims) >= 3:
            diag.append((dims[0] ** 2 + dims[1] ** 2 + dims[2] ** 2) ** 0.5)
    diag.sort()
    return diag[len(diag) // 2] if diag else 1.0


def repair(spec: dict, qa: dict | None, critic: dict | None) -> tuple[dict, list[dict]]:
    """Deterministic repairs from the previous attempt's findings.

    Repairable findings are the QA's placement ones plus the critic's
    scale_bounds; anything else (self-intersection, sealed pockets) is left
    alone — v1 has no fix for them, and the gate reports that honestly
    instead of retrying into the same wall.
    """
    log: list[dict] = []
    by_name = {p["name"]: p for p in spec.get("props", [])}
    room = spec["room"]
    findings = []
    for report in (qa, critic):
        if report:
            findings += report.get("findings", [])

    def bbox_of(p: dict) -> tuple[float, float, float, float]:
        w = p.get("w") or 2 * p.get("r", 0)
        d = p.get("d") or 2 * p.get("r", 0)
        return p["x"] - w / 2, p["x"] + w / 2, p["y"] - d / 2, p["y"] + d / 2

    for f in findings:
        p = by_name.get(f.get("name", ""))
        if p is None and f["kind"] in ("blocked_door", "collision_trap"):
            # a blocked door is a room-level finding with no name; the
            # culprit is whatever prop stands in the door strip — infer it
            # from the spec's own geometry rather than guessing
            door = room.get("door", {"offset": room["width"] / 2 - 0.7, "width": 1.4})
            dx, dw = float(door["offset"]), float(door["width"])
            for cand in spec.get("props", []):
                x0, x1, y0, y1 = bbox_of(cand)
                if x1 > dx - 0.1 and x0 < dx + dw + 0.1 and y1 > -0.5 and y0 < 1.0:
                    p = cand
                    break
        if p is None:
            continue
        if f["kind"] == "floating_object":
            log.append({"prop": p["name"], "fix": "snap_to_floor", "was_z": p.get("z", 0)})
            p["z"] = 0.0
        elif f["kind"] in ("blocked_door", "collision_trap"):
            newy = max(p["y"], 1.9)
            log.append({"prop": p["name"], "fix": "clear_door_strip", "was_y": p["y"], "y": newy})
            p["y"] = newy
        elif f["kind"] == "prop_unreachable":
            cx, cy = room["width"] / 2, room["depth"] / 2
            newx = p["x"] + 0.4 * (cx - p["x"])
            newy = p["y"] + 0.4 * (cy - p["y"])
            log.append({"prop": p["name"], "fix": "move_toward_center", "x": newx, "y": newy})
            p["x"], p["y"] = newx, newy
        elif f["kind"] == "scale_bounds":
            med = _family_median(spec, p["kind"], p["name"])
            target = 1.5 * med / (p["w"] ** 2 + p["d"] ** 2 + p["h"] ** 2) ** 0.5
            log.append(
                {
                    "prop": p["name"],
                    "fix": "clamp_to_family",
                    "was_whd": [p["w"], p["d"], p["h"]],
                    "scale": round(target, 3),
                }
            )
            for k in ("w", "d", "h"):
                p[k] = round(p[k] * target, 3)
    return spec, log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, help="the room spec JSON")
    ap.add_argument("--out", required=True, help="attempt directory")
    ap.add_argument("--qa", help="previous attempt's qa_report.json")
    ap.add_argument("--critic", help="previous attempt's critic_report.json")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    repair_log: list[dict] = []
    if args.qa or args.critic:
        qa = json.loads(Path(args.qa).read_text()) if args.qa else None
        cr = json.loads(Path(args.critic).read_text()) if args.critic else None
        spec, repair_log = repair(spec, qa, cr)

    scene = build(spec, Path(args.out))
    (Path(args.out) / "spec.used.json").write_text(json.dumps(spec, indent=1, sort_keys=True))
    if repair_log:
        (Path(args.out) / "repair_log.json").write_text(json.dumps(repair_log, indent=1))
    print(
        json.dumps(
            {
                "room_id": spec["room_id"],
                "objects": len(scene["shell"]) + len(scene["props"]),
                "props": len(scene["props"]),
                "repairs": len(repair_log),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
