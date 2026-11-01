"""The replay test the review asked for: the recorded d1 trace through
the wired judge, with a restart in the middle.

The 240-tick d1-2B sea-state recording (the liquid study's §4.3, run on
the Thor; distilled to the columns the gate consumes into
``docs/lab/hysteresis-scripts/results/d1-2B-ticks.json``) is replayed
tick by tick through ``Judge(standing=StandingGate(), now=tick)`` — the
adopted wiring, its defaults, no tuning. The lab harness
(``docs/lab/hysteresis-scripts/replay_d1_traces.py``) measured the
adopted shape on this trace: 66 flickers at the raw calibrated τ, 1
after the gate. The test fails unless the wired judge reproduces that
measured result — which is what makes the shipped defaults a
measurement rather than a taste — and unless:

* the standing rebuilt from the ledger at the midpoint (a fresh judge,
  a fresh process) says exactly what the uninterrupted run said, tick
  for tick — ``standing_from_rows`` replays every row and refuses a
  divergence, so this check is the ledger's own;
* a null-confidence tick moves no standing and takes no reading;
* every row was judged at the calibrated τ, and says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.judge.backends import BackendReply, JudgeCost
from core.judge.gate import SEA_STATE_TASK, StandingGate
from core.judge.judge import Judge, fold_judgments, standing_from_rows
from core.judge.models import Question
from core.night.ledger import InMemoryLedger

HERE = Path(__file__).resolve().parents[2]
TICKS_PATH = HERE / "docs/lab/hysteresis-scripts/results/d1-2B-ticks.json"
SWEEP_PATH = HERE / "docs/lab/hysteresis-scripts/results/hysteresis-d1-sweep.json"

#: The flicker window, in ticks — ``core.hysteresis.metrics``' definition,
#: the one the lab harness counted with.
WINDOW = 2

LETTERS = "ABCDE"


def _ticks() -> list[dict]:
    return json.loads(TICKS_PATH.read_text())["ticks"]


def _measured() -> dict:
    """The sweep's chosen configuration and its measured metrics — the
    numbers the default run has to reproduce."""
    sweep = json.loads(SWEEP_PATH.read_text())
    chosen = sweep["models"]["d1-2B"]["chosen"]
    return {"config": chosen["config"], "metrics": chosen["metrics"]}


class ReplayBackend:
    """The recorded rung: each ask is the next recorded tick's answers."""

    name = "d1"
    model = "d1-2B"

    def __init__(self, ticks, offset: int = 0, *, blank_confidence_at: int | None = None):
        self._ticks = ticks
        self._offset = offset
        self._blank_at = blank_confidence_at
        self.calls = 0

    def ask(self, state, questions):
        row = self._ticks[self._offset]
        index = self._offset
        self._offset += 1
        self.calls += 1
        confidence = (
            None if index == self._blank_at else row["confidence"]
        )
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions={q.qid: row["probs"] for q in questions},
            confidences={q.qid: confidence for q in questions},
            input_tokens=0,
            wall_seconds=0.001,
        )

    def cost_of(self, reply):
        return JudgeCost(wall_seconds=reply.wall_seconds, input_tokens=0)


def _question(trial: int) -> Question:
    # one subject per trial, the lab harness's own shape: a fresh
    # recording starts cold, and the flicker count is pooled over trials
    return Question(
        qid=f"sea-state/trial-{trial}",
        kind="choice",
        instructions="Which sea condition is shown?",
        criteria={letter: f"condition {letter}" for letter in LETTERS},
    )


def _replay(ticks, *, split_at: int | None = None, blank_confidence_at: int | None = None):
    """Play the recording through the wired judge, one tick per ask;
    when ``split_at`` is given, rebuild the standing from the ledger
    there and continue with a fresh judge — the restart."""
    ledger = InMemoryLedger()
    judge = Judge(
        backend=ReplayBackend(ticks, blank_confidence_at=blank_confidence_at),
        standing=StandingGate(),
        ledger=ledger,
    )
    words: dict[int, list[str]] = {}
    for row in ticks:
        index = row["trial"] * 40 + row["t"]
        if split_at is not None and index == split_at:
            standing = standing_from_rows(fold_judgments(ledger.events()))
            judge = Judge(
                backend=ReplayBackend(ticks, offset=split_at),
                standing=standing,
                ledger=ledger,
            )
        answer = judge.judge(
            SEA_STATE_TASK,
            json.dumps(row["probs"], sort_keys=True),
            (_question(row["trial"]),),
            now=row["t"],
        )
        words.setdefault(row["trial"], []).append(
            answer.standing_words[f"sea-state/trial-{row['trial']}"]
        )
    return words, ledger


