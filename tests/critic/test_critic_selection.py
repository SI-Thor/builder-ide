"""The critic selection's tests.

The selection's rules, as tests:

* the critic is a **parameter with a default** — the scripted critic in
  ``core/critic``, which is also the **fallback** whenever the chosen critic
  cannot be built;
* an unknown name, or a candidate whose dependencies are not on this box,
  falls back to the scripted critic **with the reason** — never to a
  different critic quietly;
* the **hybrid** keeps the scripted checks on the classes they hold and
  hands only the out-of-band class to the model, and the verdict says which
  critic answered;
* a critic that cannot see a layer is **not charged with misses** on it:
  the fold leaves those members out and the table says which layers it
  covered;
* the chosen critic sits behind the core's ``Critic`` seam, and a frame it
  could not judge scores zero and says so.

The tests run on **synthetic images**, not on the sweep: fast, and they do
not depend on the sweep being there.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.critic.critic import (  # noqa: E402
    CriticRunner,
    ScriptedReferenceCritic,
    calibration_table,
)
from core.critic.grow import ensure_derived  # noqa: E402
from core.critic.hybrid import HybridCritic  # noqa: E402
from core.critic.imaging import save_rgb  # noqa: E402
from core.critic.models import (  # noqa: E402
    CheckOutcome,
    CriticVerdict,
)
from core.critic.select import (  # noqa: E402
    CRITIC_DEFAULT,
    SCRIPTED_OUT_OF_BAND,
    CriticUnavailable,
    FallbackCritic,
    build_critic,
    candidate_names,
    configured_critic,
    configured_name,
    resolve_critic,
)
from core.critic.service import RenderCritic, build_render_critic  # noqa: E402
from core.critic.set import MemberRecipe  # noqa: E402


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="session")
def frame() -> np.ndarray:
    """A synthetic frame with a gradient and some texture."""
    h, w = 240, 320
    image = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        image[y, :, :] = int(90 + 120 * (y / h))
    rng = np.random.default_rng(11)
    band = image[int(h * 0.6) :, :, :]
    noise = rng.integers(-30, 30, size=band.shape, dtype=np.int16)
    image[int(h * 0.6) :, :, :] = np.clip(
        band.astype(np.int16) + noise, 0, 255
    ).astype(np.uint8)
    image[120:150, 100:130, :] = 250
    return image


@pytest.fixture(scope="session")
def frame_path(tmp_path_factory, frame) -> Path:
    path = tmp_path_factory.mktemp("frames") / "frame.png"
    save_rgb(path, frame)
    return path


@pytest.fixture(scope="session")
def clean_frame() -> np.ndarray:
    """A frame with nothing wrong with it: a smooth sky over a smooth ground.

    No flat patch big enough to be a missing object, no dark hole, no
    speckle — so the scripted checks leave it alone, which is what a clean
    control has to be.
    """
    h, w = 540, 960
    image = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        value = int(60 + 180 * (y / h))
        image[y, :, :] = value
    return image


@pytest.fixture(scope="session")
def clean_frame_path(tmp_path_factory, clean_frame) -> Path:
    path = tmp_path_factory.mktemp("clean") / "clean.png"
    save_rgb(path, clean_frame)
    return path


_IMAGE_CHECKS = (
    "black_frame",
    "fireflies",
    "flat_patch",
    "dark_holes",
    "patch_seam",
    "floating_blob",
)


class _FakeScripted:
    """The scripted checks, stubbed: quiet on everything but what it is told."""

    name = "scripted-fake"
    layers = ("image", "mesh")

    def __init__(self, fired_for: tuple[str, ...] = ()) -> None:
        self.fired_for = fired_for
        self.asked: list[str] = []

    def score(
        self,
        member: MemberRecipe,
        *,
        bases=(),
        thresholds=None,
        cache_dir=None,
        blender_python=None,
    ) -> CriticVerdict:
        self.asked.append(member.member_id)
        checks = tuple(
            CheckOutcome(
                check=check,
                fired=check in self.fired_for,
                detail=f"the checks say {check}",
                applicable=True,
            )
            for check in _IMAGE_CHECKS
        )
        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=checks,
            label="verdict@scripted-fake",
            degraded="scripted",
            layer=member.layer,
        )


class _FakeDelegate:
    """A model that answers with the checks it was told to answer."""

    name = "fake-model"
    layers = ("image",)

    def __init__(self, fired_for: tuple[str, ...] = ()) -> None:
        self.fired_for = fired_for
        self.asked: list[str] = []

    def score(
        self,
        member: MemberRecipe,
        *,
        bases=(),
        thresholds=None,
        cache_dir=None,
        blender_python=None,
    ) -> CriticVerdict:
        self.asked.append(member.member_id)
        checks = tuple(
            CheckOutcome(
                check=check,
                fired=check in self.fired_for,
                detail=f"the fake model says {check}",
                applicable=True,
            )
            for check in _IMAGE_CHECKS
        )
        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=checks,
            label=f"verdict@{self.name}",
            degraded=self.name,
            layer=member.layer,
        )


class _UnreachableDelegate:
    """A model that cannot be reached — no server, no weights, no GPU."""

    name = "unreachable-model"
    layers = ("image",)

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or OSError("connection refused")

    def score(
        self,
        member: MemberRecipe,
        *,
        bases=(),
        thresholds=None,
        cache_dir=None,
        blender_python=None,
    ) -> CriticVerdict:
        raise self.error


def _member(
    member_id: str = "m1",
    defect: str | None = "floating_object",
    layer: str = "image",
    derived_path: str | None = None,
) -> MemberRecipe:
    return MemberRecipe(
        member_id=member_id,
        base_id="desert-s4",
        defect=defect,
        layer=layer,
        seed=902,
        recipe={"kind": layer},
        derived_path=derived_path,
    )


# -- the parameter and the fallback -------------------------------------------


def test_the_default_critic_is_the_scripted_one():
    """The default needs no model, no GPU and no network."""
    assert CRITIC_DEFAULT == "scripted"
    critic, reason = resolve_critic()
    assert critic.name == "scripted"
    assert reason is None


def test_the_registry_names_the_candidates():
    names = candidate_names()
    assert "scripted" in names
    assert "hybrid" in names
    assert len(set(names)) == len(names)


def test_an_unknown_critic_falls_back_to_the_scripted_one():
    critic, reason = resolve_critic("no-such-critic")
    assert critic.name == "scripted"
    assert reason is not None
    assert "no-such-critic" in reason


def test_a_critic_that_cannot_be_built_falls_back(monkeypatch):
    """A model that is not on the box is not a crash: the checks answer."""
    import core.critic.candidates.vlm as vlm_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("no weights on this box")

    monkeypatch.setattr(vlm_mod, "VLMCritic", _boom)

    critic, reason = resolve_critic("vlm")
    assert critic.name == "scripted"
    assert reason is not None
    assert "vlm" in reason


def test_a_critic_that_cannot_answer_falls_back_to_the_checks(frame_path):
    """The second kind of failure: the candidate is built and then cannot answer.

    A model server that is not resident, a key that has expired, weights
    that have gone missing — the night still gets a table, and the verdict
    says which critic actually made it.
    """
    fallback = FallbackCritic(_UnreachableDelegate())
    verdict = fallback.score(
        _member(defect="black_frame", derived_path=str(frame_path))
    )
    assert verdict.degraded == "scripted"
    assert verdict.label == "verdict@unreachable-model"
    assert any("could not answer" in c.detail for c in verdict.checks)


def test_the_fallback_keeps_the_chosen_critic_s_layers():
    """The fold measures the chosen critic on the layers it can see."""
    fallback = FallbackCritic(_UnreachableDelegate())
    assert fallback.name == "unreachable-model"
    assert fallback.layers == ("image",)


def test_building_an_unknown_critic_raises():
    with pytest.raises(CriticUnavailable):
        build_critic("no-such-critic")


def test_the_scripted_critic_sees_both_layers():
    assert ScriptedReferenceCritic().layers == ("image", "mesh")


# -- the configured critic ----------------------------------------------------


def test_the_configured_critic_is_the_default_when_nothing_is_configured():
    assert configured_name() == CRITIC_DEFAULT


def test_the_configured_critic_comes_from_the_settings(monkeypatch):
    """The settings carry the name, so the night and the re-score agree."""
    monkeypatch.delenv("BUILDER_CRITIC", raising=False)

    class _Settings:
        critic = "hybrid"

    assert configured_name(_Settings()) == "hybrid"


def test_the_configured_critic_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("BUILDER_CRITIC", "vlm")
    assert configured_name() == "vlm"


def test_the_configured_critic_falls_back_to_the_checks(monkeypatch):
    """A critic that cannot be built is not a crash: the checks answer."""
    monkeypatch.setenv("BUILDER_CRITIC", "no-such-critic")
    critic, reason = configured_critic()
    assert critic.name == "scripted"
    assert reason is not None


def test_the_core_seam_is_built_from_the_configured_critic(monkeypatch):
    """One call puts the chosen critic behind the core's ``Critic`` seam."""
    monkeypatch.setenv("BUILDER_CRITIC", "scripted")
    critic, reason = build_render_critic(render_of=lambda task, variant: None)
    assert reason is None
    assert critic.critic.name == "scripted"


