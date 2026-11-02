"""The six signals of §3.4, and the honest answer to which of them the
world's ledger can carry.

§3.4 of ``docs/design/vibecode-in-world.md`` names six signals. This
module computes them, and for the two the ledger cannot carry it says so
instead of inventing a proxy:

| signal | scope | in the ledger? | what it is computed from |
|---|---|---|---|
| stall time rising | per agent | **yes** | the gap between consecutive ``tile.played`` events |
| success rate falling | per agent | **yes** | the outcome on ``tile.played`` |
| error bursts | the world | **yes** | ``judge.verdict`` rows flagged ``refused`` |
| rule violations | per agent | **no** | nothing writes a violation to the ledger |
| spend per productive decision | per agent | **partly** | the cost fields; thor-admit books no world label |
| build drift | a branch | **no** | the ledger has no branch head and no constraint set |

**Two corrections to §3.4, made here because the data says so.**

1. §3.4 reads the success signal from "``judge.verdict`` rows with a
   good outcome". In the world's ledger the *outcome* is on
   ``tile.played`` (``outcome.result``); a verdict carries the
   *decision* — the agent it was asked about (``judgments[].qid``) and
   the confidence — and no outcome. So the success rate is read from the
   plays and attributed per agent by ``context.bot``.
2. §3.4 reads error bursts from "``constraint.failed``, ``wo.failed``,
   and events whose payload is flagged ``refused: true``". The first two
   are **canon** event types (``core/fold.py``); the world ledger has
   neither. The world's own refusal event is the judge's, and it is
   flagged exactly as §3.4 says — ``refused: true`` — so that half of
   the definition holds verbatim.

**Every signal is a rate, not a count.** A count grows with the window
and with the size of the world; a rate does not, so the same threshold
means the same thing at 3 a.m. and at noon.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .config import DriftConfig
from .ledger import WorldSeries

__all__ = [
    "SignalPoint",
    "Signal",
    "StallSignal",
    "SuccessSignal",
    "ErrorSignal",
    "ViolationSignal",
    "SpendSignal",
    "BuildDriftSignal",
    "build_signals",
    "median",
]


@dataclass(frozen=True)
class SignalPoint:
    """One signal's value in one window."""

    #: The window's start, epoch seconds.
    at: float
    #: The agent the value belongs to, or ``""`` for a world-scope
    #: signal.
    scope: str
    #: The signal's value, or ``None`` when the signal is undefined
    #: here (not enough data to say anything).
    value: float | None


def median(values: Sequence[float]) -> float | None:
    """The median of a list, or ``None`` for an empty one."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


class Signal:
    """The base: a name, a scope, and whether the ledger carries it."""

    name: str = ""
    title: str = ""
    scope: str = "agent"
    computable: bool = True
    reason: str = ""

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        raise NotImplementedError


class StallSignal(Signal):
    """**Stall time rising** — the agent's trailing worst gap against its
    own median gap.

    §3.4: "the agent's trailing-window p99 gap exceeds its own 24 h
    median by a factor". The factor is the signal; the gate asks
    whether it *changed*.

    The baseline is the agent's own median inter-play gap over the
    reference period, and it is **frozen**: a baseline that follows the
    drift becomes the new normal.

    The numerator is the worst gap in the trailing
    ``stall_lookback_buckets`` windows — the largest of the per-window
    p99 gaps, and, in a window where the agent did nothing, the length
    of its idle. A window where nothing happened *is* a long gap.

    **A yield is not a stall.** The folding (``ledger.build_series``)
    censors a gap that has a ``drift.yield`` point inside it — the
    agent tried during that gap and the world said "not now" — and
    excuses the idle of a window the agent spent standing aside. So a
    busy box, and a drift pause, do not reach this signal as stalls:
    what is left is the silence nobody explained. This is the fix for
    the negative control of
    ``docs/lab/exp-drift-detector.md`` §5, and the numbers are in
    ``docs/lab/exp-drift-pause.md``.
    """

    name = "stall"
    title = "stall time rising"
    scope = "agent"

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        ref_start, ref_end = reference
        points: list[SignalPoint] = []
        for agent in series.agents:
            baseline = self._baseline(series, agent, ref_start, ref_end)
            if baseline is None or baseline <= 0:
                # The agent has no reference period of its own yet: the
                # signal is undefined rather than alarming.
                for bucket in series.buckets:
                    points.append(SignalPoint(bucket.start, agent, None))
                continue
            for index, bucket in enumerate(series.buckets):
                worst = self._trailing_worst(series, agent, index, config)
                if worst is None:
                    points.append(SignalPoint(bucket.start, agent, None))
                else:
                    points.append(
                        SignalPoint(bucket.start, agent, worst / baseline)
                    )
        return points

    @staticmethod
    def _baseline(
        series: WorldSeries, agent: str, ref_start: float, ref_end: float
    ) -> float | None:
        """The agent's own median inter-play gap over the reference period."""
        medians = [
            bucket.agent(agent).gap_p50
            for bucket in series.buckets
            if ref_start <= bucket.start < ref_end
            and bucket.agent(agent).gap_p50 is not None
        ]
        return median([m for m in medians if m is not None])

    @staticmethod
    def _trailing_worst(
        series: WorldSeries, agent: str, index: int, config: DriftConfig
    ) -> float | None:
        """The worst gap in the trailing window, ending at ``index``."""
        first = max(0, index - config.stall_lookback_buckets + 1)
        worst: float | None = None
        for position in range(first, index + 1):
            entry = series.buckets[position].agent(agent)
            candidate: float | None = None
            if entry.plays > 0 and entry.gap_p99 is not None:
                candidate = entry.gap_p99
            elif entry.idle_seconds is not None:
                candidate = entry.idle_seconds
            if candidate is None:
                continue
            if worst is None or candidate > worst:
                worst = candidate
        return worst


