"""The fixed question per defect class — one wording, every frame, every delegate.

The questions live in their own module because **three** delegates now ask
them: the local vision-language model, the local decision model (``d1-2B``)
and the cloud decision model (``clef-flash``). They must be the same words, or
the bake-off compares two different questions instead of two different models.

The rule the wording follows:

* **One question per class, the same for every frame.** A delegate cannot be
  tuned per member, so the numbers are comparable across members and across
  candidates.
* **The question asks about the picture only.** No scripted measurements, no
  thresholds, no hint about which class is planted. Whatever a delegate gets
  right, it got from the frame.
* **The wording is fixed before the measurement.** It was written for the
  first candidate (the 30 B vision-language model) and kept, so the new rows
  are comparable with the old one. Changing it now, after seeing which
  members each model gets right, would be tuning on the set the numbers are
  measured on.

A ``noul`` question needs no answer format — the decision models answer with
a probability of *yes* — but the tail is harmless and keeps one wording for
every candidate, including the text one.
"""

from __future__ import annotations

__all__ = ["CLASS_QUESTIONS", "IMAGE_CLASSES", "question_for"]

#: The image classes a pixel delegate can be asked about. The mesh classes
#: live in the geometry, and the reference set never re-renders a mesh defect,
#: so there is no picture of them to look at.
IMAGE_CLASSES: tuple[str, ...] = (
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
)

#: The fixed question per class. Every frame is asked the same words.
CLASS_QUESTIONS: dict[str, str] = {
    "black_frame": (
        "Does this image show a completely black picture with no visible scene? "
        "Answer yes or no."
    ),
    "noise_fireflies": (
        "Does this image show bright isolated speckles scattered over the "
        "picture, like dust or fireflies in a render? Answer yes or no."
    ),
    "missing_object": (
        "Does this image show a missing object — a flat, empty patch where "
        "something should be, as if a prop failed to render? Answer yes or no."
    ),
    "holes": (
        "Does this image show holes — dark empty gaps or pits in a surface? "
        "Answer yes or no."
    ),
    "texture_swap": (
        "Does this image show a rectangular block of texture that does not "
        "belong, as if a patch of the surface came from a different picture? "
        "Answer yes or no."
    ),
    "floating_object": (
        "Does this image show an object floating in mid-air, detached from "
        "the ground or hanging in empty space? Answer yes or no."
    ),
}


def question_for(defect: str) -> str:
    """The fixed question for a defect class."""
    return CLASS_QUESTIONS[defect]
