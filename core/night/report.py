"""The morning report page (core-spec v2 §3.2.9).

The page is a **static file over the ledger**: no panel-side state, so it can
be regenerated from the log at any time and it survives the night that
produced it (§5.4). The order is the spec's, and it is the order the owner
reads in:

1. the **status line**, computed — ``ran as planned | ran short | ran
   degraded | did not run`` plus a one-line reason;
2. the **failure line** — always present, even when it is "nothing failed";
   failures lead;
3. **the cut named**, not just the spend;
4. the **night numbers** — and no single prediction score, which is theatre;
5. the filmstrip, the branches **plus the two standing options**, the parked
   questions **triaged top-3 plus a count**, the landed work orders, the
   model-change notices and the lost time;
6. the **tally**, per builder × claim type, with denominators;
7. the **three-number line**: hours of your Thor, hosted money, hours of
   your attention.

Then **"The box"**: the night's estimates replaced by what the box actually
did (M2). It comes last so the spec's order is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from core.night.cost.model import get_model
from core.night.heartbeat import lost_minutes
from core.night.models import AuditEvent
from core.night.projection import NightProjection
from core.night.status import StatusLine, compute_status

__all__ = [
    "BranchCard",
    "BoxRow",
    "CutCard",
    "FailureCard",
    "NightNumbers",
    "NightReport",
    "QuestionCard",
    "TallyRow",
    "TaskCard",
    "ThreeNumbers",
    "build_report",
    "render_html",
    "render_text",
    "write_report",
    "DECISION_BUDGET",
    "MINUTES_PER_DECISION",
]

#: A morning may ask for at most this many decisions (§3.2.9 item 7).
DECISION_BUDGET = 10

#: The attention estimate — how long a decision is expected to take the
#: owner. It is an **estimate**, and the page says so; this is the number
#: nobody measures (§3.2.9). It lives in the cost model with the rest of
#: the night's numbers, so every estimate the night quotes is in one place.
MINUTES_PER_DECISION = get_model().attention_minutes_per_decision()


class FailureCard(BaseModel):
    """A failure with its reason and its artifact — never an error alone."""

    task_id: str | None = None
    summary: str
    reason: str
    artifact: str | None = None


class CutCard(BaseModel):
    """Work the bar did not reach. It waits for tomorrow; it is not a failure."""

    task_id: str
    intention: str
    reason: str
    lane_minutes: float


class TaskCard(BaseModel):
    """What the night did with one task."""

    task_id: str
    intention: str
    state: str
    reason: str | None = None


class BranchCard(BaseModel):
    """One branch the morning can choose, or a standing exit."""

    id: str
    name: str
    kind: str
    head: str | None = None


class QuestionCard(BaseModel):
    """A parked question — and the assumption that replaced it, if any."""

    id: str
    name: str
    detail: str = ""
    blocking: bool = False
    assumptions: list[str] = Field(default_factory=list)


class TallyRow(BaseModel):
    """One builder × claim type, with its denominator."""

    builder: str
    claim_type: str
    hits: int = 0
    misses: int = 0
    partial: int = 0
    total: int = 0
    percentage: float | None = None


class ThreeNumbers(BaseModel):
    """The three-number morning line (§3.2.9 item 7) — and its fourth.

    The line is what the owner reads first: hours of your Thor, hosted
    money, hours of your attention. Plan item 17 added a fourth — the
    **joules** the night drew on the board's measured rails — and it is
    measured, not estimated.
    """

    thor_hours: float
    hosted_cents: int
    attention_hours: float
    decisions: int
    decision_budget: int = DECISION_BUDGET
    #: The night's energy, in joules: the whole-box ``VIN`` rail over the
    #: night's wall time. ``None`` only if nobody measured the rails.
    joules: float | None = None


class NightNumbers(BaseModel):
    """The night's numbers — measured, and with the cut named separately."""

    wall_time_minutes: float = 0.0
    recipe_edits: int = 0
    sealed_bets: int = 0
    kept_critic: int = 0
    kept_owner: int = 0
    reverted: int = 0
    parked: int = 0
    cut: int = 0
    gpu_minutes_spent: float = 0.0
    gpu_minutes_budget: float = 0.0
    hosted_cents: int = 0
    model_loads: dict[str, int] = Field(default_factory=dict)
    model_load_budget: dict[str, int] = Field(default_factory=dict)
    stage_cache_hits: int | None = None
    stage_cache_total: int = 0
    power_mode: int = 0
    wall_overrun_minutes: float = 0.0
    #: The loop's own numbers — how many goals were iterated on, how many
    #: variants were scored, and the quality the extra rounds bought.
    iterated_tasks: int = 0
    variants_scored: int = 0
    quality_gained: float = 0.0
    joules: float | None = None


