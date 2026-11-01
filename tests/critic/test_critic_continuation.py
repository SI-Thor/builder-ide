"""The continuations' tests — the critic's next move.

The rules, as tests:

* a verdict that flags ``floating_object`` carries a **continuation** — a
  typed edit in the closed vocabulary of :mod:`core.critic.edits` — and a
  verdict that does not flag it carries none;
* the edit names the **support surface below** the thing and the **drop
  distance**, both measured, and it round-trips through its dictionary form;
* applying the edit to the frame **clears the flag**.

The tests run on **synthetic frames**, not on the sweep: fast, and they do
not depend on the sweep being there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.critic.checks import run_image_checks  # noqa: E402
from core.critic.edits import Edit, Support, apply_edit  # noqa: E402
from core.critic.hybrid import HybridCritic  # noqa: E402
from core.critic.imaging import save_rgb  # noqa: E402
from core.critic.set import MemberRecipe  # noqa: E402
from core.critic.surface import probe_surface, suggest_edit  # noqa: E402


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="session")
def sky_with_a_thing() -> np.ndarray:
    """A frame with a thing hanging in the sky above a textured ground.

    The sky is smooth (so the thing stands in empty space) and the ground
    carries texture (so there is a surface to measure against).
    """
    h, w = 540, 960
    image = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        value = 150 + int(60 * (y / h))
        image[y, :, :] = value
    rng = np.random.default_rng(7)
    ground = image[350:, :, :]
    noise = rng.integers(-70, 70, size=ground.shape, dtype=np.int16)
    image[350:, :, :] = np.clip(ground.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # the thing: a dark compact blob, well clear of the frame's edges
    image[100:200, 400:500, :] = 40
    return image


@pytest.fixture(scope="session")
def clean_sky() -> np.ndarray:
    """A frame with a smooth sky over a smooth ground: nothing hanging."""
    h, w = 540, 960
    image = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        image[y, :, :] = 150 + int(60 * (y / h))
    return image


@pytest.fixture(scope="session")
def frame_path(tmp_path_factory, sky_with_a_thing) -> Path:
    path = tmp_path_factory.mktemp("frames") / "frame.png"
    save_rgb(path, sky_with_a_thing)
    return path


def _member(frame_path: Path) -> MemberRecipe:
    return MemberRecipe(
        member_id="mem_test",
        base_id="base_test",
        defect="floating_object",
        layer="image",
        seed=1,
        recipe={},
        derived_path=str(frame_path),
    )


class _AlwaysFloating:
    """A delegate that answers the way a model would: yes, it is floating."""

    name = "always-floating"
    layers = ("image",)

    def score(self, member, **kwargs):
        from core.critic.models import CheckOutcome, CriticVerdict

        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=(
                CheckOutcome(
                    check="floating_blob",
                    fired=True,
                    detail="the delegate says yes",
                    measured={"d1_probability": 0.99},
                ),
            ),
            label="verdict@always-floating",
            degraded="always-floating",
            layer=member.layer,
        )


class _Quiet:
    """A delegate that answers no."""

    name = "quiet"
    layers = ("image",)

    def score(self, member, **kwargs):
        from core.critic.models import CheckOutcome, CriticVerdict

        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=(
                CheckOutcome(
                    check="floating_blob",
                    fired=False,
                    detail="the delegate says no",
                    measured={"d1_probability": 0.01},
                ),
            ),
            label="verdict@quiet",
            degraded="quiet",
            layer=member.layer,
        )


# -- the continuation --------------------------------------------------------


def test_the_probe_finds_the_support_surface_and_the_drop_distance(sky_with_a_thing):
    surface = probe_surface(sky_with_a_thing)
    assert surface is not None
    # the surface is where the frame's structure resumes: the ground starts
    # at row 350 and carries detail a few rows into it
    assert 350 <= surface.row <= 400
    assert surface.drop_px == surface.row - surface.box[3]
    assert surface.drop_px > 100
    assert surface.drop_frame_heights == pytest.approx(surface.drop_px / 540)
    # the thing the probe points at is the blob that hangs in the sky
    assert surface.box[0] < 400 and surface.box[2] > 500
    assert surface.box[1] < 100 and surface.box[3] > 200


def test_the_probe_says_nothing_when_nothing_is_hanging(clean_sky):
    assert probe_surface(clean_sky) is None
    assert suggest_edit(clean_sky) is None


def test_the_edit_is_a_typed_thing_in_a_closed_vocabulary(sky_with_a_thing):
    edit = suggest_edit(sky_with_a_thing)
    assert edit is not None
    assert edit.op == "lower_object"
    assert edit.support.kind in ("terrain", "liquid", "prop", "unknown")
    assert edit.drop_px > 0
    # the dictionary form is what the builder consumes, and it round-trips
    payload = edit.as_dict()
    assert json.loads(json.dumps(payload)) == payload
    again = Edit.from_dict(payload)
    assert again.op == edit.op
    assert again.box == edit.box
    assert again.drop_px == edit.drop_px
    assert again.support.kind == edit.support.kind


def test_applying_the_edit_clears_the_flag(sky_with_a_thing):
    before = [c for c in run_image_checks(sky_with_a_thing) if c.check == "floating_blob"][0]
    assert before.fired

    edit = suggest_edit(sky_with_a_thing)
    assert edit is not None
    edited = apply_edit(sky_with_a_thing, edit)

    after = [c for c in run_image_checks(edited) if c.check == "floating_blob"][0]
    assert not after.fired
    assert after.measured["gap"] == 0.0


def test_the_hybrid_carries_the_continuation_when_the_flag_fires(frame_path):
    hybrid = HybridCritic(_AlwaysFloating(), escalate=("floating_object",))
    verdict = hybrid.score(_member(frame_path))
    assert verdict.outcome("floating_blob").fired
    assert len(verdict.edits) == 1
    edit = verdict.edits[0]
    assert edit.op == "lower_object"
    assert edit.drop_px > 0
    assert edit.support.row is not None


def test_the_hybrid_carries_no_continuation_when_nothing_fires(frame_path):
    hybrid = HybridCritic(_Quiet(), escalate=("floating_object",))
    verdict = hybrid.score(_member(frame_path))
    assert not verdict.outcome("floating_blob").fired
    assert verdict.edits == ()


# -- the metric scale, from the geometry probe --------------------------------


def _camera_stats(half_width: float, frame_width: int = 960):
    from core.critic.models import CameraInfo, MeshStats

    return MeshStats(
        camera=CameraInfo(
            location=(0.0, 0.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            up=(0.0, 1.0, 0.0),
            right=(1.0, 0.0, 0.0),
            half_width=half_width,
            half_height=half_width * 9 / 16,
            depth=10.0,
        ),
        frame_width=frame_width,
        frame_height=540,
    )


def test_the_edit_carries_the_drop_in_metres_when_the_scene_is_measured(
    frame_path, monkeypatch
):
    """The geometry probe's camera gives the picture's scale, so the drop has
    a metre value as well as a pixel one."""
    import core.critic.hybrid as hybrid_module

    monkeypatch.setattr(
        hybrid_module, "probe_scene", lambda *a, **k: _camera_stats(9.6)
    )
    member = MemberRecipe(
        member_id="mem_test",
        base_id="base_test",
        defect="floating_object",
        layer="image",
        seed=1,
        recipe={},
        derived_path=str(frame_path),
        mesh_path="/nowhere/scene.blend",
    )
    hybrid = HybridCritic(_AlwaysFloating(), escalate=("floating_object",))
    verdict = hybrid.score(member)
    assert len(verdict.edits) == 1
    edit = verdict.edits[0]
    # 9.6 m of half-width over 960 px is 0.02 m per pixel
    assert edit.drop_m == pytest.approx(edit.drop_px * 0.02)
    assert edit.as_dict()["drop_m"] == pytest.approx(edit.drop_px * 0.02)


def test_the_edit_stays_in_the_frame_when_the_scene_cannot_be_measured(
    frame_path, monkeypatch
):
    """No scene means no metre value — the edit says so instead of guessing."""
    import core.critic.hybrid as hybrid_module

    def _no_scene(*a, **k):
        raise RuntimeError("no blend on this box")

    monkeypatch.setattr(hybrid_module, "probe_scene", _no_scene)
    member = MemberRecipe(
        member_id="mem_test",
        base_id="base_test",
        defect="floating_object",
        layer="image",
        seed=1,
        recipe={},
        derived_path=str(frame_path),
        mesh_path="/nowhere/scene.blend",
    )
    hybrid = HybridCritic(_AlwaysFloating(), escalate=("floating_object",))
    verdict = hybrid.score(member)
    edit = verdict.edits[0]
    assert edit.drop_px > 0
    assert edit.drop_frame_heights > 0
    assert edit.drop_m is None
