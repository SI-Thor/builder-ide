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
continuous signal and τ as the enter line.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from core.hysteresis.gate import HysteresisGate, Level, Transition

from .backends import BackendReply, JudgeBackend

__all__ = ["DEFAULT_TAU", "ConfidencePolicy", "EscalationLadder", "StandingGate"]


#: E1 (§1.4): all three of d1-2B's errors sat in the bottom confidence
#: band; above 0.5 it was 196/196. The default until a task's own
#: calibration says otherwise.
DEFAULT_TAU = 0.5


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

    Gates are per subject (a tile, a question, a builder): ask with
    :meth:`step_for` or with the default subject via :meth:`step`.
    """

    def __init__(
        self,
        *,
        tau: float = DEFAULT_TAU,
        band: float = 0.1,
        dwell_up: float = 0.0,
        dwell_down: float = 0.0,
        name: str = "",
    ) -> None:
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
