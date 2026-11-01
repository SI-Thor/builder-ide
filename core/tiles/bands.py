"""Pincher's score bands, held by the hysteresis gate: execute, confirm, compile.

**The idea this seat borrowed.** The reflex engine in `quilt-pincher` does not
use a threshold. It uses a *band*, and the band has three names:

    score ≥ 0.80  →  execute it now;
    0.55 – 0.80   →  confirm it, then run it;
    score < 0.55  →  the library has nothing for this: compile a new one.

The three numbers are pincher's defaults, measured in *his* embedding space.
They are not ours, and this module does not pretend otherwise: the
thresholds are a parameter (:class:`BandConfig`), and
``docs/lab/exp-tiles-retrieval.md`` records what our own scores do to them.

**Why a gate and not a threshold.** A raw threshold flickers. A tile's
similarity score is a measurement with noise in it; a score that sits on the
line crosses it, and every crossing is a state change — a tile played
without confirmation, then not, then again. The gate in :mod:`core.hysteresis`
is the mechanism built and measured for exactly this: **split thresholds**
(each level has an enter line and an exit line, and the gap between them is
where nothing moves) plus an optional **dwell** (a change has to be asked
for before it commits).

So the bands are not a new mechanism; they are
:class:`core.hysteresis.HysteresisGate` with the levels named for the policy.
The same way :class:`core.judge.StandingGate` holds the judge's escalation,
this holds the retrieval's standing — and the hysteresis package owns no
tile-specific meaning, exactly as it owns no judge-specific meaning.

**The three levels, and what each one means here.**

* ``execute`` — the score says this tile is what the game asked for. Play
  it, without asking.
* ``confirm`` — the score says it *might* be. Play it, but mark the play as
  one that was confirmed rather than executed outright: the record says the
  fast path did not apply.
* ``compile`` — the score says the library has nothing for this. **Nothing
  is played.** A request goes to the cloud author for a new tile
  (:mod:`core.tiles.author`), and the tile that comes back joins the
  library as the family's next version. Playing the closest wrong tile here
  is the failure mode the band exists to prevent.

**A cold subject starts in ``compile``.** The gate starts in its lowest
level, and the lowest level here is the safe one: a tile nobody has scored
yet is not executed on a cold reading. It is confirmed or compiled, and the
first reading puts it where it belongs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.hysteresis.gate import HysteresisGate, Level

__all__ = [
    "DEFAULT_TAU_HI",
    "DEFAULT_TAU_LO",
    "DEFAULT_BAND",
    "DEFAULT_DWELL_UP",
    "DEFAULT_DWELL_DOWN",
    "BAND_EXECUTE",
    "BAND_CONFIRM",
    "BAND_COMPILE",
    "BandConfig",
    "BandDecision",
    "BandGate",
]


#: Pincher's own numbers (``docs/research/pincher-fit.md``): at or above
#: this the reflex is executed outright.
DEFAULT_TAU_HI = 0.80

#: Pincher's own number: below this the library has nothing for the request
#: and a new one is compiled.
DEFAULT_TAU_LO = 0.55

#: The width of the region under the high line inside which the standing
#: does not move. A score that wobbles across 0.80 does not flip the band,
#: which is the flicker the gate exists for.
#:
#: The width has to satisfy two rules, and both are enforced in
#: :class:`BandConfig`: it must not reach down to the low line (a band that
#: does would swallow the confirm level), and it must be wide enough to
#: hold the wobble the gate is there to hold.
DEFAULT_BAND = 0.05

#: How long a change has to be asked for before it commits, in the caller's
#: clock. Zero by default: a retrieval score is a fresh measurement on every
#: call, not a signal that drifts, so there is nothing to wait for. The
#: judge's gate uses a dwell because a judgment is a stream of ticks; this
#: one is a per-request reading.
DEFAULT_DWELL_UP = 0.0
DEFAULT_DWELL_DOWN = 0.0

#: The three bands, in the order the gate holds them (lowest first).
BAND_COMPILE = "compile"
BAND_CONFIRM = "confirm"
BAND_EXECUTE = "execute"


@dataclass(frozen=True)
class BandConfig:
    """The band policy as one parameter, with pincher's defaults.

    ``tau_hi`` is the execute line and ``tau_lo`` the compile line; the gap
    between them is the confirm band. ``band`` is the width under the
    execute line inside which the standing holds, and it must not reach the
    compile line — otherwise there would be no confirm band left to hold.
    """

    tau_hi: float = DEFAULT_TAU_HI
    tau_lo: float = DEFAULT_TAU_LO
    band: float = DEFAULT_BAND
    dwell_up: float = DEFAULT_DWELL_UP
    dwell_down: float = DEFAULT_DWELL_DOWN

    def __post_init__(self) -> None:
        if not 0.0 < self.tau_hi <= 1.0:
            raise ValueError("tau_hi is a rate in (0, 1]")
        if not 0.0 <= self.tau_lo < self.tau_hi:
            raise ValueError(
                "tau_lo is below tau_hi: the compile line is under the "
                "execute line, and a band with no gap in it is not a band"
            )
        if not 0.0 <= self.band:
            raise ValueError("the band is a width")
        if self.tau_hi - self.band <= self.tau_lo:
            raise ValueError(
                f"the band ({self.band}) reaches the low line ({self.tau_lo}): "
                "the standing would hold across the whole gap and the "
                "confirm band would never be entered"
            )
        if self.dwell_up < 0.0 or self.dwell_down < 0.0:
            raise ValueError("a dwell time is a duration")

    def levels(self) -> tuple[Level, ...]:
        """The gate's levels, lowest first.

        Each level's ``exit`` is the line under it that leaves the level;
        the gap between that line and the next level's ``enter`` is where
        the standing holds.
        """
        return (
            Level(name=BAND_COMPILE, enter=self.tau_lo, exit=float("-inf")),
            Level(name=BAND_CONFIRM, enter=self.tau_lo, exit=self.tau_lo - self.band),
            Level(name=BAND_EXECUTE, enter=self.tau_hi, exit=self.tau_hi - self.band),
        )


@dataclass(frozen=True)
class BandDecision:
    """What the band said, and what it was reading.

    ``band`` is the standing after this reading: ``execute``, ``confirm`` or
    ``compile``. ``score`` is the number the reading was made from, kept so
    a decision can be re-read later without the gate.

    ``changed`` is True when the standing moved — **or when this reading
    set it for the first time**. A band that has never been read has not
    been held by anything yet, and the first reading is what puts it
    somewhere; after that, only a real move counts.
    """

    band: str
    score: float
    changed: bool
    #: The band the score is asking for, whether or not it was committed.
    target: str = ""
    #: How long the target has been asking, in the caller's clock.
    pending_for: float = 0.0
    #: How long the committed band waited for its target, when it just moved.
    latency: float | None = None

    @property
    def executes(self) -> bool:
        """True when the fast path applies: the tile is played as it stands."""
        return self.band == BAND_EXECUTE

    @property
    def confirms(self) -> bool:
        """True when the tile is played, but marked as confirmed."""
        return self.band == BAND_CONFIRM

    @property
    def compiles(self) -> bool:
        """True when nothing is played and a new tile is asked for."""
        return self.band == BAND_COMPILE

    def line(self) -> str:
        """The one line the log can show."""
        return f"{self.band} at {self.score:.4f}"


class BandGate:
    """The retrieval score, driving a standing that persists.

    Per subject, like :class:`core.judge.StandingGate`: a tile that scores
    badly in one context does not drag the band down in another. The subject
    here is the tile, so the standing is a property of "this tile, in this
    context" — a caller that wants per (tile, context) standing passes a
    key that says so.

    The clock is the caller's. The gate has no time of its own, because a
    gate that keeps its own time cannot be replayed: the same readings in
    the same order give the same bands, on any machine, tomorrow.
    """

    def __init__(self, config: BandConfig | None = None, *, name: str = "") -> None:
        self.config = config if config is not None else BandConfig()
        self.name = name
        self._gates: dict[str, HysteresisGate] = {}
        self._read: set[str] = set()

    # -- the reads -------------------------------------------------------------

    @property
    def tau_hi(self) -> float:
        return self.config.tau_hi

    @property
    def tau_lo(self) -> float:
        return self.config.tau_lo

    @property
    def band(self) -> float:
        return self.config.band

    def standing_for(self, subject: str) -> str:
        """One subject's standing. A cold subject stands in ``compile``."""
        return self._gate(subject).state

    def standing(self) -> str:
        """The default subject's standing."""
        return self.standing_for("")

    # -- the step --------------------------------------------------------------

    def step_for(self, subject: str, score: float, now: float) -> BandDecision:
        """Feed one subject one score and get the band back.

        The score is the retrieval's similarity — a number in [0, 1] — and
        ``now`` is the caller's clock.
        """
        gate = self._gate(subject)
        transition = gate.step(float(score), now)
        first_reading = subject not in self._read
        self._read.add(subject)
        return BandDecision(
            band=transition.state,
            score=float(score),
            changed=transition.changed or first_reading,
            target=transition.target,
            pending_for=transition.pending_for,
            latency=transition.latency,
        )

    def step(self, score: float, now: float) -> BandDecision:
        """Feed the default subject one score."""
        return self.step_for("", score, now)

    def reset_for(self, subject: str) -> None:
        """Forget one subject's standing — back to the safe cold state."""
        self._gate(subject).reset()
        self._read.discard(subject)

    def reset(self) -> None:
        """Forget every subject's standing."""
        for gate in self._gates.values():
            gate.reset()
        self._read.clear()

    def state(self) -> dict[str, Any]:
        """What the gate holds, for the morning's report."""
        return {
            "name": self.name,
            "tau_hi": self.tau_hi,
            "tau_lo": self.tau_lo,
            "band": self.band,
            "subjects": {subject: self.standing_for(subject) for subject in sorted(self._gates)},
        }

    # -- internals -------------------------------------------------------------

    def _gate(self, subject: str) -> HysteresisGate:
        gate = self._gates.get(subject)
        if gate is None:
            gate = HysteresisGate(
                self.config.levels(),
                dwell_up=self.config.dwell_up,
                dwell_down=self.config.dwell_down,
                name=f"{self.name}:{subject}" if self.name else subject,
            )
            self._gates[subject] = gate
        return gate
