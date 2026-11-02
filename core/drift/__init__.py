"""``core.drift`` — the drift detector: what "off track" means, measurably.

The design is ``docs/design/vibecode-in-world.md`` §3.4 and §3.5; the
lab note is ``docs/lab/exp-drift-detector.md``.

    from core.drift import DriftConfig, DriftDetector, build_series

    series = build_series("/path/to/world-ledger.sqlite3")
    detection = DriftDetector(DriftConfig()).run(series)
    for alarm in detection.alarms:
        print(alarm.at, alarm.level, alarm.reason)

Six signals, each a **rate** gate with hysteresis, and the hard signal
kept apart from the scored ones. The gate compares a signal's *rate of
change*, not its level: a level gate is a state, and only a change of
state is a trigger.
"""

from __future__ import annotations

from .config import SIGNALS, DriftConfig, GateSpec
from .detect import HARD, SOFT, TIER, Alarm, Detection, DriftDetector
from .gate import LEVEL, RATE, DriftGate, GateMode, GateResult
from .ledger import (
    AgentBucket,
    WorldBucket,
    WorldSeries,
    build_series,
    parse_at,
    read_plays,
    read_verdicts,
    rule_violation_events,
)
from .pause import (
    PauseEntry,
    PauseFile,
    Plan,
    apply,
    clear,
    demote,
    plan_from_state,
)
from .signals import (
    BuildDriftSignal,
    ErrorSignal,
    Signal,
    SignalPoint,
    SpendSignal,
    StallSignal,
    SuccessSignal,
    ViolationSignal,
    build_signals,
)

__all__ = [
    "SIGNALS",
    "Alarm",
    "PauseEntry",
    "PauseFile",
    "Plan",
    "AgentBucket",
    "BuildDriftSignal",
    "Detection",
    "DriftConfig",
    "DriftDetector",
    "DriftGate",
    "ErrorSignal",
    "GateMode",
    "GateResult",
    "GateSpec",
    "HARD",
    "LEVEL",
    "RATE",
    "SOFT",
    "Signal",
    "SignalPoint",
    "SpendSignal",
    "StallSignal",
    "SuccessSignal",
    "TIER",
    "ViolationSignal",
    "WorldBucket",
    "WorldSeries",
    "build_series",
    "apply",
    "build_signals",
    "clear",
    "demote",
    "parse_at",
    "plan_from_state",
    "read_plays",
    "read_verdicts",
    "rule_violation_events",
]
