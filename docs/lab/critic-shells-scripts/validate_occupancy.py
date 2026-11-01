"""Check the occupancy measures against shapes whose volume is known.

**The question.** The critic's ``fill_ratio`` has to measure *what the object
occupies*, not the material in its wall. The visual hull answers that by
construction — it is the intersection of the object's three axis-aligned
silhouettes — but a measure that is wrong on a shape with a known volume is
wrong everywhere.

So: a cube, a sphere, a **hollow mug** (a cup with a solid bottom and a
wall), a plate and an L-bracket. Each has an occupied volume that can be
written down, and each has a signed volume that differs from it by
construction. The measure that agrees with the known number is the one the
critic gets.

Usage::

    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/validate_occupancy.py
"""

from __future__ import annotations

import json
import math
import os
import platform
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.glb import Mesh
from core.genbatch.occupancy import occupied


def revolve(profile: list[tuple[float, float]], segments: int = 64) -> Mesh:
    """A surface of revolution: a closed profile in (radius, height)."""
    angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    ring = np.stack([np.cos(angles), np.sin(angles)], axis=1)

    positions: list[np.ndarray] = []
    for radius, height in profile:
        positions.append(
            np.stack(
                [
                    ring[:, 0] * radius,
                    ring[:, 1] * radius,
                    np.full(segments, height),
                ],
                axis=1,
            )
        )

    count = len(profile)
    indices: list[np.ndarray] = []
    for index in range(count):
        a = index * segments
        b = ((index + 1) % count) * segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            indices.append(
                np.array(
                    [
                        [a + segment, b + segment, b + nxt],
                        [a + segment, b + nxt, a + nxt],
                    ],
                    dtype=np.int64,
                )
            )

    return Mesh(
        positions=np.concatenate(positions, axis=0),
        indices=np.concatenate(indices, axis=0),
    )


def cube(side: float = 1.0) -> Mesh:
    half = side / 2.0
    positions = np.array(
        [
            [-half, -half, -half],
            [half, -half, -half],
            [half, half, -half],
            [-half, half, -half],
            [-half, -half, half],
            [half, -half, half],
            [half, half, half],
            [-half, half, half],
        ],
        dtype=np.float64,
    )
    indices = np.array(
        [
            [0, 2, 1], [0, 3, 2],
            [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4],
            [3, 7, 6], [3, 6, 2],
            [0, 4, 7], [0, 7, 3],
            [1, 2, 6], [1, 6, 5],
        ],
        dtype=np.int64,
    )
    return Mesh(positions=positions, indices=indices)


def icosphere(radius: float = 0.5, subdivisions: int = 3) -> Mesh:
    """A sphere, by subdividing an icosahedron."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    points = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    vertices = [list(point) for point in points]
    for _ in range(subdivisions):
        cache: dict[tuple[int, int], int] = {}
        new_faces = []

        def midpoint(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key in cache:
                return cache[key]
            middle = [
                (vertices[a][axis] + vertices[b][axis]) / 2.0 for axis in range(3)
            ]
            vertices.append(middle)
            index = len(vertices) - 1
            cache[key] = index
            return index

        for a, b, c in faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces

    array = np.asarray(vertices, dtype=np.float64)
    array /= np.linalg.norm(array, axis=1, keepdims=True)
    array *= radius
    return Mesh(positions=array, indices=np.asarray(faces, dtype=np.int64))


def mug(
    outer: float = 0.04, inner: float = 0.035, height: float = 0.09, bottom: float = 0.005
) -> Mesh:
    """A cup: a wall of thickness ``outer - inner`` and a solid bottom."""
    profile = [
        (0.0, 0.0),
        (outer, 0.0),
        (outer, height),
        (inner, height),
        (inner, bottom),
        (0.0, bottom),
    ]
    return revolve(profile)


def plate(radius: float = 0.05, thickness: float = 0.006) -> Mesh:
    profile = [
        (0.0, 0.0),
        (radius, 0.0),
        (radius, thickness),
        (0.0, thickness),
    ]
    return revolve(profile)


def bracket(arm: float = 0.2, thickness: float = 0.02, depth: float = 0.05) -> Mesh:
    """An L: two slabs at right angles, with a void in the corner."""
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> None:
        base = len(verts)
        verts.extend(
            [
                (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
            ]
        )
        faces.extend(
            [
                (base + 0, base + 2, base + 1), (base + 0, base + 3, base + 2),
                (base + 4, base + 5, base + 6), (base + 4, base + 6, base + 7),
                (base + 0, base + 1, base + 5), (base + 0, base + 5, base + 4),
                (base + 3, base + 7, base + 6), (base + 3, base + 6, base + 2),
                (base + 0, base + 4, base + 7), (base + 0, base + 7, base + 3),
                (base + 1, base + 2, base + 6), (base + 1, base + 6, base + 5),
            ]
        )

    box(0.0, 0.0, 0.0, arm, thickness, depth)
    box(0.0, 0.0, 0.0, thickness, arm, depth)
    return Mesh(
        positions=np.asarray(verts, dtype=np.float64),
        indices=np.asarray(faces, dtype=np.int64),
    )


CASES = {
    "cube": (cube(), 1.0),
    "sphere": (icosphere(0.5), 4.0 / 3.0 * math.pi * 0.5**3),
    "mug": (mug(), math.pi * 0.04**2 * 0.09),
    "plate": (plate(), math.pi * 0.05**2 * 0.006),
    "bracket": (bracket(), 0.2 * 0.02 * 0.05 * 2),
}


def box_state() -> dict:
    """The box's state, beside the numbers.

    Every measurement in this repository carries the state of the machine
    that produced it, so a number can be read against the box it came from.
    """
    memory = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    memory[key] = int(rest.split()[0]) * 1024
    except OSError:
        pass
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = []
    return {
        "machine": "NVIDIA Jetson AGX Thor, aarch64, 14 Neoverse cores",
        "kernel": platform.release(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "load_average": load,
        "mem_total_gb": round(memory.get("MemTotal", 0) / 1024**3, 1),
        "mem_available_gb": round(memory.get("MemAvailable", 0) / 1024**3, 1),
    }


def main() -> int:
    rows = []
    state = box_state()
    print(f"box: {state['machine']}, kernel {state['kernel']}, "
          f"load {state['load_average']}, "
          f"{state['mem_available_gb']} GB available")
    print(f"{'case':10s} {'method':8s} {'occupied':>12s} {'expected':>12s} {'error':>8s}")
    for name, (mesh, expected) in CASES.items():
        for method in ("visual", "convex", "signed"):
            result = occupied(mesh, method, resolution=96)
            error = (result.volume - expected) / expected
            print(
                f"{name:10s} {method:8s} {result.volume:>12.6f} {expected:>12.6f} "
                f"{error:>7.2%}"
            )
            rows.append(
                {
                    "case": name,
                    "method": method,
                    "occupied_volume": result.volume,
                    "expected": expected,
                    "relative_error": error,
                }
            )
    out = Path(__file__).with_name("results") / "occupancy_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"box": state, "cases": rows}, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