def test_the_core_seam_falls_back_and_says_why(monkeypatch):
    monkeypatch.setenv("BUILDER_CRITIC", "no-such-critic")
    critic, reason = build_render_critic(render_of=lambda task, variant: None)
    assert critic.critic.name == "scripted"
    assert reason is not None
    assert "no-such-critic" in reason


def test_the_nightly_growth_scores_with_the_chosen_critic(tmp_path):
    """``grow`` re-scores with the critic it is given, not always the checks."""
    from core.critic.grow import NightBudget, grow

    _sweep(tmp_path, count=4)
    result = grow(
        sweep_root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        cache_dir=tmp_path / "cache",
        budget=NightBudget(wall_minutes=100.0),
        publish=False,
        critic=ScriptedReferenceCritic(),
    )
    assert result.critic == "scripted"
    assert result.verdicts
    assert all(v.label == "verdict@scripted" for v in result.verdicts)


def _sweep(tmp_path, count: int = 4):
    """A sweep's worth of renders for the growth to harvest."""
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


# -- the fold and the layers -------------------------------------------------


def test_a_critic_that_cannot_see_a_layer_is_not_charged_with_misses():
    """A pixel critic is measured on the image layer only.

    The mesh members are left out of the fold entirely — not counted as
    misses, and not counted as clean controls. A defect nobody could look at
    is not a miss, and the table must not pretend it was measured.
    """
    verdicts = [
        CriticVerdict(
            member_id="m1",
            base_id="b1",
            defect="black_frame",
            checks=(CheckOutcome(check="black_frame", fired=True, detail=""),),
            layer="image",
        ),
        CriticVerdict(
            member_id="m2",
            base_id="b2",
            defect="wrong_scale",
            checks=(CheckOutcome(check="scale_bounds", fired=True, detail=""),),
            layer="mesh",
        ),
    ]
    table = calibration_table(verdicts, layers=("image",))
    assert table.row_for("black_frame").counts.tp == 1
    assert table.row_for("wrong_scale").counts.fn == 0
    assert table.row_for("wrong_scale").members == 0
    assert table.layers == ("image",)