class BoxRow(BaseModel):
    """One task's ask beside what the box actually did (M2's "The box")."""

    task_id: str
    intention: str
    ask_gpu_minutes: float
    measured_gpu_minutes: float
    ask_wall_minutes: float
    measured_wall_minutes: float


class WinnerCard(BaseModel):
    """The variant the loop kept."""

    variant_id: str
    label: str
    score: float
    round: int
    reason: str = ""


class RunnerUpCard(BaseModel):
    """A variant the winner beat — with the score and the reason it lost."""

    variant_id: str
    label: str
    score: float
    round: int
    why: str


class RoundCard(BaseModel):
    """One round of the loop: what it scored, what it gained, what it cost."""

    round: int
    variants: int = 0
    best_score: float = 0.0
    gain: float = 0.0
    gpu_minutes: float = 0.0
    wall_minutes: float = 0.0
    joules: float | None = None


class IterationCard(BaseModel):
    """One goal the night iterated on: the winner, and what it beat."""

    task_id: str
    intention: str
    winner: WinnerCard
    runner_ups: list[RunnerUpCard] = Field(default_factory=list)
    rounds: list[RoundCard] = Field(default_factory=list)
    stop: str = ""
    stop_detail: str = ""
    attempts: int = 0
    quality_gained: float = 0.0
    joules: float | None = None


class NightReport(BaseModel):
    """The whole morning, as data. The HTML and the text are two readings of it."""

    night_id: str
    generated_at: str
    status: StatusLine
    failures: list[FailureCard] = Field(default_factory=list)
    cut: list[CutCard] = Field(default_factory=list)
    tasks: list[TaskCard] = Field(default_factory=list)
    numbers: NightNumbers = Field(default_factory=NightNumbers)
    branches: list[BranchCard] = Field(default_factory=list)
    questions: list[QuestionCard] = Field(default_factory=list)
    questions_total: int = 0
    questions_hidden: int = 0
    work_orders: list[dict[str, Any]] = Field(default_factory=list)
    model_changes: list[dict[str, Any]] = Field(default_factory=list)
    lost_minutes: float = 0.0
    tally: list[TallyRow] = Field(default_factory=list)
    three_numbers: ThreeNumbers = Field(default_factory=ThreeNumbers)
    the_box: list[BoxRow] = Field(default_factory=list)
    iterations: list[IterationCard] = Field(default_factory=list)
    recovery: str | None = None
    #: The owner's two lines, as they were written when the night started.
    estimate: dict[str, Any] | None = None


# -- building ------------------------------------------------------------


def build_report(events: Sequence[AuditEvent]) -> NightReport:
    """Read the morning out of the log."""
    projection = NightProjection(events)
    status = compute_status(projection)
    night = projection.night
    night_id = night.id if night else "night_unknown"

    tasks = [
        TaskCard(
            task_id=task.id,
            intention=task.intention,
            state=task.state,
            reason=projection.reason_for(task.id),
        )
        for task in projection.tasks.values()
    ]

    failures = [
        FailureCard(
            task_id=failure.get("task_id"),
            summary=failure.get("reason", "the work failed"),
            reason=failure.get("reason", "no reason recorded"),
            artifact=failure.get("artifact"),
        )
        for failure in projection.failures
    ]

    cut = [
        CutCard(
            task_id=task.id,
            intention=task.intention,
            reason=projection.reason_for(task.id) or "cut at the bar",
            lane_minutes=task.cost_estimate.gpu_minutes,
        )
        for task in projection.tasks.values()
        if task.state == "cut"
    ]

    numbers = _numbers(projection, events)
    branches = _branches(projection)
    questions, questions_total = _questions(projection)
    tally = _tally(projection)
    iterations = _iterations(projection)
    numbers.iterated_tasks = len(iterations)
    numbers.variants_scored = len(projection.attempts)
    numbers.quality_gained = sum(card.quality_gained for card in iterations)
    # The night's joules are the whole box's draw over the night's wall time
    # — the rails were measured, so this is a measurement and not a guess.
    numbers.joules = _night_joules(numbers.wall_time_minutes)

    decisions = (1 if branches else 0) + len(questions) + len(projection.work_orders)
    three_numbers = ThreeNumbers(
        thor_hours=round(numbers.gpu_minutes_spent / 60.0, 1),
        hosted_cents=numbers.hosted_cents,
        attention_hours=round(decisions * MINUTES_PER_DECISION / 60.0, 1),
        decisions=decisions,
        joules=numbers.joules,
    )

    return NightReport(
        night_id=night_id,
        generated_at=events[-1].at if events else "",
        status=status,
        failures=failures,
        cut=cut,
        tasks=tasks,
        numbers=numbers,
        branches=branches,
        questions=questions,
        questions_total=questions_total,
        questions_hidden=max(0, questions_total - len(questions)),
        work_orders=list(projection.work_orders),
        model_changes=list(projection.model_changes),
        lost_minutes=lost_minutes(projection.ticks),
        tally=tally,
        three_numbers=three_numbers,
        the_box=_the_box(projection, events),
        iterations=iterations,
        recovery=_recovery(status, projection),
        estimate=projection.estimate,
    )


