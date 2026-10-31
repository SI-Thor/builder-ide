"""Small statistics for the seat's own claims (§3, and the acceptance run).

Every number this seat reports about a win rate comes with its
denominator, and every *claim* about a difference comes with an interval.
A win rate without an interval is a number somebody could have picked.

Three functions, all standard and all in the standard library:

* :func:`wilson_interval` — the interval for **one** rate. Wilson's
  interval, not the normal one: the normal interval is nonsense at 0 wins
  out of 3, which is exactly the case a cold start is in.
* :func:`newcombe_difference` — the interval for the **difference** of two
  rates (Newcombe's method 10). The acceptance run compares a chooser
  against a uniform pick, and that is a difference of two proportions, so
  that is what gets an interval.
* :func:`two_proportion_z` — the test statistic and the p-value for the
  same comparison, for when a single number is wanted.

No third-party dependency: this seat runs on the Thor with the renderer and
the decision models, and a statistics library is not worth the bytes.
"""

from __future__ import annotations

import math

__all__ = [
    "Z_95",
    "wilson_interval",
    "newcombe_difference",
    "two_proportion_z",
    "normal_cdf",
]

#: The two-sided 95% normal quantile.
Z_95 = 1.959963984540054


def normal_cdf(x: float) -> float:
    """The standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def wilson_interval(
    successes: int, trials: int, *, z: float = Z_95
) -> tuple[float, float]:
    """The Wilson score interval for a rate.

    ``(0.0, 0.0)`` for no trials: there is nothing to be sure about yet,
    and pretending otherwise is how a cold start turns into a claim.
    """
    if trials <= 0:
        return (0.0, 0.0)
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between 0 and trials")

    p = successes / trials
    denominator = 1.0 + (z * z) / trials
    centre = (p + (z * z) / (2 * trials)) / denominator
    margin = (
        z
        * math.sqrt((p * (1.0 - p) / trials) + (z * z / (4.0 * trials * trials)))
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def newcombe_difference(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
    *,
    z: float = Z_95,
) -> tuple[float, float]:
    """Newcombe's method 10: the interval for the difference of two rates.

    ``a - b``. Each rate gets a Wilson interval, and the difference's
    interval is built from the two gaps to their own bounds — which is
    what makes it behave at the small samples a cold start produces.
    """
    if trials_a <= 0 or trials_b <= 0:
        return (0.0, 0.0)

    p_a = successes_a / trials_a
    p_b = successes_b / trials_b
    low_a, high_a = wilson_interval(successes_a, trials_a, z=z)
    low_b, high_b = wilson_interval(successes_b, trials_b, z=z)

    difference = p_a - p_b
    lower = difference - math.sqrt((p_a - low_a) ** 2 + (high_b - p_b) ** 2)
    upper = difference + math.sqrt((high_a - p_a) ** 2 + (p_b - low_b) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


def two_proportion_z(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
) -> tuple[float, float]:
    """The two-proportion z statistic and its two-sided p-value."""
    if trials_a <= 0 or trials_b <= 0:
        return (0.0, 1.0)

    p_a = successes_a / trials_a
    p_b = successes_b / trials_b
    pooled = (successes_a + successes_b) / (trials_a + trials_b)
    standard_error = math.sqrt(pooled * (1.0 - pooled) * (1.0 / trials_a + 1.0 / trials_b))
    if standard_error == 0.0:
        return (0.0, 1.0)
    z = (p_a - p_b) / standard_error
    return (z, 2.0 * (1.0 - normal_cdf(abs(z))))
