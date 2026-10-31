"""The seven-night melt run as one test: the week must play end to end.

`meltweek.play_week` runs evening → night → morning seven times against the
simulated owner, asserting each step's outcome, its budget and the plan's
week-3 item 13 checks as it goes; the first failure raises with the step's
name. This wrapper prints the step table and the per-night melt table (pass
or fail) and re-derives the week-level checks a second time from the
ledgers alone.
"""

from __future__ import annotations

from meltweek import play_week
from script import EXPECTED_QUESTIONS


def test_the_week_plays_end_to_end(world):
    ses = play_week(world)
    table = ses.table() + "\n\n" + world.week["table"]
    print("\n" + table)
    (world.run_dir / "steps.txt").write_text(table + "\n", encoding="utf-8")
    failed = [s for s in ses.steps if not s.ok]
    assert not failed, f"{len(failed)} failed steps:\n{table}"
    # every act played: the boot, seven evenings, nights and mornings, the week
    acts = {s.act for s in ses.steps}
    assert {"boot", "evening", "night", "morning", "week"} <= acts
    for act in ("evening", "night", "morning"):
        assert sum(1 for s in ses.steps if s.act == act) >= 7 * 4
    names = {s.name for s in ses.steps}
    for gate in ("n1-open", "n1-ask", "n1-queue-dam", "n5-ask", "n7-open",
                 "n4-gate-rebuild", "melt-table"):
        assert gate in names, f"gate step {gate!r} missing"


def test_the_melt_rederives_from_the_ledger(world):
    """Item 13's checks, held again against the ledgers alone — not against
    the driver's own bookkeeping."""
    if not world.week.get("nights") or len(world.week["nights"]) < 7:
        play_week(world)  # pragma: no cover — the first test already played it
    records = world.week["nights"]
    asker = world.asker
    from owner import BANK_CODES

    # the melt: questions → 0, per code, as denominators passed two
    assert [r["questions"] for r in records] == list(EXPECTED_QUESTIONS)
    melted = asker.gate.melted_codes("companion")
    assert set(BANK_CODES) <= melted, "the companion still has codes to ask"

    # guesses → gone: every sealed guess sat below two observations; nothing
    # sealed `guess` on a code that held two
    for r in records:
        for seal in r.get("taste_seals", []):
            if seal["confidence"] == "guess":
                assert seal["observations"] < 2
            else:
                assert seal["observations"] >= 2

    # the budget and the attention trend
    assert all(r["decisions"] <= 10 for r in records)
    attention = [r["attention"] for r in records]
    assert attention[-1] < attention[0]
    assert all(r["standing"] for r in records)

    # the spine's ledger carries the same melt, code for code
    spine = world.spec.taste(author="casey")
    spine_rows = spine.get("notes", spine.get("rows", []))
    assert len(spine_rows) == len(
        asker.ledger.events(types=["taste.note.appended"]))
