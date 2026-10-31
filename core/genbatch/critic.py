"""The scripted critic: the judgement that picks the night's winner.

Every check is **graded** from 0 to 1 rather than passed or failed, and the
prop's score is the weighted mean of them. That matters: three props that
all fail the same check would otherwise all score zero, and the "winner"
would be whichever the loop happened to see first. A graded check keeps
telling them apart.

The checks, in the order the brief names them and the order SolidCraft's
oracle set uses:

* **watertightness** — the prop is a closed, consistently wound solid with a
  positive volume. A hole or a flipped triangle and it is not a solid, so
  this one is all or nothing.
* **triangle_budget** — the prop stays inside the triangle budget the
  request set.
* **bbox_aspect** — the prop's proportions are the ones asked for. Only
  checked when the request states a shape; TRELLIS.2 normalises a prop's
  size away, so the proportions are the only part of the shape a generated
  prop can be held to.
* **solid_volume** — the prop fills its own bounding box like a solid, not
  like a shell, and its volume does not exceed its box.
* **surface** — the oracle check: a closed solid cannot have less surface
  than a sphere of the same volume, so a mesh that does is not measuring
  what it thinks it is.
* **centre_of_mass** — the prop's mass sits inside its own box, and near
  the middle of it.
* **degenerate** — the prop has no triangles of no area.
"""

from __future__ import annotations

import math
from typing import Mapping

from core.night.iterate import CriticScore, Variant
from core.records import Task

from core.genbatch.mesh import MeshReport
from core.genbatch.models import CheckResult, PropRequest, PropVerdict
from core.genbatch.store import PropStore

__all__ = ["CHECK_WEIGHTS", "PropCritic", "judge"]

#: How much each check counts for.
CHECK_WEIGHTS: dict[str, float] = {
    "watertight": 3.0,
    "triangle_budget": 2.0,
    "bbox_aspect": 2.0,
    "solid_volume": 2.0,
    "surface": 1.0,
    "centre_of_mass": 1.0,
    "degenerate": 1.0,
}

#: A sphere is the tightest bound on a solid's surface for its volume:
#: ``4 * pi * r^2 / ((4/3) * pi * r^3)^(2/3) = 4.836``.
_SPHERE_RATIO = 4.836
#: The floor below which a closed solid's surface cannot plausibly be.
_MIN_SURFACE_RATIO = 3.0


def _normalise(extent: tuple[float, float, float]) -> tuple[float, float, float]:
    """Scale an extent so its largest axis is one."""
    largest = max(extent)
    if largest <= 0:
        return (0.0, 0.0, 0.0)
    return tuple(axis / largest for axis in extent)


def _check_watertight(report: MeshReport) -> CheckResult:
    weight = CHECK_WEIGHTS["watertight"]
    if report.watertight and report.consistent_winding and report.volume > 0:
        return CheckResult(
            name="watertight",
            score=1.0,
            weight=weight,
            passed=True,
            detail=(
                f"closed and consistently wound, {report.triangles:,} triangles, "
                f"volume {report.volume:.4g}"
            ),
        )
    faults: list[str] = []
    if not report.watertight:
        faults.append(
            f"{report.boundary_edges} boundary edges and "
            f"{report.nonmanifold_edges} non-manifold edges"
        )
    if not report.consistent_winding:
        faults.append("the winding is inconsistent")
    if report.volume <= 0:
        faults.append(f"volume {report.volume:.4g}")
    return CheckResult(
        name="watertight",
        score=0.0,
        weight=weight,
        passed=False,
        detail="; ".join(faults),
    )


def _check_budget(report: MeshReport, request: PropRequest) -> CheckResult:
    weight = CHECK_WEIGHTS["triangle_budget"]
    detail = (
        f"{report.triangles:,} triangles against a "
        f"{request.triangle_budget:,} budget"
    )
    if report.triangles <= request.triangle_budget:
        return CheckResult(
            name="triangle_budget",
            score=1.0,
            weight=weight,
            passed=True,
            detail=detail,
        )
    return CheckResult(
        name="triangle_budget",
        score=0.0,
        weight=weight,
        passed=False,
        detail=f"{detail} — over by {report.triangles - request.triangle_budget:,}",
    )


def _check_aspect(report: MeshReport, request: PropRequest) -> CheckResult | None:
    """The shape check. Skipped when the request states no shape."""
    expected = request.expected_aspect
    if expected is None:
        return None
    weight = CHECK_WEIGHTS["bbox_aspect"]
    measured = _normalise(report.extent)
    worst_axis = max(range(3), key=lambda i: abs(measured[i] - expected[i]) / expected[i])
    worst = abs(measured[worst_axis] - expected[worst_axis]) / expected[worst_axis]
    detail = (
        f"aspect {measured[0]:.3f}:{measured[1]:.3f}:{measured[2]:.3f} against "
        f"{expected[0]:.3f}:{expected[1]:.3f}:{expected[2]:.3f} — "
        f"{worst:.0%} off on the {'xyz'[worst_axis]} axis"
    )
    if worst <= request.aspect_tolerance:
        return CheckResult(
            name="bbox_aspect",
            score=1.0,
            weight=weight,
            passed=True,
            detail=detail,
        )
    # Grade it: the further off the shape, the worse — but two props that
    # are both wrong about the shape can still be told apart.
    score = 1.0 / (1.0 + (worst - request.aspect_tolerance))
    return CheckResult(
        name="bbox_aspect",
        score=score,
        weight=weight,
        passed=False,
        detail=detail,
    )


