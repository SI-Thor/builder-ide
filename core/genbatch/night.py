"""The night driver: the whole thing, and the morning it leaves behind.

This is where the seat meets the core. The night's work is a list of tasks
on the core's queue; the work itself is the core's night runner asking the
executor to do it; the judgement is the core's loop asking the critic; and
the morning is the core's own report — the winner, and what it beat — with
the prop seat's numbers beside it.

The three scheduling rules live in the plan (see
:mod:`core.genbatch.schedule`), and the report says which ones ran and what
they cost.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Sequence

from pydantic import BaseModel, Field

from core.models import Asset
from core.night.clock import Clock
from core.night.ledger import Ledger
from core.night.models import Rail
from core.night.report import NightReport, build_report
from core.night.runner import NightRunner
from core.night.iterate import Variant

from core.genbatch.critic import PropCritic
from core.genbatch.executor import PropExecutor, Templates
from core.genbatch.models import PropRequest
from core.genbatch.schedule import NightPlan, ScheduleRule
from core.genbatch.store import PropStore

__all__ = [
    "LaneSummary",
    "MeasuredClock",
    "PropNightReport",
    "PropVariantSource",
    "PropWinner",
    "run_prop_night",
]


class MeasuredClock:
    """The wall clock of the box, for a night whose work really happened.

    The runner advances the clock by the time the work took, so that the
    window ticks and the running job's lease renews (§3.4, §5.2). On a
    night whose work was real, that time has already passed — advancing
    again would sleep for it, and the night would take twice as long as the
    work did.
    """

    def now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def advance(self, minutes: float) -> None:
        """The time has already passed; there is nothing to wait for."""


class PropVariantSource:
    """The candidates the night tries: N seeds per request.

    One round of N seeds, and the best of them kept — which is what the
    brief asks of the iterator. The seeds come from the request, so the
    night's work replays.
    """

    def __init__(self, plan: NightPlan) -> None:
        self._plan = plan

    def variants(
        self, task, *, round: int, parent, count: int
    ) -> list[Variant]:
        request = self._plan.request(task.id)
        if request is None:
            return []
        return [
            Variant(
                id=f"{task.id}_r{round}_v{index + 1}",
                label=f"seed {seed}",
                seed=seed,
                round=round,
            )
            for index, seed in enumerate(self._plan.seeds(request.id))
        ]


class LaneSummary(BaseModel):
    """Where the night's time went, by lane."""

    prompts: int = 0
    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    unknown_seconds: float = 0.0
    wall_seconds: float = 0.0
    #: How many pairs of prompts shared any time. It must be zero.
    overlaps: int = 0

    @property
    def cpu_fraction(self) -> float:
        if self.wall_seconds <= 0:
            return 0.0
        return self.cpu_seconds / self.wall_seconds


class PropWinner(BaseModel):
    """The prop the night kept, and what it beat."""

    task_id: str
    request_id: str
    variant_id: str
    seed: int = 0
    score: float = 0.0
    reason: str = ""
    asset_id: str = ""
    glb_path: str = ""
    triangles: int = 0
    watertight: bool = False
    extent: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: What the repair stage did to the mesh, and how much of the prop's
    #: outline survived it.
    repair: str = ""
    repair_fidelity: float = 0.0
    #: The variants this one beat, with their scores.
    beaten: list[str] = Field(default_factory=list)


class PropNightReport(BaseModel):
    """The morning: the core's report, and the prop seat's numbers."""

    night_id: str
    generated_at: str
    rules: list[ScheduleRule] = Field(default_factory=list)
    lanes: LaneSummary = Field(default_factory=LaneSummary)
    winners: list[PropWinner] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    #: The core's own morning.
    night: NightReport

    def render_text(self) -> str:
        """The morning, as text."""
        lines: list[str] = []
        lines.append(f"=== {self.night_id} — {self.generated_at}")
        lines.append("")
        lines.append("The rules the night ran by:")
        for rule in self.rules:
            lines.append(f"  · {rule.name}: {rule.rule}")
            lines.append(f"    ({rule.evidence})")
        lines.append("")
        lines.append("Where the time went:")
        lines.append(
            f"  · {self.lanes.prompts} prompts, {self.lanes.wall_seconds:.0f} s of wall clock"
        )
        lines.append(
            f"  · GPU lane {self.lanes.gpu_seconds:.0f} s "
            f"({self.lanes.gpu_seconds / max(self.lanes.wall_seconds, 1):.0%} of the night)"
        )
        lines.append(
            f"  · CPU lane {self.lanes.cpu_seconds:.0f} s "
            f"({self.lanes.cpu_fraction:.0%} of the night) — the mesh tail"
        )
        if self.lanes.unknown_seconds:
            lines.append(f"  · unclassified {self.lanes.unknown_seconds:.0f} s")
        lines.append(
            f"  · overlapping prompts: {self.lanes.overlaps} (the rule says zero)"
        )
        lines.append("")
        lines.append("The winners:")
        for winner in self.winners:
            lines.append(
                f"  · {winner.request_id}: {winner.variant_id} — scored "
                f"{winner.score:.3f} (seed {winner.seed})"
            )
            lines.append(
                f"    {winner.triangles:,} triangles, "
                f"{'watertight' if winner.watertight else 'not watertight'}, "
                f"extent {winner.extent[0]:.3f}×{winner.extent[1]:.3f}×{winner.extent[2]:.3f}"
            )
            if winner.reason:
                lines.append(f"    the critic: {winner.reason}")
            if winner.repair:
                lines.append(f"    the repair: {winner.repair}")
            if winner.beaten:
                lines.append(f"    it beat: {', '.join(winner.beaten)}")
        if not self.winners:
            lines.append("  · nothing was kept")
        lines.append("")
        lines.append("The core's morning:")
        for line in self.night.model_dump_json(indent=2).splitlines():
            lines.append(f"  {line}")
        return "\n".join(lines)


