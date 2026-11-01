"""The candidate critics that need a model.

Each one is a :class:`core.critic.critic.ReferenceCritic`: it names itself,
it says which layers it can see, and it scores a member. They are imported
**lazily** — the core has no torch, no llama.cpp and no network dependency,
so ``import core.critic`` never needs any of them.
"""

from __future__ import annotations

__all__ = ["dino", "jev", "vlm"]
