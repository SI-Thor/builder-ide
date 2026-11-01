"""The prompt-fix replay's own tests.

Three things are pinned here:

* **the arms** — the ``recorded`` arm asks the recording's own text; the two
  fixed arms name **the true condition and the decoy** in a neutral order,
  which on a noise step is the step's first mention of the truth at all;
  the catalog check refuses a recording built from any other material;
* **the semantics** — the sweep and the bootstrap written in the analysis
  agree with ``core.judge.calibration``'s own, so the numbers in the note
  mean what the repository's numbers mean (the gate escalates when the
  confidence is *below* τ, and the AUC counts a tie as a half);
* **the analysis** — on a synthetic recording, the grouping, the positional
  tally and the pass rows come out the way the mechanism says they must.

No network, no GPU, no model: the replay's model calls are the only thing
not under test, and they are what the measurement is.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parents[2]
SCRIPTS = HERE / "docs/lab/judge-prompt-fix-scripts"

sys.path.insert(0, str(HERE))

from core.judge.calibration import area_under_curve, bootstrap_auc, escalation_sweep  # noqa: E402
from core.judge.calibration import CalibrationSample  # noqa: E402

KEYS = "ABCDE"


def _load(name: str):
    """One of the lab scripts, loaded by path (its directory is not a package)."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


replay = _load("replay_fixed")
measure = _load("measure_fixed")

#: the recorder's own sentences — the replay script's catalog is the
#: recorder's TRUE_TEXT, and the tests build from the same table.
TEXTS: list[str] = replay.TRUE_TEXT


def _state(first: int, second: int) -> str:
    return f"{TEXTS[first]} {TEXTS[second]}"


# --- the arms ----------------------------------------------------------------


def _step(*, truth: int, shown: int, decoy: int) -> dict[str, Any]:
    return {
        "t": 7,
        "trial": 1,
        "truth": truth,
        "shown": shown,
        "decoy": decoy,
        "state": _state(shown, decoy if decoy != shown else (truth + 1) % 5),
    }


def test_the_recorded_arm_asks_the_recording_is_own_text() -> None:
    step = _step(truth=1, shown=1, decoy=2)
    assert replay.arm_state(step, "recorded") == step["state"]


def test_the_fixed_arms_name_the_true_condition_and_the_decoy() -> None:
    step = _step(truth=1, shown=2, decoy=0)  # a noise step: shown is the decoy
    for arm in ("canonical", "balanced"):
        state = replay.arm_state(step, arm)
        sentences = replay.named_sentences(state, replay.MARKER)
        names = {replay.condition_name(sentence, replay.MARKER) for sentence in sentences}
        # the truth the recorded prompt left out, and the decoy — nothing else
        assert names == {"slight chop", "flat calm"}


def test_the_canonical_arm_sorts_by_the_condition_is_own_name() -> None:
    step = _step(truth=4, shown=4, decoy=0)
    state = replay.arm_state(step, "canonical")
    sentences = replay.named_sentences(state, replay.MARKER)
    first = replay.condition_name(sentences[0], replay.MARKER)
    assert first == "breaking water"  # sorts before "flat calm"


def test_the_balanced_arm_is_deterministic_for_replay() -> None:
    step = _step(truth=1, shown=1, decoy=2)
    once = replay.arm_state(step, "balanced")
    assert once == replay.arm_state(step, "balanced")
    assert once in (_state(1, 2), _state(2, 1))


def test_the_recording_must_be_built_from_the_recorder_is_material() -> None:
    steps = [_step(truth=1, shown=1, decoy=2)]
    report = replay.check_catalog(steps)
    assert report["sentences_seen"] == 2
    # the one step names two conditions; the other three are unused, and
    # only a sentence outside the recorder's table is refused
    assert "slight chop" not in report["conditions_missing_from_the_recording"]
    stranger = dict(steps[0])
    stranger["state"] = "The sea is glassy: invented text."
    with pytest.raises(ValueError):
        replay.check_catalog([stranger])


def test_the_noise_and_noop_flags_read_the_recording() -> None:
    assert replay.is_noise(_step(truth=1, shown=2, decoy=0)) is True
    assert replay.is_noise(_step(truth=1, shown=1, decoy=2)) is False
    assert replay.is_noop(_step(truth=1, shown=2, decoy=2)) is True
    assert replay.is_noop(_step(truth=1, shown=1, decoy=2)) is False


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
    rows = {row["tau"]: row for row in measure.sweep(PAIRS)}
    assert rows[0.6]["escalated"] >= rows[0.5]["escalated"]
    assert rows[0.5]["escalated"] == sum(1 for confidence, _ in PAIRS if confidence < 0.5)


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


def test_tau_for_budget_stays_under_the_budget() -> None:
    row = measure.tau_for_budget(PAIRS, 0.30)
    assert row["share"] <= 0.30
    assert row["escalated"] == sum(
        1 for confidence, _ in PAIRS if confidence < row["tau"]
    )


def test_wilson_brackets_the_share() -> None:
    interval = measure.wilson(6, 10)
    assert interval is not None
    assert interval["low"] < 0.6 < interval["high"]
    assert measure.wilson(0, 0) is None


# --- the analysis ------------------------------------------------------------


