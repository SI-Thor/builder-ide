"""Experiment: the three checks that measurement says are not yet sound.

The measurement of the 39 real frames left three classes short:

* **texture_swap** — the seam statistic separates badly (clean p90 0.238,
  max 0.284; planted p50 0.102). The swap is usually *not* the frame's
  biggest rectangle-like discontinuity, so the plant has to make the swap
  plainly visible — the donor region must differ from the host region by a
  human-visible margin, or the defect is a free false negative.
* **floating_object** — 7.9 % caught. The plant lands the copy just above
  the horizon, where it reads as "a prop on the skyline" rather than as
  "a prop in the air", and where the check's clearance is barely positive.
* **holes** — 89.5 % caught; the misses need naming, not guessing.

This script measures three plant variants for each class against the real
frames and prints the separation, so the plant and the threshold are both
chosen from a number.

Run:

    .venv/bin/python core/critic/exp_recal.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic import defects  # noqa: E402
from core.critic.checks import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    _check_dark_holes,
    _check_floating_blob,
    _check_patch_seam,
    components,
    local_std,
    luma,
)
from core.critic.defects import _candidate_boxes, _pick_textured  # noqa: E402
from core.critic.harvest import harvest  # noqa: E402
from core.critic.imaging import box_mean, load_rgb  # noqa: E402


def separation(name: str, clean: list[float], planted: list[float], thresholds) -> None:
    clean = sorted(clean)
    planted = sorted(planted)
    print(f"  {name}: clean n={len(clean)} planted n={len(planted)}")
    for label, values in (("clean", clean), ("planted", planted)):
        if not values:
            continue
        print(
            f"    {label:8s} min={values[0]:.3f} p10={values[int(len(values)*0.1)]:.3f} "
            f"p50={values[len(values)//2]:.3f} p90={values[int(len(values)*0.9)]:.3f} "
            f"max={values[-1]:.3f}"
        )
    print("    threshold sweep (clean are false positives, planted are catches):")
    for threshold in thresholds:
        fp = sum(1 for v in clean if v >= threshold)
        tp = sum(1 for v in planted if v >= threshold)
        print(
            f"      >= {threshold:5.3f}: clean {fp:3d}/{len(clean):3d} "
            f"({fp/max(1,len(clean)):5.1%}), planted {tp:3d}/{len(planted):3d} "
            f"({tp/max(1,len(planted)):5.1%})"
        )


# -- texture swap ------------------------------------------------------------


def host_box(image: np.ndarray, rng: np.random.Generator) -> tuple[int, int, int, int]:
    h, w, _ = image.shape
    vmap = local_std(luma(image), 9)
    return _pick_textured(vmap, _candidate_boxes(rng, w, h, defects.SWAP_SCALE))


def swap_v1(image, donor, rng):
    """The current plant: a random host, the donor's farthest of 28."""
    return defects._plant_texture_swap(image, donor, rng, "d")


def swap_v2(image, donor, rng, candidates: int = 400):
    """A host box and the donor region that differs from it the most.

    The visibility rule: the donor region's mean colour must differ from
    the host's by at least a stated margin — a swap between two patches
    that look alike is not a defect anybody could see.
    """
    h, w, _ = image.shape
    dh, dw, _ = donor.shape
    x0, y0, x1, y1 = host_box(image, rng)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    host = image[y0 : y1 + 1, x0 : x1 + 1, :].reshape(-1, 3).mean(axis=0)
    boxes = _candidate_boxes(rng, dw, dh, defects.SWAP_SCALE)
    boxes = boxes + _candidate_boxes(rng, dw, dh, defects.SWAP_SCALE)
    boxes = boxes + _candidate_boxes(rng, dw, dh, defects.SWAP_SCALE)
    best = None
    best_distance = -1.0
    for bx0, by0, bx1, by1 in boxes:
        region = donor[by0 : by1 + 1, bx0 : bx1 + 1, :]
        if region.size == 0:
            continue
        distance = float(np.linalg.norm(region.reshape(-1, 3).mean(axis=0) - host))
        if distance > best_distance:
            best_distance = distance
            best = (bx0, by0, bx1, by1)
    if best is None:
        return None, 0.0
    sx0, sy0, sx1, sy1 = best
    sx1 = min(sx1, sx0 + bw - 1)
    sy1 = min(sy1, sy0 + bh - 1)
    patch = donor[sy0 : sy1 + 1, sx0 : sx1 + 1, :]
    out = image.copy()
    out[y0 : y0 + patch.shape[0], x0 : x0 + patch.shape[1], :] = patch
    return out, best_distance


