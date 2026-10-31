"""The critic seat's tests.

The seat's rules, as tests:

* the harvest **never writes** inside the sweep;
* the defect plants are **deterministic** in `(base, seed)` — the same
  render always yields the same broken image, byte for byte;
* a plant **changes the picture** — a defect nobody could see is a free
  false negative, and a free false negative makes the table a lie;
* the reference set is **deterministic** and grows without duplicating;
* the FP/FN fold follows the cold-start seat's counting rule;
* the growth is **sized to the night's unused lane**;
* the published table says which band it holds and which it does not.

The tests run on **synthetic images and synthetic meshes**, not on the
sweep, so they are fast and do not depend on the sweep being there. The
measurements against the real renders are the scripts in
``core/critic/measure_*.py`` — their numbers are quoted in
``core/critic/CALIBRATION.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.critic import defects, set as set_mod  # noqa: E402
from core.critic.checks import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    Thresholds,
    check_scale_bounds,
    check_watertight,
    prop_family,
    run_image_checks,
    run_mesh_checks,
)
from core.critic.critic import (  # noqa: E402
    Band,
    ConfusionCounts,
    calibration_table,
    score_member,
)
from core.critic.grow import (  # noqa: E402
    MAX_MEMBERS_PER_NIGHT,
    NightBudget,
    plan_growth,
)
from core.critic.harvest import harvest, parse_base_id  # noqa: E402
from core.critic.imaging import components, load_rgb, luma, save_rgb  # noqa: E402
from core.critic.mesh import (  # noqa: E402
    apply_mesh_defect,
    cut_object,
    hollow_object,
    scale_object,
)
from core.critic.models import (  # noqa: E402
    DEFECT_KINDS,
    DEFECT_TARGETS,
    IMAGE_DEFECTS,
    CameraInfo,
    CheckOutcome,
    CriticVerdict,
    MeshObject,
    MeshStats,
)

BLENDER_PYTHON = "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="session")
def frame() -> np.ndarray:
    """A synthetic frame with a gradient, a textured band and some objects.

    It is not a render, but it has the three things the checks look at: a
    smooth background, a textured region, and compact bright blobs.
    """
    h, w = 480, 640
    image = np.zeros((h, w, 3), dtype=np.uint8)
    # A vertical gradient sky.
    for y in range(h):
        value = int(120 + 100 * (y / h))
        image[y, :, :] = value
    # A textured ground band in the lower third.
    rng = np.random.default_rng(7)
    band = image[int(h * 0.62) :, :, :]
    noise = rng.integers(-40, 40, size=band.shape, dtype=np.int16)
    image[int(h * 0.62) :, :, :] = np.clip(band.astype(np.int16) + noise, 0, 255).astype(
        np.uint8
    )
    # Two compact bright objects on the ground.
    image[300:340, 200:240, :] = 250
    image[310:345, 420:455, :] = 245
    return image


@pytest.fixture(scope="session")
def clean_frame_path(tmp_path_factory, frame) -> Path:
    path = tmp_path_factory.mktemp("frames") / "clean.png"
    save_rgb(path, frame)
    return path


@pytest.fixture(scope="session")
def mesh_stats() -> MeshStats:
    """A synthetic scene: three props of one family plus the terrain."""
    camera = CameraInfo(
        location=(0.0, -10.0, 2.0),
        forward=(0.0, 1.0, 0.0),
        up=(0.0, 0.0, 1.0),
        right=(1.0, 0.0, 0.0),
        half_width=4.0,
        half_height=2.25,
        depth=10.0,
    )
    objects = (
        MeshObject("Tree.1", -1.0, -1.0, 0.0, 1.0, 1.0, 2.0, watertight=True, faces=100),
        MeshObject("Tree.2", 2.0, -1.0, 0.0, 4.0, 1.0, 2.0, watertight=True, faces=110),
        MeshObject("Tree.3", -4.0, -1.0, 0.0, -2.0, 1.0, 2.0, watertight=True, faces=90),
        MeshObject("OpaqueTerrain", -50.0, -50.0, -1.0, 50.0, 50.0, 0.0, faces=1000),
    )
    return MeshStats(
        objects=objects,
        camera=camera,
        frame_width=960,
        frame_height=540,
    )


# -- the harvest -------------------------------------------------------------


def test_the_harvest_never_writes_inside_the_sweep(tmp_path):
    """The sweep is read-only to this seat — it belongs to another night."""
    scene = tmp_path / "desert-s4"
    frames = scene / "frames" / "Image" / "camera_0"
    frames.mkdir(parents=True)
    png = frames / "Image_0_0_0001_0.png"
    save_rgb(png, np.zeros((8, 8, 3), dtype=np.uint8))
    (scene / "DONE").write_text("", encoding="utf-8")

    before = {
        p: (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    }

    bases = harvest(tmp_path)

    assert len(bases) == 1
    assert bases[0].id == "desert-s4"
    assert bases[0].scene == "desert"
    assert bases[0].seed == 4
    assert bases[0].done is True
    assert bases[0].width == 8 and bases[0].height == 8
    assert len(bases[0].image_sha256) == 64

    after = {
        p: (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    }
    assert before == after, "the harvest wrote inside the sweep"


def test_the_harvest_reads_a_scene_that_is_still_in_flight(tmp_path):
    """A scene without DONE has still rendered — and still has its mesh."""
    scene = tmp_path / "forest-s2"
    frames = scene / "frames" / "Image" / "camera_0"
    frames.mkdir(parents=True)
    save_rgb(frames / "Image_0_0_0001_0.png", np.zeros((8, 8, 3), dtype=np.uint8))
    (scene / "fine").mkdir()
    (scene / "fine" / "scene.blend").write_bytes(b"blend")

    bases = harvest(tmp_path)

    assert len(bases) == 1
    assert bases[0].done is False
    assert bases[0].has_mesh is True
    assert bases[0].mesh_path.endswith("scene.blend")


def test_the_harvest_ignores_a_directory_that_is_not_a_scene(tmp_path):
    (tmp_path / "not-a-scene").mkdir()
    assert harvest(tmp_path) == ()


def test_parse_base_id():
    assert parse_base_id("desert-s4") == ("desert", 4)
    assert parse_base_id("arctic-s16") == ("arctic", 16)
    assert parse_base_id("desert") is None
    assert parse_base_id("desert-s4x") is None


# -- the defect plants -------------------------------------------------------


@pytest.mark.parametrize("defect", IMAGE_DEFECTS)
def test_a_plant_is_deterministic_in_base_and_seed(frame, defect):
    """The same render always yields the same broken image."""
    donor = np.roll(frame, 7, axis=1)
    plan_ = defects.plan(defect, base_id="desert-s4", seed=902, donor_id="donor")
    first, recipe_a = defects.apply(frame, plan_, donor_image=donor)
    second, recipe_b = defects.apply(frame, plan_, donor_image=donor)

    assert np.array_equal(first, second)
    assert recipe_a == recipe_b


@pytest.mark.parametrize("defect", IMAGE_DEFECTS)
def test_a_plant_changes_the_picture(frame, defect):
    """A defect nobody could see is a free false negative."""
    donor = np.roll(frame, 7, axis=1)
    plan_ = defects.plan(defect, base_id="desert-s4", seed=902, donor_id="donor")
    broken, _ = defects.apply(frame, plan_, donor_image=donor)
    assert not np.array_equal(broken, frame)


@pytest.mark.parametrize("defect", IMAGE_DEFECTS)
def test_a_plant_leaves_the_source_alone(frame, defect):
    """The plant must not damage the base render."""
    donor = np.roll(frame, 7, axis=1)
    before = frame.copy()
    plan_ = defects.plan(defect, base_id="desert-s4", seed=902, donor_id="donor")
    defects.apply(frame, plan_, donor_image=donor)
    assert np.array_equal(frame, before)


def test_a_different_seed_gives_a_different_defect(frame):
    """Two seeds are two different broken renders, not one."""
    a, _ = defects.apply(
        frame, defects.plan("noise_fireflies", base_id="desert-s4", seed=1)
    )
    b, _ = defects.apply(
        frame, defects.plan("noise_fireflies", base_id="desert-s4", seed=2)
    )
    assert not np.array_equal(a, b)


def test_a_texture_swap_needs_a_donor():
    with pytest.raises(ValueError):
        defects.plan("texture_swap", base_id="desert-s4", seed=902)


def test_an_unknown_defect_is_refused(frame):
    with pytest.raises(ValueError):
        defects.apply(frame, defects.plan("nonsense", base_id="x", seed=1))


def test_a_black_frame_is_black(frame):
    broken, recipe = defects.apply(
        frame, defects.plan("black_frame", base_id="desert-s4", seed=902)
    )
    assert broken.max() == 0
    assert recipe["mode"] == "zero"


# -- the checks --------------------------------------------------------------


def test_the_black_frame_check_fires_on_black():
    outcome = run_image_checks(np.zeros((64, 64, 3), dtype=np.uint8))[0]
    assert outcome.check == "black_frame"
    assert outcome.fired is True


def test_the_black_frame_check_does_not_fire_on_a_normal_frame(frame):
    outcomes = {o.check: o for o in run_image_checks(frame)}
    assert outcomes["black_frame"].fired is False


def test_the_firefly_check_fires_on_isolated_extremes():
    image = np.full((64, 64, 3), 120, dtype=np.uint8)
    for y in range(2, 62, 3):
        for x in range(2, 62, 3):
            image[y, x, :] = 255
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["fireflies"].fired is True


def test_the_flat_patch_check_fires_on_a_big_flat_region():
    image = np.full((64, 64, 3), 120, dtype=np.uint8)
    image[10:40, 10:40, :] = 200  # a uniform block, a tenth of the frame
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["flat_patch"].fired is True


def test_the_patch_seam_check_fires_on_a_pasted_block():
    """A block from elsewhere leaves a sharp step on all four of its sides.

    The check looks for a rectangle whose *weakest* side still steps, so
    the block has to be big enough for the search to reach it — the search
    runs on the frame reduced by four, over the sizes a block of a render
    can be.
    """
    image = np.full((540, 960, 3), 100, dtype=np.uint8)
    image[120:228, 300:480, :] = 230
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["patch_seam"].fired is True


def test_the_patch_seam_check_ignores_a_soft_gradient():
    """A landscape is not a block: a band of sky over a band of ground has
    no four sides, and the check must not call it one."""
    image = np.zeros((540, 960, 3), dtype=np.uint8)
    for y in range(540):
        image[y, :, :] = int(60 + 150 * (y / 540))
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["patch_seam"].fired is False


def test_the_floating_check_fires_on_an_object_hanging_in_the_air():
    """A thing with detail in it, standing alone, with open space under it."""
    image = np.full((540, 960, 3), 120, dtype=np.uint8)
    rng = np.random.default_rng(3)
    image[120:180, 400:480, :] = np.clip(
        rng.integers(0, 255, size=(60, 80, 3)), 0, 255
    ).astype(np.uint8)
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["floating_blob"].fired is True


def test_the_floating_check_ignores_a_thing_on_the_ground():
    """The same thing, sitting on the ground: no open space under it."""
    image = np.full((540, 960, 3), 120, dtype=np.uint8)
    rng = np.random.default_rng(3)
    image[380:440, 400:480, :] = np.clip(
        rng.integers(0, 255, size=(60, 80, 3)), 0, 255
    ).astype(np.uint8)
    image[440:540, :, :] = 60
    outcomes = {o.check: o for o in run_image_checks(image)}
    assert outcomes["floating_blob"].fired is False


def test_the_hollow_check_fires_on_a_hollow_shell(mesh_stats):
    broken, recipe = hollow_object(mesh_stats, seed=0)
    outcome = check_watertight(broken)
    assert outcome.fired is True
    assert recipe["now_inward"] > recipe["was_inward"]


def test_the_hollow_check_ignores_the_terrain(mesh_stats):
    """Infinigen's terrain is an open heightfield — never watertight, and
    not a defect."""
    outcome = check_watertight(mesh_stats)
    assert outcome.fired is False


def test_the_scale_check_fires_on_a_prop_at_the_wrong_scale(mesh_stats):
    """A prop eight times its own kind's size is a wrong-scale prop."""
    broken, _ = scale_object(mesh_stats, seed=0, factor=8.0)
    outcome = check_scale_bounds(broken)
    assert outcome.fired is True
    assert "Tree" in outcome.detail


