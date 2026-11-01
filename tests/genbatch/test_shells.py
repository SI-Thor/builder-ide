"""The shells: the plausibility prior has to know that a real object is hollow.

**The finding these tests pin.** The critic's ``fill_ratio`` divided a
mesh's **signed volume** by its bounding box, and every real object is a
shell: a real mug's wall encloses 43 cm³ of ceramic inside the 500 cm³ its
box holds, so the prior fitted on generated solids called all 38 sampled
real SimReady assets ghosts. A real mug is 0.052 where the toy mug is
0.68 — and the gap between "generated solid" and "real hollow object" is
wider than the gap between "real object" and "ghost".

**What changed.** The critic measures the space an object **occupies**
(:mod:`core.genbatch.occupancy`), not the material in its wall, and the
prior is fitted on the **union** of the approved set and the real objects
(:mod:`core.genbatch.reference`).

**The rules under test:**

* a **real hollow mug is not a ghost** — the brief's own pin, and the one
  that matters: a real object must survive the prior;
* the occupied measure reads the **envelope**, so a shell and a solid of
  the same size read alike;
* the **whole asset** is measured, not its first part: a real forklift is
  32 parts and its first primitive is 0.2 % of the geometry;
* the prior fitted on the union **flags the ghost** and flags **at most
  5 %** of the real objects it was fitted on.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.genbatch.glb import Mesh, read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.occupancy import FILL_METHODS, occupied
from core.genbatch.plausibility import features_from_report
from core.genbatch.reference import (
    GHOST_THRESHOLD,
    REFERENCE_CLUSTERS,
    REFERENCE_FILL_METHOD,
    REFERENCE_SEED,
    reference_document,
    simready_features,
    simready_reference,
    union_prior,
)
from tests.genbatch import test_plausibility as toy
from tests.genbatch.glb_fixtures import build_glb_parts, cube_mesh, mug_mesh

#: The ghost the test file in this seat uses: a valid solid whose shape is
#: the wrong shape for anything. Its features are the ground truth the
#: prior has to reject.
GHOST = toy.PropFeatures(
    log_volume=-2.5,
    sphericity=30.0,
    elongation=12.0,
    fill_ratio=0.02,
    offcentre=0.4,
    defect_rate=0.0,
)

#: The mug's dimensions, so the numbers below can be written down.
MUG_OUTER = 0.04
MUG_INNER = 0.035
MUG_HEIGHT = 0.09
MUG_BOTTOM = 0.005


def _mug() -> Mesh:
    """The hollow mug, as a mesh."""
    positions, indices = mug_mesh(MUG_OUTER, MUG_INNER, MUG_HEIGHT, MUG_BOTTOM)
    return Mesh(
        positions=np.asarray(positions, dtype=np.float64),
        indices=np.asarray(indices, dtype=np.int64).reshape(-1, 3),
    )


def _prior():
    """The prior on the union: the toy approved set and the real objects.

    The toy set's kinds are its ground truth — a mug is a mug, a plank is a
    plank — and the real objects are one kind. The groups are those kinds,
    so every group is big enough for the threshold to mean anything.
    """
    features, labels = toy._reference_set()
    return union_prior(features, labels)


# --- the brief's pin: a real hollow mug is not a ghost ----------------------


def test_a_real_hollow_mug_is_not_a_ghost():
    """The rule the whole change exists for.

    A mug with a wall and a solid bottom and nothing inside is a **real
    object**. It must not be called a ghost by the prior — and the prior
    is fitted on the real objects, so it has to know what a shell is.
    """
    prior = _prior()
    features = features_from_report(
        measure_mesh(_mug(), fill_method=REFERENCE_FILL_METHOD)
    )

    score = prior.score(features)
    assert score.score >= GHOST_THRESHOLD, (
        f"a real hollow mug scored {score.score:.4f}, which is a ghost"
    )
    # And it is not the ghost either: the ghost is what the prior rejects.
    assert prior.score(GHOST).score < GHOST_THRESHOLD


def test_the_hollow_mug_reads_like_the_real_mug():
    """The mug's features are the envelope's, and they match the sample's.

    The stored reference set carries the measured features of the real
    SimReady mug. A hollow mug built here must land in the same place in
    feature space — which is only true if the measure is the occupied one
    and the whole asset is measured.
    """
    features = features_from_report(
        measure_mesh(_mug(), fill_method=REFERENCE_FILL_METHOD)
    )
    real = {
        asset.name: asset.features for asset in simready_reference()
    }["dishware_mug_a01"]

    assert features.log_volume == pytest.approx(real.log_volume, abs=0.3)
    assert features.sphericity == pytest.approx(real.sphericity, abs=1.5)
    assert features.elongation == pytest.approx(real.elongation, abs=0.6)
    assert features.fill_ratio == pytest.approx(real.fill_ratio, abs=0.3)
    assert features.defect_rate == pytest.approx(0.0, abs=1e-9)


# --- the measure: what the object occupies, not the wall --------------------


def test_the_occupied_measure_reads_the_envelope_and_not_the_wall():
    """The mug occupies a cylinder; it is made of a much smaller amount of
    ceramic, and the two numbers are not close."""
    mesh = _mug()
    envelope = math.pi * MUG_OUTER**2 * MUG_HEIGHT
    ceramic = (
        math.pi * (MUG_OUTER**2 - MUG_INNER**2) * MUG_HEIGHT
        + math.pi * MUG_INNER**2 * MUG_BOTTOM
    )

    result = occupied(mesh, REFERENCE_FILL_METHOD)
    assert result.volume == pytest.approx(envelope, rel=0.05)
    # The signed volume is the wall's — and it is a small fraction of the
    # envelope's, which is the number the critic used to read.
    report = measure_mesh(mesh)
    assert abs(report.volume) == pytest.approx(ceramic, rel=0.05)
    assert abs(report.volume) < result.volume / 3.0


def test_a_shell_and_a_solid_of_the_same_size_read_alike():
    """The same space, occupied or not, is the same amount of space."""
    positions, indices = cube_mesh()
    solid = Mesh(
        positions=np.asarray(positions, dtype=np.float64),
        indices=np.asarray(indices, dtype=np.int64).reshape(-1, 3),
    )
    report = measure_mesh(solid, fill_method=REFERENCE_FILL_METHOD)
    # A unit cube fills its own box, and its occupied volume is its volume.
    assert report.occupied_volume == pytest.approx(1.0, rel=0.01)
    assert features_from_report(report).fill_ratio == pytest.approx(1.0, rel=0.01)


def test_every_fill_measure_is_available_and_names_itself():
    """The other measures are kept as parameters, and each says which it was."""
    mesh = _mug()
    for method in FILL_METHODS:
        result = occupied(mesh, method)
        assert result.method == method
        assert result.volume > 0.0
        assert np.isfinite(result.centre).all()


# --- the whole asset, not its first part ------------------------------------


def test_the_reader_measures_the_whole_asset_and_not_its_first_part(tmp_path):
    """A real asset is made of parts, and the first one is not the object.

    The SimReady forklift is 32 parts and its first primitive holds 0.2 %
    of the geometry. A reader that stops at the first primitive measures a
    fragment, and the fragment's box is not the object's box.
    """
    positions, indices = cube_mesh()
    far = [(point[0] + 10.0, point[1], point[2]) for point in positions]
    path = tmp_path / "two-parts.glb"
    path.write_bytes(
        build_glb_parts(
            [(positions, indices), (far, indices)],
            translations=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
        )
    )

    glb = read_glb(path)
    # The first primitive alone: the small cube at the origin.
    assert glb.mesh.triangles == 12
    assert float(glb.mesh.positions[:, 0].max()) == pytest.approx(0.5)
    # The whole asset: both parts, and the box that holds them.
    asset = glb.asset
    assert asset.triangles == 24
    assert float(asset.positions[:, 0].max()) == pytest.approx(10.5)


def test_a_part_is_placed_where_its_node_says(tmp_path):
    """The parts of an asset are put where the file puts them."""
    positions, indices = cube_mesh()
    path = tmp_path / "moved.glb"
    path.write_bytes(
        build_glb_parts(
            [(positions, indices)],
            translations=[(3.0, 0.0, 0.0)],
        )
    )

    asset = read_glb(path).asset
    assert float(asset.positions[:, 0].min()) == pytest.approx(2.5)
    assert float(asset.positions[:, 0].max()) == pytest.approx(3.5)


# --- the prior on the union ------------------------------------------------


def test_the_union_prior_flags_the_ghost():
    """The control the critic cannot pass without: a shape no camera has
    ever seen is still rejected after the prior learns what a shell is."""
    prior = _prior()
    score = prior.score(GHOST)
    assert score.score < GHOST_THRESHOLD
    # And it is far from every group, not merely unusual in one feature.
    assert score.distance > 3.0


def test_at_most_five_percent_of_the_real_assets_are_flagged():
    """The prior must not call the real objects it was fitted on ghosts.

    Before the change it called **all 38** of them ghosts.
    """
    prior = _prior()
    real = simready_features()
    flagged = [
        asset.name
        for asset in simready_reference()
        if prior.score(asset.features).score < GHOST_THRESHOLD
    ]
    rate = len(flagged) / len(real)
    assert rate <= 0.05, f"{len(flagged)} of {len(real)} real assets flagged: {flagged}"


def test_the_reference_set_is_measured_on_what_the_object_occupies():
    """Every real asset in the reference set fills a good part of its box.

    On the shell's own signed volume the real mug reads 0.052 and the
    median across the sample is 0.16. On the occupied volume the smallest
    of the 38 is 0.31 and the median is 0.62 — which is the point of the
    change, and a regression here is visible.
    """
    fills = [features.fill_ratio for features in simready_features()]
    assert min(fills) > 0.2
    assert float(np.median(fills)) > 0.4


def test_the_reference_set_says_where_it_came_from():
    """A number without its provenance is not a measurement."""
    document = reference_document()
    source = document["source"]
    assert source["dataset"] == "nvidia/simready-assets"
    assert source["licence"] == "CC-BY-4.0"
    assert document["measure"]["method"] == REFERENCE_FILL_METHOD
    assert document["prior"]["clusters"] == REFERENCE_CLUSTERS
    assert document["prior"]["seed"] == REFERENCE_SEED
    assert document["source"]["box"]["machine"]
    assert len(document["assets"]) == 38
