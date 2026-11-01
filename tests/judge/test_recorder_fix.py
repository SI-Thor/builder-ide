"""The recorder fix's own tests.

The brief's regression, stated once: **no prompt may omit the truth or
name an option twice.** The fixed builder
(``docs/lab/judge-recorder-fix-scripts/recorder.py``) must satisfy it on
the October seed, and the October builder — kept verbatim in that module
as the baseline — must fail it, with the counts §8 reported (82 of 240
prompts without the truth, 43 naming one condition twice). The other
property the fix promises is pinned too: the random stream is spent as the
old builder spent it, so the task — the truths, the noise labels — is the
October task, and only the prompt changed.

No network, no GPU, no model, no October file on disk.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
SCRIPTS = HERE / "docs/lab/judge-recorder-fix-scripts"

sys.path.insert(0, str(HERE))


def _load(name: str):
    """One of the lab scripts, loaded by path (its directory is not a package)."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


recorder = _load("recorder")


def _build(builder, seed: int = recorder.SEED):
    rng = random.Random(seed)
    return [
        builder(rng, recorder.N_STEPS, recorder.NOISE)
        for _ in range(recorder.N_TRIALS)
    ]


def _steps(trials):
    return [step for trial in trials for step in trial]


def _assert_no_faults(trials) -> None:
    for step in _steps(trials):
        faults = recorder.prompt_faults(step["state"], step["truth"])
        assert faults == [], f"t={step['t']} truth={step['truth']}: {faults}"


# --- the invariant ----------------------------------------------------------


def test_every_prompt_names_the_truth_exactly_once() -> None:
    """The brief's test: it fails on the old recorder, passes on the fixed one."""
    _assert_no_faults(_build(recorder.make_trial))


def test_the_old_recorder_fails_the_invariant() -> None:
    """The same assertion, run on the October builder: it must not pass."""
    with pytest.raises(AssertionError):
        _assert_no_faults(_build(recorder.old_make_trial))


def test_the_old_recorders_counts_are_the_note_s() -> None:
    """The violation, counted: 82 prompts without the truth, 43 with a double.

    §8 of the calibration note: *it leaves the truth out of the prompt
    entirely (the decoy named twice, or the decoy and the truth's
    neighbour), which is the §7.1 bound no gate could lift: 82 of the 2B's
    114 errors were unwinnable*; the 43 no-op steps are §7's determinism
    control. These counts are that finding, reproduced from the seed.
    """
    audit = recorder.audit_trials(_build(recorder.old_make_trial))
    assert audit["steps"] == 240
    assert audit["truth_omitted"] == 82
    assert audit["option_named_twice"] == 43
    assert audit["faulty"] == 82


def test_the_fixed_recorder_has_no_fault_to_count() -> None:
    audit = recorder.audit_trials(_build(recorder.make_trial))
    assert audit == {
        "steps": 240,
        "truth_omitted": 0,
        "option_named_twice": 0,
        "faulty": 0,
    }


# --- the order --------------------------------------------------------------


def test_the_fixed_order_is_the_canonical_one() -> None:
    """The state's sentences are name-sorted — an order the truth is not a key of."""
    for step in _steps(_build(recorder.make_trial)):
        sentences = recorder.named_sentences(step["state"], recorder.MARKER)
        assert sentences == recorder.canonical_order(
            sentences, recorder.MARKER
        )
        assert len(sentences) == 2


# --- the task is unchanged --------------------------------------------------


def test_the_fix_keeps_the_recorded_task() -> None:
    """Same stream, same task: truths and noise labels equal the old builder's.

    The decoy fields differ where the old builder corrupted its own record
    (it wrote the second-named condition there, not the decoy it drew); the
    task the step poses — which condition is true, and whether the step was
    a noise step — does not.
    """
    old = _steps(_build(recorder.old_make_trial))
    fixed = _steps(_build(recorder.make_trial))
    assert len(old) == len(fixed) == 240
    for old_step, fixed_step in zip(old, fixed):
        assert fixed_step["t"] == old_step["t"]
        assert fixed_step["truth"] == old_step["truth"]
        assert fixed_step["shown"] == old_step["shown"]


def test_the_named_pair_is_the_truth_and_the_drawn_decoy() -> None:
    """Every prompt names the truth and the step's own decoy, once each."""
    for step in _steps(_build(recorder.make_trial)):
        sentences = recorder.named_sentences(step["state"], recorder.MARKER)
        names = {
            recorder.condition_name(sentence, recorder.MARKER)
            for sentence in sentences
        }
        assert names == {
            recorder.SEA_STATES[step["truth"]][0],
            recorder.SEA_STATES[step["decoy"]][0],
        }


def test_the_builder_is_deterministic() -> None:
    """Building the task twice gives the same 240 prompts, byte for byte."""
    first = [step["state"] for step in _steps(_build(recorder.make_trial))]
    second = [step["state"] for step in _steps(_build(recorder.make_trial))]
    assert first == second


def test_a_state_that_already_names_the_pair_is_unchanged_by_the_policy() -> None:
    """``neutral_state`` on the fixed builder's own output is a no-op.

    The builder builds through the ordering policy already, so the policy's
    own entry point must agree with what it built — the property a replay
    needs.
    """
    from core.judge.ordering import neutral_state

    for step in _steps(_build(recorder.make_trial)):
        assert neutral_state(step["state"], recorder.MARKER) == step["state"]