def test_the_scripted_critic_is_measured_on_the_whole_set():
    verdicts = [
        CriticVerdict(
            member_id="m1",
            base_id="b1",
            defect="wrong_scale",
            checks=(CheckOutcome(check="scale_bounds", fired=True, detail=""),),
            layer="mesh",
        )
    ]
    table = calibration_table(verdicts, layers=("image", "mesh"))
    assert table.row_for("wrong_scale").counts.tp == 1


# -- the hybrid ---------------------------------------------------------------


def test_the_hybrid_keeps_the_checks_on_the_classes_they_hold(frame_path):
    """Only the out-of-band class goes to the model."""
    delegate = _FakeDelegate(fired_for=("floating_blob",))
    checks = _FakeScripted(fired_for=("black_frame",))
    hybrid = HybridCritic(delegate, escalate=("floating_object",), scripted=checks)
    verdict = hybrid.score(_member(derived_path=str(frame_path)))
    by_check = {o.check: o for o in verdict.checks}
    assert by_check["floating_blob"].fired is True
    assert "the fake model" in by_check["floating_blob"].detail
    assert by_check["black_frame"].fired is True
    assert "the checks" in by_check["black_frame"].detail
    assert verdict.label == "verdict@hybrid"


def test_the_hybrid_does_not_ask_the_model_about_a_mesh_member():
    """A mesh member is judged by the checks; the model has no picture."""
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    hybrid.score(_member(defect="wrong_scale", layer="mesh"))
    assert delegate.asked == []


