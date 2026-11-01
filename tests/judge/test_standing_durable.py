"""The standing is calibrated, and it survives a restart.

The review's second failure: ``Judge(standing=StandingGate())`` shipped
``DEFAULT_TAU`` (0.5) while the 66 → 1 flicker result was measured at the
traces' calibrated τ of 0.7; and the standing's dwell counters, last
standing and bound τ lived in memory only — a restart, a new process or
a clock jump lost them, and the ledger's ``standing_words`` could not be
reproduced. The fix, in three pieces:

* the measured τ per (backend, model, task) ships as the default
  (``CALIBRATED_TAUS``, from the committed sweep), with ``DEFAULT_TAU``
  as the fallback for uncalibrated pairs — and every row says which
  bound it was judged under (``tau_source``);
* every standing-governed row carries what fed the gate — the
  confidence (in the judgment), the tick, the τ, the band and the
  dwells — so the standing is replayable from the log alone;
* :func:`standing_from_rows` rebuilds the standing from
  ``fold_judgments(ledger.events())``, replaying each row through a
  fresh gate and refusing a row whose recorded word the replay cannot
  reproduce — a log that cannot be replayed is a log that cannot be
  trusted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.judge.backends import BackendReply
from core.judge.gate import (
    CALIBRATED_TAUS,
    DEFAULT_BAND,
    DEFAULT_DWELL_DOWN,
    DEFAULT_DWELL_UP,
    DEFAULT_TAU,
    SEA_STATE_TASK,
    ConfidencePolicy,
    StandingConfig,
    StandingGate,
)
from core.judge.judge import Judge, fold_judgments, standing_from_rows
from core.judge.models import JudgeCost, Question
from core.night.ledger import InMemoryLedger

SWEEP = (
    Path(__file__).resolve().parents[2]
    / "docs/lab/hysteresis-scripts/results/hysteresis-d1-sweep.json"
)

SEA_STATE = Question(
    qid="condition",
    kind="choice",
    instructions="Which sea condition is shown?",
    criteria={"A": "one", "B": "two", "C": "three", "D": "four", "E": "five"},
)


class SeriesBackend:
    """A d1-shaped rung whose confidence plays a fixed series, in order."""

    name = "d1"
    model = "d1-2B"

    def __init__(self, series, offset: int = 0):
        self._series = list(series)
        self._offset = offset
        self.calls: list[list[str]] = []

    def ask(self, state, questions):
        self.calls.append([q.qid for q in questions])
        value = self._series[self._offset]
        self._offset += 1
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions={q.qid: {"A": value, "B": 1.0 - value} for q in questions},
            confidences={q.qid: value for q in questions},
            input_tokens=1,
            wall_seconds=0.001,
        )

    def cost_of(self, reply):
        return JudgeCost(wall_seconds=reply.wall_seconds, input_tokens=1)


# --- the shipped calibration --------------------------------------------------


def test_the_shipped_calibration_is_the_sweep_s_tau_star():
    """The table is the measurement: one entry per (backend, model, task)
    the sweep calibrated, at exactly the τ* the committed results name."""
    sweep = json.loads(SWEEP.read_text())
    for model in ("d1-2B", "d1-3B"):
        tau_star = sweep["models"][model]["chosen"]["tau_star"]
        assert CALIBRATED_TAUS[("d1", model, SEA_STATE_TASK)] == tau_star


def test_the_default_standing_resolves_the_tau_per_pair():
    gate = StandingGate()
    # the calibrated pair binds the sweep's τ
    assert gate.tau_for("d1", "d1-2B", SEA_STATE_TASK) == (0.7, "calibrated")
    # an uncalibrated pair falls back to E1's default, and says so
    assert gate.tau_for("d1", "d1-2B", "tiles.shortlist") == (DEFAULT_TAU, "default")
    assert gate.tau_for("jev", "jev-latest", SEA_STATE_TASK) == (DEFAULT_TAU, "default")
    # an explicitly bound τ is the caller's, and says so
    assert StandingGate(tau=0.6).tau_for("d1", "d1-2B", SEA_STATE_TASK) == (
        0.6,
        "configured",
    )


def test_the_policy_ships_the_calibration_as_its_default():
    policy = ConfidencePolicy()
    assert policy.tau_for("d1", "d1-2B", SEA_STATE_TASK) == 0.7
    assert policy.source_for("d1", "d1-2B", SEA_STATE_TASK) == "calibrated"
    assert policy.tau_for("d1", "d1-2B", "other.task") == DEFAULT_TAU
    assert policy.source_for("d1", "d1-2B", "other.task") == "default"
    # a caller's own calibration wins over the shipped one
    override = ConfidencePolicy(taus={("d1", "d1-2B", SEA_STATE_TASK): 0.65})
    assert override.tau_for("d1", "d1-2B", SEA_STATE_TASK) == 0.65
    assert override.source_for("d1", "d1-2B", SEA_STATE_TASK) == "calibrated"


def test_the_judge_binds_the_calibrated_tau_and_says_so_in_the_row(ledger):
    judge = Judge(
        backend=SeriesBackend([0.9] * 4),
        standing=StandingGate(),
        ledger=ledger,
    )
    answer = judge.judge(SEA_STATE_TASK, "state", (SEA_STATE,), now=0)
    (row,) = fold_judgments(ledger.events())
    assert row["tau"] == 0.7
    assert row["tau_source"] == "calibrated"
    assert row["standing_governed"] is True
    assert row["tick"] == 0
    assert row["standing_config"] == {
        "tau": 0.7,
        "band": DEFAULT_BAND,
        "dwell_up": DEFAULT_DWELL_UP,
        "dwell_down": DEFAULT_DWELL_DOWN,
    }
    assert answer.judgments[0].tau == 0.7


def test_an_uncalibrated_pair_says_default_in_the_row(ledger):
    pair = Question(
        qid="condition",
        kind="choice",
        instructions="Which condition?",
        criteria={"A": "one", "B": "two"},
    )
    judge = Judge(
        backend=SeriesBackend([0.9] * 4),
        standing=StandingGate(),
        ledger=ledger,
    )
    judge.judge("tiles.shortlist", "state", (pair,), now=0)
    (row,) = fold_judgments(ledger.events())
    assert row["tau"] == DEFAULT_TAU
    assert row["tau_source"] == "default"


# --- the rebuild --------------------------------------------------------------


def _run(series, ledger, *, standing=None, split_at=None):
    """Play a confidence series through a standing-wired judge, tick by
    tick; when ``split_at`` is given, rebuild the standing from the
    ledger there and continue with a fresh judge — the restart."""
    words = []
    first = SeriesBackend(series[:split_at] if split_at is not None else series)
    judge = Judge(backend=first, standing=standing or StandingGate(), ledger=ledger)
    for tick in range(len(series)):
        if split_at is not None and tick == split_at:
            standing = standing_from_rows(fold_judgments(ledger.events()))
            judge = Judge(
                backend=SeriesBackend(series, offset=split_at),
                standing=standing,
                ledger=ledger,
            )
        answer = judge.judge(SEA_STATE_TASK, f"state at {tick}", (SEA_STATE,), now=tick)
        words.append(answer.standing_words[SEA_STATE.qid])
    return words, judge.standing


#: A series with the recorded trace's shape: warm-up, a wander across τ
#: that never falls below the exit line, then a real sustained drop.
SERIES = [0.9, 0.9, 0.9, 0.55, 0.42, 0.55, 0.42, 0.55, 0.6, 0.9, 0.9, 0.3, 0.3, 0.3]


def test_a_standing_rebuilds_from_the_ledger_and_continues_exactly(ledger):
    control_words, control_gate = _run(SERIES, InMemoryLedger())

    ledger = InMemoryLedger()
    restart_words, restart_gate = _run(
        SERIES, ledger, split_at=len(SERIES) // 2
    )

    assert restart_words == control_words
    assert restart_gate.standing_for(SEA_STATE.qid) == control_gate.standing_for(
        SEA_STATE.qid
    )


def test_the_rebuild_replays_every_row_and_refuses_a_divergence(ledger):
    _run(SERIES[:6], ledger)
    rows = fold_judgments(ledger.events())
    assert any(row["judgment"] is not None for row in rows)
    # tamper with one recorded word: the replay can no longer reproduce it
    tampered = [dict(row) for row in rows]
    for row in tampered:
        if row["judgment"] is not None and row["standing"] == "escalate":
            row["standing"] = "act"
            break
    with pytest.raises(ValueError, match="replay"):
        standing_from_rows(tampered)


def test_the_rebuild_refuses_a_null_confidence_tick_that_moved_the_standing(ledger):
    class NoConfidenceBackend(SeriesBackend):
        def ask(self, state, questions):
            reply = super().ask(state, questions)
            return BackendReply(
                backend=self.name,
                model=self.model,
                distributions=reply.distributions,
                confidences={q.qid: None for q in questions},
                input_tokens=1,
                wall_seconds=reply.wall_seconds,
            )

    judge = Judge(
        backend=NoConfidenceBackend([0.9, 0.9, 0.9]),
        standing=StandingGate(),
        ledger=ledger,
    )
    judge.judge(SEA_STATE_TASK, "state", (SEA_STATE,), now=0)
    rows = fold_judgments(ledger.events())
    assert rows[0]["standing"] is None  # the standing took no reading
    tampered = [dict(row) for row in rows]
    tampered[0]["standing"] = "act"
    with pytest.raises(ValueError, match="null-confidence"):
        standing_from_rows(tampered)


def test_the_rebuild_carries_the_bound_tau_per_question(ledger):
    _, gate = _run(SERIES[:6], ledger, split_at=3)
    # the rebuilt subject carries its row's τ: a subject judged at one
    # bound is not silently re-bound by a later calibration
    assert gate._subject_tau[SEA_STATE.qid] == 0.7


def test_the_rebuild_refuses_a_tau_that_moved_under_a_subject(ledger):
    judge = Judge(
        backend=SeriesBackend([0.9] * 2),
        standing=StandingGate(tau=0.6),
        ledger=ledger,
    )
    judge.judge(SEA_STATE_TASK, "state", (SEA_STATE,), now=0)
    other = Judge(
        backend=SeriesBackend([0.9] * 2),
        standing=StandingGate(tau=0.8),
        ledger=ledger,
    )
    other.judge(SEA_STATE_TASK, "state", (SEA_STATE,), now=1)
    with pytest.raises(ValueError, match="τ"):
        standing_from_rows(fold_judgments(ledger.events()))


def test_the_adopted_standing_config_is_the_sweep_s_choice():
    """The shape is the measurement (the sweep's choice at τ*); the τ is
    resolved per ask from the shipped calibration, ``DEFAULT_TAU`` where
    a pair is uncalibrated."""
    assert StandingConfig() == StandingConfig(
        tau=DEFAULT_TAU, band=0.15, dwell_up=2.0, dwell_down=0.0
    )
    gate = StandingGate()
    assert gate.tau is None  # resolved per ask, per (backend, model, task)
    assert (gate.band, gate.dwell_up, gate.dwell_down) == (0.15, 2.0, 0.0)
