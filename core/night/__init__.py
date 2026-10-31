"""The night runner and the morning report (core-spec v2 §3.2, §3.4, §5).

The night is the part of the product where nobody is watching. This package
is the night's own logic — the task queue, the rails, the heartbeat, the
detach-or-timeout rule, the boot sequence after a restart, and the morning
report page that reads all of it back.

Three ideas hold it together:

* **everything is a fold over the audit log.** The status line, the cut, the
  tally and the report are computed from the rows, never narrated by whoever
  is awake to write them — which is what makes them survive the failure they
  describe (§3.4, §5.4);
* **admission is before spend.** A task the rail cannot cover is cut with its
  reason attached, not started and killed (§5.5);
* **the work is behind a seam.** In this seat the work is simulated —
  scripted tasks with injected failures — and the engine and the GPU
  stations will implement the same two methods.

And a fourth, newer: **a task is no longer one attempt.** The night
generates variants, scores them, keeps the best and refines from it; the
variants, the critic and the power meter are seams of their own.

The public surface:

    from core.night import NightRunner, ScriptedExecutor, build_report

    runner = NightRunner(ledger, executor, night_id=night_id, rails=rails, clock=clock)
    runner.start(tasks)
    runner.run()
    runner.stop()                       # the status, computed from the log
    write_report(build_report(ledger.events()), Path("reports/"))

With a critic and a variant source, the tasks iterate:

    from core.night import ScriptedCritic, ScriptedVariantSource

    runner = NightRunner(
        ledger, executor, night_id=night_id, rails=rails, clock=clock,
        variant_source=ScriptedVariantSource(scripts),
        critic=ScriptedCritic(scores),
    )
"""

from __future__ import annotations

from core.night.clock import Clock, ScriptedClock, SystemClock
from core.night.cost import (
    AdmissionCheck,
    CostBand,
    CostEstimate,
    CostModel,
    NightPlan,
    OwnerEstimate,
    PlannedJob,
    admission_check,
    get_model,
    owner_estimate,
)
from core.night.executor import (
    ExecutionPlan,
    ScriptedExecutor,
    ScriptedTask,
    TaskExecutor,
)
from core.night.heartbeat import Heartbeat, lost_minutes, tick_gaps
from core.night.iterate import (
    Critic,
    CriticScore,
    NullPowerMeter,
    PerturbationSource,
    PowerMeter,
    RailPowerMeter,
    ScriptedCritic,
    ScriptedVariantSource,
    Variant,
    VariantSource,
)
from core.night.ledger import InMemoryLedger, Ledger, SQLiteLedger
from core.night.models import Actor, AuditEvent, IterationPolicy, Job, Night, Rail, Task
from core.night.projection import NightProjection
from core.night.queue import TaskQueue
from core.night.rails import BudgetExceeded, LoadBudget, RailBudget, ThrottleLevel
from core.night.report import (
    NightReport,
    build_report,
    render_html,
    render_text,
    write_report,
)
from core.night.resume import RecoveryOutcome, boot, recover
from core.night.runner import NightRunner
from core.night.status import StatusLine, compute_status

__all__ = [
    "Actor",
    "AdmissionCheck",
    "AuditEvent",
    "BudgetExceeded",
    "Clock",
    "CostBand",
    "CostEstimate",
    "CostModel",
    "Critic",
    "CriticScore",
    "ExecutionPlan",
    "Heartbeat",
    "InMemoryLedger",
    "IterationPolicy",
    "Job",
    "Ledger",
    "LoadBudget",
    "Night",
    "NightPlan",
    "NightProjection",
    "NightReport",
    "NightRunner",
    "NullPowerMeter",
    "OwnerEstimate",
    "PerturbationSource",
    "PlannedJob",
    "PowerMeter",
    "Rail",
    "RailBudget",
    "RailPowerMeter",
    "RecoveryOutcome",
    "SQLiteLedger",
    "ScriptedClock",
    "ScriptedCritic",
    "ScriptedExecutor",
    "ScriptedTask",
    "ScriptedVariantSource",
    "StatusLine",
    "SystemClock",
    "Task",
    "TaskExecutor",
    "TaskQueue",
    "ThrottleLevel",
    "Variant",
    "VariantSource",
    "admission_check",
    "boot",
    "build_report",
    "compute_status",
    "get_model",
    "lost_minutes",
    "owner_estimate",
    "recover",
    "render_html",
    "render_text",
    "tick_gaps",
    "write_report",
]