def test_the_hybrid_asks_the_model_about_a_clean_control():
    """A clean control's false positives are counted over every check."""
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    hybrid.score(_member(defect=None))
    assert delegate.asked == ["m1"]


def test_the_hybrid_does_not_ask_the_model_when_the_checks_can_answer():
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    hybrid.score(_member(defect="black_frame"))
    assert delegate.asked == []


def test_the_out_of_band_class_is_the_one_the_table_names():
    assert "floating_object" in SCRIPTED_OUT_OF_BAND


# -- the hybrid's verdict says who answered -----------------------------------


def test_the_hybrid_s_verdict_names_the_hybrid_when_the_model_answered():
    """The model answered the escalated class: the hybrid made this verdict."""
    delegate = _FakeDelegate(fired_for=("floating_blob",))
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    verdict = hybrid.score(_member(defect="floating_object"))
    assert verdict.label == "verdict@hybrid"
    assert verdict.degraded == "hybrid"


def test_the_hybrid_s_verdict_says_the_checks_stood_in_when_the_model_cannot():
    """The delegate could not judge the escalated class: that is a fallback."""
    delegate = _FakeDelegate()
    delegate.layers = ()  # a model that cannot see this layer
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    verdict = hybrid.score(_member(defect="floating_object"))
    assert verdict.degraded == "scripted"


def test_the_hybrid_s_verdict_is_not_a_fallback_when_the_checks_answer_by_design():
    """A class the checks hold needs no model, so nothing fell back."""
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    verdict = hybrid.score(_member(defect="black_frame"))
    assert delegate.asked == []
    assert verdict.degraded == "hybrid"


def test_the_hybrid_falls_back_to_the_checks_when_the_model_cannot_be_reached():
    """No server, no weights, no GPU: the checks answer, and the verdict says so.

    This is the failure a night actually hits — the model server is not
    resident — and it must not take the night's table with it.
    """
    delegate = _UnreachableDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    verdict = hybrid.score(_member(defect="floating_object"))
    assert verdict.degraded == "scripted"
    assert verdict.label == "verdict@hybrid"
    assert any("could not be reached" in c.detail for c in verdict.checks)
    # the checks' own answer stands: the scripted outcome is still there
    by_check = {c.check: c for c in verdict.checks}
    assert by_check["floating_blob"].fired is False


def test_the_hybrid_s_verdict_keeps_the_member_s_layer():
    """A mesh member stays a mesh member: the layer says where the defect lives."""
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    verdict = hybrid.score(_member(defect="wrong_scale", layer="mesh"))
    assert verdict.layer == "mesh"


# -- the runner ---------------------------------------------------------------


def test_the_runner_scores_with_the_critic_it_was_given(frame_path):
    delegate = _FakeDelegate(fired_for=("floating_blob",))
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    runner = CriticRunner(critic=hybrid)
    verdict = runner.score(_member(derived_path=str(frame_path)))
    assert verdict.label == "verdict@hybrid"
    assert runner.critic is hybrid


def test_the_runner_folds_the_table_over_the_layers_the_critic_sees(frame_path):
    """The hybrid sees both layers, so both layers are in its table."""
    delegate = _FakeDelegate()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    runner = CriticRunner(critic=hybrid)
    runner.score(_member(derived_path=str(frame_path)))
    runner.score(_member(member_id="m2", defect="wrong_scale", layer="mesh"))
    table = runner.table()
    assert table.layers == ("image", "mesh")
    assert table.row_for("wrong_scale").members == 1
    assert table.row_for("floating_object").members == 1


def test_a_pixel_critic_s_table_leaves_the_mesh_rows_empty(frame_path):
    """The same fold, a critic that cannot see the geometry."""
    delegate = _FakeDelegate()
    runner = CriticRunner(critic=delegate)
    runner.score(_member(derived_path=str(frame_path)))
    runner.score(_member(member_id="m2", defect="wrong_scale", layer="mesh"))
    table = runner.table()
    assert table.layers == ("image",)
    assert table.row_for("wrong_scale").members == 0
    assert table.row_for("wrong_scale").counts.fn == 0


# -- the night seam -----------------------------------------------------------


