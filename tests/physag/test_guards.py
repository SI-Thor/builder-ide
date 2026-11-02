"""The guards, as tests.

Each of these is a thing the brief's Hy4 review says decides whether the
numbers mean anything, written as the check that would catch it breaking.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.physag.decompose import decompose_part
from core.physag.geometry import (
    is_closed,
    load_mesh,
    scale_mesh,
    signed_volume,
)
from core.physag.pipeline import run_prop
from core.physag.segment import segment
from core.physag.spec import Box, Cut, InteractionSpec, Joint, Part, load_spec
from tests.physag.fixtures import box_mesh, crate_mesh, write_glb
from tests.physag.test_spec import make_spec


# ---------------------------------------------------------------------------
# The scale
# ---------------------------------------------------------------------------


def test_the_mesh_is_scaled_to_the_prior_size(tmp_path):
    # A generated prop arrives in the generator's units, and the generator's
    # unit is not a metre. The physics is a statement about metres.
    vertices, triangles = box_mesh((1.0, 1.0, 1.0))
    path = write_glb(tmp_path / "unit.glb", vertices, triangles)
    mesh = load_mesh(path)
    assert mesh.bbox_size.max() == pytest.approx(1.0)

    scaled = scale_mesh(mesh, 0.4)
    assert scaled.bbox_size.max() == pytest.approx(0.4)
    # The corner stays at the origin: the prop frame does not move.
    assert scaled.bbox_min == pytest.approx(np.zeros(3))


def test_the_run_scales_the_mesh_to_the_prior(tmp_path):
    vertices, triangles = crate_mesh()
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    spec = make_spec()
    data = spec.to_dict()
    data["priors"]["size_m"] = 0.2
    data["basis"]["size_m"] = "estimated"
    spec = InteractionSpec.from_dict(data)
    run = run_prop(spec, path, out_dir=tmp_path / "out")
    # The spec's parts are written in normalised coordinates, so the split
    # is the same; the mesh the collider stands for is 20 cm across.
    assert run.segmentation.mesh.bbox_size.max() == pytest.approx(0.2, rel=1e-6)
    assert run.built.mesh_hull_volume_m3 > 0.0


# ---------------------------------------------------------------------------
# The volume ratio
# ---------------------------------------------------------------------------


def test_a_closed_mesh_has_a_volume_and_an_open_one_does_not(tmp_path):
    closed_v, closed_f = box_mesh((0.4, 0.4, 0.4))
    closed = write_glb(tmp_path / "closed.glb", closed_v, closed_f)
    assert is_closed(load_mesh(closed))
    assert signed_volume(*(lambda m: (m.vertices, m.triangles))(load_mesh(closed))) > 0.0

    # A box with its top face taken off: open, and the divergence theorem
    # gives a number that is not a volume.
    open_v, open_f = box_mesh((0.4, 0.4, 0.4))
    keep = np.ones(open_f.shape[0], dtype=bool)
    keep[1] = False  # the top face
    open_mesh = write_glb(tmp_path / "open.glb", open_v, open_f[keep])
    assert not is_closed(load_mesh(open_mesh))


def test_the_volume_ratio_is_not_evaluated_on_an_open_mesh(tmp_path):
    from core.physag.mjcf import build_mjcf
    from core.physag.pipeline import _decompose_all

    vertices, triangles = box_mesh((0.4, 0.4, 0.4))
    keep = np.ones(triangles.shape[0], dtype=bool)
    keep[1] = False
    path = write_glb(tmp_path / "open.glb", vertices, triangles[keep])
    mesh = load_mesh(path)
    spec = make_spec()
    segmentation = segment(mesh, spec)
    decompositions = _decompose_all(segmentation, spec, 0.004, 24)
    built = build_mjcf(spec, segmentation, decompositions)

    assert not built.mesh_closed
    assert built.volume_ratio is None
    assert built.inflation is None
    # The space the prop occupies is still known.
    assert built.mesh_hull_volume_m3 > 0.0


def test_a_closed_solid_is_compared_by_its_volume(tmp_path):
    # A closed solid: the collider is compared with the volume the
    # surface encloses, and a collider that stands for the prop is about
    # the same size as it.
    from core.physag.mjcf import build_mjcf
    from core.physag.pipeline import _decompose_all

    vertices, triangles = box_mesh((0.4, 0.4, 0.4))
    path = write_glb(tmp_path / "solid.glb", vertices, triangles)
    mesh = load_mesh(path)
    spec = make_spec()
    segmentation = segment(mesh, spec)
    decompositions = _decompose_all(segmentation, spec, 0.004, 24)
    built = build_mjcf(spec, segmentation, decompositions)

    assert built.mesh_closed
    assert not built.mesh_is_surface
    assert built.volume_ratio is not None
    assert built.mesh_volume_m3 == pytest.approx(0.4**3, rel=0.05)


# ---------------------------------------------------------------------------
# The hollow
# ---------------------------------------------------------------------------


def test_the_cavity_a_collider_fills_in_is_measured():
    # A shell: four walls and a floor, with air in the middle. The pieces
    # have to be the walls and the floor, not one hull that swallows the
    # air: a collider that filled the cavity would be a box where the
    # crate is, and "nothing penetrated past epsilon" would then be a
    # sentence about the box.
    wall = 0.02
    size = 0.4
    pieces = []
    for center in (
        (size / 2 - wall / 2, size / 2, size / 2),
        (size / 2 - wall / 2, wall / 2, size / 2),
        (wall / 2, size / 2, size / 2),
        (size / 2, size / 2, wall / 2),
    ):
        pieces.append(box_mesh((wall, size, size), center))
    vertices = np.concatenate([p[0] for p in pieces])
    triangles = np.concatenate(
        [p[1] + sum(q[0].shape[0] for q in pieces[:i]) for i, p in enumerate(pieces)]
    )

    from core.physag.geometry import MeshPart

    shell = MeshPart(vertices=vertices, triangles=triangles)
    decomposition = decompose_part(shell, "shell", 0.004, 24)

    # The pieces cover the shell: every bit of the material is under a
    # piece, and the pieces do not reach into the cavity.
    assert decomposition.deviation_m < 0.005
    # The hollow the pieces fill in is of the order of the shell's own
    # wall — the inside of a wall is a wall's thickness away from the
    # material's surface — and not of the order of the cavity.
    assert decomposition.concavity_m < 0.03


def test_a_hollow_that_a_single_hull_would_fill_in_is_caught():
    # The hollow measure has to be able to see the bad case as well as
    # the good one: one hull of the shell above fills the cavity, and the
    # depth of that hollow is the depth of the cavity.
    from core.physag.decompose import measure_pieces
    from core.physag.geometry import MeshPart, convex_hull

    wall = 0.02
    size = 0.4
    boxes = []
    for center in (
        (size / 2 - wall / 2, size / 2, size / 2),
        (size / 2 - wall / 2, wall / 2, size / 2),
        (wall / 2, size / 2, size / 2),
        (size / 2, size / 2, wall / 2),
    ):
        boxes.append(box_mesh((wall, size, size), center))
    vertices = np.concatenate([b[0] for b in boxes])
    triangles = np.concatenate(
        [b[1] + sum(q[0].shape[0] for q in boxes[:i]) for i, b in enumerate(boxes)]
    )
    shell = MeshPart(vertices=vertices, triangles=triangles)

    from core.physag.decompose import Collider

    one = Collider.from_piece(convex_hull(vertices))
    measured = measure_pieces([one], shell)
    # One hull of the shell is a box: it fills the cavity, and the cavity
    # is as deep as the shell is wide.
    assert measured["concavity_m"] > 0.05


def test_a_surface_mesh_is_told_from_a_solid_one(tmp_path):
    # The inflation test needs to know which it is looking at: a solid has
    # a volume to compare the collider with, a surface does not, and the
    # cavity is what stands in for the volume.
    from core.physag.mjcf import build_mjcf
    from core.physag.pipeline import _decompose_all

    # A tube: the four sides of a box, with no top and no bottom. The
    # surface encloses nothing, so the divergence theorem gives it no
    # volume, and it is not closed.
    vertices, triangles = box_mesh((0.4, 0.4, 0.4))
    keep = np.ones(triangles.shape[0], dtype=bool)
    keep[0] = False  # the bottom face
    keep[1] = False  # the top face
    path = write_glb(tmp_path / "skin.glb", vertices, triangles[keep])
    mesh = load_mesh(path)
    spec = make_spec()
    segmentation = segment(mesh, spec)
    decompositions = _decompose_all(segmentation, spec, 0.004, 24)
    built = build_mjcf(spec, segmentation, decompositions)

    # The skin is not closed, so there is no volume to compare the
    # collider's against, and the record says so.
    assert not built.mesh_closed
    assert built.volume_ratio is None
    assert built.inflation is None


# ---------------------------------------------------------------------------
# The mapping
# ---------------------------------------------------------------------------


def test_a_prop_whose_mapping_is_not_verified_does_not_count(tmp_path):
    # The crate's lid is cut at 80 % of the height, but the mesh is a
    # crate with a lid only over the middle: the "lid" that comes out is a
    # sliver, and the mapping is not verified. The prop may well complete
    # its action, and it still does not count.
    vertices, triangles = crate_mesh()
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    spec = make_spec()
    run = run_prop(spec, path, out_dir=tmp_path / "out")
    assert not run.segmentation.verified
    assert not run.counted
    assert any("not verified" in note for note in run.notes)


def test_a_verified_mapping_counts(tmp_path):
    # A crate whose lid stands a little clear of the body — the way a real
    # one does — and a cut in the gap between them. The split then finds
    # the lid, and the lid alone, and the mapping is verified.
    body_v, body_f = box_mesh((0.4, 0.4, 0.3), (0.0, 0.0, 0.15))
    lid_v, lid_f = box_mesh((0.42, 0.42, 0.055), (0.0, 0.0, 0.3325))
    vertices = np.concatenate([body_v, lid_v])
    triangles = np.concatenate([body_f, lid_f + body_v.shape[0]])
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    spec = make_spec(
        parts=(
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="plane", axis="z", at=0.84, keep="above"),
                expect=Box(min=(0.0, 0.0, 0.84), max=(1.0, 1.0, 1.0)),
            ),
        ),
    )
    run = run_prop(spec, path, out_dir=tmp_path / "out")
    assert run.segmentation.verified, run.segmentation.to_dict()
    assert run.counted


def test_a_cut_that_goes_through_the_body_is_not_verified(tmp_path):
    # The same crate, cut at 0.8: the cut passes through the body, so the
    # "lid" is a slice of the body plus the lid, in two pieces, and the
    # mapping is not verified. This is the trap the guard is for.
    vertices, triangles = crate_mesh()
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    run = run_prop(make_spec(), path, out_dir=tmp_path / "out")
    assert not run.segmentation.verified
    assert not run.counted


def test_a_hull_that_is_the_only_cover_for_its_material_is_kept():
    # A lattice: three slats joined by a rail across the top. The hull
    # that ends up standing over two slats is mostly the gap between
    # them, so the hollow test calls it air — and dropping it would leave
    # the slats with no collider at all. The drop is only allowed where
    # what remains still covers the material: the regression here is a
    # gate leaf whose pales came out of the model entirely.
    from core.physag.geometry import MeshPart

    slats = []
    for center_y in (0.03, 0.14, 0.25):
        slats.append(box_mesh((0.02, 0.06, 0.5), (0.0, center_y, 0.25)))
    slats.append(box_mesh((0.02, 0.28, 0.02), (0.0, 0.14, 0.49)))
    vertices = np.concatenate([s[0] for s in slats])
    triangles = np.concatenate(
        [s[1] + sum(q[0].shape[0] for q in slats[:i]) for i, s in enumerate(slats)]
    )
    lattice = MeshPart(vertices=vertices, triangles=triangles)

    decomposition = decompose_part(lattice, "lattice", 0.004, 24)
    # Every slat is under a piece: nothing was silently dropped as
    # "hollow" while being the only thing standing over real material.
    assert decomposition.deviation_m < 0.005, decomposition.notes


def test_known_parts_are_measured_against_the_claim_but_not_voided_by_it(tmp_path):
    # The CAD arm's rule: the parts are the kernel's, so the mapping is
    # exact by construction, and the planner's claim about where the
    # moving part is — here, wrong by half the height — is scored as
    # claim accuracy, not held against the mapping. The segmentation
    # arm's rule stays as it was: a cut that misses the claim voids the
    # mapping, and that is the test above this one.
    from core.physag.segment import segmentation_from_parts
    from core.physag.geometry import MeshPart, load_mesh

    body_v, body_f = box_mesh((0.4, 0.4, 0.3), (0.0, 0.0, 0.15))
    lid_v, lid_f = box_mesh((0.42, 0.42, 0.055), (0.0, 0.0, 0.3325))
    vertices = np.concatenate([body_v, lid_v])
    triangles = np.concatenate([body_f, lid_f + body_v.shape[0]])
    path = write_glb(tmp_path / "crate.glb", vertices, triangles)
    mesh = load_mesh(path)

    spec = make_spec(
        parts=(
            Part(name="body", role="base", cut=Cut(kind="rest")),
            Part(
                name="lid",
                role="moving",
                cut=Cut(kind="plane", axis="z", at=0.94, keep="above"),
                expect=Box(min=(0.0, 0.0, 0.94), max=(1.0, 1.0, 1.0)),
            ),
        ),
    )
    # The kernel's parts: the lid is the whole top slab, not the band the
    # claim names.
    parts = {
        "body": MeshPart(vertices=body_v, triangles=body_f),
        "lid": MeshPart(vertices=lid_v, triangles=lid_f),
    }
    segmentation = segmentation_from_parts(mesh, parts, spec)
    lid = segmentation.piece("lid")
    assert lid.bbox_iou < 0.9  # the claim is recorded as wrong
    assert segmentation.verified  # the mapping is still exact
    assert not lid.ambiguous