def swap_v3(image, rng, candidates: int = 400):
    """A swap **within** the frame: the two regions that differ the most.

    A texture swap is a swap: the wrong patch of the picture is bound to a
    surface. Taking both patches from the same frame keeps the defect real
    and makes the visibility margin a property of the frame, not of the
    donor's luck.
    """
    h, w, _ = image.shape
    boxes = _candidate_boxes(rng, w, h, defects.SWAP_SCALE) * 14
    means = []
    for bx0, by0, bx1, by1 in boxes:
        region = image[by0 : by1 + 1, bx0 : bx1 + 1, :]
        if region.size == 0:
            continue
        means.append((region.reshape(-1, 3).mean(axis=0), (bx0, by0, bx1, by1)))
    if len(means) < 2:
        return None, 0.0
    best = None
    best_distance = -1.0
    for i, (mean_a, box_a) in enumerate(means):
        for mean_b, box_b in means[i + 1 :]:
            if abs(box_a[0] - box_b[0]) < 40 or abs(box_a[1] - box_b[1]) < 40:
                continue
            distance = float(np.linalg.norm(mean_a - mean_b))
            if distance > best_distance:
                best_distance = distance
                best = (box_a, box_b)
    if best is None:
        return None, 0.0
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = best
    patch = image[by0 : by1 + 1, bx0 : bx1 + 1, :].copy()
    ph, pw = patch.shape[:2]
    out = image.copy()
    out[ay0 : min(ay0 + ph, h), ax0 : min(ax0 + pw, w), :] = patch[
        : min(ay0 + ph, h) - ay0, : min(ax0 + pw, w) - ax0
    ]
    return out, best_distance


# -- floating ----------------------------------------------------------------


def float_v2(image, rng, min_clearance: float = 0.25, min_contrast: float = 0.15):
    """A copy lifted into the sky, with clear sky under it.

    The visibility rule: the copy's bottom must sit at least ``min_clearance``
    frame heights above the frame's ground line, and must contrast with the
    sky it hangs in. A copy that lands on the skyline is not floating.
    """
    h, w, _ = image.shape
    lifted = defects._pick_object(image)
    if lifted is None:
        return None, 0.0, 0
    patch, alpha = lifted
    ph, pw = patch.shape[:2]
    horizon = defects._horizon(image)
    vmap = local_std(luma(image), 9)
    occupied = defects._empty_mask(image)
    mean = patch[alpha].mean(axis=0) if alpha.any() else patch.reshape(-1, 3).mean(axis=0)

    best = None
    for _ in range(400):
        x0 = int(rng.integers(1, max(2, w - pw - 1)))
        y0 = int(rng.integers(1, max(2, horizon - ph)))
        x1, y1 = x0 + pw - 1, y0 + ph - 1
        if y1 >= horizon or x0 <= 0 or y0 <= 0 or x1 >= w - 1 or y1 >= h - 1:
            continue
        clearance = (horizon - y1) / float(h)
        if clearance < min_clearance:
            continue
        below = vmap[y1 + 1 : horizon, x0 : x1 + 1]
        if below.size == 0 or float((below <= defects.FLOAT_SMOOTH_MAX).mean()) < 0.95:
            continue
        busy = float(vmap[y0 : y1 + 1, x0 : x1 + 1].mean())
        if busy > defects.FLOAT_SMOOTH_MAX:
            continue
        region = image[y0 : y1 + 1, x0 : x1 + 1, :].reshape(-1, 3)
        contrast = float(np.linalg.norm(mean - region.mean(axis=0)))
        if contrast < min_contrast:
            continue
        key = (-clearance, -contrast)
        if best is None or key < best[0]:
            best = (key, (x0, y0, x1, y1), clearance, contrast)
    if best is None:
        return None, 0.0, 0
    _, (x0, y0, x1, y1), clearance, contrast = best
    out = image.copy()
    region = out[y0 : y0 + ph, x0 : x0 + pw, :]
    region[alpha] = patch[alpha]
    out[y0 : y0 + ph, x0 : x0 + pw, :] = region
    return out, clearance, contrast


