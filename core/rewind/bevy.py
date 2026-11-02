"""The Bevy world: the ``lm`` CLI, and the keep/drop proof on a round log.

The Bevy world is the one where byte-identical replay holds
(``docs/design/vibecode-in-world.md`` §2.6), so it is where the rewind is
*proved* rather than asserted.

Two mechanisms build the same world, and the diff between them is the proof:

* the **fork** — ``lm branch --at <tick> --drop <source>``: the round's own
  machinery, where the sim stops applying the dropped source's decisions
  from the branch tick on;
* the **reference** — ``lm run --inject <the kept decisions>``: the
  decisions the selection kept, replayed into a fresh round by the Python
  side.

The two share nothing but the ledger they read: the fork is Rust, the
reference is this package. ``lm diff`` between their logs is therefore a
cross-check and not a tautology.

One limit, and it is the limit the design note means by *"where replay
allows"*: the fork can only drop a **whole source**. A selection that keeps
some of a source's decisions and drops others is finer than the fork can
express; such a source is named in ``partial_sources`` and the reference is
the only world that can show it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .ledger import Ledger, read_bevy_dump, read_bevy_header
from .report import Outcome, Parked
from .selection import Selection, select

__all__ = [
    "BevyError",
    "BevyWorld",
    "ReplayResult",
    "DiffResult",
    "BevyKeep",
    "keep_from_round",
    "injection_lines",
]


class BevyError(RuntimeError):
    """The ``lm`` tool failed, or is not on the box."""


@dataclass(frozen=True)
class ReplayResult:
    """What ``lm replay`` said."""

    ok: bool
    hashes: int = 0
    output: str = ""


@dataclass(frozen=True)
class DiffResult:
    """What ``lm diff`` said."""

    identical: bool
    tick: int | None = None
    left: str = ""
    right: str = ""
    output: str = ""


class BevyWorld:
    """The Bevy world, through its CLI.

    Every call is a subprocess: the world is a Rust program, and this
    package reads it the way a person would — from the outside.
    """

    def __init__(self, binary: str = "lm") -> None:
        self.binary = binary

    def available(self) -> bool:
        """Whether the tool is on this box."""
        return shutil.which(self.binary) is not None

    def _call(self, args: Sequence[str]) -> subprocess.CompletedProcess:
        if not self.available():
            raise BevyError(f"no {self.binary!r} on PATH")
        return subprocess.run(
            [self.binary, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    # -- the commands ------------------------------------------------------

    def run(
        self,
        *,
        seed: int,
        ticks: int,
        out: Path | str,
        inject: Path | str | None = None,
    ) -> str:
        """Play a headless round and write its log."""
        args = [
            "run",
            "--seed",
            str(seed),
            "--ticks",
            str(ticks),
            "--out",
            str(out),
        ]
        if inject is not None:
            args.extend(["--inject", str(inject)])
        result = self._call(args)
        if result.returncode != 0:
            raise BevyError(f"lm run failed: {result.stderr.strip()}")
        return result.stdout

    def replay(self, log: Path | str) -> ReplayResult:
        """Replay a log and check every hash it recorded."""
        result = self._call(["replay", str(log)])
        output = (result.stdout + result.stderr).strip()
        hashes = 0
        if result.returncode == 0 and output.startswith("OK "):
            try:
                hashes = int(output.split()[1])
            except (IndexError, ValueError):
                hashes = 0
        return ReplayResult(ok=result.returncode == 0, hashes=hashes, output=output)

    def diff(self, left: Path | str, right: Path | str) -> DiffResult:
        """Compare two logs and name the first tick that moves."""
        result = self._call(["diff", str(left), str(right)])
        output = result.stdout.strip()
        if output == "IDENTICAL":
            return DiffResult(identical=True, output=output)
        tick: int | None = None
        left_hash = ""
        right_hash = ""
        if output.startswith("DIFFER at tick "):
            try:
                rest = output[len("DIFFER at tick ") :]
                tick_text, hashes = rest.split(": ", 1)
                tick = int(tick_text.strip())
                left_hash, right_hash = (part.strip() for part in hashes.split(" != ", 1))
            except (ValueError, IndexError):
                tick = None
        return DiffResult(
            identical=False, tick=tick, left=left_hash, right=right_hash, output=output
        )

    def dump(self, log: Path | str, *, header: bool = True) -> str:
        """Print a log's decisions, in the format ``lm run --inject`` reads."""
        args = ["dump"]
        if header:
            args.append("--header")
        args.append(str(log))
        result = self._call(args)
        if result.returncode != 0:
            raise BevyError(f"lm dump failed: {result.stderr.strip()}")
        return result.stdout

    def branch(
        self,
        parent: Path | str,
        *,
        at: int,
        out: Path | str,
        drops: Sequence[str] = (),
        reflexes: Sequence[str] = (),
        params: Sequence[str] = (),
    ) -> str:
        """Rewind a round to a tick, change one thing and re-run it."""
        args = ["branch", str(parent), "--at", str(at)]
        for drop in drops:
            args.extend(["--drop", drop])
        for reflex in reflexes:
            args.extend(["--reflex", reflex])
        for param in params:
            args.extend(["--param", param])
        args.extend(["--out", str(out)])
        result = self._call(args)
        if result.returncode != 0:
            raise BevyError(f"lm branch failed: {result.stderr.strip()}")
        return result.stdout


