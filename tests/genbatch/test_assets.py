"""The licence rows, and the asset that carries them.

A generated prop is only as good as the licence it comes with. The rows here
are the ones the TRELLIS.2 spike checked against the Hugging Face registry
and the upstream repositories (docs/research/trellis-spike.md §6) — MIT for
the TRELLIS.2 weights with the DINOv3 end-use limits travelling alongside,
and OpenRAIL++-M for the image stage.
"""

from __future__ import annotations

import hashlib

import pytest

from core.genbatch.assets import build_asset
from core.genbatch.licences import LicenceRow, licence_for
from core.genbatch.models import PropRequest
from tests.genbatch.glb_fixtures import build_glb, cube_mesh


def test_the_trellis_weights_are_mit():
    row = licence_for("trellis2")

    assert row.licence.spdx == "MIT"
    assert row.licence.commercial_ok is True


def test_the_dinov3_terms_travel_with_the_weights():
    row = licence_for("trellis2")

    assert any("DINOv3" in term for term in row.licence.dependency_terms)


def test_the_image_stage_carries_its_own_licence():
    row = licence_for("sd_xl_base_1.0")

    assert row.licence.spdx == "OpenRAIL++-M"
    assert row.licence.commercial_ok is True


def test_comfyui_stays_a_separate_service():
    row = licence_for("trellis2")

    assert any("ComfyUI" in term for term in row.licence.dependency_terms)


def test_an_unknown_model_has_no_licence_row():
    with pytest.raises(KeyError):
        licence_for("some-model-nobody-checked")


def test_the_asset_carries_the_glb_its_provenance_and_its_licence(tmp_path):
    positions, indices = cube_mesh()
    glb = tmp_path / "crate.glb"
    glb.write_bytes(build_glb(positions, indices))
    request = PropRequest(id="crate", prompt="a weathered wooden crate")

    asset = build_asset(
        request=request,
        variant_id="crate_r1_v2",
        glb_path=glb,
        generator={
            "model": "trellis2",
            "weights_revision": "430a9d09b2416687018c8fe8edced2ad4858a439",
            "seed": 4242,
            "resolution": 512,
            "prompt": "a weathered wooden crate",
        },
        licence=licence_for("trellis2").licence,
        critic={"score": 0.91},
    )

    assert asset.kind == "mesh"
    assert asset.provenance.source == "generated"
    assert asset.provenance.generator["prompt"] == "a weathered wooden crate"
    assert asset.provenance.generator["seed"] == 4242
    assert asset.provenance.generator["resolution"] == 512
    assert asset.provenance.generator["weights_revision"].startswith("430a9d0")
    assert asset.licence.spdx == "MIT"
    assert asset.critic == {"score": 0.91}


def test_the_asset_records_the_file_it_points_at(tmp_path):
    positions, indices = cube_mesh()
    glb = tmp_path / "crate.glb"
    glb.write_bytes(build_glb(positions, indices))
    request = PropRequest(id="crate", prompt="a weathered wooden crate")

    asset = build_asset(
        request=request,
        variant_id="crate_r1_v2",
        glb_path=glb,
        generator={"model": "trellis2"},
        licence=licence_for("trellis2").licence,
    )

    (ref,) = asset.files
    assert ref.role == "glb"
    assert ref.path == str(glb)
    assert ref.bytes == glb.stat().st_size
    assert ref.sha256 == hashlib.sha256(glb.read_bytes()).hexdigest()


def test_the_asset_id_is_stable_for_the_same_request_and_variant(tmp_path):
    positions, indices = cube_mesh()
    glb = tmp_path / "crate.glb"
    glb.write_bytes(build_glb(positions, indices))
    request = PropRequest(id="crate", prompt="a weathered wooden crate")

    first = build_asset(
        request=request,
        variant_id="crate_r1_v2",
        glb_path=glb,
        generator={"model": "trellis2"},
        licence=licence_for("trellis2").licence,
    )
    second = build_asset(
        request=request,
        variant_id="crate_r1_v2",
        glb_path=glb,
        generator={"model": "trellis2"},
        licence=licence_for("trellis2").licence,
    )

    assert first.id == second.id
    assert first.id == "asset_crate_r1_v2"
