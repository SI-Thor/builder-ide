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
from core.night.cost.model import get_model
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.iterate import (
    CriticScore,
    ScriptedCritic,
    ScriptedVariantSource,
    Variant,
)
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
    "iteration_night",
    "iteration_rail_cut_night",
    "iteration_stalled_night",
    "rail_cut_night",
    "reboot_night",
    "the_four_mornings",
]

NIGHT_ID = "night_2026-10-30"
NIGHT_START = "2026-10-30T21:14:00Z"

#: The night's rail — the spec's defaults (§5.5): 360 GPU-minutes, no hosted
#: cents, 560 wall-minutes. It comes from the cost model so the code and the
#: document cannot drift apart.
RAILS = get_model().default_night_rails()

_SCHEDULER = Actor(kind="scheduler", id="night-runner")

#: How many hero renders the rail-cut scenario's first task is. The count is
#: the scenario's, not a cost: the model prices each one.
HERO_RENDERS = 14


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


def _price(kind: str, *, count: int = 1, scene: str | None = None) -> Rail:
    """What the cost model says a job of this kind costs.

    The measured p50, times how many of them the night does. Nothing here is
    a number somebody typed: every ask in these scenarios comes from a
    recording on this box.
    """
    band = get_model().band(kind, scene=scene)
    estimate = band.p50
    return Rail(
        gpu_minutes=estimate.gpu_minutes * count,
        hosted_cents=estimate.hosted_cents * count,
        wall_minutes=estimate.wall_minutes * count,
    )


def _ceiling(kind: str, *, count: int = 1, scene: str | None = None) -> Rail:
    """The p95 of the same job — the most a task may spend before it is cut."""
    band = get_model().band(kind, scene=scene)
    estimate = band.p95
    return Rail(
        gpu_minutes=estimate.gpu_minutes * count,
        hosted_cents=estimate.hosted_cents * count,
        wall_minutes=estimate.wall_minutes * count,
    )


def _variant_price(kind: str, *, scene: str | None = None) -> Rail:
    """What one *variant* of a goal costs: the goal's price, split by its depth.

    A goal that tries three seeds tries each of them for the same work, so
    one variant is the goal's share.
    """
    band = get_model().band(kind, scene=scene)
    estimate = band.p50
    variants = max(1, estimate.iterations)
    return Rail(
        gpu_minutes=estimate.gpu_minutes / variants,
        hosted_cents=estimate.hosted_cents,
        wall_minutes=estimate.wall_minutes / variants,
    )


def _task(
    task_id: str,
    intention: str,
    kind: str,
    *,
    count: int = 1,
    scene: str | None = None,
) -> Task:
    """A task on the plan, asked at the model's measured price."""
    return Task(
        id=task_id,
        intention=intention,
        owner_character="prop-maker",
        cost_estimate=_price(kind, count=count, scene=scene),
        rail=_ceiling(kind, count=count, scene=scene),
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
    """The night of §3.2: two small bets, both kept, one question parked.

    The asks come from the cost model: a prop goal is what a picture, a
    3D prop and a verdict cost on this box, measured over the mini-night.
    """
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
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
            "task_0002": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
            "task_0003": ScriptedTask(
                gpu_minutes=_price("scene.goal", scene="plain").gpu_minutes,
                wall_minutes=_price("scene.goal", scene="plain").wall_minutes,
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
            _task("task_0001", "Weather the harbour crates", "prop.goal"),
            _task("task_0002", "Rope the jetty", "prop.goal"),
            _task("task_0003", "Thin the east slope", "scene.goal", scene="plain"),
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
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
                model="trellis2",
                outcome="failed",
                reason="hollow mesh from the image-to-3D model",
                artifact="artifacts/ab/ab1234.png",
            ),
            "task_0002": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", "prop.goal"),
            _task("task_0002", "Rope the jetty", "prop.goal"),
        ]
    )
    runner.run()
    runner.stop()
    return _finish("failures", ledger)


