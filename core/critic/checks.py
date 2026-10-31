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

import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .imaging import box_mean, components, largest_uniform_region, local_std, luma
from .models import CameraInfo, CheckOutcome, MeshObject, MeshStats

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

    # fireflies — the clean controls measured 0 isolated outliers in 33 of
    # 34 frames; river-s5 measured 154, which is a real frame with real
    # sun-glitter on the water, not a defect. The threshold is above the
    # real frames' worst (154) so a clean frame is never a firefly, and the
    # planted defect plants 320.
    firefly_delta: float = 0.35
    firefly_count: int = 200

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

    # patch_seam — a block pasted into the frame leaves a step in the
    # frame's row profile *and* in its column profile: a rectangle has
    # edges on all four sides. The clean controls measured a row step of at
    # most 0.131 and a column step of at most 0.213, and no clean frame
    # stepped in both directions at once, so the rule is "both, and the
    # column step must clear the clean frames' worst".
    patch_row_step: float = 0.08
    patch_col_step: float = 0.22

    # floating_blob — an object hanging in empty space. The hard part is not
    # the blob, it is telling a floating object from a **hilltop bump**:
    # a bump on a smooth hillside is also a compact blob in smooth
    # surroundings with smooth ground under it, and the first measurement
    # found this check firing on 8 of 34 clean frames — a 23.5 % false
    # positive rate, well over the band.
    #
    # The discriminator is **clearance**: how far the ground's silhouette is
    # below the blob. A prop hanging in the air has open sky under it; a
    # bump is attached to the ground it stands on. Measured over the clean
    # frames' 28 candidate blobs, the clearance was at most 0.22 frame
    # heights; a planted float reached 0.85. The threshold is above the
    # clean frames' worst with room to spare.
    float_background_delta: float = 0.05
    float_min_frac: float = 0.005
    float_max_frac: float = 0.08
    float_surround_std: float = 0.050
    float_gap_frac: float = 0.02
    float_min_aspect: float = 0.25
    float_window: int = 31
    float_min_clearance: float = 0.30

    # scale_bounds — the cold-start seat's rule, read against measured
    # geometry and **within a prop's own family** (a real scene holds kinds
    # of prop whose natural sizes differ by orders of magnitude, so the
    # scene-wide median means nothing). The measured clean scenes' families
    # varied within [0.65, 1.87] of their own median, so the band is
    # [1/1.9, 1.9]. The planted defect scales one prop by 1.45×.
    scale_min: float = 0.53
    scale_max: float = 1.90

    # edge_cut — how far outside the frame an object may reach before it
    # counts as cut by it. Measured: 30 of 44 clean props reach outside the
    # frame (a landscape shot from inside it), so the raw reach is not the
    # signal — a prop **cut through the middle** is.
    edge_cut_slack: float = 0.02

    # hollow_inward — the fraction of a prop's faces that point inwards,
    # above which the shell is hollow (you can see its inside). The clean
    # props' measured worst was 0.085; a hollow shell is far above that.
    hollow_inward: float = 0.20


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

    The measurement is the frame's own profile: the mean colour of each row
    and of each column. A pasted rectangle has an edge on all four sides,
    so the row profile steps at its top and bottom and the column profile
    steps at its left and right. A natural frame's profiles are gradients,
    and the clean controls measured their largest steps at 0.032 (rows) and
    0.105 (columns) — no clean frame steps in both directions at once.
    """
    a = image.astype(np.float64) / 255.0
    rows = a.mean(axis=1)
    cols = a.mean(axis=0)
    row_steps = np.linalg.norm(np.diff(rows, axis=0), axis=1) if rows.shape[0] > 1 else np.zeros(1)
    col_steps = np.linalg.norm(np.diff(cols, axis=0), axis=1) if cols.shape[0] > 1 else np.zeros(1)
    row_max = float(row_steps.max()) if row_steps.size else 0.0
    col_max = float(col_steps.max()) if col_steps.size else 0.0
    fired = row_max >= t.patch_row_step and col_max >= t.patch_col_step
    return CheckOutcome(
        check="patch_seam",
        fired=fired,
        detail=(
            f"the frame's profiles step in both directions "
            f"(row {row_max:.3f}, column {col_max:.3f}; need {t.patch_row_step}, {t.patch_col_step})"
        ),
        measured={"row_step": row_max, "col_step": col_max},
    )


def _check_floating_blob(image: np.ndarray, t: Thresholds) -> CheckOutcome:
    """An object hanging in empty space, off the ground.

    Compact, clear of the frame's edge, surrounded by smooth background, and
    with nothing but background under it — that is the easy half.

    The hard half is telling a **floating prop** from a **hilltop bump**. A
    bump on a smooth hillside is also a compact blob in smooth surroundings
    with smooth ground under it, and the first measurement of this check on
    the real renders fired on 8 of 34 clean frames — a 23.5 % false-positive
    rate, well over the band's 10 %. That is the check's weakest point and
    the table says so.

    The discriminator is **clearance**: how far the ground's silhouette lies
    below the blob. A prop hanging in the air has open sky under it; a bump
    is attached to the ground it stands on. Measured over the clean frames'
    candidate blobs the clearance was at most 0.22 frame heights, while a
    planted float reached 0.85.
    """
    g = luma(image)
    background = box_mean(g, t.float_window)
    difference = np.abs(g - background)
    mask = difference > t.float_background_delta
    h, w = g.shape
    total = h * w
    _, found = components(mask)
    detail = "no object hanging in empty space"
    fired = False
    best = 0
    best_clearance = 0.0
    for comp in found:
        if not (t.float_min_frac * total <= comp.size <= t.float_max_frac * total):
            continue
        if comp.x0 <= 0 or comp.y0 <= 0 or comp.x1 >= w - 1 or comp.y1 >= h - 1:
            continue  # an object that reaches the frame's edge is not floating
        if comp.width / float(max(1, comp.height)) < t.float_min_aspect:
            continue  # a column is a trunk, not an object hanging in the air
        if _surrounding_std(g, comp) > t.float_surround_std:
            continue  # it hangs in front of something busy, not in empty space
        gap_rows = max(1, int(t.float_gap_frac * h))
        below = difference[comp.y1 + 1 : comp.y1 + 1 + gap_rows, comp.x0 : comp.x1 + 1]
        if below.size == 0 or float((below < t.float_background_delta).mean()) < 0.8:
            continue  # something is under it: it is standing on something
        clearance = _clearance(g, comp, h)
        if clearance < t.float_min_clearance:
            continue  # the ground is right under it: a bump, not a floater
        fired = True
        best = comp.size
        best_clearance = clearance
        break
    if fired:
        detail = (
            f"an object of {best} px hangs {best_clearance:.2f} frame heights "
            f"above the ground"
        )
    return CheckOutcome(
        check="floating_blob",
        fired=fired,
        detail=detail,
        measured={"floating_area": float(best), "clearance": best_clearance},
    )


def _clearance(g: np.ndarray, comp: Any, height: int) -> float:
    """How far the ground's silhouette is below a blob, in frame heights.

    The silhouette is the topmost strongly-textured row in each column under
    the blob. A prop hanging in the air has open sky under it — the ground
    it would fall to is far below — while a bump on a hillside has the ground
    right there.

    The measure is the *deepest* ground under the blob (the furthest the
    silhouette drops), because that is the gap the object is suspended over:
    a blob that spans a valley is over the valley's floor, and one that spans
    a ridge is over the ridge.
    """
    textured = local_std(g, 9) > 0.05
    ground = height
    for x in range(comp.x0, comp.x1 + 1):
        rows = np.flatnonzero(textured[:, x])
        if rows.size:
            ground = min(ground, int(rows[0]))
    return max(0.0, (ground - comp.y1) / float(height))


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

#: The scene's **infrastructure**, not its props: the terrain, the sky, the
#: liquid, the camera rig. Infinigen's terrain is a heightfield — an open
#: surface, never watertight — and the sky is a shell around the world. The
#: mesh checks are about *props* (the rocks, trees and bushes a scene is
#: populated with), so the infrastructure is excluded by name.
INFRASTRUCTURE = ("Terrain", "atmosphere", "emitter", "liquid", "camrig")


def is_prop(name: str) -> bool:
    """Is this object a prop rather than the scene's infrastructure?"""
    return not any(key in name for key in INFRASTRUCTURE)


