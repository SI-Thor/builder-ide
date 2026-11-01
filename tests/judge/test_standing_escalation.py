"""The escalation trigger, routed through the hysteresis standing.

The brief's wiring: where a judgment drives a state that persists across
ticks — the ladder's act-or-escalate trigger — the decision follows the
:class:`StandingGate`, not the per-tick τ comparison. The two behaviours
under test are the brief's own:

* **a wandering confidence no longer flips the standing state** — the
  signal crosses τ tick after tick and the ladder does not flap;
* **a real drop still escalates within the latency bound** — a sustained
  fall below the exit line reaches the next rung inside two ticks.

And the record rule that carries them: the standing's word is on every
row, because a log that needs a computation to say what governed is a log
that lies by omission.
"""

from __future__ import annotations

import pytest

from core.judge.backends import BackendReply
from core.judge.gate import EscalationLadder, StandingConfig, StandingGate
from core.judge.judge import Judge, fold_judgments
from core.judge.models import JudgeCost, Question
from core.night.ledger import InMemoryLedger

TILES = Question(
    qid="tile",
    kind="choice",
    instructions="Which tile?",
    criteria={"plain": "plain crates", "weathered": "weathered crates", "stained": "stained crates"},
)

#: A confidence series with the recorded 2B trace's shape: three
#: confident ticks (the standing warms into ``act`` — the adopted
#: ``dwell_up`` is 2), then a wander across τ that never falls below the
#: exit line (τ − band = 0.35). The raw τ gate flips on every sub-τ tick
#: of the wander; the standing holds.
WANDER = [0.9, 0.9, 0.9, 0.55, 0.42, 0.55, 0.42, 0.55, 0.42]

#: The same shape with a real drop at the end: three ticks below the
#: exit line, sustained. The drop is a third of the mass — the model
#: cannot choose between the three options — because the confidence is the
#: top probability of a distribution that sums to one, and a third is the
#: smallest top probability a three-option question can have.
DROP = [0.9, 0.9, 0.9, 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]


class SeriesBackend:
    """A local rung whose top-probability confidence plays a fixed series."""

    name = "d1"
    model = "d1-2B"

    def __init__(self, series):
        self._series = iter(series)
        self.calls: list[list[str]] = []

    def ask(self, state, questions):
        self.calls.append([q.qid for q in questions])
        value = next(self._series)
        return BackendReply(
            backend=self.name,
            model=self.model,
            # a distribution that sums to one, with the series value as the
            # top probability — what a real head returns, and what the
            # canonical confidence (the top probability) reads
            distributions={
                q.qid: {
                    "plain": value,
                    "weathered": (1.0 - value) / 2,
                    "stained": (1.0 - value) / 2,
                }
                for q in questions
            },
            confidences={q.qid: value for q in questions},
            input_tokens=1,
            wall_seconds=0.001,
        )

    def cost_of(self, reply):
        return JudgeCost(wall_seconds=reply.wall_seconds, input_tokens=1)


class JevoBackend:
    """The cloud rung: confident, and it records who asks."""

    name = "jev"
    model = "jev-latest"

    def __init__(self):
        self.calls: list[list[str]] = []

    def ask(self, state, questions):
        self.calls.append([q.qid for q in questions])
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions={q.qid: {"plain": 0.8, "weathered": 0.1, "stained": 0.1} for q in questions},
            confidences={q.qid: 0.8 for q in questions},
            input_tokens=1,
            wall_seconds=0.001,
        )

    def cost_of(self, reply):
        return JudgeCost(wall_seconds=reply.wall_seconds, input_tokens=1)


def _wired_with_ladder(series, *, standing=None, ledger=None):
    d1 = SeriesBackend(series)
    jev = JevoBackend()
    judge = Judge(
        backend=d1,
        ladder=EscalationLadder([("jev", jev)]),
        ledger=ledger or InMemoryLedger(),
        standing=standing,
    )
    return judge, d1, jev


# --- the clock ---------------------------------------------------------------


def test_a_standing_needs_the_caller_s_clock():
    """The standing's clock is the caller's — no silent wall-clock default."""
    judge, _, _ = _wired_with_ladder(WANDER, standing=StandingGate())
    with pytest.raises(ValueError):
        judge.judge("tiles.shortlist", "state", (TILES,))


# --- the wander --------------------------------------------------------------


def test_a_wandering_confidence_no_longer_flips_the_standing_state(ledger):
    """The brief's first wired behaviour, through the ladder.

    Same series, two wirings: the raw τ gate escalates on every sub-τ
    tick of the wander (each flap a rung-1 call, a fact written and
    withdrawn); the standing escalates only through its warm-up, then
    holds `act` across the whole wander and the ladder never flaps.
    """
    raw_judge, _, raw_jev = _wired_with_ladder(WANDER)
    for tick in range(len(WANDER)):
        raw_judge.judge("tiles.shortlist", "state", (TILES,), now=tick)
    assert len(raw_jev.calls) >= 3  # the raw gate flapped to the cloud rung

    standing = StandingGate()
    wired_judge, _, wired_jev = _wired_with_ladder(WANDER, standing=standing, ledger=ledger)
    answers = [
        wired_judge.judge("tiles.shortlist", "state", (TILES,), now=tick)
        for tick in range(len(WANDER))
    ]
    # the warm-up escalates (a cold standing is the safe one); the wander
    # escalates nothing
    warm_up_calls = len(wired_jev.calls)
    assert warm_up_calls == 2
    for answer in answers[3:]:
        assert answer.judgments[0].backend == "d1"
        assert answer.standing_words["tile"] == "act"
        assert answer.surfaced is False  # the standing governed it to act
    assert len(wired_jev.calls) == warm_up_calls
    assert standing.standing_for("tile") == "act"