def _recovery(status: StatusLine, projection: NightProjection) -> str | None:
    """The one-tap recovery every ``did not run`` morning carries (§3.4).

    The plan is a recipe — kilobytes — so it survives every one of these
    nights by construction, and it is re-offered verbatim: *start now ·
    tonight · drop it*.
    """
    if status.status != "did not run":
        return None
    if not projection.tasks:
        return None
    return "Your plan is unstarted, unchanged — start now · tonight · drop it."


def _numbers(projection: NightProjection, events: Sequence[AuditEvent]) -> NightNumbers:
    night = projection.night
    numbers = NightNumbers()
    numbers.sealed_bets = len(
        [event for event in events if event.type == "prediction.sealed"]
    )
    numbers.recipe_edits = len([event for event in events if event.type == "edit.proposed"])
    numbers.kept_critic = len(projection.tasks_in_state("kept"))
    numbers.reverted = len(projection.tasks_in_state("reverted"))
    numbers.parked = len(projection.tasks_in_state("parked"))
    numbers.cut = len(projection.tasks_in_state("cut"))
    numbers.kept_owner = len(
        [
            event
            for event in events
            if event.type == "taste.note.appended"
            and (event.payload.get("row") or event.payload).get("verdict") == "keep"
        ]
    )
    numbers.gpu_minutes_spent = projection.spend.gpu_minutes
    numbers.hosted_cents = projection.spend.hosted_cents
    numbers.model_loads = dict(projection.model_loads)
    if night is not None:
        numbers.gpu_minutes_budget = night.rails.gpu_minutes
        numbers.model_load_budget = dict(night.load_budget)
        numbers.power_mode = night.power_mode
        numbers.wall_time_minutes = _wall_minutes(night.started_at, events)
        numbers.wall_overrun_minutes = max(
            0.0,
            projection.spend.wall_minutes
            - sum(task.cost_estimate.wall_minutes for task in projection.tasks.values()),
        )
    cache_values = [
        event.payload.get("stage_cache")
        for event in events
        if event.type == "job.done" and event.payload.get("stage_cache")
    ]
    numbers.stage_cache_total = len(cache_values)
    numbers.stage_cache_hits = (
        len([value for value in cache_values if value == "hit"]) if cache_values else None
    )
    return numbers


def _wall_minutes(started_at: str, events: Sequence[AuditEvent]) -> float:
    from datetime import datetime

    def parse(stamp: str) -> datetime:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))

    if not events:
        return 0.0
    last = max(event.at for event in events)
    return (parse(last) - parse(started_at)).total_seconds() / 60.0


def _branches(projection: NightProjection) -> list[BranchCard]:
    """The night's options, plus the two standing exits (§1.2).

    The standing options are furniture from night one, so using one on a bad
    morning reads as a choice, not a failure.
    """
    branches = [
        BranchCard(id=branch["branch"], name=branch["branch"], kind="night option")
        for branch in projection.branches
    ]
    branches.append(BranchCard(id="standing:keep-yesterday", name="keep yesterday", kind="standing"))
    branches.append(
        BranchCard(id="standing:back-to-the-plan", name="back to the plan", kind="standing")
    )
    return branches


def _questions(projection: NightProjection) -> tuple[list[QuestionCard], int]:
    """The parked questions, triaged: blocking first, then the top three."""
    ordered = sorted(
        projection.questions,
        key=lambda question: (not question.get("blocking", False), question.get("question_id", "")),
    )
    cards = [
        QuestionCard(
            id=question.get("question_id", ""),
            name=question.get("name", ""),
            detail=question.get("detail", ""),
            blocking=bool(question.get("blocking", False)),
            assumptions=list(question.get("assumptions", [])),
        )
        for question in ordered[:3]
    ]
    return cards, len(ordered)


