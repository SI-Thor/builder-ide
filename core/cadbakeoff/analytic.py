"""The analytic ground truth for the prop specs.

This module computes volume, surface area and centre of mass straight from the
spec's cell list, with closed-form formulas. It never touches SolidCraft or
OCCT, so it is an independent reference: the two kernels can agree with each
other and both be wrong, and this is what says which one is wrong (Hy4
guard 3).

It also enforces the two rules the specs rely on:

* the cells inside one body must not overlap in volume;
* every face two cells share must be listed in the body's ``interfaces``, so
  the surface area can subtract the hidden area twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from core.cadbakeoff.specs import expr

__all__ = [
    "Cell",
    "BodyMass",
    "MassProps",
    "evaluate_body",
    "evaluate_prop",
    "overlap_report",
]


@dataclass(frozen=True)
class Cell:
    """One closed solid, already evaluated against a parameter set."""

    label: str
    kind: str
    volume: float  # mm^3
    area: float  # mm^2
    centre: tuple[float, float, float]  # mm
    aabb: tuple[float, float, float, float, float, float]
    contains: Any  # callable(point) -> bool

    @property
    def bbox(self) -> tuple[float, float, float, float, float, float]:
        return self.aabb


@dataclass(frozen=True)
class BodyMass:
    name: str
    role: str
    volume: float
    area: float
    centre: tuple[float, float, float]
    mass_kg: float


@dataclass(frozen=True)
class MassProps:
    """Mass properties for one prop at one parameter set."""

    prop: str
    params: dict[str, float]
    bodies: list[BodyMass]
    volume: float
    area: float
    centre: tuple[float, float, float]
    mass_kg: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "prop": self.prop,
            "params": dict(self.params),
            "volume_mm3": self.volume,
            "area_mm2": self.area,
            "center_of_mass_mm": list(self.centre),
            "mass_kg": self.mass_kg,
            "bodies": [
                {
                    "name": b.name,
                    "role": b.role,
                    "volume_mm3": b.volume,
                    "area_mm2": b.area,
                    "center_of_mass_mm": list(b.centre),
                    "mass_kg": b.mass_kg,
                }
                for b in self.bodies
            ],
        }


# ---------------------------------------------------------------------------
# cell geometry
# ---------------------------------------------------------------------------


def _box_cell(label: str, x, y, z, params: dict[str, float]) -> Cell:
    x0, x1 = expr(x[0], params), expr(x[1], params)
    y0, y1 = expr(y[0], params), expr(y[1], params)
    z0, z1 = expr(z[0], params), expr(z[1], params)
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    if min(dx, dy, dz) <= 0:
        raise ValueError(f"{label}: box has a non-positive extent")
    volume = dx * dy * dz
    area = 2.0 * (dx * dy + dx * dz + dy * dz)
    centre = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)

    def contains(p, x0=x0, x1=x1, y0=y0, y1=y1, z0=z0, z1=z1):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and z0 <= p[2] <= z1

    return Cell(label, "box", volume, area, centre, (x0, y0, z0, x1, y1, z1), contains)


def _cyl_cell(label: str, axis: str, centre, r_text: str, length_text: str, params) -> Cell:
    cx, cy, cz = (expr(v, params) for v in centre)
    r = expr(r_text, params)
    length = expr(length_text, params)
    if r <= 0 or length <= 0:
        raise ValueError(f"{label}: cylinder has a non-positive radius or length")
    volume = math.pi * r * r * length
    area = 2.0 * math.pi * r * r + 2.0 * math.pi * r * length
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    centre_pt = [cx, cy, cz]
    half = [0.0, 0.0, 0.0]
    half[idx] = length / 2.0
    aabb = (
        cx - half[0] - (r if idx != 0 else 0.0),
        cy - half[1] - (r if idx != 1 else 0.0),
        cz - half[2] - (r if idx != 2 else 0.0),
        cx + half[0] + (r if idx != 0 else 0.0),
        cy + half[1] + (r if idx != 1 else 0.0),
        cz + half[2] + (r if idx != 2 else 0.0),
    )

    def contains(p, axis=axis, idx=idx, r=r, length=length, cx=cx, cy=cy, cz=cz):
        radial = math.hypot(p[0] - cx, p[1] - cy) if idx == 2 else (
            math.hypot(p[1] - cy, p[2] - cz) if idx == 0 else math.hypot(p[0] - cx, p[2] - cz)
        )
        if radial > r:
            return False
        axis_pos = p[idx] - (cx if idx == 0 else cy if idx == 1 else cz)
        return -length / 2.0 <= axis_pos <= length / 2.0

    return Cell(label, "cyl", volume, area, (cx, cy, cz), aabb, contains)


def _tube_cell(label: str, axis: str, centre, r_out_text: str, r_in_text: str, length_text: str, params) -> Cell:
    cx, cy, cz = (expr(v, params) for v in centre)
    r_out = expr(r_out_text, params)
    r_in = expr(r_in_text, params)
    length = expr(length_text, params)
    if not (0 < r_in < r_out) or length <= 0:
        raise ValueError(f"{label}: tube needs 0 < r_inner < r_outer and a positive length")
    volume = math.pi * (r_out * r_out - r_in * r_in) * length
    area = (
        2.0 * math.pi * r_out * length
        + 2.0 * math.pi * r_in * length
        + 2.0 * math.pi * (r_out * r_out - r_in * r_in)
    )
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    centre_pt = (cx, cy, cz)
    half = [0.0, 0.0, 0.0]
    half[idx] = length / 2.0
    aabb = (
        cx - half[0] - (r_out if idx != 0 else 0.0),
        cy - half[1] - (r_out if idx != 1 else 0.0),
        cz - half[2] - (r_out if idx != 2 else 0.0),
        cx + half[0] + (r_out if idx != 0 else 0.0),
        cy + half[1] + (r_out if idx != 1 else 0.0),
        cz + half[2] + (r_out if idx != 2 else 0.0),
    )

    def contains(p, axis=axis, idx=idx, r_out=r_out, r_in=r_in, length=length, cx=cx, cy=cy, cz=cz):
        if idx == 2:
            radial = math.hypot(p[0] - cx, p[1] - cy)
        elif idx == 0:
            radial = math.hypot(p[1] - cy, p[2] - cz)
        else:
            radial = math.hypot(p[0] - cx, p[2] - cz)
        if not (r_in <= radial <= r_out):
            return False
        axis_pos = p[idx] - (cx if idx == 0 else cy if idx == 1 else cz)
        return -length / 2.0 <= axis_pos <= length / 2.0

    return Cell(label, "tube", volume, area, centre_pt, aabb, contains)


def _half_cyl_cell(label: str, axis: str, dome_dir: str, centre, r_text: str, length_text: str, params) -> Cell:
    cx, cy, cz = (expr(v, params) for v in centre)
    r = expr(r_text, params)
    length = expr(length_text, params)
    if r <= 0 or length <= 0:
        raise ValueError(f"{label}: half cylinder has a non-positive radius or length")
    volume = 0.5 * math.pi * r * r * length
    area = math.pi * r * length + 2.0 * r * length + math.pi * r * r
    axis_idx = {"x": 0, "y": 1, "z": 2}[axis]
    dome_idx = {"x": 0, "y": 1, "z": 2}[dome_dir]
    centre_pt = [cx, cy, cz]
    # The half-disc's centroid sits 4r/3pi from the flat face, towards the dome.
    centre_pt[dome_idx] += 4.0 * r / (3.0 * math.pi)
    half = [0.0, 0.0, 0.0]
    half[axis_idx] = length / 2.0
    # The bounding box follows the same shape as ``contains``: along the
    # cylinder's axis the half-cylinder is ``length`` long, in the dome's
    # direction it rises ``r`` above the flat face at the centre, and in the
    # third direction it is ``r`` either side of the axis.
    lo = [0.0, 0.0, 0.0]
    hi = [0.0, 0.0, 0.0]
    base = [cx, cy, cz]
    for i in range(3):
        if i == axis_idx:
            lo[i] = base[i] - half[i]
            hi[i] = base[i] + half[i]
        elif i == dome_idx:
            lo[i] = base[i]
            hi[i] = base[i] + r
        else:
            lo[i] = base[i] - r
            hi[i] = base[i] + r
    aabb = (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])

    def contains(p, axis_idx=axis_idx, dome_idx=dome_idx, r=r, length=length,
                 cx=cx, cy=cy, cz=cz, centre_pt=centre_pt):
        base = [cx, cy, cz]
        axis_pos = p[axis_idx] - base[axis_idx]
        if not (-length / 2.0 <= axis_pos <= length / 2.0):
            return False
        # The radial plane of the cut contains the axis and is perpendicular to dome_dir.
        radial_sq = 0.0
        for i in range(3):
            if i in (axis_idx, dome_idx):
                continue
            d = p[i] - base[i]
            radial_sq += d * d
        if radial_sq > r * r:
            return False
        dome_pos = p[dome_idx] - base[dome_idx]
        return dome_pos >= 0.0

    return Cell(label, "half_cyl", volume, area, (centre_pt[0], centre_pt[1], centre_pt[2]), aabb, contains)


def build_cell(raw: dict[str, Any], params: dict[str, float]) -> Cell:
    kind = raw["kind"]
    label = raw["label"]
    if kind == "box":
        return _box_cell(label, raw["x"], raw["y"], raw["z"], params)
    if kind == "cyl":
        return _cyl_cell(label, raw["axis"], raw["center"], raw["r"], raw["length"], params)
    if kind == "tube":
        return _tube_cell(label, raw["axis"], raw["center"], raw["r_outer"], raw["r_inner"], raw["length"], params)
    if kind == "half_cyl":
        return _half_cyl_cell(label, raw["axis"], raw["dome_dir"], raw["center"], raw["r"], raw["length"], params)
    raise ValueError(f"{label}: unknown cell kind {kind!r}")


# ---------------------------------------------------------------------------
# overlap detection
# ---------------------------------------------------------------------------


def _intersection_box(a: Cell, b: Cell):
    lo = [max(a.aabb[0], b.aabb[0]), max(a.aabb[1], b.aabb[1]), max(a.aabb[2], b.aabb[2])]
    hi = [min(a.aabb[3], b.aabb[3]), min(a.aabb[4], b.aabb[4]), min(a.aabb[5], b.aabb[5])]
    if any(hi[i] <= lo[i] for i in range(3)):
        return None
    return lo, hi


def _overlap_volume(a: Cell, b: Cell, step: float = 1.5) -> float:
    """Estimate the volume two cells share, in mm^3.

    Box-box pairs are exact. Everything else is a grid over the intersection of
    the two bounding boxes, fine enough to notice a millimetre-scale overlap.
    """
    box = _intersection_box(a, b)
    if box is None:
        return 0.0
    lo, hi = box
    if a.kind == "box" and b.kind == "box":
        return (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
    span = [hi[i] - lo[i] for i in range(3)]
    steps = [max(2, int(span[i] / step) + 1) for i in range(3)]
    total = steps[0] * steps[1] * steps[2]
    if total > 4_000_000:  # keep the grid affordable
        scale = (4_000_000 / total) ** (1 / 3)
        for i in range(3):
            steps[i] = max(2, int(steps[i] * scale))
        span = [span[i] * (steps[i] - 1) / (steps[i] - 1) for i in range(3)]
    dx = span[0] / (steps[0] - 1) if steps[0] > 1 else 0.0
    dy = span[1] / (steps[1] - 1) if steps[1] > 1 else 0.0
    dz = span[2] / (steps[2] - 1) if steps[2] > 1 else 0.0
    cell_vol = max(dx * dy * dz, 1e-9)
    hits = 0
    for i in range(steps[0]):
        px = lo[0] + i * dx
        for j in range(steps[1]):
            py = lo[1] + j * dy
            for k in range(steps[2]):
                pz = lo[2] + k * dz
                if a.contains((px, py, pz)) and b.contains((px, py, pz)):
                    hits += 1
    return hits * cell_vol


def overlap_report(cells: list[Cell]) -> list[dict[str, Any]]:
    """Every pair of cells in one body that shares volume."""
    out: list[dict[str, Any]] = []
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            a, b = cells[i], cells[j]
            v = _overlap_volume(a, b)
            if v > 1.0:  # one cubic millimetre of slop
                out.append({"a": a.label, "b": b.label, "overlap_mm3": v})
    return out


# ---------------------------------------------------------------------------
# the exact area and volume of a union of axis-aligned boxes
# ---------------------------------------------------------------------------


def _as_box(aabb: tuple[float, ...]) -> tuple[float, ...]:
    """``(x0, y0, z0, x1, y1, z1)`` to the ``(x0, x1, y0, y1, z0, z1)`` layout."""
    return (aabb[0], aabb[3], aabb[1], aabb[4], aabb[2], aabb[5])


def _rect_union_area(rects: list[tuple[float, float, float, float]]) -> float:
    """The area covered by a set of axis-aligned rectangles in a plane."""
    rects = [r for r in rects if r[1] > r[0] and r[3] > r[2]]
    if not rects:
        return 0.0
    xs = sorted({x for r in rects for x in (r[0], r[1])})
    ys = sorted({y for r in rects for y in (r[2], r[3])})
    total = 0.0
    for i in range(len(xs) - 1):
        cx = (xs[i] + xs[i + 1]) / 2.0
        for j in range(len(ys) - 1):
            cy = (ys[j] + ys[j + 1]) / 2.0
            for r in rects:
                if r[0] <= cx <= r[1] and r[2] <= cy <= r[3]:
                    total += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
                    break
    return total


def union_volume_boxes(boxes: list[tuple[float, ...]]) -> float:
    """The volume of the union of axis-aligned boxes, by coordinate compression.

    A box is ``(x0, y0, z0, x1, y1, z1)``, the same layout the cells use.
    """
    xs = sorted({v for b in boxes for v in (b[0], b[3])})
    ys = sorted({v for b in boxes for v in (b[1], b[4])})
    zs = sorted({v for b in boxes for v in (b[2], b[5])})
    total = 0.0
    for i in range(len(xs) - 1):
        cx = (xs[i] + xs[i + 1]) / 2.0
        for j in range(len(ys) - 1):
            cy = (ys[j] + ys[j + 1]) / 2.0
            for k in range(len(zs) - 1):
                cz = (zs[k] + zs[k + 1]) / 2.0
                for b in boxes:
                    if b[0] <= cx <= b[3] and b[1] <= cy <= b[4] and b[2] <= cz <= b[5]:
                        total += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]) * (zs[k + 1] - zs[k])
                        break
    return total


def union_area_boxes(boxes: list[tuple[float, ...]]) -> float:
    """The surface area of the union of axis-aligned boxes.

    A face of a box is counted, minus the part of it that lies inside another
    box, minus twice the part that is coincident with another box's face: a
    coincident face is interior to the union and both boxes counted it.

    This matters for the props: a crate's front wall and its left wall meet
    along a face that is interior to the crate, and a hand-written interface
    list that misses one of those meetings is wrong by a few square
    millimetres per meeting.

    A box is ``(x0, y0, z0, x1, y1, z1)``, the same layout the cells use.
    """
    total = 0.0
    for i, b in enumerate(boxes):
        for axis in range(3):
            u, v = [a for a in range(3) if a != axis]
            for side, plane in ((0, b[axis]), (1, b[axis + 3])):
                rect = (b[u], b[u + 3], b[v], b[v + 3])
                spanning: list[tuple[float, float, float, float]] = []
                coincident: list[tuple[float, float, float, float]] = []
                for j, c in enumerate(boxes):
                    if i == j:
                        continue
                    if c[axis] < plane < c[axis + 3]:
                        bucket = spanning
                    elif (side == 1 and abs(c[axis] - plane) < 1e-9) or (
                        side == 0 and abs(c[axis + 3] - plane) < 1e-9
                    ):
                        bucket = coincident
                    else:
                        continue
                    inter = (
                        max(rect[0], c[u]),
                        min(rect[1], c[u + 3]),
                        max(rect[2], c[v]),
                        min(rect[3], c[v + 3]),
                    )
                    if inter[1] <= inter[0] or inter[3] <= inter[2]:
                        continue
                    bucket.append(inter)
                face_area = (rect[1] - rect[0]) * (rect[3] - rect[2])
                # A region covered by another box is interior to the union: it
                # is counted once by this face and must not be counted at all.
                # A coincident face is counted by both boxes, so each of the
                # two loses it once and the region is counted zero times.
                covered = _rect_union_area(spanning + coincident)
                total += face_area - covered
    return total


# ---------------------------------------------------------------------------
# body and prop
# ---------------------------------------------------------------------------


def evaluate_body(raw_body: dict[str, Any], params: dict[str, float]) -> tuple[BodyMass, list[Cell]]:
    cells = [build_cell(c, params) for c in raw_body["cells"]]
    volume = sum(c.volume for c in cells)
    if all(c.kind == "box" for c in cells):
        # Boxes are unioned exactly, so the area is the union's area and not
        # the cells' areas minus a hand-written list of the faces they share.
        boxes = [c.aabb for c in cells]
        area = union_area_boxes(boxes)
        volume = union_volume_boxes(boxes)
    else:
        area = sum(c.area for c in cells)
        for a_label, b_label, area_expr in raw_body.get("interfaces", []):
            area -= 2.0 * expr(area_expr, params)
    moments = [tuple(c.volume * v for v in c.centre) for c in cells]
    centre = tuple(sum(m[i] for m in moments) / volume for i in range(3))
    density = params["__density__"] / 1.0e9  # kg/mm^3
    body = BodyMass(
        name=raw_body["name"],
        role=raw_body["role"],
        volume=volume,
        area=area,
        centre=centre,  # type: ignore[arg-type]
        mass_kg=volume * density,
    )
    return body, cells


def evaluate_prop(spec: dict[str, Any], overrides: dict[str, float] | None = None) -> MassProps:
    """Evaluate a spec at one parameter set."""
    params = dict(spec["parameters"])
    params.update(overrides or {})
    params["__density__"] = spec["density_kg_m3"]
    bodies: list[BodyMass] = []
    for raw_body in spec["bodies"]:
        body, _cells = evaluate_body(raw_body, params)
        bodies.append(body)
    volume = sum(b.volume for b in bodies)
    area = sum(b.area for b in bodies)
    moments = [tuple(b.volume * v for v in b.centre) for b in bodies]
    centre = tuple(sum(m[i] for m in moments) / volume for i in range(3))
    mass = sum(b.mass_kg for b in bodies)
    return MassProps(
        prop=spec["prop"],
        params={k: v for k, v in params.items() if not k.startswith("__")},
        bodies=bodies,
        volume=volume,
        area=area,
        centre=centre,  # type: ignore[arg-type]
        mass_kg=mass,
    )
