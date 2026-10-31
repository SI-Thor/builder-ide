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

from .imaging import border_colour, local_std, luma, paste_region

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

#: The size of the region that is swapped for another render's pixels.
SWAP_SCALE = (0.14, 0.24)

#: The size of the object that is made to float, and where it lands.
FLOAT_OBJECT_SCALE = (0.07, 0.13)

#: The most local detail an "empty" region may have for the copy to land
#: there — above this, the region is something, not sky.
FLOAT_SMOOTH_MAX = 0.02


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
    """
    h, w, _ = image.shape
    out = image.copy()
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
        value = 255 if rng.random() < 0.5 else 0
        out[y, x, :] = value
    return out, {
        "count": len(placed),
        "min_spacing": FIREFLY_MIN_SPACING,
        "values": [0, 255],
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
    """
    h, w, _ = image.shape
    vmap = local_std(luma(image), 9)
    box = _pick_textured(vmap, _candidate_boxes(rng, w, h, HOLE_REGION_SCALE))
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
    else's. The donor is a different real render from the sweep, and the
    patch is taken from the part of the donor that looks *least* like the
    host — so the defect is plainly visible rather than a subtle
    coincidence of palettes.
    """
    h, w, _ = image.shape
    dh, dw, _ = donor.shape
    vmap = local_std(luma(image), 9)
    box = _pick_textured(vmap, _candidate_boxes(rng, w, h, SWAP_SCALE))
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    host = image[y0 : y1 + 1, x0 : x1 + 1, :].reshape(-1, 3).mean(axis=0)
    donor_box = _pick_furthest(donor, _candidate_boxes(rng, dw, dh, SWAP_SCALE), host, bw, bh)
    sx0, sy0, sx1, sy1 = donor_box
    sx1 = min(sx1, sx0 + bw - 1)
    sy1 = min(sy1, sy0 + bh - 1)
    patch = donor[sy0 : sy1 + 1, sx0 : sx1 + 1, :]
    out = image.copy()
    out[y0 : y0 + patch.shape[0], x0 : x0 + patch.shape[1], :] = patch
    return out, {
        "bbox": [x0, y0, x0 + patch.shape[1] - 1, y0 + patch.shape[0] - 1],
        "donor": donor_id,
        "donor_bbox": [sx0, sy0, sx1, sy1],
    }


def _plant_floating_object(
    image: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, Any]]:
    """An object is lifted off the ground and left hanging in the air.

    The copy is of a real *object* — a region that stands out from its own
    background, so the pasted thing has the hard edge an object has — and it
    is pasted into the smoothest region of the frame, which is where the
    "sky" is whatever the camera was doing. The copy is left where it was:
    the object is now in two places at once, one of them in mid-air.
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
    vmap = local_std(luma(image), 9)
    occupied = _empty_mask(image)
    dest = _pick_contrasting(
        image,
        patch,
        _boxes_of_size(rng, w, h, pw, ph),
        vmap=vmap,
        alpha=alpha,
        occupied=occupied,
        avoid=source_box,
    )
    dx0, dy0, dx1, dy1 = dest
    dx0 = min(dx0, w - pw)
    dy0 = min(dy0, h - ph)
    out = image.copy()
    region = out[dy0 : dy0 + ph, dx0 : dx0 + pw, :]
    region[alpha] = patch[alpha]
    out[dy0 : dy0 + ph, dx0 : dx0 + pw, :] = region
    return out, {
        "source_bbox": [dx0, dy0, dx0 + pw - 1, dy0 + ph - 1],
        "dest_bbox": [dx0, dy0, dx0 + pw - 1, dy0 + ph - 1],
        "pasted_px": int(alpha.sum()),
    }


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
    from .imaging import box_mean, components

    g = luma(image)
    background = box_mean(g, 31)
    mask = np.abs(g - background) > 0.05
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
    pool.sort(key=lambda c: (-c.size, abs((c.x0 + c.x1) / 2 - w / 2)))
    c = pool[0]
    patch = image[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1, :].copy()
    alpha = labels[c.y0 : c.y1 + 1, c.x0 : c.x1 + 1] == c.label
    return patch, alpha