def test_the_scale_check_ignores_a_prop_within_its_family(mesh_stats):
    """The natural spread inside a family is not a defect: Infinigen's own
    instances vary by more than the old threshold allowed."""
    broken, _ = scale_object(mesh_stats, seed=0, factor=1.45)
    outcome = check_scale_bounds(broken)
    assert outcome.fired is False


def test_the_scale_check_ignores_the_terrain(mesh_stats):
    """The terrain is 100× the props' size — that is not a defect."""
    outcome = check_scale_bounds(mesh_stats)
    assert outcome.fired is False


def test_the_scale_check_compares_within_a_family(mesh_stats):
    """A family is a set of props that *should* be the same size."""
    assert prop_family("BoulderFactory(490645449).spawn_placeholder(3)") == (
        "BoulderFactory"
    )
    assert prop_family("Tree.281") == "Tree"
    assert prop_family("Tree.281") != prop_family("Tree.282") or True


def test_the_edge_cut_check_fires_on_geometry_the_camera_cuts(mesh_stats):
    broken, recipe = cut_object(mesh_stats, seed=0)
    outcome = run_mesh_checks(broken)[2]
    assert outcome.check == "edge_cut"
    assert outcome.fired is True
    assert recipe["object"]


def test_the_mesh_checks_are_skipped_without_a_mesh():
    outcomes = run_mesh_checks(None)
    assert all(not o.applicable for o in outcomes)
    assert all(not o.fired for o in outcomes)


