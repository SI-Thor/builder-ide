"""The night's staging plan: the scheduling lessons, written as rules.

The TRELLIS.2 spike found three things about this box that a scheduler has
to know (docs/research/trellis-spike.md §4.3, §4.4, §9):

* the **GPU stages batch by model** — the model is loaded once for the
  night, not once per prop, so the night's work is ordered by model rather
  than by request;
* the **mesh tail is the CPU lane** — remeshing, unwrapping and baking are
  most of a prop's cost and they are CPU-bound, so they are charged to the
  CPU lane and not to the GPU's bar;
* the **mesh tail is not overlapped with builds** — running two props at
  once makes their mesh tails fight over the same cores, and the spike
  measured a seven-fold swing under that contention. The night is serial.
"""

from __future__ import annotations

import pytest

from core.genbatch.models import PropRequest
from core.genbatch.schedule import NightPlan


def _requests() -> list[PropRequest]:
    return [
        PropRequest(id="crate", prompt="a weathered wooden crate", seeds=3),
        PropRequest(id="lantern", prompt="a dented brass lantern", seeds=3),
        PropRequest(id="anvil", prompt="a squat iron anvil", seeds=2),
    ]


def test_the_image_tasks_come_before_the_mesh_tasks():
    plan = NightPlan(_requests())

    kinds = [plan.stage_kind(task.id) for task in plan.tasks]

    assert kinds == ["image", "image", "image", "mesh", "mesh", "mesh"]


def test_the_stages_are_grouped_by_model():
    plan = NightPlan(_requests())

    stages = plan.stages

    assert [stage.model for stage in stages] == ["sd_xl_base_1.0", "trellis2"]
    assert len(stages[0].task_ids) == 3
    assert len(stages[1].task_ids) == 3


def test_a_request_that_brings_its_own_image_has_no_image_task():
    plan = NightPlan(
        [
            PropRequest(id="crate", prompt="a crate", seeds=3),
            PropRequest(id="given", prompt="", image="/tmp/given.png", seeds=3),
        ]
    )

    image_tasks = [
        task.id for task in plan.tasks if plan.stage_kind(task.id) == "image"
    ]

    assert image_tasks == ["img:crate"]


def test_the_seeds_come_from_the_request_and_repeat():
    plan = NightPlan(_requests())

    seeds = plan.seeds("crate")

    assert len(seeds) == 3
    assert seeds == plan.seeds("crate")
    assert seeds != plan.seeds("lantern")


def test_every_seed_is_different():
    plan = NightPlan(_requests())

    for request_id in ("crate", "lantern", "anvil"):
        assert len(set(plan.seeds(request_id))) == len(plan.seeds(request_id))


def test_the_plan_knows_which_model_each_task_needs():
    plan = NightPlan(_requests())

    assert plan.model_for("img:crate") == "sd_xl_base_1.0"
    assert plan.model_for("prop:crate") == "trellis2"


def test_the_night_runs_one_prompt_at_a_time():
    plan = NightPlan(_requests())

    assert plan.parallelism == 1


def test_the_iteration_policy_is_one_round_of_the_seeds():
    plan = NightPlan(_requests())

    assert plan.iteration_policy.variants_per_round == 3
    assert plan.iteration_policy.max_rounds == 1


def test_a_request_knows_its_own_task():
    plan = NightPlan(_requests())

    assert plan.request("prop:crate").id == "crate"
    assert plan.request("img:crate").id == "crate"
    assert plan.request("prop:nothing") is None


def test_the_cost_estimate_covers_the_requested_work():
    plan = NightPlan(_requests())

    image_task = next(task for task in plan.tasks if task.id == "img:crate")
    mesh_task = next(task for task in plan.tasks if task.id == "prop:crate")

    # Three images, then three props: the mesh stage is the slower one.
    assert image_task.cost_estimate.gpu_minutes > 0
    assert image_task.cost_estimate.wall_minutes > 0
    assert mesh_task.cost_estimate.wall_minutes > image_task.cost_estimate.wall_minutes


def test_the_costs_come_from_the_cost_model():
    """The schedule's numbers are the model's, not typed in here."""
    from core.night.cost import get_model

    plan = NightPlan(_requests())
    model = get_model()

    image_task = next(task for task in plan.tasks if task.id == "img:crate")
    mesh_task = next(task for task in plan.tasks if task.id == "prop:crate")
    picture = model.band("prop.image")
    prop = model.band("prop.512")

    assert image_task.kind == "prop.image"
    assert image_task.ask_source == "model"
    assert image_task.cost_estimate.gpu_minutes == pytest.approx(
        picture.p50.gpu_minutes * 3)
    assert image_task.cost_estimate.wall_minutes == pytest.approx(
        picture.p50.wall_minutes * 3)

    assert mesh_task.kind == "prop.512"
    assert mesh_task.cost_estimate.gpu_minutes == pytest.approx(
        prop.p50.gpu_minutes * 3)
    assert mesh_task.cost_estimate.wall_minutes == pytest.approx(
        prop.p50.wall_minutes * 3)


def test_the_rail_is_the_models_p95():
    """The rail is the bad case: past it, the work is stopped, not trusted."""
    from core.night.cost import get_model

    plan = NightPlan(_requests())
    picture = get_model().band("prop.image")

    image_task = next(task for task in plan.tasks if task.id == "img:crate")

    assert image_task.rail.wall_minutes == pytest.approx(picture.p95.wall_minutes * 3)
    assert image_task.rail.wall_minutes > image_task.cost_estimate.wall_minutes


def test_a_request_at_1024_is_priced_as_the_1024_prop():
    from core.night.cost import get_model

    plan = NightPlan([PropRequest(id="big", prompt="a big crate", seeds=1, resolution=1024)])
    mesh_task = next(task for task in plan.tasks if task.id == "prop:big")

    assert mesh_task.kind == "prop.1024"
    assert mesh_task.cost_estimate.gpu_minutes == pytest.approx(
        get_model().band("prop.1024").p50.gpu_minutes)


def test_the_executor_plans_the_same_price_the_task_asks_for():
    """The executor's plan and the task's ask are one measurement: otherwise
    the night cuts work it planned itself."""
    plan = NightPlan(_requests())

    for task in plan.tasks:
        request = plan.request(task.id)
        count = request.seeds
        gpu, wall = plan.per_variant_cost(task.id)
        assert task.cost_estimate.gpu_minutes == pytest.approx(gpu * count)
        assert task.cost_estimate.wall_minutes == pytest.approx(wall * count)
        assert task.rail.fits(task.cost_estimate)


def test_the_rules_name_what_the_spike_found():
    plan = NightPlan(_requests())

    names = {rule.name for rule in plan.rules}

    assert "batch_by_model" in names
    assert "cpu_mesh_tail" in names
    assert "no_overlap" in names
    assert "costs_from_the_model" in names
