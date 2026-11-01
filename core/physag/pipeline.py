"""The loop, run per prop: plan, build, check, repair once, record.

This is the seat's whole mechanism in one function, and the order is the
brief's order:

1. the mesh is segmented into the spec's parts, and the split is measured;
2. each part is decomposed into convex pieces, and the pieces are checked
   against the mesh;
3. the model is written, and the action is executed in MuJoCo;
4. if the action did not complete, the check's measurements and a render
   go back to the planner, which returns a revised spec — with the action
   and the joint limits frozen;
5. the record is written.

The repair round runs **at most once**. A second round would let the
planner keep changing the prop until the check happened to pass, and the
completion rate would then measure the planner's persistence rather than
the prop's mechanics.

Nothing in this module needs a GPU. The mesh is the only thing that came
from one, and it arrives as a file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.physag.check import CheckResult, check_prop
from core.physag.decompose import Decomposition, decompose_part
from core.physag.delivery import Delivery, build_delivery
from core.physag.geometry import MeshPart, load_mesh
from core.physag.mjcf import BuiltProp, build_mjcf
from core.physag.planner import Planner, RepairFeedback
from core.physag.segment import Segmentation, segment
from core.physag.spec import InteractionSpec

__all__ = ["PropRun", "run_prop"]


@dataclass(frozen=True)
class PropRun:
    """Everything one prop's run produced."""

    prop: str
    spec: InteractionSpec
    built: BuiltProp | None
    segmentation: Segmentation | None
    decompositions: dict[str, Decomposition]
    result: CheckResult | None
    repair: dict[str, Any] | None
    timings: dict[str, float]
    counted: bool
    notes: tuple[str, ...] = ()

    @property
    def completed(self) -> bool:
        return bool(self.result and self.result.completion and self.result.completion.completed)

    @property
    def stable(self) -> bool:
        return bool(self.result and self.result.stability and self.result.stability.stable)


def _decompose_all(
    segmentation: Segmentation,
    spec: InteractionSpec,
    tolerance_m: float,
    max_pieces: int,
) -> dict[str, Decomposition]:
    """Every part's convex pieces, clipped to the part's own half-space."""
    out: dict[str, Decomposition] = {}
    size = segmentation.mesh.bbox_size
    for part in spec.parts:
        piece = segmentation.pieces[part.name]
        decomp = decompose_part(
            piece.part,
            part.name,
            tol_m=tolerance_m,
            max_pieces=max_pieces,
        )
        out[part.name] = _clip_to_part(decomp, part, spec, size, piece.part)
    return out


def _clip_to_part(decomp: Decomposition, part, spec, size, material: MeshPart) -> Decomposition:
    """Clip a part's pieces to the region the part owns.

    Every cut in the spec is a boundary between two parts, and each part's
    collider has to stay on its own side of it. Without this the pieces of
    two parts share space at the cut — a chest's rim bulges above the
    plane the lid was cut on — and the simulation reports an
    interpenetration that the builder made rather than the prop.

    The base is clipped too. It is "whatever is left", and what is left is
    on the other side of every other part's cut.
    """
    import numpy as np

    from core.physag.decompose import clip_convex
    from core.physag.geometry import distance_to_union

    clipped = []
    for piece in decomp.colliders:
        current = piece
        for other in spec.parts:
            cut = other.cut
            if cut.kind == "rest":
                continue
            axis = {"x": 0, "y": 1, "z": 2}[cut.axis]
            at = cut.at * size[axis]
            if cut.kind == "plane":
                if other.name == part.name:
                    # The part keeps the side its own cut claims.
                    if cut.keep == "above":
                        normal = np.zeros(3)
                        normal[axis] = -1.0
                        current = clip_convex(current, normal, at)
                    else:
                        normal = np.zeros(3)
                        normal[axis] = 1.0
                        current = clip_convex(current, normal, -at)
                else:
                    # Everything else keeps the other side.
                    if cut.keep == "above":
                        normal = np.zeros(3)
                        normal[axis] = 1.0
                        current = clip_convex(current, normal, -at)
                    else:
                        normal = np.zeros(3)
                        normal[axis] = -1.0
                        current = clip_convex(current, normal, at)
            else:  # a box cut
                lo = np.asarray(cut.min) * size
                hi = np.asarray(cut.max) * size
                owner = other.name == part.name
                for index in range(3):
                    normal = np.zeros(3)
                    normal[index] = -1.0
                    if owner:
                        # Inside the box: x >= lo and x <= hi.
                        current = clip_convex(current, normal, lo[index])
                        current = clip_convex(current, -normal, -hi[index])
                    else:
                        # Outside the box: x <= lo and x >= hi.
                        current = clip_convex(current, -normal, -lo[index])
                        current = clip_convex(current, normal, hi[index])
        clipped.append(current)

    kept = [c for c in clipped if not c.is_empty]
    if not kept:
        return decomp
    volume = float(sum(c.volume for c in kept))

    # The deviation is measured after the clip, against the material the
    # collider stands for: the clearance at the cut is part of it, and the
    # clearance is a known, recorded number.
    #
    # The distance is to the **union** of the pieces, not to each piece: a
    # vertex that one piece covers is covered, however far it is from the
    # *other* pieces' surfaces. Measuring to each piece and taking the worst
    # would report a vertex as far from the collider when the collider is
    # standing right there.
    deviation = 0.0
    p95 = 0.0
    if material is not None and not material.is_empty:
        planes = [piece.planes for piece in kept if piece.planes.shape[0] > 0]
        if planes:
            distances = distance_to_union(material.vertices, planes)
            finite = distances[np.isfinite(distances)]
            if finite.size:
                deviation = float(finite.max())
                p95 = float(np.percentile(finite, 95))

    return Decomposition(
        part_name=decomp.part_name,
        colliders=tuple(kept),
        hull_volume=decomp.hull_volume,
        collider_volume=volume,
        deviation_m=deviation,
        deviation_p95_m=p95,
        overlaps=decomp.overlaps,
        notes=decomp.notes,
    )