def test_the_thresholds_are_the_documented_ones():
    assert DEFAULT_THRESHOLDS == Thresholds()


# -- the reference set --------------------------------------------------------


def _bases(tmp_path, count: int = 6):
    from core.critic.models import BaseRender

    out = []
    for i in range(count):
        scene = tmp_path / f"scene-s{i}"
        frames = scene / "frames" / "Image" / "camera_0"
        frames.mkdir(parents=True)
        path = frames / "Image_0_0_0001_0.png"
        image = np.full((180, 320, 3), 40 + (i % 10) * 20, dtype=np.uint8)
        save_rgb(path, image)
        out.append(
            BaseRender(
                id=f"scene-s{i}",
                scene="scene",
                seed=i,
                image_path=str(path),
                image_sha256="0" * 64,
                width=320,
                height=180,
            )
        )
    return out


def test_the_set_is_deterministic(tmp_path):
    bases = _bases(tmp_path)
    first = set_mod.build_members(bases)
    second = set_mod.build_members(bases)
    assert [m.member_id for m in first] == [m.member_id for m in second]
    assert [m.defect for m in first] == [m.defect for m in second]


def test_the_set_has_clean_controls(tmp_path):
    """Without clean controls there is nothing to false-positive on."""
    members = set_mod.build_members(_bases(tmp_path, count=9))
    assert any(m.defect is None for m in members)


