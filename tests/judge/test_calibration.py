"""One definition of confidence, and the calibration tracked against it.

The seed bank #2 (B15) asks three things, and this file exercises each of
them:

* **one definition** — the same function computes the confidence for every
  backend, from the distribution the backend returned, and the three
  definitions the seed named are compared on the same rows;
* **the metrics** — the Brier score, the expected calibration error over
  reliability bins, the reliability curve, and the escalation sweep;
* **recalibration as a parameter** — a temperature or an isotonic map fitted
  on one split of the outcomes and read on another, kept only when it
  improves the held-out Brier score.

The numbers here are hand-computed, not copied from a run: a test that
agrees with a recorded number only proves the code still does what it did.
"""

from __future__ import annotations

import math

import pytest

from core.judge.calibration import (
    CANONICAL_CONFIDENCE,
    CONFIDENCE_DEFINITIONS,
    CalibrationSample,
    IsotonicScale,
    TemperatureScale,
    accuracy,
    area_under_curve,
    brier_score,
    cell_of,
    cells_of,
    confidence_of,
    drift_of,
    escalation_sweep,
    expected_calibration_error,
    fit_isotonic,
    fit_temperature,
    mean_confidence,
    recalibrate,
    reliability_curve,
)


def _binary(p_true: float) -> dict[str, float]:
    return {"true": p_true, "false": round(1.0 - p_true, 10)}


def _sample(
    *,
    p_true: float,
    outcome: bool,
    backend: str = "d1",
    model: str = "d1-2B",
    task: str = "tiles",
    qid: str = "q",
    at: str = "2026-10-31T00:00:00Z",
) -> CalibrationSample:
    """One binary judgment and its outcome."""
    return CalibrationSample(
        backend=backend,
        model=model,
        task=task,
        kind="noul",
        qid=qid,
        distribution=_binary(p_true),
        outcome=outcome,
        truth="true" if outcome else "false",
        at=at,
    )


# --- the definitions ------------------------------------------------------------


def test_the_three_definitions_are_the_ones_the_seed_named():
    assert CONFIDENCE_DEFINITIONS == (
        "top_probability",
        "normalised_margin",
        "entropy_normalised",
    )
    assert CANONICAL_CONFIDENCE == "top_probability"


def test_top_probability_is_the_probability_the_backend_gave_its_own_answer():
    assert confidence_of({"a": 0.7, "b": 0.3}, "top_probability") == pytest.approx(0.7)


def test_the_normalised_margin_is_the_lfm2_formula():
    # (p_max − 1/K) / (1 − 1/K) on two options: (0.7 − 0.5) / 0.5
    assert confidence_of({"a": 0.7, "b": 0.3}, "normalised_margin") == pytest.approx(0.4)
    # on five options: (0.9 − 0.2) / 0.8
    five = {"a": 0.9, "b": 0.025, "c": 0.025, "d": 0.025, "e": 0.025}
    assert confidence_of(five, "normalised_margin") == pytest.approx(0.875)


def test_the_entropy_score_is_one_on_a_point_mass_and_zero_on_the_uniform():
    point = {"a": 1.0, "b": 0.0, "c": 0.0}
    assert confidence_of(point, "entropy_normalised") == pytest.approx(1.0)
    uniform = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    assert confidence_of(uniform, "entropy_normalised") == pytest.approx(0.0, abs=1e-9)


def test_the_entropy_score_on_a_known_pair():
    # H(0.7, 0.3) = 0.6108643...; ln 2 = 0.6931472...
    entropy = -(0.7 * math.log(0.7) + 0.3 * math.log(0.3))
    expected = 1.0 - entropy / math.log(2.0)
    assert confidence_of({"a": 0.7, "b": 0.3}, "entropy_normalised") == pytest.approx(expected)


def test_a_distribution_that_does_not_sum_to_one_is_refused():
    with pytest.raises(ValueError, match="sums to one"):
        confidence_of({"a": 0.7, "b": 0.2}, "top_probability")


def test_a_negative_probability_is_refused():
    with pytest.raises(ValueError, match="negative"):
        confidence_of({"a": 1.2, "b": -0.2}, "top_probability")


