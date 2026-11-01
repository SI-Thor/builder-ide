"""The reversed replay's own tests.

Three things are pinned here:

* **the swap** — the reversed prompt is the two named conditions the other way
  round, the swap twice is the identity, and on a prompt that names the same
  condition twice the swap is a no-op (those 43 steps are the run's
  determinism control);
* **the semantics** — the sweep and the bootstrap written here agree with
  ``core.judge.calibration``'s own, so the numbers in the note mean what the
  repository's numbers mean (the gate escalates when the confidence is *below*
  τ, and the AUC counts a tie as a half);
* **the analysis** — on a synthetic model that answers positionally and on a
  synthetic model that answers by content, the positional share, the
  disagreement set and the catch come out the way the mechanism says they
  must.

No network, no GPU, no model: the replay's model calls are the only thing not
under test, and they are what the measurement is.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parents[2]
SCRIPTS = HERE / "docs/lab/judge-reversed-scripts"

KEYS = "ABCDE"

#: the text of each condition, so that a prompt naming the same condition
#: twice holds the *same* sentence twice — which is what the recorder wrote.
TEXTS = {
    "A": "the water is flat as glass",
    "B": "a light ripple runs across it",
    "C": "a long heavy swell comes up",
    "D": "chop from two directions at once",
    "E": "white water over the shoal",
}


def _load(name: str):
    """One of the lab scripts, loaded by path (its directory is not a package)."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


replay = _load("replay_reversed")
measure = _load("measure_reversed")

from core.judge.calibration import (  # noqa: E402
    CalibrationSample,
    area_under_curve,
    bootstrap_auc,
    escalation_sweep,
)


# --- the swap ----------------------------------------------------------------


def _state(first: int, second: int) -> str:
    """A state text in the recorder's shape: two sentences, one per condition.

    The sentence of a condition is the sentence of that condition, so a prompt
    that names one condition twice holds the same sentence twice — which is
    what makes the swap a no-op there.
    """
    return (
        f"The sea is {KEYS[first]}: {TEXTS[KEYS[first]]}. "
        f"The sea is {KEYS[second]}: {TEXTS[KEYS[second]]}."
    )


def test_split_state_recovers_the_two_sentences() -> None:
    first, second = replay.split_state(_state(2, 0))
    assert first == f"The sea is C: {TEXTS['C']}."
    assert second == f"The sea is A: {TEXTS['A']}."


def test_the_swap_exchanges_the_two_named_conditions() -> None:
    swapped = replay.swapped_state(_state(2, 0))
    assert swapped == f"The sea is A: {TEXTS['A']}. The sea is C: {TEXTS['C']}."
    assert replay.swapped_state(swapped) == _state(2, 0)


def test_the_swap_is_a_no_op_when_the_prompt_names_one_condition_twice() -> None:
    state = _state(3, 3)
    assert replay.swapped_state(state) == state


def test_the_swap_moves_only_the_order() -> None:
    state = _state(2, 0)
    swapped = replay.swapped_state(state)
    assert sorted(state.split(" ")) == sorted(swapped.split(" "))


# --- the steps ---------------------------------------------------------------


