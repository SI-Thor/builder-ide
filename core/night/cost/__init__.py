"""The night's arithmetic — the measured cost table, and the plan's admission.

This package turns the box's recorded numbers into the three things the
night needs before it spends anything:

* a **cost model** (:class:`~core.night.cost.model.CostModel`) — what each
  job kind costs, per job kind, with p50 and p95 from the recorded samples,
  in GPU-minutes, CPU-lane minutes, wall minutes, hosted cents, iterations
  and joules;
* an **admission check**
  (:func:`~core.night.cost.admission.admission_check`) — does tonight's plan
  fit the rails, and what is cut, named;
* the **two-line estimate**
  (:func:`~core.night.cost.estimates.owner_estimate`) — what the owner reads
  this evening, in two lines;
* a **price** (:func:`~core.night.cost.pricing.price_job`) — what one job
  kind costs as a task carries it: the ask (the p50) and the rail (the p95),
  with the band's basis and source beside them.

Everything the model says comes from a measurement with a source beside it
(:mod:`core.night.cost.records`). The one exception is the owner's attention
per decision, which nobody has measured yet; it is marked an estimate and
stays marked.

See ``core/night/cost/README.md`` for the numbers, their sources and how to
re-derive them.
"""

from __future__ import annotations

from core.night.cost.admission import (
    AdmissionCheck,
    CutLine,
    NightPlan,
    PlannedJob,
    admission_check,
    plan_from_asks,
)
from core.night.cost.estimates import OwnerEstimate, owner_estimate
from core.night.cost.model import CostBand, CostEstimate, CostModel, get_model, percentile
from core.night.cost.pricing import (
    DEFAULT_KIND,
    PricedAsk,
    hold_to,
    known_kinds,
    price_job,
)
from core.night.cost.records import (
    DATA_DIR,
    JobRecord,
    PowerRails,
    RecordedData,
    Sample,
    load_recorded,
)

__all__ = [
    "AdmissionCheck",
    "CostBand",
    "CostEstimate",
    "CostModel",
    "CutLine",
    "DATA_DIR",
    "DEFAULT_KIND",
    "JobRecord",
    "NightPlan",
    "OwnerEstimate",
    "PlannedJob",
    "PowerRails",
    "PricedAsk",
    "RecordedData",
    "Sample",
    "admission_check",
    "get_model",
    "hold_to",
    "known_kinds",
    "load_recorded",
    "owner_estimate",
    "percentile",
    "plan_from_asks",
    "price_job",
]