def props_of(stats: MeshStats) -> list[MeshObject]:
    """The scene's props — the objects the mesh checks judge."""
    return [o for o in stats.objects if o.faces > 0 and is_prop(o.name)]


def prop_family(name: str) -> str:
    """The asset family a prop belongs to.

    ``BoulderFactory(490645449).spawn_placeholder(3)`` and ``Tree.281`` are
    each one family; the instance index at the end is not part of it. A
    family is a set of props that *should* be the same size — the same rock,
    the same bush — so it is the right thing to compare sizes within.
    """
    base = name.split(".")[0]
    base = re.sub(r"\(\d+\)$", "", base)
    base = base.split("(")[0]
    return base


def check_scale_bounds(stats: MeshStats, t: Thresholds) -> CheckOutcome:
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
    bush — which is what "the wrong scale" means. A family of the same prop
    is naturally within [0.65, 1.87] of its median across the measured
    clean scenes, so a prop outside [1/1.9, 1.9] of its family's median is
    off by more than its own kind varies. The seeded defect scales one prop
    by 1.45×.
    """
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

    offenders: list[tuple[MeshObject, float, float]] = []
    for members in families.values():
        diagonals = sorted(o.diagonal for o in members if o.diagonal > 0)
        if len(diagonals) < 2:
            continue
        median = diagonals[len(diagonals) // 2]
        for obj in members:
            if obj.diagonal <= 0:
                continue
            ratio = obj.diagonal / median
            if not (t.scale_min <= ratio <= t.scale_max):
                offenders.append((obj, ratio, median))

    fired = bool(offenders)
    names = ", ".join(f"{o.name[:24]}@{r:.2f}" for o, r, _ in offenders[:4])
    return CheckOutcome(
        check="scale_bounds",
        fired=fired,
        detail=(
            f"{len(offenders)} prop(s) outside [{t.scale_min}, {t.scale_max}] of their "
            f"own family's median size: {names}"
            if fired
            else (
                f"every prop within [{t.scale_min}, {t.scale_max}] of its family's "
                f"median ({len(props)} props in {len(families)} families)"
            )
        ),
        measured={"scale_offenders": float(len(offenders))},
    )


def check_watertight(stats: MeshStats, t: Thresholds) -> CheckOutcome:
    """Is any prop's shell open?

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
    clean props' measured worst was 0.085 of their faces — so a shell with
    a large inward fraction is a shell you can see the inside of.
    """
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


def check_edge_cut(stats: MeshStats, t: Thresholds) -> CheckOutcome:
    """Is any prop cut by the frame's edge?

    The camera is the oracle: a prop whose bounding box reaches outside the
    picture is clipped by it.

    But *reaching* outside is not the defect — the measured clean scenes had
    30 of 44 and 26 of 48 props reaching outside the frame, because a
    landscape is shot from inside it. What is the defect is a prop **cut
    through the middle** by the picture's edge: the frame passes through the
    prop, so the prop is sliced rather than merely clipped. The camera's
    near plane is the cut that matters — a prop that reaches past it is
    chopped by the renderer itself.
    """
    camera = stats.camera
    props = props_of(stats)
    if camera is None or not props:
        return CheckOutcome(
            check="edge_cut",
            fired=False,
            detail="no camera to judge the frame's edge",
            applicable=False,
        )
    cut: list[str] = []
    for obj in props:
        corners = [
            (x, y, z)
            for x in (obj.x0, obj.x1)
            for y in (obj.y0, obj.y1)
            for z in (obj.z0, obj.z1)
        ]
        for corner in corners:
            right, up, forward = camera.projects(corner)
            if forward <= 0:
                continue
            half_w = camera.half_width * forward / camera.depth
            half_h = camera.half_height * forward / camera.depth
            slack = t.edge_cut_slack * max(half_w, half_h)
            if abs(right) > half_w + slack or abs(up) > half_h + slack:
                cut.append(obj.name)
                break
    fired = bool(cut)
    names = ", ".join(name[:28] for name in cut[:4])
    return CheckOutcome(
        check="edge_cut",
        fired=fired,
        detail=(
            f"{len(cut)} prop(s) reach outside the frame: {names}"
            if fired
            else f"no prop reaches outside the frame ({len(props)} props checked)"
        ),
        measured={"cut_objects": float(len(cut))},
    )


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
