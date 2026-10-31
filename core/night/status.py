"""The status line — computed from the ledger, never narrated (§3.4).

The four values are the spec's: ``ran as planned``, ``ran short``,
``ran degraded``, ``did not run``. The last one has three variants, because
from the owner's chair they are three different facts — **off**, **busy** and
**no plan**. Dark ≠ asleep ≠ busy, stated in words under the picture, never
colour alone (X G5).

Nothing here is written by the night runner; it is read out of the log. That
is the whole point: a status line that survives the failure it describes
(§3.4, §5.4).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.night.heartbeat import TICK_INTERVAL_MINUTES, lost_minutes
from core.night.models import NightStatus
from core.night.projection import NightProjection

__all__ = ["StatusLine", "compute_status", "STATUS_VALUES"]

#: The only four statuses the morning may say (§3.4).
STATUS_VALUES = ("ran as planned", "ran short", "ran degraded", "did not run")

OFF_REASON = (
    "the Thor was off. Nothing ran; nothing was lost. Your plan is unstarted, unchanged."
)
BUSY_REASON = "the GPU spent the night on your render job. Ours queued and was never admitted."
NO_PLAN_REASON = "no plan was started."
UNKNOWN_REASON = "unknown (no telemetry)"


class StatusLine(BaseModel):
    """The computed status: the value, its variant and its one-line reason."""

    status: NightStatus
    variant: str | None = None
    reason: str = ""
    detail: list[str] = Field(default_factory=list)

    @property
    def first_line(self) -> str:
        """The morning's first line (§3.2.8 item 1)."""
        if self.status == "ran as planned":
            return f"{self.status} · {self.reason}"
        return f"{self.status} — {self.reason}"


def compute_status(
    projection: NightProjection, *, expected_interval_minutes: int = TICK_INTERVAL_MINUTES
) -> StatusLine:
    """Read the night's status out of the log."""
    if projection.night is None:
        if projection.tasks:
            return StatusLine(status="did not run", variant="off", reason=OFF_REASON)
        return StatusLine(status="did not run", variant="no plan", reason=NO_PLAN_REASON)

    if not projection.ticks:
        # Telemetry was blind: say so, never guess (§3.2.2).
        return StatusLine(status="did not run", variant="unknown", reason=UNKNOWN_REASON)

    ran = [
        task
        for task in projection.tasks.values()
        if task.state in ("running", "kept", "reverted")
    ]
    preflight = projection.preflight or {}
    if not ran and preflight.get("lane_free") is False:
        return StatusLine(status="did not run", variant="busy", reason=BUSY_REASON)

    cut = [task for task in projection.tasks.values() if task.state == "cut"]
    failures = projection.failures
    lost = lost_minutes(
        projection.ticks, expected_interval_minutes=expected_interval_minutes
    )

    short_clauses: list[str] = []
    if cut:
        minutes = sum(task.cost_estimate.gpu_minutes for task in cut)
        bar = projection.threshold_pct or 80
        name = cut[0].intention
        short_clauses.append(
            f"{minutes / 60:.1f} lane-h of the ask was cut at the {bar}% bar; "
            f"{name} is re-queued for tonight"
        )
    if failures:
        count = len(failures)
        first = failures[0].get("reason", "no reason recorded")
        short_clauses.append(f"{count} task{'s' if count > 1 else ''} failed: {first}")
    if lost > 0:
        short_clauses.append(f"{lost:.0f} min lost to a reboot")
    if short_clauses:
        return StatusLine(status="ran short", reason=" · ".join(short_clauses))

    degraded_clauses: list[str] = []
    if projection.stall_minutes > 0:
        degraded_clauses.append(
            f"one batch stalled {projection.stall_minutes:.0f} min on the lane"
        )
    batches = projection.batches or {}
    if batches.get("trigger") == "deadline":
        cause = batches.get("cause") or "the client never detached"
        degraded_clauses.append(
            f"{cause} — the deadline started the batches {projection.late_minutes:.0f} min late"
        )
    if projection.degraded_verdicts:
        count = projection.degraded_verdicts
        degraded_clauses.append(
            f"{count} verdict{'s' if count > 1 else ''} ran scripted-only — see their cards"
        )
    if degraded_clauses:
        if not failures:
            degraded_clauses.append("nothing failed outright")
        return StatusLine(status="ran degraded", reason=" · ".join(degraded_clauses))

    parked = len(projection.tasks_in_state("parked"))
    reason = "nothing failed"
    if parked:
        reason = f"{reason} · {parked} parked"
    return StatusLine(status="ran as planned", reason=reason)
