"""The M1 acceptance session as one test: the script must play end to end.

`driver.play` runs the evening → night → morning script step by step; each
step asserts its outcome and its latency budget, and the first failure
raises with the step's name. This wrapper prints the step table (pass or
fail) and asserts the whole session held.
"""

from __future__ import annotations

from driver import play
from session import StepFailure


def test_m1_session_plays_end_to_end(world):
    ses = play(world)
    table = ses.table()
    print("\n" + table)
    (world.run_dir / "steps.txt").write_text(table + "\n", encoding="utf-8")
    failed = [s for s in ses.steps if not s.ok]
    assert not failed, f"{len(failed)} failed steps:\n{table}"
    # the session covered every act and every named gate
    acts = {s.act for s in ses.steps}
    assert {"boot", "evening", "night", "morning"} <= acts
    names = {s.name for s in ses.steps}
    for gate in ("cold-open", "ask-mode", "kill-9", "computer-call",
                 "sealed-bet-crates"):
        assert gate in names, f"gate step {gate!r} missing"


def test_the_plan_gates_are_recorded(world):
    """The M1 slice gates (plan §2) are steps of the session, and they held."""
    ses = play(world) if not world.artifacts.get("steps") else None
    if ses is None:
        steps = world.artifacts["steps"]
    else:  # pragma: no cover — play already ran in the first test
        steps = ses.steps
    by_name = {f"{s.act}/{s.name}": s for s in steps}
    gates = {
        "(a) kill -9": "night/kill-9",
        "(b) two referents": "morning/computer-call",
        "(c) seal before render": "night/sealed-bet-crates",
        "(d) zero panel-side state": "night/kill-9",
        "cold open": "evening/cold-open",
        "question budget": "evening/ask-mode",
    }
    for label, key in gates.items():
        assert key in by_name, f"gate {label} has no step"
        assert by_name[key].ok, f"gate {label} failed"
    # the morning's decision budget, from the session itself
    decisions = sum(
        1 for s in steps
        if s.act == "morning" and "decision" in s.backends
    )
    assert decisions <= 10
