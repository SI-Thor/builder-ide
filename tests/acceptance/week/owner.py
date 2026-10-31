"""The simulated owner: a fixed, seeded taste, stated as rules.

Plan item 13's melt run is "seven nights against the real owner **or a
simulated one**" (`docs/plan.md` §2 M2; G §1.9's test: "simulate seven
nights against a fake owner"). This is that owner. Everything the owner
does is a rule over one seeded table — no judgment, no randomness — so the
melt's input is exactly reproducible and the run's only variables are the
mechanisms under test.

The rules, stated once:

1. **The value table is the taste.** Exactly one of every pair the product
   can offer is kept — the eight pairs of the night-one question bank
   (`cold-start`'s `bank.py`) and the value labels the week's night edits
   land on (crate styles, weathering tones, rack depths). The kept side of
   each pair is the seeded taste; there is no other input.
2. **Ask-mode answers pick the kept chip.** Whatever the two crops show,
   the owner taps the chip whose value the table keeps — so every answer
   writes a `keep` row on the question's reason code (ask answers are keeps
   by construction; the taste ledger's rejects come from rule 4).
3. **The morning's branch choice follows the same table.** The night's edit
   lands on one value; the owner applies the night's branch when the table
   keeps that value and keeps yesterday (the standing exit) when it does
   not.
4. **Unprompted verdicts name the night's scripted flaw.** Each night's
   artifact carries one flaw class — one of the four closed reason codes
   the question bank does *not* cover (`too_busy`, `too_messy`, `too_dark`,
   `no_focus`), so the owner's unprompted rows melt *every* builder
   (unattributed rows count for all, cold-start's gate) while the bank's
   codes melt only the builder that asked. The verdict is rule 1's; the
   code is the flaw's.
5. **A sealed taste bet scores the way the artifact ruled.** The builder
   bet "you keep this"; if the table keeps the artifact's value the bet
   hits, else it misses. No forgiveness, no streaks.
"""

from __future__ import annotations

#: Rule 1 — the seeded taste over values. Exactly one kept side per pair.
VALUE_TASTE: dict[str, bool] = {
    # the eight bank pairs (cold-start bank.py, in bank order)
    "deep": True, "flush": False,                    # joints
    "weathered": True, "fresh-cut": False,           # wood age
    "cluttered": True, "shipshape": False,           # jetty
    "big": True, "snug": False,                      # shed scale
    "lantern-lit": True, "floodlit": False,          # quay light
    "mixed": True, "birch-only": False,              # stand
    "rope-handled": True, "plain": False,            # crate handles
    "mist": True, "clear": False,                    # dawn
    # the night edits' value labels (the week's script lands on these)
    "stained": True,                                 # crate style
    "gray": True, "dark": True, "pale": False,       # weathering tones
    "deep-racks": True, "shallow-racks": False,      # rack depth
}

#: Rule 4 — the flaw classes are the four codes the bank does not cover, so
#: the two melt tracks (asked rows melt the asker; unprompted rows melt
#: everyone) stay separable in the ledger.
FLAW_CODES: tuple[str, ...] = ("too_busy", "too_messy", "too_dark", "no_focus")

#: The bank's eight codes — the asked track (melt the Companion only).
BANK_CODES: tuple[str, ...] = (
    "too_clean", "wrong_era", "too_empty", "wrong_scale",
    "too_bright", "too_flat", "wrong_material", "wrong_weather",
)


class SimulatedOwner:
    """Casey, as far as this week is concerned: the rules above, nothing else."""

    author = "casey"

    # -- rule 2: ask-mode answers ------------------------------------------------

    def answer_chip(self, question):
        """The chip the owner taps: the one whose value the table keeps.

        Exactly one of the two qualifies — the table is seeded so — which is
        itself asserted at boot by `owner_table_is_a_taste`.
        """
        kept = [chip for chip in question.chips if VALUE_TASTE.get(chip.value)]
        if len(kept) != 1:
            raise ValueError(
                f"the seeded taste must keep exactly one chip of {question.id!r}, "
                f"keeps {[c.id for c in kept]}"
            )
        return kept[0]

    # -- rules 1, 3, 4, 5: verdicts over artifacts ---------------------------------

    def keeps_value(self, value: str) -> bool:
        if value not in VALUE_TASTE:
            raise ValueError(f"the script landed on {value!r}, which the table does not seed")
        return VALUE_TASTE[value]

    def branch_choice(self, night_edit_value: str) -> str:
        """"apply" the night's branch, or "keep yesterday" — the standing exit."""
        return "apply" if self.keeps_value(night_edit_value) else "keep-yesterday"

    def artifact_verdict(self, value: str) -> str:
        return "keep" if self.keeps_value(value) else "reject"

    def taste_bet_outcome(self, night_edit_value: str) -> str:
        """Rule 5 — the sealed "you keep this" bet scores as the artifact ruled."""
        return "keep" if self.keeps_value(night_edit_value) else "reject"


#: The one owner. The week is deterministic; a second owner would be a
#: different run, not a different rule set.
OWNER = SimulatedOwner()


def owner_table_is_a_taste(bank) -> list[str]:
    """Every pair the week can offer has exactly one kept side.

    Checked from the question bank at boot: each question's two chip values
    split one keep / one reject. This is the sense in which the taste is
    *seeded* rather than arbitrary.
    """
    problems = []
    for candidate in bank:
        keeps = [c.value for c in candidate.chips if VALUE_TASTE.get(c.value)]
        if len(keeps) != 1:
            problems.append(f"{candidate.prompt!r}: keeps {keeps}")
    return problems
