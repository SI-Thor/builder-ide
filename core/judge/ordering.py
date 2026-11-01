"""The prompt's order policy: an order the answer cannot be read off.

The calibration note's finding
([`docs/lab/exp-judge-calibration.md`](../../docs/lab/exp-judge-calibration.md)
§5.5, §7): on the sea-state task the d1-2B answers the condition the prompt
names **first** — 85.8 % of its two-condition steps — so when the state names
a decoy first the model is confidently wrong, and its confidence, which tracks
the presentation rather than the world, is *anti*-correlated with being right
(AUC 0.2815). The state's order was the recorder's presentation choice ("the
shown condition first"), and a model that reads presentation as verdict turns
every presentation lie into a sure error.

The fix is upstream, in the prompt: name the conditions in an order that
carries no information about which one holds. Two orders are provided, both
deterministic, so a replay made today replays tomorrow:

* **canonical** — the named conditions sorted by a key of their own identity
  (the name the sentence carries). The key says what a condition *is*, never
  whether it is the true one, so the first-named condition is a function of
  which conditions the state names and of nothing else.
* **balanced** — the order a seeded coin chose for the step (sha256 over the
  caller's step key). Half the steps name either condition first, the same
  step always asks in the same order, and the coin reads nothing but the step
  key — the truth is not an input, so the order cannot leak it.

Which of the two a caller ships is a measurement, not a taste: the lab note's
§8 measured both on the fresh recording and the numbers pick.

This module only ever reorders what a state already names. It never decides
*which* conditions a state names — that is the caller's perception, and the
order fix does not touch it.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Sequence

__all__ = [
    "OrderMode",
    "ORDER_MODES",
    "condition_name",
    "named_sentences",
    "canonical_order",
    "balanced_order",
    "order_named",
    "neutral_state",
]

#: The two orders the policy ships.
OrderMode = Literal["canonical", "balanced"]

ORDER_MODES: tuple[str, ...] = ("canonical", "balanced")

#: The domain separator of the balanced order's coin, so a step key shared
#: with another seeded draw cannot collide with this one.
_BALANCED_DOMAIN = "judge-prompt-order:v1"


def named_sentences(state: str, marker: str) -> list[str]:
    """The state's condition sentences, in the order the state names them.

    A sentence is one marker-to-marker stretch (or marker-to-end). The text
    before the first marker is the state's preamble; the rebuilders keep it,
    so a rebuilt state differs from its input by the order of the sentences
    and nothing else.
    """
    if not marker:
        return []
    positions: list[int] = []
    at = state.find(marker)
    while at != -1:
        positions.append(at)
        at = state.find(marker, at + len(marker))
    if not positions:
        return []
    sentences: list[str] = []
    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(state)
        sentences.append(state[start:end].strip())
    return sentences


def condition_name(sentence: str, marker: str) -> str:
    """What a sentence names: the words between the marker and the colon.

    ``The sea is slight chop: a light ripple …`` names ``slight chop``. A
    sentence without a colon names its whole tail; this is the canonical
    key — a property of the condition's identity, unrelated to which
    condition is true.
    """
    tail = sentence[len(marker):].strip() if sentence.startswith(marker) else sentence.strip()
    colon = tail.find(":")
    return tail[:colon].strip() if colon != -1 else tail


def canonical_order(sentences: Sequence[str], marker: str) -> list[str]:
    """The sentences, sorted by the name each one carries.

    A stable sort: sentences that name the same condition keep their
    relative order, so a state that names one condition twice comes back
    unchanged.
    """
    return sorted(sentences, key=lambda sentence: condition_name(sentence, marker))


def balanced_order(sentences: Sequence[str], step_key: str) -> list[str]:
    """The sentences in the order a seeded coin chose for this step.

    The coin is the first bytes of ``sha256(domain + step_key)``, read as a
    Fisher–Yates shuffle: every permutation is equally likely, the same step
    key always draws the same permutation, and half the two-condition steps
    name either condition first. The step key is the caller's identity for
    the step — a ``(trial, t)`` pair rendered as text is enough. It must not
    be derived from which condition is true: the coin's whole job is to be
    unrelated to the answer.
    """
    ordered = list(sentences)
    digest = hashlib.sha256(f"{_BALANCED_DOMAIN}:{step_key}".encode()).digest()
    for index in range(len(ordered) - 1, 0, -1):
        draw = int.from_bytes(digest[index % len(digest):][:4], "big")
        swap = draw % (index + 1)
        ordered[index], ordered[swap] = ordered[swap], ordered[index]
    return ordered


def order_named(
    sentences: Sequence[str],
    *,
    mode: OrderMode,
    marker: str,
    step_key: str | None = None,
) -> list[str]:
    """The sentences in the chosen order; the switch the measurement set."""
    if mode == "canonical":
        return canonical_order(sentences, marker)
    if mode == "balanced":
        if step_key is None:
            raise ValueError("the balanced order needs the step's key")
        return balanced_order(sentences, step_key)
    raise ValueError(f"unknown order mode: {mode!r}")


def neutral_state(
    state: str,
    marker: str,
    *,
    mode: OrderMode = "canonical",
    step_key: str | None = None,
) -> str:
    """The same state with its named conditions in the neutral order.

    A state that names nothing (no marker), names one condition, or names
    the same condition twice comes back unchanged — there is no order for
    those prompts to leak. Anything else comes back with the same preamble,
    the same sentences, and nothing moved but their order.
    """
    sentences = named_sentences(state, marker)
    if len(sentences) < 2:
        return state
    first_break = state.find(marker)
    preamble = state[:first_break]
    ordered = order_named(sentences, mode=mode, marker=marker, step_key=step_key)
    return preamble + " ".join(ordered)