def test_an_unknown_definition_is_refused():
    with pytest.raises(ValueError, match="unknown confidence definition"):
        confidence_of({"a": 1.0}, "vibes")  # type: ignore[arg-type]


def test_a_binary_confidence_cannot_fall_below_a_half():
    """One of two options always holds at least half the mass.

    This is the fact the seed's threshold has to respect: a τ below a half
    cannot escalate an undecided noul, because an undecided noul's top
    probability is exactly a half.
    """
    assert confidence_of(_binary(0.5), "top_probability") == pytest.approx(0.5)
    assert confidence_of(_binary(0.0), "top_probability") == pytest.approx(1.0)


# --- the sample -----------------------------------------------------------------


def test_a_sample_carries_its_cell():
    sample = _sample(p_true=0.9, outcome=True)
    assert sample.cell == ("d1", "d1-2B", "tiles")


def test_the_truth_is_named_from_the_outcome_on_a_binary_question():
    right = _sample(p_true=0.9, outcome=True)
    wrong = _sample(p_true=0.9, outcome=False)
    assert right.truth_key() == "true"
    assert wrong.truth_key() == "false"


def test_a_k_way_question_without_a_recorded_truth_is_scored_for_accuracy_only():
    sample = CalibrationSample(
        backend="d1",
        model="d1-2B",
        task="tiles",
        kind="choice",
        qid="q",
        distribution={"a": 0.6, "b": 0.3, "c": 0.1},
        outcome=True,
    )
    assert sample.truth_key() is None
    assert sample.brier() is None


# --- the metrics ----------------------------------------------------------------


def test_the_brier_score_of_a_binary_judgment():
    # right: (0.8 − 1)² + (0.2 − 0)² = 0.08, over two options
    right = _sample(p_true=0.8, outcome=True)
    assert right.brier() == pytest.approx(0.04)
    # wrong: (0.8 − 0)² + (0.2 − 1)² = 1.28, over two options
    wrong = _sample(p_true=0.8, outcome=False)
    assert wrong.brier() == pytest.approx(0.64)


def test_the_brier_score_of_a_k_way_judgment_is_divided_by_k():
    sample = CalibrationSample(
        backend="d1",
        model="d1-2B",
        task="tiles",
        kind="choice",
        qid="q",
        distribution={"a": 0.6, "b": 0.3, "c": 0.1},
        outcome=True,
        truth="a",
    )
    # (0.4)² + (0.3)² + (0.1)² = 0.26, over three options
    assert sample.brier() == pytest.approx(0.26 / 3.0)


def test_the_brier_score_is_a_mean_over_the_scorable_samples():
    samples = [
        _sample(p_true=0.8, outcome=True),
        _sample(p_true=0.8, outcome=False),
    ]
    assert brier_score(samples) == pytest.approx((0.04 + 0.64) / 2.0)


def test_accuracy_is_the_share_that_were_right():
    samples = [
        _sample(p_true=0.9, outcome=True),
        _sample(p_true=0.9, outcome=False),
        _sample(p_true=0.9, outcome=True),
        _sample(p_true=0.9, outcome=True),
    ]
    assert accuracy(samples) == pytest.approx(0.75)


def test_mean_confidence_is_the_mean_under_the_named_definition():
    samples = [_sample(p_true=0.9, outcome=True), _sample(p_true=0.7, outcome=True)]
    assert mean_confidence(samples) == pytest.approx(0.8)
    assert mean_confidence(samples, "normalised_margin") == pytest.approx((0.8 + 0.4) / 2.0)


def test_the_reliability_curve_bins_on_the_confidence():
    samples = [_sample(p_true=0.95, outcome=True), _sample(p_true=0.55, outcome=False)]
    curve = reliability_curve(samples, bins=10)
    assert curve[9].n == 1
    assert curve[9].mean_confidence == pytest.approx(0.95)
    assert curve[9].accuracy == pytest.approx(1.0)
    assert curve[9].gap == pytest.approx(0.05)
    assert curve[5].n == 1
    assert curve[5].gap == pytest.approx(-0.55)


