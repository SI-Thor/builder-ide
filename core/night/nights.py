"""The simulated nights — the four mornings, and the neighbours.

The work is simulated here (scripted fake tasks with injected failures), not
real renders. What is *not* simulated is the night's own logic: the queue,
the rails, the heartbeat, the detach rule, the boot sequence and the report
are the real code, running against a scripted world.

Each scenario returns a :class:`SimulatedNight`: the log, the computed
status and the report — the three things the morning is made of.

The scenarios cover every morning the product can wake up to:

* **clean** — the night of §3.2, as planned;
* **failures** — a batch came back hollow; the night was short;
* **rail cut** — the ask did not fit under the bar; the cut is named;
* **reboot** — the box went dark mid-night and came back;
* **degraded** — the ProArt never detached and a batch stalled on the lane;
* **did not run** — in its four variants: the box was off, the GPU was busy
  with somebody else's job, there was no plan, and the telemetry was blind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.ledger import InMemoryLedger, Ledger
from core.night.models import Actor, AuditEvent, Rail, Task
from core.night.report import NightReport, build_report, render_html, render_text
from core.night.resume import recover
from core.night.runner import NightRunner
from core.night.status import StatusLine

__all__ = [
    "SimulatedNight",
    "all_mornings",
    "clean_night",
    "degraded_night",
    "did_not_run_night",
    "failures_night",
    "rail_cut_night",
    "reboot_night",
    "the_four_mornings",
]

NIGHT_ID = "night_2026-10-30"
NIGHT_START = "2026-10-30T21:14:00Z"
RAILS = Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0)

_SCHEDULER = Actor(kind="scheduler", id="night-runner")


@dataclass(frozen=True)
class SimulatedNight:
    """One simulated night and the morning it produced."""

    name: str
    events: list[AuditEvent]
    status: StatusLine
    report: NightReport

    def html(self) -> str:
        return render_html(self.report)

    def text(self) -> str:
        return render_text(self.report)


def _task(task_id: str, intention: str, gpu: float, wall: float) -> Task:
    return Task(
        id=task_id,
        intention=intention,
        owner_character="prop-maker",
        cost_estimate=Rail(gpu_minutes=gpu, hosted_cents=0, wall_minutes=wall),
        rail=Rail(gpu_minutes=gpu + 10.0, hosted_cents=0, wall_minutes=wall + 15.0),
    )


def _slate(ledger: Ledger, tasks: Sequence[Task]) -> None:
    """Write the plan slate — tasks before any night (RV patch 11)."""
    for task in tasks:
        ledger.append(
            type="night.task.created",
            actor=_SCHEDULER,
            subject={"entity_kind": "task", "entity_id": task.id},
            payload={"task": {**task.model_dump(), "night": None, "state": "slated"}},
            at=NIGHT_START,
        )


def _finish(name: str, ledger: Ledger) -> SimulatedNight:
    events = ledger.events()
    report = build_report(events)
    return SimulatedNight(name=name, events=events, status=report.status, report=report)


# -- the scenarios ---------------------------------------------------------


def clean_night() -> SimulatedNight:
    """The night of §3.2: two small bets, both kept, one question parked."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                model="trellis2",
                predictions=[
                    {
                        "prediction_id": "pr_0001",
                        "builder": "prop-maker",
                        "claim_type": "shadow_count",
                        "claim": "the crates will read weathered",
                        "confidence": "guess",
                        "basis": "0 observations",
                    },
                    {
                        "prediction_id": "pr_0002",
                        "builder": "prop-maker",
                        "claim_type": "material_read",
                        "claim": "the lids will read as oak",
                        "confidence": "guess",
                        "basis": "0 observations",
                    },
                ],
                verdicts=[
                    {"prediction_id": "pr_0001", "verdict": "hit"},
                    {"prediction_id": "pr_0002", "verdict": "miss"},
                ],
                branches=["br_07f2"],
            ),
            "task_0002": ScriptedTask(gpu_minutes=25.0, wall_minutes=40.0),
            "task_0003": ScriptedTask(
                gpu_minutes=10.0,
                wall_minutes=20.0,
                outcome="parked",
                reason="waiting on Casey: keep the oak?",
            ),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT_ID,
        rails=RAILS,
        clock=ScriptedClock(NIGHT_START),
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", 30.0, 45.0),
            _task("task_0002", "Rope the jetty", 25.0, 40.0),
            _task("task_0003", "Thin the east slope", 10.0, 20.0),
        ]
    )
    runner.run()
    runner.stop()
    return _finish("clean", ledger)


