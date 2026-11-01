"""The sea-state recorder, fixed at the source.

**What this is.** The calibration note
([`docs/lab/exp-judge-calibration.md`](../../exp-judge-calibration.md)) §8
found the leak: the recorder that built the October trace —
`liquid-study/scripts/exp_c_hysteresis.py`, `make_trial` — meant to name
*"the true condition plus a decoy"*, but on a noise step it named the decoy
**and the truth's neighbour** (or the decoy twice), so **the truth was not
in the prompt at all**: 82 of the 240 recorded prompts were unwinnable by
arithmetic, and 43 of those named one condition twice. This module is the
fixed builder, in the repository where the fix is tested and merged:

* the named pair is **the true condition and the decoy, once each**, on
  every step — the recorder's own docstring, kept at last; and
* the pair's order is `core.judge.ordering`'s **canonical** order (the
  mode §8.2's measurement shipped): sorted by the condition's own name, a
  key of what the condition is, never of whether it is true.

**The task is unchanged.** The random stream is spent exactly as the old
builder spent it — same draws, same order — so the truth sequence, the
dwell pattern, the decoys and the noise labels come out identical to the
October trace's (pinned by the suite, `tests/judge/test_recorder_fix.py`).
Only the state text changed: which two conditions it names and in what
order.

**The noise label survives as a label.** With the order neutral and the
pair fixed, the presentation no longer depends on `shown`, so the noise
process the old recorder simulated (present the decoy with probability p)
has nothing left to present itself through — `shown` stays in the step
record as the label of which group a step belonged to in the October task,
and the note's §9 reads the fixed cell through it.

`old_make_trial` is the October builder kept verbatim, the regression
baseline: the suite runs the invariant on it and fails until it does
violate it. `prompt_faults` is the invariant, one function: no prompt may
omit the truth, and no prompt may name an option twice.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from core.judge.ordering import (  # noqa: E402
    OrderMode,
    canonical_order,
    condition_name,
    named_sentences,
    order_named,
)

#: the conditions and their sentences, verbatim from the recorder
#: (liquid-study's scripts/exp_c_hysteresis.py).
SEA_STATES: list[tuple[str, str]] = [
    ("flat calm", "the water is flat as glass between the breakwaters, no chop at all"),
    ("slight chop", "a light ripple runs across the water, short and regular, nothing breaking"),
    ("rough swell", "a long heavy swell comes up from the southwest and the whole boat lifts on it"),
    ("confused chop", "the sea is confused with rain on it, chop from two directions at once"),
    ("breaking water", "white water is breaking over the shoal and spray is coming aboard"),
]

#: the sentence each condition names, indexed by condition number.
TRUE_TEXT: list[str] = [f"The sea is {name}: {desc}." for name, desc in SEA_STATES]

#: the question, the recorder's own.
QUESTIONS: dict[str, Any] = {
    "type": "choice",
    "instructions": "What is the sea state?",
    "criteria": {
        "A": "flat calm: the water is flat as glass, no chop, no swell",
        "B": "slight chop: a light ripple, short and regular, nothing breaking",
        "C": "rough swell: a long heavy swell, the boat lifts on it",
        "D": "confused chop: chop from two directions at once, often with rain",
        "E": "breaking water: white water over the shoal, spray coming aboard",
    },
}

#: every state sentence starts with this.
MARKER = "The sea is "

#: the option letters, in the criteria's order — the letter a condition
#: name answers under (``KEYS[condition_index]``).
KEYS = "ABCDE"

#: the order mode §8.2's measurement shipped (the note's §9 keeps measuring
#: under it).
SHIPPED_MODE: OrderMode = "canonical"

#: the October recording's design, the one number every comparison ties to.
SEED = 20261031
N_TRIALS = 6
N_STEPS = 40
NOISE = 0.35


# --- the fixed builder ------------------------------------------------------


def step_state(
    truth: int,
    decoy: int,
    *,
    mode: OrderMode = SHIPPED_MODE,
    step_key: str | None = None,
) -> str:
    """The state a step asks: the truth and the decoy, once each, neutral order.

    The pair is the recorder's own stated pair ("mentions the true condition
    plus a decoy"); the order is ``core.judge.ordering``'s — canonical by
    default, the mode the measurement shipped.
    """
    pair = [TRUE_TEXT[truth], TRUE_TEXT[decoy]]
    ordered = order_named(pair, mode=mode, marker=MARKER, step_key=step_key)
    return " ".join(ordered)


def make_trial(rng: random.Random, n_steps: int, noise: float) -> list[dict]:
    """A time series of sea states that changes slowly, with perceptual noise.

    The draws are spent exactly as the October builder spent them (same
    calls, same order), so the truth sequence, the dwells, the decoys and
    the noise labels reproduce the recorded task step for step. What changed
    is only the state text: the truth and the decoy, named once each, in the
    neutral order.
    """
    steps = []
    truth = rng.randrange(len(SEA_STATES))
    dwell = 0
    for t in range(n_steps):
        if dwell <= 0:
            truth = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
            dwell = rng.randint(3, 9)
        dwell -= 1
        decoy = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
        shown = truth
        if rng.random() < noise:
            shown = decoy
        steps.append({
            "t": t,
            "truth": truth,
            "shown": shown,
            "decoy": decoy,
            "state": step_state(truth, decoy),
        })
    return steps


def build_trials(
    *,
    seed: int = SEED,
    n_trials: int = N_TRIALS,
    n_steps: int = N_STEPS,
    noise: float = NOISE,
) -> list[list[dict]]:
    """The 240-step task, from the October seed."""
    rng = random.Random(seed)
    return [make_trial(rng, n_steps, noise) for _ in range(n_trials)]


# --- the invariant ----------------------------------------------------------


def prompt_faults(state: str, truth: int) -> list[str]:
    """What a state violates, as the brief states it.

    No prompt may omit the truth, and no prompt may name an option twice.
    A clean prompt returns ``[]``.
    """
    names = [
        condition_name(sentence, MARKER)
        for sentence in named_sentences(state, MARKER)
    ]
    faults: list[str] = []
    truth_name = SEA_STATES[truth][0]
    if truth_name not in names:
        faults.append(f"the truth ({truth_name!r}) is not named")
    seen: set[str] = set()
    for name in names:
        if name in seen:
            faults.append(f"{name!r} is named twice")
        seen.add(name)
    return faults


def audit_trials(trials: Sequence[Sequence[dict]]) -> dict[str, Any]:
    """The invariant's count over a task: the number the note's §9 cites."""
    steps = [step for trial in trials for step in trial]
    omitted = [
        step for step in steps
        if any("not named" in fault for fault in prompt_faults(step["state"], step["truth"]))
    ]
    doubled = [
        step for step in steps
        if any("named twice" in fault for fault in prompt_faults(step["state"], step["truth"]))
    ]
    return {
        "steps": len(steps),
        "truth_omitted": len(omitted),
        "option_named_twice": len(doubled),
        "faulty": len({
            id(step)
            for step in steps
            if prompt_faults(step["state"], step["truth"])
        }),
    }


# --- the October builder, kept verbatim -------------------------------------


def old_make_trial(rng: random.Random, n_steps: int, noise: float) -> list[dict]:
    """The October recorder's builder, verbatim (the regression baseline).

    Copied from liquid-study's ``scripts/exp_c_hysteresis.py`` at the
    commit the October trace was recorded from. On a noise step it names
    the decoy and ``(truth + 1) % len(SEA_STATES)`` — which is the decoy
    again when the decoy came from above, and the truth's other neighbour
    when it came from below — so the truth is absent from every noise
    prompt. The suite runs the invariant on this and pins the violation.
    """
    steps = []
    truth = rng.randrange(len(SEA_STATES))
    dwell = 0
    for t in range(n_steps):
        if dwell <= 0:
            truth = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
            dwell = rng.randint(3, 9)
        dwell -= 1
        decoy = (truth + rng.choice([-1, 1])) % len(SEA_STATES)
        shown = truth
        if rng.random() < noise:
            shown = decoy
        # the text names the shown condition first, then names the other one
        other = decoy if shown != decoy else (truth + 1) % len(SEA_STATES)
        state = (TRUE_TEXT[shown] + " " + TRUE_TEXT[other])
        steps.append({
            "t": t,
            "truth": truth,
            "shown": shown,
            "decoy": other,
            "state": state,
        })
    return steps


def old_build_trials(
    *,
    seed: int = SEED,
    n_trials: int = N_TRIALS,
    n_steps: int = N_STEPS,
    noise: float = NOISE,
) -> list[list[dict]]:
    """The October task as the old builder spent the seed."""
    rng = random.Random(seed)
    return [old_make_trial(rng, n_steps, noise) for _ in range(n_trials)]


# --- the audit, run from the shell ------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--october", type=Path, default=None,
        help="an October trace to audit (its states, against its own truths)",
    )
    args = parser.parse_args()

    print("the old builder, on the October seed:")
    print(json.dumps(audit_trials(old_build_trials()), indent=2))
    print("the fixed builder, on the same seed:")
    print(json.dumps(audit_trials(build_trials()), indent=2))

    if args.october is not None:
        data = json.loads(args.october.read_text(encoding="utf-8"))
        print(f"the October file {args.october.name}, audited:")
        print(json.dumps(audit_trials(data["trials"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
