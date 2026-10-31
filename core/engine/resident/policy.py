"""The resident's policy — the four dials the brief names.

* **health checks** — is the resident still there, and is it answering? A
  resident that has died or stopped answering is not "slow"; it is gone, and
  the adapter's job is to notice and rebuild it;
* **a restart policy** — how many times a resident may be restarted before
  the adapter gives up and says so, and how long it waits between attempts
  (a crash loop must not become a spin loop);
* **a checkpoint cadence** — how often the durable recipe is snapshotted and
  anchored, in edits and in seconds;
* **memory-growth guards** — how much a resident may grow above its loaded
  baseline before it is recycled.

The last one is the spike's finding made operational (WS §5.1, §5.5): a
resident process accumulates orphan datablocks that a batch run never has to
think about, because Blender collects them at save time and a resident never
saves. The guard is the watchdog for that: it watches the resident's RSS and
recycles the process when it has grown past the bound. The bound is measured
against the baseline taken **after the scene was loaded**, so a big scene is
not mistaken for a leak.

Every default here is a *bound*, not a hope: the values are small enough that
a runaway resident is caught in seconds rather than at the end of the night.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["ResidentPolicy"]


class ResidentPolicy(BaseModel):
    """How the adapter treats the resident process."""

    # -- health ------------------------------------------------------------

    #: How long a single RPC may take before the resident is declared hung.
    request_timeout_s: float = Field(default=60.0, gt=0)
    #: How often the adapter pings the resident when it is otherwise idle.
    health_check_interval_s: float = Field(default=30.0, gt=0)
    #: How long the resident may take to come up (a cold ``import bpy`` is
    #: ~0.25 s; a real engine's first stage is much more).
    start_timeout_s: float = Field(default=180.0, gt=0)

    # -- the restart policy ------------------------------------------------

    #: How many times the resident may be restarted before the adapter stops
    #: and reports the failure. A crash loop must end in an honest error,
    #: never in an infinite rebuild.
    max_restarts: int = Field(default=3, ge=0)
    #: The wait before the first restart; it doubles after each failure up to
    #: the cap, so a resident that dies on start-up is not restarted in a
    #: tight loop.
    restart_backoff_s: float = Field(default=0.5, ge=0)
    restart_backoff_cap_s: float = Field(default=8.0, gt=0)

    # -- the checkpoint cadence --------------------------------------------

    #: Snapshot and anchor after this many applied edits.
    checkpoint_every_ops: int = Field(default=25, ge=1)
    #: …and after this many seconds, whichever comes first.
    checkpoint_every_s: float = Field(default=60.0, gt=0)

    # -- the memory-growth guard -------------------------------------------

    #: How far the resident's RSS may grow above its loaded baseline before
    #: it is recycled. 512 MiB is roughly one Hello Room render's worth of
    #: allocator high-water (WS §4.3) — enough for a real night, small
    #: enough to catch an orphan-datablock leak (WS §4.5).
    max_growth_mb: float = Field(default=512.0, ge=0)
    #: How often the guard samples the resident's RSS, in edits.
    growth_check_every_ops: int = Field(default=10, ge=1)

    # -- the resident's own lifetime ---------------------------------------

    #: Recycle the resident after this long, even when it is healthy: a
    #: long-lived process accumulates allocator high-water, and a fresh one
    #: is a known quantity. ``None`` means "keep it".
    max_uptime_s: float | None = Field(default=None, gt=0)

    def backoff_for(self, attempt: int) -> float:
        """The wait before restart number ``attempt`` (1-based)."""
        if attempt <= 1:
            return self.restart_backoff_s
        delay = self.restart_backoff_s * (2 ** (attempt - 1))
        return min(delay, self.restart_backoff_cap_s)
