"""The spine's half of the gc wiring: the seam the night runner calls, and
the reputation rows the morning report reads.

`gc` (tools/gc) is the general contractor: it holds a subcontractor to its
bid and it stops the seat at 80% of that bid when the goal line has not
passed. This module is the builder-ide side of that conversation.

**Two things live here.**

* :class:`GcNightSeam` — the seam the night runner talks to. The night
  seat must not know about gc (it is a separate half of the codebase), so
  it asks two questions: *which contracts does this task carry?* and *here
  is the burn so far*. This class answers both, reading builder-ide's own
  ledger and calling the bridge.
* :func:`reputation_rows` — the rows the read API and the morning report
  show. Every number in them is gc's: the bridge asks gc for
  ``report --json`` and this shapes the answer. Nothing is recomputed in
  Python, because a rate gc did not measure must not be invented here.

**What it stubs**: nothing gc owns. The burn ratio, the stop line, the
verdict and the reputation score are all gc's; this module only carries
builder-ide's ids across the boundary and reads gc's numbers back.

**How it connects to the rest**: `core.svc.work_orders` opens the contracts
(a confirmed work order is a gc job), `core.night.runner` calls the seam
(the burn is checkpointed; gc's stop line cuts the task), `core.svc.report`
closes the contracts at the morning, and `core.api` reads the reputation
back over HTTP.

**How to run its tests**

    /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
        -p no:cacheprovider tests/test_gc_integration.py

The suite is green with or without the gc binary: the end-to-end walk skips
with a stated reason when gc is not on the box.
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger("core.svc.gc_night")

#: The work order states that still carry a contract. A parked, landed or
#: cancelled order is not burning against its bid any more.
OPEN_ORDER_STATES = ("queued", "building", "testing")

__all__ = ["GcNightSeam", "reputation_rows"]


class GcNightSeam:
    """The night runner's window onto the general contractor.

    The runner asks which contracts a task carries and reports the burn; it
    never sees gc. Every method here fails open: a missing bridge, an
    unreadable ledger or a failing gc returns an empty answer, and the night
    carries on as if gc were not there.
    """

    def __init__(self, core) -> None:
        self.core = core

    # ------------------------------------------------------------- the seam

    def contracts_for(self, task_id: str) -> list[dict]:
        """The open gc contracts for a task.

        A work order names the plan goal it serves (``serves``); that link
        is what the night half finds the contract by. The seat is the order's
        latest attempt's engineer — the seat gc holds to its bid — and is
        empty when no attempt has started yet.
        """
        try:
            rows = self.core.store.scan("work_orders")
        except Exception:  # pragma: no cover - the ledger must not break the night
            _LOG.warning("the work orders could not be read; no gc contract is reported")
            return []
        out: list[dict] = []
        for row in rows:
            if row.get("state") not in OPEN_ORDER_STATES:
                continue
            payload = row.get("payload") or {}
            if payload.get("serves") != task_id:
                continue
            attempts = payload.get("attempts") or []
            seat = ""
            if attempts:
                seat = attempts[-1].get("engineer") or ""
            out.append({
                "external_id": row.get("id") or payload.get("id"),
                "seat": seat,
            })
        return out

    def checkpoint(self, *, external_id: str, crew_used_min: float) -> dict | None:
        """Report the burn to gc and hand back gc's checkpoint body.

        The body carries ``stop_required`` and gc's own verdict on the goal
        line. None means gc is not here or the call failed — the night then
        carries on.
        """
        bridge = getattr(self.core, "gc", None)
        if bridge is None:
            return None
        try:
            return bridge.checkpoint(external_id=external_id, crew_used_min=crew_used_min)
        except Exception:  # pragma: no cover - the bridge must not break the night
            _LOG.warning("the gc checkpoint for %s failed; the night carries on", external_id)
            return None


# ------------------------------------------------------------- the reputation

def reputation_rows(
    core,
    *,
    seat: str | None = None,
    job_class: str | None = None,
) -> list[dict]:
    """The reputation rows, read out of gc's own report.

    With a seat, gc is asked for that seat's rows; with a class, the rows
    are filtered by it. The numbers are gc's: ``on_time_rate``,
    ``goal_line_rate``, ``budget_hit_rate`` (the inside-bid rate), the debt
    and the reputation score are all copied out of gc's ``report --json``.

    When gc has no record of a deadline for the pair, ``on_time`` is None and
    ``on_time_known`` is False: "unknown", never a flattering 0 %.
    """
    bridge = getattr(core, "gc", None)
    if bridge is None:
        return []
    try:
        payload = bridge.reputation(seat, job_class)
    except Exception:  # pragma: no cover - the bridge must not break the reader
        _LOG.warning("gc's reputation could not be read; the rows are empty")
        return []
    if payload is None:
        return []
    raw_rows = payload if isinstance(payload, list) else payload.get("seats") or []
    rows: list[dict] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        if seat and raw.get("sub") != seat:
            continue
        if job_class and raw.get("class") != job_class:
            continue
        rows.append(_shape_row(raw))
    return rows


def _shape_row(raw: dict) -> dict:
    """One seat row, in builder-ide's shape.

    Every value comes from gc. The only thing added here is the sentence:
    it is built from the numbers that are actually there, so a seat with no
    retools is not credited with "0 retools" and a pair with no recorded
    deadline says "on time: unknown".
    """
    seat = str(raw.get("sub") or "")
    klass = str(raw.get("class") or "")
    known = bool(raw.get("on_time_known"))
    on_time = raw.get("on_time_jobs")
    on_time_total = raw.get("on_time_total")
    if not known or on_time_total is None:
        known = False
        on_time = None
        on_time_total = None
    retools = int(raw.get("retools") or 0)
    row = {
        "seat": seat,
        "class": klass,
        "jobs": int(raw.get("jobs") or 0),
        "on_time": int(on_time) if on_time is not None else None,
        "on_time_total": int(on_time_total) if on_time_total is not None else None,
        "on_time_rate": float(raw.get("on_time_rate") or 0.0),
        "on_time_known": known,
        "goal_line_rate": float(raw.get("goal_line_rate") or 0.0),
        "goal_line_inconclusive": int(raw.get("goal_line_inconclusive") or 0),
        "inside_bid_rate": float(raw.get("budget_hit_rate") or 0.0),
        "debt_min": float(raw.get("debt_min") or 0.0),
        "retools": retools,
        "reputation": float(raw.get("reputation") or 0.0),
        "blocked": bool(raw.get("blocked")),
        "line": _line(seat, on_time, on_time_total, known, retools),
    }
    return row


def _line(
    seat: str,
    on_time: int | None,
    on_time_total: int | None,
    known: bool,
    retools: int,
) -> str:
    """The sentence the morning and the panel read.

    Only what is true: the on-time count when there is a denominator, the
    honest "unknown" when there is not, and the retools when there are any.
    """
    if known and on_time_total:
        parts = [f"{on_time} of {on_time_total} on time"]
    else:
        parts = ["on time: unknown"]
    if retools:
        parts.append(f"{retools} retools")
    return f"{seat}: " + ", ".join(parts)
