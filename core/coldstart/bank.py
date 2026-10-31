"""The night-one question bank (spec §3.5; G §1 20:12).

Ask-mode is a policy, not a content generator: the Companion supplies the
bank and `AskMode` decides whether a question may be asked. This is the
bank night one actually offers — eight two-chip questions over the first
seed render's crops, each aggregating under one of the closed dozen reason
codes, sized above the ≤ 6 budget on purpose so the bound is real and not
an accident of supply.

The artifact references are placeholders of the honest shape (`branch@rung/
crop`) until the engine renders real crops (the M1 slice's stub-generator
risk, `docs/plan.md`); what matters here is that every question *has* two
artifact references — the two-crops rule is structural, and the taste rows
the answers write point at these refs.

The chips' `value` is what the written row's `subject.value` carries: the
choice, in one word, about the thing.
"""

from __future__ import annotations

from .models import AskCandidate, Chip

__all__ = ["night_one_bank", "NIGHT_ONE_BASE"]

#: Night one per the continuity note (G §0): Saturday 2026-10-24, first rung.
NIGHT_ONE_BASE = "night-2026-10-24@rung-1"


def _crop(name: str) -> str:
    return f"{NIGHT_ONE_BASE}/{name}"


def night_one_bank() -> tuple[AskCandidate, ...]:
    """Eight questions, one reason code each, two chips over two crops each."""
    return (
        AskCandidate(
            prompt="Deep joints, or flush?",
            chips=(
                Chip(id="deep", label="Deep joints", artifact_ref=_crop("shed-joints-deep"), value="deep"),
                Chip(id="flush", label="Flush", artifact_ref=_crop("shed-joints-flush"), value="flush"),
            ),
            reason_code="too_clean",
            subject_path="harbor.sheds.joint_depth",
            artifact_ref=_crop("shed-joints"),
        ),
        AskCandidate(
            prompt="Weathered, or fresh-cut?",
            chips=(
                Chip(id="weathered", label="Weathered", artifact_ref=_crop("shed-wood-weathered"), value="weathered"),
                Chip(id="fresh", label="Fresh-cut", artifact_ref=_crop("shed-wood-fresh"), value="fresh-cut"),
            ),
            reason_code="wrong_era",
            subject_path="harbor.sheds.wood_age",
            artifact_ref=_crop("shed-wood"),
        ),
        AskCandidate(
            prompt="Cluttered jetty, or shipshape?",
            chips=(
                Chip(id="cluttered", label="Cluttered", artifact_ref=_crop("jetty-cluttered"), value="cluttered"),
                Chip(id="shipshape", label="Shipshape", artifact_ref=_crop("jetty-shipshape"), value="shipshape"),
            ),
            reason_code="too_empty",
            subject_path="harbor.jetty.clutter",
            artifact_ref=_crop("jetty"),
        ),
        AskCandidate(
            prompt="Big shed, or snug?",
            chips=(
                Chip(id="big", label="Big", artifact_ref=_crop("shed-scale-big"), value="big"),
                Chip(id="snug", label="Snug", artifact_ref=_crop("shed-scale-snug"), value="snug"),
            ),
            reason_code="wrong_scale",
            subject_path="harbor.sheds.size",
            artifact_ref=_crop("shed-scale"),
        ),
        AskCandidate(
            prompt="Lantern-lit, or floodlit?",
            chips=(
                Chip(id="lantern", label="Lantern-lit", artifact_ref=_crop("quay-lantern"), value="lantern-lit"),
                Chip(id="flood", label="Floodlit", artifact_ref=_crop("quay-flood"), value="floodlit"),
            ),
            reason_code="too_bright",
            subject_path="harbor.quay.lighting",
            artifact_ref=_crop("quay-light"),
        ),
        AskCandidate(
            prompt="Birch only, or mixed stand?",
            chips=(
                Chip(id="birch", label="Birch only", artifact_ref=_crop("slope-birch"), value="birch-only"),
                Chip(id="mixed", label="Mixed", artifact_ref=_crop("slope-mixed"), value="mixed"),
            ),
            reason_code="too_flat",
            subject_path="slope.forest.mix",
            artifact_ref=_crop("slope-stand"),
        ),
        AskCandidate(
            prompt="Rope-handled crates, or plain?",
            chips=(
                Chip(id="rope", label="Rope handles", artifact_ref=_crop("crates-rope"), value="rope-handled"),
                Chip(id="plain", label="Plain", artifact_ref=_crop("crates-plain"), value="plain"),
            ),
            reason_code="wrong_material",
            subject_path="harbor.crates.handles",
            artifact_ref=_crop("crates"),
        ),
        AskCandidate(
            prompt="Mist at dawn, or clear?",
            chips=(
                Chip(id="mist", label="Mist", artifact_ref=_crop("dawn-mist"), value="mist"),
                Chip(id="clear", label="Clear", artifact_ref=_crop("dawn-clear"), value="clear"),
            ),
            reason_code="wrong_weather",
            subject_path="weather.dawn",
            artifact_ref=_crop("dawn"),
        ),
    )
