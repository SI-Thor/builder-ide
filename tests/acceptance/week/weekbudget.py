"""The week's budget, from the cost model — plan item 14's arithmetic.

The brief for the honest week: *seven nights against the integrated core
with a real render behind the rungs — keep each night small enough that
the week runs in under ~2 hours of wall time; budget from the cost
model.* This module is that budget: the jobs each night runs, priced from
`core.night.cost`'s measured bands (the p95 end — the model's own rule is
to build a plan against the bad run), the admission check against the
night's rails, and the two lines the owner reads. After the week, the
same bands sit beside what the ledger says the renders actually cost —
the estimate is never quietly replaced by the measurement; both stand in
the table, and the gap between them is a finding about the band, not
about the night.

What one night of this week costs, in jobs:

* the **world bet's render** — one rung-2 preview of the night's edit
  (960×540, 16 spp; `render_job` through the engine seam);
* the **work order's preview** — the landed order's evidence render, the
  same rung through the same seam;
* the **scripted critic's verdict** — one write; the model has it
  measured at ~21 µs, and it is priced here to say so.

The band behind the render jobs is `rung.2`, whose 33 samples are the
seed sweep's render stages — *scene* renders, not object renders. The
honest-week run measures that gap (its object renders come in far under
the band); the band stays the estimate until object-render samples are
recorded, and the table names the basis rather than smoothing it over.
"""

from __future__ import annotations

from core.night.cost.admission import NightPlan, PlannedJob, admission_check
from core.night.cost.estimates import OwnerEstimate, owner_estimate
from core.night.cost.model import CostModel, get_model
from core.night.models import Rail

from script import NightSpec

__all__ = [
    "QUANTILE",
    "RAILS",
    "WEEK_WALL_BUDGET_MIN",
    "fold_renders",
    "night_plan",
    "night_rows",
    "render_budget_table",
    "week_estimate",
    "week_plan",
]

#: The week's rails — the melt driver's own (generous on purpose: the
#: week's cuts are the decision budget's at the queue, never the GPU bar's).
RAILS = Rail(gpu_minutes=130.0, hosted_cents=0, wall_minutes=420.0)

#: The brief's wall budget for the whole week: seven nights, under ~2 h.
WEEK_WALL_BUDGET_MIN = 120.0

#: Which end of the measured band an ask is taken from — the p95, because
#: the plan should be built against the bad run (the model's own rule).
QUANTILE = "p95"


def _ask(band, quantile: str = QUANTILE) -> Rail:
    end = getattr(band, quantile)
    return Rail(gpu_minutes=end.gpu_minutes, hosted_cents=0,
                wall_minutes=end.wall_minutes)


def night_plan(spec_night: NightSpec, *, model: CostModel | None = None,
               quantile: str = QUANTILE) -> NightPlan:
    """One night's plan: the jobs it runs, priced from the measured model."""
    model = model or get_model()
    n = spec_night.n
    rung2 = _ask(model.rung(2), quantile)
    return NightPlan(jobs=[
        PlannedJob(
            id=f"n{n}-bet-render",
            intention=(f"N{n} · the world bet's render "
                       f"({spec_night.world_bet.code})"),
            ask=rung2, kind="rung.2"),
        PlannedJob(
            id=f"n{n}-wo-preview",
            intention=f"N{n} · the work order's preview render",
            ask=rung2, kind="rung.2"),
        PlannedJob(
            id=f"n{n}-critic-verdict",
            intention=f"N{n} · the scripted critic's verdict",
            ask=_ask(model.critic_verdict(), quantile), kind="critic.verdict"),
    ])


def week_plan(nights, *, model: CostModel | None = None,
              quantile: str = QUANTILE) -> list[NightPlan]:
    """The seven nights' plans, in order."""
    return [night_plan(spec_night, model=model, quantile=quantile)
            for spec_night in nights]


def week_estimate(nights, *, rails: Rail = RAILS,
                  model: CostModel | None = None,
                  quantile: str = QUANTILE) -> list[OwnerEstimate]:
    """The owner's two lines, one per night (the unit the product budgets)."""
    model = model or get_model()
    out = []
    for spec_night in nights:
        plan = night_plan(spec_night, model=model, quantile=quantile)
        out.append(owner_estimate(plan, rails, model=model))
    return out


def fits(nights, *, rails: Rail = RAILS, model: CostModel | None = None,
         quantile: str = QUANTILE) -> list[bool]:
    """The admission check, per night: does the plan fit the rails?"""
    model = model or get_model()
    return [
        admission_check(night_plan(s, model=model, quantile=quantile),
                        rails).fits
        for s in nights
    ]


# --------------------------------------------------------------- the fold


