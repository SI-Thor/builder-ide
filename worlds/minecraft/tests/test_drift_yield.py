#!/usr/bin/env python3
"""The world's side of drift-pause: the yield event and the pause file.

Build #3 of ``docs/design/vibecode-in-world.md`` (the brief in
``~/lm-wt/drift-pause``): the world writes a ``drift.yield`` event
every time it stands aside, and it reads the drift detector's pause
file at the same admission seam. Nobody is killed; the world declines
new work politely and says so in the log of record.

    runtime/venv/bin/python tests/test_drift_yield.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "reflex"))

import agent_world_reflex.service as service  # noqa: E402
from agent_world_reflex.ledger import WorldLedger  # noqa: E402
from agent_world_reflex.service import _Pending, ReflexService  # noqa: E402

results: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    results.append(f"{'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")


def pending(bot: str) -> _Pending:
    return _Pending(
        bot, "builder", {}, [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}], ""
    )


def main() -> None:
    # -- the ledger writer ------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        ledger = WorldLedger(Path(tmp) / "ledger.sqlite3")
        ledger.yielded(["Kite", "Pebble"], "the box has 3 GB free; the rule is 25 GB")
        events = [
            e
            for e in ledger.events(types=["drift.yield"])
        ]
        payload = events[0].payload if events else {}
        check("one event per admission decision", len(events), 1)
        check("the event names who waited", payload.get("bots"), ["Kite", "Pebble"])
        check("the event says why", "25 GB" in str(payload.get("reason", "")), True)

    # -- the pause file ---------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "drift-pause.json"
        real = service.PAUSE_FILE
        service.PAUSE_FILE = path
        try:
            check("a missing file is no pause", service.drift_pauses(), {})
            path.write_text("not json at all")
            check("a malformed file is no pause", service.drift_pauses(), {})
            path.write_text(
                json.dumps(
                    {
                        "world": {"level": "tier", "reason": "refusal rate 1.0", "until": None},
                        "Kite": {
                            "level": "soft",
                            "reason": "stall",
                            "until": time.time() - 1.0,
                        },
                    }
                )
            )
            in_force = service.drift_pauses()
            check("an expired entry is not in force", "Kite" in in_force, False)
            check("an unexpired one is", "world" in in_force, True)
        finally:
            service.PAUSE_FILE = real

    # -- the service: the three stand-asides ------------------------------
    written: list[tuple[list[str], str]] = []

    class Recorder:
        def yielded(self, bots, why):
            written.append((list(bots), why))

    def fresh() -> ReflexService:
        return ReflexService(
            library=None, chooser=None, model=None, ledger=Recorder()
        )

    real_may_act = service.may_act
    real_pauses = service.drift_pauses
    try:
        # 1. the box rule: the batch is refused and the yield recorded.
        service.may_act = lambda: (False, "the box has 3 GB free; the rule is 25 GB")
        service.drift_pauses = lambda: {}
        svc = fresh()
        batch = [pending("Kite"), pending("Pebble")]
        svc._answer(batch)
        check(
            "the box rule refuses the batch",
            [i.error for i in batch],
            ["yielded: the box has 3 GB free; the rule is 25 GB"] * 2,
        )
        check(
            "the yield is recorded with who waited",
            written,
            [(["Kite", "Pebble"], "the box has 3 GB free; the rule is 25 GB")],
        )

        # 2. a world-level drift pause stands the world aside.
        written.clear()
        service.may_act = lambda: (True, "")
        service.drift_pauses = lambda: {
            "world": {"level": "tier", "reason": "refusal rate moved to 1.000"}
        }
        svc = fresh()
        batch = [pending("Kite")]
        svc._answer(batch)
        check(
            "a world pause yields politely",
            batch[0].error,
            "yielded: drift pause (tier): refusal rate moved to 1.000",
        )
        check("a pause is a yield too", "drift pause" in written[0][1], True)

        # 3. the soft level: one bot waits, and only that one.
        written.clear()
        service.drift_pauses = lambda: {
            "Kite": {"level": "soft", "reason": "worst gap 193x its median"}
        }
        svc = fresh()
        held = pending("Kite")
        svc._answer([held])  # the pack empties: no model is asked
        check(
            "a soft pause holds the named bot",
            held.error,
            "paused: drift pause (soft): worst gap 193x its median",
        )
        check(
            "the held bot is recorded as a yield",
            written,
            [(["Kite"], "drift pause (soft): held by the drift detector")],
        )
    finally:
        service.may_act = real_may_act
        service.drift_pauses = real_pauses

    failed = [line for line in results if line.startswith("FAIL")]
    print("\n".join(results))
    print()
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
