"""The licence rows: what each model in the pipeline carries.

These were checked against the Hugging Face registry and the upstream
repositories directly, not against a summary — the working is in
docs/research/trellis-spike.md §6. Two obligations travel with the TRELLIS.2
path and the rows say so:

* the **DINOv3** encoder's end-use limits and attribution, which ride along
  inside the MIT weights; and
* **ComfyUI**, which is GPL-3.0 and is the *host* — kept as a separate
  service and talked to over HTTP, never linked.

The image stage's SDXL weights are a row of their own (OpenRAIL++-M), and a
prop made from an image carries both.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.models import Licence

__all__ = ["LICENCE_ROWS", "LicenceRow", "licence_for", "licences_for"]

#: The TRELLIS.2 weights' revision, as the spike pinned it.
TRELLIS2_REVISION = "430a9d09b2416687018c8fe8edced2ad4858a439"

#: The SDXL checkpoint the image stage uses.
SDXL_REVISION = "sd_xl_base_1.0.safetensors"


class LicenceRow(BaseModel):
    """One model's licence, and where the row was checked."""

    model: str
    licence: Licence
    source: str
    revision: str = ""


TRELLIS2_ROW = LicenceRow(
    model="trellis2",
    licence=Licence(
        spdx="MIT",
        dependency_terms=[
            "DINOv3 encoder (Meta dinov3-license): attribution and end-use limits "
            "travel with the weights",
            "ComfyUI (GPL-3.0) is the host and is used as a separate service, never linked",
        ],
        commercial_ok=True,
        checked_at="2026-10-31",
        checked_by="trellis-spike",
        notes=(
            "TRELLIS.2 weights: Comfy-Org/TRELLIS.2, MIT, ungated, "
            f"revision {TRELLIS2_REVISION}"
        ),
    ),
    source="huggingface.co/Comfy-Org/TRELLIS.2 and github.com/microsoft/TRELLIS.2",
    revision=TRELLIS2_REVISION,
)

SDXL_ROW = LicenceRow(
    model="sd_xl_base_1.0",
    licence=Licence(
        spdx="OpenRAIL++-M",
        dependency_terms=[
            "Stability AI's OpenRAIL++ use restrictions apply to the image stage's output",
        ],
        commercial_ok=True,
        checked_at="2026-10-31",
        checked_by="trellis-spike",
        notes="SDXL base 1.0, Stability AI, OpenRAIL++-M; the image stage only",
    ),
    source="huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
    revision=SDXL_REVISION,
)

#: Every row, by model name.
LICENCE_ROWS: dict[str, LicenceRow] = {
    TRELLIS2_ROW.model: TRELLIS2_ROW,
    SDXL_ROW.model: SDXL_ROW,
}


def licence_for(model: str) -> LicenceRow:
    """The licence row for one model.

    Raises ``KeyError`` when nobody has checked the model — a licence nobody
    looked at is not a licence, and the morning has to be able to say which
    one it was.
    """
    return LICENCE_ROWS[model]


def licences_for(models: list[str]) -> list[Licence]:
    """The licence rows for a list of models, in the order they were used."""
    return [licence_for(model).licence for model in models]
