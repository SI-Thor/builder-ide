"""The lifecycle behaviours borrowed from cognitive-ecology.

Per the fit study's recommendation (carried in BRIEF.md): borrow **lifecycle
and consolidation as behaviours**, adopt neither the tick loop nor the
attention economy. What is borrowed is the piece ADR-0002 calls the bridge —
the one place the kernel's statuses become numbers and rules:

    alive    1.0   JUSTIFIED — full weight in whatever queue asks
    unknown  0.25  QUESTIONABLE — kept, never deleted; runs at a discount
                   and surfaces in the morning report
    dead     0.0   DEAD (removal justified) — but builder-ide never deletes
                   (spec §1.2: "a rejection is a branch you can revisit");
                   dead dependents are retained, flagged, and barred from
                   entering new work
    absent   —     UNWIRED — no justification edge mentions it; a
                   consolidation candidate for the morning report

These are the same constants as upstream's attention.JUSTIFICATION_WEIGHTS
(alive 1.0 / unknown 0.25 / dead 0.0), quoted there as "the one place to
watch for gaming". Here they are a read-only derived view other seats may
consume (a scheduler, the morning report); nothing bids, nothing ticks.
"""

from __future__ import annotations

from core.why import Status

#: The label is a word, never a colour (spec §4.3's panel rule).
LABELS: dict[str, str] = {
    "alive": "justified",
    "unknown": "questionable",
    "dead": "dead",
    "absent": "unwired",
}

#: Borrowed weights — a derived view, not an attention economy (BRIEF.md).
WEIGHTS: dict[str, float] = {
    "alive": 1.0,
    "unknown": 0.25,
    "dead": 0.0,
    "absent": 0.0,
}


def label(status: Status) -> str:
    return LABELS[status.value]


def weight(status: Status) -> float:
    return WEIGHTS[status.value]


def may_enter_new_work(status: Status) -> bool:
    """The one gate: questionable work continues at a discount; dead work
    may not start anything new (its records are retained regardless)."""
    return status is Status.ALIVE or status is Status.UNKNOWN
