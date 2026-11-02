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
from core.physag.geometry import MeshPart, load_mesh, scale_mesh
from core.physag.mjcf import BuiltProp, build_mjcf
from core.physag.planner import Planner, RepairFeedback
from core.physag.segment import Segmentation, segment, segmentation_from_parts
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


def _decompose_subparts(
    part_name: str,
    subparts: list["MeshPart"],
    tolerance_m: float,
    max_pieces: int,
    max_depth: int,
) -> "Decomposition":
    """Decompose a part that arrives as several known bodies, and merge.

    The CAD arm's parts are the kernel's bodies. A base is several of them
    — a table's legs, a gate's posts — and decomposing them *merged* makes
    one convex search face a shape whose pieces the kernel had already
    separated: the hull of a leg-and-rail frame spans the space between
    the legs, and no axis-aligned cut of the search's vocabulary takes it
    apart again. Decomposing each body as the shape it is keeps the hulls
    on the bodies, and the merged measures are taken afterwards, against
    the whole part, so the guard's numbers are the guard's numbers.
    """
    import numpy as np

    from core.physag.decompose import measure_pieces

    decomps = [
        decompose_part(
            subpart,
            part_name,
            tol_m=tolerance_m,
            max_pieces=max_pieces,
            max_depth=max_depth,
        )
        for subpart in subparts
    ]
    colliders = tuple(c for d in decomps for c in d.colliders)
    material = subparts[0]
    if len(subparts) > 1:
        material = MeshPart(
            vertices=np.concatenate([s.vertices for s in subparts], axis=0),
            triangles=np.concatenate(
                [s.triangles + sum(t.vertices.shape[0] for t in subparts[:i]) for i, s in enumerate(subparts)],
                axis=0,
            ),
        )
    measured = (
        measure_pieces(list(colliders), material)
        if colliders
        else {
            "deviation_m": 0.0,
            "deviation_p95_m": 0.0,
            "concavity_m": 0.0,
            "stray_m": 0.0,
            "stray_p95_m": 0.0,
        }
    )
    notes = tuple(
        f"{d.part_name} body {i}: {note}"
        for i, d in enumerate(decomps)
        for note in d.notes
    )
    return Decomposition(
        part_name=part_name,
        colliders=colliders,
        hull_volume=float(sum(d.hull_volume for d in decomps)),
        collider_volume=float(sum(d.collider_volume for d in decomps)),
        deviation_m=measured["deviation_m"],
        deviation_p95_m=measured["deviation_p95_m"],
        concavity_m=measured["concavity_m"],
        stray_m=measured["stray_m"],
        stray_p95_m=measured["stray_p95_m"],
        overlaps=any(d.overlaps for d in decomps),
        notes=notes,
    )


def _decompose_all(
    segmentation: Segmentation,
    spec: InteractionSpec,
    tolerance_m: float,
    max_pieces: int,
    max_depth: int = 8,
    clip: bool = True,
    subparts: dict[str, list[MeshPart]] | None = None,
) -> dict[str, Decomposition]:
    """Every part's convex pieces, clipped to the part's own half-space.

    The clipping is skipped when the parts were known already — when the
    kernel that built the prop made them, one body each. The two bodies
    do not share space, because the kernel put them where it wanted them,
    and clipping them to the spec's cut would cut a lid off a door.

    ``subparts`` is the CAD arm's way in: when a part arrives as several
    kernel bodies, each is decomposed as the shape it is and the results
    are merged — see :func:`_decompose_subparts`.
    """
    out: dict[str, Decomposition] = {}
    size = segmentation.mesh.bbox_size
    for part in spec.parts:
        piece = segmentation.pieces[part.name]
        if subparts and part.name in subparts and subparts[part.name]:
            decomp = _decompose_subparts(
                part.name,
                subparts[part.name],
                tolerance_m,
                max_pieces,
                max_depth,
            )
        else:
            decomp = decompose_part(
                piece.part,
                part.name,
                tol_m=tolerance_m,
                max_pieces=max_pieces,
                max_depth=max_depth,
            )
        if clip:
            decomp = _clip_to_part(decomp, part, spec, size, piece.part)
        out[part.name] = decomp
    return out