def _check_volume(report: MeshReport, request: PropRequest) -> CheckResult:
    weight = CHECK_WEIGHTS["solid_volume"]
    ex_x, ex_y, ex_z = report.extent
    box = ex_x * ex_y * ex_z
    if box <= 0:
        return CheckResult(
            name="solid_volume",
            score=0.0,
            weight=weight,
            passed=False,
            detail="the prop has no size",
        )
    ratio = report.volume / box
    low, high = request.fill_ratio
    if ratio < low:
        return CheckResult(
            name="solid_volume",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the volume is {ratio:.3%} of its own bounding box — "
                f"a shell, not a solid"
            ),
        )
    if ratio > high + 1e-9:
        return CheckResult(
            name="solid_volume",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the volume is {ratio:.3%} of its own bounding box — "
                f"a solid cannot be larger than the box around it"
            ),
        )
    return CheckResult(
        name="solid_volume",
        score=1.0,
        weight=weight,
        passed=True,
        detail=f"the volume is {ratio:.1%} of its own bounding box",
    )


def _check_surface(report: MeshReport) -> CheckResult:
    weight = CHECK_WEIGHTS["surface"]
    if report.volume <= 0:
        return CheckResult(
            name="surface",
            score=0.0,
            weight=weight,
            passed=False,
            detail="there is no volume to measure the surface against",
        )
    ratio = report.area / (report.volume ** (2.0 / 3.0))
    detail = (
        f"the surface is {ratio:.2f} times the tightest a solid of this "
        f"volume could be (a sphere is {(_SPHERE_RATIO):.2f})"
    )
    if ratio >= _SPHERE_RATIO * 0.93:
        return CheckResult(
            name="surface",
            score=1.0,
            weight=weight,
            passed=True,
            detail=detail,
        )
    score = max(0.0, (ratio - _MIN_SURFACE_RATIO) / (_SPHERE_RATIO * 0.93 - _MIN_SURFACE_RATIO))
    return CheckResult(
        name="surface",
        score=score,
        weight=weight,
        passed=False,
        detail=detail,
    )


def _check_centre_of_mass(report: MeshReport) -> CheckResult:
    weight = CHECK_WEIGHTS["centre_of_mass"]
    centre = tuple(
        (report.bbox_min[i] + report.bbox_max[i]) / 2.0 for i in range(3)
    )
    com = report.centre_of_mass
    slack = 1e-9 + 1e-6 * report.diagonal
    inside = all(
        report.bbox_min[i] - slack <= com[i] <= report.bbox_max[i] + slack
        for i in range(3)
    )
    if not inside:
        return CheckResult(
            name="centre_of_mass",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the centre of mass ({com[0]:.3f}, {com[1]:.3f}, {com[2]:.3f}) "
                "is outside the prop's own bounding box"
            ),
        )
    if report.diagonal <= 0:
        return CheckResult(
            name="centre_of_mass",
            score=1.0,
            weight=weight,
            passed=True,
            detail="the prop has no size to be lopsided about",
        )
    distance = math.dist(com, centre) / (0.5 * report.diagonal)
    score = max(0.0, 1.0 - distance)
    return CheckResult(
        name="centre_of_mass",
        score=score,
        weight=weight,
        passed=score >= 0.5,
        detail=(
            f"the centre of mass sits {distance:.0%} of the way from the "
            "middle of the box towards its corner"
        ),
    )


def _check_degenerate(report: MeshReport) -> CheckResult:
    weight = CHECK_WEIGHTS["degenerate"]
    if report.triangles == 0:
        return CheckResult(
            name="degenerate",
            score=0.0,
            weight=weight,
            passed=False,
            detail="the prop has no triangles",
        )
    ratio = report.degenerate_triangles / report.triangles
    return CheckResult(
        name="degenerate",
        score=1.0 - ratio,
        weight=weight,
        passed=report.degenerate_triangles == 0,
        detail=(
            f"{report.degenerate_triangles:,} of {report.triangles:,} "
            "triangles have no area"
        ),
    )


def judge(report: MeshReport, request: PropRequest) -> PropVerdict:
    """Judge one measured prop against the request that asked for it."""
    checks = [
        _check_watertight(report),
        _check_budget(report, request),
        _check_aspect(report, request),
        _check_volume(report, request),
        _check_surface(report),
        _check_centre_of_mass(report),
        _check_degenerate(report),
    ]
    checks = [check for check in checks if check is not None]
    weight = sum(check.weight for check in checks)
    score = sum(check.weight * check.score for check in checks) / weight if weight else 0.0
    failed = [check for check in checks if not check.passed]
    reason = (
        "; ".join(f"{check.name}: {check.detail}" for check in failed)
        if failed
        else "every check passed"
    )
    return PropVerdict(
        score=score,
        checks=checks,
        reason=reason,
        degraded=any(check.score < 1.0 for check in checks),
    )


class PropCritic:
    """The critic, wired to the core's ``Critic`` seam.

    The core's runner asks "how good is this variant?" after the executor has
    run it. This asks the store what the executor measured and judges that.
    A variant the store never heard of scores zero — a score nobody measured
    must never win a variant by accident.
    """

    def __init__(
        self,
        requests: Mapping[str, PropRequest],
        store: PropStore,
    ) -> None:
        self._requests = dict(requests)
        self._store = store

    def score(self, task: Task, variant: Variant) -> CriticScore:
        request = self._requests.get(task.id)
        if request is None:
            return CriticScore(
                score=0.0,
                reason=f"no request for task {task.id!r}",
                degraded=True,
            )
        report = self._store.mesh(task.id, variant.id)
        if report is None:
            return CriticScore(
                score=0.0,
                reason=f"no mesh was measured for variant {variant.id!r}",
                degraded=True,
            )
        verdict = judge(report, request)
        return CriticScore(
            score=verdict.score,
            reason=verdict.reason,
            degraded=verdict.degraded,
        )
