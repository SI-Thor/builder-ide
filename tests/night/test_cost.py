"""The cost model: the night's arithmetic, measured.

The model is only worth anything if it is **measured**, so these tests do
not check that the model returns a number — they check that the number is
the number the recorded data says it should be. Three kinds of check:

* **against the recorded file** — the model's p50 and p95 are re-derived
  here, straight from ``core/night/cost/data/``, and compared. If the model
  changes how it computes a percentile, this fails.
* **against the source document** — a few numbers are pinned to the lab
  notes they came from (the TRELLIS spike's wall-clock range, the sweep's
  render p50, the rails' watts), so a wrong *recording* fails too, not just
  a wrong *computation*.
* **against the night that actually ran** — the model is asked what the
  mini-night cost and has to land on what the mini-night's own ledger says
  it cost.

The joules are checked against the board's measured rails, the admission
check is checked against the rails it is given, and the owner's two lines are
checked for saying what they are for: what it costs, and what is cut.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from core.night.cost import (
    CostModel,
    NightPlan,
    PlannedJob,
    admission_check,
    get_model,
    load_recorded,
    owner_estimate,
    percentile,
)
from core.night.cost.records import DATA_DIR
from core.night.models import Rail
from core.night.rails import LoadBudget


@pytest.fixture()
def model() -> CostModel:
    return get_model()


def _percentile(values: list[float], q: float) -> float:
    """The percentile, computed here — deliberately not the model's function."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[int(position)]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _sweep_rows() -> list[dict[str, str]]:
    with (DATA_DIR / "infinigen_sweep.tsv").open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# -- the recorded data is what it says it is --------------------------------


def test_the_sweep_snapshot_is_the_one_the_index_records():
    index = json.loads((DATA_DIR / "recorded.json").read_text())
    source = index["sources"]["sweep"]
    rows = _sweep_rows()
    assert len(rows) == source["rows"]
    import hashlib

    digest = hashlib.md5((DATA_DIR / "infinigen_sweep.tsv").read_bytes()).hexdigest()
    assert digest == source["md5"], "the sweep snapshot was edited; re-record it"


def test_every_scene_and_stage_the_sweep_has_is_offered_by_the_model(model):
    scenes = sorted({row["scene"] for row in _sweep_rows()})
    for scene in scenes:
        for stage in ("coarse", "fine", "render"):
            band = model.infinigen_stage(scene, stage)
            assert band.p50.samples >= 4, f"{scene}/{stage} has too few samples"


def test_an_unknown_scene_type_is_refused_by_name(model):
    with pytest.raises(KeyError) as caught:
        model.infinigen_stage("swamp", "coarse")
    assert "swamp" in str(caught.value)


# -- the model agrees with the recorded file ---------------------------------


def test_the_infinigen_render_p50_is_the_sweeps_own_render_p50(model):
    rows = [row for row in _sweep_rows() if row["stage"] == "render"]
    seconds = [float(row["seconds"]) for row in rows]
    expected = _percentile(seconds, 0.50) / 60.0
    assert model.band("rung.2").p50.wall_minutes == pytest.approx(expected)
    # and the spec's "about a minute" is the measured number
    assert 0.9 < model.band("rung.2").p50.wall_minutes < 1.2


def test_the_infinigen_coarse_p50_is_the_sweeps_own_coarse_p50(model):
    rows = [row for row in _sweep_rows() if row["stage"] == "coarse"]
    seconds = [float(row["seconds"]) for row in rows]
    expected = _percentile(seconds, 0.50) / 60.0
    band = model.band("infinigen.coarse")
    assert band.p50.cpu_lane_minutes == pytest.approx(expected)
    assert band.p50.gpu_minutes == 0.0, "the coarse stage is the solver's, on the CPU"


def test_the_scenes_own_coarse_cost_is_its_own_sample_set(model):
    rows = [
        row
        for row in _sweep_rows()
        if row["stage"] == "coarse" and row["scene"] == "forest"
    ]
    seconds = [float(row["seconds"]) for row in rows]
    expected = _percentile(seconds, 0.50) / 60.0
    band = model.infinigen_stage("forest", "coarse")
    assert band.p50.wall_minutes == pytest.approx(expected)
    assert band.scene == "forest"


def test_the_model_never_claims_a_p95_below_its_p50(model):
    for kind in model.kinds():
        band = model.band(kind)
        assert band.p95.wall_minutes >= band.p50.wall_minutes, kind
        assert band.p95.gpu_minutes >= band.p50.gpu_minutes, kind


