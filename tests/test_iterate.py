"""The iterator's seams: variants, the critic, the power meter, the depth policy.

A night task is no longer one attempt (core-spec v2 §3.2.4): for each goal the
night generates **N variants**, scores each with the critic, keeps the best and
**refines from it** (warm start) for up to K rounds or until the score stops
improving by more than ε.

This file tests the seams themselves — the small interfaces the engine and the
GPU stations will implement — before the loop that drives them (the runner's
side of the seam is tested in :mod:`tests.test_loop`).

The rules under test:

* a variant is **seeded and bounded** — seeds are first-class (spec §1.9) and
  the same goal must give the same variants every time (determinism, §1.1);
* a warm start **perturbs around the parent**, it does not start over;
* the critic **never invents a score** — an unscored variant raises rather than
  quietly winning;
* the power meter **reads nothing yet** — the joules field stays unmeasured
  until lab round 3 supplies the Thor's rails;
* the depth policy (N, K, ε) is **part of the night's rails**, so it is
  loggable and foldable like the rest of the bar.
"""

from __future__ import annotations

import pytest

from core.night.iterate import (
    Attempt,
    CriticScore,
    IterationPolicy,
    NullPowerMeter,
    PerturbationSource,
    ScriptedCritic,
    ScriptedVariantSource,
    Variant,
    best_of,
    gain_of,
    summarise_rounds,
)
from core.night.models import Task


def a_task(task_id: str = "task_0001") -> Task:
    return Task(id=task_id, intention="Weather the harbour crates")


def test_the_depth_policy_is_three_variants_and_three_rounds_by_default():
    policy = IterationPolicy()
    assert policy.variants_per_round == 3
    assert policy.max_rounds == 3
    assert policy.min_gain == 0.02


def test_the_depth_policy_is_loggable_because_it_is_part_of_the_rails():
    payload = IterationPolicy(variants_per_round=4, max_rounds=2, min_gain=0.05).model_dump()
    assert payload == {
        "variants_per_round": 4,
        "max_rounds": 2,
        "min_gain": 0.05,
    }


def test_the_perturbation_source_gives_the_count_it_was_asked_for():
    source = PerturbationSource()
    variants = source.variants(a_task(), round=1, parent=None, count=4)
    assert len(variants) == 4


def test_the_perturbation_source_is_deterministic_across_runs():
    """The same goal gives the same variants every time (spec §1.1)."""
    first = PerturbationSource().variants(a_task(), round=1, parent=None, count=3)
    second = PerturbationSource().variants(a_task(), round=1, parent=None, count=3)
    assert [variant.seed for variant in first] == [variant.seed for variant in second]


def test_the_perturbation_source_gives_each_variant_its_own_seed():
    variants = PerturbationSource().variants(a_task(), round=1, parent=None, count=3)
    assert len({variant.seed for variant in variants}) == 3


def test_a_warm_start_perturbs_around_the_parent_it_was_given():
    source = PerturbationSource(base_params={"roughness": 0.4})
    parent = source.variants(a_task(), round=1, parent=None, count=1)[0]
    child = source.variants(a_task(), round=2, parent=parent, count=1)[0]

    assert child.parent_id == parent.id
    assert child.params["roughness"] != parent.params["roughness"]
    assert abs(child.params["roughness"] - parent.params["roughness"]) <= 0.05


def test_a_variant_perturbs_the_parents_parameters_not_the_origins():
    source = PerturbationSource(base_params={"roughness": 0.4})
    parent = source.variants(a_task(), round=1, parent=None, count=1)[0]
    child = source.variants(a_task(), round=2, parent=parent, count=1)[0]
    assert child.params["roughness"] != 0.4


def test_a_scripted_source_returns_the_variants_it_was_given():
    scripted = Variant(id="v_coarse", label="coarser planks", seed=17)
    source = ScriptedVariantSource({"task_0001": {1: [scripted]}})
    variants = source.variants(a_task(), round=1, parent=None, count=3)
    assert [variant.id for variant in variants] == ["v_coarse"]


def test_a_scripted_source_gives_nothing_for_a_round_it_does_not_script():
    source = ScriptedVariantSource({"task_0001": {1: [Variant(id="v1")]}})
    assert source.variants(a_task(), round=2, parent=None, count=3) == []


