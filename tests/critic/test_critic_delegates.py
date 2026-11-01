"""The delegates' tests — the decision models, and the 30 B default that is gone.

The rules, as tests:

* the **registry** knows the two decision-model delegates (``d1`` and
  ``clef``), and the hybrid's default delegate is the local one;
* the 30 B vision-language model is **no longer anybody's default**: the
  candidate cannot even be built without being told which model it is;
* the delegates ask the **same fixed questions**, so the bake-off compares
  models and not questions.
"""

from __future__ import annotations

import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.critic.candidates.questions import CLASS_QUESTIONS  # noqa: E402
from core.critic.select import (  # noqa: E402
    HYBRID_DELEGATE,
    CriticUnavailable,
    build_critic,
    candidate_names,
)


def test_the_registry_knows_the_decision_model_delegates():
    names = candidate_names()
    assert "d1" in names
    assert "clef" in names


def test_the_hybrid_s_default_delegate_is_the_local_decision_model():
    assert HYBRID_DELEGATE == "d1"


def test_the_vlm_candidate_has_no_default_model():
    """The 30 B model is no longer anybody's default.

    The candidate cannot be built without being told which model it is, so
    a caller that forgets says so instead of quietly loading a 17 GB
    language model onto a shared box.
    """
    with pytest.raises(CriticUnavailable):
        build_critic("vlm")
    critic = build_critic("vlm", model="some-other-vlm")
    assert critic.name == "vlm"


def test_the_delegates_ask_the_same_fixed_questions():
    from core.critic.candidates.clef import CLEF_CLASSES
    from core.critic.candidates.d1 import D1_CLASSES
    from core.critic.candidates.vlm import VLM_QUESTIONS

    assert D1_CLASSES == CLEF_CLASSES
    assert VLM_QUESTIONS == CLASS_QUESTIONS
    assert "floating_object" in CLASS_QUESTIONS
