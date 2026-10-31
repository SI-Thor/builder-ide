"""The session recorder: one line per step, with its budget and its backend.

The M1 acceptance session is a script that must play end to end; each step
asserts its outcome **and** its latency budget from the spine
(`budgets.py`). Because the core's parts are not on `main` yet, each step
also records **what served it** — which sibling seat (materialized from its
branch), and what was a stub — so the run's output is an honest map of the
integration as it stands. The legend:

* `real:<seat>` — the sibling branch's own code did the work.
* `bridge` — real code on both sides, joined by a thin adapter here (the
  seam that disappears when the seats merge).
* `stub` — nothing on any branch owns this yet (the stub generator's
  renders, the scripted critic, the stub engine rungs); the plan says so
  (plan §2 M1 risks).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class Step:
    act: str          # evening / night / morning / gates
    name: str
    clock: str        # Talk / Watch / Workshop / —
    budget_s: float | None
    backends: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def backend_line(self) -> str:
        return "+".join(self.backends) if self.backends else "?"

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(label, bool(ok), detail))
        return bool(ok)

    def note(self, text: str) -> None:
        self.notes.append(text)


class StepFailure(AssertionError):
    """A session step failed its outcome or its budget."""

    def __init__(self, step: Step, message: str) -> None:
        self.step = step
        super().__init__(f"[{step.act}/{step.name}] {message}")


class Session:
    """Plays the script and keeps the step table."""

    def __init__(self, world: "World") -> None:
        self.world = world
        self.steps: list[Step] = []

    @contextmanager
    def step(
        self,
        name: str,
        *,
        act: str,
        clock: str = "—",
        budget: float | None = None,
        backend: str | list[str] | None = None,
    ) -> Iterator[Step]:
        step = Step(
            act=act, name=name, clock=clock, budget_s=budget,
            backends=[backend] if isinstance(backend, str) else list(backend or []),
        )
        self.steps.append(step)
        started = time.perf_counter()
        try:
            yield step
        except Exception as exc:  # the script itself broke — not a verdict
            step.elapsed_s = time.perf_counter() - started
            raise StepFailure(step, f"step raised {exc!r}") from exc
        step.elapsed_s = time.perf_counter() - started
        if budget is not None:
            step.check(
                f"{clock} budget ≤ {budget:g} s" if clock != "—" else f"budget ≤ {budget:g} s",
                step.elapsed_s <= budget,
                f"took {step.elapsed_s * 1000:.1f} ms",
            )
        if not step.ok:
            failed = "; ".join(c.label for c in step.checks if not c.ok)
            raise StepFailure(step, failed)

    # -- reporting -------------------------------------------------------------

    def table(self) -> str:
        head = (
            f"{'STEP':<34} {'CLK':<9} {'MS':>8} {'BUDGET':>7} "
            f"{'BACKEND':<44} RESULT"
        )
        lines = [head, "-" * len(head)]
        for s in self.steps:
            ms = f"{s.elapsed_s * 1000:.1f}"
            budget = f"{s.budget_s:g}s" if s.budget_s is not None else "—"
            result = "PASS" if s.ok else "FAIL"
            lines.append(
                f"{s.act + '/' + s.name:<34} {s.clock:<9} {ms:>8} {budget:>7} "
                f"{s.backend_line:<44} {result}"
            )
        for s in self.steps:
            for n in s.notes:
                lines.append(f"  · [{s.act}/{s.name}] {n}")
        return "\n".join(lines)

    @property
    def decisions_asked(self) -> int:
        """How many decisions the morning asked of the owner so far.

        Counted where the product counts them: owner keep/apply/reject/answer
        calls the session made during the morning act (G §4.3's attention
        number is decisions, not clicks).
        """
        return sum(
            1
            for s in self.steps
            if s.act == "morning" and any(b == "decision" for b in s.backends)
        )


class World:
    """Everything the session shares: the client, the doors, the seats, the ids.

    One fresh `$BUILDER_HOME` per run (spec §1.0 layout); the spine ledger is
    the only store the panels ever read.
    """

    def __init__(self, home: Path, run_dir: Path) -> None:
        self.home = home
        self.run_dir = run_dir
        self.stamps: dict[str, Any] = {}      # night_id, wo ids, task ids…
        self.artifacts: dict[str, Any] = {}   # scratch handles for assertions