def test_the_scripted_critic_scores_the_variant_it_was_given():
    critic = ScriptedCritic(
        {"task_0001": {"v1": CriticScore(score=0.42, reason="the crates read clean")}}
    )
    score = critic.score(a_task(), Variant(id="v1"))
    assert score.score == 0.42
    assert score.reason == "the crates read clean"


def test_the_critic_refuses_to_invent_a_score_for_a_variant_it_does_not_know():
    """A score nobody measured must never win a variant by accident."""
    critic = ScriptedCritic({})
    with pytest.raises(KeyError):
        critic.score(a_task(), Variant(id="v1"))


def test_the_null_power_meter_measures_nothing_yet():
    """Lab round 3 supplies the Thor's rails; until then the joules stay empty."""
    assert NullPowerMeter().joules(gpu_minutes=30.0, wall_minutes=45.0) is None


def test_a_variant_carries_its_seed_its_parameters_and_its_edit():
    variant = Variant(
        id="v1",
        label="seed 1024",
        seed=1024,
        params={"roughness": 0.4},
        edit={"verb": "roughen", "target": "crates"},
    )
    assert variant.seed == 1024
    assert variant.params["roughness"] == 0.4
    assert variant.edit["verb"] == "roughen"


def test_the_iterators_seams_are_part_of_the_package_surface():
    """The loop is public: the engine and the GPU stations use these names."""
    import importlib

    module = importlib.import_module("core.night")
    for name in (
        "Critic",
        "CriticScore",
        "IterationPolicy",
        "NullPowerMeter",
        "PerturbationSource",
        "PowerMeter",
        "ScriptedCritic",
        "ScriptedVariantSource",
        "Variant",
        "VariantSource",
    ):
        assert name in module.__all__, name
        assert getattr(module, name) is not None, name


# -- the loop's arithmetic -------------------------------------------------


def attempt(variant_id: str, score: float, round: int = 1, **kwargs) -> Attempt:
    return Attempt(
        task_id="task_0001",
        variant_id=variant_id,
        score=score,
        round=round,
        **kwargs,
    )


def test_the_best_of_a_round_is_the_highest_scoring_variant_that_was_kept():
    attempts = [
        attempt("v1", 0.4),
        attempt("v2", 0.7),
        attempt("v3", 0.9, outcome="failed"),
    ]
    assert best_of(attempts).variant_id == "v2"


def test_a_round_with_nothing_kept_has_no_best():
    """A failed variant must never win by scoring high."""
    attempts = [attempt("v1", 0.9, outcome="failed")]
    assert best_of(attempts) is None


def test_the_gain_of_the_first_round_is_measured_against_nothing():
    assert gain_of(0.55, None) == pytest.approx(0.55)


def test_the_gain_of_a_round_is_measured_against_the_best_the_loop_had():
    assert gain_of(0.71, 0.55) == pytest.approx(0.16)


def test_the_rounds_summarise_the_quality_gained_in_each_of_them():
    rounds = summarise_rounds(
        [
            attempt("v1", 0.4, 1),
            attempt("v2", 0.55, 1),
            attempt("w1", 0.71, 2),
            attempt("w2", 0.60, 2),
        ]
    )
    assert [row.round for row in rounds] == [1, 2]
    assert [row.variants for row in rounds] == [2, 2]
    assert [row.best_score for row in rounds] == [pytest.approx(0.55), pytest.approx(0.71)]
    assert [row.gain for row in rounds] == [pytest.approx(0.55), pytest.approx(0.16)]


def test_a_round_summary_carries_the_cost_the_round_burned():
    rounds = summarise_rounds(
        [
            attempt("v1", 0.4, 1, gpu_minutes=30.0, wall_minutes=45.0),
            attempt("v2", 0.5, 1, gpu_minutes=30.0, wall_minutes=45.0),
        ]
    )
    assert rounds[0].gpu_minutes == pytest.approx(60.0)
    assert rounds[0].wall_minutes == pytest.approx(90.0)


def test_a_round_summary_leaves_the_joules_unmeasured_until_the_meter_reads_them():
    rounds = summarise_rounds([attempt("v1", 0.4, 1, joules=None)])
    assert rounds[0].joules is None


def test_a_round_summary_adds_the_joules_when_the_meter_has_read_them():
    rounds = summarise_rounds(
        [attempt("v1", 0.4, 1, joules=12.0), attempt("v2", 0.5, 1, joules=8.0)]
    )
    assert rounds[0].joules == pytest.approx(20.0)
