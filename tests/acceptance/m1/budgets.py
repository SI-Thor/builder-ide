"""The latency budgets of the experience spine, as numbers a test can check.

Every constant below is a `[b]` budget from `docs/design/core-spec.md` §4.1
("Service budgets by clock") and the experience-measures table of
`docs/plan.md` §6; the citation names the spine moment it comes from
(`docs/research/rev-ux.md` §5, S1–S15, and `docs/research/gaps.md`). The
three clocks (D §"The three clocks"): **Talk ≤ 2 s · Watch ≤ 5 s per card ·
Workshop ≤ 60 s with progress and a cancel** — anything that cannot hold its
clock moves to the night queue.

The budgets are pass/fail, not targets: a step that is honest but late, or
fast but fabricated, is equally a failure (plan §6). Today every step runs
in-process against materialized seats and stubs, so the timings are
microseconds — the assertions stay because they are the regression gate for
the day the real services, models and renders stand behind the same
interfaces.
"""

from __future__ import annotations

# --- Talk (≤ 2 s) -----------------------------------------------------------

#: First line after open, cold or return (X S1/S2; G §7 test 1).
FIRST_LINE_S = 2.0
#: A chip lands, Casey's or Magnus's (X S3/S4).
CHIP_LANDS_S = 1.5
#: One ask-mode answer, one tap (spec §3.5; X S3).
ASK_ANSWER_S = 1.5
#: The confirm line is readable (X S6; D §4) — the Talk half of the compile.
CONFIRM_READABLE_S = 5.0
#: The stop button answers (X S9).
STOP_S = 2.0
#: Keep / reject, one tap (spec §4.1).
KEEP_REJECT_S = 2.0
#: A parked question answered, one tap (X S12).
QUESTION_ANSWER_S = 2.0
#: "Why?" opens (X S13 — the best-supported promise in the corpus).
WHY_S = 1.0
#: An evidence card opens (spec §4.1; D §4 moment 9).
EVIDENCE_CARD_S = 1.0

# --- Watch (≤ 5 s per card) --------------------------------------------------

#: Joining the night feed cold (X S9).
PEEK_JOIN_S = 5.0
#: One feed card legible (X S9).
CARD_LEGIBLE_S = 5.0
#: The pre-flight line, ten seconds after "Start the night" (spine moment 9).
PREFLIGHT_S = 10.0
#: The morning report's first paint (X S10); the text mode is the same read.
REPORT_FIRST_PAINT_S = 3.0
#: The report digestible (X S10).
REPORT_DIGEST_S = 120.0
#: A branch flip is a pointer move (X S11; spec §1.2).
BRANCH_FLIP_S = 2.0

# --- Workshop (≤ 60 s with progress and a cancel) ----------------------------

#: `/v1/call` compiles (X S6; D §21:08; spec §4.1 "compile ≤ 20 s").
COMPILE_S = 20.0
#: The plan slate transaction — no cancel needed, the night has not started
#: (X C13: before the night a slow decision is free).
SLATE_TRANSACTION_S = 30.0
#: Applying a branch, head move plus pre-baked artifacts (X S11).
APPLY_S = 10.0
# Re-stream after apply is ≤ 15 s but measurement-gated on the LOD spike
# (X R1; RV patch 14) — not asserted here, and not owed until measured.

# --- Counts, not seconds -----------------------------------------------------

#: A morning may ask for at most this many decisions (G §4.3; X G6).
DECISIONS_PER_MORNING = 10
#: Cold-start questions in the first session (G §1; spec §3.5: ≤ 6).
QUESTIONS_FIRST_SESSION = 6
#: Blocking questions that may exist at once; the fourth parks the task
#: (G §4.5; spec §3.2.6).
BLOCKING_QUESTIONS = 3


def seconds(name: str) -> float:
    """Look a budget up by its constant name — used by the step table."""
    table = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, float)}
    return table[name.rstrip("_S")]