def failures_night() -> SimulatedNight:
    """A batch came back hollow; the night was short and says so."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                model="trellis2",
                outcome="failed",
                reason="hollow mesh from the image-to-3D model",
                artifact="artifacts/ab/ab1234.png",
            ),
            "task_0002": ScriptedTask(gpu_minutes=25.0, wall_minutes=40.0),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", 30.0, 45.0),
            _task("task_0002", "Rope the jetty", 25.0, 40.0),
        ]
    )
    runner.run()
    runner.stop()
    return _finish("failures", ledger)


def rail_cut_night() -> SimulatedNight:
    """The ask did not fit under the bar; the cut is named, not merely counted."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=300.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Light the north lantern", 300.0, 45.0),
            _task("task_0002", "Rope the jetty", 30.0, 45.0),
        ]
    )
    runner.run()
    runner.stop()
    return _finish("rail cut", ledger)


class _CrashingExecutor(ScriptedExecutor):
    """The box goes dark once, in the middle of the night."""

    def __init__(self, scripts=None) -> None:
        super().__init__(scripts)
        self.crashed = False

    def run(self, task, variant=None):
        if task.id == "task_0002" and not self.crashed:
            self.crashed = True
            raise RuntimeError("the box rebooted")
        return super().run(task, variant)


def reboot_night() -> SimulatedNight:
    """The box reboots mid-night; the night resumes and names the lost time."""
    ledger = InMemoryLedger()
    executor = _CrashingExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", 30.0, 45.0),
            _task("task_0002", "Rope the jetty", 30.0, 45.0),
        ]
    )
    try:
        runner.run()
    except RuntimeError:
        pass  # the box went dark

    # An hour later the box is back: boot, recover, resume (§5.2).
    back_at = "2026-10-30T23:00:00Z"
    recover(ledger, executor, night_id=NIGHT_ID, clock=ScriptedClock(back_at))
    resumed = NightRunner.resume(
        ledger, executor, night_id=NIGHT_ID, clock=ScriptedClock(back_at)
    )
    resumed.run()
    resumed.stop()
    return _finish("reboot", ledger)


def degraded_night() -> SimulatedNight:
    """The ProArt never detached and a batch stalled on the lane."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                model="trellis2",
                stall_minutes=41.0,
                stall_reason="model-load cap hit",
            ),
            "task_0002": ScriptedTask(gpu_minutes=25.0, wall_minutes=40.0),
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT_ID,
        rails=RAILS,
        clock=ScriptedClock(NIGHT_START),
        presence=lambda now: "attached",  # the ProArt never closed
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", 30.0, 45.0),
            _task("task_0002", "Rope the jetty", 25.0, 40.0),
        ]
    )
    runner.run()
    runner.stop()
    return _finish("degraded", ledger)


def did_not_run_night(variant: str = "off") -> SimulatedNight:
    """The four ways a morning can say "did not run".

    From the owner's chair they are four different facts: the box was
    **off**, the GPU was **busy** with somebody else's job, there was **no
    plan**, or the **telemetry was blind** — and a status line may be
    uncertain, never fabricated (§3.4).
    """
    if variant == "no plan":
        ledger = InMemoryLedger()
        return _finish("did not run (no plan)", ledger)

    if variant == "unknown":
        # The night started and the telemetry went blind: say so, never guess.
        ledger = InMemoryLedger()
        ledger.append(
            type="night.started",
            actor=_SCHEDULER,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload={
                "night_id": NIGHT_ID,
                "rails": RAILS.model_dump(),
                "load_budget": {"trellis2": 1},
                "power_mode": 0,
                "batch_start": "both",
                "detach_deadline": "2026-10-30T21:44:00Z",
            },
            at=NIGHT_START,
        )
        return _finish("did not run (unknown)", ledger)

    if variant == "busy":
        # A foreign job holds the GPU all night: ours queues and is never
        # admitted.
        ledger = InMemoryLedger()
        executor = ScriptedExecutor(
            {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
        )
        runner = NightRunner(
            ledger,
            executor,
            night_id=NIGHT_ID,
            rails=RAILS,
            clock=ScriptedClock(NIGHT_START),
            lane_free=lambda now: False,  # somebody else's render job
        )
        runner.start([_task("task_0001", "Weather the harbour crates", 30.0, 45.0)])
        runner.run()
        runner.stop()
        return _finish("did not run (busy)", ledger)

    # "off": the plan is on the slate and the box never woke up.
    ledger = InMemoryLedger()
    _slate(ledger, [_task("task_0001", "Weather the harbour crates", 30.0, 45.0)])
    return _finish("did not run (off)", ledger)


def the_four_mornings() -> list[SimulatedNight]:
    """One morning per status value — the spec's four."""
    return [clean_night(), failures_night(), degraded_night(), did_not_run_night("off")]


def all_mornings() -> list[SimulatedNight]:
    """Every morning the product can wake up to."""
    return [
        clean_night(),
        failures_night(),
        rail_cut_night(),
        reboot_night(),
        degraded_night(),
        did_not_run_night("off"),
        did_not_run_night("busy"),
        did_not_run_night("no plan"),
        did_not_run_night("unknown"),
    ]