def test_the_sweeps_p95_is_the_recorded_p95(model):
    """The p95 is the 95th percentile of the record, not the p50 again."""
    rows = _sweep_rows()
    for stage, kind in (
        ("coarse", "infinigen.coarse"),
        ("fine", "infinigen.fine"),
        ("render", "infinigen.render"),
    ):
        seconds = [float(row["seconds"]) for row in rows if row["stage"] == stage]
        expected = _percentile(seconds, 0.95) / 60.0
        assert model.band(kind).p95.wall_minutes == pytest.approx(expected), kind
    render = [float(row["seconds"]) for row in rows if row["stage"] == "render"]
    assert model.band("rung.2").p95.wall_minutes == pytest.approx(
        _percentile(render, 0.95) / 60.0
    )
    # and the p95 really is above the p50 on the sweep's own numbers
    assert model.band("rung.2").p95.wall_minutes > model.band("rung.2").p50.wall_minutes


def test_the_mini_nights_p95_is_the_recorded_p95(model):
    document = json.loads((DATA_DIR / "mini_night.json").read_text())
    for kind, wanted in (("prop.image", "image"), ("prop.night", "prop")):
        wall = [
            sample["wall_seconds"]
            for sample in document["samples"]
            if sample["kind"] == wanted
        ]
        gpu = [
            sample["gpu_seconds"]
            for sample in document["samples"]
            if sample["kind"] == wanted
        ]
        band = model.band(kind)
        assert band.p95.wall_minutes == pytest.approx(_percentile(wall, 0.95) / 60.0)
        assert band.p95.gpu_minutes == pytest.approx(_percentile(gpu, 0.95) / 60.0)
        assert band.p95.wall_minutes > band.p50.wall_minutes


def test_the_recorded_props_p95_is_the_recorded_p95(model):
    index = json.loads((DATA_DIR / "recorded.json").read_text())
    for kind in ("prop.512", "prop.1024", "rung.3"):
        samples = index["jobs"][kind]["samples"]
        wall = [sample["wall_seconds"] for sample in samples]
        gpu = [sample["gpu_seconds"] for sample in samples]
        band = model.band(kind)
        assert band.p95.wall_minutes == pytest.approx(_percentile(wall, 0.95) / 60.0)
        assert band.p95.gpu_minutes == pytest.approx(_percentile(gpu, 0.95) / 60.0)


def test_the_critics_recorded_p95_is_the_recorded_p95(model):
    document = json.loads((DATA_DIR / "critic_verdict.json").read_text())
    judge = [
        value
        for asset in document["assets"]
        for value in asset["judge_seconds"]
    ]
    band = model.critic_verdict()
    assert band.p95.wall_minutes == pytest.approx(_percentile(judge, 0.95) / 60.0)


# -- the model agrees with the source documents ------------------------------


def test_the_512_prop_is_the_trellis_spikes_wall_clock_range(model):
    """docs/research/trellis-spike.md §0: 512³ in 98-115 s, 1024³ in 166-179 s."""
    assert 98.0 <= model.band("prop.512").p50.wall_seconds <= 115.0
    assert 166.0 <= model.band("prop.1024").p50.wall_seconds <= 179.0


def test_the_nights_own_prop_costs_more_than_the_bare_generator(model):
    """The mini-night's prop also measures the mesh and writes the GLB."""
    assert (
        model.band("prop.night").p50.wall_seconds
        > model.band("prop.512").p50.wall_seconds
    )


def test_the_1024_props_sampling_is_the_part_that_scales(model):
    """§4.2: the sampling scales with resolution; the mesh tail does not."""
    gpu_512 = model.band("prop.512").p50.gpu_seconds
    gpu_1024 = model.band("prop.1024").p50.gpu_seconds
    cpu_512 = model.band("prop.512").p50.cpu_seconds
    cpu_1024 = model.band("prop.1024").p50.cpu_seconds
    assert gpu_1024 > 3 * gpu_512, "the sampling quadruples from 512³ to 1024³"
    assert abs(cpu_1024 - cpu_512) < 0.5 * cpu_512, "the mesh tail is a fixed ~80 s"


def test_the_1024_prop_costs_more_sampling_than_the_512_one(model):
    gpu_512 = model.band("prop.512").p50.gpu_minutes
    gpu_1024 = model.band("prop.1024").p50.gpu_minutes
    assert gpu_1024 > gpu_512