def test_the_reliability_curve_puts_a_full_confidence_in_the_last_bin():
    samples = [_sample(p_true=1.0, outcome=True)]
    curve = reliability_curve(samples, bins=10)
    assert curve[-1].n == 1
    assert sum(bin_.n for bin_ in curve) == 1


def test_the_expected_calibration_error_is_the_weighted_mean_of_the_gaps():
    # two samples in one bin: confidence 0.9, one right one wrong — the
    # accuracy is 0.5, so the gap is 0.5 − 0.9 = −0.4
    samples = [_sample(p_true=0.9, outcome=True), _sample(p_true=0.9, outcome=False)]
    assert expected_calibration_error(samples, bins=10) == pytest.approx(0.4)
    # one sample: confidence 0.6, right — the gap is 1.0 − 0.6 = 0.4
    one = [_sample(p_true=0.6, outcome=True)]
    assert expected_calibration_error(one, bins=10) == pytest.approx(0.4)


def test_a_honest_cell_has_a_zero_error():
    """Ten judgments at 0.6, six of them right — the model says what it means."""
    samples = [_sample(p_true=0.6, outcome=index < 6) for index in range(10)]
    assert expected_calibration_error(samples, bins=10) == pytest.approx(0.0, abs=1e-9)


def test_an_over_confident_cell_has_a_positive_error():
    """Ten judgments at 0.9, all of them right — it claimed more than it had."""
    samples = [_sample(p_true=0.9, outcome=True) for _ in range(10)]
    assert expected_calibration_error(samples, bins=10) == pytest.approx(0.1)


def test_the_escalation_sweep_counts_what_the_gate_would_have_caught():
    samples = [
        _sample(p_true=0.9, outcome=True),   # right, confident
        _sample(p_true=0.9, outcome=True),
        _sample(p_true=0.6, outcome=False),  # wrong, below τ = 0.7
    ]
    rows = {row.tau: row for row in escalation_sweep(samples, taus=(0.5, 0.7))}
    at_seven = rows[0.7]
    assert at_seven.escalated == 1
    assert at_seven.catch == pytest.approx(1.0)
    assert at_seven.tax == pytest.approx(0.0)
    assert at_seven.act_rate == pytest.approx(2 / 3)
    assert at_seven.caught_all is True
    at_nine = rows[0.5]
    assert at_nine.escalated == 0
    assert at_nine.catch == pytest.approx(0.0)
    assert at_nine.tax == pytest.approx(0.0)


def test_a_gate_at_a_half_can_never_escalate_a_binary_question():
    """The fact the seed's threshold has to respect.

    A binary question's confidence — the probability of its own answer — is
    never below a half, so a gate that escalates below τ = 0.5 escalates
    nothing at all. The τ that catches an undecided noul is above a half.
    """
    samples = [_sample(p_true=0.5, outcome=False) for _ in range(10)]
    rows = {row.tau: row for row in escalation_sweep(samples, taus=(0.5, 0.51))}
    assert rows[0.5].escalated == 0
    assert rows[0.5].catch == pytest.approx(0.0)
    assert rows[0.51].escalated == 10
    assert rows[0.51].catch == pytest.approx(1.0)


def test_the_sweep_reports_a_gate_that_catches_nothing():
    samples = [_sample(p_true=0.9, outcome=False)]
    rows = escalation_sweep(samples, taus=(0.5,))
    assert rows[0].catch == pytest.approx(0.0)
    assert rows[0].caught_all is False


def test_the_area_under_the_curve_reads_the_separability():
    assert area_under_curve([(0.9, True), (0.1, False)]) == pytest.approx(1.0)
    assert area_under_curve([(0.9, False), (0.1, True)]) == pytest.approx(0.0)
    assert area_under_curve([(0.5, True), (0.5, False)]) == pytest.approx(0.5)
    assert area_under_curve([(0.9, True)]) is None


# --- the cell -------------------------------------------------------------------


def test_a_cell_carries_its_numbers_under_every_definition():
    samples = [
        _sample(p_true=0.9, outcome=True),
        _sample(p_true=0.6, outcome=False),
    ]
    cell = cell_of(samples)
    assert cell.n == 2
    assert cell.accuracy == pytest.approx(0.5)
    assert cell.mean_confidence == pytest.approx(0.75)
    # the Brier score is computed over the whole vector, so it does not
    # depend on the definition — the ECE and the mean confidence do.
    assert cell.per_definition["top_probability"]["brier"] == pytest.approx(
        cell.per_definition["entropy_normalised"]["brier"]
    )
    assert cell.per_definition["top_probability"]["ece"] != pytest.approx(
        cell.per_definition["entropy_normalised"]["ece"]
    )


