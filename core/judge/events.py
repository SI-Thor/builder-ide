"""The judge seat's audit types — one type, and why it is one.

``judge.verdict`` carries one **attempt**: one backend's answers to one
question pack (or to the below-τ questions of one, when the pack was
escalated). Every attempt is a row, including the refused ones and the
ones escalated away from — the edges are the story, and a cascade's
bill is the sum of its rows.

The type lives in the closed set (§1.8); this module holds the seat's
own copy of its name, mirrored into ``core.records``,
``core.night.events`` and ``core.recipe.events`` so every reader of the
log agrees.
"""

from __future__ import annotations

__all__ = ["JUDGE_EVENT_TYPE", "JUDGE_EVENT_TYPES"]

#: The one audit type a judgment writes.
JUDGE_EVENT_TYPE = "judge.verdict"

JUDGE_EVENT_TYPES = frozenset({JUDGE_EVENT_TYPE})