def run_prop(
    spec: InteractionSpec,
    mesh_path: str | Path,
    *,
    out_dir: str | Path | None = None,
    planner: Planner | None = None,
    decomposition_tolerance_m: float = 0.004,
    max_pieces: int = 24,
    epsilon_rel: float = 0.005,
    rest_s: float = 2.0,
    arm: str = "trellis",
    allow_repair: bool = True,
    mesh_provenance: dict[str, Any] | None = None,
    ground_truth: dict[str, Any] | None = None,
) -> PropRun:
    """Run one prop through the whole loop."""
    out_dir = Path(out_dir) if out_dir else Path("artifacts/physag-lite") / spec.prop
    out_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    timings: dict[str, float] = {}

    # -- build ------------------------------------------------------------
    started = time.perf_counter()
    mesh = load_mesh(mesh_path)
    timings["load_mesh_s"] = time.perf_counter() - started

    started = time.perf_counter()
    segmentation = segment(mesh, spec)
    timings["segment_s"] = time.perf_counter() - started

    started = time.perf_counter()
    decompositions = _decompose_all(segmentation, spec, decomposition_tolerance_m, max_pieces)
    timings["decompose_s"] = time.perf_counter() - started

    started = time.perf_counter()
    built = build_mjcf(spec, segmentation, decompositions)
    timings["build_s"] = time.perf_counter() - started
    (out_dir / "model.xml").write_text(built.xml)

    # -- check ------------------------------------------------------------
    started = time.perf_counter()
    result = check_prop(
        built,
        segmentation,
        epsilon_rel=epsilon_rel,
        rest_s=rest_s,
        render_path=out_dir / "final.png",
    )
    timings["check_s"] = time.perf_counter() - started

    repair_record: dict[str, Any] | None = None
    counted = True

    # -- repair, once -----------------------------------------------------
    if not result.completion.completed and allow_repair and planner is not None:
        started = time.perf_counter()
        feedback = RepairFeedback(
            prop=spec.prop,
            interaction_status=result.interaction_status,
            physics_status=result.physics_status,
            measurements=result.to_dict(),
            render_path=str(out_dir / "final.png"),
            notes=notes,
        )
        repaired = planner.repair(spec, feedback)
        timings["repair_s"] = time.perf_counter() - started

        if repaired is None:
            repair_record = {"used": False, "reason": "the planner returned no revision"}
        else:
            from core.physag.spec import repair_is_allowed, spec_diff

            diff = spec_diff(spec, repaired)
            allowed, moved = repair_is_allowed(spec, repaired)
            prior_changes = sorted(
                key
                for key in diff["changed"]
                if key.startswith("priors.")
            )
            repair_record = {
                "used": True,
                "spec_diff": diff["changed"],
                "action_changed": diff["action_changed"],
                "action_changed_fields": diff["action_changed_fields"],
                "allowed": allowed,
                "prior_changes": prior_changes,
            }
            if not allowed:
                counted = False
                notes.append(
                    "the repair changed the action or the joint limits, so the "
                    "prop does not count towards the completion rate"
                )
            if prior_changes:
                notes.append(
                    "the repair changed the priors ("
                    + ", ".join(prior_changes)
                    + "), which is allowed but is reported"
                )

            # Rebuild and re-check with the revised spec.
            started = time.perf_counter()
            mesh = load_mesh(mesh_path)
            segmentation = segment(mesh, repaired)
            decompositions = _decompose_all(
                segmentation, repaired, decomposition_tolerance_m, max_pieces
            )
            built = build_mjcf(repaired, segmentation, decompositions)
            timings["rebuild_s"] = time.perf_counter() - started
            (out_dir / "model.repaired.xml").write_text(built.xml)

            started = time.perf_counter()
            result = check_prop(
                built,
                segmentation,
                epsilon_rel=epsilon_rel,
                rest_s=rest_s,
                render_path=out_dir / "final.repaired.png",
            )
            timings["recheck_s"] = time.perf_counter() - started
            spec = repaired

    if mesh_provenance:
        timings.update(
            {f"generation_{k}": float(v) for k, v in mesh_provenance.items() if isinstance(v, (int, float))}
        )

    return PropRun(
        prop=spec.prop,
        spec=spec,
        built=built,
        segmentation=segmentation,
        decompositions=decompositions,
        result=result,
        repair=repair_record,
        timings=timings,
        counted=counted,
        notes=tuple(notes),
    )


def delivery_for(run: PropRun, *, arm: str = "trellis") -> Delivery:
    """The delivery record for a finished run."""
    return build_delivery(
        prop=run.prop,
        arm=arm,
        spec=run.spec,
        built=run.built,
        segmentation=run.segmentation,
        result=run.result,
        timings=run.timings,
        repair=run.repair,
        counted=run.counted,
        notes=run.notes,
    )