def test_the_render_critic_scores_a_clean_frame_one(clean_frame_path):
    """A frame the checks find nothing wrong with scores one."""
    critic = RenderCritic(
        ScriptedReferenceCritic(),
        render_of=lambda task, variant: str(clean_frame_path),
    )
    score = critic.score(_task(), _variant())
    assert score.score == 1.0
    assert score.degraded is False
    assert "scripted" in score.reason


def test_the_render_critic_scores_a_frame_with_a_defect_below_one(frame_path):
    """A frame with a defect found scores less than a clean one."""
    from core.critic.candidates.vlm import VLM_CLASSES  # noqa: F401

    def _render(task, variant):
        return str(frame_path)

    critic = RenderCritic(_BlackFrameCritic(), render_of=_render)
    score = critic.score(_task(), _variant())
    assert score.score < 1.0
    assert "black_frame" in score.reason


def test_the_render_critic_scores_zero_when_there_is_no_frame():
    critic = RenderCritic(
        ScriptedReferenceCritic(), render_of=lambda task, variant: None
    )
    score = critic.score(_task(), _variant())
    assert score.score == 0.0
    assert score.degraded is True


def test_the_render_critic_falls_back_to_the_scripted_checks():
    """The chosen critic cannot be built: the checks answer, and say so."""
    critic, reason = resolve_critic("no-such-critic")
    assert critic.name == "scripted"
    assert reason


def test_the_render_critic_is_not_degraded_when_the_hybrid_answered(frame_path):
    """The hybrid's model answered the escalated class: a full verdict."""
    delegate = _FakeDelegate(fired_for=("floating_blob",))
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    critic = RenderCritic(
        hybrid,
        render_of=lambda task, variant: str(frame_path),
    )
    score = critic.score(_task(), _variant())
    assert score.degraded is False


def test_the_render_critic_is_degraded_when_the_hybrid_fell_back(frame_path):
    """The hybrid needed its model and could not have it: the checks stood in."""
    delegate = _FakeDelegate()
    delegate.layers = ()
    hybrid = HybridCritic(
        delegate, escalate=("floating_object",), scripted=_FakeScripted()
    )
    critic = RenderCritic(
        hybrid,
        render_of=lambda task, variant: str(frame_path),
    )
    score = critic.score(_task(), _variant())
    assert score.degraded is True


def test_the_render_critic_is_degraded_when_the_model_cannot_be_reached(frame_path):
    """The model server is not resident: the checks answer, and the score says so."""
    hybrid = HybridCritic(
        _UnreachableDelegate(),
        escalate=("floating_object",),
        scripted=_FakeScripted(),
    )
    critic = RenderCritic(
        hybrid,
        render_of=lambda task, variant: str(frame_path),
    )
    score = critic.score(_task(), _variant())
    assert score.degraded is True
    assert "hybrid" in score.reason


# -- the re-derivation --------------------------------------------------------


def test_a_missing_derived_image_is_re_derived_from_its_recipe(tmp_path, frame):
    """The derived image is a cache: the recipe is the truth."""
    from core.critic.models import BaseRender

    base_path = tmp_path / "base.png"
    save_rgb(base_path, frame)
    base = BaseRender(
        id="desert-s4",
        scene="desert",
        seed=4,
        image_path=str(base_path),
        image_sha256="0" * 64,
        width=frame.shape[1],
        height=frame.shape[0],
    )
    member = MemberRecipe(
        member_id="m1",
        base_id="desert-s4",
        defect="black_frame",
        layer="image",
        seed=902,
        recipe={"kind": "image", "mode": "zero"},
        derived_path=None,
    )
    rebuilt = ensure_derived([member], [base], tmp_path / "cache")
    assert rebuilt[0].derived_path is not None
    assert Path(rebuilt[0].derived_path).is_file()


def test_an_existing_derived_image_is_left_alone(tmp_path, frame):
    from core.critic.models import BaseRender

    base_path = tmp_path / "base.png"
    save_rgb(base_path, frame)
    base = BaseRender(
        id="desert-s4",
        scene="desert",
        seed=4,
        image_path=str(base_path),
        image_sha256="0" * 64,
        width=frame.shape[1],
        height=frame.shape[0],
    )
    kept = tmp_path / "kept.png"
    save_rgb(kept, frame)
    member = MemberRecipe(
        member_id="m1",
        base_id="desert-s4",
        defect="black_frame",
        layer="image",
        seed=902,
        recipe={"kind": "image"},
        derived_path=str(kept),
    )
    rebuilt = ensure_derived([member], [base], tmp_path / "cache")
    assert rebuilt[0].derived_path == str(kept)


