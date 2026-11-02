"""Restoring a snapshot into a world — by swap, never by deletion.

The rule is the brief's: **the world the server is running is moved
aside, never deleted.** The live world directory becomes
``world.replaced-<timestamp>``, the snapshot's tree is copied into a new
``world``, and afterwards *both* are on disk: the moment that was restored
and the moment it replaced. A restore that cannot be undone is not a
restore, it is a mistake with a good name.

The order:

1. **stop** the server — a world cannot be swapped under a running server;
2. **move the old world aside** (never delete it);
3. **copy the snapshot's tree** into the new world directory;
4. **verify the hashes** — every restored file is checked against the
   manifest by content, so a copy that went wrong is caught before the
   world is started again;
5. **start** the server.

The copy is a plain file copy, not a hard link: a hard link would let the
restored world's writes reach back into the snapshot and change it, which
would make every later snapshot of that world quietly wrong.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .manifest import MANIFEST_NAME, Manifest, read_manifest, verify_directory
from .world import copy_tree

__all__ = ["RestoreResult", "restore", "world_aside_name"]


@dataclass
class RestoreResult:
    """What a restore produced."""

    manifest: Manifest
    new_world: Path
    previous_world: Path | None = None
    problems: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    stopped: bool = False
    started: bool = False
    siblings_moved: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        """True when every restored file hashed to what the manifest says."""
        return not self.problems

    def summary(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.manifest.snapshot_id,
            "new_world": str(self.new_world),
            "previous_world": str(self.previous_world) if self.previous_world else None,
            "verified": self.verified,
            "problems": list(self.problems),
            "stopped": self.stopped,
            "started": self.started,
            "siblings_moved": list(self.siblings_moved),
            "timings": self.timings,
        }


def world_aside_name(world_name: str, when: datetime | None = None) -> str:
    """The name the replaced world is kept under."""
    moment = when or datetime.now(timezone.utc)
    return f"{world_name}.replaced-{moment.strftime('%Y%m%dT%H%M%SZ')}"


def restore(
    server_dir: str | Path,
    snapshot_dir: str | Path,
    *,
    manifest: Manifest | None = None,
    stop: Callable[[], Any] | None = None,
    start: Callable[[], Any] | None = None,
    world_name: str = "world",
) -> RestoreResult:
    """Restore the snapshot at ``snapshot_dir`` into the server at ``server_dir``.

    ``stop`` and ``start`` are callables that stop and start the server.
    Both are optional: a restore can be done onto a server that is not
    running, and the verification is the same either way.
    """
    server = Path(server_dir)
    snapshot = Path(snapshot_dir)
    if manifest is None:
        manifest = read_manifest(snapshot / MANIFEST_NAME)
    snapshot_world = snapshot / world_name
    if not snapshot_world.is_dir():
        raise FileNotFoundError(f"the snapshot has no {world_name} directory: {snapshot_world}")

    timings: dict[str, float] = {}
    stopped = False
    started = False

    started_at = time.perf_counter()
    if stop is not None:
        stop()
        stopped = True
    timings["stop"] = time.perf_counter() - started_at

    live_world = server / world_name
    previous: Path | None = None
    started_at = time.perf_counter()
    if live_world.exists():
        aside = server / world_aside_name(world_name)
        shutil.move(str(live_world), str(aside))
        previous = aside
    # A server may keep **more** than one world directory beside the main
    # one — the old flat layout puts the nether and the end in
    # ``world_nether`` and ``world_the_end``, and a server that is
    # upgraded migrates them into ``world/dimensions``. Left in place,
    # the next start tries to migrate them into the world that was just
    # restored and refuses ("Refusing to overwrite existing migrated
    # file"), and the server crashes on start. They are moved aside with
    # the world, and the result says which ones.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    siblings: list[str] = []
    for sibling in sorted(server.glob(f"{world_name}_*")):
        if not sibling.is_dir():
            continue
        shutil.move(str(sibling), str(server / f"{sibling.name}.replaced-{stamp}"))
        siblings.append(sibling.name)
    timings["move_aside"] = time.perf_counter() - started_at

    started_at = time.perf_counter()
    live_world.mkdir(parents=True, exist_ok=True)
    copy_tree(snapshot_world, live_world)
    timings["copy"] = time.perf_counter() - started_at

    started_at = time.perf_counter()
    problems = verify_directory(live_world, manifest)
    timings["verify"] = time.perf_counter() - started_at

    started_at = time.perf_counter()
    if start is not None:
        start()
        started = True
    timings["start"] = time.perf_counter() - started_at

    return RestoreResult(
        manifest=manifest,
        new_world=live_world,
        previous_world=previous,
        problems=problems,
        timings=timings,
        stopped=stopped,
        started=started,
        siblings_moved=tuple(siblings),
    )
