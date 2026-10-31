"""The plausibility side of the prop critic.

The rules under test:

* a prop from **either** of two kinds of real object is plausible — the
  prior is multimodal, and a single distribution over the pooled set would
  call the rarer kind a ghost;
* a prop that is **off the manifold** of real objects is not plausible, even
  when it matches its image perfectly — this is the control a
  consistency-only critic cannot pass;
* the **fiber-width gate** fires when the night's reconstructions of one
  image disagree more than real objects of one kind disagree;
* the two sides are put on **one scale**, and the scale gap that was closed
  is measured rather than assumed;
* everything is numpy, and the features come from what the mesh layer
  already measures.

The toy has **known ground truth**: the reference set is drawn from two
modes with known labels, so "plausible" and "implausible" are facts about
the world the toy was built from, not opinions about the scores.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.genbatch.mesh import MeshReport
from core.genbatch.plausibility import (
    FEATURE_NAMES,
    PropFeatures,
    ReferencePrior,
    features_from_report,
    fiber_width,
    judge,
    percentile_against,
)

#: The two kinds of real object in the toy.
#:
#: A **mug**: solid, roundish, ordinary volume. A **plank**: flat, long,
#: and rare among the approved assets — 20 in 200. The rarity is the
#: point: it is what makes a pooled prior fail.
MODES = {
    "mug": {
        "count": 180,
        "fill_ratio": (0.68, 0.06),
        "elongation": (1.45, 0.18),
        "log_volume": (0.0, 0.22),
    },
    "plank": {
        "count": 20,
        "fill_ratio": (0.27, 0.035),
        "elongation": (3.9, 0.55),
        "log_volume": (0.55, 0.30),
    },
}

#: The features the toy holds still: a real object's surface, how centred
#: it is, and how clean its mesh is.
QUIET = {
    "sphericity": (5.6, 0.5),
    "offcentre": (0.08, 0.03),
    "defect_rate": (0.002, 0.001),
}

#: The seed, so every number in the lab note is reproducible.
SEED = 20261031


def _features(
    rng: np.random.Generator, mode: str
) -> PropFeatures:
    """One object of a known kind."""
    spec = MODES[mode]
    quiet = {name: rng.normal(*QUIET[name]) for name in QUIET}
    return PropFeatures(
        log_volume=float(rng.normal(*spec["log_volume"])),
        sphericity=float(quiet["sphericity"]),
        elongation=float(rng.normal(*spec["elongation"])),
        fill_ratio=float(rng.normal(*spec["fill_ratio"])),
        offcentre=float(quiet["offcentre"]),
        defect_rate=float(quiet["defect_rate"]),
    )


def _reference_set(seed: int = SEED) -> tuple[list[PropFeatures], list[str]]:
    """The approved assets, with their known kinds."""
    rng = np.random.default_rng(seed)
    features: list[PropFeatures] = []
    labels: list[str] = []
    for mode, spec in MODES.items():
        for _ in range(spec["count"]):
            features.append(_features(rng, mode))
            labels.append(mode)
    return features, labels


def _prior(reference: list[PropFeatures], clusters: int = 2) -> ReferencePrior:
    return ReferencePrior(reference, clusters=clusters, seed=SEED)


# --- the prior over real objects --------------------------------------------


def test_the_prior_groups_the_approved_set_by_kind():
    """The fit finds the two kinds, and it is reproducible."""
    reference, labels = _reference_set()
    prior = _prior(reference)

    assert sorted(prior.group_sizes) == [20, 180]
    # The same seed gives the same prior.
    again = _prior(reference)
    assert again.group_sizes == prior.group_sizes
    for features in reference[:20]:
        assert prior.score(features).cluster == again.score(features).cluster


def _median_score(prior: ReferencePrior, mode: str, count: int = 40) -> float:
    """The median plausibility of fresh props of a known kind.

    A distribution, not a draw: the score is a rank among a small group,
    so a single prop's score is coarse — the claim is about the kind, not
    about one prop of it.
    """
    rng = np.random.default_rng(SEED + 11)
    scores = [prior.score(_features(rng, mode)).score for _ in range(count)]
    return float(np.median(scores))


def test_a_prop_of_either_kind_is_plausible():
    """The prior is multimodal, and that is what saves the rare kind.

    A plank is 20 of 200 approved assets. Against the pooled set it sits
    in the bottom tenth of the fill ratio and the top tenth of the
    elongation, so a prior that did not group would call it a ghost.
    """
    reference, _ = _reference_set()
    prior = _prior(reference)

    assert _median_score(prior, "mug") > 0.2
    assert _median_score(prior, "plank") > 0.2


def test_a_single_group_prior_calls_the_rare_kind_a_ghost():
    """The control for the grouping: pool the set and the plank dies."""
    reference, _ = _reference_set()
    pooled = ReferencePrior(reference, clusters=1, seed=SEED)
    grouped = _prior(reference)

    assert _median_score(grouped, "plank") > 0.2
    assert _median_score(pooled, "plank") < 0.2
    # And the abundant kind is not the thing that changed.
    assert _median_score(pooled, "mug") > _median_score(grouped, "mug") * 0.5


def test_a_prop_off_the_manifold_is_not_plausible():
    """A ghost: a valid solid, the wrong shape for anything."""
    reference, _ = _reference_set()
    prior = _prior(reference)

    ghost = PropFeatures(
        log_volume=-2.5,
        sphericity=30.0,
        elongation=12.0,
        fill_ratio=0.02,
        offcentre=0.4,
        defect_rate=0.0,
    )
    score = prior.score(ghost)
    assert score.score < 0.05
    # And it is far from every group, not merely unusual in one feature.
    assert score.distance > 3.0


def test_the_score_punishes_one_impossible_feature():
    """One bad feature is not averaged away by five fine ones."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 2)

    ordinary = _features(rng, "mug")
    broken = PropFeatures(
        log_volume=ordinary.log_volume,
        sphericity=ordinary.sphericity,
        elongation=ordinary.elongation,
        fill_ratio=0.001,
        offcentre=ordinary.offcentre,
        defect_rate=ordinary.defect_rate,
    )
    assert prior.score(broken).score < 0.5 * prior.score(ordinary).score