# --- the real drop -----------------------------------------------------------


def test_a_real_drop_still_escalates_within_the_latency_bound(ledger):
    """The brief's second wired behaviour, through the ladder.

    After three confident ticks the confidence falls below the exit line
    and stays there: the standing commits within the bound — on the
    first below-exit reading with the adopted dwell_down of zero — and
    the next rung answers from that tick on.
    """
    standing = StandingGate()
    judge, d1, jev = _wired_with_ladder(DROP, standing=standing, ledger=ledger)
    answers = [
        judge.judge("tiles.shortlist", "state", (TILES,), now=tick)
        for tick in range(len(DROP))
    ]
    # the drop tick is index 3; the escalation is there or within the
    # bound's two ticks, and from then on the cloud rung governs
    governing = [answer.judgments[0].backend for answer in answers]
    assert governing[4] == "jev"
    assert governing[-1] == "jev"
    assert standing.standing_for("tile") == "escalate"
    # and the local row for the drop tick stays on the log, marked
    # escalated away from
    rows = fold_judgments(ledger.events())
    d1_rows = [row for row in rows if row["backend"] == "d1"]
    assert any(row["escalated"] for row in d1_rows)


def test_a_down_dwell_delays_the_escalation_but_not_past_the_bound(ledger):
    """A configured dwell_down is served before the commitment lands —
    and the bound (two ticks) is not exceeded."""
    standing = StandingGate(config=StandingConfig(dwell_up=0.0, dwell_down=2.0))
    judge, _, jev = _wired_with_ladder(DROP, standing=standing, ledger=ledger)
    answers = [
        judge.judge("tiles.shortlist", "state", (TILES,), now=tick)
        for tick in range(len(DROP))
    ]
    governing = [answer.judgments[0].backend for answer in answers]
    # tick 3 is the drop; the dwell serves two ticks, so the escalation
    # lands at tick 5 — exactly the bound
    assert governing[3] == "d1"
    assert governing[5] == "jev"
    assert standing.standing_for("tile") == "escalate"


# --- the record --------------------------------------------------------------


def test_the_standing_s_word_is_on_every_row(ledger):
    standing = StandingGate()
    judge, _, _ = _wired_with_ladder(WANDER, standing=standing, ledger=ledger)
    for tick in range(len(WANDER)):
        judge.judge("tiles.shortlist", "state", (TILES,), now=tick)
    rows = fold_judgments(ledger.events())
    assert rows
    assert all("standing" in row for row in rows)
    # a row from the held wander says the standing governed it to act
    held = [row for row in rows if row["standing"] == "act"]
    assert held


def test_a_standing_escalated_judgment_at_the_ladder_s_end_is_surfaced(ledger):
    """A cold standing escalates a confident judgment at the ladder's
    end: the raw gate would say act (the confidence clears τ), the
    standing says escalate, and the answer's contract — surfaced, not
    acted on — follows the standing."""
    standing = StandingGate()  # cold: act needs dwell_up=2 of sustained τ
    d1 = SeriesBackend([0.9])
    judge = Judge(backend=d1, ledger=ledger, standing=standing)
    answer = judge.judge("tiles.shortlist", "state", (TILES,), now=0)
    assert answer.surfaced is True
    assert answer.standing_words["tile"] == "escalate"
    (row,) = fold_judgments(ledger.events())
    assert row["standing"] == "escalate"


def test_a_backend_with_no_confidence_of_its_own_still_gates_on_the_distribution(ledger):
    """A backend that reports no confidence of its own does not stop the gate.

    The confidence is computed from the distribution the backend returned —
    one definition, for every backend — so it is there even when the backend
    reports nothing of its own. The gate acts on what the model actually
    said. The old rule, a judgment with no confidence at all never passing,
    still holds for a judgment that has none: the policy's own test covers
    it, and a row folded from an older log is judged on the number it
    carries.
    """

    class NoConfidenceBackend(SeriesBackend):
        def ask(self, state, questions):
            self.calls.append([q.qid for q in questions])
            reply = super().ask(state, questions)
            return BackendReply(
                backend=self.name,
                model=self.model,
                distributions=reply.distributions,
                confidences={q.qid: None for q in questions},
                input_tokens=1,
                wall_seconds=0.001,
            )

    standing = StandingGate()
    d1 = NoConfidenceBackend([0.9, 0.9, 0.9])
    jev = JevoBackend()
    judge = Judge(
        backend=d1,
        ladder=EscalationLadder([("jev", jev)]),
        ledger=ledger,
        standing=standing,
    )
    answer = judge.judge("tiles.shortlist", "state", (TILES,), now=0)
    # the local rung's answer was confident on its own distribution, but the
    # standing is cold: it escalates, and the cloud rung governs
    assert answer.judgments[0].backend == "jev"
    assert standing.standing_for("tile") == "escalate"
    (row,) = [row for row in fold_judgments(ledger.events()) if row["backend"] == "d1"]
    # the standing took a reading — the distribution gave it one
    assert row["standing"] == "escalate"
    # and the row says which definition the confidence was computed under
    assert row["judgment"].confidence_definition == "top_probability"
    assert row["judgment"].backend_confidence is None
    assert row["judgment"].confidence == pytest.approx(0.9)