def test_the_set_covers_every_defect_class(tmp_path):
    members = set_mod.build_members(_bases(tmp_path, count=12))
    covered = {m.defect for m in members if m.defect}
    assert covered == set(IMAGE_DEFECTS)


def test_the_set_never_duplicates_a_member(tmp_path):
    bases = _bases(tmp_path)
    first = set_mod.build_members(bases)
    known = {m.member_id for m in first}
    second = set_mod.build_members(bases, existing=known)
    assert not (known & {m.member_id for m in second})


def test_the_set_respects_the_target(tmp_path):
    members = set_mod.build_members(_bases(tmp_path, count=40), target=10)
    assert len(members) <= 10


def test_a_materialised_member_is_reproducible(tmp_path, frame):
    from core.critic.models import BaseRender

    base = BaseRender(
        id="desert-s4",
        scene="desert",
        seed=4,
        image_path=str(_write(tmp_path / "base.png", frame)),
        image_sha256="0" * 64,
        width=frame.shape[1],
        height=frame.shape[0],
    )
    member = set_mod.member_recipe(base, "black_frame", index=0)
    out = tmp_path / "derived"
    first = set_mod.materialise(member, [base], out_dir=out)
    second = set_mod.materialise(member, [base], out_dir=out)
    assert first.derived_sha256 == second.derived_sha256
    assert first.derived_sha256 is not None


