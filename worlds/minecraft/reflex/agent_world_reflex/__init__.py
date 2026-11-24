"""agent-world's reflex: the decision seam of the world.

The world's reflex is builder-ide's judge (a small local decision model
on the Thor) and builder-ide's contextual bandit, with this world's own
skill library in front of them. The mediator — the cloud author — is in
:mod:`agent_world_reflex.mediator`.
"""

from .chooser import Choice, Chooser
from .decision import DecisionModel
from .door import ACT, OBSERVE, VOCABULARY, check_body
from .library import SkillLibrary, build_skill
from .mediator import Mediator, feedback_packets, sign_of
from .models import (
    FeedbackPacket,
    Outcome,
    PlayCost,
    PlayRecord,
    Prediction,
    Precondition,
    Skill,
    SkillAuthor,
    SkillRefusal,
)
from .service import ReflexService, serve

__all__ = [
    "Choice",
    "Chooser",
    "DecisionModel",
    "ACT",
    "OBSERVE",
    "VOCABULARY",
    "check_body",
    "SkillLibrary",
    "build_skill",
    "Mediator",
    "feedback_packets",
    "sign_of",
    "FeedbackPacket",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "Prediction",
    "Precondition",
    "Skill",
    "SkillAuthor",
    "SkillRefusal",
    "ReflexService",
    "serve",
]
