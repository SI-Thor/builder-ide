"""The critic's continuations: a verdict that carries the next move.

The design doc's "room is the anti-GAN" rule says the critic does not make
pictures — it says what is wrong *and what to do about it*. A verdict with no
continuation is a complaint; a verdict with a continuation is a move, and the
builder can act on it without asking anything.

So the critic's answer has two halves:

* the **verdict** — which class fired, and what was measured;
* the **continuation** — a *typed edit* in a closed vocabulary that the
  builder can apply to the scene.

The vocabulary is closed on purpose. A builder changes recipes through a
closed, typed vocabulary, never by writing code, so an edit that can only be
one of a fixed set of things is an edit a builder can apply without
understanding the critic. Today there is one:

``lower_object``
    Put the thing that is floating down onto the surface below it. The edit
    carries **which surface** (the support) and **how far** (the drop
    distance), both measured by a probe, and both in the frame's own units
    plus metres when a metric probe was available.

The edit is a *proposal*, not an action: the critic does not move anything.
Applying it is the builder's move, and :func:`apply_edit` is what "applying
it" means in the frame's domain — the thing is cut out of the frame and
pasted onto the support surface, with the sky it vacated filled in from the
frame's own colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .imaging import luma

__all__ = [
    "SupportKind",
    "EditOp",
    "Support",
    "Edit",
    "apply_edit",
]


#: What a thing can be put down on. The set is closed: a builder's recipe
#: may only name one of these.
SupportKind = Literal["terrain", "liquid", "prop", "unknown"]

#: The edits the critic may propose. The set is closed, for the same reason.
EditOp = Literal["lower_object"]


@dataclass(frozen=True)
class Support:
    """The surface below the thing that is floating.

    ``kind`` is the surface's *type*, not a name: a builder's recipe says
    "put it on the terrain", not "put it on the snow at x=12". ``row`` is
    where the surface starts in the frame (the frame domain), and ``source``
    says which probe said so — ``frame`` (measured in the picture) or
    ``geometry`` (measured in the scene).
    """

    kind: SupportKind
    label: str = ""
    row: int | None = None
    source: str = "frame"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "row": self.row,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Support":
        return cls(
            kind=payload.get("kind", "unknown"),
            label=payload.get("label", ""),
            row=payload.get("row"),
            source=payload.get("source", "frame"),
        )


@dataclass(frozen=True)
class Edit:
    """One typed edit the builder can apply.

    The drop distance is carried in the frame's own units — pixels and frame
    heights, both exact — and in metres when a metric probe could reach the
    scene. ``box`` is the thing to move, in the frame's pixels.
    """

    op: EditOp
    target: str
    box: tuple[int, int, int, int]
    support: Support
    drop_px: int
    drop_frame_heights: float
    drop_m: float | None = None
    evidence: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "target": self.target,
            "box": list(self.box),
            "support": self.support.as_dict(),
            "drop_px": self.drop_px,
            "drop_frame_heights": round(self.drop_frame_heights, 6),
            "drop_m": self.drop_m,
            "evidence": {k: round(float(v), 6) for k, v in self.evidence.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Edit":
        return cls(
            op=payload.get("op", "lower_object"),
            target=payload.get("target", ""),
            box=tuple(payload.get("box", (0, 0, 0, 0))),  # type: ignore[arg-type]
            support=Support.from_dict(payload.get("support", {})),
            drop_px=int(payload.get("drop_px", 0)),
            drop_frame_heights=float(payload.get("drop_frame_heights", 0.0)),
            drop_m=payload.get("drop_m"),
            evidence=dict(payload.get("evidence", {})),
        )


def _row_background(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """The frame's own colour for each row of the box, from outside the box.

    A thing hanging in the air sits against the background, so the colour of
    the row it hangs in — measured from the rest of that row — is the colour
    it is hanging against. The median is used, so the thing itself (a small
    part of a wide row) does not bias it.

    The colour is kept in **RGB**, not reduced to a luminance: a sky is not
    grey, and filling a hole with the luminance of a sky leaves a grey patch
    where the sky was — a patch that a critic (or a person) reads as an
    artefact of its own.
    """
    x0, y0, x1, y1 = box
    height, width = image.shape[:2]
    background = np.zeros((y1 - y0 + 1, 3), dtype=np.float32)
    for row in range(y0, y1 + 1):
        line = image[row]
        margins = np.concatenate([line[:x0], line[x1 + 1 :]], axis=0)
        if margins.size:
            background[row - y0] = np.median(margins.astype(np.float32), axis=0)
        else:
            background[row - y0] = np.median(line.astype(np.float32), axis=0)
    return background


def _object_mask(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    delta: float,
) -> np.ndarray:
    """The thing's own pixels: what stands out from the background it hangs in.

    The check's own mask finds a thing's *edges* against its local mean, which
    is the right mask for finding a thing and the wrong one for cutting it
    out: a thing with holes in it (a bush, a lacy rock) would be cut into
    speckles. The background model here is the row's own colour, so the cut
    is the thing's silhouette and the sky between its branches stays sky.
    """
    g = luma(image)
    x0, y0, x1, y1 = box
    background = _row_background(image, box)
    background_luma = (
        0.299 * background[:, 0] + 0.587 * background[:, 1] + 0.114 * background[:, 2]
    )
    band = np.abs(g[y0 : y1 + 1, x0 : x1 + 1] - background_luma[:, None])
    mask = np.zeros(g.shape, dtype=bool)
    mask[y0 : y1 + 1, x0 : x1 + 1] = band > delta
    return mask


def apply_edit(
    image: np.ndarray,
    edit: Edit,
    *,
    delta: float = 0.03,
) -> np.ndarray:
    """Apply a ``lower_object`` edit to a frame.

    The thing is cut out of the frame, the space it leaves is filled with the
    frame's own colour for those rows (the sky it was hanging in), and the
    thing is pasted lower so that its bottom sits on the support surface.

    This is the frame-domain meaning of the edit, and it is what the
    reference set's members can be tested against: the member's picture is
    edited, the checks run again on the edited picture, and the flag has to
    be gone.
    """
    if edit.op != "lower_object":
        raise ValueError(f"unknown edit op {edit.op!r}")
    out = image.copy()
    height, width = image.shape[:2]
    x0, y0, x1, y1 = edit.box
    x0 = max(0, min(x0, width - 1))
    x1 = max(x0, min(x1, width - 1))
    y0 = max(0, min(y0, height - 1))
    y1 = max(y0, min(y1, height - 1))

    mask = _object_mask(image, (x0, y0, x1, y1), delta)
    if not mask.any():
        return out

    patch = image[y0 : y1 + 1, x0 : x1 + 1, :].copy()
    alpha = mask[y0 : y1 + 1, x0 : x1 + 1]
    background = _row_background(image, (x0, y0, x1, y1))

    # 1. the space the thing leaves is filled with the frame's own colour for
    #    those rows — the background it was hanging against.
    for row in range(y0, y1 + 1):
        band = out[row, x0 : x1 + 1, :]
        band[alpha[row - y0]] = np.clip(background[row - y0], 0, 255).astype(np.uint8)

    # 2. the thing is pasted lower, so that its bottom lands on the support.
    drop = int(edit.drop_px)
    target_bottom = y1 + drop
    if target_bottom > height - 1:
        drop = max(0, (height - 1) - y1)
        target_bottom = y1 + drop
    if drop <= 0:
        return out
    destination = out[y0 + drop : target_bottom + 1, x0 : x1 + 1, :]
    destination[alpha] = patch[alpha]
    return out