def rail_cut_night() -> SimulatedNight:
    """The ask did not fit under the bar; the cut is named, not merely counted.

    The first task is the night's hero renders — fourteen full renders, priced
    by the model at the Hello Room's measured 1307 s each. That is most of
    the 6.0 GPU-hour bar, so the night drains at the 80 % line and the second
    task is re-queued for another night.
    """
    ledger = InMemoryLedger()
    renders = _price("rung.3", count=HERO_RENDERS)
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=renders.gpu_minutes,
                wall_minutes=renders.wall_minutes,
            ),
            "task_0002": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Render the north lantern", "rung.3", count=HERO_RENDERS),
            _task("task_0002", "Rope the jetty", "prop.goal"),
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
            "task_0001": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
            "task_0002": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
        }
    )
    runner = NightRunner(
        ledger, executor, night_id=NIGHT_ID, rails=RAILS, clock=ScriptedClock(NIGHT_START)
    )
    runner.start(
        [
            _task("task_0001", "Weather the harbour crates", "prop.goal"),
            _task("task_0002", "Rope the jetty", "prop.goal"),
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
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
                model="trellis2",
                stall_minutes=41.0,
                stall_reason="model-load cap hit",
            ),
            "task_0002": ScriptedTask(
                gpu_minutes=_price("prop.goal").gpu_minutes,
                wall_minutes=_price("prop.goal").wall_minutes,
            ),
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
            _task("task_0001", "Weather the harbour crates", "prop.goal"),
            _task("task_0002", "Rope the jetty", "prop.goal"),
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
            {
                "task_0001": ScriptedTask(
                    gpu_minutes=_price("prop.goal").gpu_minutes,
                    wall_minutes=_price("prop.goal").wall_minutes,
                )
            }
        )
        runner = NightRunner(
            ledger,
            executor,
            night_id=NIGHT_ID,
            rails=RAILS,
            clock=ScriptedClock(NIGHT_START),
            lane_free=lambda now: False,  # somebody else's render job
        )
        runner.start([_task("task_0001", "Weather the harbour crates", "prop.goal")])
        runner.run()
        runner.stop()
        return _finish("did not run (busy)", ledger)

    # "off": the plan is on the slate and the box never woke up.
    ledger = InMemoryLedger()
    _slate(ledger, [_task("task_0001", "Weather the harbour crates", "prop.goal")])
    return _finish("did not run (off)", ledger)


def the_four_mornings() -> list[SimulatedNight]:
    """One morning per status value — the spec's four."""
    return [clean_night(), failures_night(), degraded_night(), did_not_run_night("off")]


# -- the iterator's mornings ------------------------------------------------

#: The variants the night may try for a goal: three seeds, then two refined
#: from the winner, then one more.
_VARIANTS = {
    1: [
        Variant(id="v1", label="seed 1024"),
        Variant(id="v2", label="seed 2048"),
        Variant(id="v3", label="seed 4096"),
    ],
    2: [
        Variant(id="w1", label="refined a"),
        Variant(id="w2", label="refined b"),
    ],
    3: [Variant(id="x1", label="refined c")],
}


def _critic(scores: dict[str, float]) -> ScriptedCritic:
    """The scripted critic: a score per variant, and a reason with it."""
    return ScriptedCritic(
        {
            "task_0001": {
                variant_id: CriticScore(
                    score=score, reason=f"the critic scored it {score:.2f}"
                )
                for variant_id, score in scores.items()
            }
        }
    )


def _iterating_night(
    name: str,
    scores: dict[str, float],
    rails: Rail = RAILS,
) -> SimulatedNight:
    """A night whose one task goes round the loop."""
    ledger = InMemoryLedger()
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=_variant_price("prop.goal").gpu_minutes,
                wall_minutes=_variant_price("prop.goal").wall_minutes,
            )
        }
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT_ID,
        rails=rails,
        clock=ScriptedClock(NIGHT_START),
        variant_source=ScriptedVariantSource({"task_0001": _VARIANTS}),
        critic=_critic(scores),
    )
    runner.start([_task("task_0001", "Weather the harbour crates", "prop.goal")])
    runner.run()
    runner.stop()
    return _finish(name, ledger)


def iteration_night() -> SimulatedNight:
    """The loop found a better variant than the first try — and says so.

    The first try scored 0.42; by the third round the loop had something
    worth 0.78. The morning names the winner, the round it came from, and
    everything it beat.
    """
    return _iterating_night(
        "iteration",
        {
            "v1": 0.42,
            "v2": 0.55,
            "v3": 0.50,
            "w1": 0.71,
            "w2": 0.60,
            "x1": 0.78,
        },
    )


def iteration_rail_cut_night() -> SimulatedNight:
    """The bar cut the loop short after the first round.

    Three variants took the night to 90 % of the rail, so the 80 % bar stopped
    the night opening another round. The rail is sized from the model's own
    price for a variant — the scenario's setting, not a typed-in number. The
    work it did keep is kept; the morning says the loop was cut.
    """
    variant = _variant_price("prop.goal")
    return _iterating_night(
        "iteration (rail cut)",
        {"v1": 0.42, "v2": 0.71, "v3": 0.50},
        rails=Rail(
            gpu_minutes=variant.gpu_minutes * 3 / 0.9,
            hosted_cents=0,
            wall_minutes=560.0,
        ),
    )


def iteration_stalled_night() -> SimulatedNight:
    """The score stopped improving, so the loop stopped early.

    The second round was no better than the first, so the gain fell below ε
    and the night stopped opening rounds. That is the loop working, not the
    night failing.
    """
    return _iterating_night(
        "iteration (stalled)",
        {"v1": 0.55, "v2": 0.42, "v3": 0.50, "w1": 0.55, "w2": 0.40},
    )


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
        iteration_night(),
        iteration_rail_cut_night(),
        iteration_stalled_night(),
    ]
