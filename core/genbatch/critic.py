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
  this one is all or nothing. It is measured on the **repaired** mesh: the
  repair stage (see :mod:`core.genbatch.repair`) welds the UV seams the
  generator leaves behind, and without it the check cannot tell a closed
  solid from an open one. The edge census itself is unchanged: Open3D's
  own watertight word also demands vertex-manifoldness and no
  self-intersection and would flip 12 of the 45 swept rows
  (docs/lab/exp-open3d-critic.md §3.1) — a semantic change this check
  deliberately does not make.
* **self_intersection** — no two triangles of the surface cross each other.
  A mesh can be closed, consistently wound, and still pass a triangle
  through its own skin: the overlap is counted twice in the signed volume
  (the reference set's storage shelf reads 3.9x its ray-parity volume), so
  a self-intersecting mesh's signed volume is flagged, not trusted, and
  the solid-volume check reads the ray-parity fallback. The check runs
  under a triangle cap
  (:data:`~core.genbatch.o3d_geometry.SELF_INTERSECTION_CAP`); above it,
  and when the ``o3d`` extra is absent, the verdict is **unchecked** with
  the reason — never a guess, and never a punishment for a measurement
  that was not made.
* **repair_fidelity** — the repair did not quietly reshape the prop: the
  silhouette IoU between the repaired mesh and the mesh the generator
  handed over.
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
from core.genbatch.models import CheckResult, PropRequest, PropVerdict, StageKind
from core.genbatch.repair import RepairReport
from core.genbatch.schedule import NightPlan
from core.genbatch.store import PropStore

__all__ = ["CHECK_WEIGHTS", "PropCritic", "judge"]

#: How much each check counts for.
CHECK_WEIGHTS: dict[str, float] = {
    "watertight": 3.0,
    # Half of watertight's weight: the two defects are neighbours but not
    # the same — a mesh can pass the edge census and still pass a triangle
    # through its own skin, and on such a mesh only this check notices.
    "self_intersection": 1.5,
    "repair_fidelity": 1.0,
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


def _check_watertight(
    report: MeshReport, repair: RepairReport | None = None
) -> CheckResult:
    """Is the prop a solid?

    The measurement is of the **repaired** mesh. A repair that did not
    succeed is a repair that cannot be trusted, and a prop that was not
    repaired cannot be called a solid at all.
    """
    weight = CHECK_WEIGHTS["watertight"]
    if repair is not None and not repair.ok:
        return CheckResult(
            name="watertight",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the repair did not succeed: {repair.reason}"
                if repair.reason
                else "the repair did not succeed"
            ),
        )
    if report.watertight and report.consistent_winding and report.volume > 0:
        detail = (
            f"closed and consistently wound, {report.triangles:,} triangles, "
            f"volume {report.volume:.4g}"
        )
        if repair is not None:
            detail += (
                f" — after welding {repair.welded_vertices:,} coincident "
                f"vertices and splitting {repair.nonmanifold_edges_split} "
                "self-crossing edges"
            )
        return CheckResult(
            name="watertight",
            score=1.0,
            weight=weight,
            passed=True,
            detail=detail,
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


def _check_self_intersection(report: MeshReport) -> CheckResult:
    """Do any two triangles of the surface cross each other?

    The one geometry defect the edge census cannot see: a mesh can be
    closed and consistently wound with a triangle passed through its own
    skin, and the overlap inflates the signed volume (counted twice). The
    check is all-or-nothing like watertightness — a pair of crossing
    triangles is a defect, not a degree of one.

    An **unchecked** verdict (the mesh over the triangle cap, or the
    ``o3d`` extra absent) neither punishes nor vouches: it passes with its
    reason, because a prop must not lose to a measurement that was never
    made. What it does change is the volume below: an unchecked mesh's
    signed volume is treated exactly as it was before the check existed.
    """
    weight = CHECK_WEIGHTS["self_intersection"]
    if report.self_intersection == "self_intersecting":
        return CheckResult(
            name="self_intersection",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"{report.self_intersection_pairs:,} pairs of triangles "
                "cross — the signed volume counts overlapped material "
                "twice and is not trusted here"
            ),
        )
    if report.self_intersection == "unchecked":
        reason = report.self_intersection_reason or "not measured on this report"
        return CheckResult(
            name="self_intersection",
            score=1.0,
            weight=weight,
            passed=True,
            detail=f"not checked — {reason}",
        )
    return CheckResult(
        name="self_intersection",
        score=1.0,
        weight=weight,
        passed=True,
        detail=f"no triangle pairs cross ({report.triangles:,} triangles checked)",
    )


def _volume_fault(report: MeshReport) -> str:
    """Why the signed volume cannot be trusted, in words."""
    faults: list[str] = []
    if not (report.watertight and report.consistent_winding):
        faults.append(
            "is measured on a surface that is not closed and consistently wound"
        )
    if report.volume <= 0:
        faults.append("is not positive")
    if report.self_intersection == "self_intersecting":
        faults.append("counts overlapped material twice")
    return "; it ".join(faults) if faults else "is unreliable"


def _check_repair_fidelity(
    repair: RepairReport | None, request: PropRequest
) -> CheckResult | None:
    """Did the repair keep the prop looking like the prop?

    The silhouette IoU between the repaired mesh and the mesh the generator
    handed over. Skipped when the repair stage was not run.
    """
    if repair is None:
        return None
    weight = CHECK_WEIGHTS["repair_fidelity"]
    floor = request.repair.min_fidelity
    fidelity = repair.fidelity
    detail = (
        f"the silhouette of the repaired prop is {fidelity:.4f} of the "
        f"original's (a floor of {floor:.2f})"
    )
    if fidelity >= floor:
        return CheckResult(
            name="repair_fidelity",
            score=1.0,
            weight=weight,
            passed=True,
            detail=detail,
        )
    # Graded: a repair that came close still says something.
    score = max(0.0, fidelity / floor) if floor > 0 else 0.0
    return CheckResult(
        name="repair_fidelity",
        score=score,
        weight=weight,
        passed=False,
        detail=detail,
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
    """The prop fills its own bounding box like a solid, not like a shell.

    Which volume that is read from depends on what can be trusted. The
    signed volume is the measurement when the surface earns it (closed,
    wound, positive, not self-intersecting). When it does not, the
    **ray-parity volume** stands in — winding-free, and the conservative
    number on a self-intersecting mesh because it does not count overlapped
    material twice — and the detail says so. When there is no fallback
    either, the check fails rather than grade a number it has just said it
    does not trust.
    """
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
    low, high = request.fill_ratio
    if report.volume_reliable:
        volume = report.volume
        note = ""
    elif report.parity_volume is not None:
        volume = report.parity_volume
        note = (
            " — the ray-parity volume stands in, because the signed volume "
            f"{_volume_fault(report)}"
        )
    else:
        return CheckResult(
            name="solid_volume",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the signed volume ({report.volume:.4g}) cannot be trusted: "
                f"it {_volume_fault(report)}; and no ray-parity fallback "
                "was measured"
            ),
        )
    ratio = volume / box
    if ratio < low:
        return CheckResult(
            name="solid_volume",
            score=0.0,
            weight=weight,
            passed=False,
            detail=(
                f"the volume is {ratio:.3%} of its own bounding box — "
                f"a shell, not a solid{note}"
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
                f"a solid cannot be larger than the box around it{note}"
            ),
        )
    return CheckResult(
        name="solid_volume",
        score=1.0,
        weight=weight,
        passed=True,
        detail=f"the volume is {ratio:.1%} of its own bounding box{note}",
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


def judge(
    report: MeshReport,
    request: PropRequest,
    repair: RepairReport | None = None,
) -> PropVerdict:
    """Judge one measured prop against the request that asked for it.

    ``repair`` is the repair stage's report, when the stage ran: the
    watertightness check is made against it, and the fidelity check reads
    the outline the repair left behind.
    """
    checks = [
        _check_watertight(report, repair),
        _check_self_intersection(report),
        _check_repair_fidelity(repair, request),
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

    The image stage is judged too, and by the only thing that can be
    measured about a picture without looking at it: that it was made, and
    that it is the size it was asked to be. A picture at the wrong size is a
    picture the mesh stage would silently mis-condition on.
    """

    def __init__(
        self,
        requests: Mapping[str, PropRequest],
        store: PropStore,
        plan: "NightPlan | None" = None,
    ) -> None:
        self._requests = dict(requests)
        self._store = store
        self._plan = plan

    def score(self, task: Task, variant: Variant) -> CriticScore:
        request = self._requests.get(task.id)
        if request is None:
            return CriticScore(
                score=0.0,
                reason=f"no request for task {task.id!r}",
                degraded=True,
            )
        if self._plan is not None and self._plan.stage_kind(task.id) == StageKind.IMAGE:
            return self._score_image(request, variant)
        report = self._store.mesh(task.id, variant.id)
        if report is None:
            return CriticScore(
                score=0.0,
                reason=f"no mesh was measured for variant {variant.id!r}",
                degraded=True,
            )
        repair = self._store.repair(task.id, variant.id)
        verdict = judge(report, request, repair)
        return CriticScore(
            score=verdict.score,
            reason=verdict.reason,
            degraded=verdict.degraded,
        )

    def _score_image(self, request: PropRequest, variant: Variant) -> CriticScore:
        seed = variant.seed if variant.seed is not None else 0
        image = self._store.image(request.id, seed)
        if image is None:
            return CriticScore(
                score=0.0,
                reason=f"no image was made for seed {seed}",
                degraded=True,
            )
        if image.width != request.image_size or image.height != request.image_size:
            return CriticScore(
                score=0.0,
                reason=(
                    f"the picture came back {image.width}×{image.height}, "
                    f"not {request.image_size}×{request.image_size}"
                ),
                degraded=True,
            )
        return CriticScore(
            score=1.0,
            reason=f"a {image.width}×{image.height} picture of {request.prompt!r}",
        )