def _pooled(words: dict[int, list[str]], ticks: list[dict]) -> dict:
    """The lab harness's metrics, pooled over the trials."""
    transitions = 0
    changes: list[tuple[int, int, str, str]] = []
    for trial, series in sorted(words.items()):
        previous = series[0]
        for index, word in enumerate(series[1:], start=1):
            if word != previous:
                transitions += 1
                changes.append((trial, index, previous, word))
                previous = word
    flickers = 0
    for position, (trial, when, was, _) in enumerate(changes):
        for later_trial, later, _, back in changes[position + 1 :]:
            if later_trial != trial or later - when > WINDOW:
                break
            if back == was:
                flickers += 1
                break
    tp = fp = tn = fn = 0
    for row in ticks:
        word = words[row["trial"]][row["t"]]
        right = max(row["probs"], key=row["probs"].get) == LETTERS[row["shown"]]
        if word == "act" and right:
            tp += 1
        elif word == "act":
            fp += 1
        elif right:
            fn += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    return {
        "transitions": transitions,
        "flickers": flickers,
        "act_rate": (tp + fp) / n,
        "catch_vs_shown": tn / (fp + tn) if fp + tn else None,
        "agreement_vs_shown": (tp + tn) / n,
    }


# --- the measured result ------------------------------------------------------


def test_the_default_run_reproduces_the_measured_result():
    ticks = _ticks()
    assert len(ticks) == 240
    words, _ = _replay(ticks)
    pooled = _pooled(words, ticks)
    measured = _measured()["metrics"]

    # the shape the sweep adopted (the review's failure was a default
    # that never met the measurement: τ 0.5 on a trace calibrated 0.7)
    assert _measured()["config"] == {
        "tau": 0.7,
        "band": 0.15,
        "dwell_up": 2,
        "dwell_down": 0,
    }
    # the flicker count is the measurement: 66 at the raw gate, 1 here —
    # and more than one means the standing has stopped doing its work
    assert pooled["flickers"] <= 1
    # the sweep's summary carries its numbers rounded to 4 decimals;
    # compare at the sweep's own precision
    rounded = {
        key: (round(value, 4) if isinstance(value, float) else value)
        for key, value in pooled.items()
    }
    assert rounded["transitions"] == measured["transitions"]
    assert rounded["flickers"] == measured["flickers"]
    assert rounded["act_rate"] == measured["act_rate"]
    assert rounded["catch_vs_shown"] == measured["catch_vs_shown"]
    assert rounded["agreement_vs_shown"] == measured["agreement_vs_shown"]


def test_every_row_is_judged_at_the_calibrated_tau_and_says_so():
    ticks = _ticks()
    _, ledger = _replay(ticks)
    rows = fold_judgments(ledger.events())
    assert len(rows) == 240
    assert {row["tau"] for row in rows} == {0.7}
    assert {row["tau_source"] for row in rows} == {"calibrated"}
    assert all(row["standing_governed"] for row in rows)


# --- the restart --------------------------------------------------------------


def test_a_judge_rebuilt_from_the_ledger_at_the_midpoint_says_the_same():
    ticks = _ticks()
    control_words, _ = _replay(ticks)

    midpoint = len(ticks) // 2
    restart_words, ledger = _replay(ticks, split_at=midpoint)

    # the fresh judge — its standing rebuilt from the rows alone — says
    # what the uninterrupted run said, tick for tick, per subject
    assert restart_words == control_words


def test_the_rebuild_replays_the_whole_first_half_without_divergence():
    ticks = _ticks()
    _, ledger = _replay(ticks, split_at=len(ticks) // 2)
    # standing_from_rows replayed every row up to the split while
    # rebuilding (it raises on a divergence); run it again over the
    # whole log as the ledger's own integrity check
    assert standing_from_rows(fold_judgments(ledger.events())) is not None


# --- the null-confidence rule -------------------------------------------------


def test_a_backend_with_no_confidence_of_its_own_still_gates_on_the_distribution():
    """A tick whose backend reported no confidence of its own still moves
    the standing — on the number the distribution gave.

    The confidence is read from the distribution under one definition,
    for every backend (``core.judge.calibration``), so blanking the
    backend's own number changes nothing about the gate: the words are
    the control's words, tick for tick. The old rule — a tick with **no
    confidence at all** moves nothing — still holds where it can still
    happen: a row folded from a log written before the definition was
    stated (``tests/judge/test_standing_durable.py``) and the policy's
    own rule that a judgment with no confidence never passes
    (``tests/judge/test_gate.py``).
    """
    ticks = _ticks()
    control_words, _ = _replay(ticks[:8])

    blank_at = 4  # the fifth tick of the first trial
    words, ledger = _replay(ticks[:8], blank_confidence_at=blank_at)

    # the blanked tick reads the same, because the distribution is the
    # confidence's source
    assert words[0] == control_words[0]
    # and the row says which is which: the canonical number is there, the
    # backend's own is null
    row = fold_judgments(ledger.events())[blank_at]
    assert row["judgment"].backend_confidence is None
    assert row["judgment"].confidence is not None
    assert row["judgment"].confidence_definition == "top_probability"