def _tally(projection: NightProjection) -> list[TallyRow]:
    """The tally: per builder × claim type, with denominators.

    Percentages only where the denominator supports one; on night one it says
    the empty thing.
    """
    rows: dict[tuple[str, str], TallyRow] = {}
    for prediction in projection.predictions.values():
        verdict = prediction.get("verdict")
        if verdict is None:
            # An unsealed, unscored prediction died with the step that never
            # reached a render; it is not in the denominator (§5.2).
            continue
        builder = prediction.get("builder", "unknown")
        claim_type = prediction.get("claim_type", "unknown")
        row = rows.setdefault(
            (builder, claim_type),
            TallyRow(builder=builder, claim_type=claim_type),
        )
        if verdict == "hit":
            row.hits += 1
        elif verdict == "miss":
            row.misses += 1
        elif verdict == "partial":
            row.partial += 1
        row.total += 1
        if row.total >= 2:
            row.percentage = round(100.0 * row.hits / row.total, 1)
    return [rows[key] for key in sorted(rows)]


def _the_box(projection: NightProjection, events: Sequence[AuditEvent]) -> list[BoxRow]:
    """The box's own growth beat: the ask beside what was measured."""
    measured: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != "job.done":
            continue
        task_id = event.payload.get("task_id")
        if not task_id:
            continue
        # A task that iterated was measured more than once; the box did all
        # of it, so the measured cost is the sum of the attempts.
        cost = measured.setdefault(
            task_id, {"gpu_minutes": 0.0, "wall_minutes": 0.0, "hosted_cents": 0}
        )
        for axis in ("gpu_minutes", "wall_minutes", "hosted_cents"):
            cost[axis] = float(cost.get(axis, 0.0)) + float(
                (event.payload.get("cost") or {}).get(axis, 0.0)
            )
    rows: list[BoxRow] = []
    for task in projection.tasks.values():
        cost = measured.get(task.id, {})
        rows.append(
            BoxRow(
                task_id=task.id,
                intention=task.intention,
                ask_gpu_minutes=task.cost_estimate.gpu_minutes,
                measured_gpu_minutes=float(cost.get("gpu_minutes", 0.0)),
                ask_wall_minutes=task.cost_estimate.wall_minutes,
                measured_wall_minutes=float(cost.get("wall_minutes", 0.0)),
            )
        )
    return rows


def _iterations(projection: NightProjection) -> list[IterationCard]:
    """The loop's cards: the winner, and everything it beat.

    The winner comes from the task's own row (the loop's record); the
    runner-ups come from the attempts the log holds, so the morning can say
    what the winner beat and why each one lost.
    """
    cards: list[IterationCard] = []
    for task_id, record in projection.iterations.items():
        task = projection.tasks.get(task_id)
        winner = record.get("winner") or {}
        if not winner:
            continue
        attempts = projection.attempts_for(task_id)
        first_try = attempts[0] if attempts else None
        quality_gained = (
            float(winner.get("score", 0.0)) - first_try.score if first_try else 0.0
        )
        cards.append(
            IterationCard(
                task_id=task_id,
                intention=task.intention if task else "",
                winner=WinnerCard(
                    variant_id=winner.get("variant_id", ""),
                    label=winner.get("label", ""),
                    score=float(winner.get("score", 0.0)),
                    round=int(winner.get("round", 1)),
                    reason=winner.get("reason", ""),
                ),
                runner_ups=_runner_ups(attempts, winner),
                rounds=[
                    RoundCard(
                        round=int(row.get("round", 0)),
                        variants=int(row.get("variants", 0)),
                        best_score=float(row.get("best_score", 0.0)),
                        gain=float(row.get("gain", 0.0)),
                        gpu_minutes=float(row.get("gpu_minutes", 0.0)),
                        wall_minutes=float(row.get("wall_minutes", 0.0)),
                        joules=row.get("joules"),
                    )
                    for row in record.get("rounds", [])
                ],
                stop=str((record.get("stop") or {}).get("reason", "")),
                stop_detail=str((record.get("stop") or {}).get("detail", "")),
                attempts=int(record.get("attempts", len(attempts))),
                quality_gained=quality_gained,
                joules=_total_joules(record.get("rounds", [])),
            )
        )
    return cards


def _runner_ups(attempts: Sequence[Any], winner: dict[str, Any]) -> list[RunnerUpCard]:
    """The variants the winner beat, with the score and the reason each lost.

    A runner-up that became the warm start for a later round is named as
    such: "it lost, and then the loop narrowed in from it" is a different
    fact from "it lost".
    """
    winner_id = winner.get("variant_id", "")
    winner_score = float(winner.get("score", 0.0))
    # The round each variant was refined from — the warm start's lineage.
    children: dict[str, int] = {}
    for attempt in attempts:
        if attempt.parent_id:
            children[attempt.parent_id] = attempt.round
    runner_ups: list[RunnerUpCard] = []
    for attempt in attempts:
        if attempt.variant_id == winner_id:
            continue
        gap = winner_score - attempt.score
        if attempt.outcome != "kept":
            why = (
                f"scored {attempt.score:.2f}, but the work was not kept — "
                f"{attempt.reason or 'it failed'}"
            )
        else:
            why = f"scored {attempt.score:.2f}, {gap:.2f} below the winner"
        if attempt.variant_id in children:
            why += f" — it was the warm start for round {children[attempt.variant_id]}"
        runner_ups.append(
            RunnerUpCard(
                variant_id=attempt.variant_id,
                label=attempt.label,
                score=attempt.score,
                round=attempt.round,
                why=why,
            )
        )
    return runner_ups


