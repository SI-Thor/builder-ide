"""The scripted checks: what the critic measures on a member.

Until a critic *model* is chosen and measured (X R4: the critic is "the
largest unchosen dependency in the whole stack"), every automated verdict
is a scripted check and wears ``verdict@scripted`` on its face. These are
the checks, and they are deliberately dumb: each one is a **measurement** of
the frame, with a threshold, and no model anywhere.

The thresholds below were **measured on the clean controls**, not guessed:
each comment says what the real renders measured, and
:mod:`core.critic.publish` writes those numbers into
``core/critic/CALIBRATION.md`` so the table can be read against them. A
threshold is not tuned to make a planted defect detectable — a check that
fired on every defect would be a check that learned the answer, and the
table would be measuring nothing.

The image checks:

    black_frame     the frame is black — the render failed
    fireflies       isolated extreme pixels — under-sampled noise
    flat_patch      a large region of one exact colour — a hole where an
                    object was
    dark_holes      compact dark discs inside a surface — holes punched
                    through geometry
    patch_seam      a rectangular block pasted into the frame — somebody else's
                    texture, visible as a step in the frame's own profiles
    floating_blob   a compact object hanging in smooth empty space — a prop
                    that left the ground

The mesh checks (the cold-start seat's two, plus a camera oracle):

    watertight      a shell with a hole in it
    scale_bounds    an object whose size is off the scene's scale
    edge_cut        an object cut by the frame's edge — clipped geometry
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .imaging import (
    block_edge_strengths,
    box_mean,
    components,
    largest_uniform_region,
    local_std,
    luma,
    next_true_row,
    reduce_rgb,
)
from .models import (
    INFRASTRUCTURE,
    CameraInfo,
    CheckOutcome,
    MeshObject,
    MeshStats,
    is_prop,
    prop_family,
)

__all__ = [
    "Thresholds",
    "DEFAULT_THRESHOLDS",
    "IMAGE_CHECKS",
    "MESH_CHECKS",
    "run_image_checks",
    "run_mesh_checks",
    "check_scale_bounds",
    "check_watertight",
    "check_edge_cut",
]


@dataclass(frozen=True)
class Thresholds:
    """The checks' thresholds — measured, and stated.

    Each constant carries the clean-control measurement it was set against
    (the real sweep renders, 960×540, on the Thor). The margin between the
    measurement and the threshold is the honest headroom; where the margin
    is thin, the check says so in the table.

    The measurements are reproducible: `core/critic/measure_image.py` prints
    the clean frames' numbers, and `core/critic/measure_set.py` prints what
    the seeded defects score. The thresholds below are the ones those two
    scripts support.
    """

    # black_frame — the clean controls' darkest mean luminance was 0.103
    # (river-s5, the darkest of the 34 real frames); 0.02 is five times below
    # the darkest real frame.
    black_mean_luma: float = 0.02

    # fireflies — the clean controls measured 0 isolated outliers in 44 of
    # the 45 real frames; river-s5 measured 154, which is a real frame with
    # real sun-glitter on the water. The planted defects measure 307 to
    # 472. The threshold sits between the two populations, so the glitter
    # on the water is not a firefly and every planted defect is.
    firefly_delta: float = 0.35
    firefly_count: int = 250

    # flat_patch — the largest exact-colour rectangle in a clean frame was
    # 30 px (0.006 % of the frame); 1 % is 170 times that. A real render has
    # gradients everywhere, so a large single-colour region is an edit.
    flat_region_frac: float = 0.01

    # dark_holes — a hole is a compact blob well below its own surroundings
    # whose interior is *uniform* (the clean controls measured no such blob
    # at all: 0 holes in all 34 frames).
    hole_delta: float = 0.10
    hole_min_area: int = 40
    hole_max_area: int = 8000
    hole_uniform_std: float = 0.015
    hole_min_contrast: float = 0.12

    # patch_seam — a rectangular block pasted into the frame leaves four
    # straight edges. The measurement is the **strength of the weakest of the
    # four sides**: a pasted rectangle is bounded by four straight, sharp
    # steps, and the frame's own landscape has very few of those.
    #
    # The first version of this check measured the frame's global row and
    # column profiles, and it caught the planted swaps in 3 % of the real
    # frames: a patch covering a fifth of the frame's width shifts the row
    # profile by only a fifth of the colour difference it contains, so the
    # step is diluted below anything the clean frames do not also do.
    #
    # The second version looked for the rectangle's edges directly, but it
    # only considered the six strongest edge candidates in each direction.
    # The measurement said why that failed too: a natural frame has more than
    # six straight edges, so the *swapped* rectangle was often not among the
    # candidates at all.
    #
    # So the search is exhaustive but **bounded**: the frame is reduced by
    # four, and a rectangle's four side strengths are read off cumulative
    # sums, which makes every position of every candidate size cost O(1).
    # The statistic is the weakest of the four sides — a seam is only a seam
    # if *all* four of its sides step.
    seam_widths: tuple[int, ...] = (132, 156, 180, 204, 228)
    """The widths a pasted block can be, in the frame's own pixels."""
    seam_heights: tuple[int, ...] = (72, 96, 120, 144)
    """The heights a pasted block can be, in the frame's own pixels."""
    seam_position_step: int = 4
    """How far apart the search's candidate positions are, in pixels."""
    seam_candidates: int = 3
    """How many positions per size the search proposes."""
    seam_refine: int = 3
    """How far, in pixels, a candidate's position is refined around it."""
    seam_nudge: int = 3
    """How far, in pixels, a side's boundary may sit from the search's
    grid and still be read."""
    seam_size_refine: int = 12
    """How far, in pixels, a candidate's size is refined around it."""
    seam_min_strength: float = 0.33
    """How far the weakest of a block's four sides must step.

    Measured: the clean frames' strongest four-sided rectangle steps by
    0.286 at its best, and the planted swaps by 0.46 at their median — so
    the threshold sits between the two populations."""

    # floating_blob — an object hanging in empty space. The hard part is not
    # the blob, it is telling a floating object from a **hilltop bump**:
    # a bump on a smooth hillside is also a compact blob in smooth
    # surroundings with smooth ground under it, and the first measurement
    # found this check firing on 8 of 34 clean frames — a 23.5 % false
    # positive rate, well over the band.
    #
    # The discriminator is the **open gap underneath**: how far the frame's
    # empty space extends below the blob before the next textured row. A
    # prop hanging in the air has open sky under it; a bump is attached to
    # the ground it stands on, so the gap under it is short.
    #
    # The earlier version measured the clearance above a *horizon* — the
    # median over columns of the topmost textured row — and the measurement
    # said why that does not hold: the horizon came out at row 0 in ten of
    # the 41 real frames (their sky is textured, so the topmost textured
    # row is the top of the picture) and at the bottom in two (a frame with
    # no texture at all). A horizon that is sometimes the top of the frame
    # is not an oracle.
    float_background_delta: float = 0.05
    """How far a pixel must differ from its local mean to be part of a
    thing's edge."""
    float_detail: float = 0.04
    """The local detail above which a pixel counts as *busy* — the open
    space under a thing is measured with it."""
    float_min_frac: float = 0.002
    float_max_frac: float = 0.08
    """The largest a thing's box may be, as a fraction of the frame."""
    float_surround_std: float = 0.050
    float_gap_frac: float = 0.02
    float_min_aspect: float = 0.25
    float_window: int = 31
    float_min_gap: float = 0.10
    """The open gap below the blob, in frame heights, above which the blob is
    read as hanging in the air rather than standing on something.

    Measured: the clean frames' candidate blobs reached 0.070 at the ninth
    percentile and 0.209 at the worst, and the planted floats reach 0.10 or
    more — so the threshold sits between the two populations."""
    float_smooth_max: float = 0.05
    """The local detail under which a row counts as open space."""

    # scale_bounds — the cold-start seat's rule, read against measured
    # geometry and **within a prop's own family** (a real scene holds kinds
    # of prop whose natural sizes differ by orders of magnitude, so the
    # scene-wide median means nothing). The measured clean scenes' families
    # reached 5.48× their own median (a family of chopped trees holds both
    # stumps and whole trees), so the threshold sits above that natural
    # spread; the seeded defect scales one prop by 8×.
    scale_max: float = 6.0

    # edge_cut — how near the picture's edge a prop's middle may lie, in
    # its own half-width, before the picture counts as cutting it in half.
    # Measured over the nine rebuilt clean scenes: the closest a clean
    # prop's middle comes to the picture's edge is 0.0105 of its own
    # half-width, and no clean scene has a prop that close.
    edge_cut_margin: float = 0.01

    # hollow_inward — the fraction of a prop's faces that point inwards,
    # above which the shell is hollow (you can see its inside). The clean
    # props' measured worst was 0.593 — vegetation is full of inward faces
    # — so the threshold sits above that, and the seeded defect turns 90 %
    # of a prop's faces inwards.
    hollow_inward: float = 0.70