def test_cells_are_grouped_by_backend_model_and_task():
    samples = [
        _sample(p_true=0.9, outcome=True),
        _sample(p_true=0.9, outcome=True, model="d1-3B"),
        _sample(p_true=0.9, outcome=True, task="defect"),
    ]
    cells = cells_of(samples)
    assert [cell.key for cell in cells] == [
        ("d1", "d1-2B", "defect"),
        ("d1", "d1-2B", "tiles"),
        ("d1", "d1-3B", "tiles"),
    ]


# --- the recalibration scales ---------------------------------------------------


def test_a_temperature_softens_an_over_confident_model():
    """Ten judgments at 0.9, five of them right.

    The right answer is a temperature above one: the model's 0.9 is worth
    much less than 0.9, and the fitted map has to say so.
    """
    samples = [_sample(p_true=0.9, outcome=index < 5) for index in range(10)]
    scale = fit_temperature(samples)
    assert float(scale.params["temperature"]) > 1.0
    calibrated = scale.apply(_binary(0.9))
    assert calibrated["true"] < 0.9


def test_a_temperature_sharpens_an_under_confident_model():
    """Ten judgments at 0.6, eight of them right."""
    samples = [_sample(p_true=0.6, outcome=index < 8) for index in range(10)]
    scale = fit_temperature(samples)
    assert float(scale.params["temperature"]) < 1.0
    calibrated = scale.apply(_binary(0.6))
    assert calibrated["true"] > 0.6


def test_a_well_calibrated_model_is_left_alone():
    """Ten judgments at 0.7, seven of them right — the model is honest."""
    samples = [_sample(p_true=0.7, outcome=index < 7) for index in range(10)]
    scale = fit_temperature(samples)
    assert float(scale.params["temperature"]) == pytest.approx(1.0, abs=0.05)


def test_the_temperature_fit_is_deterministic():
    samples = [_sample(p_true=0.9, outcome=index < 5) for index in range(10)]
    assert fit_temperature(samples) == fit_temperature(samples)


def test_an_isotonic_map_is_monotone():
    samples = []
    for index in range(20):
        p = 0.2 + 0.04 * index
        samples.append(_sample(p_true=p, outcome=index % 2 == 0))
    scale = fit_isotonic(samples)
    mapped = [scale.map(0.1 + 0.05 * index) for index in range(20)]
    assert all(later >= earlier - 1e-9 for earlier, later in zip(mapped, mapped[1:]))


def test_an_isotonic_map_keeps_the_ranking_of_the_distribution():
    """A calibration is not a ranking error.

    The cascade's choice prior exists for this reason: a map may soften the
    top option's mass, but it may not make the runner-up the answer.
    """
    scale = IsotonicScale(params={"knots": [[0.0, 0.9], [1.0, 0.95]]})
    scaled = scale.apply({"a": 0.6, "b": 0.4})
    assert scaled["a"] > scaled["b"]


def test_a_recalibration_is_kept_only_when_the_held_out_brier_improves():
    """The fit half says 0.9; the held-out half says 0.9 and is wrong.

    The scale that the fit half wants (sharpen towards 1.0) makes the
    held-out half worse, so it is dropped and the raw confidence stands.
    """
    fit = [_sample(p_true=0.9, outcome=True) for _ in range(10)]
    holdout = [_sample(p_true=0.9, outcome=False) for _ in range(10)]
    result = recalibrate(fit, holdout)
    assert result.kept is False
    assert result.held_out_brier_before == pytest.approx(0.81)
    assert result.held_out_brier_after > result.held_out_brier_before
    assert "raw confidence is kept" in result.reason