def _total_joules(rounds: Sequence[dict[str, Any]]) -> float | None:
    """The night's joules — unmeasured until the power meter reads them."""
    values = [row.get("joules") for row in rounds]
    if not values or any(value is None for value in values):
        return None
    return float(sum(values))


def _night_joules(wall_minutes: float) -> float | None:
    """The energy the whole box drew while the night was running.

    The board's ``VIN`` rail was measured at 47.5 W under load
    (``docs/lab/exp-engines.md`` §4.4), and the box belongs to this project,
    so every joule it drew that night was this night's.
    """
    if wall_minutes <= 0:
        return None
    rails = get_model().data.rails
    return rails.vin_w * wall_minutes * 60.0 / 1000.0


def _four_numbers(three: ThreeNumbers) -> str:
    """The morning's line: hours, money, joules, attention.

    Three numbers in the spec, and the joules that plan item 17 added — the
    one that is measured rather than estimated. The attention hours keep
    their ``[e]``: nobody has measured those yet.
    """
    joules = (
        # kJ, not joules/1000: the field already holds kilojoules (the
        # rails' watts over the wall's seconds, scaled once — the same
        # 1000× under-report the honest-week run caught on the owner's
        # estimate line)
        f"{three.joules:.1f} kJ on the box"
        if three.joules is not None
        else "joules not measured"
    )
    return (
        f"{three.thor_hours:.1f} h of your Thor · "
        f"${three.hosted_cents / 100:.2f} hosted (local) · "
        f"{joules} · "
        f"{three.attention_hours:.1f} h of your attention [e] "
        f"({three.decisions} decision{'s' if three.decisions != 1 else ''}; "
        f"budget {three.decision_budget})"
    )


# -- rendering ------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0 auto; max-width: 46rem; padding: 2rem 1.25rem; line-height: 1.5; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; text-transform: lowercase;
     letter-spacing: .04em; opacity: .75; }
ul { padding-left: 1.1rem; margin: .35rem 0; }
li { margin: .2rem 0; }
.status { font-size: 1.25rem; font-weight: 600; margin: .5rem 0 0; }
.reason { opacity: .8; margin: .25rem 0 0; }
.note { opacity: .75; font-size: .9rem; }
.three { font-size: 1.05rem; margin: 0; padding: .75rem 0;
         border-top: 1px solid currentColor; border-bottom: 1px solid currentColor; }
.card { border-left: 3px solid currentColor; padding: .25rem 0 .25rem .75rem; margin: .5rem 0; }
.why { opacity: .75; font-size: .9rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .2rem .5rem .2rem 0; border-bottom: 1px solid rgba(128,128,128,.3); }
.empty { opacity: .7; font-style: italic; }
"""


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _hours(minutes: float) -> str:
    hours = minutes / 60.0
    return f"{int(hours)} h {int(round((hours - int(hours)) * 60)):02d} m"


def _plural(count: int, word: str) -> str:
    """``1 variant``, ``3 variants`` — the count and the word agree."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _where_the_time_went(numbers: NightNumbers) -> str:
    """Where a night's extra wall time went, when the night iterated.

    A night that ran long because it iterated is not a night that ran long
    for a mystery, and the page should not leave it as one.
    """
    if not numbers.variants_scored:
        return ""
    return f" — it went on {_plural(numbers.variants_scored, 'variant')}"


