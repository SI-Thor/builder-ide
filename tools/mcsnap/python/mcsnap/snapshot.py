"""Taking a snapshot of a live Paper world.

The order of operations, and why each is where it is:

1. ``save-off`` — the server stops writing the world on its own schedule.
   Without it the copy can catch a chunk half-written, and the sha256 in
   the manifest would be of a file that never existed.
2. ``save-all flush`` — every chunk in every dimension is written to disk
   **now**, and the server waits for it. This is the moment the world's
   state stops moving.
3. the copy — the world's files, hashed as they sit in the snapshot.
4. ``save-on`` — the server goes back to writing on its own schedule. It
   runs even when the copy fails: a server left with saving switched off
   is a server that will lose the world's next hour.

The snapshot is a **copy**, never a move. The world keeps running while
the snapshot is taken, and the snapshot is a separate tree with a manifest
beside it.

A snapshot without a server to talk to is still possible — the files on
disk are copied as they are — and the manifest then says so, because a
snapshot of a stopped world and a snapshot of a running world are not the
same kind of thing.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ledger import ledger_head
from .manifest import (
    MANIFEST_NAME,
    FileEntry,
    Manifest,
    section_totals,
    sha256_file,
    write_manifest,
)
from .nbt import level_facts, read_nbt
from .world import copy_tree, plan_tree

__all__ = ["SnapshotResult", "take_snapshot", "snapshot_id_for", "server_facts"]


@dataclass
class SnapshotResult:
    """What a snapshot produced."""

    manifest: Manifest
    directory: Path
    timings: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """A short summary, for the CLI and the report."""
        return {
            "snapshot_id": self.manifest.snapshot_id,
            "directory": str(self.directory),
            "files": self.manifest.totals.get("files", 0),
            "bytes": self.manifest.totals.get("bytes", 0),
            "ledger_seq": self.manifest.ledger_seq,
            "tick": self.manifest.world.get("tick"),
            "day_time": self.manifest.world.get("day_time"),
            "timings": self.timings,
        }


def snapshot_id_for(when: datetime | None = None) -> str:
    """A snapshot's name: the moment, and a short unique suffix."""
    moment = when or datetime.now(timezone.utc)
    return f"snap-{moment.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def server_facts(command: Callable[[str], str]) -> dict[str, Any]:
    """What the server says about itself.

    Paper's ``version`` command answers with a sentence like
    ``This server is running Paper version git-Paper-196 (MC: 1.21.4)``.
    The sentence is kept whole, and the two pieces are pulled out of it.
    """
    try:
        answer = command("version")
    except Exception as error:  # the server may be down; the snapshot is not
        return {"available": False, "error": str(error)}
    text = _strip_colours(answer).strip()
    facts: dict[str, Any] = {"available": True, "version_line": text}
    if "Paper version" in text:
        tail = text.split("Paper version", 1)[1].strip()
        facts["paper_version"] = tail.split()[0] if tail else ""
    if "MC:" in text:
        facts["minecraft_version"] = text.split("MC:", 1)[1].split(")")[0].strip()
    return facts


def _strip_colours(text: str) -> str:
    """The section codes a Minecraft server writes (a sign then a letter)."""
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\u00a7" and index + 1 < len(text):
            index += 2
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _hash_tree(root: Path, section_of: dict[str, str]) -> list[FileEntry]:
    """Every file under the snapshot, hashed, with its section."""
    entries: list[FileEntry] = []
    for absolute in sorted(p for p in root.rglob("*") if p.is_file()):
        relpath = absolute.relative_to(root).as_posix()
        stat = absolute.stat()
        entries.append(
            FileEntry(
                relpath=relpath,
                size=stat.st_size,
                sha256=sha256_file(absolute),
                mtime=stat.st_mtime,
                section=section_of.get(relpath, "unclassified"),
            )
        )
    return entries


