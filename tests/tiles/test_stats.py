"""The numbers this seat reports: an interval with every rate, and a test
with every difference.

The house rule is that a number without its denominator is a fabrication,
and a difference without an interval is an opinion.
"""

from __future__ import annotations

from core.tiles.stats import newcombe_difference, normal_cdf, two_proportion_z, wilson_interval


def test_the_wilson_interval_brackets_the_rate():
    low, high = wilson_interval(30, 100)
    assert low < 0.30 < high


def test_the_wilson_interval_is_sane_at_zero():
    """The normal interval is nonsense at 0 wins out of 3; Wilson's is not."""
    low, high = wilson_interval(0, 3)
    assert low < 1e-12  # the lower bound is zero, up to float noise
    assert high > 0.0
    assert high < 1.0


def test_the_wilson_interval_of_no_trials_says_nothing():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_the_wilson_interval_narrows_with_more_trials():
    narrow = wilson_interval(300, 1000)
    wide = wilson_interval(3, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_the_newcombe_interval_brackets_the_difference():
    low, high = newcombe_difference(80, 100, 20, 100)
    assert low < 0.60 < high


def test_the_newcombe_interval_excludes_zero_when_the_difference_is_real():
    low, high = newcombe_difference(80, 100, 20, 100)
    assert low > 0.0


def test_the_newcombe_interval_includes_zero_when_there_is_no_difference():
    low, high = newcombe_difference(50, 100, 50, 100)
    assert low < 0.0 < high


def test_the_z_test_says_which_side():
    z, p = two_proportion_z(80, 100, 20, 100)
    assert z > 0
    assert p < 0.001


def test_the_z_test_finds_nothing_when_there_is_nothing():
    z, p = two_proportion_z(50, 100, 50, 100)
    assert abs(z) < 1e-9
    assert p == 1.0


def test_the_normal_cdf_is_a_distribution():
    assert normal_cdf(0.0) == 0.5
    assert 0.0 < normal_cdf(-3.0) < 0.01
    assert 0.99 < normal_cdf(3.0) < 1.0
