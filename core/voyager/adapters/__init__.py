"""The adapters — the worlds the loop plays in.

Four of them, in the order the brief gives:

1. :mod:`core.voyager.adapters.minecraft` — the real one, measured on a
   private Paper server;
2. :mod:`core.voyager.adapters.crafter` — the fast one, Crafter, the
   same loop with the latency removed;
3. :mod:`core.voyager.adapters.vibesandbox` — a stub, for build skills;
4. :mod:`core.voyager.adapters.bevy` — a stub, for the Bevy world.

Each adapter is the **same interface** (:class:`core.voyager.ports.EnvironmentPort`),
and each brings three things: the facts, the closed vocabulary of
primitives, and the ground truth. The core never imports a world's own
module.
"""

from __future__ import annotations

__all__ = ["minecraft", "crafter", "vibesandbox", "bevy"]
