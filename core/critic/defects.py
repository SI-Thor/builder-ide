"""The seeded defect vocabulary: how each defect class is planted.

Every defect is planted **deterministically** in `(base, seed)`: the same
sweep render always yields the same broken image, byte for byte. That is
what makes the reference set a *recipe* rather than a pile of pictures — the
render is the cache, the recipe is the truth, and a member can be re-derived
from the base render alone (the house rule: store recipes, not meshes).

Two rules govern how a defect may be planted, and both exist to keep the
table honest:

1. **The plant may not know the check.** A defect is planted by what a
   *broken render* looks like, not by what the check measures. The checks
   never see the recipe; if a plant were tuned to a threshold, the table
   would be measuring the plant, not the critic.
2. **The plant must be visible.** A defect nobody could see is a free
   false negative, and a free false negative makes the table a lie. So each
   plant changes the picture in a way a person would name as that defect.

The classes and their layers are in :mod:`core.critic.models`; the mesh
classes (which need the scene's geometry) live in :mod:`core.critic.mesh`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from .imaging import (
    background_mean,
    block_edge_strengths,
    border_colour,
    box_mean,
    local_std,
    luma,
    next_true_row,
    paste_region,
)

__all__ = [
    "DefectPlan",
    "plan",
    "apply",
    "rng_for",
    "available_image_defects",
]

#: How many fireflies a firefly defect plants, and how close together they
#: may sit (a firefly next to a firefly is one bright pair, not two).
FIREFLY_COUNT = 320
FIREFLY_MIN_SPACING = 4

#: The size of a removed object, as a fraction of the frame's width.
MISSING_OBJECT_SCALE = (0.16, 0.26)

#: The size of the region a hole is punched into.
HOLE_REGION_SCALE = (0.14, 0.22)

#: How many holes, and how big, in a holed object.
HOLE_COUNT = (3, 7)
HOLE_RADIUS = (7, 15)

#: How much darker a hole is than the surface it is punched into, in 8-bit
#: levels. The subtraction is *absolute* so that the hole reads the same on
#: a bright dune and on a dark hillside (a proportional darkening would
#: vanish on the dark ones).
HOLE_DARKNESS = 76

#: The least local detail a surface may have and still be a surface to punch
#: a hole into.
HOLE_MIN_TEXTURE = 0.02

#: The least light a surface may have and still show a hole: the hole is
#: ``HOLE_DARKNESS`` levels below the surface, and the check needs the
#: contrast to clear ``hole_min_contrast``.
HOLE_MIN_LUMA = 0.25

#: The size of the region that is swapped for another render's pixels.
SWAP_SCALE = (0.14, 0.24)

#: How far the donor block's **worst** border must be from the host's, for
#: the swap to count as visible — in RGB distance over the unit cube. A swap
#: whose edges do not show is not a defect anybody could see, and a defect
#: nobody can see is a free false negative.
SWAP_MIN_DISTANCE = 0.40

#: How many donor windows the plant looks at, per host box.
SWAP_DONOR_TRIES = 120

#: The size of the object that is made to float, and where it lands.
FLOAT_OBJECT_SCALE = (0.07, 0.13)

#: The most local detail an "empty" region may have for the copy to land
#: there — above this, the region is something, not sky.
FLOAT_SMOOTH_MAX = 0.05

#: The open space the copy must have under it, in frame heights, before it
#: reads as hanging in the air rather than standing on something. The ladder
#: is tried in order: the first gap that can be found is used, and the gap
#: it reached is recorded in the recipe.
FLOAT_GAP_LADDER = (0.12, 0.10, 0.08)

#: How far the copy keeps from the frame's edge — and how wide the empty
#: band around it has to be, so that it cannot merge with whatever stands
#: beside it.
FLOAT_MARGIN = 14

#: How far the copy's colour must be from what it hangs against, so that
#: the copy is visible at all.
FLOAT_MIN_CONTRAST = 0.08

#: The least detail an object may carry and still be an object worth
#: copying: a smooth patch is not a thing.
FLOAT_MIN_TEXTURE = 0.04

#: How far a pixel must differ from its local mean to be part of a
#: thing's edge. The plant and the check share it, so the copy is a thing
#: to the critic as well.
FLOAT_BACKGROUND_DELTA = 0.05

#: How far down the frame a copy may hang, as a fraction of the frame's
#: height. A thing that hangs in the air is in the picture's upper part; a
#: copy pasted low down is a prop on the ground.
FLOAT_MAX_HEIGHT = 0.70


@dataclass(frozen=True)
class DefectPlan:
    """What to plant, and in which render.

    The plan is the *intent*; the recipe (which pixels were touched) is
    written out after the plant, because it depends on the image.
    """

    defect: str
    base_id: str
    seed: int
    donor_id: str | None = None
    """The other render a swap takes its pixels from (``texture_swap``)."""


def available_image_defects() -> tuple[str, ...]:
    """The defect classes this module can plant in the pixels."""
    from .models import IMAGE_DEFECTS

    return IMAGE_DEFECTS


def rng_for(*parts: Any) -> np.random.Generator:
    """A generator seeded by the parts — the same parts, the same stream."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % (2**32)
    return np.random.default_rng(seed)