class SuccessSignal(Signal):
    """**Success rate falling** — the agent's win rate against its own
    reference rate.

    §3.4: "the rate over a window falls below the agent's own
    baseline". The value is the *drop*: the reference rate minus this
    window's rate, so a positive number means "worse than this agent
    normally is".

    The rate is pooled over the trailing ``signal_lookback_buckets``
    windows, not over one window: a rate over five plays is noise, and
    the gate differences this signal, so a noisy signal would give a
    noisy *rate of change*. A window with fewer than
    ``min_scored_plays`` scored plays has no rate, and an undefined
    signal is not a bad one.
    """

    name = "success"
    title = "success rate falling"
    scope = "agent"

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        ref_start, ref_end = reference
        points: list[SignalPoint] = []
        for agent in series.agents:
            baseline = self._baseline(series, agent, ref_start, ref_end)
            for index, bucket in enumerate(series.buckets):
                first = max(0, index - config.signal_lookback_buckets + 1)
                wins = 0
                losses = 0
                for position in range(first, index + 1):
                    entry = series.buckets[position].agent(agent)
                    wins += entry.wins
                    losses += entry.losses
                scored = wins + losses
                if baseline is None or scored < config.min_scored_plays:
                    points.append(SignalPoint(bucket.start, agent, None))
                    continue
                points.append(SignalPoint(bucket.start, agent, baseline - wins / scored))
        return points

    @staticmethod
    def _baseline(
        series: WorldSeries, agent: str, ref_start: float, ref_end: float
    ) -> float | None:
        wins = 0
        losses = 0
        for bucket in series.buckets:
            if not (ref_start <= bucket.start < ref_end):
                continue
            entry = bucket.agent(agent)
            wins += entry.wins
            losses += entry.losses
        if wins + losses == 0:
            return None
        return wins / (wins + losses)


class ErrorSignal(Signal):
    """**Error bursts** — the world's refusal rate.

    §3.4: "the *rate* of failures rises, not the count". The refusals
    are the judge's: a ``judge.verdict`` whose payload is flagged
    ``refused: true``, which is the world's own refusal event and the
    one §3.4 names.

    The scope is the world, not an agent: the decision model is shared,
    so its refusal is everybody's problem at once.
    """

    name = "errors"
    title = "error bursts"
    scope = "world"

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        points: list[SignalPoint] = []
        for bucket in series.buckets:
            if bucket.verdicts < config.min_verdicts:
                points.append(SignalPoint(bucket.start, "", None))
            else:
                points.append(
                    SignalPoint(bucket.start, "", bucket.refused / bucket.verdicts)
                )
        return points


class ViolationSignal(Signal):
    """**Rule violations** — the hard signal, with zero tolerance.

    §3.4: "**any** occurrence — see below. A drift detector that
    averages them into a score would be worse than useless. One
    violation → escalate immediately."

    **The world ledger cannot carry this.** The promises the note means
    — "They never touch your stuff… they never attack a player" — are
    enforced in the bots' own code
    (``agent-world/bots/src/humanity.js``, ``bots/test/no-grief.test.js``)
    and no violation is ever written to the ledger. The event type
    ``drift.rule_violation`` is read here so that the day the world
    writes one, the hard path is already wired and tested.
    """

    name = "violation"
    title = "rule violations"
    scope = "agent"
    computable = False
    reason = (
        "no ledger event carries a rule violation; the bots' humanity "
        "promises are enforced in the bots' own code and never written "
        "to the ledger"
    )

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        points: list[SignalPoint] = []
        for bucket in series.buckets:
            counts = bucket.rule_violations
            if not counts:
                points.append(SignalPoint(bucket.start, "", None))
                continue
            for agent, count in counts.items():
                points.append(SignalPoint(bucket.start, agent, float(count)))
        return points


