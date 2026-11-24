"""agent-world-gym: the world's game as a Gymnasium environment, and a
Minari recorder for the community's demonstrations.

Two pieces, one world:

* :class:`~agent_world_gym.env.AgentWorldEnv` — a Gymnasium environment
  over the live agent-world. It drives **one** mineflayer bot on a
  **private** Paper server (127.0.0.1:25630, offline mode, a world of its
  own — never the live server, never the live world). The observation is
  the reflex's state facts plus an optional local block grid; the action
  is the reflex's option set, discrete.
* :class:`~agent_world_gym.recorder.GymRecorder` — a Minari dataset writer
  with two sources: the private world under a scripted policy, and the
  **live community's** plays, read-only from the world's ledger.

The recorder keeps **every** frame it is given. Crafter round 2
(2026-11-02) settled that question: all the frames, at the largest budget
available; a subset is a compute-saving shortcut, not a better choice.

The recorder is not imported here on purpose: it pulls Minari (and Minari
pulls jax, which is slow to import). Import it where it is needed::

    from agent_world_gym.recorder import GymRecorder
"""

from __future__ import annotations

from .actions import PROJECT_PREFIX, action_list, index_of, is_project_id
from .bridge import BridgeError, GymBridge
from .env import AgentWorldEnv
from .facts import BLOCK_VOCAB, FACT_NAMES, encode_facts
from .ledger import LedgerEpisode, LedgerPlay, WorldLedgerReader
from .policies import ScriptedPolicy, make_policy
from .replay import LedgerReplayEnv
from .student import BCStudent, RandomPolicy, evaluate_in_env, train_student

__all__ = [
    "AgentWorldEnv",
    "BCStudent",
    "BLOCK_VOCAB",
    "BridgeError",
    "FACT_NAMES",
    "GymBridge",
    "LedgerEpisode",
    "LedgerPlay",
    "LedgerReplayEnv",
    "PROJECT_PREFIX",
    "RandomPolicy",
    "ScriptedPolicy",
    "WorldLedgerReader",
    "action_list",
    "encode_facts",
    "evaluate_in_env",
    "index_of",
    "is_project_id",
    "make_policy",
    "train_student",
]

__version__ = "0.1.0"
