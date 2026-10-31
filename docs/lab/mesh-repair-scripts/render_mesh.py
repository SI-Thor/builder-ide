"""Render a mesh's silhouette and a shaded view of it, with numpy only.

The measurement this file supports is the **silhouette IoU**: how much of the
object's outline survives a repair. The silhouette of a mesh is the union of
the projections of its surface onto the view plane, so it can be measured by
sampling the surface and splatting the samples into a pixel grid — no
rasteriser, no GPU, no window.

The same sampling makes a shaded picture: the nearest sample per pixel wins,
so the picture is a point-cloud z-buffer render. Good enough to *see* a prop,
which is what a person needs when a number says "the repair changed the
shape".

Run: .venv/bin/python docs/lab/mesh-repair-scripts/render_mesh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.glb import read_glb

OUT = Path.home() / "lm-wt/trellis/out/genbatch"

#: The six axis-aligned views, as (right, up, towards) unit vectors.
VIEWS = {
    "+x": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "-x": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
    "+y": ((1, 0, 0), (0, 0, 1), (0, 1, 0)),
    "-y": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "+z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-z": ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
}


def sample_surface(
    positions: np.ndarray, indices: np.ndarray, n: int, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Sample points on a mesh's surface, and the normal of each one.

    Points are drawn area-weighted over the triangles and uniformly inside
    their triangle, so the density on the surface is uniform.
    """
    rng = np.random.default_rng(seed)
    a = positions[indices[:, 0]]
    b = positions[indices[:, 1]]
    c = positions[indices[:, 2]]
    cross = np.cross(b - a, c - a)
    twice_area = np.linalg.norm(cross, axis=1)
    total = twice_area.sum()
    if total <= 0:
        raise ValueError("the mesh has no area to sample")
    # How many samples each triangle gets, proportional to its area.
    counts = rng.multinomial(n, twice_area / total)
    tri = np.repeat(np.arange(indices.shape[0]), counts)
    u = rng.random(tri.size)
    v = rng.random(tri.size)
    flip = u + v > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    pts = (
        a[tri] * (1.0 - u - v)[:, None]
        + b[tri] * u[:, None]
        + c[tri] * v[:, None]
    )
    normals = cross[tri] / np.maximum(twice_area[tri], 1e-300)[:, None]
    return pts, normals


def _bounds_in_view(
    bounds: tuple[np.ndarray, np.ndarray], right: np.ndarray, up: np.ndarray, towards: np.ndarray
) -> tuple[float, float, float, float, float]:
    """The bounding box, as seen by one view.

    The eight corners of the box are projected onto the view's right and up
    axes, which gives the rectangle the picture is fitted into. Returns
    ``(u_min, u_max, v_min, v_max, depth_min)``.
    """
    lo, hi = bounds
    corners = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    )
    us = corners @ right
    vs = corners @ up
    ds = corners @ towards
    return float(us.min()), float(us.max()), float(vs.min()), float(vs.max()), float(ds.min())


def project(
    pts: np.ndarray,
    normals: np.ndarray,
    view: str,
    resolution: int,
    bounds: tuple[np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Project points into a pixel grid. Returns (pixel index, depth)."""
    right, up, towards = (np.asarray(v, dtype=np.float64) for v in VIEWS[view])
    u_min, u_max, v_min, v_max, depth_min = _bounds_in_view(bounds, right, up, towards)
    u = (pts @ right - u_min) / max(u_max - u_min, 1e-12)
    v = (pts @ up - v_min) / max(v_max - v_min, 1e-12)
    depth = pts @ towards
    x = np.clip((u * (resolution - 1)).astype(np.int64), 0, resolution - 1)
    y = np.clip((v * (resolution - 1)).astype(np.int64), 0, resolution - 1)
    # Keep only the points that are in front of the camera.
    front = depth >= depth_min
    x, y, depth = x[front], y[front], depth[front]
    return y * resolution + x, depth


def silhouette(
    positions: np.ndarray,
    indices: np.ndarray,
    view: str,
    resolution: int = 256,
    samples: int = 2_000_000,
    seed: int = 7,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """The mesh's silhouette from one view, as a boolean pixel grid."""
    if bounds is None:
        lo = positions.min(axis=0)
        hi = positions.max(axis=0)
        bounds = (lo, hi)
    pts, _ = sample_surface(positions, indices, samples, seed=seed)
    pixel, _ = project(pts, None, view, resolution, bounds)  # type: ignore[arg-type]
    mask = np.zeros(resolution * resolution, dtype=bool)
    mask[pixel] = True
    return mask.reshape(resolution, resolution)


def shaded(
    positions: np.ndarray,
    indices: np.ndarray,
    view: str,
    resolution: int = 256,
    samples: int = 4_000_000,
    seed: int = 7,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """A shaded picture of the mesh from one view (a point-cloud z-buffer)."""
    if bounds is None:
        lo = positions.min(axis=0)
        hi = positions.max(axis=0)
        bounds = (lo, hi)
    pts, normals = sample_surface(positions, indices, samples, seed=seed)
    pixel, depth = project(pts, normals, view, resolution, bounds)
    if pixel.size == 0:
        return np.zeros((resolution, resolution, 3), dtype=np.uint8)
    # Far samples first, so the nearest one is written last and wins.
    order = np.argsort(-depth)
    pixel = pixel[order]
    nrm = normals[order]
    zbuf = np.full(resolution * resolution, np.inf)
    zbuf[pixel] = depth[order]
    hit = np.isfinite(zbuf)
    # A lamp in the upper-left, plus a little ambient.
    light = np.array([-0.4, 0.6, 0.7])
    light /= np.linalg.norm(light)
    lam = np.abs(nrm @ light)
    shade = np.clip(0.25 + 0.75 * lam, 0, 1)
    img = np.zeros((resolution * resolution, 3))
    img[pixel] = shade[:, None]
    return (img.reshape(resolution, resolution, 3) * 255).astype(np.uint8)


def write_png(path: Path, image: np.ndarray) -> None:
    """Write a PNG without a plotting library."""
    import zlib

    height, width, channels = image.shape
    raw = b"".join(
        b"\x00" + image[row].tobytes() for row in range(height)
    )

    def chunk(tag: bytes, body: bytes) -> bytes:
        import struct

        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", __import__("struct").pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> None:
    names = sys.argv[1:] or ["crate_s1064508603_00004_.glb"]
    out_dir = Path("artifacts/mesh-repair/renders")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = OUT / name
        mesh = read_glb(path).mesh
        for view in ("+x", "+y", "+z"):
            img = shaded(mesh.positions, mesh.indices, view, resolution=256)
            stem = name.replace(".glb", "")
            write_png(out_dir / f"{stem}_{view.replace('+', 'p')}.png", img)
            print("wrote", out_dir / f"{stem}_{view.replace('+', 'p')}.png")


if __name__ == "__main__":
    main()
