"""The split: does it find the part the spec asked for?

These are the Hy4 guard's tests. A geometric split can cut the mesh
without cutting the *part*, and then the joint moves the wrong body and
the completion rate measures nothing. The segmentation has to say so
rather than hand back a plausible-looking piece.
"""

from __future__ import annotations

import math

import pytest

from core.physag.geometry import load_mesh
from core.physag.segment import segment
from core.physag.spec import Action, Box, Cut, InteractionSpec, Joint, Part, Priors

from .fixtures import box_mesh, crate_mesh, write_glb

BASIS = {
    "mass_kg": "estimated",
    "friction": "estimated",
    "actuator_force_n": "estimated",
    "actuator_torque_nm": "estimated",
    "base_static": "estimated",
}


def crate_spec(cut_at: float = 0.857, expect_min: float = 0.857) -> InteractionSpec:
    return InteractionSpec(
        prop="crate",
        kind="crate",
        image_prompt="a weathered wooden crate",
        parts=(
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="plane", axis="z", at=cut_at, keep="above"),
                expect=Box(min=(0.0, 0.0, expect_min), max=(1.0, 1.0, 1.0)),
            ),
        ),
        joints=(
            Joint(
                name="lid_hinge",
                type="hinge",
                parent="body",
                child="lid",
                axis=(1.0, 0.0, 0.0),
                anchor=(0.5, 0.0, cut_at),
                low=0.0,
                high=math.radians(90.0),
            ),
        ),
        action=Action(kind="joint", joint="lid_hinge", target=math.radians(90.0)),
        priors=Priors(mass_kg=12.0),
        basis=dict(BASIS),
    )


def box_cut_spec(box_min, box_max) -> InteractionSpec:
    """A spec whose moving part is cut out of a box in the mesh.

    A **plane** cut can never come out empty: the cut is a fraction of the
    mesh's own height, and the mesh has material at its own height. A **box**
    cut can — the box may sit in empty space — and that is the case the empty
    part guard is about.
    """
    return InteractionSpec(
        prop="crate",
        kind="crate",
        image_prompt="a weathered wooden crate",
        parts=(
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="box", min=box_min, max=box_max),
                expect=Box(min=box_min, max=box_max),
            ),
        ),
        joints=(
            Joint(
                name="lid_hinge",
                type="hinge",
                parent="body",
                child="lid",
                axis=(1.0, 0.0, 0.0),
                anchor=(0.5, 0.0, 0.5),
                low=0.0,
                high=math.radians(90.0),
            ),
        ),
        action=Action(kind="joint", joint="lid_hinge", target=math.radians(90.0)),
        priors=Priors(mass_kg=12.0),
        basis=dict(BASIS),
    )


@pytest.fixture()
def crate(tmp_path):
    vertices, triangles = crate_mesh()
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    return load_mesh(path)


def test_the_parts_tile_the_mesh(crate):
    segmentation = segment(crate, crate_spec())
    # The parts account for the mesh's whole area: clipping swaps a cut
    # face for the faces it replaced, so nothing is lost and nothing is
    # counted twice.
    assert segmentation.coverage == pytest.approx(1.0, abs=1e-6)


def test_the_lid_is_the_top_of_the_crate(crate):
    segmentation = segment(crate, crate_spec())
    lid = segmentation.piece("lid")
    body = segmentation.piece("body")
    assert lid.bbox_min[2] > body.bbox_max[2]
    assert lid.triangles > 0


def test_the_split_leaves_a_clearance_between_the_parts(crate):
    segmentation = segment(crate, crate_spec(), gap_m=0.002)
    lid = segmentation.piece("lid")
    body = segmentation.piece("body")
    # the lid's material starts at the cut, the body's ends at the cut,
    # and the clearance opens a gap between them
    assert lid.bbox_min[2] - body.bbox_max[2] > 0.002


def test_a_moving_part_that_falls_into_pieces_is_flagged(tmp_path):
    # Two separate blobs above the cut: the lid's region is two pieces
    # and neither dominates, so the mapping is ambiguous.
    v1, f1 = box_mesh((0.2, 0.2, 0.3), (-0.25, 0.0, 0.65))
    v2, f2 = box_mesh((0.2, 0.2, 0.3), (0.25, 0.0, 0.65))
    import numpy as np

    vertices = np.concatenate([v1, v2])
    triangles = np.concatenate([f1, f2 + v1.shape[0]])
    path = write_glb(tmp_path / "two.glb", vertices, triangles)
    mesh = load_mesh(path)

    segmentation = segment(mesh, crate_spec(cut_at=0.5))
    lid = segmentation.piece("lid")
    assert lid.components == 2
    assert lid.ambiguous
    assert not lid.verified


def test_the_iou_against_the_planner_s_claim_is_measured(crate):
    # The planner claims the lid is the top 14 % of the height; the cut
    # takes the top 30 %. The piece does not match the claim, and the
    # number says so.
    segmentation = segment(crate, crate_spec(cut_at=0.7, expect_min=0.86))
    lid = segmentation.piece("lid")
    assert lid.bbox_iou < 0.9
    assert lid.notes


def test_a_piece_outside_the_claimed_region_is_noted(crate):
    segmentation = segment(crate, crate_spec(cut_at=0.7, expect_min=0.95))
    lid = segmentation.piece("lid")
    assert any("outside" in note for note in lid.notes)


def test_an_empty_part_is_reported(tmp_path):
    # A mesh with a gap in it — a slab at the bottom, a slab at the top,
    # nothing between — and a cut that claims the gap.
    bottom_v, bottom_f = box_mesh((0.4, 0.4, 0.1), (0.0, 0.0, 0.05))
    top_v, top_f = box_mesh((0.4, 0.4, 0.1), (0.0, 0.0, 0.35))
    import numpy as np

    vertices = np.concatenate([bottom_v, top_v])
    triangles = np.concatenate([bottom_f, top_f + bottom_v.shape[0]])
    path = write_glb(tmp_path / "gapped.glb", vertices, triangles)
    mesh = load_mesh(path)

    segmentation = segment(mesh, box_cut_spec((0.1, 0.1, 0.4), (0.3, 0.3, 0.6)))
    lid = segmentation.piece("lid")
    assert lid.triangles == 0
    assert any("empty" in reason for reason in segmentation.reasons)
    assert not segmentation.verified
    assert not lid.verified


def test_a_plane_cut_never_comes_out_empty(crate):
    # The counterpart: a plane cut is a fraction of the mesh's own height,
    # so there is always material above it. The guard about empty parts is
    # about a cut that claims the wrong region, not about a plane cut.
    segmentation = segment(crate, crate_spec(cut_at=0.99))
    lid = segmentation.piece("lid")
    assert lid.triangles > 0
    assert not any("empty" in reason for reason in segmentation.reasons)


def test_the_segmentation_is_deterministic(crate):
    first = segment(crate, crate_spec())
    second = segment(crate, crate_spec())
    assert first.to_dict() == second.to_dict()
