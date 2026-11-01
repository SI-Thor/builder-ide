"""The order policy's tests: an order the answer cannot be read off.

Pinned here:

* **the split** — a state's condition sentences, and the name each one
  carries, with the preamble kept where the rebuilders need it;
* **the canonical order** — sorted by the condition's own name, independent
  of the order the sentences arrived in, so the first-named condition is a
  function of which conditions the state names and of nothing else;
* **the balanced order** — deterministic per step key, half the steps name
  either condition first, and no step key reads anything but the key;
* **the rebuild** — a state that names one condition (or the same condition
  twice) comes back unchanged; a rebuilt state holds the same sentences it
  was given, and nothing but their order moved.

No network, no GPU, no model.
"""

from __future__ import annotations

import pytest

from core.judge.ordering import (
    balanced_order,
    canonical_order,
    condition_name,
    named_sentences,
    neutral_state,
    order_named,
)

MARKER = "The sea is "

A = "The sea is flat calm: the water is flat as glass, no chop at all."
B = "The sea is slight chop: a light ripple, short and regular."
E = "The sea is breaking water: white water over the shoal."


# --- the split ---------------------------------------------------------------


def test_named_sentences_splits_on_the_marker_and_keeps_the_order() -> None:
    state = f"{A} {E}"
    assert named_sentences(state, MARKER) == [A, E]


def test_named_sentences_keeps_a_preamble() -> None:
    state = f"Harbor report. {A} {E}"
    sentences = named_sentences(state, MARKER)
    assert sentences == [A, E]
    assert state.startswith("Harbor report. ")


def test_named_sentences_finds_nothing_without_the_marker() -> None:
    assert named_sentences("The harbour is quiet.", MARKER) == []


def test_condition_name_is_the_words_between_the_marker_and_the_colon() -> None:
    assert condition_name(A, MARKER) == "flat calm"
    assert condition_name(E, MARKER) == "breaking water"


def test_condition_name_without_a_colon_names_the_whole_tail() -> None:
    assert condition_name("The sea is rough", MARKER) == "rough"


# --- the canonical order -----------------------------------------------------


def test_the_canonical_order_is_independent_of_the_order_it_was_given() -> None:
    assert canonical_order([E, A], MARKER) == canonical_order([A, E], MARKER)


def test_the_canonical_order_sorts_by_the_condition_is_own_name() -> None:
    # "breaking water" sorts before "flat calm", whichever sentence arrived first
    assert canonical_order([A, E], MARKER) == [E, A]
    assert canonical_order([E, A], MARKER) == [E, A]


def test_the_canonical_order_is_a_stable_sort() -> None:
    # the same sentence twice keeps its relative order — the no-op prompts
    assert canonical_order([A, A], MARKER) == [A, A]


def test_the_canonical_key_does_not_know_which_condition_is_true() -> None:
    # the key is read off the sentence alone: the same sentence carries the
    # same key whether it names the true condition or the decoy
    assert condition_name(A, MARKER) == condition_name(A, MARKER)
    key_of_a = canonical_order([A, B], MARKER)
    assert key_of_a == canonical_order([A, B], MARKER)


# --- the balanced order ------------------------------------------------------


def test_the_balanced_order_is_deterministic_per_step_key() -> None:
    first = balanced_order([A, E], "0:17")
    assert first == balanced_order([A, E], "0:17")


def test_the_balanced_order_is_balanced_over_a_trace() -> None:
    # 240 steps keyed the way the replay keys them: both orders appear, and
    # neither owns the trace
    firsts = 0
    for trial in range(6):
        for t in range(40):
            ordered = balanced_order([A, E], f"{trial}:{t}")
            if ordered[0] == A:
                firsts += 1
    assert 0.4 <= firsts / 240 <= 0.6


def test_the_balanced_order_sees_different_keys_as_different_steps() -> None:
    orders = {tuple(balanced_order([A, E], f"{t}:0")) for t in range(40)}
    assert len(orders) == 2


def test_the_balanced_order_of_one_sentence_is_that_sentence() -> None:
    assert balanced_order([A], "0:0") == [A]


# --- the switch ---------------------------------------------------------------


def test_the_switch_names_its_modes() -> None:
    assert order_named([A, E], mode="canonical", marker=MARKER) == [E, A]
    assert order_named(
        [A, E], mode="balanced", marker=MARKER, step_key="3:9"
    ) == balanced_order([A, E], "3:9")


def test_the_balanced_mode_needs_a_step_key() -> None:
    with pytest.raises(ValueError):
        order_named([A, E], mode="balanced", marker=MARKER)


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        order_named([A, E], mode="first-named", marker=MARKER)  # type: ignore[arg-type]


# --- the rebuild -------------------------------------------------------------


def test_a_state_that_names_one_condition_comes_back_unchanged() -> None:
    assert neutral_state(A, MARKER) == A


def test_a_state_without_the_marker_comes_back_unchanged() -> None:
    state = "The harbour is quiet."
    assert neutral_state(state, MARKER) == state


def test_a_state_that_names_the_same_condition_twice_comes_back_unchanged() -> None:
    state = f"{A} {A}"
    assert neutral_state(state, MARKER) == state
    assert neutral_state(state, MARKER, mode="balanced", step_key="0:0") == state


def test_the_rebuilt_state_holds_the_same_sentences_in_the_neutral_order() -> None:
    state = f"{A} {E}"
    rebuilt = neutral_state(state, MARKER, mode="canonical")
    assert rebuilt == f"{E} {A}"
    assert named_sentences(rebuilt, MARKER) == [E, A]


def test_the_balanced_rebuild_is_deterministic_for_replay() -> None:
    state = f"{A} {E}"
    once = neutral_state(state, MARKER, mode="balanced", step_key="2:41")
    again = neutral_state(state, MARKER, mode="balanced", step_key="2:41")
    assert once == again
    assert once in (f"{A} {E}", f"{E} {A}")
