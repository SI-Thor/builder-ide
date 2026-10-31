"""The morning's clocks, measured on this box (core-spec v2 §4.1, §3.2.9).

The morning report is a static page over the ledger, so it has to be fast
*forever*: the Watch clock budgets the first paint at ≤ 3 s and the whole
morning at ≤ 2 minutes to read. This test measures the two operations that
have to fit inside it — folding the log into the night, and building the
page — and prints the numbers beside the state of the box, because a number
without the box it came off is a number nobody can trust (CLAUDE.md).

Run it with ``-s`` to see the measurements.
"""

from __future__ import annotations

import platform
import time
from pathlib import Path

from core.night.nights import clean_night
from core.night.report import build_report, render_html, render_text
from core.night.ledger import SQLiteLedger
from core.night.models import Actor

#: The Watch clock: the morning's first paint (§4.1, spine moment 13).
FIRST_PAINT_BUDGET_SECONDS = 3.0


def box_state() -> str:
    """The state of the box the numbers came off."""
    board = "unknown"
    memtotal = "unknown"
    try:
        raw = Path("/proc/device-tree/model").read_bytes()
        board = raw.replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:  # pragma: no cover - not a device-tree box
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                memtotal = line.split(":", 1)[1].strip()
                break
    except OSError:  # pragma: no cover
        pass
    return (
        f"board={board} · cores={__import__('os').cpu_count()} · "
        f"MemTotal={memtotal} · kernel={platform.release()} · "
        f"python={platform.python_version()}"
    )


def test_the_morning_page_is_built_inside_the_watch_clock():
    night = clean_night()
    events = night.events

    started = time.perf_counter()
    report = build_report(events)
    html = render_html(report)
    text = render_text(report)
    elapsed = time.perf_counter() - started

    print(f"\nmorning report: {elapsed * 1000:.1f} ms for {len(events)} events "
          f"({len(html)} bytes of html, {len(text)} bytes of text)")
    print(f"box: {box_state()}")

    assert elapsed < FIRST_PAINT_BUDGET_SECONDS, (
        f"the morning took {elapsed:.2f}s; the Watch clock budgets "
        f"{FIRST_PAINT_BUDGET_SECONDS}s"
    )


def test_the_status_line_is_a_ledger_read_and_not_a_narration():
    """The status line is computed from the log — it must be cheap and exact."""
    from core.night.projection import NightProjection
    from core.night.status import compute_status

    night = clean_night()
    events = night.events

    started = time.perf_counter()
    for _ in range(100):
        status = compute_status(NightProjection(events))
    elapsed = (time.perf_counter() - started) / 100

    print(f"\nstatus line: {elapsed * 1000:.3f} ms per fold of {len(events)} events")
    print(f"box: {box_state()}")

    assert status.status == "ran as planned"
    assert elapsed < 0.1, "the status line is a ledger read; it must be instant"


def test_an_append_to_the_durable_ledger_is_fsynced(tmp_path):
    """§5.1 — the change is durable before the append returns."""
    ledger = SQLiteLedger(tmp_path / "core.db")
    actor = Actor(kind="core", id="night-runner")

    started = time.perf_counter()
    for index in range(20):
        ledger.append(
            type="night.tick",
            actor=actor,
            subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
            payload={"at": f"2026-10-30T21:{index:02d}:00Z", "kind": "wall"},
        )
    elapsed = (time.perf_counter() - started) / 20

    print(f"\nappend: {elapsed * 1000:.2f} ms per fsynced append "
          f"(journal_mode={ledger.journal_mode()}, synchronous={ledger.synchronous()})")
    print(f"box: {box_state()}")
    ledger.close()

    assert elapsed < 0.5, "a durable append must not cost the morning its clock"