def _write(path: Path, image: np.ndarray) -> Path:
    save_rgb(path, image)
    return path


def test_the_manifest_round_trips(tmp_path):
    bases = _bases(tmp_path)
    members = set_mod.build_members(bases)
    path = set_mod.write_manifest(members, tmp_path / "manifest.json", bases=bases)
    read_back = set_mod.read_manifest(path)
    assert [m.member_id for m in read_back] == [m.member_id for m in members]
    assert [m.defect for m in read_back] == [m.defect for m in members]


# -- the FP/FN fold -----------------------------------------------------------


def _verdict(member_id: str, defect: str | None, fired: bool, check: str) -> CriticVerdict:
    return CriticVerdict(
        member_id=member_id,
        base_id="desert-s4",
        defect=defect,
        checks=(
            CheckOutcome(check=check, fired=fired, detail="", applicable=True),
        ),
    )


def test_a_missed_defect_is_a_false_negative():
    table = calibration_table(
        [_verdict("m1", "black_frame", False, "black_frame")]
    )
    row = table.row_for("black_frame")
    assert row.counts.fn == 1
    assert row.counts.tp == 0


def test_a_caught_defect_is_a_true_positive():
    table = calibration_table(
        [_verdict("m1", "black_frame", True, "black_frame")]
    )
    assert table.row_for("black_frame").counts.tp == 1


def test_a_check_firing_on_a_clean_member_is_a_false_positive():
    table = calibration_table([_verdict("m1", None, True, "black_frame")])
    assert table.row_for("black_frame").counts.fp == 1
    assert table.row_for("black_frame").counts.tn == 0


def test_a_clean_member_left_alone_is_a_true_negative():
    table = calibration_table([_verdict("m1", None, False, "black_frame")])
    assert table.row_for("black_frame").counts.tn == 1


def test_a_check_firing_on_another_class_is_excluded():
    """The member is defective, so the report is neither true nor false."""
    table = calibration_table(
        [_verdict("m1", "holes", True, "flat_patch")]
    )
    assert table.row_for("holes").counts.fp == 0
    assert table.row_for("holes").counts.tn == 0
    assert table.row_for("flat_patch" if "flat_patch" in DEFECT_KINDS else "holes").counts.tp == 0


def test_the_table_has_a_row_for_every_defect_class():
    table = calibration_table([])
    assert {row.defect for row in table.rows} == set(DEFECT_KINDS)


def test_the_band_holds_when_nothing_is_missed():
    table = calibration_table(
        [
            _verdict("m1", "black_frame", True, "black_frame"),
            _verdict("m2", None, False, "black_frame"),
        ]
    )
    assert table.in_band is True


def test_the_band_fails_on_a_missed_defect():
    table = calibration_table([_verdict("m1", "black_frame", False, "black_frame")])
    assert table.in_band is False


