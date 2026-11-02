"""`core/voyager` — Voyager's loop, re-engineered to be system-agnostic.

Casey's brief: *"https://github.com/MineDojo/Voyager ... can be
re-engineered for different systems."*

Voyager's loop has three parts — an automatic novelty-biased curriculum,
a library of executable skills written by a model, and iterative
prompting that feeds the environment's feedback and the execution errors
back into the next program. This package is that loop with the
Minecraft taken out:

| part | here |
|---|---|
| the curriculum | :mod:`core.voyager.curriculum` — novelty-biased, with the tech tree as a dependency rather than a fixed order |
| the skill library | :mod:`core.voyager.skills` — **our tiles** (``core/tiles``), content addressed, versioned by family, never deleted |
| the skill writer | :mod:`core.voyager.llm` and :mod:`core.voyager.prompts` — three roles, and the verifier is a **different model** from the coder |
| the environment | :mod:`core.voyager.ports` — one protocol; the Minecraft, Crafter, vibe-sandbox and Bevy worlds are adapters behind it |
| the feedback | :mod:`core.voyager.runner` — the execution error and the verifier's critique go into the next prompt |

**The model is in the cloud and every token is counted.** The Thor hosts
no language model; the planner, the coder and the verifier are DeepInfra
models, and every call's prompt and completion tokens are on the record,
because the brief asks for the token cost of a milestone and a cost with
no denominator is a decoration.

The licences: Voyager is MIT and its notice is kept; this is a
re-engineering, not a copy of its code.
"""

from __future__ import annotations

from .budget import ProbeBudget, RunBudget
from .curriculum import Curriculum, CurriculumState
from .llm import DeepInfraClient, ModelRouter, load_secret
from .metrics import Metrics
from .models import (
    Disposition,
    Milestone,
    ModelReply,
    Role,
    RunReport,
    SkillProposal,
    SkillRecord,
    StepRecord,
    TokenUsage,
    Verdict,
)
from .ports import (
    CheckResult,
    EnvironmentPort,
    ExecResult,
    ModelPort,
    ProgressSnapshot,
)
from .runner import LoopConfig, VoyagerLoop
from .skills import SkillLibrary, fold_skills
from .vocab import SkillVocabulary, SkillRefusal, scan_primitives

__all__ = [
    "Budget",
    "CheckResult",
    "Curriculum",
    "CurriculumState",
    "DeepInfraClient",
    "Disposition",
    "EnvironmentPort",
    "ExecResult",
    "LoopConfig",
    "Metrics",
    "Milestone",
    "ModelPort",
    "ModelReply",
    "ModelRouter",
    "ProbeBudget",
    "ProgressSnapshot",
    "Role",
    "RunBudget",
    "RunReport",
    "SkillLibrary",
    "SkillProposal",
    "SkillRecord",
    "SkillRefusal",
    "SkillVocabulary",
    "StepRecord",
    "TokenUsage",
    "Verdict",
    "VoyagerLoop",
    "fold_skills",
    "load_secret",
    "scan_primitives",
]


class Budget(RunBudget):
    """The run's outer limits. A name that reads well at the call site."""
