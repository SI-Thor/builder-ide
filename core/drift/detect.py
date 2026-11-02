"""The detector: run the gates over the signals, and decide what an
alarm means for the world.

§3.4 gives the signals; §3.5 gives the three levels of auto-pause.
This module is where the two meet:

| what happened | what it means | level |
|---|---|---|
| one agent's signal drifted | the agent waits on its own safe branch | **soft** |
| the world's own signal drifted, or several agents drifted at once | the world's work is demoted from ``live`` to ``preparation`` | **tier** |
| a rule violation | the doors close: nothing commits to ``main`` | **hard** |

The hard signal is **not** scored with the others and it has no
threshold, no band and no dwell: §3.4 is explicit that a promise to a
person is not a rate, and that averaging it into a score would be worse
than useless. One occurrence escalates immediately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..precedent import BoardManifest
from .config import DriftConfig
from .gate import HYBRID, LEVEL, RATE, DriftGate, GateMode, GateResult, HybridGate
from .ledger import WorldSeries
from .signals import Signal, SignalPoint, build_signals

__all__ = ["Alarm", "Detection", "DriftDetector", "SOFT", "TIER", "HARD"]

SOFT = "soft"
TIER = "tier"
HARD = "hard"


@dataclass(frozen=True)
class Alarm:
    """One thing the detector saw."""

    #: The window the alarm belongs to, epoch seconds.
    at: float
    #: The signal that fired.
    signal: str
    #: The agent it was about, or ``""`` for the world's own signals.
    agent: str
    #: ``soft``, ``tier`` or ``hard``.
    level: str
    #: The signal's value in that window.
    value: float | None
    #: The number the gate compared to the threshold.
    fed: float | None
    #: A sentence a human can read.
    reason: str


@dataclass
class Detection:
    """Everything one run of the detector produced."""

    alarms: list[Alarm] = field(default_factory=list)
    #: signal -> scope -> state, at the end of the run.
    states: dict[str, dict[str, str]] = field(default_factory=dict)
    #: signal -> the points the signal produced.
    points: dict[str, list[SignalPoint]] = field(default_factory=dict)
    #: window -> the (signal, scope) pairs that were in alarm in it.
    #: This is the detector's **state** over time, which is what a
    #: pause actually costs: an alarm that holds for two hours holds
    #: for two hours, whether it fired once or twice.
    alarm_windows: dict[float, set[tuple[str, str]]] = field(default_factory=dict)

    @property
    def hard(self) -> list[Alarm]:
        return [a for a in self.alarms if a.level == HARD]

    @property
    def tier(self) -> list[Alarm]:
        return [a for a in self.alarms if a.level == TIER]

    @property
    def soft(self) -> list[Alarm]:
        return [a for a in self.alarms if a.level == SOFT]


class DriftDetector:
    """The six signals, their gates, and the pause ladder."""

    def __init__(
        self,
        config: DriftConfig | None = None,
        *,
        mode: GateMode = RATE,
        manifest: BoardManifest | None = None,
        build_events: Sequence[Mapping[str, object]] | None = None,
    ) -> None:
        """With a ``manifest`` the build-drift signal becomes computable:
        it reads the board's ratified scope (``core/precedent``) and
        scores ``drift.build_drift`` rows (``build_events``) against it.
        Without one, every signal here behaves exactly as it did.
        """
        self.config = config or DriftConfig()
        self.mode = mode
        self.signals: list[Signal] = build_signals(
            manifest=manifest, build_events=build_events
        )

    # -- the run ---------------------------------------------------------------

    def run(
        self,
        series: WorldSeries,
        *,
        reference: tuple[float, float] | None = None,
    ) -> Detection:
        """Run every gate over the series and collect the alarms.

        ``reference`` is the period the baselines are computed over. It
        defaults to the series' own reference period (the first
        ``baseline_horizon_seconds`` of the run). In the calibration the
        reference is the **calibration half**, so the holdout half is
        scored against thresholds and baselines it did not choose.
        """
        if reference is None:
            reference = (series.reference_start, series.reference_end)

        detection = Detection()
        window_alarms: dict[float, list[Alarm]] = {}

        for signal in self.signals:
            points = signal.compute(series, self.config, reference)
            detection.points[signal.name] = points

            if signal.name == "violation":
                # The hard path: any occurrence, immediately, no gate.
                # It is checked before the "computable" gate below,
                # because the ledger does not carry violations today
                # and the path still has to be live for the day it does.
                for point in points:
                    if point.value is not None and point.value > 0:
                        detection.alarm_windows.setdefault(point.at, set()).add(
                            (signal.name, point.scope)
                        )
                        window_alarms.setdefault(point.at, []).append(
                            Alarm(
                                at=point.at,
                                signal=signal.name,
                                agent=point.scope,
                                level=HARD,
                                value=point.value,
                                fed=point.value,
                                reason=(
                                    f"rule violation ({point.value:.0f}) — the "
                                    "doors close"
                                ),
                            )
                        )
                detection.states[signal.name] = {}
                continue

            if not signal.computable:
                continue

            spec = self.config.gate_for(signal.name)
            if spec is None:
                continue
            by_scope: dict[str, list[SignalPoint]] = {}
            for point in points:
                by_scope.setdefault(point.scope, []).append(point)
            final: dict[str, str] = {}
            for scope, scope_points in by_scope.items():
                # One gate per scope: the gate carries the previous
                # value, and the previous value belongs to one agent.
                if self.mode == HYBRID:
                    gate: DriftGate | HybridGate = HybridGate(
                        signal.name,
                        enter_rate=spec.enter,
                        exit_level=spec.level_exit,
                        dwell_up=spec.dwell_up,
                        dwell_down=spec.dwell_down,
                    )
                else:
                    gate = DriftGate(signal.name, spec, mode=self.mode)
                for point in scope_points:
                    result = gate.step(point.value, point.at)
                    if result.state == "alarm":
                        detection.alarm_windows.setdefault(point.at, set()).add(
                            (signal.name, scope)
                        )
                    if result.fired:
                        window_alarms.setdefault(point.at, []).append(
                            Alarm(
                                at=point.at,
                                signal=signal.name,
                                agent=scope,
                                level=SOFT,
                                value=result.value,
                                fed=result.fed,
                                reason=self._reason(signal.name, scope, result),
                            )
                        )
                final[scope] = gate.state
            detection.states[signal.name] = final

        # The ladder: several agents at once, or the world's own signal,
        # is not one agent's problem.
        promoted: list[Alarm] = []
        for at, alarms in window_alarms.items():
            agents = {a.agent for a in alarms if a.agent}
            world_scope = any(not a.agent for a in alarms)
            promote = world_scope or len(agents) >= self.config.tier_agents
            for alarm in alarms:
                if alarm.level == HARD or not promote:
                    promoted.append(alarm)
                    continue
                promoted.append(
                    Alarm(
                        at=alarm.at,
                        signal=alarm.signal,
                        agent=alarm.agent,
                        level=TIER,
                        value=alarm.value,
                        fed=alarm.fed,
                        reason=alarm.reason + " — the world's work yields",
                    )
                )
        detection.alarms = sorted(promoted, key=lambda a: a.at)
        return detection

    # -- the reason ------------------------------------------------------------

    @staticmethod
    def _reason(signal: str, scope: str, result: GateResult) -> str:
        agent = scope or "the world"
        if signal == "stall":
            return (
                f"{agent}: the trailing worst gap jumped to "
                f"{result.value:.1f}x its own median gap"
            )
        if signal == "spend":
            return (
                f"{agent}: the cost per decision moved to "
                f"{result.value:.2f}x its own reference"
            )
        if signal == "success":
            direction = "fell" if result.value >= 0 else "rose"
            amount = abs(result.value)
            return (
                f"{agent}: the success rate {direction} {amount:.3f} "
                "against its own reference rate"
            )
        if signal == "errors":
            return (
                "the world: the decision model's refusal rate moved to "
                f"{result.value:.3f}"
            )
        return f"{agent}: {signal} moved to {result.fed:.3f}"