def _fresh_file(path: Path) -> Path:
    """A three-step fresh recording: one step of each recorded group.

    The synthetic model answers the first-named condition with confidence
    0.9 in the ``recorded`` arm — the positional shape — and the truth with
    confidence 0.8 in both fixed arms, so the pass rows have something to
    move.
    """
    steps_out = []
    trace_rows = []
    trials_out = []
    plan = [
        # (truth, shown, decoy) — truth_first, decoy_first_noop, decoy_first_two_cond
        (1, 1, 2),
        (1, 2, 2),
        (1, 2, 0),
    ]
    for index, (truth, shown, decoy) in enumerate(plan):
        recorded_state = _state(shown, decoy if decoy != shown else (truth + 1) % 5)
        arms: dict[str, Any] = {}
        for arm in ("recorded", "canonical", "balanced"):
            state = (
                recorded_state
                if arm == "recorded"
                else replay.arm_state(
                    {"t": index, "trial": 0, "truth": truth, "shown": shown, "decoy": decoy,
                     "state": recorded_state},
                    arm,
                )
            )
            if arm == "recorded":
                # the positional shape: the first-named condition, confidently
                named = replay.condition_name(
                    replay.named_sentences(state, replay.MARKER)[0], replay.MARKER
                )
                choice = TEXTS.index(
                    next(s for s in TEXTS if s.startswith(f"The sea is {named}:"))
                )
                probs = {KEYS[i]: 0.025 for i in range(5)}
                probs[KEYS[choice]] = 0.9
            elif index == 1:
                # a wrong, *less confident* answer on the no-op step, so the
                # fixed arm's confidence orders right above wrong
                probs = {KEYS[i]: 0.025 for i in range(5)}
                probs[KEYS[(truth + 1) % 5]] = 0.6
            else:
                probs = {KEYS[i]: 0.025 for i in range(5)}
                probs[KEYS[truth]] = 0.8
            argmax = max(sorted(probs), key=lambda key: probs[key])
            arms[arm] = {
                "argmax": argmax,
                "probs": probs,
                "confidence": probs[argmax],
                "ms": 30.0 + index,
                "named_first": replay.condition_name(
                    replay.named_sentences(state, replay.MARKER)[0], replay.MARKER
                ),
                "state": state,
            }
        steps_out.append(
            {
                "t": index,
                "trial": 0,
                "truth": truth,
                "shown": shown,
                "decoy": decoy,
                "identical_prompt": shown == decoy,
                "arm_order": ["recorded", "canonical", "balanced"],
                "arms": arms,
                "recorded": {
                    "probs": {"A": 0.1, "B": 0.6, "C": 0.1, "D": 0.1, "E": 0.1},
                    "confidence": 0.6,
                    "wall_ms": 25.0,
                },
            }
        )
        trace_rows.append(
            {
                "t": index,
                "truth": truth,
                "shown": shown,
                "probs": {"A": 0.1, "B": 0.6, "C": 0.1, "D": 0.1, "E": 0.1},
            }
        )
        trials_out.append(
            [
                {
                    "t": index,
                    "truth": truth,
                    "shown": shown,
                    "decoy": decoy,
                    "state": recorded_state,
                }
            ]
        )
    path.write_text(
        json.dumps(
            {
                "experiment": "judge-prompt-fix",
                "model": "test-model",
                "complete": True,
                "steps": steps_out,
                "trials": trials_out,
                "trace": trace_rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_read_rows_groups_by_the_recorded_prompt_is_order(tmp_path: Path) -> None:
    path = _fresh_file(tmp_path / "fresh-test.json")
    rows = measure.read_rows(path)
    assert [row["group"] for row in rows] == [
        "truth_first",
        "decoy_first_noop",
        "decoy_first_two_cond",
    ]


def test_the_fixed_arms_positions_read_off_their_own_prompt(tmp_path: Path) -> None:
    path = _fresh_file(tmp_path / "fresh-test.json")
    rows = measure.read_rows(path)
    for row in rows:
        for arm in ("canonical", "balanced"):
            answer = row["arms"][arm]
            # exactly one of the three tallies fires
            assert sum(
                (answer["positional"], answer["content"], answer["third"])
            ) == 1


def test_the_pass_rows_move_the_way_the_synthetic_model_does(tmp_path: Path) -> None:
    path = _fresh_file(tmp_path / "fresh-test.json")
    result = measure.analyse_model(path)
    for arm in ("canonical", "balanced"):
        passes = result["pass"][arm]
        # the synthetic model answers the truth in the fixed arms: the
        # decoy-first accuracy rises from 0, and the truth-first row falls —
        # because the recorded arm's positional model was right there
        assert passes["decoy_first_accuracy_rises"]["pass"] is True
        assert passes["decoy_first_accuracy_rises"]["before"] == 0.0
        assert passes["auc_above_half"]["auc"] > 0.5


def test_the_recorded_arm_reproduces_the_positional_shape(tmp_path: Path) -> None:
    path = _fresh_file(tmp_path / "fresh-test.json")
    rows = measure.read_rows(path)
    tally = measure.analyse_arm(rows, "recorded")["positional_tally"]
    # the synthetic recorded arm answers the first-named condition on every
    # step where the prompt names two conditions
    assert tally["positional"] == 2
    assert tally["n"] == 2  # the no-op step is not a two-condition prompt


def test_the_routing_table_reads_both_models(tmp_path: Path) -> None:
    path_a = _fresh_file(tmp_path / "fresh-a.json")
    path_b = _fresh_file(tmp_path / "fresh-b.json")
    rows_a = measure.read_rows(path_a)
    rows_b = measure.read_rows(path_b)
    table = measure.routing_table(rows_a, rows_b)
    for arm in ("canonical", "balanced"):
        assert table[arm]["d1-2B"]["accuracy"] == table[arm]["d1-3B"]["accuracy"]
        counts = table[arm]["steps_where_one_is_right"]
        assert counts["both"] + counts["the_2B_only"] + counts["the_3B_only"] + counts["neither"] == 3
