"""The empty project's first screen (spec §3.5; G §1 19:58).

On night one the only honest currency is the sealed guess and the measured
number, and the first line the product ever speaks is where that starts. The
line comes from the ledger, not the world, so it is instant — and it obeys
three rules that gaps §7 test 1 turns into assertions:

* it **carries its denominator** — "0 of 0", never an adjective standing in
  for a count (the killed `ux-day` opener "I'm reading that as 'straight
  lines, weathered wood'" is inadmissible for exactly this reason — X C1);
* it says **nothing about the owner** — builders "express taste about
  artifacts, never about the owner" (T §"The taste ledger"), and with zero
  rows there is nothing to say anyway;
* it makes **exactly one offer** — of four **seeds, not guesses**, each chip
  carrying its seed on its face.

The structural guarantee: `companion_opening` takes *counts*, not
descriptions. There is no parameter through which an adjective about the
owner could enter the line; the coldness is computed, never written.
"""

from __future__ import annotations

from .models import ColdOpen, SeedStarter, TasteRow
from .stubs import taste_rows_from_events

__all__ = ["FOUR_STARTERS", "companion_opening", "opening_line"]

#: §3.5 — the four starters: seeds, not guesses, each with its seed on its face.
FOUR_STARTERS: tuple[SeedStarter, ...] = (
    SeedStarter(name="harbor hamlet", seed=4471),
    SeedStarter(name="forest stead", seed=12),
    SeedStarter(name="mountain bothy", seed=902),
    SeedStarter(name="blank terrain", seed=0),
)


def opening_line(*, kept: int, observed: int) -> str:
    """The Companion's first line, from counts alone.

    On the empty ledger: "First night. I have nothing on you — 0 of 0. Four
    ways to start; pick one and I'll learn from what you keep." Once rows
    exist the line carries their denominator instead — the same sentence
    shape, honestly grown (G §1 07:12 keeps calling low N "a start, not
    taste" in the *report*; the opener's job is only never to overclaim).
    """
    if observed == 0:
        return (
            "First night. I have nothing on you — 0 of 0. "
            "Four ways to start; pick one and I'll learn from what you keep."
        )
    return (
        f"You've kept {kept} of {observed} so far. "
        "Four ways to start; pick one and I'll learn from what you keep."
    )


def companion_opening(
    events, *, author: str = "casey", starters=FOUR_STARTERS
) -> ColdOpen:
    """The first screen over whatever the ledger currently holds.

    Rows are author-scoped (§1.7): Magnus's rows never inform Casey's opener,
    and `pending_ratification` rows are inert — the same exclusions every
    builder's slice applies.
    """
    rows: list[TasteRow] = [
        row
        for row in taste_rows_from_events(events)
        if row.author == author and row.status == "active"
    ]
    kept = sum(1 for row in rows if row.kept)
    return ColdOpen(
        line=opening_line(kept=kept, observed=len(rows)),
        starters=starters,
        taste_rows=len(rows),
        kept=kept,
    )