def test_the_critics_verdict_is_free_and_the_measurement_it_reads_is_not(model):
    """The verdict is ~21 microseconds; the mesh measurement is ~0.28 s."""
    verdict = model.critic_verdict()
    measure = model.band("mesh.measure")
    assert 0.0 < verdict.p50.wall_seconds < 0.001
    assert measure.p50.wall_seconds > 0.1
    assert verdict.p50.wall_seconds * 100 < measure.p50.wall_seconds


def test_the_full_render_is_the_hello_rooms_1307_seconds(model):
    """docs/research/spike-phase1.md §3: the full render took 1307 s."""
    band = model.rung(3)
    assert band.p50.wall_seconds == pytest.approx(1307.0)


def test_the_fast_preview_is_seconds_not_minutes(model):
    """docs/research/warm-scene.md §4.1: the warm preview is under 10 s."""
    band = model.rung(1)
    assert band.p95.wall_seconds < 10.0


# -- the model reproduces the night that actually ran -------------------------


def test_the_model_prices_the_mini_night_the_mini_night_cost(model):
    """Three props, three seeds each: what the model says against what ran.

    The mini-night's own ledger records 9.156 GPU-minutes and 24.640 wall
    minutes (docs/lab/mini-night.md). The model is asked for the same six
    goals and has to land within a tenth.
    """
    band = model.band("prop.goal")
    gpu_minutes = band.p50.gpu_minutes * 3
    wall_minutes = band.p50.wall_minutes * 3
    assert gpu_minutes == pytest.approx(9.156, abs=1.0)
    assert wall_minutes == pytest.approx(24.640, abs=2.5)


def test_the_mini_nights_own_lane_split_is_the_one_recorded(model):
    """The recorded file says GPU 549.3 s and CPU 916.5 s for the whole night."""
    document = json.loads((DATA_DIR / "mini_night.json").read_text())
    gpu = sum(sample["gpu_seconds"] for sample in document["samples"])
    wall = sum(sample["wall_seconds"] for sample in document["samples"])
    assert gpu == pytest.approx(549.343, abs=0.01)
    assert wall == pytest.approx(1478.387, abs=0.01)
    assert wall - gpu > 0, "the CPU lane (the mesh tail) is most of the night"


# -- the joules come from the measured rails ---------------------------------


def test_the_joules_come_from_the_boards_measured_vin_rail(model):
    """docs/lab/exp-engines.md §4.4: the whole-box VIN rail drew 47.5 W."""
    rails = model.data.rails
    assert rails.vin_w == pytest.approx(47.5)
    assert rails.vdd_gpu_w == pytest.approx(20.85)
    assert rails.vdd_cpu_soc_mss_w == pytest.approx(8.27)
    band = model.band("rung.3")
    # 1307 s at 47.5 W is 62 kJ drawn by the whole box
    assert band.p50.joules == pytest.approx(47.5 * 1307.0 / 1000.0)
    # and the reading above the box's idle floor is that minus 26.5 W
    assert band.p50.joules_above_idle == pytest.approx(
        (47.5 - 26.5) * 1307.0 / 1000.0
    )


def test_the_joules_are_never_a_zero_pretending_to_be_a_measurement(model):
    for kind in model.kinds():
        band = model.band(kind)
        assert band.p50.joules > 0.0, kind
        assert band.p50.joules_above_idle is not None, kind


def test_the_marginal_cost_of_one_more_iteration_is_the_measured_one(model):
    """docs/lab/exp-joules-per-fixed-point.md: 1.39 J per iteration."""
    assert model.joules_per_iteration() == pytest.approx(1.392)


# -- the admission check ------------------------------------------------------


def _plan(*asks: tuple[str, float, float], **kwargs) -> NightPlan:
    jobs = []
    for job_id, gpu, wall in asks:
        jobs.append(
            PlannedJob(
                id=job_id,
                intention=f"do {job_id}",
                ask=Rail(gpu_minutes=gpu, hosted_cents=0, wall_minutes=wall),
                **kwargs,
            )
        )
    return NightPlan(jobs=jobs)


def test_a_plan_that_fits_is_admitted_in_full():
    plan = _plan(("a", 10.0, 20.0), ("b", 10.0, 20.0))
    check = admission_check(plan, Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=100.0))
    assert check.fits
    assert check.admitted == ["a", "b"]
    assert check.cut == []
    assert check.projected.gpu_minutes == pytest.approx(20.0)