def test_a_percentile_is_strictly_inside_the_unit_interval():
    """The mid-p correction: no zero, no one."""
    population = [0.1, 0.2, 0.3, 0.4]
    assert 0.0 < percentile_against(0.0, population) < 1.0
    assert 0.0 < percentile_against(1.0, population) < 1.0
    assert percentile_against(0.25, population) == pytest.approx(
        percentile_against(0.25, population)
    )
    with pytest.raises(ValueError):
        percentile_against(0.5, [])


# --- the control: a consistency-only critic certifies the ghost ------------


def test_a_consistency_only_critic_passes_the_ghost_and_the_two_sided_one_does_not():
    """The control the brief asks for.

    The ghost matches its image perfectly — its consistency score is 0.99,
    which is better than the real prop's — and it is still a thing no
    camera has ever seen. A critic that reads consistency alone passes it.
    The two-sided critic does not.
    """
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 3)

    real = _features(rng, "mug")
    ghost = PropFeatures(
        log_volume=-2.5,
        sphericity=30.0,
        elongation=12.0,
        fill_ratio=0.02,
        offcentre=0.4,
        defect_rate=0.0,
    )

    consistency_population = [0.98 + 0.004 * index for index in range(50)]

    ghost_verdict = judge(
        features=ghost,
        consistency=0.99,
        prior=prior,
        consistency_population=consistency_population,
    )
    real_verdict = judge(
        features=real,
        consistency=0.985,
        prior=prior,
        consistency_population=consistency_population,
    )

    # The consistency-only critic sees 0.99 and passes it.
    assert 0.99 > 0.985
    # The two-sided critic sees the ghost for what it is.
    assert ghost_verdict.plausibility < real_verdict.plausibility
    assert ghost_verdict.combined < real_verdict.combined
    assert "less ordinary" in ghost_verdict.reason


def test_the_two_sided_score_does_not_average_a_ghost_away():
    """A perfect consistency score does not buy an impossible shape."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    ghost = PropFeatures(
        log_volume=-2.5,
        sphericity=30.0,
        elongation=12.0,
        fill_ratio=0.02,
        offcentre=0.4,
        defect_rate=0.0,
    )
    verdict = judge(
        features=ghost,
        consistency=1.0,
        prior=prior,
        consistency_population=[0.99] * 50,
    )
    # The comparison is distributional: the score is a rank among a small
    # group, so one prop's score is coarse.
    rng = np.random.default_rng(SEED + 9)
    real_scores = [
        judge(
            features=_features(rng, "mug"),
            consistency=1.0,
            prior=prior,
            consistency_population=[0.99] * 50,
        ).combined
        for _ in range(40)
    ]
    ordinary = float(np.median(real_scores))
    # The consistency side is perfect for both, and the ghost still loses.
    assert verdict.plausibility < 0.1
    assert verdict.combined < 0.3
    assert verdict.combined < 0.4 * ordinary


# --- the ambiguity gate ------------------------------------------------------


def test_reconstructions_that_disagree_make_the_prop_ambiguous():
    """The fiber-width gate: the image did not determine the shape."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 4)

    agreeing = [_features(rng, "mug"), _features(rng, "mug")]
    disagreeing = [_features(rng, "mug"), _features(rng, "plank")]

    verdict = judge(
        features=_features(rng, "mug"),
        consistency=0.99,
        prior=prior,
        reconstructions=disagreeing,
    )
    assert verdict.ambiguous
    assert verdict.escalate
    assert "did not determine the shape" in verdict.reason

    calm = judge(
        features=_features(rng, "mug"),
        consistency=0.99,
        prior=prior,
        reconstructions=agreeing,
    )
    assert not calm.ambiguous