def take_snapshot(
    world_dir: str | Path,
    out_dir: str | Path,
    *,
    ledger_path: str | Path | None = None,
    command: Callable[[str], str] | None = None,
    snapshot_id: str | None = None,
    world_name: str = "world",
) -> SnapshotResult:
    """Take a snapshot of the world at ``world_dir`` into ``out_dir``.

    ``command`` is a callable that runs one console command on the server
    (``save-off``, ``save-all flush``, ``save-on``, ``version``). It is
    optional: with no server to talk to, the world's files are copied as
    they are on disk.

    The snapshot lands in ``<out_dir>/<snapshot_id>/`` and holds two things:
    ``world/`` (the copy) and ``manifest.json`` (what it says about
    itself).
    """
    source = Path(world_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"no world directory at {source}")

    identifier = snapshot_id or snapshot_id_for()
    store = Path(out_dir)
    directory = store / identifier
    if directory.exists():
        raise FileExistsError(f"there is already a snapshot at {directory}")
    snapshot_world = directory / world_name
    snapshot_world.mkdir(parents=True, exist_ok=False)

    timings: dict[str, float] = {}
    plans = plan_tree(source)
    section_of = {plan.relpath: plan.section for plan in plans}

    # -- the world stops moving ---------------------------------------------
    started = time.perf_counter()
    if command is not None:
        command("save-off")
    timings["save_off"] = time.perf_counter() - started

    started = time.perf_counter()
    if command is not None:
        command("save-all flush")
    timings["save_flush"] = time.perf_counter() - started

    # The ledger's head is read *here*, between the flush and the copy.
    # The flush is the moment the world's state is fixed on disk, so the
    # story up to this row is the story the snapshot holds. Reading it
    # after the copy would let a row count as part of the snapshot when
    # its block is not in it: a bot that placed a block between the
    # flush and the copy would have a row the restore then silently
    # drops.
    ledger: dict[str, Any] = {"path": str(ledger_path) if ledger_path else "", "seq": None}
    if ledger_path:
        head = ledger_head(ledger_path)
        ledger = {"path": head["path"], "seq": head["seq"], "at": head.get("at")}

    try:
        started = time.perf_counter()
        files, total = copy_tree(source, snapshot_world, plans=plans)
        timings["copy"] = time.perf_counter() - started

        started = time.perf_counter()
        entries = _hash_tree(snapshot_world, section_of)
        timings["hash"] = time.perf_counter() - started
    finally:
        # The saving goes back on whatever happened: a world left with
        # saving off is a world that will lose the next hour.
        if command is not None:
            try:
                command("save-on")
            except Exception:
                pass

    # -- what the snapshot says about itself ---------------------------------
    facts: dict[str, Any] = {}
    level = snapshot_world / "level.dat"
    if level.is_file():
        try:
            facts = level_facts(read_nbt(level))
        except Exception as error:
            facts = {"error": f"level.dat could not be read: {error}"}

    server = server_facts(command) if command is not None else {"available": False}

    # The console's version line mentions the *previous* build too, and
    # the Minecraft version it carries can be that older one. The build
    # that wrote the world says its own version in the world's own level
    # data ("Paper/26.1.2-74-e4e17fc (MC: 26.1.2)"), and that is the one
    # the world was written by.
    written = str(facts.get("server_version") or "")
    if "(MC:" in written:
        server["minecraft_version"] = written.split("(MC:", 1)[1].split(")", 1)[0].strip()

    # Two of the world's facts are the *server's* and are not in the
    # world's files in this Paper version: the seed (the world is grown
    # from it, but the level data does not carry it) and the time of day
    # (the level data carries the tick count, and the day cycle is the
    # server's own clock). They are asked of the server while it is up.
    if command is not None:
        seed_answer = command("seed")
        if "[" in seed_answer and "]" in seed_answer:
            try:
                facts["seed"] = int(seed_answer.split("[", 1)[1].split("]", 1)[0])
            except ValueError:
                pass
        # In this Paper version the day is a *timeline*: "time query day"
        # answers "Timeline minecraft:day is at 5039 tick(s)". The older
        # spelling is tried too, for a server that still has it.
        day_answer = command("time query day")
        if "tick" not in day_answer:
            day_answer = command("time query daytime")
        digits = "".join(character for character in day_answer if character.isdigit())
        if digits:
            facts["day_time"] = int(digits)
    taken_at = datetime.now(timezone.utc)
    sections = section_totals(entries)
    manifest = Manifest(
        snapshot_id=identifier,
        taken_at=taken_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        world_dir=str(source),
        server=server,
        world=facts,
        ledger=ledger,
        files=tuple(entries),
        skipped=tuple(
            {"path": plan.relpath, "reason": plan.reason}
            for plan in plans
            if not plan.include
        ),
        totals={"files": files, "bytes": total},
        sections=sections,
        timing=dict(timings),
    )

    started = time.perf_counter()
    write_manifest(manifest, directory / MANIFEST_NAME)
    timings["manifest"] = time.perf_counter() - started

    return SnapshotResult(manifest=manifest, directory=directory, timings=timings)
