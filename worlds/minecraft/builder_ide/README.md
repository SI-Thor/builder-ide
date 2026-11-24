# `worlds/minecraft/builder_ide` — the seam

The Minecraft world meets builder-ide here. It is a **seam**, not a copy:
nothing in this package re-implements builder-ide or the world, it only
translates between them.

## What it is

| module | what it owns |
|---|---|
| `ledger.py` | the world's log of record, written through builder-ide's core store (`CoreStoreLedger`), and the reader that reads that store back (`read_core_store_ledger`) |
| `skills.py` | the loader: the world's skills as builder-ide's tiles (`load_skills`, `load_tiles`, `tile_library`, `fold_world_library`) |

The mapping itself — what a skill *is* as a tile — is in
`agent_world_reflex.tiles`, beside the world's own records, because it is
a statement about the world and not about builder-ide.

## How to run its tests

```bash
# from the builder-ide root
pytest worlds/minecraft/tests/test_builder_ide_seam.py -q
```

They need nothing but the repository's own venv: `numpy`, `pydantic` and
`gymnasium` (the last one only for the two checks that read the log the
gym's way — those skip themselves when it is absent).

## What it stubs

Nothing. The seam has no mock world and no fake store: the tests build a
real `core.store.LedgerStore` on a temporary file and write real rows
into it.

## How it connects to the rest

### The ledger

`WorldLedger` takes a **door**:

```python
from agent_world_reflex.ledger import WorldLedger
from builder_ide.ledger import CoreStoreLedger
from core.store import LedgerStore
from core.artifacts import ArtifactStore

store = LedgerStore("/path/to/core.db", ArtifactStore("/path/to/artifacts"))
ledger = WorldLedger("/path/to/world.db", ledger=CoreStoreLedger(store))
ledger.authored(skill)     # → tile.authored in builder-ide's log
ledger.played(record)      # → tile.played in builder-ide's log
```

Without the door, the world writes its own SQLite file, exactly as it
did before the move. The rows are the same shape either way, so a file
written before the move still reads and a file written after it reads in
both vocabularies.

Two things the seam gets right, and both are about **not losing the
subject**:

- The core store persists a subject as `subject_kind` and `entity_id`
  and drops every other key. The world's old subject shape
  (`{"skill": ..., "family": ...}`) would have lost the skill id
  silently, so the world's ledger puts every subject into the core's
  shape on the way in — and **refuses** a subject with no id at all
  rather than guessing.
- The world's own keys (`skill_id`, `skill`, `role`, `api`, …) are kept
  beside the core's (`tile_id`, `play_id`, `scope`, …), so the drift
  seat, the rewind seat and the gym's recorder keep reading what they
  read before.

### The skills

```python
from builder_ide.skills import load_tiles, tile_library, fold_world_library

tiles = load_tiles("worlds/minecraft/reflex/skills/seed")
library = tile_library(tiles)          # builder-ide's own TileLibrary
library.require(tiles[0].id).words     # the world's vocabulary words
```

A skill and a capability are **one record**: the tile's id is the
skill's id (both are content addresses over the same source), the tile's
words are the skill's `api`, the tile's preconditions are the skill's
preconditions, and the world's prediction travels in the tile's
`provenance` — because a prediction is the *measure* of a play, not a
property of a capability.

The tile door is the world's door:
`agent_world_reflex.tiles.WorldVocabulary` answers builder-ide's
`VocabularyPort` from the world's closed vocabulary, so a tile that
names a word the world does not have is refused, not repaired.

The seed directory holds **65 files and 56 skills** — five scripts are
written more than once, and a skill is content addressed, so the same
script written twice is the same skill. That is the world's own rule.

## What must be checked on the Thor

The Thor is offline in this fold, so the live world was not run. What
the laptop cannot check is in `FOLD-REPORT.md` at the root of the
worktree: the world's ledger against the core store, the gym's reader
against the live log, and the ops scripts against the moved runtime
tree.