def render_html(report: NightReport) -> str:
    """The page. Static, self-contained, and in the spec's order."""
    numbers = report.numbers
    three = report.three_numbers
    out: list[str] = []
    add = out.append

    add("<!doctype html>")
    add('<html lang="en"><head><meta charset="utf-8">')
    add(f"<title>The morning — {report.night_id}</title>")
    add(f"<style>{_CSS}</style>")
    add("</head><body>")
    add(f"<h1>The morning — {_escape(report.night_id)}</h1>")

    # 1 — the status line, computed.
    add('<section id="status">')
    add(f'<p class="status">{_escape(report.status.first_line)}</p>')
    if report.status.variant:
        add(f'<p class="reason">Nothing ran: {_escape(report.status.variant)}.</p>')
    if report.recovery:
        add(f'<p class="reason">{_escape(report.recovery)}</p>')
    add("</section>")

    # 2 — the failures, first.
    add('<section id="failures">')
    add("<h2>What failed</h2>")
    if not report.failures:
        add('<p class="empty">Nothing failed.</p>')
    for failure in report.failures:
        add('<div class="card">')
        add(f"<div>{_escape(failure.summary)}</div>")
        if failure.artifact:
            add(f'<div class="why">artifact: {_escape(failure.artifact)}</div>')
        add("</div>")
    add("</section>")

    # 3 — the cut, named.
    add('<section id="cut">')
    add("<h2>The cut</h2>")
    if not report.cut:
        add('<p class="empty">Nothing was cut; the ask fitted under the bar.</p>')
    else:
        minutes = sum(card.lane_minutes for card in report.cut)
        add(
            f"<p>{minutes / 60:.1f} lane-h of the ask was cut and re-queued for tonight.</p>"
        )
        for card in report.cut:
            add('<div class="card">')
            add(f"<div>{_escape(card.intention)}</div>")
            add(f'<div class="why">{_escape(card.reason)}</div>')
            add("</div>")
    if numbers.wall_overrun_minutes > 0:
        add(
            f'<p class="note">The night ran {numbers.wall_overrun_minutes:.0f} min longer '
            f"than the ask{_where_the_time_went(numbers)}.</p>"
        )
    add("</section>")

    # 4 — the numbers.
    add('<section id="numbers">')
    add("<h2>The night's numbers</h2>")
    if report.estimate:
        add('<p class="note">What the night was asked to do:</p>')
        add(f"<p>{_escape(str(report.estimate.get('line_one', '')))}</p>")
        add(f"<p>{_escape(str(report.estimate.get('line_two', '')))}</p>")
    add("<ul>")
    add(f"<li>{_hours(numbers.wall_time_minutes)} on the clock</li>")
    add(f"<li>{numbers.recipe_edits} recipe edits</li>")
    add(f"<li>{numbers.sealed_bets} sealed bets</li>")
    add(
        f"<li>{numbers.kept_critic + numbers.kept_owner} kept "
        f"({numbers.kept_critic} critic-keeps, {numbers.kept_owner} owner-keeps)</li>"
    )
    add(f"<li>{numbers.reverted} reverted</li>")
    add(f"<li>{numbers.parked} parked</li>")
    add(f"<li>{numbers.cut} cut</li>")
    add(
        f"<li>{numbers.gpu_minutes_spent / 60:.1f} of "
        f"{numbers.gpu_minutes_budget / 60:.1f} GPU-h</li>"
    )
    loads = ", ".join(
        f"{model} {count}"
        f" (budget {numbers.model_load_budget.get(model, 1)})"
        for model, count in sorted(numbers.model_loads.items())
    )
    add(f"<li>model loads: {loads or 'none'}</li>")
    if numbers.stage_cache_hits is not None:
        add(
            f"<li>stage-cache hits {numbers.stage_cache_hits}/{numbers.stage_cache_total}</li>"
        )
    add(f"<li>power mode: MAXN ({numbers.power_mode})</li>")
    if numbers.iterated_tasks:
        add(f"<li>{numbers.iterated_tasks} goal(s) iterated on</li>")
        add(f"<li>{numbers.variants_scored} variants scored</li>")
        add(f"<li>quality gained over the first tries: {numbers.quality_gained:.2f}</li>")
        joules = (
            f"{numbers.joules:.0f} J"
            if numbers.joules is not None
            else "not measured (no rails)"
        )
        add(f"<li>joules: {joules}</li>")
    add("</ul>")
    add("</section>")

    # 5 — the morning: the branches, the questions, the work orders.
    add('<section id="morning">')
    add("<h2>What the night did</h2>")
    add("<ul>")
    for task in report.tasks:
        reason = f" — {_escape(task.reason)}" if task.reason else ""
        add(f"<li>{_escape(task.intention)}: {task.state}{reason}</li>")
    add("</ul>")

    if report.iterations:
        add("<h2>What the night iterated</h2>")
        for card in report.iterations:
            add('<div class="card">')
            add(f"<div>{_escape(card.intention)}</div>")
            add(
                f'<div>the winner: {_escape(card.winner.label or card.winner.variant_id)} '
                f"(variant {_escape(card.winner.variant_id)}) — scored "
                f"{card.winner.score:.2f} in round {card.winner.round}</div>"
            )
            if card.quality_gained:
                add(
                    f'<div class="why">it beat the first try by '
                    f"{card.quality_gained:.2f}</div>"
                )
            if card.rounds:
                add("<table><tr><th>Round</th><th>Variants</th><th>Best</th>"
                    "<th>Gained</th><th>Lane-min</th></tr>")
                for row in card.rounds:
                    add(
                        f"<tr><td>{row.round}</td><td>{row.variants}</td>"
                        f"<td>{row.best_score:.2f}</td><td>{row.gain:.2f}</td>"
                        f"<td>{row.gpu_minutes:.0f}</td></tr>"
                    )
                add("</table>")
            if card.stop_detail:
                add(f'<div class="why">stopped: {_escape(card.stop_detail)}</div>')
            if card.runner_ups:
                add("<div>what it beat:</div><ul>")
                for runner_up in card.runner_ups:
                    add(
                        f"<li>{_escape(runner_up.label or runner_up.variant_id)} "
                        f'<span class="why">({_escape(runner_up.why)})</span></li>'
                    )
                add("</ul>")
            joules = (
                f"{card.joules:.0f} J"
                if card.joules is not None
                else "not measured (no rails)"
            )
            add(f'<div class="why">joules: {joules}</div>')
            add("</div>")

    add("<h2>Branches to choose</h2>")
    add("<ul>")
    for branch in report.branches:
        kind = "standing exit" if branch.kind == "standing" else "tonight's option"
        add(f"<li>{_escape(branch.name)} <span class=\"why\">({kind})</span></li>")
    add("</ul>")

    add("<h2>Parked questions</h2>")
    if not report.questions:
        add('<p class="empty">No questions are waiting.</p>')
    for question in report.questions:
        add('<div class="card">')
        add(f"<div>{_escape(question.name)}</div>")
        if question.detail:
            add(f'<div class="why">{_escape(question.detail)}</div>')
        for assumption in question.assumptions:
            add(f'<div class="why">taken instead: {_escape(assumption)}</div>')
        add("</div>")
    if report.questions_hidden:
        add(f'<p class="note">{report.questions_hidden} more, none blocking.</p>')

    if report.work_orders:
        add("<h2>Landed work orders</h2>")
        add("<ul>")
        for order in report.work_orders:
            add(f"<li>{_escape(order.get('title', order.get('id', 'work order')))}</li>")
        add("</ul>")

    if report.model_changes:
        add("<h2>Model changes</h2>")
        add("<ul>")
        for change in report.model_changes:
            add(f"<li>{_escape(change.get('note', change.get('model', 'model change')))}</li>")
        add("</ul>")

    if report.lost_minutes > 0:
        add("<h2>Lost time</h2>")
        add(
            f'<p class="note">The box was not answering for '
            f"{report.lost_minutes:.0f} minutes. The night resumed from its last "
            "sealed step.</p>"
        )
    add("</section>")

    # 6 — the tally.
    add('<section id="tally">')
    add("<h2>The tally</h2>")
    if not report.tally:
        add('<p class="empty">No sealed bets were scored yet — not taste yet; that is a start.</p>')
    else:
        add("<table><tr><th>Builder</th><th>Claim</th><th>Kept</th><th>Missed</th>"
            "<th>Total</th><th>Rate</th></tr>")
        for row in report.tally:
            rate = f"{row.percentage:.0f}%" if row.percentage is not None else "—"
            add(
                f"<tr><td>{_escape(row.builder)}</td><td>{_escape(row.claim_type)}</td>"
                f"<td>{row.hits}</td><td>{row.misses}</td><td>{row.total}</td>"
                f"<td>{rate}</td></tr>"
            )
        add("</table>")
    add("</section>")

    # 7 — the three-number line, and its fourth.
    add('<section id="three-numbers">')
    add(f'<p class="three">{_four_numbers(three)}</p>')
    add("</section>")

    # The box — the machine's own growth beat, after the spec's order.
    add('<section id="the-box">')
    add("<h2>The box</h2>")
    if not report.the_box:
        add('<p class="empty">Nothing was measured tonight.</p>')
    else:
        add("<table><tr><th>Task</th><th>Ask (lane-min)</th><th>Measured</th>"
            "<th>Ask (wall)</th><th>Measured</th></tr>")
        for row in report.the_box:
            add(
                f"<tr><td>{_escape(row.intention)}</td>"
                f"<td>{row.ask_gpu_minutes:.0f}</td><td>{row.measured_gpu_minutes:.0f}</td>"
                f"<td>{row.ask_wall_minutes:.0f}</td><td>{row.measured_wall_minutes:.0f}</td></tr>"
            )
        add("</table>")
    add("</section>")

    add("</body></html>")
    return "\n".join(out)