def plan(
    defect: str,
    *,
    base_id: str,
    seed: int,
    donor_id: str | None = None,
) -> DefectPlan:
    """The intent for one defect. Which render it is, and which other render
    it may borrow from."""
    if defect == "texture_swap" and donor_id is None:
        raise ValueError("texture_swap needs a donor render")
    return DefectPlan(defect=defect, base_id=base_id, seed=seed, donor_id=donor_id)


def apply(
    image: np.ndarray,
    plan_: DefectPlan,
    *,
    donor_image: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Plant the planned defect and return the broken image plus its recipe.

    The recipe says exactly what was touched (the boxes, the colours, the
    donor) — enough to re-derive the image and to audit the plant without
    trusting the code that made it.
    """
    defect = plan_.defect
    rng = rng_for(plan_.base_id, defect, plan_.seed)
    if defect == "black_frame":
        return _plant_black_frame(image)
    if defect == "noise_fireflies":
        return _plant_fireflies(image, rng)
    if defect == "missing_object":
        return _plant_missing_object(image, rng)
    if defect == "holes":
        return _plant_holes(image, rng)
    if defect == "texture_swap":
        if donor_image is None:
            raise ValueError("texture_swap needs a donor image")
        return _plant_texture_swap(image, donor_image, rng, plan_.donor_id or "?")
    if defect == "floating_object":
        return _plant_floating_object(image, rng)
    raise ValueError(f"cannot plant {defect!r} in the pixels")


# -- the plants -------------------------------------------------------------


def _plant_black_frame(image: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """The render came back black — the GPU died, the compositor failed."""
    out = np.zeros_like(image)
    return out, {"mode": "zero", "shape": list(image.shape[:2])}


def _plant_fireflies(
    image: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """Salt-and-pepper fireflies: isolated extreme pixels.

    Fireflies are what a Cycles render with too few samples and a hot pixel
    looks like, and they are *isolated* — that is what the check measures,
    and it is why the plant keeps them apart.

    Each firefly is planted **opposite to its local background**: a bright
    one where the frame is dark, a dark one where it is bright. The first
    version of this plant chose the value at random, so a third of its
    fireflies landed where they could not be seen at all (a black pixel in
    a dark sky is not a firefly) — and a firefly nobody can see is a free
    false negative, which makes the table a lie.
    """
    h, w, _ = image.shape
    out = image.copy()
    background = box_mean(luma(image), 9)
    placed: list[tuple[int, int]] = []
    attempts = 0
    while len(placed) < FIREFLY_COUNT and attempts < FIREFLY_COUNT * 40:
        attempts += 1
        y = int(rng.integers(1, h - 1))
        x = int(rng.integers(1, w - 1))
        if any(abs(y - py) < FIREFLY_MIN_SPACING and abs(x - px) < FIREFLY_MIN_SPACING
               for py, px in placed):
            continue
        placed.append((y, x))
        # Bright on a dark background, dark on a bright one — always visible.
        value = 255 if float(background[y, x]) < 0.5 else 0
        out[y, x, :] = value
    return out, {
        "count": len(placed),
        "min_spacing": FIREFLY_MIN_SPACING,
        "values": [0, 255],
        "contrasting": True,
    }


def _plant_missing_object(
    image: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """An object is gone: its pixels are replaced by the frame's background.

    The fill is one exact colour, taken from the frame's border ring (the
    part of the picture most likely to be background whatever the camera is
    doing), so the hole reads as "whatever was behind the object" rather
    than as a grey box.
    """
    h, w, _ = image.shape
    vmap = local_std(luma(image), 9)
    box = _pick_textured(vmap, _candidate_boxes(rng, w, h, MISSING_OBJECT_SCALE))
    fill = border_colour(image)
    out = image.copy()
    x0, y0, x1, y1 = box
    out[y0 : y1 + 1, x0 : x1 + 1, :] = fill
    area = (x1 - x0 + 1) * (y1 - y0 + 1)
    return out, {
        "bbox": [x0, y0, x1, y1],
        "fill": list(fill),
        "area_frac": round(area / float(w * h), 5),
    }


def _plant_holes(
    image: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """Holes punched through a surface: dark discs inside an object.

    Each disc is the surface's own colour with a fixed amount of light
    taken off it, so the hole reads as a hole in *that* surface rather than
    as a black sticker — and the size of the step is the same on a bright
    dune and on a dark hillside.

    The surface is chosen for its **brightness**, not just its detail. The
    first version punched into the most *textured* region, and the
    measurement of the checks said what that cost: in three of the 41 real
    frames the textured region was a shadow, the hole went as dark as the
    shadow already was, and the hole was invisible — a free false
    negative. A hole in a lit surface is a hole you can see.
    """
    h, w, _ = image.shape
    vmap = local_std(luma(image), 9)
    lmap = luma(image)
    box = _pick_bright(vmap, lmap, _candidate_boxes(rng, w, h, HOLE_REGION_SCALE))
    if box is None:
        # No lit surface in this frame: a hole punched into dark water is
        # black on black, and a defect nobody can see is a free false
        # negative. The member is skipped rather than counted.
        return image.copy(), {
            "placed": False,
            "reason": "no lit surface in this frame",
        }
    x0, y0, x1, y1 = box
    out = image.copy()
    holes: list[list[int]] = []
    count = int(rng.integers(HOLE_COUNT[0], HOLE_COUNT[1] + 1))
    for _ in range(count):
        radius = int(rng.integers(HOLE_RADIUS[0], HOLE_RADIUS[1] + 1))
        cx = int(rng.integers(x0 + radius, max(x0 + radius + 1, x1 - radius)))
        cy = int(rng.integers(y0 + radius, max(y0 + radius + 1, y1 - radius)))
        # The surface colour at the hole's own spot, read before painting.
        surface = image[
            max(0, cy - radius * 2) : cy + radius * 2 + 1,
            max(0, cx - radius * 2) : cx + radius * 2 + 1,
            :,
        ].reshape(-1, 3).mean(axis=0)
        dark = tuple(int(round(float(c))) - HOLE_DARKNESS for c in surface)
        dark = tuple(max(0, min(255, c)) for c in dark)
        yy, xx = np.ogrid[:h, :w]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius
        out[mask, :] = dark
        holes.append([cx, cy, radius])
    return out, {
        "bbox": [x0, y0, x1, y1],
        "darkness": HOLE_DARKNESS,
        "holes": holes,
    }


def _plant_texture_swap(
    image: np.ndarray,
    donor: np.ndarray,
    rng: np.random.Generator,
    donor_id: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """A patch of the picture is replaced by another render's pixels.

    The classic "the texture did not load" or "the wrong material was
    bound" failure: the geometry is right and the surface is somebody
    else's. The donor is a different real render from the sweep.

    The visibility rule is the donor's, and it is stated on the block's
    **edges**: the donor region must differ from the host region along
    *every* side of the block, or the swap is not a defect anybody could
    see — and a defect nobody can see is a free false negative, which makes
    the table a lie.

    The first version of this plant compared the donor's mean colour with
    the host's, and the measurement of the check said what that cost: a
    donor whose *middle* differs from the host while its *border* does not
    produces a block with no visible edge, and the check — which looks for
    the block's four sides — cannot see it. So the donor is chosen by the
    **worst** of its four borders' distances from the host's, and the recipe
    records the distance it reached.
    """
    h, w, _ = image.shape
    dh, dw, _ = donor.shape
    vmap = local_std(luma(image), 9)
    boxes = _candidate_boxes(rng, w, h, SWAP_SCALE)
    best: tuple[tuple[int, int, int, int], int, int, float] | None = None
    for box in boxes:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if x0 < 2 or y0 < 2 or x1 > w - 3 or y1 > h - 3:
            # The block needs a surface on every side for its edges to show.
            continue
        sx0, sy0, score = _pick_furthest_sided(donor, rng, bw, bh, image, (x0, y0))
        if best is None or score > best[3]:
            best = ((x0, y0, x1, y1), sx0, sy0, score)
    if best is None:
        # No box with a surface on every side; take the most detailed one and
        # let the donor do what it can.
        box = _pick_textured(vmap, boxes)
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        sx0, sy0, score = _pick_furthest_sided(donor, rng, bw, bh, image, (x0, y0))
        best = ((x0, y0, x1, y1), sx0, sy0, score)

    (x0, y0, x1, y1), sx0, sy0, score = best
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    patch = donor[sy0 : sy0 + bh, sx0 : sx0 + bw, :]
    out = image.copy()
    out[y0 : y0 + bh, x0 : x0 + bw, :] = patch
    # The score is measured on the composed picture, so that it is the same
    # number the check will read.
    sides = block_edge_strengths(out, (x0, y0, x0 + bw - 1, y0 + bh - 1))
    score = min(sides)
    return out, {
        "bbox": [x0, y0, x1, y1],
        "donor": donor_id,
        "donor_bbox": [sx0, sy0, sx0 + bw - 1, sy0 + bh - 1],
        "edge_distance": round(score, 4),
        "visible": score >= SWAP_MIN_DISTANCE,
    }


def _pick_furthest_sided(
    donor: np.ndarray,
    rng: np.random.Generator,
    width: int,
    height: int,
    host_image: np.ndarray,
    host_box: tuple[int, int],
) -> tuple[int, int, float]:
    """The donor window whose four edges are all unlike the host's.

    The score is the **worst** of the four edges' distances, so a donor
    that matches the host along one edge cannot win: a block with one
    invisible edge is not a swap anybody would see.

    Each edge is scored the way a person would read it — the average
    difference between the donor's edge pixels and the host's pixels right
    beside them — and not by the two edges' average colours, which can be
    far apart while the edges themselves look continuous.
    """
    dh, dw, _ = donor.shape
    hx, hy = host_box
    if dw <= width or dh <= height:
        return 0, 0, 0.0
    best = (0, 0)
    best_score = -1.0
    for _ in range(SWAP_DONOR_TRIES):
        sx0 = int(rng.integers(0, dw - width))
        sy0 = int(rng.integers(0, dh - height))
        # The donor's border, measured against the host's pixels just
        # outside the block: what the block's edges will look like.
        region = donor[sy0 : sy0 + height, sx0 : sx0 + width, :]
        left = _strip_mean(region[:, 0], host_image[hy : hy + height, hx - 1])
        right = _strip_mean(region[:, -1], host_image[hy : hy + height, hx + width])
        top = _strip_mean(region[0, :], host_image[hy - 1, hx : hx + width])
        bottom = _strip_mean(region[-1, :], host_image[hy + height, hx : hx + width])
        score = min(left, right, top, bottom)
        if score > best_score:
            best_score = score
            best = (sx0, sy0)
    return best[0], best[1], best_score


def _strip_mean(a: np.ndarray, b: np.ndarray) -> float:
    """The mean colour step between two matched strips of pixels."""
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    diff = a.astype(np.float64) - b.astype(np.float64)
    return float(np.linalg.norm(diff, axis=-1).mean()) / 255.0


def _plant_floating_object(
    image: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """An object is lifted off the ground and left hanging in the air.

    The copy is of a real *object* — a region that stands out from its own
    background and carries detail in it — so the pasted thing has the hard
    edge an object has.

    Where it lands is the whole difficulty. A thing that hangs in the air
    has **open space under it**: the ground is a long way below, and the
    space between the thing and the ground is empty. The first version of
    this plant pasted into the smoothest region anywhere, which is often a
    smooth patch of *ground* — and an object sitting on the ground is not
    floating, it is just an object. The second version pasted above the
    frame's horizon, and the measurement of the checks said why that will
    not do either: the horizon came out at the top row of the picture in
    ten of the 41 real frames, because their sky is textured, and at the
    bottom in two, because they have no texture at all.

    So the plant does not use a horizon. It places the copy where the frame
    itself says there is open space: where the next textured row below the
    copy is a long way down, where the copy's surround is smooth, where the
    copy contrasts with what it hangs against, and where the copy keeps
    clear of the frame's edge. A person looking at the result sees a thing
    hovering.

    The copy is left where it was: the object is now in two places at once,
    one of them in mid-air.
    """
    h, w, _ = image.shape
    lifted = _pick_object(image)
    source_box: tuple[int, int, int, int] | None = None
    if lifted is None:
        # Nothing in this frame reads as an object; fall back to the most
        # detailed region there is rather than planting nothing.
        vmap = local_std(luma(image), 9)
        source_box = _pick_textured(vmap, _candidate_boxes(rng, w, h, FLOAT_OBJECT_SCALE))
        patch = image[source_box[1] : source_box[3] + 1, source_box[0] : source_box[2] + 1, :].copy()
        alpha = np.ones(patch.shape[:2], dtype=bool)
    else:
        patch, alpha = lifted
    ph, pw = patch.shape[:2]
    if pw >= w - 16 or ph >= h - 16:
        return image.copy(), {"placed": False, "reason": "the object is the whole frame"}

    g = luma(image)
    detail = local_std(g, 9)
    textured = detail > FLOAT_SMOOTH_MAX
    next_row = next_true_row(textured)
    mean = patch[alpha].mean(axis=0) if alpha.any() else patch.reshape(-1, 3).mean(axis=0)

    best: tuple[tuple[float, float], tuple[int, int], float, float] | None = None
    for want in FLOAT_GAP_LADDER:
        for bottom in range(ph + FLOAT_MARGIN, h - FLOAT_MARGIN - 1, 4):
            if bottom > h * FLOAT_MAX_HEIGHT:
                break
            row = next_row[bottom + 1]
            if row.size < pw:
                continue
            windows = np.lib.stride_tricks.sliding_window_view(row, pw)
            gaps = windows.min(axis=1) - (bottom + 1)
            where = np.flatnonzero(gaps >= want * h)
            if where.size == 0:
                continue
            for x0 in where:
                x0 = int(x0)
                if x0 < FLOAT_MARGIN or x0 + pw > w - FLOAT_MARGIN:
                    continue
                y0 = bottom + 1 - ph
                if y0 < FLOAT_MARGIN:
                    continue
                # The copy's surround must be empty, or it merges with the
                # scene instead of standing alone in it. The copy's own
                # pixels are not part of the surround.
                band = FLOAT_MARGIN
                ring = detail[
                    max(0, y0 - band) : y0 + ph + band,
                    max(0, x0 - band) : x0 + pw + band,
                ].copy()
                if ring.shape[0] > 2 * band and ring.shape[1] > 2 * band:
                    ring[band:-band, band:-band] = 0.0
                if ring.size == 0 or float(ring.mean()) > FLOAT_SMOOTH_MAX:
                    continue
                region = image[y0 : bottom + 1, x0 : x0 + pw, :].reshape(-1, 3)
                if region.size == 0:
                    continue
                contrast = float(np.linalg.norm(mean - region.mean(axis=0)))
                if contrast < FLOAT_MIN_CONTRAST:
                    continue
                gap = float(gaps[x0]) / h
                # Prefer the gap the plant asked for, then the contrast.
                key = (abs(gap - want), -contrast)
                if best is None or key < best[0]:
                    best = (key, (x0, y0), gap, contrast)
        if best is not None:
            break

    if best is None:
        # No open space in this frame to hang anything in: the defect would
        # be invisible, so the member is skipped rather than counted as a
        # false negative nobody could have avoided.
        return image.copy(), {
            "placed": False,
            "reason": "no open space in this frame",
            "source_bbox": list(source_box) if source_box else None,
        }

    _, (x0, y0), gap, contrast = best
    out = image.copy()
    region = out[y0 : y0 + ph, x0 : x0 + pw, :]
    region[alpha] = patch[alpha]
    out[y0 : y0 + ph, x0 : x0 + pw, :] = region
    return out, {
        "source_bbox": list(source_box) if source_box else None,
        "dest_bbox": [x0, y0, x0 + pw - 1, y0 + ph - 1],
        "gap": round(gap, 4),
        "contrast": round(contrast, 4),
        "pasted_px": int(alpha.sum()),
        "placed": True,
    }


def _horizon(image: np.ndarray) -> int:
    """The frame's horizon: the median, over columns, of the topmost
    strongly-textured row.

    Above it is the sky; below it is the ground. It is the same measure the
    check uses to tell a thing in the air from a bump on the ground.
    """
    g = luma(image)
    h, w = g.shape
    textured = local_std(g, 9) > 0.05
    tops = []
    for x in range(0, w, 4):
        rows = np.flatnonzero(textured[:, x])
        tops.append(int(rows[0]) if rows.size else h)
    return int(np.median(tops)) if tops else h


def _pick_in_sky(
    image: np.ndarray,
    patch: np.ndarray,
    rng: np.random.Generator,
    width: int,
    height: int,
    horizon: int,
    *,
    vmap: np.ndarray,
    alpha: np.ndarray,
    occupied: np.ndarray,
    avoid: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    """Where the floating copy lands: in the sky, with open sky below it.

    A candidate is a rectangle that lies **above** the horizon and whose
    columns are open (no ground) from the bottom of the rectangle all the
    way down to the horizon — that is what makes the copy read as suspended
    rather than as a prop on the ground.
    """
    ph, pw = patch.shape[:2]
    if alpha is not None and alpha.any():
        mean = patch[alpha].mean(axis=0)
    else:
        mean = patch.reshape(-1, 3).mean(axis=0)

    best: tuple[tuple[int, int, int], tuple[int, int, int, int]] | None = None
    for _ in range(120):
        x0 = int(rng.integers(0, max(1, width - pw)))
        y0 = int(rng.integers(0, max(1, horizon - ph)))
        x1 = x0 + pw - 1
        y1 = y0 + ph - 1
        if y1 >= horizon:
            continue
        if x0 <= 0 or y0 <= 0 or x1 >= width - 1 or y1 >= height - 1:
            continue
        if avoid is not None and not (
            x0 > avoid[2] or x1 < avoid[0] or y0 > avoid[3] or y1 < avoid[1]
        ):
            continue  # do not paste the object on top of itself
        # Open sky below: nothing textured between the copy and the horizon.
        below = vmap[y1 + 1 : horizon, x0 : x1 + 1]
        if below.size == 0:
            continue
        openness = float((below <= FLOAT_SMOOTH_MAX).mean())
        if openness < 0.9:
            continue
        # Busy or already-occupied ground there is not sky.
        busy = float(vmap[y0 : y1 + 1, x0 : x1 + 1].mean())
        if busy > FLOAT_SMOOTH_MAX:
            continue
        taken = float(occupied[y0 : y1 + 1, x0 : x1 + 1].mean())
        # Prefer the emptiest, smoothest, most contrasting spot.
        region = image[y0 : y1 + 1, x0 : x1 + 1, :].reshape(-1, 3)
        if region.size == 0:
            continue
        distance = float(np.linalg.norm(mean - region.mean(axis=0)))
        key = (int(taken > 0.02), int(busy > FLOAT_SMOOTH_MAX), -distance)
        if best is None or key < best[0]:
            best = (key, (x0, y0, x1, y1))
    if best is not None:
        return best[1]
    # No sky in this frame (a top-down shot, or a wall of rock): fall back
    # to the top of the frame, which is the least wrong place for a thing
    # that is supposed to be in the air.
    return (max(0, width // 2 - pw // 2), max(0, horizon - ph - 1),
            max(0, width // 2 - pw // 2) + pw - 1,
            max(0, horizon - ph - 1) + ph - 1)


# -- the region pickers -----------------------------------------------------


def _candidate_boxes(
    rng: np.random.Generator,
    width: int,
    height: int,
    scale: tuple[float, float],
) -> list[tuple[int, int, int, int]]:
    """A handful of plausible rectangles of a plausible size."""
    bw = max(8, int(width * rng.uniform(*scale)))
    bh = max(8, int(height * rng.uniform(*scale)))
    boxes: list[tuple[int, int, int, int]] = []
    for _ in range(28):
        x0 = int(rng.integers(0, max(1, width - bw)))
        y0 = int(rng.integers(0, max(1, height - bh)))
        boxes.append((x0, y0, x0 + bw - 1, y0 + bh - 1))
    return boxes


def _interior_boxes(
    rng: np.random.Generator,
    width: int,
    height: int,
    scale: tuple[float, float],
) -> list[tuple[int, int, int, int]]:
    """Like :func:`_candidate_boxes`, but away from the frame's border."""
    bw = max(8, int(width * rng.uniform(*scale)))
    bh = max(8, int(height * rng.uniform(*scale)))
    boxes: list[tuple[int, int, int, int]] = []
    for _ in range(28):
        x0 = int(rng.integers(0, max(1, width - bw - 4)))
        y0 = int(rng.integers(0, max(1, height - bh - 4)))
        boxes.append((x0 + 2, y0 + 2, x0 + bw - 1, y0 + bh - 1))
    return boxes


