"""The confidence gate as policy: τ, the ladder, and the standing.

**The default is a measurement, not a taste.** Lab-cascade's E1 (folded
into ``docs/research/liquid-study.md`` §1.4) found that on the action
gate **every** d1-2B error sat below confidence 0.5 — above 0.5 the
model was 196/196 exactly right, and a gate at 0.5 caught 100 % of the
errors with 2 % of the traffic. So the policy is:

    **act at or above τ; escalate below** — τ per (backend, model,
    task), defaulting to E1's 0.5.

Escalation walks a configured ladder — the brief's: local d1-2B →
cloud Clef / Jev → a cloud LLM work order. A judgment still below τ at
the ladder's end is **surfaced, not acted on**: it is recorded, flagged,
and handed to whoever can act on it. (jev.md's rule, made mechanical:
*the tools advise; the core enforces* — and *low confidence on a
consequential call goes to the owner, with the numbers attached*.)

**Where a judgment drives a state that persists across ticks**, a raw
threshold flickers: each flap is a fact written, withdrawn, written
again. :class:`StandingGate` is that case, and it is not a new
mechanism — it wraps :mod:`core.hysteresis`, the gate built and
measured for exactly this, with the judgment's confidence as the
continuous signal and τ as the enter line. Its defaults are a
measurement too: the real d1 traces replayed through the gate chose
:class:`StandingConfig`'s band and dwells, and the replay is what
``docs/lab/exp-hysteresis-d1.md`` records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from core.hysteresis.gate import HysteresisGate, Level, Transition

from .backends import BackendReply, JudgeBackend

__all__ = [
    "DEFAULT_TAU",
    "DEFAULT_BAND",
    "DEFAULT_DWELL_UP",
    "DEFAULT_DWELL_DOWN",
    "StandingConfig",
    "ConfidencePolicy",
    "EscalationLadder",
    "StandingGate",
]


#: E1 (§1.4): all three of d1-2B's errors sat in the bottom confidence
#: band; above 0.5 it was 196/196. The default until a task's own
#: calibration says otherwise.
DEFAULT_TAU = 0.5

#: The adopted standing configuration, from the replay of the real d1
#: traces through the gate (`docs/lab/exp-hysteresis-d1.md`; the sweep
#: and its results JSON are beside the harness). At the traces'
#: calibrated τ the raw threshold flickers 66 times in 240 ticks on the
#: 2B recording; **band 0.15, dwell_up 2, dwell_down 0 leaves one** with
#: the raw gate's catch of the model's misreadings and its agreement
#: kept and both latency bounds met. The band holds the shallow wobble,
#: the dwell_up earns `act`, and a real drop is not delayed — the same
#: asymmetry the mechanism's own README argues for, mirrored for
#: escalation (the safety direction commits at once).
#:
#: The dwells are in **the caller's clock**: for the judge's per-tick
#: caller that is ticks of the decision loop (one tick, one judgment —
#: 2 ticks ≈ 64 ms of decision time on the rung-0 recording). A caller
#: whose clock is seconds passes its own numbers; that is what a
#: parameter with a default is for.
DEFAULT_BAND = 0.15
DEFAULT_DWELL_UP = 2.0
DEFAULT_DWELL_DOWN = 0.0


@dataclass(frozen=True)
class StandingConfig:
    """The standing's four numbers as one parameter, with the adopted default.

    ``tau`` is the enter line (E1's default until a task's own
    calibration names another), ``band`` is the width of the
    inside-which-nothing-moves region below it, and the two dwells are
    how long a change must be asked for before it commits, in the
    caller's clock. This is the configuration the trace replay chose;
    the sweep table in ``docs/lab/exp-hysteresis-d1.md`` is its record.
    """

    tau: float = DEFAULT_TAU
    band: float = DEFAULT_BAND
    dwell_up: float = DEFAULT_DWELL_UP
    dwell_down: float = DEFAULT_DWELL_DOWN

    def __post_init__(self) -> None:
        if not 0.0 < self.tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        if not 0.0 <= self.band < self.tau:
            raise ValueError("the band sits below tau and does not reach zero")
        if self.dwell_up < 0.0 or self.dwell_down < 0.0:
            raise ValueError("a dwell time is a duration")

    def standing_gate(self, name: str = "") -> "StandingGate":
        """The gate this configuration builds."""
        return StandingGate(
            tau=self.tau,
            band=self.band,
            dwell_up=self.dwell_up,
            dwell_down=self.dwell_down,
            name=name,
        )


class ConfidencePolicy:
    """τ per (backend, model, task), defaulting from E1.

    The lookup order is the key you named, then ``*`` wildcards for the
    task, then the default — so a task's own calibration (E1's T3
    cautions that the tiles task is not T1) overrides per backend and
    model without forking the policy.
    """

    def __init__(
        self,
        taus: Mapping[tuple[str, str, str], float] | None = None,
        default: float = DEFAULT_TAU,
    ) -> None:
        for key, tau in (taus or {}).items():
            if not 0.0 < tau <= 1.0:
                raise ValueError(f"tau for {key} is a rate in (0, 1]")
            if len(key) != 3:
                raise ValueError("a tau key is (backend, model, task)")
        self.taus = dict(taus or {})
        self.default = default

    def tau_for(self, backend: str, model: str, task: str) -> float:
        if (backend, model, task) in self.taus:
            return self.taus[(backend, model, task)]
        if (backend, model, "*") in self.taus:
            return self.taus[(backend, model, "*")]
        return self.default

    def decision(
        self,
        *,
        confidence: float | None,
        tau: float | None = None,
        backend: str = "",
        model: str = "",
        task: str = "",
    ) -> str:
        """``"act"`` or ``"escalate"`` for one confidence.

        Act **at or above** τ — E1's number is an exclusive-below result
        (196/196 at and above 0.5). A judgment with no confidence cannot
        pass a gate: it escalates, because treating ``None`` as
        confident would be the kind of silent default that biases
        nobody can see.
        """
        if tau is None:
            tau = self.tau_for(backend, model, task)
        if confidence is not None and confidence >= tau:
            return "act"
        return "escalate"


class EscalationLadder:
    """The backends a below-τ judgment is escalated through, in order.

    The brief's ladder: local d1-2B → cloud Clef / Jev → a cloud LLM
    work order. The last rung of that ladder is not a backend here — a
    work order is the work-order seat's record — so a judgment still
    below τ after the rungs are exhausted is what this package calls
    **surfaced**: recorded, flagged, not acted on.
    """

    def __init__(self, rungs: Sequence[tuple[str, JudgeBackend]]) -> None:
        if not rungs:
            raise ValueError("a ladder names at least one rung")
        self.rungs = tuple(rungs)

    def next_after(self, name: str) -> JudgeBackend | None:
        """The backend after ``name`` — ``None`` when the ladder is exhausted."""
        for index, (rung_name, _) in enumerate(self.rungs):
            if rung_name == name and index + 1 < len(self.rungs):
                return self.rungs[index + 1][1]
        return None


class StandingGate:
    """A judgment confidence driving a state that persists across ticks.

    This is :class:`core.hysteresis.gate.HysteresisGate` with the
    levels named for the policy — ``escalate`` below, ``act`` above —
    τ as the enter line, and a **band** of ``tau - band`` … ``tau``
    inside which the standing does not move. The clock is the caller's,
    exactly as the mechanism requires, so a trace replays to the same
    answer.

    The defaults are the **adopted configuration** — the standing
    config the real d1 traces chose (see :class:`StandingConfig`): pass
    nothing and the gate is the one the sweep's rule landed on; pass a
    ``config`` (or the four numbers) and yours governs. Per-tick callers
    pass ticks as ``now``; the adopted dwells are ticks.

    Gates are per subject (a tile, a question, a builder): ask with
    :meth:`step_for` or with the default subject via :meth:`step`.
    """

    def __init__(
        self,
        *,
        config: StandingConfig | None = None,
        tau: float = DEFAULT_TAU,
        band: float = DEFAULT_BAND,
        dwell_up: float = DEFAULT_DWELL_UP,
        dwell_down: float = DEFAULT_DWELL_DOWN,
        name: str = "",
    ) -> None:
        if config is not None:
            tau, band = config.tau, config.band
            dwell_up, dwell_down = config.dwell_up, config.dwell_down
        if not 0.0 < tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        if not 0.0 <= band < tau:
            raise ValueError("the band sits below tau and does not reach zero")
        self.tau = tau
        self.band = band
        self._gates: dict[str, HysteresisGate] = {}
        self._levels = (
            Level(name="escalate", enter=tau - band, exit=float("-inf")),
            Level(name="act", enter=tau, exit=tau - band),
        )
        self._dwell_up = dwell_up
        self._dwell_down = dwell_down
        self.name = name

    # -- the reads -------------------------------------------------------------

    @property
    def dwell_up(self) -> float:
        return self._dwell_up

    @property
    def dwell_down(self) -> float:
        return self._dwell_down

    @property
    def standing(self) -> str:
        """The default subject's standing."""
        return self._gate("").state

    def standing_for(self, subject: str) -> str:
        """One subject's standing."""
        return self._gate(subject).state

    # -- the step --------------------------------------------------------------

    def step(self, value: float, now: float) -> Transition:
        """Feed the default subject one confidence reading."""
        return self._gate("").step(value, now)

    def step_for(self, subject: str, value: float, now: float) -> Transition:
        """Feed one subject one confidence reading."""
        return self._gate(subject).step(value, now)

    def reset_for(self, subject: str) -> None:
        """Forget one subject's standing — back to the safe cold state."""
        self._gate(subject).reset()

    # -- internals -------------------------------------------------------------

    def _gate(self, subject: str) -> HysteresisGate:
        gate = self._gates.get(subject)
        if gate is None:
            gate = HysteresisGate(
                self._levels,
                dwell_up=self._dwell_up,
                dwell_down=self._dwell_down,
                name=f"{self.name}:{subject}" if self.name else subject,
            )
            self._gates[subject] = gate
        return gate