def fold_renders(door) -> dict[str | None, list[dict]]:
    """Every `render.completed` in the ledger, grouped by its night.

    The join is job_id → the `job.enqueued` that carries the night id —
    the fold never trusts the driver's own bookkeeping (the melt's rule).
    """
    night_of = {e.payload["job_id"]: e.payload.get("night")
                for e in door.raw_events(0, ["job.enqueued"])}
    renders: dict[str | None, list[dict]] = {}
    for ev in door.raw_events(0, ["render.completed"]):
        payload = ev.payload
        renders.setdefault(night_of.get(payload.get("job_id")), []).append({
            "job_id": payload.get("job_id"),
            "wall_ms": payload.get("wall_ms"),
            "bytes": (payload.get("artifact") or {}).get("bytes"),
            "rung": payload.get("rung"),
            "seed": payload.get("seed"),
            "engine": payload.get("engine_flavour"),
        })
    return renders


def night_rows(world, steps) -> list[dict]:
    """One row per night: what ran, what was cut, the estimate beside the
    measured cost, the renders, and the melt's own columns.

    The estimate is the plan's p95 ask (this module); the measured is the
    ledger's render walls plus the preview wall the door recorded — the
    night's own bar, not a transcribed number. `steps` is the session's
    step list (meltweek leaves it on `world.artifacts["steps"]`).
    """
    records = world.week["nights"]
    renders = fold_renders(world.door)
    rows = []
    for rec in records:
        n = rec["n"]
        spec_renders = renders.get(rec.get("night"), [])
        bet_ms = next((r["wall_ms"] for r in spec_renders if r["wall_ms"]), None)
        preview_ms = rec.get("preview_wall_ms")
        walls = [w for w in (bet_ms, preview_ms) if w]
        measured_gpu = sum(walls) / 60000.0
        night_wall_s = sum(s.elapsed_s for s in steps
                           if s.act == "night" and s.name.startswith(f"n{n}-"))
        rows.append({
            "n": n,
            "date": rec.get("date", ""),
            "renders": [
                {"what": "the world bet's render",
                 "wall_ms": bet_ms, "bytes": next(
                     (r["bytes"] for r in spec_renders if r["wall_ms"]), None)},
                {"what": "the work order's preview",
                 "wall_ms": preview_ms, "bytes": None},
            ],
            "render_count": len(walls),
            "measured_gpu_minutes": measured_gpu,
            "night_wall_seconds": night_wall_s,
            "critic_verdict_ms": rec.get("critic_verdict_ms"),
            "cut_tasks": rec.get("cut_tasks", 0),
            "status": rec.get("status", ""),
            "questions": rec.get("questions", 0),
            "decisions": rec.get("decisions", 0),
            "attention": rec.get("attention", 0),
        })
    return rows


def render_budget_table(world, steps, nights, *, rails: Rail = RAILS,
                        model: CostModel | None = None,
                        quantile: str = QUANTILE) -> str:
    """The honest week's per-night table: what ran, the cut, cost vs
    estimate, the real renders — and the melt's columns beside them."""
    model = model or get_model()
    estimates = week_estimate(nights, rails=rails, model=model, quantile=quantile)
    checks = fits(nights, rails=rails, model=model, quantile=quantile)
    rows = night_rows(world, steps)
    head = (f"{'NIGHT':<7}{'WHAT RAN':<34}{'CUT':>4}  {'EST GPU-MIN':>11} "
            f"{'MEAS GPU-MIN':>12}  {'RENDERS':<24}{'STATUS':<13}{'DEC':>4}{'ATT':>4}")
    lines = [head, "-" * len(head)]
    for row, est, fits_n in zip(rows, estimates, checks):
        ran = "bet render + preview, rung 2"
        renders = " + ".join(
            _ms(r["wall_ms"]) for r in row["renders"]) or "none"
        lines.append(
            f"N{row['n']:<6}{ran:<34}{row['cut_tasks']:>4}  "
            f"{est.ask.gpu_minutes:>11.2f} {row['measured_gpu_minutes']:>12.3f}  "
            f"{renders:<24}{row['status']:<13}"
            f"{row['decisions']:>4}{row['attention']:>4}")
    total_est = sum(e.ask.gpu_minutes for e in estimates)
    total_meas = sum(r["measured_gpu_minutes"] for r in rows)
    total_renders = sum(r["render_count"] for r in rows)
    night_wall = sum(r["night_wall_seconds"] for r in rows)
    lines.append("-" * len(head))
    lines.append(
        f"{'the week':<7}{total_renders} real renders · every plan fit its rails "
        f"({all(checks)}) · est {total_est:.2f} GPU-min · meas {total_meas:.3f} "
        f"GPU-min · the nights' steps {night_wall:.1f} s")
    lines.append("")
    lines.append("the two lines each evening (the cost model's p95 asks):")
    for row, est in zip(rows, estimates):
        lines.append(f"  N{row['n']}: {est.line_one}")
        lines.append(f"      {est.line_two}")
    return "\n".join(lines)


def _ms(value) -> str:
    if value is None:
        return "—"
    return f"{value / 1000.0:.1f} s"