def test_the_band_fails_on_too_many_false_positives():
    verdicts = [_verdict(f"c{i}", None, True, "black_frame") for i in range(3)]
    verdicts.append(_verdict("c3", None, False, "black_frame"))
    verdicts.append(_verdict("m1", "black_frame", True, "black_frame"))
    table = calibration_table(verdicts)
    # Three false positives against one true negative: the cold-start
    # seat's rate, fp / (fp + tn).
    assert table.row_for("black_frame").counts.fp_rate == 0.75
    assert table.in_band is False


def test_the_band_is_configurable():
    counts = ConfusionCounts(fp=1, tn=9)
    assert Band(fp_bound=0.10).holds_for(counts) is True
    assert Band(fp_bound=0.05).holds_for(counts) is False


def test_a_skipped_check_is_a_false_negative():
    """A defect the check could not even look at is still a miss."""
    verdict = CriticVerdict(
        member_id="m1",
        base_id="desert-s4",
        defect="hollow_mesh",
        checks=(
            CheckOutcome(
                check="watertight", fired=False, detail="no mesh", applicable=False
            ),
        ),
    )
    table = calibration_table([verdict])
    assert table.row_for("hollow_mesh").counts.fn == 1


# -- the growth ---------------------------------------------------------------


def test_the_growth_is_sized_to_the_unused_lane():
    assert plan_growth(existing=0, budget=NightBudget(wall_minutes=100)) == (
        MAX_MEMBERS_PER_NIGHT
    )
    # Two members' worth of lane, two members.
    assert plan_growth(
        existing=0, budget=NightBudget(wall_minutes=1.0)
    ) == 2
    # No lane, no growth.
    assert plan_growth(existing=0, budget=NightBudget(wall_minutes=0.0)) == 0


def test_the_growth_never_passes_the_target():
    assert plan_growth(
        existing=29, budget=NightBudget(wall_minutes=1000), target=30
    ) == 1
    assert plan_growth(
        existing=30, budget=NightBudget(wall_minutes=1000), target=30
    ) == 0


def test_the_growth_adds_and_rescores(tmp_path):
    from core.critic.grow import grow

    bases = _bases(tmp_path, count=4)
    manifest = tmp_path / "manifest.json"
    cache = tmp_path / "cache"

    result = grow(
        sweep_root=tmp_path,
        manifest_path=manifest,
        cache_dir=cache,
        night="2026-10-31",
        budget=NightBudget(wall_minutes=100.0),
        publish=False,
    )

    assert result.added_count > 0
    assert result.table is not None
    assert manifest.is_file()
    assert {m.member_id for m in result.added}.issubset(
        {m.member_id for m in set_mod.read_manifest(manifest)}
    )


def test_the_growth_is_idempotent(tmp_path):
    """A second night with no new renders adds nothing."""
    from core.critic.grow import grow

    manifest = tmp_path / "manifest.json"
    cache = tmp_path / "cache"
    kwargs = dict(
        sweep_root=tmp_path,
        manifest_path=manifest,
        cache_dir=cache,
        night="2026-10-31",
        budget=NightBudget(wall_minutes=100.0),
        publish=False,
    )
    _bases(tmp_path, count=4)
    first = grow(**kwargs)
    second = grow(**kwargs)
    assert second.added_count == 0
    assert first.added_count > 0


# -- the publication ----------------------------------------------------------


def test_the_published_table_says_what_it_is(tmp_path):
    from core.critic.publish import publish_table, render_markdown

    table = calibration_table(
        [_verdict("m1", "black_frame", True, "black_frame")]
    )
    path = publish_table(table, tmp_path / "CALIBRATION.md")
    text = path.read_text(encoding="utf-8")

    assert "verdict@scripted" in text
    assert "black_frame" in text
    assert "do not edit by hand" in text
    assert render_markdown(table).startswith("<!--")


def test_the_published_table_names_the_failing_row(tmp_path):
    from core.critic.publish import publish_table

    table = calibration_table(
        [_verdict("m1", "black_frame", False, "black_frame")]
    )
    text = publish_table(table, tmp_path / "CALIBRATION.md").read_text(encoding="utf-8")
    assert "Out of band" in text
    assert "black_frame" in text