# ==================================================================== the proof


@dataclass
class BevyKeep:
    """What a keep/drop on a round log did."""

    point: int
    selection: Selection
    kept: tuple[Outcome, ...] = ()
    dropped: tuple[Outcome, ...] = ()
    dropped_sources: tuple[str, ...] = ()
    partial_sources: tuple[str, ...] = ()
    fork: str = ""
    reference: str = ""
    identical: bool | None = None
    diff: DiffResult | None = None
    notes: tuple[str, ...] = ()

    def report(self, *, source: str = "") -> Any:
        from .report import RewindReport

        return RewindReport(
            source=source,
            point=f"tick {self.point}",
            selection=self.selection.text,
            kept=self.kept,
            dropped=self.dropped,
            notes=self.notes,
        )


def injection_lines(rows: Sequence[Any]) -> list[str]:
    """The kept decisions as the injection file ``lm run --inject`` reads."""
    lines: list[str] = []
    for row in rows:
        payload = row.payload
        decision = payload.get("decision")
        if decision is None:
            continue
        lines.append(
            json.dumps(
                {"arrived": int(payload.get("arrived") or 0), "decision": decision},
                sort_keys=True,
            )
        )
    return lines


def keep_from_round(
    world: BevyWorld,
    *,
    parent: Path | str,
    at: int,
    selection: Selection,
    out_dir: Path | str,
    name: str = "keep",
    build_reference: bool = True,
) -> BevyKeep:
    """Rewind a round to a tick, keep the selected decisions, drop the rest.

    The events before the tick are the prefix the fork and the canon share;
    the selection is applied to the events from the tick on.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dump = world.dump(parent, header=True)
    header = read_bevy_header(dump)
    ledger = read_bevy_dump(dump, source=str(parent))

    after = [row for row in ledger.rows if row.at >= at]
    result = select(_LedgerView(after, "tick"), selection)

    kept_rows = [row for row in ledger.rows if row.at < at]
    kept_rows.extend(result.kept)
    dropped_rows = [row for row, _ in result.dropped]

    kept_sources = {row.actor for row in result.kept}
    dropped_sources = sorted(
        {row.actor for row in dropped_rows} - kept_sources
    )
    partial_sources = sorted(
        {row.actor for row in dropped_rows} & kept_sources
    )

    notes: list[str] = []
    if partial_sources:
        notes.append(
            "the fork can only drop a whole source; "
            + ", ".join(partial_sources)
            + " kept some decisions and dropped others, so the fork keeps "
            "them all and the reference shows the finer selection"
        )

    fork_path = out_dir / f"{name}-fork.lml"
    world.branch(
        parent,
        at=at,
        out=fork_path,
        drops=dropped_sources,
    )

    reference_path = out_dir / f"{name}-reference.lml"
    identical: bool | None = None
    diff: DiffResult | None = None
    if build_reference:
        inject_path = out_dir / f"{name}-kept.jsonl"
        inject_path.write_text(
            "\n".join(injection_lines(kept_rows)) + "\n", encoding="utf-8"
        )
        seed = int(header.get("seed") or 0)
        first = int(header.get("start_tick") or 0)
        last = int(header.get("last_tick") or first)
        ticks = max(1, last - first + 1)
        world.run(seed=seed, ticks=ticks, out=reference_path, inject=inject_path)
        diff = world.diff(fork_path, reference_path)
        identical = diff.identical
        if identical:
            notes.append(
                "the fork and the reference are the same world, tick for tick"
            )
        else:
            notes.append(
                "the fork and the reference parted company at tick "
                f"{diff.tick}: {diff.output}"
            )

    kept_outcomes = tuple(
        Outcome(
            seq=int(row.seq),
            at=str(int(row.at)),
            actor=row.actor,
            kind=row.kind,
            kept=True,
            reason="kept",
        )
        for row in kept_rows
    )
    dropped_outcomes = tuple(
        Outcome(
            seq=int(row.seq),
            at=str(int(row.at)),
            actor=row.actor,
            kind=row.kind,
            kept=False,
            reason=reason,
        )
        for row, reason in result.dropped
    )

    return BevyKeep(
        point=at,
        selection=selection,
        kept=kept_outcomes,
        dropped=dropped_outcomes,
        dropped_sources=tuple(dropped_sources),
        partial_sources=tuple(partial_sources),
        fork=str(fork_path),
        reference=str(reference_path) if build_reference else "",
        identical=identical,
        diff=diff,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class _LedgerView:
    """The rows after the point, as the selection reads them."""

    rows: tuple[Any, ...]
    time_unit: str = "tick"
