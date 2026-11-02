"""The drift detector's defaults, in one place.

Every number the detector uses is here, named, and has a reason. The
defaults were chosen on the **calibration half** of the world's ledger
and checked on the **holdout half**; see
``docs/lab/exp-drift-detector.md`` for the numbers and the method.

The shape of the configuration follows ``docs/design/vibecode-in-world.md``
§3.4: six signals, each a **rate** gate with hysteresis, and a
five-minute window.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

__all__ = ["DriftConfig", "GateSpec", "SIGNALS"]


@dataclass(frozen=True)
class GateSpec:
    """One signal's gate: the thresholds, the band, and the dwell.

    ``enter`` is the value the signal must reach to raise an alarm;
    ``exit`` is the value it must fall below to clear it. The gap
    between them is the band, and it is what stops the alarm from
    flickering (``core/hysteresis``).

    In the **rate** mode ``enter`` and ``exit`` are in units of the
    signal's change; in the **level** mode they are in units of the
    signal's value. The **hybrid** mode uses both quantities, and
    ``level_exit`` is the level at which the alarm lets go.

    ``dwell_up`` is how long the signal must hold the alarm before the
    alarm is committed, and ``dwell_down`` how long it must hold the
    clear before the clear is committed. Both are in seconds of the
    world's clock.
    """

    enter: float
    exit: float
    level_exit: float = 0.0
    dwell_up: float = 0.0
    dwell_down: float = 600.0

    def __post_init__(self) -> None:
        if self.exit > self.enter:
            raise ValueError(
                f"gate band is the wrong way round: exit {self.exit} is above "
                f"enter {self.enter}"
            )
        if self.dwell_up < 0.0 or self.dwell_down < 0.0:
            raise ValueError("a dwell time is a duration")


#: The six signals of §3.4, in the order the note names them, with what
#: each one is computed from and whether the **world ledger** carries it.
#:
#: ``computable`` is the honest answer to "can this be built from what the
#: ledger has". Two of the six cannot, and the detector says so rather
#: than inventing a proxy.
SIGNALS: dict[str, dict[str, object]] = {
    "stall": {
        "title": "stall time rising",
        "scope": "agent",
        "computable": True,
        "source": "the gap between consecutive tile.played events, per agent",
    },
    "success": {
        "title": "success rate falling",
        "scope": "agent",
        "computable": True,
        "source": "the outcome on tile.played, per agent",
    },
    "errors": {
        "title": "error bursts",
        "scope": "world",
        "computable": True,
        "source": "judge.verdict rows whose payload is flagged refused",
    },
    "violation": {
        "title": "rule violations",
        "scope": "agent",
        "computable": False,
        "source": "no ledger event carries a rule violation",
    },
    "spend": {
        "title": "spend per productive decision",
        "scope": "agent",
        "computable": True,
        "source": "the cost fields on tile.played and judge.verdict",
    },
    "build": {
        "title": "build drift",
        "scope": "branch",
        "computable": False,
        "source": "the world ledger has no branch head and no constraint set",
    },
}


@dataclass(frozen=True)
class DriftConfig:
    """Everything the detector needs, with the defaults the lab chose.

    The defaults are the ones the calibration selected on the
    calibration half of the ledger; they are frozen here so the
    detector is reproducible and so a reader can see the numbers.
    """

    # -- the window -----------------------------------------------------------
    #: §6.2 of the design note: "a rate gate over the ledger with
    #: hysteresis and a five-minute window".
    bucket_seconds: int = 300

    #: §3.4: each agent's baseline is "its own 24 h median". The
    #: baseline is a **reference**, not a trailing one: a baseline that
    #: follows the drift becomes the new normal and the drift stops
    #: being visible. In the lab the reference is the calibration half;
    #: for the live detector it is the world's first 24 h.
    baseline_horizon_seconds: int = 24 * 3600

    #: How many buckets the stall signal looks back over. Three buckets
    #: is 15 minutes at the default window.
    stall_lookback_buckets: int = 3

    #: How many buckets the success and spend signals look back over.
    #: Both are rates over a sample, and a rate over five plays is
    #: noise: the lab measured that differencing a noisy rate makes a
    #: noisy *rate of change*, so the sample is widened before it is
    #: differenced, not after.
    signal_lookback_buckets: int = 3

    #: A window with fewer scored plays than this does not get a success
    #: rate: a rate computed from two plays is noise, and noise that
    #: fires an alarm is worse than no alarm. The lab measured the
    #: width: at five scored plays the success signal's rate gate spent
    #: 16.2 false-alarm windows over the nine leave-one-out folds, at
    #: twenty 18.3, at forty 7.2 — the same 2 of 9 episodes in all
    #: three. The width is a second-order lever; the **one-sided** rate
    #: is the first-order one (the two-sided gate spent 35.4 and
    #: alarmed on 7 of the 12 designed-yield windows, against 18.3 and
    #: 5 of 12). Twenty is kept because the holdout numbers are better
    #: there than at five, and because a rate over five plays is not a
    #: rate.
    min_scored_plays: int = 20

    #: A window with fewer verdicts than this does not get an error
    #: rate, for the same reason.
    min_verdicts: int = 5

    # -- the gates ------------------------------------------------------------
    #: The stall gate fires when the trailing worst gap, divided by the
    #: agent's own median gap, rises by this much **in one bucket**.
    #: The level gate on the same signal has no useful threshold at all
    #: (the lab note says why); the rate gate does.
    stall: GateSpec = field(default_factory=lambda: GateSpec(enter=10.0, exit=6.0))

    #: The success gate fires when the agent's success rate falls this
    #: far below its own reference rate, in one bucket.
    success: GateSpec = field(default_factory=lambda: GateSpec(enter=0.2, exit=0.12))

    #: The error gate fires when the refusal rate of the world's decision
    #: path rises by this much in one bucket.
    errors: GateSpec = field(default_factory=lambda: GateSpec(enter=0.8, exit=0.48))

    #: The spend gate fires when the cost per productive decision rises
    #: by this many multiples of the agent's own reference, in one bucket.
    spend: GateSpec = field(default_factory=lambda: GateSpec(enter=0.5, exit=0.3))

    #: The rule-violation gate is **not** a gate. It is here so that
    #: the configuration names every signal, and the detector ignores
    #: these numbers: one occurrence escalates immediately, with no
    #: threshold, no band and no dwell.
    violation: GateSpec = field(default_factory=lambda: GateSpec(enter=0.0, exit=0.0))

    # -- the hard signal ------------------------------------------------------
    #: A rule violation is zero tolerance: no threshold, no dwell, no
    #: band. One occurrence escalates immediately (§3.4).
    violation_is_hard: bool = True

    # -- the auto-pause ladder (§3.5) -----------------------------------------
    #: How many agents in alarm at once demotes the world's work from
    #: ``live`` to ``preparation``.
    tier_agents: int = 2

    # -- the reference --------------------------------------------------------
    #: ``reference`` freezes the baseline over the first
    #: ``baseline_horizon_seconds`` of the run. ``trailing`` follows
    #: the run. The lab uses ``reference``; ``trailing`` is there
    #: because it is the obvious wrong answer and the lab note says
    #: what it costs.
    baseline_mode: str = "reference"

    def with_thresholds(self, **kwargs: object) -> "DriftConfig":
        """A copy with some fields replaced."""
        return replace(self, **kwargs)  # type: ignore[arg-type]

    def gate_for(self, signal: str) -> GateSpec | None:
        """The gate spec for one signal, or ``None`` if it has none."""
        return getattr(self, signal, None)