def test_a_plan_that_does_not_fit_names_what_is_cut():
    plan = _plan(("a", 10.0, 20.0), ("b", 200.0, 20.0), ("c", 10.0, 20.0))
    check = admission_check(plan, Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=100.0))
    assert not check.fits
    assert check.cut_names == ["do b", "do c"]
    assert "does not fit" in check.cut[0].reason
    assert "do b" in check.cut[0].reason


def test_a_job_past_the_load_cap_is_parked_not_cut():
    plan = NightPlan(
        jobs=[
            PlannedJob(id="a", intention="do a", ask=Rail(gpu_minutes=1.0), model="trellis2"),
            PlannedJob(id="b", intention="do b", ask=Rail(gpu_minutes=1.0), model="trellis2"),
        ]
    )
    check = admission_check(
        plan,
        Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=100.0),
        load_budget=LoadBudget({"trellis2": 1}),
    )
    assert check.fits, "a parked job is not a cut job"
    assert check.parked_names == ["do b"]
    assert check.admitted == ["a"]


def test_the_admission_check_agrees_with_the_nights_own_rails():
    """The runner admits a job at a time; the check does the same arithmetic."""
    rails = Rail(gpu_minutes=10.0, hosted_cents=0, wall_minutes=60.0)
    plan = _plan(("a", 6.0, 10.0), ("b", 6.0, 10.0))
    check = admission_check(plan, rails)
    assert check.admitted == ["a"]
    assert check.remaining.gpu_minutes == pytest.approx(4.0)


# -- the owner's two lines ----------------------------------------------------


def test_the_owner_estimate_is_two_lines_and_says_what_it_costs(model):
    plan = _plan(("a", 30.0, 45.0), ("b", 25.0, 40.0))
    estimate = owner_estimate(plan, Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0))
    assert len(estimate.lines()) == 2
    assert "GPU-h" in estimate.line_one
    assert "wall-h" in estimate.line_one
    assert "hosted" in estimate.line_one
    assert "kJ" in estimate.line_one
    assert estimate.fits


def test_line_ones_kJ_is_the_rails_arithmetic_not_a_thousandth_of_it(model):
    """The honest-week run caught line one printing "0.0 kJ" for a plan
    whose wall time draws 14 kJ on the measured VIN rail — the field holds
    kilojoules and the line divided by 1000 a second time."""
    plan = _plan(("a", 30.0, 45.0))  # 45 wall-min
    estimate = owner_estimate(plan, Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0))
    vin_w = model.data.rails.vin_w
    expected_kj = vin_w * 45.0 * 60.0 / 1000.0
    assert estimate.joules == pytest.approx(expected_kj)
    assert f"{expected_kj:.1f} kJ" in estimate.line_one, estimate.line_one


def test_the_owner_estimate_names_the_cut_when_the_plan_does_not_fit(model):
    plan = _plan(("a", 10.0, 20.0), ("b", 400.0, 20.0))
    estimate = owner_estimate(plan, Rail(gpu_minutes=100.0, hosted_cents=0, wall_minutes=560.0))
    assert not estimate.fits
    assert "does not fit" in estimate.line_two
    assert "do b" in estimate.line_two


def test_the_owner_estimate_uses_the_measured_ask_for_a_real_job_kind(model):
    band = model.band("prop.goal")
    plan = NightPlan(
        jobs=[
            PlannedJob(
                id="prop:crate",
                intention="prop a weathered wooden crate",
                ask=band.p50.rail(),
                kind="prop.goal",
            )
        ]
    )
    estimate = owner_estimate(plan, model.default_night_rails())
    assert estimate.ask.gpu_minutes == pytest.approx(band.p50.gpu_minutes)
    assert "prop a weathered wooden crate" not in estimate.line_two
    assert estimate.fits


def test_the_default_rails_are_the_specs_rails(model):
    rails = model.default_night_rails()
    assert rails.gpu_minutes == pytest.approx(360.0)
    assert rails.hosted_cents == 0
    assert rails.wall_minutes == pytest.approx(560.0)


# -- the recorded data loads without the internet ----------------------------


def test_the_recorded_data_loads_from_the_package(tmp_path: Path):
    """The model reads its own data — no network, no box."""
    data = load_recorded()
    assert data.job("prop.image").samples
    assert load_recorded(DATA_DIR).index == data.index
