"""The support probe: the surface below a floating thing, and how far above it the thing is.

A verdict says *that* something floats. A continuation says *what it should
be resting on* and *how far it has to fall*, and both of those are
measurements, not opinions:

* **the support surface** — where the frame's structure starts again under
  the thing, and what kind of surface it is (terrain, liquid, a prop, or
  unknown when the picture cannot say);
* **the drop distance** — how far the thing's bottom is above that surface,
  in the frame's own units (pixels and frame heights, both exact) and in
  metres when a metric probe could reach the scene.

The probe is the **frame domain**: it measures the picture the critic was
handed. When the member's scene is live, the geometry probe
(:mod:`core.critic.mesh`) adds the scene's scale — metres per pixel at the
scene's depth — and the scene's own name for the surface.

The picture is the only thing that can be measured for a defect that lives in
the pixels, and the reference set's members are exactly that: a defect
planted in a render. So the frame is the probe's home, and the geometry is
the bonus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .checks import DEFAULT_THRESHOLDS, Thresholds, _floating_candidate
from .edits import Edit, Support, SupportKind
from .imaging import box_mean, components, luma, local_std, next_true_row

__all__ = ["Surface", "probe_surface", "suggest_edit"]


@dataclass(frozen=True)
class Surface:
    """What the probe measured under the thing that is floating."""

    kind: SupportKind
    row: int | None
    drop_px: int
    drop_frame_heights: float
    relief: float
    span: float
    box: tuple[int, int, int, int]
    metres_per_pixel: float | None = None

    @property
    def drop_m(self) -> float | None:
        """The drop in metres, when a metric scale is known."""
        if self.metres_per_pixel is None:
            return None
        return self.drop_px * self.metres_per_pixel


def _surface_kind(relief: float, smooth_max: float) -> SupportKind:
    """What kind of surface the band below the thing is.

    The frame's own measurement decides it, and it decides **little**: a
    surface that carries **relief** (the local detail over the band is above
    the check's smooth threshold) is broken ground — terrain. A surface that
    measures flat is a plane, and a picture cannot say which plane it is: a
    lake, a beach and a snowfield all measure flat. So a flat surface is
    reported as ``unknown`` rather than guessed at, and the measured relief
    travels with the edit so a reader can see the number the name would have
    come from.
    """
    return "terrain" if relief > smooth_max else "unknown"


def _hanging_candidate(image: np.ndarray, t: Thresholds):
    """The thing that hangs highest above the surface, whether or not the
    scripted check called it a floater.

    The check is deliberately conservative — it skips a thing that hangs in
    front of something busy — and a model delegate may flag a frame the
    check let alone. The probe must still be able to point at the thing, so
    it does its own search with the check's mask and the check's size and
    edge filters, and keeps the thing with the **largest** open space under
    it.

    Returns ``(component, mask, detail, next_row)`` or ``None``.
    """
    g = luma(image)
    detail = local_std(g, 9)
    background = box_mean(g, t.float_window)
    difference = np.abs(g - background)
    mask = difference > t.float_background_delta
    h, w = g.shape
    total = h * w
    _, found = components(mask)
    next_row = next_true_row(detail > t.float_smooth_max)
    best = None
    for comp in found:
        extent = comp.width * comp.height
        if not (t.float_min_frac * total <= extent <= t.float_max_frac * total):
            continue
        if comp.x0 <= 0 or comp.y0 <= 0 or comp.x1 >= w - 1 or comp.y1 >= h - 1:
            continue
        if comp.width / float(max(1, comp.height)) < t.float_min_aspect:
            continue
        start = comp.y1 + 1 + 5
        if start >= h:
            continue
        below = next_row[start:h, comp.x0 : comp.x1 + 1]
        if below.size == 0:
            continue
        rows = np.asarray(below, dtype=int)
        rows = rows[rows > 0]
        if rows.size == 0:
            continue
        gap = int(rows.min()) - comp.y1
        if best is None or gap > best[0]:
            best = (gap, comp)
    if best is None:
        return None
    return best[1], mask, detail, next_row


def probe_surface(
    image: np.ndarray,
    thresholds: Thresholds | None = None,
    *,
    metres_per_pixel: float | None = None,
) -> Surface | None:
    """Probe the support below the thing the floating check fires on.

    Returns ``None`` when there is nothing hanging in the frame at all.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    found = _floating_candidate(image, t)
    if found is not None:
        comp, _gap, _mask, detail, next_row = found
    else:
        loose = _hanging_candidate(image, t)
        if loose is None:
            return None
        comp, _mask, detail, next_row = loose
    height = image.shape[0]

    # Where the frame's structure starts again under the thing: the first
    # detailed row below it. The same rows the gap is measured over, so the
    # surface and the gap are the same surface.
    #
    # ``next_row`` holds, for every cell, the index of the next detailed row
    # at or below it — so, for each of the thing's columns, where the frame's
    # structure resumes. The surface's own row is the **median** of those:
    # the minimum is one column's detail (a rock, an edge — the thing would
    # come to rest on it and still hang over the slope beside it), and the
    # maximum is a column with no detail at all until the frame's bottom (a
    # smooth slope, where the thing would be pushed out of the picture).
    start = comp.y1 + 1 + 5  # the gap's halo: the blob's own edge leaves one
    below = next_row[start : height, comp.x0 : comp.x1 + 1]
    if below.size == 0:
        rows = np.array([], dtype=int)
    else:
        rows = np.asarray(below, dtype=int)
    surface_rows = rows[rows > 0]
    if surface_rows.size == 0:
        # Nothing under it at all: the thing hangs over the frame's edge.
        return Surface(
            kind="unknown",
            row=None,
            drop_px=0,
            drop_frame_heights=0.0,
            relief=0.0,
            span=0.0,
            box=(comp.x0, comp.y0, comp.x1, comp.y1),
            metres_per_pixel=metres_per_pixel,
        )
    support_row = int(np.median(surface_rows))
    band = detail[support_row : min(height, support_row + 16), comp.x0 : comp.x1 + 1]
    relief = float(np.median(band)) if band.size else 0.0
    # How much of the thing's width the surface actually covers: a plane
    # under the whole thing is one thing, a ledge under part of it is another.
    span = float((surface_rows <= support_row + 2).mean())
    drop_px = max(0, support_row - comp.y1)
    return Surface(
        kind=_surface_kind(relief, t.float_smooth_max),
        row=support_row,
        drop_px=drop_px,
        drop_frame_heights=drop_px / float(height),
        relief=relief,
        span=span,
        box=(comp.x0, comp.y0, comp.x1, comp.y1),
        metres_per_pixel=metres_per_pixel,
    )


def scene_scale(stats: Any) -> float | None:
    """Metres per pixel, from the geometry probe's camera.

    The camera's frame is quoted in the world at the scene's depth, so the
    picture's width in metres divided by its width in pixels is the scale of
    the frame **at that depth**. It is an estimate for anything else: a thing
    hanging in the sky is nearer the camera than the ground it hangs over, so
    the metres it falls are fewer than the pixels it moves.
    """
    camera = getattr(stats, "camera", None)
    width = int(getattr(stats, "frame_width", 0) or 0)
    if camera is None or not width:
        return None
    half_width = float(getattr(camera, "half_width", 0.0) or 0.0)
    if half_width <= 0.0:
        return None
    return (2.0 * half_width) / float(width)


def suggest_edit(
    image: np.ndarray,
    thresholds: Thresholds | None = None,
    *,
    metres_per_pixel: float | None = None,
    target: str = "floating_blob",
) -> Edit | None:
    """The edit the critic proposes for a frame that has something floating.

    ``None`` when the check did not fire: there is nothing to propose, and a
    critic that always has an edit is a critic that is always crying wolf.
    """
    surface = probe_surface(
        image, thresholds, metres_per_pixel=metres_per_pixel
    )
    if surface is None:
        return None
    support = Support(
        kind=surface.kind,
        label=surface.kind,
        row=surface.row,
        source="frame",
    )
    return Edit(
        op="lower_object",
        target=target,
        box=surface.box,
        support=support,
        drop_px=surface.drop_px,
        drop_frame_heights=surface.drop_frame_heights,
        drop_m=surface.drop_m,
        evidence={
            "relief": surface.relief,
            "span": surface.span,
            "support_row": float(surface.row or 0),
        },
    )