def _rails_for(plan: NightPlan) -> Rail:
    """The night's rails: enough for the work the plan describes."""
    gpu = sum(task.cost_estimate.gpu_minutes for task in plan.tasks)
    wall = sum(task.cost_estimate.wall_minutes for task in plan.tasks)
    return Rail(
        gpu_minutes=gpu * 1.5 + 5.0,
        wall_minutes=wall * 1.5 + 10.0,
        hosted_cents=0,
    )


def _lane_summary(store: PropStore) -> LaneSummary:
    prompts = store.prompts()
    overlaps = 0
    for index, first in enumerate(prompts):
        for second in prompts[index + 1 :]:
            if first.overlaps(second):
                overlaps += 1
    return LaneSummary(
        prompts=len(prompts),
        gpu_seconds=sum(p.gpu_seconds for p in prompts),
        cpu_seconds=sum(p.cpu_seconds for p in prompts),
        unknown_seconds=sum(p.unknown_seconds for p in prompts),
        wall_seconds=sum(p.seconds for p in prompts),
        overlaps=overlaps,
    )


def run_prop_night(
    *,
    requests: Sequence[PropRequest],
    client,
    templates: Templates,
    ledger: Ledger,
    night_id: str = "night-genbatch",
    rails: Rail | None = None,
    clock: Clock | None = None,
    load_budget: Mapping[str, int] | None = None,
) -> PropNightReport:
    """Run a night of props, and report the morning.

    ``client`` is the ComfyUI client (or anything that speaks to it);
    ``templates`` are the workflow templates read from the TRELLIS.2
    environment; ``ledger`` is the core's log, and the night is written
    into it like any other.
    """
    plan = NightPlan(list(requests))
    store = PropStore()
    executor = PropExecutor(
        client=client, plan=plan, store=store, templates=templates
    )
    by_task = {task.id: plan.request(task.id) for task in plan.tasks}
    critic = PropCritic(requests=by_task, store=store, plan=plan)
    runner = NightRunner(
        ledger,
        executor,
        night_id=night_id,
        rails=rails if rails is not None else _rails_for(plan),
        clock=clock if clock is not None else MeasuredClock(),
        load_budget=dict(load_budget or {}),
        variant_source=PropVariantSource(plan),
        critic=critic,
        iteration=plan.iteration_policy,
    )
    runner.start(plan.tasks)
    runner.run()
    runner.stop()

    core_report = build_report(ledger.events())
    winners = _winners(plan, store, core_report)
    assets = [
        asset
        for winner in winners
        for asset in [store.asset(winner.task_id, winner.variant_id)]
        if asset is not None
    ]
    return PropNightReport(
        night_id=night_id,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rules=plan.rules,
        lanes=_lane_summary(store),
        winners=winners,
        assets=assets,
        night=core_report,
    )


def _winners(plan: NightPlan, store: PropStore, report: NightReport) -> list[PropWinner]:
    """The prop the night kept for each request, and what it beat."""
    winners: list[PropWinner] = []
    for iteration in report.iterations:
        request = plan.request(iteration.task_id)
        if request is None:
            continue
        variant_id = iteration.winner.variant_id
        mesh = store.mesh(iteration.task_id, variant_id)
        if mesh is None:
            continue
        asset = store.asset(iteration.task_id, variant_id)
        repair = store.repair(iteration.task_id, variant_id)
        winners.append(
            PropWinner(
                task_id=iteration.task_id,
                request_id=request.id,
                variant_id=variant_id,
                seed=store.seed(iteration.task_id, variant_id),
                score=iteration.winner.score,
                reason=iteration.winner.reason,
                asset_id=asset.id if asset else "",
                glb_path=asset.files[0].path if asset and asset.files else "",
                triangles=mesh.triangles,
                watertight=mesh.watertight,
                extent=mesh.extent,
                repair=repair.reason if repair else "",
                repair_fidelity=repair.fidelity if repair else 0.0,
                beaten=[
                    f"{runner_up.variant_id} ({runner_up.score:.3f})"
                    for runner_up in iteration.runner_ups
                ],
            )
        )
    return winners
