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
    "SEA_STATE_TASK",
    "CALIBRATED_TAUS",
    "StandingConfig",
    "ConfidencePolicy",
    "EscalationLadder",
    "StandingGate",
]


#: E1 (§1.4): all three of d1-2B's errors sat in the bottom confidence
#: band; above 0.5 it was 196/196. The default until a task's own
#: calibration says otherwise.
DEFAULT_TAU = 0.5

#: The sea-state task the liquid study's §4.3 recorded — five-way
#: condition classification, 6 trials × 40 steps per model, one decision
#: per tick. It is the task the calibration below is measured on.
SEA_STATE_TASK = "sea-state.v1"

#: The measured τ per (backend, model, task) — the sweep's calibrated
#: τ* (``docs/lab/hysteresis-scripts/results/hysteresis-d1-sweep.json``;
#: the method is ``docs/lab/exp-hysteresis-d1.md`` §5: the best catch of
#: the model's misreadings subject to the rung still acting on at least
#: half the ticks). On the recorded traces a τ of 0.5 never fires on the
#: 2B's confidence at all — a gate at a τ the signal never crosses is
#: not a gate — and at the calibrated 0.7 the raw threshold flickers 66
#: times in 240 ticks. This table ships as the default: a calibrated
#: pair is judged at its measured τ, an uncalibrated pair falls back to
#: :data:`DEFAULT_TAU` until its own calibration lands here.
CALIBRATED_TAUS: dict[tuple[str, str, str], float] = {
    ("d1", "d1-2B", SEA_STATE_TASK): 0.7,
    ("d1", "d1-3B", SEA_STATE_TASK): 0.7,
}

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
    """τ per (backend, model, task), defaulting from the shipped calibration.

    The lookup order is the key you named, then ``*`` wildcards for the
    task, then the default — so a task's own calibration (E1's T3
    cautions that the tiles task is not T1) overrides per backend and
    model without forking the policy. The shipped
    :data:`CALIBRATED_TAUS` sit under whatever the caller names, so the
    measured default and the caller's override are one table.
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
        self.taus = {**CALIBRATED_TAUS, **(taus or {})}
        self.default = default

    def tau_for(self, backend: str, model: str, task: str) -> float:
        if (backend, model, task) in self.taus:
            return self.taus[(backend, model, task)]
        if (backend, model, "*") in self.taus:
            return self.taus[(backend, model, "*")]
        return self.default

    def source_for(self, backend: str, model: str, task: str) -> str:
        """Where the pair's τ came from — ``"calibrated"`` or ``"default"``.

        The row carries it (``tau_source``): a log that does not say
        which bound a decision was judged under cannot be audited.
        """
        if (backend, model, task) in self.taus or (backend, model, "*") in self.taus:
            return "calibrated"
        return "default"

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

    **The τ is a bound, and the bound is a measurement.** Pass a
    ``config`` or an explicit ``tau`` and yours governs (the row says
    ``configured``); pass nothing — the default — and the τ is resolved
    per ask from the shipped :data:`CALIBRATED_TAUS` for the (backend,
    model, task) the Judge's first rung names, falling back to
    :data:`DEFAULT_TAU` for an uncalibrated pair (the row says
    ``calibrated`` or ``default``). The shape — band and dwells — stays
    the adopted configuration the sweep chose.

    The bound τ rides per **subject**: each question id's gate is built
    at the τ its first reading was judged under, and a later ask that
    resolves a different τ for that subject is refused rather than
    silently re-binding it. That is what makes the standing
    reconstructable: the τ each decision was judged under is in the row,
    and :meth:`bind_subject` puts it back.

    Gates are per subject (a tile, a question, a builder): ask with
    :meth:`step_for` or with the default subject via :meth:`step`.
    """

    def __init__(
        self,
        *,
        config: StandingConfig | None = None,
        tau: float | None = None,
        band: float = DEFAULT_BAND,
        dwell_up: float = DEFAULT_DWELL_UP,
        dwell_down: float = DEFAULT_DWELL_DOWN,
        name: str = "",
    ) -> None:
        if config is not None:
            tau = config.tau
            band, dwell_up = config.band, config.dwell_up
            dwell_down = config.dwell_down
        if tau is not None and not 0.0 < tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        if band < 0.0 or (tau is not None and not 0.0 <= band < tau):
            raise ValueError("the band sits below tau and does not reach zero")
        #: ``None`` until bound: the τ is resolved per ask from the
        #: shipped calibration (or the caller's own policy), never a
        #: silent wall-clock-style default.
        self.tau = tau
        self.band = band
        self._gates: dict[str, HysteresisGate] = {}
        self._subject_tau: dict[str, float] = {}
        self._current_tau: float | None = None
        self._dwell_up = dwell_up
        self._dwell_down = dwell_down
        self.name = name

    # -- the τ -----------------------------------------------------------------

    def tau_for(self, backend: str, model: str, task: str) -> tuple[float, str]:
        """The τ this gate would bind for the pair, and where it came from.

        An explicitly bound τ is ``"configured"``; otherwise the shipped
        calibration answers (``"calibrated"``), then
        :data:`DEFAULT_TAU` (``"default"``). The Judge resolves the τ
        through its own policy first — the policy carries the caller's
        taus too — so this is the direct user's path.
        """
        if self.tau is not None:
            return self.tau, "configured"
        if (backend, model, task) in CALIBRATED_TAUS:
            return CALIBRATED_TAUS[(backend, model, task)], "calibrated"
        if (backend, model, "*") in CALIBRATED_TAUS:
            return CALIBRATED_TAUS[(backend, model, "*")], "calibrated"
        return DEFAULT_TAU, "default"

    def bind_tau(self, tau: float) -> None:
        """Bind the τ subjects stepped from now on are gated by.

        The Judge calls this once per ask, with the τ its policy (or the
        shipped calibration) resolved for the rung. It does not move a
        subject already bound — :meth:`_gate` refuses that — because a
        standing judged at one τ cannot be re-bound mid-history without
        the row and the gate disagreeing.
        """
        if not 0.0 < tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        self._current_tau = tau

    def bind_subject(self, subject: str, tau: float) -> None:
        """Bind one subject's gate at τ — the rebuild's way to put the
        row's calibrated bound back.

        A subject already bound to another τ is a divergence the caller
        must see, not a silent re-bind.
        """
        if not 0.0 < tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        bound = self._subject_tau.get(subject)
        if bound is not None and bound != tau:
            raise ValueError(
                f"subject {subject!r} was judged at τ {bound} and this "
                f"rebuild binds {tau} — the bound moved under it"
            )
        self._subject_tau[subject] = tau

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
        return self.standing_for("")

    def standing_for(self, subject: str) -> str:
        """One subject's standing — the cold ``escalate`` before a binding."""
        gate = self._gates.get(subject)
        return gate.state if gate is not None else "escalate"

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

    def _levels_at(self, tau: float) -> tuple[Level, Level]:
        if not 0.0 < tau <= 1.0:
            raise ValueError("tau is a rate in (0, 1]")
        if not 0.0 <= self.band < tau:
            raise ValueError("the band sits below tau and does not reach zero")
        return (
            Level(name="escalate", enter=tau - self.band, exit=float("-inf")),
            Level(name="act", enter=tau, exit=tau - self.band),
        )

    def _gate(self, subject: str) -> HysteresisGate:
        gate = self._gates.get(subject)
        if gate is None:
            tau = self._subject_tau.get(subject)
            if tau is None:
                tau = self._current_tau
            if tau is None:
                tau = self.tau_for("", "", "")[0]
            self._subject_tau[subject] = tau
            gate = HysteresisGate(
                self._levels_at(tau),
                dwell_up=self._dwell_up,
                dwell_down=self._dwell_down,
                name=f"{self.name}:{subject}" if self.name else subject,
            )
            self._gates[subject] = gate
        elif (
            self._current_tau is not None
            and self._subject_tau.get(subject) != self._current_tau
        ):
            raise ValueError(
                f"subject {subject!r} is bound to τ "
                f"{self._subject_tau.get(subject)} and this ask binds "
                f"{self._current_tau} — a standing is not re-bound "
                "mid-history; reset it or wire another"
            )
        return gate