DEFAULT_THRESHOLDS = Thresholds()


# -- the image checks --------------------------------------------------------


def _check_black_frame(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    g = luma(image)
    mean = float(g.mean())
    fired = mean < t.black_mean_luma
    return CheckOutcome(
        check="black_frame",
        fired=fired,
        detail=f"mean luminance {mean:.4f} (threshold {t.black_mean_luma})",
        measured={"mean_luma": mean},
    )


def _check_fireflies(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    g = luma(image)
    interior = g[1:-1, 1:-1]
    up, down = g[:-2, 1:-1], g[2:, 1:-1]
    left, right = g[1:-1, :-2], g[1:-1, 2:]
    nbr_max = np.maximum(np.maximum(up, down), np.maximum(left, right))
    nbr_min = np.minimum(np.minimum(up, down), np.minimum(left, right))
    hi = (interior - nbr_max) > t.firefly_delta
    lo = (nbr_min - interior) > t.firefly_delta
    count = int(hi.sum()) + int(lo.sum())
    fired = count > t.firefly_count
    return CheckOutcome(
        check="fireflies",
        fired=fired,
        detail=f"{count} isolated outliers (threshold {t.firefly_count})",
        measured={"fireflies": float(count)},
    )


def _check_flat_patch(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    h, w, _ = image.shape
    area, box, colour = largest_uniform_region(image)
    frac = area / float(w * h)
    fired = frac >= t.flat_region_frac
    where = f" at {box}" if box is not None else ""
    return CheckOutcome(
        check="flat_patch",
        fired=fired,
        detail=(
            f"largest single-colour region {area} px ({frac:.4%} of the frame)"
            f"{where}; threshold {t.flat_region_frac:.2%}"
        ),
        measured={"flat_area": float(area), "flat_frac": frac},
    )


def _check_dark_holes(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    """A compact, uniform, dark blob inside a surface — a hole.

    The uniformity is what separates a hole from the scene's own dark
    details (a pebble, a branch, a shadow edge): a hole is a flat disc of
    one colour, and the clean controls measured no blob with an interior
    spread below 0.02.
    """
    g = luma(image)
    surface = box_mean(g, 9)
    diff = surface - g
    mask = diff > t.hole_delta
    labels, found = components(mask)
    holes = []
    for c in found:
        if not (t.hole_min_area <= c.size <= t.hole_max_area):
            continue
        window = (slice(c.y0, c.y1 + 1), slice(c.x0, c.x1 + 1))
        selected = labels[window] == c.label
        if not selected.any():
            continue
        contrast = float(diff[window][selected].mean())
        if contrast < t.hole_min_contrast:
            continue
        spread = float(g[window][selected].std())
        if spread > t.hole_uniform_std:
            continue
        holes.append((c.size, contrast, spread))
    fired = bool(holes)
    biggest = max((h[0] for h in holes), default=0)
    return CheckOutcome(
        check="dark_holes",
        fired=fired,
        detail=(
            f"{len(holes)} uniform dark blob(s) inside a surface (largest {biggest} px)"
            if fired
            else f"no uniform dark blob inside a surface (contrast ≥ {t.hole_min_contrast})"
        ),
        measured={"holes": float(len(holes)), "hole_area": float(biggest)},
    )


def _check_patch_seam(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    """A rectangular block has been pasted into the frame.

    The measurement is the **weakest of the block's four sides**. A pasted
    rectangle is bounded by four straight, sharp steps in the frame — the
    line where the donor's pixels meet the host's — and a landscape, for all
    its straight horizons and cliff faces, does not have four of them.

    The statistic is deliberately the **minimum** of the four sides and not
    their average: one strong edge and three weak ones is a cliff, not a
    block, and an average would let the strong edge carry the decision.

    The search proposes candidates on a coarse grid of positions and then
    measures each of them in the frame's own pixels. The frame is *not*
    reduced: an earlier version reduced it by four, and the measurement said
    why that was wrong — an edge that falls inside a reduced pixel is smeared
    across it, so the block the check reported was often not the block that
    had been planted.

    Three earlier versions of this check failed, and the measurement said
    why. The first measured the frame's global row and column profiles: a
    patch covering a fifth of the frame's width shifts the row profile by
    only a fifth of the colour difference it contains, so the step is
    diluted below anything the clean frames do not also do. The second
    looked for the rectangle's edges and only considered the six strongest
    candidates in each direction — and a natural frame has more than six
    straight edges, so the swapped rectangle was often not among them at
    all. The third measured the block's interior against the ring around
    it, which a landscape reproduces easily: a sky over a desert measured
    0.74 on that statistic, above anything a planted swap reaches.
    """
    h, w, _ = image.shape
    rgb = image.astype(np.float64) / 255.0

    # The step across each column boundary and each row boundary.
    dcol = np.linalg.norm(np.diff(rgb, axis=1), axis=2)  # (h, w-1)
    drow = np.linalg.norm(np.diff(rgb, axis=0), axis=2)  # (h-1, w)

    # Cumulative sums, so that the mean of a run is a difference of two
    # entries and every position costs O(1).
    ccol = np.concatenate([np.zeros((1, dcol.shape[1])), np.cumsum(dcol, axis=0)], axis=0)
    crow = np.concatenate([np.zeros((drow.shape[0], 1)), np.cumsum(drow, axis=1)], axis=1)

    step = max(1, int(t.seam_position_step))
    reach = max(0, int(t.seam_refine))
    best = 0.0
    best_box: tuple[int, int, int, int] | None = None

    for bw in t.seam_widths:
        if bw + 2 >= w:
            continue
        for bh in t.seam_heights:
            if bh + 2 >= h:
                continue
            rows = h - 1 - bh
            cols = w - 1 - bw
            if rows <= 0 or cols <= 0:
                continue
            r_idx = np.arange(0, rows, step)
            c_idx = np.arange(0, cols, step)
            if r_idx.size == 0 or c_idx.size == 0:
                continue
            # The four sides, on the coarse grid.
            coarse = _sum_of_sides(
                ccol, crow, r_idx, c_idx, bw, bh, nudge=int(t.seam_nudge)
            )
            flat = coarse.ravel()
            keep = min(int(t.seam_candidates), flat.size)
            for i in np.argpartition(flat, -keep)[-keep:]:
                r0 = int(r_idx[i // c_idx.size])
                c0 = int(c_idx[i % c_idx.size])
                strength, box = _refine_block(
                    ccol, crow, c0, r0, bw, bh, reach, int(t.seam_size_refine)
                )
                if strength > best:
                    best = strength
                    best_box = box

    if best_box is None:
        detail = "no rectangular block in the frame"
    else:
        detail = (
            f"a block {best_box[2] - best_box[0] + 1}x{best_box[3] - best_box[1] + 1} px "
            f"whose weakest side steps by {best:.3f}"
        )
    fired = best >= t.seam_min_strength
    if fired:
        detail = f"{detail} (threshold {t.seam_min_strength})"
    return CheckOutcome(
        check="patch_seam",
        fired=fired,
        detail=detail,
        measured={"seam_strength": best},
    )


def _vertical_side_values(
    ccol: np.ndarray,
    span: int,
    r_idx: np.ndarray,
    c_idx: np.ndarray,
    nudge: int,
) -> np.ndarray:
    """The mean step down a column boundary, over ``span`` rows.

    The strongest of the few boundaries the side could be on is taken: a
    side is a single column, and a boundary one pixel off reads nothing.
    """
    best = None
    for d in range(-nudge, nudge + 1):
        c = c_idx + d
        if c.min() < 0 or c.max() > ccol.shape[1] - 1:
            continue
        if (r_idx + span).max() > ccol.shape[0] - 1 or r_idx.min() < 0:
            continue
        values = (ccol[span + r_idx][:, c] - ccol[r_idx][:, c]) / span
        best = values if best is None else np.maximum(best, values)
    if best is None:
        return np.zeros((r_idx.size, c_idx.size))
    return best


def _horizontal_side_values(
    crow: np.ndarray,
    span: int,
    r_idx: np.ndarray,
    c_idx: np.ndarray,
    nudge: int,
) -> np.ndarray:
    """The mean step along a row boundary, over ``span`` columns."""
    best = None
    for d in range(-nudge, nudge + 1):
        r = r_idx + d
        if r.min() < 0 or r.max() > crow.shape[0] - 1:
            continue
        if (c_idx + span).max() > crow.shape[1] - 1 or c_idx.min() < 0:
            continue
        values = (crow[r][:, c_idx + span] - crow[r][:, c_idx]) / span
        best = values if best is None else np.maximum(best, values)
    if best is None:
        return np.zeros((r_idx.size, c_idx.size))
    return best


def _sum_of_sides(
    ccol: np.ndarray,
    crow: np.ndarray,
    r_idx: np.ndarray,
    c_idx: np.ndarray,
    bw: int,
    bh: int,
    nudge: int = 1,
) -> np.ndarray:
    """The four sides of a block, *added up*.

    The sum, not the minimum: the search's size grid is coarse, so the far
    sides of a candidate can sit a dozen pixels off the block's own edges
    and read nothing at all. The sum still ranks the block, and the
    refinement — which knows the size and the position exactly — judges it
    on the minimum, which is the statistic that matters.
    """
    left = _vertical_side_values(ccol, bh, r_idx, c_idx, nudge)
    right = _vertical_side_values(ccol, bh, r_idx, c_idx + bw, nudge)
    top = _horizontal_side_values(crow, bw, r_idx, c_idx, nudge)
    bottom = _horizontal_side_values(crow, bw, r_idx + bh, c_idx, nudge)
    return left + right + top + bottom


def _min_of_sides(
    ccol: np.ndarray,
    crow: np.ndarray,
    r_idx: np.ndarray,
    c_idx: np.ndarray,
    bw: int,
    bh: int,
    nudge: int = 1,
) -> np.ndarray:
    """The weakest of a block's four sides, over the given positions."""
    left = _vertical_side_values(ccol, bh, r_idx, c_idx, nudge)
    right = _vertical_side_values(ccol, bh, r_idx, c_idx + bw, nudge)
    top = _horizontal_side_values(crow, bw, r_idx, c_idx, nudge)
    bottom = _horizontal_side_values(crow, bw, r_idx + bh, c_idx, nudge)
    return np.minimum(np.minimum(left, right), np.minimum(top, bottom))


def _refine_block(
    ccol: np.ndarray,
    crow: np.ndarray,
    c0: int,
    r0: int,
    bw: int,
    bh: int,
    reach: int,
    size_refine: int,
) -> tuple[float, tuple[int, int, int, int]]:
    """Measure a candidate block in the frame's own pixels.

    The candidate's position is searched in a small window around it, and
    its size in a small window of its own, because the coarse grid knows
    the block only to within a step.
    """
    offsets = np.arange(-reach, reach + 1)
    best = 0.0
    best_box = (c0, r0, c0 + bw, r0 + bh)
    sizes = [0]
    if size_refine > 0:
        sizes = list(range(-size_refine, size_refine + 1, 4))
    for dw in sizes:
        for dh in sizes:
            width = bw + dw
            height = bh + dh
            if width < 8 or height < 8:
                continue
            rs = r0 + offsets
            cs = c0 + offsets
            if rs.min() < 0 or cs.min() < 0:
                continue
            if (bh + rs).max() > ccol.shape[0] - 1:
                continue
            if (bh + rs).max() > crow.shape[0] - 1:
                continue
            if (bw + cs).max() > ccol.shape[1] - 1:
                continue
            if (bw + cs).max() > crow.shape[1] - 1:
                continue
            sides = _min_of_sides(ccol, crow, rs, cs, width, height, nudge=1)
            flat = float(sides.max())
            if flat > best:
                best = flat
                i = int(sides.argmax())
                row = int(rs[i // offsets.size])
                col = int(cs[i % offsets.size])
                best_box = (col + 1, row + 1, col + width, row + height)
    return best, best_box


def _vertical_side(
    ccol: np.ndarray, bh: int, rows: int, cols: int, c0: int
) -> np.ndarray:
    """The mean step down a column boundary, over the block's height.

    Indexed by the block's top row and left column. The strongest of the
    three boundaries the side could be on is taken, so that a side one
    pixel off the block's edge still reads the step.
    """
    best = None
    for nudge in (-1, 0, 1):
        x = c0 + nudge
        if x < 0 or x + cols > ccol.shape[1]:
            continue
        run = (ccol[bh : bh + rows, x : x + cols] - ccol[0:rows, x : x + cols]) / bh
        best = run if best is None else np.maximum(best, run)
    if best is None:
        return np.zeros((rows, cols))
    return best


def _horizontal_side(
    crow: np.ndarray, bw: int, rows: int, cols: int, r0: int
) -> np.ndarray:
    """The mean step along a row boundary, over the block's width.

    Indexed by the block's top row and left column, like the vertical side.
    """
    best = None
    for nudge in (-1, 0, 1):
        y = r0 + nudge
        if y < 0 or y + rows > crow.shape[0]:
            continue
        run = (crow[y : y + rows, bw : bw + cols] - crow[y : y + rows, 0:cols]) / bw
        best = run if best is None else np.maximum(best, run)
    if best is None:
        return np.zeros((rows, cols))
    return best


def _check_floating_blob(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    """An object hanging in empty space, off the ground.

    A **thing** is a compact region with detail in it; **empty space** is a
    region without. The object hangs clear of the frame's edge, stands in
    empty space on every side, and has open space under it — that is the
    easy half.

    The hard half is telling a **floating prop** from a **hilltop bump**. A
    bump on a smooth hillside is also a compact thing in smooth
    surroundings, and the first measurement of this check on the real
    renders fired on 8 of 34 clean frames — a 23.5 % false-positive rate,
    well over the band's 10 %. That is the check's weakest point and the
    table says so.

    The discriminator is the **open gap underneath**: how far the frame's
    empty space extends below the thing before the next detailed row. A
    prop hanging in the air has open sky under it; a bump is attached to
    the ground it stands on, so the ground comes up to meet it.

    The earlier version measured the gap above the frame's *horizon*, and
    the measurement said why that will not do: the horizon came out at the
    top row of the picture in ten of the 41 real frames, because their sky
    is textured, and at the bottom row in two, because they have no texture
    at all. A horizon that is sometimes the top of the frame is not an
    oracle. The gap underneath is measured from the thing itself, so it
    needs no horizon.

    The mask is **detail**, not a difference from the local mean. The first
    version used the local mean, and the plant that places the copy used
    the detail: two different notions of "empty", so the copy was placed
    where the check saw foreground and it merged with the ground. Half of
    the planted copies were thrown away that way.
    """
    g = luma(image)
    detail = local_std(g, 9)
    background = box_mean(g, t.float_window)
    difference = np.abs(g - background)
    mask = difference > t.float_background_delta
    h, w = g.shape
    total = h * w
    _, found = components(mask)
    # Where the empty space under each row ends: the next detailed row.
    next_row = next_true_row(detail > t.float_smooth_max)

    detail_text = "no object hanging in empty space"
    fired = False
    best = 0
    best_gap = 0.0
    for comp in found:
        # The object's size is its **box**, not the number of pixels in its
        # outline: the mask finds a thing's edges, so a tree's crown is a
        # ring of pixels around a lot of sky.
        extent = comp.width * comp.height
        if not (t.float_min_frac * total <= extent <= t.float_max_frac * total):
            continue
        if comp.x0 <= 0 or comp.y0 <= 0 or comp.x1 >= w - 1 or comp.y1 >= h - 1:
            continue  # an object that reaches the frame's edge is not floating
        if comp.width / float(max(1, comp.height)) < t.float_min_aspect:
            continue  # a column is a trunk, not an object hanging in the air
        if _surrounding_detail(detail, comp) > t.float_surround_std:
            continue  # it hangs in front of something busy, not in empty space
        gap = _open_gap(next_row, comp, h)
        if gap < t.float_min_gap:
            continue  # the ground is right under it: a bump, not a floater
        fired = True
        best = comp.size
        best_gap = gap
        break
    if fired:
        detail_text = (
            f"an object of {best} px hangs with {best_gap:.2f} frame heights "
            f"of open space under it"
        )
    return CheckOutcome(
        check="floating_blob",
        fired=fired,
        detail=detail_text,
        measured={"floating_area": float(best), "gap": best_gap},
    )


def _surrounding_detail(detail: np.ndarray, comp: Any) -> float:
    """The median detail in the band just outside a component."""
    h, w = detail.shape
    band = 9
    x0 = max(0, comp.x0 - band)
    y0 = max(0, comp.y0 - band)
    x1 = min(w - 1, comp.x1 + band)
    y1 = min(h - 1, comp.y1 + band)
    outside = np.ones((y1 - y0 + 1, x1 - x0 + 1), dtype=bool)
    ox0 = comp.x0 - x0
    oy0 = comp.y0 - y0
    outside[oy0 : oy0 + comp.height, ox0 : ox0 + comp.width] = False
    region = detail[y0 : y1 + 1, x0 : x1 + 1]
    if not outside.any():
        return float("inf")
    return float(np.median(region[outside]))


#: How many rows below a blob the open-space search starts. The local
#: detail is measured over a nine-pixel window, so a blob's own edge leaves
#: a halo of "busy" pixels under itself.
_GAP_HALO = 5


def _open_gap(next_row: np.ndarray, comp: Any, height: int) -> float:
    """How far the open space extends below a blob, in frame heights.

    The gap is the longest run of empty rows directly under the blob, taken
    over its columns: a prop hanging in the air has a long one, a bump on
    the ground has none.

    The search starts a few rows **below** the blob's own bottom: the
    local detail is measured over a nine-pixel window, so the blob's edge
    leaves a halo of "busy" pixels underneath itself, and a gap measured
    from the blob's last row is always zero.
    """
    start = comp.y1 + 1 + _GAP_HALO
    if start >= height:
        return 0.0
    below = next_row[start, comp.x0 : comp.x1 + 1]
    if below.size == 0:
        return 0.0
    gap = int(below.min()) - start
    return max(0, gap) / float(height)


def _clearance(g: np.ndarray, comp: Any, height: int) -> float:
    """How far a blob's bottom sits above the frame's horizon, in frame
    heights.

    The horizon is the frame's skyline: the median, over columns, of the
    topmost strongly-textured row. A prop hanging in the air is entirely
    above it, with open sky under it; a bump on a hillside has its bottom
    *at* the skyline, because that is where the ground it stands on is.
    """
    textured = local_std(g, 9) > 0.05
    width = g.shape[1]
    tops = []
    for x in range(0, width, 4):
        rows = np.flatnonzero(textured[:, x])
        tops.append(int(rows[0]) if rows.size else height)
    horizon = int(np.median(tops)) if tops else height
    return max(0.0, (horizon - comp.y1) / float(height))


def _surrounding_std(g: np.ndarray, comp: Any) -> float:
    """The median local detail in the band just outside a component."""
    h, w = g.shape
    band = 9
    x0 = max(0, comp.x0 - band)
    y0 = max(0, comp.y0 - band)
    x1 = min(w - 1, comp.x1 + band)
    y1 = min(h - 1, comp.y1 + band)
    outside = np.ones((y1 - y0 + 1, x1 - x0 + 1), dtype=bool)
    ox0 = comp.x0 - x0
    oy0 = comp.y0 - y0
    outside[oy0 : oy0 + comp.height, ox0 : ox0 + comp.width] = False
    region = local_std(g[y0 : y1 + 1, x0 : x1 + 1], 9)
    if not outside.any():
        return float("inf")
    return float(np.median(region[outside]))


#: The image checks, in the order the critic runs them.
IMAGE_CHECKS: tuple[Callable[[np.ndarray, Thresholds], CheckOutcome], ...] = (
    _check_black_frame,
    _check_fireflies,
    _check_flat_patch,
    _check_dark_holes,
    _check_patch_seam,
    _check_floating_blob,
)


def run_image_checks(
    image: np.ndarray, thresholds: Thresholds | None = None
) -> list[CheckOutcome]:
    """Every image check's measurement on one frame."""
    t = thresholds or DEFAULT_THRESHOLDS
    return [check(image, t) for check in IMAGE_CHECKS]


# -- the mesh checks ---------------------------------------------------------

def props_of(stats: MeshStats) -> list[MeshObject]:
    """The scene's props — the objects the mesh checks judge."""
    return [o for o in stats.objects if o.faces > 0 and is_prop(o.name)]


def check_scale_bounds(
    stats: MeshStats, t: Thresholds | None = None
) -> CheckOutcome:
    """Is any prop the wrong size for its own kind?

    The cold-start seat's rule, read against measured geometry: a prop's
    bounding-box diagonal must sit within a band of the scene's median
    diagonal.

    Measured against real scenes, that oracle does not hold, and the
    measurement says why: a real scene holds *several kinds* of prop, and
    their natural sizes differ by orders of magnitude. In one measured scene
    a lichen was 0.14 units across while a bush was 8.2 — the scene-wide
    median said nothing about either. The band would have fired on every
    clean frame.

    So the comparison is made **within a family** — the same rock, the same
    bush — which is what "the wrong scale" means. And then the measurement
    said something else: within a family, Infinigen's own instances vary by
    up to **5.48×** their family's median, because a family of chopped trees
    holds both stumps and whole trees. A modest scale error — 1.45×, the
    obvious choice — sits inside that spread and no threshold could ever
    separate it from a clean scene.

    So the rule is the one that nature does not produce: a prop **far**
    bigger than every other prop of its kind. The threshold sits above the
    measured natural spread and the seeded defect is well above it.
    """
    if t is None:
        t = DEFAULT_THRESHOLDS
    props = props_of(stats)
    if len(props) < 2:
        return CheckOutcome(
            check="scale_bounds",
            fired=False,
            detail="not enough props to judge a scene's scale",
            applicable=False,
        )
    families: dict[str, list[MeshObject]] = {}
    for obj in props:
        families.setdefault(prop_family(obj.name), []).append(obj)

    offenders: list[tuple[MeshObject, float]] = []
    for members in families.values():
        diagonals = sorted(o.diagonal for o in members if o.diagonal > 0)
        if len(diagonals) < 2:
            continue
        median = diagonals[len(diagonals) // 2]
        if median <= 0:
            continue
        for obj in members:
            if obj.diagonal <= 0:
                continue
            ratio = obj.diagonal / median
            if ratio > t.scale_max:
                offenders.append((obj, ratio))

    fired = bool(offenders)
    names = ", ".join(f"{o.name[:24]}@{r:.1f}x" for o, r in offenders[:4])
    return CheckOutcome(
        check="scale_bounds",
        fired=fired,
        detail=(
            f"{len(offenders)} prop(s) more than {t.scale_max:.1f}x their own "
            f"family's median size: {names}"
            if fired
            else (
                f"every prop within {t.scale_max:.1f}x its family's median size "
                f"({len(props)} props in {len(families)} families)"
            )
        ),
        measured={"scale_offenders": float(len(offenders))},
    )


def check_watertight(
    stats: MeshStats, t: Thresholds | None = None
) -> CheckOutcome:
    """Is any prop's shell hollow?

    Watertightness runs as a mechanical check *before* any critic (RV patch
    7; X R10), so a hollow mesh dies here rather than reaching a model.

    The check reads the prop's shell, not the whole scene: Infinigen's
    terrain is a heightfield and is never watertight, so a scene-wide
    watertightness check would fire on every real frame. Among the props,
    the measured clean scenes had 26 of 44 and 24 of 48 watertight — the
    rest are Infinigen's eroded rock shells, which are *open* surfaces
    rather than hollow ones.

    So openness alone is not the defect. A **hollow** shell is one that
    folds back on itself: its faces point inwards, towards the prop's own
    centre. That is the ``inward`` fraction the probe measures, and the
    measured clean props' worst was 0.593 of their faces — vegetation is
    full of inward faces, so a shell has to fold back far more than nature
    does before it reads as hollow. The signed volume cannot carry the
    decision either: the measurement found natural negative volumes in four
    of the ten scenes.
    """
    if t is None:
        t = DEFAULT_THRESHOLDS
    props = props_of(stats)
    if not props:
        return CheckOutcome(
            check="watertight",
            fired=False,
            detail="no props to judge",
            applicable=False,
        )
    hollow = [o for o in props if o.inward >= t.hollow_inward]
    fired = bool(hollow)
    names = ", ".join(o.name[:28] for o in hollow[:4])
    worst = max((o.inward for o in props), default=0.0)
    return CheckOutcome(
        check="watertight",
        fired=fired,
        detail=(
            f"{len(hollow)} prop(s) have a hollow shell (inward faces): {names}"
            if fired
            else (
                f"no hollow shell among {len(props)} props "
                f"(worst inward fraction {worst:.3f})"
            )
        ),
        measured={"open_shells": float(len(hollow)), "worst_inward": worst},
    )


def check_edge_cut(
    stats: MeshStats, t: Thresholds | None = None
) -> CheckOutcome:
    """Is any prop cut by the picture's own edge?

    The camera is the oracle. A prop whose middle projects inside the
    picture while the picture's edge passes close to that middle is cut
    **in half** by the frame — the defect.

    It is not the same thing as a prop reaching outside the picture: the
    measured clean scenes had 30 of 44 and 26 of 48 props reaching outside
    the frame, because a landscape is shot from inside it, and 98 clean
    props are cut by the camera's near plane for the same reason. What the
    measurement separated was the *severity*: of the 11 clean props the
    picture slices, only one has its middle within a tenth of its own
    half-width of the picture's edge, and six of the nine measured scenes
    have no such prop at all.
    """
    if t is None:
        t = DEFAULT_THRESHOLDS
    camera = stats.camera
    props = props_of(stats)
    if camera is None or not props:
        return CheckOutcome(
            check="edge_cut",
            fired=False,
            detail="no camera to judge the frame's edge",
            applicable=False,
        )
    cut: list[tuple[str, float]] = []
    for obj in props:
        margin = _cut_margin(camera, obj)
        if margin is not None and margin <= t.edge_cut_margin:
            cut.append((obj.name, margin))
    fired = bool(cut)
    names = ", ".join(f"{name[:24]}@{margin:.2f}" for name, margin in cut[:4])
    return CheckOutcome(
        check="edge_cut",
        fired=fired,
        detail=(
            f"{len(cut)} prop(s) cut through the middle by the picture's edge: {names}"
            if fired
            else (
                f"no prop cut through the middle by the picture's edge "
                f"({len(props)} props checked)"
            )
        ),
        measured={"cut_objects": float(len(cut))},
    )


def _cut_margin(camera: CameraInfo, obj: MeshObject) -> float | None:
    """How near the picture's edge a prop's middle lies, in its own half-width.

    ``None`` when the prop's middle is outside the picture altogether —
    a prop that is merely off in the distance is not cut by the frame.
    """
    corners = [
        (obj.x0 if i == 0 else obj.x1, obj.y0 if j == 0 else obj.y1, obj.z0 if k == 0 else obj.z1)
        for i in (0, 1)
        for j in (0, 1)
        for k in (0, 1)
    ]
    projected = [camera.projects(corner) for corner in corners]
    forwards = [p[2] for p in projected]
    if min(forwards) <= 0:
        return None
    right, up, centre_forward = camera.projects(obj.centre)
    if centre_forward <= 0:
        return None
    # The picture's size at the prop's **middle**, which is the point the
    # margin is measured from. The plant puts the middle on the edge using
    # the same depth, so the two have to agree on it.
    half_w = camera.half_width * centre_forward / camera.depth
    half_h = camera.half_height * centre_forward / camera.depth
    if abs(right) > half_w or abs(up) > half_h:
        return None  # the middle is outside: the prop is off in the distance
    rights = [p[0] for p in projected]
    ups = [p[1] for p in projected]
    extent_r = max((max(rights) - min(rights)) / 2.0, 1e-9)
    extent_u = max((max(ups) - min(ups)) / 2.0, 1e-9)
    margins = (
        (half_w - right) / extent_r,
        (half_w + right) / extent_r,
        (half_h - up) / extent_u,
        (half_h + up) / extent_u,
    )
    return float(min(margins))


#: The mesh checks, in the order the critic runs them.
MESH_CHECKS: tuple[Callable[[MeshStats, Thresholds], CheckOutcome], ...] = (
    check_watertight,
    check_scale_bounds,
    check_edge_cut,
)


def run_mesh_checks(
    stats: MeshStats | None, thresholds: Thresholds | None = None
) -> list[CheckOutcome]:
    """Every mesh check's measurement on one scene (skipped without a mesh)."""
    t = thresholds or DEFAULT_THRESHOLDS
    if stats is None:
        return [
            CheckOutcome(
                check=check.__name__.removeprefix("check_"),
                fired=False,
                detail="no mesh attached to this member",
                applicable=False,
            )
            for check in MESH_CHECKS
        ]
    return [check(stats, t) for check in MESH_CHECKS]