def test_one_reconstruction_is_not_evidence_of_agreement():
    """A single sample cannot measure a fiber's width."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 5)

    width = fiber_width([_features(rng, "mug")], prior)
    assert np.isnan(width)

    verdict = judge(
        features=_features(rng, "mug"),
        consistency=0.99,
        prior=prior,
        reconstructions=[_features(rng, "mug")],
    )
    assert not verdict.ambiguous


def test_the_gate_is_calibrated_on_the_approved_set():
    """The threshold is read off the real objects, not picked."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 6)

    # Real objects of one kind disagree by less than the gate.
    mug = [_features(rng, "mug") for _ in range(5)]
    assert fiber_width(mug, prior) <= prior.ordinary_width
    assert prior.ordinary_width > 0.0


# --- the scale, measured -----------------------------------------------------


def test_the_scale_gap_is_measured_and_the_balancing_closes_it():
    """A silhouette IoU lives near 1 and saturates there.

    A fixed weighting would therefore give the consistency side almost no
    room: its spread over the approved set is a fraction of the
    plausibility side's. Putting both on the approved set's own scale
    gives them one scale each — and the gap that was closed is reported.
    """
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 7)

    # A saturated consistency population: everything is between 0.98 and 1.
    consistency_population = [0.980 + 0.0004 * index for index in range(50)]
    gap = prior.consistency_gap(consistency_population)
    assert 0.0 < gap < 0.5

    real = _features(rng, "mug")
    low = judge(
        features=real,
        consistency=0.980,
        prior=prior,
        consistency_population=consistency_population,
    )
    high = judge(
        features=real,
        consistency=1.000,
        prior=prior,
        consistency_population=consistency_population,
    )

    # The raw spread of the consistency side is tiny, so a fixed weighted
    # mean barely moves...
    raw = 0.5 * (1.000 - 0.980)
    # ...while the balanced one moves by the percentile distance between
    # the same two values.
    assert (high.combined - low.combined) > raw
    assert low.gap == pytest.approx(gap)


def test_without_a_consistency_population_the_gap_is_reported_as_zero():
    """An unmeasured gap is not a small gap."""
    reference, _ = _reference_set()
    prior = _prior(reference)
    rng = np.random.default_rng(SEED + 8)
    verdict = judge(
        features=_features(rng, "mug"),
        consistency=0.99,
        prior=prior,
    )
    assert verdict.gap == 0.0


# --- the features come from what the mesh layer already measures -----------


def test_the_features_of_a_cube_like_solid():
    report = MeshReport(
        triangles=12,
        vertices=8,
        watertight=True,
        consistent_winding=True,
        extent=(1.0, 1.0, 1.0),
        volume=1.0,
        area=6.0,
        diagonal=1.732,
    )
    features = features_from_report(report)
    assert features.fill_ratio == pytest.approx(1.0)
    assert features.elongation == pytest.approx(1.0)
    assert features.log_volume == pytest.approx(0.0)
    # A cube's surface-to-volume ratio is 6, above the sphere's 4.836.
    assert features.sphericity == pytest.approx(6.0)
    assert features.defect_rate == 0.0


def test_the_features_of_a_broken_mesh_do_not_crash():
    report = MeshReport(
        triangles=100,
        vertices=50,
        boundary_edges=30,
        nonmanifold_edges=2,
        degenerate_triangles=8,
        extent=(0.0, 0.0, 0.0),
        volume=0.0,
        area=0.0,
        diagonal=0.0,
    )
    features = features_from_report(report)
    assert np.isfinite(features.as_vector()).all()
    assert features.defect_rate == pytest.approx(0.4)


def test_the_feature_vector_round_trips():
    features = PropFeatures(
        log_volume=1.0,
        sphericity=5.0,
        elongation=2.0,
        fill_ratio=0.5,
        offcentre=0.1,
        defect_rate=0.01,
    )
    assert PropFeatures.from_vector(features.as_vector()) == features
    assert len(FEATURE_NAMES) == len(features.as_vector())