class SpendSignal(Signal):
    """**Spend per productive decision** — the cost of a decision.

    §3.4: "thor-admit ledger by label ÷ ``tile.played``; the ratio
    rises". Two corrections and one substitution:

    * thor-admit's ledger books the world's hours under **no world
      label** — the world's services run outside the lease system, so
      there is no by-label spend for them. The spend is in the ledger
      itself: ``cost.gpu_minutes`` and ``cost.hosted_cents``. That is
      the number used here, and it is charged to the agent the verdict
      was about (``judgments[].qid``), because the decision model is
      what the world spends.
    * ``hosted_cents`` is **0 on every row of this world** — the world's
      decision model is local — so the hosted half of the definition
      contributes nothing here, and the units of the two halves are not
      commensurable in general. GPU minutes are used.
    * the note's *name* says "per productive decision" and its
      *formula* divides by every ``tile.played``. The formula is
      followed: the cost of a decision, against the agent's own
      reference cost of a decision. Dividing by the **wins** instead
      would be the win rate again under another name — the cost per
      win is the cost per play divided by the win rate — and §3.4
      already has a signal for the win rate.

    The baseline is the agent's own reference cost per play. An agent
    with no reference has no drift to report: the detector watches for
    *change*, not for mediocrity.
    """

    name = "spend"
    title = "spend per productive decision"
    scope = "agent"

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        ref_start, ref_end = reference
        points: list[SignalPoint] = []
        for agent in series.agents:
            baseline = self._baseline(series, agent, ref_start, ref_end)
            for index, bucket in enumerate(series.buckets):
                first = max(0, index - config.signal_lookback_buckets + 1)
                cost = 0.0
                plays = 0
                for position in range(first, index + 1):
                    entry = series.buckets[position].agent(agent)
                    cost += entry.gpu_minutes + entry.hosted_cents
                    plays += entry.plays
                if baseline is None or baseline <= 0 or plays == 0:
                    # No plays means no decisions and no spend: the
                    # stall signal owns that, and this signal has
                    # nothing to say.
                    points.append(SignalPoint(bucket.start, agent, None))
                    continue
                points.append(
                    SignalPoint(bucket.start, agent, (cost / plays) / baseline)
                )
        return points

    @staticmethod
    def _baseline(
        series: WorldSeries, agent: str, ref_start: float, ref_end: float
    ) -> float | None:
        """The agent's own reference cost per decision.

        The **median** of the per-window costs, not the pooled mean: a
        reference that includes a window where the decision model was
        down would be a reference to a broken world, and the world's
        first two hours are exactly that.
        """
        per_window: list[float] = []
        for bucket in series.buckets:
            if not (ref_start <= bucket.start < ref_end):
                continue
            entry = bucket.agent(agent)
            if entry.plays == 0:
                continue
            per_window.append(
                (entry.gpu_minutes + entry.hosted_cents) / entry.plays
            )
        return median(per_window)


class BuildDriftSignal(Signal):
    """**Build drift** — a branch head that no longer satisfies its
    ratified scope.

    **The world ledger cannot carry this.** Build drift is a canon-side
    property: ``core/recipe/store.py`` holds the branch heads and
    ``core/recipe/constraints.py`` holds the ratified scope, and the
    world does not commit to the canon yet — the world's ledger has no
    branch and no constraint set.

    The signal is here so that the six are named in one place, and so
    that the seam is visible: the detector reads ``drift.build_drift``
    events when the world starts writing them.
    """

    name = "build"
    title = "build drift"
    scope = "branch"
    computable = False
    reason = (
        "the world ledger has no branch head and no constraint set; build "
        "drift is a canon-side property (core/recipe) and the world does "
        "not commit to the canon"
    )

    def compute(
        self,
        series: WorldSeries,
        config: DriftConfig,
        reference: tuple[float, float],
    ) -> list[SignalPoint]:
        return []


def build_signals() -> list[Signal]:
    """All six signals, in the order §3.4 names them."""
    return [
        StallSignal(),
        SuccessSignal(),
        ErrorSignal(),
        ViolationSignal(),
        SpendSignal(),
        BuildDriftSignal(),
    ]