def _pick_textured(
    vmap: np.ndarray, boxes: list[tuple[int, int, int, int]]
) -> tuple[int, int, int, int]:
    """The box with the most local detail — where an object would be."""
    best = boxes[0]
    best_score = -1.0
    for box in boxes:
        x0, y0, x1, y1 = box
        score = float(vmap[y0 : y1 + 1, x0 : x1 + 1].mean())
        if score > best_score:
            best_score = score
            best = box
    return best


def _pick_smooth(
    vmap: np.ndarray, boxes: list[tuple[int, int, int, int]]
) -> tuple[int, int, int, int]:
    """The box with the least local detail — where empty sky would be."""
    best = boxes[0]
    best_score = float("inf")
    for box in boxes:
        x0, y0, x1, y1 = box
        score = float(vmap[y0 : y1 + 1, x0 : x1 + 1].mean())
        if score < best_score:
            best_score = score
            best = box
    return best


def _pick_bright(
    vmap: np.ndarray,
    lmap: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """The brightest box that still holds a textured surface.

    A defect needs a lit surface to be seen on: a hole in a shadow is not a
    hole, it is a shadow. ``None`` when the frame has no lit surface at all
    — the two river frames of the sweep are dark water, and a hole in dark
    water is black on black.
    """
    best: tuple[int, int, int, int] | None = None
    best_score = -1.0
    for box in boxes:
        x0, y0, x1, y1 = box
        if float(vmap[y0 : y1 + 1, x0 : x1 + 1].mean()) < HOLE_MIN_TEXTURE:
            continue
        score = float(lmap[y0 : y1 + 1, x0 : x1 + 1].mean())
        if score < HOLE_MIN_LUMA:
            continue
        if score > best_score:
            best_score = score
            best = box
    return best


def _pick_furthest(
    donor: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    host_mean: np.ndarray,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """The donor region whose colour is least like the host region's.

    Visibility first: a swap between two pictures that look alike is
    invisible, and an invisible defect is a free false negative.
    """
    best = boxes[0]
    best_distance = -1.0
    for box in boxes:
        x0, y0, x1, y1 = box
        region = donor[y0 : min(y1 + 1, y0 + height), x0 : min(x1 + 1, x0 + width), :]
        if region.size == 0:
            continue
        mean = region.reshape(-1, 3).mean(axis=0)
        distance = float(np.linalg.norm(mean - host_mean))
        if distance > best_distance:
            best_distance = distance
            best = box
    return best


def _pick_contrasting(
    image: np.ndarray,
    patch: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    *,
    vmap: np.ndarray | None = None,
    alpha: np.ndarray | None = None,
    occupied: np.ndarray | None = None,
    avoid: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """The region the copy lands in — empty, smooth, and contrasting with it.

    The copy has to be *visible* against what it lands on (so the defect is
    not a free false negative), it has to land in empty space (so it reads
    as floating rather than as part of the ground), and it has to land
    clear of everything else (so the copy does not merge with the scene
    into one shape).
    """
    ph, pw = patch.shape[:2]
    if alpha is not None and alpha.any():
        mean = patch[alpha].mean(axis=0)
    else:
        mean = patch.reshape(-1, 3).mean(axis=0)
    scored: list[tuple[tuple[int, int, float], tuple[int, int, int, int]]] = []
    for box in boxes:
        x0, y0, x1, y1 = box
        if x1 - x0 + 1 < pw or y1 - y0 + 1 < ph:
            continue
        if avoid is not None and not (
            x0 > avoid[2] or x1 < avoid[0] or y0 > avoid[3] or y1 < avoid[1]
        ):
            continue  # do not paste the object on top of itself
        busy = 0.0
        if vmap is not None:
            busy = float(vmap[y0 : y0 + ph, x0 : x0 + pw].mean())
        taken = 0.0
        if occupied is not None:
            window = occupied[y0 : y0 + ph, x0 : x0 + pw]
            if alpha is not None and alpha.any():
                taken = float(window[alpha].mean())
            else:
                taken = float(window.mean())
        region = image[y0 : y0 + ph, x0 : x0 + pw, :]
        if region.size == 0:
            continue
        other = region.reshape(-1, 3).mean(axis=0)
        distance = float(np.linalg.norm(mean - other))
        # Empty first, then smooth, then the most visible.
        key = (int(taken > 0.02), int(busy > FLOAT_SMOOTH_MAX), -distance)
        scored.append((key, box))
    if not scored:
        return boxes[0]
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _boxes_of_size(
    rng: np.random.Generator,
    width: int,
    height: int,
    box_width: int,
    box_height: int,
    count: int = 48,
) -> list[tuple[int, int, int, int]]:
    """Random rectangles of exactly the given size, inside the frame."""
    boxes: list[tuple[int, int, int, int]] = []
    for _ in range(count):
        x0 = int(rng.integers(0, max(1, width - box_width)))
        y0 = int(rng.integers(0, max(1, height - box_height)))
        boxes.append((x0, y0, x0 + box_width - 1, y0 + box_height - 1))
    return boxes


def _empty_mask(image: np.ndarray) -> np.ndarray:
    """The frame's foreground mask — what is *not* empty space."""
    from .imaging import box_mean

    g = luma(image)
    return np.abs(g - box_mean(g, 31)) > 0.05


def _pick_object(
    image: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """The frame's most object-like thing, as pixels and a mask.

    An object is not a textured patch — a flat patch of noisy ground is
    textured too. What makes an object is that it differs from what is
    around it, so the object is taken from the frame's foreground mask and
    lifted with its shape, not with its bounding box: a tree's crown is
    mostly sky, and pasting its box would paste the sky with it.
    """
    from .imaging import components

    g = luma(image)
    # The object is taken from the same mask the check looks at: a region
    # that differs from its local mean, which finds a thing's **edges**.
    # The copy keeps the shape the edges enclose — a tree's crown is a ring
    # of pixels around a lot of sky, and the sky inside it has to come
    # with it or the copy is a hollow ring of leaves.
    background = box_mean(g, 31)
    mask = np.abs(g - background) > FLOAT_BACKGROUND_DELTA
    labels, found = components(mask)
    h, w = g.shape
    total = h * w
    usable = [
        c
        for c in found
        if 0.002 * total <= c.size <= 0.05 * total
        and c.x0 > 0
        and c.y0 > 0
        and c.x1 < w - 1
        and c.y1 < h - 1
    ]
    if not usable:
        return None
    # An object, not a column: a trunk or a cliff is not what a person
    # would call "the thing that is floating in the air".
    compact = [
        c
        for c in usable
        if 0.4 <= c.width / float(max(1, c.height)) <= 2.5
        and c.size <= 0.03 * total
    ]
    pool = compact or usable
    # The copy has to carry **detail**: a smooth patch of the frame is not
    # an object, and pasted into a smooth sky it is invisible. The measurement
    # said so — fifteen of the forty-one plants produced no foreground blob
    # at all, because the copy was a smooth patch. The detail is measured
    # over the object's own pixels, not over its box: a tree's crown is
    # mostly sky, and its box says nothing about the crown.
    detail = local_std(g, 9)
    textured = []
    for c in pool:
        window = detail[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1]
        shape = labels[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1] == c.label
        if not shape.any():
            continue
        # The *whole* copy has to carry detail, not just its busiest part:
        # a copy made of a few detailed specks and a lot of smooth pixels
        # breaks into pieces when the critic looks for it.
        values = window[shape]
        if float(np.percentile(values, 25)) >= FLOAT_MIN_TEXTURE:
            textured.append(c)
    pool = textured or pool
    pool.sort(key=lambda c: (-c.size, abs((c.x0 + c.x1) / 2 - w / 2)))
    c = pool[0]
    patch = image[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1, :].copy()
    alpha = _fill_holes(labels[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1] == c.label)
    return patch, alpha


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """A mask plus the holes inside it.

    The background regions that do not reach the mask's border are inside
    the shape, and they belong to it.
    """
    from .imaging import components

    if mask.size == 0:
        return mask
    inverse = ~mask
    labels, found = components(inverse)
    filled = mask.copy()
    height, width = mask.shape
    for comp in found:
        if comp.x0 == 0 or comp.y0 == 0 or comp.x1 >= width - 1 or comp.y1 >= height - 1:
            continue  # it reaches the border: it is outside the shape
        filled[labels == comp.label] = True
    return filled
