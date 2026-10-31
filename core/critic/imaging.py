"""The imaging helpers the scripted checks share.

Everything here is **analytic and deterministic**: a measurement of the
pixels, never a model. The spec's rule for the scripted checks (§2.3:
"scripted analytic computations, no physics engine") is the rule this module
follows — and the reason the checks can be trusted as a *baseline*: they
cannot learn the defect they are meant to catch, because they never see the
recipe.

The heavy lifting is numpy over the whole frame; the connected-component
work is done with runs and a union-find rather than per-pixel Python, so a
frame's components cost a fraction of a second.

numpy and Pillow are optional extras of the core package (``pip install
'.[critic]'``). The modules that need them import them lazily enough that
the pure-Python half of the seat — the harvest, the manifest, the fold —
keeps working without them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .harvest import sha256_file

__all__ = [
    "load_rgb",
    "save_rgb",
    "sha256_file",
    "sha256_bytes",
    "luma",
    "local_std",
    "box_mean",
    "background_mean",
    "integral",
    "components",
    "Component",
    "next_true_row",
    "reduce_rgb",
    "block_edge_strengths",
    "largest_uniform_region",
    "border_colour",
    "paste_region",
    "clip_box",
]


def load_rgb(path: str | Path) -> np.ndarray:
    """Read an image as an ``uint8`` HxWx3 array (RGB, not BGR)."""
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def save_rgb(path: str | Path, image: np.ndarray) -> str:
    """Write an RGB array as a PNG and return the file's sha256.

    Pillow's PNG writer is deterministic for the same pixels and options, so
    the same defect recipe always yields the same bytes — and therefore the
    same hash, which is what the reference set pins.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB").save(
        path, format="PNG", optimize=False, compress_level=6
    )
    return sha256_file(path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def luma(image: np.ndarray) -> np.ndarray:
    """The frame's luminance in [0, 1] — Rec. 601 weights, the usual choice."""
    rgb = image.astype(np.float32) / 255.0
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def integral(image: np.ndarray) -> np.ndarray:
    """The summed-area table of ``image`` (float64, one extra row and column)."""
    arr = image.astype(np.float64)
    out = np.zeros((arr.shape[0] + 1, arr.shape[1] + 1), dtype=np.float64)
    out[1:, 1:] = arr.cumsum(axis=0).cumsum(axis=1)
    return out


def _window_sums(table: np.ndarray, k: int) -> np.ndarray:
    """The sum over every k×k window of a summed-area table."""
    return table[k:, k:] - table[:-k, k:] - table[k:, :-k] + table[:-k, :-k]


def box_mean(gray: np.ndarray, k: int) -> np.ndarray:
    """The mean over every k×k window of a luminance map.

    The frame's border is clamped, so the result has the input's shape.
    """
    k = max(1, int(k) | 1)
    h, w = gray.shape
    mean = _window_sums(integral(gray), k) / float(k * k)
    pad = k // 2
    if pad:
        mean = np.pad(mean, pad, mode="edge")[:h, :w]
    return mean


def background_mean(gray: np.ndarray, k: int = 9) -> np.ndarray:
    """The local *background* level — the frame's smooth trend under a pixel.

    The mean over a wide window tells a pixel how bright its surroundings
    are, which is what decides whether a point of light stands out against
    them: a white pixel on a bright sky is not a firefly, and the same
    white pixel on a dark hillside is.
    """
    return box_mean(gray, k)


def local_std(gray: np.ndarray, k: int = 9) -> np.ndarray:
    """The local standard deviation of a luminance map over k×k windows.

    The edges of the frame are handled by clamping the window, so the map
    has the same shape as the input.
    """
    k = max(1, int(k) | 1)
    h, w = gray.shape
    sq = integral(gray * gray)
    mean = _window_sums(integral(gray), k) / (k * k)
    mean_sq = _window_sums(sq, k) / (k * k)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    std = np.sqrt(var)
    # Clamp the border windows (the sums above only cover full windows).
    pad = k // 2
    if pad:
        std = np.pad(std, pad, mode="edge")[:h, :w]
    return std


def reduce_rgb(rgb: np.ndarray, factor: int) -> np.ndarray:
    """A frame reduced by ``factor``, by averaging each block of pixels.

    The reduction is for *finding* things quickly, not for measuring them:
    an edge that falls inside a reduced pixel is smeared across it, so the
    step a reduced frame shows is smaller than the step the pixels have.
    """
    factor = max(1, int(factor))
    if factor == 1:
        return rgb
    h, w = rgb.shape[:2]
    hh, ww = (h // factor) * factor, (w // factor) * factor
    if hh < factor or ww < factor:
        return rgb
    return rgb[:hh, :ww].reshape(
        hh // factor, factor, ww // factor, factor, rgb.shape[2]
    ).mean(axis=(1, 3))


def _strip_step(a: np.ndarray, b: np.ndarray) -> float:
    """The mean colour step between two matched strips of pixels."""
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    diff = a.astype(np.float64) - b.astype(np.float64)
    return float(np.linalg.norm(diff, axis=-1).mean()) / 255.0


def block_edge_strengths(image: np.ndarray, box: tuple[int, int, int, int]) -> list[float]:
    """The four sides of a block, as the mean colour step across each.

    The sides are measured in the image's own pixels, and each is read with
    a one-pixel tolerance — the strongest of the three boundaries it could
    be on — because a block's edge does not have to land exactly on a pixel
    boundary.

    The order is left, right, top, bottom.
    """
    x0, y0, x1, y1 = box
    h, w = image.shape[:2]
    out: list[float] = []
    for axis in ("left", "right", "top", "bottom"):
        best = 0.0
        for nudge in (-1, 0, 1):
            if axis == "left":
                c = x0 - 1 + nudge
                if c < 0 or c + 1 > w - 1:
                    continue
                step = _strip_step(image[y0 : y1 + 1, c, :], image[y0 : y1 + 1, c + 1, :])
            elif axis == "right":
                c = x1 + nudge
                if c < 0 or c + 1 > w - 1:
                    continue
                step = _strip_step(image[y0 : y1 + 1, c, :], image[y0 : y1 + 1, c + 1, :])
            elif axis == "top":
                r = y0 - 1 + nudge
                if r < 0 or r + 1 > h - 1:
                    continue
                step = _strip_step(image[r, x0 : x1 + 1, :], image[r + 1, x0 : x1 + 1, :])
            else:
                r = y1 + nudge
                if r < 0 or r + 1 > h - 1:
                    continue
                step = _strip_step(image[r, x0 : x1 + 1, :], image[r + 1, x0 : x1 + 1, :])
            best = max(best, step)
        out.append(best)
    return out


def next_true_row(mask: np.ndarray) -> np.ndarray:
    """For every pixel, the row of the next set pixel **below** it.

    The answer is the row itself where the pixel is set, the height of the
    mask where nothing is set below, and it is computed for the whole map in
    one pass (a reverse running minimum) rather than by scanning columns in
    Python.

    This is what "how far does the open space extend below this thing" is
    measured with: the gap under a blob is where the next set row starts,
    minus the blob's own bottom.
    """
    height, width = mask.shape
    rows = np.broadcast_to(np.arange(height, dtype=np.int64)[:, None], mask.shape)
    marked = np.where(mask, rows, height)
    running = np.minimum.accumulate(marked[::-1], axis=0)[::-1]
    return running


@dataclass(frozen=True)
class Component:
    """One connected region of a mask."""

    label: int
    size: int
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def touches_border(self) -> bool:
        return self.x0 == 0 or self.y0 == 0


def components(mask: np.ndarray) -> tuple[np.ndarray, list[Component]]:
    """The 4-connected components of a boolean mask.

    Runs are found with a vectorised diff per row and merged with a
    union-find, so the cost is the number of *runs* rather than the number of
    pixels — a frame's worth of components in a fraction of a second.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent: list[int] = [0]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    all_runs: list[tuple[int, int, int, int]] = []  # (y, x0, x1, label)
    previous: list[tuple[int, int, int]] = []  # (x0, x1, label)
    next_label = 1
    for y in range(h):
        row = mask[y].astype(np.int8)
        edges = np.diff(np.concatenate(([0], row, [0])))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1) - 1
        current: list[tuple[int, int, int]] = []
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            label = next_label
            next_label += 1
            parent.append(label)
            current.append((x0, x1, label))
            all_runs.append((y, x0, x1, label))
        for x0, x1, label in current:
            for px0, px1, plabel in previous:
                if px0 <= x1 and x0 <= px1:
                    union(label, plabel)
        previous = current

    root_to_id: dict[int, int] = {}
    stats: dict[int, list[int]] = {}  # id -> [size, x0, y0, x1, y1]
    for y, x0, x1, label in all_runs:
        root = find(label)
        cid = root_to_id.get(root)
        if cid is None:
            cid = len(root_to_id) + 1
            root_to_id[root] = cid
            stats[cid] = [0, x0, y, x1, y]
        entry = stats[cid]
        entry[0] += x1 - x0 + 1
        entry[1] = min(entry[1], x0)
        entry[2] = min(entry[2], y)
        entry[3] = max(entry[3], x1)
        entry[4] = max(entry[4], y)
        labels[y, x0 : x1 + 1] = cid

    result = [
        Component(label=cid, size=s[0], x0=s[1], y0=s[2], x1=s[3], y1=s[4])
        for cid, s in sorted(stats.items())
    ]
    return labels, result


def largest_uniform_region(
    image: np.ndarray, *, colours: int = 8
) -> tuple[int, tuple[int, int, int, int] | None, tuple[int, int, int] | None]:
    """The largest axis-aligned rectangle of a single exact colour.

    A render that has been *edited* — an object removed and the hole filled
    with one colour — carries such a rectangle; a real render does not (the
    frame's colours are gradients and noise, so no exact colour repeats over
    a large area). The search is bounded to the frame's most frequent exact
    colours, which keeps it cheap and still finds a planted patch: a patch
    big enough to see is by construction one of the frame's common colours.

    Returns ``(area, (x0, y0, x1, y1), (r, g, b))``; the area is 0 when the
    frame has no such rectangle.
    """
    h, w, _ = image.shape
    packed = (
        (image[..., 0].astype(np.uint32) << 16)
        | (image[..., 1].astype(np.uint32) << 8)
        | image[..., 2].astype(np.uint32)
    )
    values, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)[:colours]
    best_area = 0
    best_box: tuple[int, int, int, int] | None = None
    best_colour: tuple[int, int, int] | None = None
    for index in order.tolist():
        colour = int(values[index])
        mask = packed == colour
        area, box = _largest_rectangle(mask)
        if area > best_area:
            best_area = area
            best_box = box
            best_colour = (
                (colour >> 16) & 0xFF,
                (colour >> 8) & 0xFF,
                colour & 0xFF,
            )
    return best_area, best_box, best_colour


def _largest_rectangle(mask: np.ndarray) -> tuple[int, tuple[int, int, int, int] | None]:
    """The largest all-True rectangle of a boolean mask (histogram method)."""
    h, w = mask.shape
    heights = np.zeros(w, dtype=np.int64)
    best = 0
    best_box: tuple[int, int, int, int] | None = None
    for y in range(h):
        row = mask[y]
        heights = np.where(row, heights + 1, 0)
        positive = heights > 0
        if not positive.any():
            continue
        edges = np.diff(np.concatenate(([0], positive.astype(np.int8), [0])))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        for seg_start, seg_end in zip(starts.tolist(), ends.tolist()):
            seg = heights[seg_start:seg_end]
            stack: list[tuple[int, int]] = []
            for i, height in enumerate(seg.tolist()):
                start = i
                while stack and stack[-1][1] >= height:
                    s0, h0 = stack.pop()
                    area = h0 * (i - s0)
                    if area > best:
                        best = area
                        best_box = (seg_start + s0, y - h0 + 1, seg_start + i - 1, y)
                    start = s0
                stack.append((start, height))
            for s0, h0 in stack:
                area = h0 * (len(seg) - s0)
                if area > best:
                    best = area
                    best_box = (seg_start + s0, y - h0 + 1, seg_end - 1, y)
    return best, best_box


def border_colour(image: np.ndarray) -> tuple[int, int, int]:
    """The median colour of the frame's border ring.

    The border ring is the part of the frame most likely to be *background*
    (sky, ground) whatever the camera is doing — and the median makes it
    robust to a frame whose subject reaches one edge. Used to fill a removed
    object with something the frame could plausibly have shown there.
    """
    ring = np.concatenate(
        [
            image[0, :, :].reshape(-1, 3),
            image[-1, :, :].reshape(-1, 3),
            image[:, 0, :].reshape(-1, 3),
            image[:, -1, :].reshape(-1, 3),
        ],
        axis=0,
    )
    med = np.median(ring.astype(np.float64), axis=0)
    return tuple(int(round(float(v))) for v in med)  # type: ignore[return-value]


def clip_box(
    box: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    """Clip a box to the frame; returns a zero-area box when it falls out."""
    x0, y0, x1, y1 = box
    x0 = max(0, min(int(x0), width - 1))
    y0 = max(0, min(int(y0), height - 1))
    x1 = max(0, min(int(x1), width - 1))
    y1 = max(0, min(int(y1), height - 1))
    return x0, y0, x1, y1


def paste_region(
    image: np.ndarray,
    source: np.ndarray,
    box: tuple[int, int, int, int],
) -> np.ndarray:
    """Paste ``source`` into ``image`` at ``box`` (x0, y0, x1, y1 inclusive)."""
    out = image.copy()
    x0, y0, x1, y1 = box
    out[y0 : y1 + 1, x0 : x1 + 1] = source[y0 : y1 + 1, x0 : x1 + 1]
    return out


def as_jsonable(value: Any) -> Any:
    """numpy scalars → python scalars, for the manifest."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value
