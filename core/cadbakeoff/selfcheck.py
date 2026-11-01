#!/usr/bin/env python3
"""Check the frozen specs: no cell overlaps, interfaces present, analytic numbers.

Run from the repository root:  python3 -m core.cadbakeoff.selfcheck
"""

from __future__ import annotations

import json
import sys

from core.cadbakeoff.analytic import build_cell, evaluate_prop, overlap_report
from core.cadbakeoff.specs import PROPS, PROP_NAMES


def main() -> int:
    problems: list[str] = []
    for name in PROP_NAMES:
        spec = PROPS[name]
        params = dict(spec["parameters"])
        params["__density__"] = spec["density_kg_m3"]
        for body in spec["bodies"]:
            cells = [build_cell(c, params) for c in body["cells"]]
            overlaps = overlap_report(cells)
            for o in overlaps:
                problems.append(
                    f"{name}/{body['name']}: cells {o['a']} and {o['b']} overlap "
                    f"by {o['overlap_mm3']:.1f} mm3"
                )
            # every touching pair must be declared as an interface
            declared = {(a, b) for a, b, _ in body.get("interfaces", [])}
            declared |= {(b, a) for a, b, _ in body.get("interfaces", [])}
            for i in range(len(cells)):
                for j in range(i + 1, len(cells)):
                    a, b = cells[i], cells[j]
                    if (a.label, b.label) in declared:
                        continue
                    # report a pair whose bounding boxes touch but which is not declared
                    gap = [
                        max(a.aabb[0] - b.aabb[3], b.aabb[0] - a.aabb[3]),
                        max(a.aabb[1] - b.aabb[4], b.aabb[1] - a.aabb[4]),
                        max(a.aabb[2] - b.aabb[5], b.aabb[2] - a.aabb[5]),
                    ]
                    if all(abs(g) < 1e-6 for g in gap):
                        problems.append(
                            f"{name}/{body['name']}: cells {a.label} and {b.label} touch "
                            "but the shared face is not declared in interfaces"
                        )
        mp = evaluate_prop(spec)
        print(
            f"{name:12s} V={mp.volume:14,.1f} mm3  A={mp.area:14,.1f} mm2  "
            f"CoM=({mp.centre[0]:9.3f},{mp.centre[1]:9.3f},{mp.centre[2]:9.3f})  "
            f"m={mp.mass_kg:8.3f} kg  bodies={len(mp.bodies)}"
        )
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(" -", p)
        return 1
    print("\nall specs ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