def _trace_file(path: Path, *, truth: int = 1, shown: int = 2, decoy: int = 0) -> Path:
    """A two-step trace file in the recorder's format."""
    state = _state(shown, decoy)
    payload = {
        "trace": [
            {
                "t": 0,
                "trial": 0,
                "truth": truth,
                "shown": shown,
                "probs": {"A": 0.1, "B": 0.2, "C": 0.5, "D": 0.1, "E": 0.1},
                "confidence": 0.5,
                "wall_ms": 30.0,
            }
        ],
        "trials": [
            [
                {
                    "t": 0,
                    "truth": truth,
                    "shown": shown,
                    "decoy": decoy,
                    "state": state,
                }
            ]
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_steps_keeps_the_ground_truth_and_the_recorded_reply(tmp_path: Path) -> None:
    path = _trace_file(tmp_path / "trace.json")
    steps = replay.load_steps(path)
    assert len(steps) == 1
    step = steps[0]
    assert step["truth"] == 1
    assert step["shown"] == 2
    assert step["decoy"] == 0
    assert step["state"] == _state(2, 0)
    assert step["recorded"]["probs"]["C"] == 0.5
    assert replay.is_degenerate(step) is False


def test_load_steps_refuses_a_trace_that_does_not_match_its_trials(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(
        json.dumps({"trace": [], "trials": [[{"t": 0, "truth": 1, "shown": 2, "decoy": 0, "state": "x"}]]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        replay.load_steps(path)


def test_a_step_that_names_one_condition_twice_is_degenerate(tmp_path: Path) -> None:
    path = _trace_file(tmp_path / "trace.json", shown=3, decoy=3)
    step = replay.load_steps(path)[0]
    assert replay.is_degenerate(step) is True
    assert replay.swapped_state(step["state"]) == step["state"]


# --- the semantics -----------------------------------------------------------


#: the pairs the repository's own sweep can be asked about: every confidence
#: is at least a half, because a distribution that sums to one cannot have a
#: top probability under a half.
PAIRS: list[tuple[float, bool]] = [
    (0.5, False),
    (0.55, True),
    (0.5, False),
    (0.65, True),
    (0.8, False),
    (0.9, True),
    (0.55, True),
]

#: the pairs a confidence under a half needs: the repository cannot carry
#: these (see ``measure._pair_distribution``), so they are checked against
#: hand-computed expectations instead.
PAIRS_LOW: list[tuple[float, bool]] = [
    (0.2, False),
    (0.35, True),
    (0.5, False),
    (0.65, True),
    (0.8, False),
    (0.9, True),
    (0.45, True),
]


def _samples(pairs: list[tuple[float, bool]]) -> list[CalibrationSample]:
    samples = []
    for index, (confidence, outcome) in enumerate(pairs):
        samples.append(
            CalibrationSample(
                backend="test",
                model="test",
                task="test",
                kind="test",
                qid=str(index),
                distribution={"X": confidence, "Y": 1.0 - confidence},
                outcome=outcome,
            )
        )
    return samples


def test_the_sweep_is_the_repository_sweep() -> None:
    mine = measure.sweep(PAIRS)
    theirs = escalation_sweep(_samples(PAIRS), measure.TAUS)
    assert len(mine) == len(theirs)
    for my_row, repo_row in zip(mine, theirs):
        assert my_row["tau"] == repo_row.tau
        assert my_row["escalated"] == repo_row.escalated
        # this sweep rounds to four places, the repository keeps full precision
        assert my_row["catch"] == pytest.approx(repo_row.catch, abs=1e-4)
        assert my_row["tax"] == pytest.approx(repo_row.tax, abs=1e-4)
        assert my_row["caught_all"] == repo_row.caught_all


def test_the_gate_escalates_below_tau_not_above_it() -> None:
    rows = {row["tau"]: row for row in measure.sweep(PAIRS_LOW)}
    # a confidence of 0.5 escalates at tau 0.6 and not at tau 0.5
    assert rows[0.5]["escalated"] == sum(
        1 for confidence, _ in PAIRS_LOW if confidence < 0.5
    )
    assert rows[0.6]["escalated"] == sum(
        1 for confidence, _ in PAIRS_LOW if confidence < 0.6
    )
    assert rows[0.6]["escalated"] > rows[0.5]["escalated"]


def test_the_bootstrap_is_the_repository_bootstrap() -> None:
    mine = measure.bootstrap_auc(PAIRS)
    theirs = bootstrap_auc(_samples(PAIRS))
    assert theirs is not None
    assert mine is not None
    assert mine["auc"] == pytest.approx(theirs.point, abs=1e-6)
    assert mine["low"] == pytest.approx(theirs.low, abs=0.02)
    assert mine["high"] == pytest.approx(theirs.high, abs=0.02)


def test_the_auc_counts_a_tie_as_a_half() -> None:
    assert area_under_curve([(0.5, True), (0.5, False)]) == pytest.approx(0.5)


def test_a_confidence_under_a_half_has_no_distribution_to_be_read_from() -> None:
    # a distribution that sums to one cannot have a top probability under a
    # half, which is why the sweeps here run on pairs
    assert measure._pair_distribution(0.4) is None
    assert measure._pair_distribution(0.8) is not None


# --- the budgets -------------------------------------------------------------


def test_tau_for_budget_stays_under_the_budget() -> None:
    row = measure.tau_for_budget(PAIRS, 0.30)
    assert row["share"] <= 0.30
    assert row["escalated"] == sum(1 for confidence, _ in PAIRS if confidence < row["tau"])


def test_capped_protocol_spends_the_budget_on_the_least_sure_steps() -> None:
    outcomes = [False, True, False, True]
    disagree = [True, True, False, True]
    scores = [0.1, 0.9, 0.2, 0.8]
    row = measure.capped_protocol(outcomes, disagree, scores, 0.25)
    assert row["escalated"] == 1
    assert row["caught"] == 1
    assert row["taxed"] == 0
    assert row["catch"] == pytest.approx(0.5)
    assert row["tax"] == 0.0


def test_capped_protocol_never_escalates_a_step_that_did_not_disagree() -> None:
    outcomes = [True] * 4
    disagree = [False, True, False, True]
    scores = [0.0, 0.9, 0.1, 0.8]
    row = measure.capped_protocol(outcomes, disagree, scores, 0.50)
    assert row["escalated"] == 2
    assert row["taxed"] == 2


# --- the analysis ------------------------------------------------------------


def _row(
    t: int,
    truth: int,
    shown: int,
    decoy: int,
    orig_argmax: str,
    rev_argmax: str,
    confidence: float = 0.9,
) -> dict[str, Any]:
    def vector(argmax: str) -> dict[str, float]:
        probs = {key: (1.0 - confidence) / 4.0 for key in KEYS}
        probs[argmax] = confidence
        return probs

    return {
        "t": t,
        "trial": 0,
        "truth": truth,
        "shown": shown,
        "decoy": decoy,
        "state_original": _state(shown, decoy),
        "state_reversed": replay.swapped_state(_state(shown, decoy)),
        "identical_prompt": shown == decoy,
        "first_call": "original",
        "original": {"argmax": orig_argmax, "probs": vector(orig_argmax), "confidence": confidence},
        "reversed": {"argmax": rev_argmax, "probs": vector(rev_argmax), "confidence": confidence},
    }


def _replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"model": "test", "steps": rows, "latency": {}, "box": {}}


def test_a_positional_model_is_caught_by_the_replay() -> None:
    # the model answers the first-named condition: the reversed prompt names the
    # other one first, so the reversed answer is the other condition
    rows = [
        # two truth-first steps the model got right (it named the truth first)
        _row(0, truth=1, shown=1, decoy=0, orig_argmax="B", rev_argmax="A"),
        _row(1, truth=1, shown=1, decoy=0, orig_argmax="B", rev_argmax="A"),
        # one decoy-first step the model got wrong (it named the decoy first)
        _row(2, truth=2, shown=0, decoy=2, orig_argmax="A", rev_argmax="C"),
    ]
    numbers = measure.analyse(_replay(rows), None)
    share = numbers["positional_share"]
    assert share["distinct_conditions"]["positional"] == 3
    assert share["distinct_conditions"]["content"] == 0
    assert share["distinct_conditions"]["third"] == 0
    assert share["distinct_conditions"]["positional_share"] == 1.0
    disagree = numbers["disagreement"]
    assert disagree["escalations"] == 3
    assert disagree["caught"] == 1
    assert disagree["taxed"] == 2
    assert disagree["catch"] == pytest.approx(1.0)
    assert disagree["tax"] == pytest.approx(1.0)


def test_a_content_model_never_disagrees() -> None:
    # the model answers the same condition whichever way round the prompt names
    rows = [
        _row(0, truth=1, shown=1, decoy=0, orig_argmax="B", rev_argmax="B"),
        _row(1, truth=2, shown=0, decoy=2, orig_argmax="A", rev_argmax="A"),
    ]
    numbers = measure.analyse(_replay(rows), None)
    share = numbers["positional_share"]
    assert share["distinct_conditions"]["content"] == 2
    assert share["distinct_conditions"]["positional"] == 0
    disagree = numbers["disagreement"]
    assert disagree["escalations"] == 0
    assert disagree["catch"] == 0.0
    assert disagree["tax"] == 0.0


def test_the_degenerate_steps_cannot_disagree() -> None:
    # the prompt names one condition twice: the reversed prompt is the same
    # text, so the two orders agree by construction
    rows = [_row(0, truth=1, shown=1, decoy=1, orig_argmax="B", rev_argmax="B")]
    numbers = measure.analyse(_replay(rows), None)
    assert numbers["positional_share"]["determinism_control"]["steps"] == 1
    assert numbers["positional_share"]["determinism_control"]["identical_vector"] == 1
    assert numbers["disagreement"]["escalations"] == 0


def test_the_average_of_the_vectors_is_the_elementwise_average() -> None:
    left = {"A": 0.5, "B": 0.5}
    right = {"A": 0.25, "B": 0.75}
    assert measure.mean_vector(left, right) == {"A": 0.375, "B": 0.625}


# --- the committed replies ---------------------------------------------------

RESULTS = SCRIPTS / "results"


def _committed(model: str) -> dict[str, Any]:
    path = RESULTS / f"replay-{model}.json"
    if not path.exists():  # pragma: no cover - the replies are committed
        pytest.skip(f"{path} is not in the tree")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_committed_replies_are_the_ones_the_note_reports() -> None:
    """The note's numbers are machine-checked against the recorded replies.

    If a replay is re-run and the model answers differently, this fails — which
    is the point: the note's numbers are a measurement of *these* replies, and
    a different set of replies is a different measurement.
    """
    two = measure.analyse(_committed("d1-2B"), None)
    share = two["positional_share"]["distinct_conditions"]
    assert share["positional"] == 169
    assert share["content"] == 28
    assert share["third"] == 0
    disagree = two["disagreement"]
    assert disagree["escalations"] == 137
    assert disagree["caught"] == 28
    assert disagree["taxed"] == 109
    assert disagree["catch"] == pytest.approx(0.2456, abs=1e-4)
    assert disagree["tax"] == pytest.approx(0.8651, abs=1e-4)
    assert two["averaging"]["canonical_original_only"]["auc"]["auc"] == 0.2815
    assert two["averaging"]["mean_confidence"]["auc"]["auc"] == 0.1104
    assert two["averaging"]["mean_vector"]["auc"]["auc"] == 0.1332

    three = measure.analyse(_committed("d1-3B"), None)
    share = three["positional_share"]["distinct_conditions"]
    assert share["positional"] == 95
    assert share["content"] == 102
    disagree = three["disagreement"]
    assert disagree["escalations"] == 4
    assert disagree["caught"] == 4
    assert disagree["catch"] == pytest.approx(0.0248, abs=1e-4)
    assert disagree["tax"] == 0.0


def test_the_committed_replies_reproduce_the_october_recording() -> None:
    """The d1-2B's live replies are the recording's, exactly."""
    fidelity = _committed("d1-2B")["fidelity"]
    assert fidelity["compared"] == 240
    assert fidelity["max_abs_diff"] == 0.0
    assert fidelity["argmax_identical"] == 240

    three = _committed("d1-3B")["fidelity"]
    assert three["compared"] == 240
    assert three["argmax_identical"] == 240


def test_the_degenerate_steps_are_a_determinism_control() -> None:
    """The 43 steps that name one condition twice cannot disagree."""
    for model in ("d1-2B", "d1-3B"):
        replayed = _committed(model)
        degenerate = [
            row for row in replayed["steps"] if row["identical_prompt"]
        ]
        assert len(degenerate) == 43
        for row in degenerate:
            assert row["original"]["probs"] == row["reversed"]["probs"]