def test_a_recalibration_is_kept_when_the_held_out_brier_improves():
    fit = [_sample(p_true=0.9, outcome=index < 5) for index in range(10)]
    holdout = [_sample(p_true=0.9, outcome=index < 5) for index in range(10)]
    result = recalibrate(fit, holdout)
    assert result.kept is True
    assert result.held_out_brier_after < result.held_out_brier_before
    assert result.kind in ("temperature", "isotonic")
    assert result.scale is not None


def test_a_recalibration_with_nothing_to_fit_on_is_not_kept():
    result = recalibrate([], [])
    assert result.kept is False
    assert result.reason == "no outcomes to fit on"


# --- the drift ------------------------------------------------------------------


def test_a_cell_that_never_moved_does_not_drift():
    samples = [_sample(p_true=0.9, outcome=index % 4 != 0) for index in range(20)]
    assert drift_of(samples, window=5) == []


def test_a_confidence_that_stops_ordering_is_a_drift():
    """The newest window's confidence no longer puts the right ones on top."""
    samples = [
        # the old window: confident and right, unsure and wrong — it separated
        _sample(p_true=0.95, outcome=True),
        _sample(p_true=0.55, outcome=False),
        # the new window: the wrong one is the confident one
        _sample(p_true=0.95, outcome=False),
        _sample(p_true=0.55, outcome=True),
    ]
    lines = drift_of(samples, window=2)
    kinds = {line.kind for line in lines}
    assert "separability_lost" in kinds
    lost = next(line for line in lines if line.kind == "separability_lost")
    assert "no longer orders right above wrong" in lost.detail
    assert lost.retune


def test_a_confidence_that_never_separated_has_not_drifted():
    """A constant confidence cannot order anything, and never did.

    The rule is that the separability **fell** to the coin-flip line, so a
    cell that sat on the line all along is not a drifting cell — it is a
    cell whose confidence was never a routing signal, and saying that every
    night would be noise.
    """
    samples = [_sample(p_true=0.9, outcome=index % 4 != 0) for index in range(20)]
    assert {line.kind for line in drift_of(samples, window=5)} == set()


def test_a_calibration_that_moved_further_than_it_ever_has_is_a_drift():
    """Three windows: the newest one's calibration moved more than the last."""
    samples = []
    # window 0: honest (confidence 0.9, right) — the noise floor is 0
    for _ in range(4):
        samples.append(_sample(p_true=0.9, outcome=True))
    # window 1: honest again — the floor is still 0
    for _ in range(4):
        samples.append(_sample(p_true=0.9, outcome=True))
    # window 2: the same confidence, now wrong — the gap opens
    for _ in range(4):
        samples.append(_sample(p_true=0.9, outcome=False))
    lines = drift_of(samples, window=4)
    kinds = {line.kind for line in lines}
    assert "calibration_moved" in kinds
    moved = next(line for line in lines if line.kind == "calibration_moved")
    assert "refitted" in moved.retune


def test_a_stale_recalibration_is_a_drift():
    """The scale fitted on the old window no longer helps the new one."""
    samples = []
    # the old window: confident and right — the scale sharpens towards 1.0
    for _ in range(4):
        samples.append(_sample(p_true=0.9, outcome=True))
    # the new window: confident and wrong — sharpening now hurts
    for _ in range(4):
        samples.append(_sample(p_true=0.9, outcome=False))
    lines = drift_of(samples, window=4)
    kinds = {line.kind for line in lines}
    assert "recalibration_stale" in kinds
    stale = next(line for line in lines if line.kind == "recalibration_stale")
    assert "no longer improves" in stale.detail


def test_a_drift_line_names_the_model_and_the_task():
    samples = [
        _sample(p_true=0.95, outcome=True, model="clef-flash", task="enemy_visible"),
        _sample(p_true=0.55, outcome=False, model="clef-flash", task="enemy_visible"),
        _sample(p_true=0.95, outcome=False, model="clef-flash", task="enemy_visible"),
        _sample(p_true=0.55, outcome=True, model="clef-flash", task="enemy_visible"),
    ]
    line = drift_of(samples, window=2)[0]
    assert line.name == "d1:clef-flash · enemy_visible"
    assert line.backend == "d1"
    assert line.model == "clef-flash"
    assert line.task == "enemy_visible"
    assert line.as_dict()["kind"] == line.kind