def render_text(report: NightReport) -> str:
    """The text mode: the same ledger read, for a screen reader or a terminal."""
    numbers = report.numbers
    three = report.three_numbers
    lines: list[str] = []
    add = lines.append

    add(f"THE MORNING — {report.night_id}")
    add("")
    add(report.status.first_line)
    if report.status.variant:
        add(f"Variant: {report.status.variant}")
    if report.recovery:
        add(report.recovery)
    add("")
    add("WHAT FAILED")
    if not report.failures:
        add("  Nothing failed.")
    for failure in report.failures:
        add(f"  {failure.summary}" + (f" [{failure.artifact}]" if failure.artifact else ""))
    add("")
    add("THE CUT")
    if not report.cut:
        add("  Nothing was cut; the ask fitted under the bar.")
    for card in report.cut:
        add(f"  {card.intention} — {card.reason}")
    if numbers.wall_overrun_minutes > 0:
        add(
            f"  The night ran {numbers.wall_overrun_minutes:.0f} min longer than the ask"
            f"{_where_the_time_went(numbers)}."
        )
    add("")
    add("THE NIGHT'S NUMBERS")
    if report.estimate:
        add(f"  asked: {report.estimate.get('line_one', '')}")
        add(f"  {report.estimate.get('line_two', '')}")
    add(f"  {_hours(numbers.wall_time_minutes)} on the clock")
    add(f"  {numbers.recipe_edits} recipe edits")
    add(f"  {numbers.sealed_bets} sealed bets")
    add(
        f"  {numbers.kept_critic + numbers.kept_owner} kept "
        f"({numbers.kept_critic} critic-keeps, {numbers.kept_owner} owner-keeps)"
    )
    add(f"  {numbers.reverted} reverted · {numbers.parked} parked · {numbers.cut} cut")
    add(
        f"  {numbers.gpu_minutes_spent / 60:.1f} of {numbers.gpu_minutes_budget / 60:.1f} GPU-h"
    )
    add(f"  {_four_numbers(three)}")
    add("")
    add("WHAT THE NIGHT DID")
    for task in report.tasks:
        add(f"  {task.intention}: {task.state}" + (f" — {task.reason}" if task.reason else ""))
    if report.iterations:
        add("")
        add("WHAT THE NIGHT ITERATED")
        for card in report.iterations:
            add(f"  {card.intention}")
            add(
                f"    the winner: {card.winner.label or card.winner.variant_id} "
                f"(variant {card.winner.variant_id}) — scored {card.winner.score:.2f} "
                f"in round {card.winner.round}"
            )
            if card.quality_gained:
                add(f"    it beat the first try by {card.quality_gained:.2f}")
            for row in card.rounds:
                add(
                    f"    round {row.round}: {_plural(row.variants, 'variant')} · best "
                    f"{row.best_score:.2f} · gained {row.gain:.2f} · "
                    f"{row.gpu_minutes:.0f} lane-min"
                )
            if card.stop_detail:
                add(f"    stopped: {card.stop_detail}")
            for runner_up in card.runner_ups:
                add(
                    f"    beat: {runner_up.label or runner_up.variant_id} "
                    f"({runner_up.why})"
                )
            joules = (
                f"{card.joules:.0f} J"
                if card.joules is not None
                else "not measured (no rails)"
            )
            add(f"    joules: {joules}")
    add("")
    add("BRANCHES TO CHOOSE")
    for branch in report.branches:
        add(f"  {branch.name} ({branch.kind})")
    add("")
    add("PARKED QUESTIONS")
    if not report.questions:
        add("  No questions are waiting.")
    for question in report.questions:
        add(f"  {question.name}")
        for assumption in question.assumptions:
            add(f"    taken instead: {assumption}")
    if report.questions_hidden:
        add(f"  {report.questions_hidden} more, none blocking.")
    add("")
    add("THE TALLY")
    if not report.tally:
        add("  No sealed bets were scored yet — not taste yet; that is a start.")
    for row in report.tally:
        rate = f"{row.percentage:.0f}%" if row.percentage is not None else "—"
        add(
            f"  {row.builder} · {row.claim_type}: {row.hits} kept, {row.misses} missed, "
            f"{row.total} total ({rate})"
        )
    if report.lost_minutes > 0:
        add("")
        add(f"LOST TIME: {report.lost_minutes:.0f} minutes")
    return "\n".join(lines) + "\n"


def write_report(report: NightReport, directory: Path) -> Path:
    """Write the page, its JSON and its text into the reports directory."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    html_path = directory / "report.html"
    html_path.write_text(render_html(report), encoding="utf-8")
    (directory / "report.json").write_text(
        json.dumps(report.model_dump(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (directory / "report.txt").write_text(render_text(report), encoding="utf-8")
    return html_path