# -- helpers ------------------------------------------------------------------


_FRAME_PATH: Path | None = None


def _frame_path_of() -> Path:
    assert _FRAME_PATH is not None
    return _FRAME_PATH


@pytest.fixture(autouse=True)
def _remember_frame(frame_path):
    global _FRAME_PATH
    _FRAME_PATH = frame_path
    yield


class _BlackFrameCritic:
    """A critic that finds a black frame and nothing else."""

    name = "black-frame-critic"
    layers = ("image",)

    def score(
        self,
        member: MemberRecipe,
        *,
        bases=(),
        thresholds=None,
        cache_dir=None,
        blender_python=None,
    ) -> CriticVerdict:
        checks = tuple(
            CheckOutcome(
                check=check,
                fired=(check == "black_frame"),
                detail="found" if check == "black_frame" else "not found",
                applicable=True,
            )
            for check in (
                "black_frame",
                "fireflies",
                "flat_patch",
                "dark_holes",
                "patch_seam",
                "floating_blob",
            )
        )
        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=checks,
            label="verdict@black-frame-critic",
            degraded="black-frame-critic",
            layer=member.layer,
        )


class _Task:
    id = "task-1"


class _Variant:
    id = "variant-1"


def _task():
    return _Task()


def _variant():
    return _Variant()


# -- the published table -------------------------------------------------------


def _published_selection_rows():
    """The rows of the published selection table, as the file carries them."""
    root = Path(__file__).resolve().parents[2]
    text = (root / "core" / "critic" / "CALIBRATION.md").read_text(encoding="utf-8")
    assert "## The selection" in text, "the published table carries no selection"
    section = text.split("## The selection", 1)[1]
    rows = {}
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        match = re.match(r"`([^`]+)`", cells[0])
        if not match:
            continue
        rows[match.group(1)] = cells
    return rows


def test_the_published_table_carries_the_selection_that_was_measured():
    """The published file's counts are the selection file's counts.

    The house rule: the table says what was measured. If the selection is
    re-measured, the table has to be published again — a hand-edit would
    leave the two disagreeing, and nobody would notice until a reader
    checked the counts.
    """
    root = Path(__file__).resolve().parents[2]
    selection = json.loads(
        (root / "core" / "critic" / "selection.json").read_text(encoding="utf-8")
    )
    rows = _published_selection_rows()

    for candidate in selection["candidates"]:
        name = candidate["name"]
        assert name in rows, f"the published table has no row for {name}"
        cells = rows[name]
        assert int(cells[2]) == candidate["tp"], name
        assert int(cells[3]) == candidate["fp"], name
        assert int(cells[4]) == candidate["fn"], name
        assert int(cells[5]) == candidate["tn"], name
        assert cells[6] == ("yes" if candidate["in_band"] else "no"), name
        assert cells[7] == f"{candidate['median_ms']:.0f}", name


def test_the_published_table_marks_the_chosen_critic():
    """One chosen critic, and the published file says which one."""
    root = Path(__file__).resolve().parents[2]
    selection = json.loads(
        (root / "core" / "critic" / "selection.json").read_text(encoding="utf-8")
    )
    rows = _published_selection_rows()
    chosen = selection["chosen"]
    assert chosen in rows
    assert "**(chosen)**" in rows[chosen][0]
    others = [n for n in rows if n != chosen]
    assert others, "the published table lists only the chosen critic"
    for name in others:
        assert "**(chosen)**" not in rows[name][0], name


def test_the_published_table_has_the_chosen_critics_own_classes():
    """The chosen critic's per-class table is in the published file too."""
    root = Path(__file__).resolve().parents[2]
    selection = json.loads(
        (root / "core" / "critic" / "selection.json").read_text(encoding="utf-8")
    )
    text = (root / "core" / "critic" / "CALIBRATION.md").read_text(encoding="utf-8")
    chosen = selection["chosen"]
    candidate = next(c for c in selection["candidates"] if c["name"] == chosen)
    for row in candidate["rows"]:
        assert row["defect"] in text, row["defect"]
        assert row["check"] in text, row["check"]
