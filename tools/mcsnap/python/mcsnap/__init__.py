"""``mcsnap`` — snapshot and restore a live Paper world, with a manifest.

Build #1 of ``docs/design/vibecode-in-world.md`` (§6.1 row 6): the missing
primitive. Everything in §2 that does not run on the Bevy world needs it —
the rewind, the scrubber's world view, the cherry-pick's preview, the
auto-pause's undo.

The four parts:

* :mod:`mcsnap.snapshot` — take a snapshot: stop the world's writing, flush
  it to disk, copy it, and write a manifest that says what the moment was;
* :mod:`mcsnap.restore` — put a snapshot back, by swapping the world aside
  (never by deleting it) and checking every restored file by its hash;
* :mod:`mcsnap.manifest` — the manifest itself: the files, their sizes and
  hashes, the server version, the world's tick, and the ledger row the
  moment sits behind;
* :mod:`mcsnap.server` — the private server this build runs against: its
  own port, its own loopback, its own memory lease.

The join to the world's story — the rewind point on the ledger, the nearest
snapshot at or before it, and the work that can be put back afterwards —
lives in :mod:`core.rewind.snapshot`, because that is the core's
vocabulary, not this tool's.
"""

from __future__ import annotations

from .ledger import ledger_head
from .manifest import (
    MANIFEST_NAME,
    FileEntry,
    Manifest,
    read_manifest,
    sha256_file,
    verify_directory,
    write_manifest,
)
from .nbt import level_facts, read_nbt
from .rcon import RconClient, RconError
from .restore import RestoreResult, restore, world_aside_name
from .server import PrivateServer, read_server_properties
from .snapshot import SnapshotResult, server_facts, snapshot_id_for, take_snapshot
from .world import SECTION_LABELS, FilePlan, classify, copy_tree, plan_tree

__all__ = [
    "FileEntry",
    "FilePlan",
    "MANIFEST_NAME",
    "Manifest",
    "PrivateServer",
    "RconClient",
    "RconError",
    "RestoreResult",
    "SECTION_LABELS",
    "SnapshotResult",
    "classify",
    "copy_tree",
    "ledger_head",
    "level_facts",
    "plan_tree",
    "read_manifest",
    "read_nbt",
    "read_server_properties",
    "restore",
    "server_facts",
    "sha256_file",
    "snapshot_id_for",
    "take_snapshot",
    "verify_directory",
    "world_aside_name",
    "write_manifest",
]