# -- holes -------------------------------------------------------------------


def hole_diagnosis(image, rng) -> str:
    """Why a planted hole was missed, if it was."""
    broken, recipe = defects.apply(
        image, defects.plan("holes", base_id="diag", seed=902)
    )
    outcome = _check_dark_holes(broken, DEFAULT_THRESHOLDS)
    if outcome.fired:
        return "caught"
    g = luma(broken)
    surface = box_mean(g, 9)
    diff = surface - g
    mask = diff > DEFAULT_THRESHOLDS.hole_delta
    labels, found = components(mask)
    reasons = []
    for cx, cy, radius in recipe["holes"]:
        window = (slice(cy - radius, cy + radius + 1), slice(cx - radius, cx + radius + 1))
        selected = labels[window] == labels[cy, cx]
        if not selected.any():
            reasons.append("no mask")
            continue
        contrast = float(diff[window][selected].mean())
        spread = float(g[window][selected].std())
        area = int(selected.sum())
        if area < DEFAULT_THRESHOLDS.hole_min_area:
            reasons.append(f"area {area}")
        elif contrast < DEFAULT_THRESHOLDS.hole_min_contrast:
            reasons.append(f"contrast {contrast:.3f}")
        elif spread > DEFAULT_THRESHOLDS.hole_uniform_std:
            reasons.append(f"spread {spread:.3f}")
        else:
            reasons.append("ok")
    return " ".join(reasons)


def main() -> int:
    bases = harvest()
    print(f"bases: {len(bases)}\n")
    images = [load_rgb(b.image_path) for b in bases]

    print("=== texture_swap: the seam statistic, per plant variant ===")
    clean_seam = [
        _check_patch_seam(image, DEFAULT_THRESHOLDS).measured["seam_delta"]
        for image in images
    ]
    def v1(image, donor, rng):
        broken, _ = swap_v1(image, donor, rng)
        return broken, 0.0

    for name, plant in (
        ("v1 current", v1),
        ("v2 farthest donor", swap_v2),
        ("v3 same-frame swap", lambda im, dn, rg: swap_v3(im, rg)),
    ):
        values = []
        distances = []
        for index, (base, image) in enumerate(zip(bases, images)):
            donor = images[(index + 1) % len(images)]
            rng = defects.rng_for(base.id, "swap-recal", 902)
            broken, distance = plant(image, donor, rng)
            if broken is None:
                values.append(0.0)
                distances.append(0.0)
                continue
            values.append(_check_patch_seam(broken, DEFAULT_THRESHOLDS).measured["seam_delta"])
            distances.append(distance)
        separation(name, clean_seam, values, (0.20, 0.25, 0.30, 0.35, 0.40, 0.50))
        print(
            f"    the swap's own colour distance: min={min(distances):.3f} "
            f"p50={sorted(distances)[len(distances)//2]:.3f} max={max(distances):.3f}"
        )

    print("\n=== floating_object: the clearance, per plant variant ===")
    clean_clearance = []
    for image in images:
        outcome = _check_floating_blob(image, DEFAULT_THRESHOLDS)
        clean_clearance.append(outcome.measured["clearance"])
    for name, plant in (
        ("v1 current", lambda im, rg: defects._plant_floating_object(im, rg)),
        ("v2 clear sky", lambda im, rg: float_v2(im, rg)),
    ):
        values = []
        fired = 0
        for base, image in zip(bases, images):
            rng = defects.rng_for(base.id, "float-recal", 902)
            if name.startswith("v2"):
                broken, clearance, contrast = plant(image, rng)
                if broken is None:
                    values.append(0.0)
                    continue
            else:
                broken, _ = plant(image, rng)
            outcome = _check_floating_blob(broken, DEFAULT_THRESHOLDS)
            values.append(outcome.measured["clearance"])
            fired += int(outcome.fired)
        print(f"  {name}: fired on {fired}/{len(values)}")
        separation(name, clean_clearance, values, (0.10, 0.15, 0.20, 0.25, 0.30, 0.40))

    print("\n=== holes: why the misses were missed ===")
    misses = 0
    for base, image in zip(bases, images):
        report = hole_diagnosis(image, defects.rng_for(base.id, "holes", 902))
        if report != "caught":
            misses += 1
            print(f"  {base.id:12s} {report}")
    print(f"  missed: {misses}/{len(bases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
