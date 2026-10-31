"""The rails: admission before spend, graduated throttling, the load cap.

Core-spec v2 §5.5 is the arithmetic of the night bar. Three things have to
hold at once:

* **admission is before spend** — a job whose ask the rail cannot cover is
  refused, not started and killed (T, citing AWS AGENTCOST07);
* **the throttle is graduated** — 80% drains, 95% stops, 100% writes the
  report now; a binary shutdown is how you get a morning report that says
  nothing happened;
* **the load cap is a fourth rail** — the hardware's binding constraint is
  weight-swap thrash, not VRAM, and no spend unit can count loads.
"""

from __future__ import annotations

import pytest

from core.night.models import Rail
from core.night.rails import (
    BudgetExceeded,
    LoadBudget,
    RailBudget,
    ThrottleLevel,
)


def test_admission_refuses_an_ask_the_rail_cannot_cover():
    budget = RailBudget(ceiling=Rail(gpu_minutes=10.0, wall_minutes=60.0))
    budget.admit(Rail(gpu_minutes=8.0, wall_minutes=10.0))
    assert not budget.can_admit(Rail(gpu_minutes=5.0, wall_minutes=10.0))


def test_admission_accepts_an_ask_that_fits_and_then_the_spend_is_recorded():
    budget = RailBudget(ceiling=Rail(gpu_minutes=10.0, wall_minutes=60.0))
    assert budget.can_admit(Rail(gpu_minutes=5.0, wall_minutes=10.0))
    budget.admit(Rail(gpu_minutes=5.0, wall_minutes=10.0))
    assert budget.spent == Rail(gpu_minutes=5.0, hosted_cents=0, wall_minutes=10.0)


def test_admitting_more_than_the_rail_allows_is_refused_loudly():
    budget = RailBudget(ceiling=Rail(gpu_minutes=10.0, wall_minutes=60.0))
    with pytest.raises(BudgetExceeded):
        budget.admit(Rail(gpu_minutes=11.0, wall_minutes=10.0))


def test_remaining_is_the_ceiling_minus_the_spend():
    budget = RailBudget(ceiling=Rail(gpu_minutes=10.0, hosted_cents=5, wall_minutes=60.0))
    budget.admit(Rail(gpu_minutes=4.0, hosted_cents=2, wall_minutes=10.0))
    assert budget.remaining == Rail(gpu_minutes=6.0, hosted_cents=3, wall_minutes=50.0)


def test_a_zero_rail_admits_nothing():
    budget = RailBudget(ceiling=Rail())
    assert not budget.can_admit(Rail(gpu_minutes=0.1))


def test_the_throttle_is_nominal_below_eighty_percent():
    budget = RailBudget(ceiling=Rail(gpu_minutes=100.0))
    budget.admit(Rail(gpu_minutes=79.0))
    assert budget.throttle_level() is ThrottleLevel.NOMINAL


def test_the_throttle_drains_at_eighty_percent():
    budget = RailBudget(ceiling=Rail(gpu_minutes=100.0))
    budget.admit(Rail(gpu_minutes=80.0))
    assert budget.throttle_level() is ThrottleLevel.DRAINING


def test_the_throttle_stops_at_ninety_five_percent():
    budget = RailBudget(ceiling=Rail(gpu_minutes=100.0))
    budget.admit(Rail(gpu_minutes=95.0))
    assert budget.throttle_level() is ThrottleLevel.STOPPING


def test_the_throttle_is_spent_at_one_hundred_percent():
    budget = RailBudget(ceiling=Rail(gpu_minutes=100.0))
    budget.admit(Rail(gpu_minutes=100.0))
    assert budget.throttle_level() is ThrottleLevel.SPENT


def test_the_throttle_follows_the_binding_axis():
    """The lane bar is nearly full while the money bar is untouched."""
    budget = RailBudget(
        ceiling=Rail(gpu_minutes=100.0, hosted_cents=100, wall_minutes=100.0)
    )
    budget.admit(Rail(gpu_minutes=10.0, hosted_cents=1, wall_minutes=96.0))
    assert budget.throttle_level() is ThrottleLevel.STOPPING


def test_the_load_cap_allows_one_load_per_model_by_default():
    """§1.9 — the default is one model load per model per night."""
    loads = LoadBudget()
    assert loads.can_load("trellis2")
    loads.record_load("trellis2")
    assert not loads.can_load("trellis2")


def test_the_load_cap_counts_each_model_separately():
    loads = LoadBudget()
    loads.record_load("trellis2")
    assert loads.can_load("sd-material")


def test_the_load_cap_can_be_raised_for_a_model():
    loads = LoadBudget(caps={"trellis2": 2})
    loads.record_load("trellis2")
    assert loads.can_load("trellis2")
    loads.record_load("trellis2")
    assert not loads.can_load("trellis2")


def test_the_load_cap_reports_the_count_against_the_cap():
    loads = LoadBudget(caps={"trellis2": 2})
    loads.record_load("trellis2")
    assert loads.counts() == {"trellis2": 1}
    assert loads.cap_for("trellis2") == 2