def _clip_to_part(
    decomp: Decomposition,
    part,
    spec,
    size,
    material: MeshPart,
    deviation_point_limit: int = 20000,
) -> Decomposition:
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

    from core.physag.decompose import clip_convex, measure_pieces

    clipped = []
    for piece in decomp.colliders:
        pieces_now = [piece]
        for other in spec.parts:
            cut = other.cut
            if cut.kind == "rest":
                continue
            axis = {"x": 0, "y": 1, "z": 2}[cut.axis]
            at = cut.at * size[axis]
            pieces_next: list = []
            for current in pieces_now:
                if cut.kind == "plane":
                    if other.name == part.name:
                        # The part keeps the side its own cut claims.
                        if cut.keep == "above":
                            normal = np.zeros(3)
                            normal[axis] = -1.0
                            pieces_next.append(clip_convex(current, normal, at))
                        else:
                            normal = np.zeros(3)
                            normal[axis] = 1.0
                            pieces_next.append(clip_convex(current, normal, -at))
                    else:
                        # Everything else keeps the other side.
                        if cut.keep == "above":
                            normal = np.zeros(3)
                            normal[axis] = 1.0
                            pieces_next.append(clip_convex(current, normal, -at))
                        else:
                            normal = np.zeros(3)
                            normal[axis] = -1.0
                            pieces_next.append(clip_convex(current, normal, at))
                else:  # a box cut
                    lo = np.asarray(cut.min) * size
                    hi = np.asarray(cut.max) * size
                    if other.name == part.name:
                        # Inside the box: the six face half-spaces
                        # intersect to the box.
                        for index in range(3):
                            normal = np.zeros(3)
                            normal[index] = 1.0
                            current = clip_convex(current, -normal, lo[index])
                            current = clip_convex(current, normal, -hi[index])
                        pieces_next.append(current)
                    else:
                        # Outside the box is the *union* of the six
                        # outside half-spaces, and a union cannot be
                        # written as a chain of clips — the chain says
                        # "and", and "x <= lo and x >= hi" is nowhere.
                        # The faces are therefore peeled off one at a
                        # time, a BSP split: each face takes the part of
                        # the piece outside that one face, out of what
                        # the previous faces left behind. The six slabs
                        # together are exactly the piece minus the box,
                        # and they do not overlap, because each slab was
                        # trimmed by every face in front of it. A piece
                        # that lies wholly inside the box comes out with
                        # nothing, and is dropped.
                        pending = current
                        for index in range(3):
                            for sign in (1.0, -1.0):
                                normal = np.zeros(3)
                                normal[index] = sign
                                if sign > 0.0:
                                    # the slab x <= lo
                                    slab = clip_convex(pending, normal, -lo[index])
                                    pending = clip_convex(pending, -normal, lo[index])
                                else:
                                    # the slab x >= hi
                                    slab = clip_convex(pending, normal, hi[index])
                                    pending = clip_convex(pending, -normal, -hi[index])
                                if not slab.is_empty:
                                    pieces_next.append(slab)
                        if pending.is_empty:
                            break
            pieces_now = [p for p in pieces_next if not p.is_empty]
            if not pieces_now:
                break
        clipped.extend(pieces_now)

    kept = [c for c in clipped if not c.is_empty]
    if not kept:
        return decomp
    volume = float(sum(c.volume for c in kept))

    # The measures are taken again after the clip: the clip moves the
    # pieces' own surfaces, and a number measured before the clip would be
    # a number about a collider that is no longer the one in the model.
    #
    # The distance is to the **union** of the pieces, not to each piece: a
    # vertex that one piece covers is covered, however far it is from the
    # *other* pieces' surfaces. Measuring to each piece and taking the worst
    # would report a vertex as far from the collider when the collider is
    # standing right there.
    measured = measure_pieces(kept, material, deviation_point_limit)

    return Decomposition(
        part_name=decomp.part_name,
        colliders=tuple(kept),
        hull_volume=decomp.hull_volume,
        collider_volume=volume,
        deviation_m=measured["deviation_m"],
        deviation_p95_m=measured["deviation_p95_m"],
        concavity_m=measured["concavity_m"],
        stray_m=measured["stray_m"],
        stray_p95_m=measured["stray_p95_m"],
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
    max_depth: int = 8,
    epsilon_rel: float = 0.005,
    rest_s: float = 2.0,
    arm: str = "trellis",
    allow_repair: bool = True,
    mesh_provenance: dict[str, Any] | None = None,
    ground_truth: dict[str, Any] | None = None,
    parts: dict[str, MeshPart] | None = None,
    mesh: MeshPart | None = None,
    subparts: dict[str, list[MeshPart]] | None = None,
) -> PropRun:
    """Run one prop through the whole loop.

    ``parts`` is the CAD arm's way in: when the parts are known already —
    because the kernel that built the prop made them, one body each — they
    are passed in and the geometric cut is skipped. ``mesh`` is the matching
    merged mesh, for the same reason: it has already been put in the prop
    frame, so it is not read again.

    Everything after the split is the same code for both arms: the
    decomposition, the MJCF, the check, the repair and the record.
    """
    out_dir = Path(out_dir) if out_dir else Path("artifacts/physag-lite") / spec.prop
    out_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    timings: dict[str, float] = {}

    # -- build ------------------------------------------------------------
    started = time.perf_counter()
    if mesh is None:
        mesh = load_mesh(mesh_path)
        # The generator's units are not metres; the prop's size is a prior
        # and the mesh is scaled to it before anything is simulated.
        mesh = scale_mesh(mesh, spec.priors.size_m)
    timings["load_mesh_s"] = time.perf_counter() - started

    started = time.perf_counter()
    if parts is None:
        segmentation = segment(mesh, spec)
    else:
        segmentation = segmentation_from_parts(mesh, parts, spec)
    timings["segment_s"] = time.perf_counter() - started

    started = time.perf_counter()
    decompositions = _decompose_all(
        segmentation,
        spec,
        decomposition_tolerance_m,
        max_pieces,
        max_depth,
        clip=not segmentation.from_known_parts,
        subparts=subparts,
    )
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

    # Guard 1: the completion rate is reported only for props whose
    # part-to-spec mapping was verified. A prop whose lid was not found —
    # because the mesh has no lid, or because the split cut the wrong
    # band — can complete its action and mean nothing by it, so it does
    # not count.
    if not segmentation.verified:
        counted = False
        reasons = "; ".join(segmentation.reasons) or "; ".join(
            f"{name}: {', '.join(piece.notes)}"
            for name, piece in segmentation.pieces.items()
            if piece.notes
        )
        notes.append(
            "the part-to-spec mapping was not verified (" + reasons + "), so the "
            "prop does not count towards the completion rate"
        )

    # -- repair, once -----------------------------------------------------
    # The repair answers a check that failed, and an unverified mapping is
    # a failure the planner is exactly the right party to fix: the claim
    # about where the part is was the planner's, and the render and the
    # measurements say where the part actually is. A prop that completed
    # with a verified mapping does not repair.
    if (
        (not result.completion.completed or not segmentation.verified)
        and allow_repair
        and planner is not None
    ):
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
        mapping_verified_before = segmentation.verified

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
            if parts is None:
                mesh = load_mesh(mesh_path)
                mesh = scale_mesh(mesh, spec.priors.size_m)
                segmentation = segment(mesh, repaired)
            else:
                segmentation = segmentation_from_parts(mesh, parts, repaired)
            decompositions = _decompose_all(
                segmentation,
                repaired,
                decomposition_tolerance_m,
                max_pieces,
                max_depth,
                clip=not segmentation.from_known_parts,
                subparts=subparts,
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

            # The repair may have found the part where the first split did
            # not: the revised plan's cut can be the one that isolates the
            # lid. The prop counts again if the mapping is verified now —
            # and only if the repair kept the action and the limits frozen.
            if allowed and segmentation.verified:
                counted = True
                if not mapping_verified_before:
                    notes.append(
                        "the repair found the part the first split did not, and the "
                        "mapping is verified now"
                    )
            elif not segmentation.verified:
                counted = False

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
